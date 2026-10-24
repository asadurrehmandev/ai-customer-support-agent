#!/usr/bin/env python3
"""Fit the answer gate on qa/dev_gate.json. Does not read the sealed set."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("FASTEMBED_CACHE_PATH", str(Path(__file__).resolve().parents[2] / ".cache" / "fastembed"))

from app.agent.respond import compose_kb
from app.db import configure, init_schema, session
from app.kb.index import SearchIndex
from app.kb.ingest import seed_knowledge
from app.kb.relevance import feature_vector, legacy_level, load_model
from app.kb import relevance
from app.seed.store import seed_store

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "qa" / "dev_gate.json"
MODEL = ROOT / "qa" / "dev_gate_model.json"
REPORT = ROOT / "qa" / "dev_gate_report.md"


def build_index():
    url = "sqlite:////tmp/keel-dev-gate.db"
    Path("/tmp/keel-dev-gate.db").unlink(missing_ok=True)
    configure(url)
    init_schema()
    db = session()
    seed_store(db)
    seed_knowledge(db, Path("/tmp/keel-dev-corpus"))
    index = SearchIndex()
    index.load_or_build(db)
    return index


def legacy_article(query: str, hits: list) -> tuple[str, str | None]:
    from app.kb.relevance import hit_band

    level = legacy_level(query, hits)
    if level != "answer" or not hits:
        return level, None
    answering = [hit for hit in hits if hit_band(query, hit) == "answer"]
    chosen = max(answering, key=lambda hit: hit.rerank) if answering else hits[0]
    return "answer", chosen.article_id


def judge(row: dict, level: str, article: str | None, reply: str) -> tuple[bool, bool]:
    reply_l = (reply or "").lower()
    includes = all(phrase.lower() in reply_l for phrase in row["must_include"])
    forbidden = any(phrase.lower() in reply_l for phrase in row["must_not"])
    caveat = any(phrase in reply_l for phrase in ("doesn't cover", "does not cover", "not covered", "rather than guessing"))
    expect = row["expect"]
    gold = set(row["gold"])
    if expect == "answer":
        ok = level in {"answer", "hedge"} and article in gold and includes and not forbidden
        false = level in {"answer", "hedge", "partial"} and (article not in gold or forbidden)
        return ok, false
    if expect == "abstain":
        return False, level in {"answer", "hedge", "partial"}
    false = (level in {"answer", "hedge"} and not caveat) or forbidden
    return False, false


def rates(rows, judged) -> dict:
    answers = 0
    correct = 0
    false = 0
    positives = sum(1 for row in rows if row["expect"] == "answer")
    for row, (ok, bad) in zip(rows, judged):
        if ok:
            correct += 1
        if bad:
            false += 1
        if row["expect"] == "answer" and ok:
            answers += 1
    given = correct + false
    return {
        "precision": (correct / given) if given else None,
        "recall": (correct / positives) if positives else None,
        "correct": correct,
        "false": false,
        "given": given,
        "positives": positives,
        "false_rate": false / len(rows),
    }


def fit_logistic(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    weight = np.where(y > 0.5, 1.0, 4.0)
    coef = np.zeros(x.shape[1])
    intercept = 0.0
    for _ in range(5000):
        logit = np.clip(x @ coef + intercept, -30, 30)
        prob = 1.0 / (1.0 + np.exp(-logit))
        error = (prob - y) * weight
        coef -= 0.15 * (x.T @ error / weight.sum() + 1.5 * coef)
        intercept -= 0.15 * float(error.sum() / weight.sum())
    return coef, float(intercept)


def main() -> None:
    payload = json.loads(DEV.read_text(encoding="utf-8"))
    rows = payload["items"]
    index = build_index()
    prepared = []
    matrix = []
    labels = []
    for row in rows:
        query = index.prepare(row["question"])
        hits = index.search(query, k=8)
        prepared.append((query, hits))
        if hits:
            matrix.append(feature_vector(query, hits))
            top_ok = row["expect"] == "answer" and hits[0].article_id in row["gold"]
            labels.append(1.0 if top_ok else 0.0)
        else:
            matrix.append([0.0] * 8)
            labels.append(0.0)
    raw = np.asarray(matrix, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    mean = raw.mean(axis=0)
    std = raw.std(axis=0)
    std[std < 1e-6] = 1.0
    scaled = (raw - mean) / std
    coef, intercept = fit_logistic(scaled, y)

    def activate(t_answer: float, t_hedge: float, min_margin: float) -> None:
        relevance._MODEL = {
            "features": ["ce", "margin", "rrf", "heading", "agree", "overlap", "cosine", "duration"],
            "mean": mean.tolist(),
            "std": std.tolist(),
            "coef": coef.tolist(),
            "intercept": intercept,
            "t_answer": t_answer,
            "t_hedge": t_hedge,
            "hedge_min_margin": min_margin,
        }

    best = None
    for t_answer in np.round(np.arange(0.45, 0.96, 0.02), 2):
        for t_hedge in np.round(np.arange(0.15, t_answer, 0.05), 2):
            for min_margin in (0.4, 1.0, 2.0):
                activate(float(t_answer), float(t_hedge), float(min_margin))
                judged = []
                for row, (query, hits) in zip(rows, prepared):
                    if not hits:
                        judged.append((False, False))
                        continue
                    level, reply = compose_kb(query, hits, set())
                    article = hits[0].article_id if level in {"answer", "hedge", "partial"} else None
                    judged.append(judge(row, level, article, reply or ""))
                summary = rates(rows, judged)
                if summary["false_rate"] > 0.01:
                    continue
                key = (summary["correct"], -summary["false"], summary["precision"] or 0)
                if best is None or key > best[0]:
                    best = (key, float(t_answer), float(t_hedge), float(min_margin), summary, judged)

    if best is None:
        raise SystemExit("No threshold kept false answers at or below 1%.")
    _, t_answer, t_hedge, min_margin, summary, judged = best
    activate(t_answer, t_hedge, min_margin)
    dev_hash = (ROOT / "qa" / "DEV_GATE.sha256").read_text(encoding="utf-8").split()[0]
    model = relevance._MODEL | {"dev_sha256": dev_hash}
    MODEL.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    load_model(force=True)

    old_judged = []
    for row, (query, hits) in zip(rows, prepared):
        if not hits:
            old_judged.append((False, False))
            continue
        level, article = legacy_article(query, hits)
        # The legacy gate quoted the whole section, so article match is the score.
        reply = hits[0].text if article else ""
        old_judged.append(judge({**row, "must_include": [], "must_not": []}, level if level != "low" else "none", article, reply if level == "answer" else ""))
    # Recompute old with a dedicated judge that ignores span phrases.
    old_clean = []
    for row, (query, hits) in zip(rows, prepared):
        level, article = legacy_article(query, hits) if hits else ("none", None)
        if row["expect"] == "answer":
            ok = level == "answer" and article in row["gold"]
            bad = level == "answer" and article not in row["gold"]
        elif row["expect"] == "abstain":
            ok = False
            bad = level == "answer"
        else:
            ok = False
            bad = level == "answer"
        old_clean.append((ok, bad))
    old = rates(rows, old_clean)
    new = summary
    misses = []
    falses = []
    for row, (query, hits), (ok, bad) in zip(rows, prepared, judged):
        level, reply = compose_kb(query, hits, set()) if hits else ("none", "")
        article = hits[0].article_id if hits and level in {"answer", "hedge", "partial"} else None
        if bad:
            falses.append((row["id"], level, article, (reply or "")[:180]))
        elif row["expect"] == "answer" and not ok:
            misses.append((row["id"], level, article, (reply or "")[:140]))
    lines = [
        "# Dev gate",
        "",
        f"Dev set `{dev_hash}` ({len(rows)} questions, {sum(1 for row in rows if row['expect']=='answer')} should be answered, {sum(1 for row in rows if row['expect']=='abstain')} absent topics, {sum(1 for row in rows if row['expect']=='caveat')} constraint caveats).",
        "",
        "Precision is correct quotes divided by quotes given. Recall is correct quotes divided by questions the help center answers. A false answer is a quote of the wrong section, a quote on an absent topic, or a confident quote that states a forbidden fact. The limit is 1% of dev questions.",
        "",
        "| Gate | Precision | Recall | Correct | False answers | False-answer rate |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| Fixed cross-encoder cutoff | {_fmt(old['precision'])} | {_fmt(old['recall'])} | {old['correct']}/{old['positives']} | {old['false']} | {old['false_rate']:.1%} |",
        f"| Calibrated gate | {_fmt(new['precision'])} | {_fmt(new['recall'])} | {new['correct']}/{new['positives']} | {new['false']} | {new['false_rate']:.1%} |",
        "",
        f"Answer threshold {t_answer}, hedge threshold {t_hedge}, hedge minimum margin {min_margin}.",
        "",
        "## Misses",
        "",
    ]
    for row in misses:
        lines.append(f"- `{row[0]}` level {row[1]} article {row[2]}: {row[3]}")
    lines.append("")
    lines.append("## False answers")
    lines.append("")
    if not falses:
        lines.append("- None.")
    for row in falses:
        lines.append(f"- `{row[0]}` level {row[1]} article {row[2]}: {row[3]}")
    lines.append("")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"old": old, "new": new, "t_answer": t_answer, "t_hedge": t_hedge, "min_margin": min_margin}, indent=2))
    print("misses", len(misses), "false", len(falses))
    for row in falses:
        print("FALSE", row[0], row[1], row[2])
    for row in misses[:25]:
        print("MISS", row[0], row[1], row[2])


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


if __name__ == "__main__":
    main()
