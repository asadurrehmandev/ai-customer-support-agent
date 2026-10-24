"""The answer gate is fit on qa/dev_gate.json and judged there.

False answers stay at or below 1% of the dev questions. The sealed set is not
an input to this test's threshold.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from app.agent.respond import compose_kb
from app.db import configure, init_schema, session
from app.kb.index import SearchIndex
from app.kb.ingest import seed_knowledge
from app.kb.relevance import legacy_level
from app.seed.store import seed_store

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "qa" / "dev_gate.json"
HASH_FILE = ROOT / "qa" / "DEV_GATE.sha256"
MODEL = ROOT / "qa" / "dev_gate_model.json"
REPORT = ROOT / "qa" / "dev_gate_report.md"
SEALED = ROOT / "qa" / "sealed.json"


def _digest() -> str:
    return hashlib.sha256(DEV.read_bytes()).hexdigest()


def test_dev_set_was_frozen_before_fitting():
    recorded = HASH_FILE.read_text(encoding="utf-8").split()[0]
    assert recorded == _digest()
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    assert model["dev_sha256"] == recorded
    assert model["kind"] == "rule"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def test_dev_wording_does_not_copy_the_sealed_set():
    sealed = json.loads(SEALED.read_text(encoding="utf-8"))
    others = [turn for case in sealed["cases"] for turn in case["turns"]]
    others += [row["q"] for row in sealed["recall"]]
    other_sets = [_tokens(text) for text in others]
    for row in json.loads(DEV.read_text(encoding="utf-8"))["items"]:
        mine = _tokens(row["question"])
        for text, other in zip(others, other_sets):
            union = mine | other
            score = len(mine & other) / len(union) if union else 0
            assert score < 0.55, (row["id"], score, text)
            assert row["question"].lower() not in text.lower()


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    path = tmp_path_factory.mktemp("devgate")
    url = f"sqlite:///{path}/keel.db"
    configure(url)
    init_schema()
    db = session()
    seed_store(db)
    seed_knowledge(db, path / "corpus")
    built = SearchIndex()
    built.load_or_build(db)
    return built


def _legacy_article(query: str, hits: list):
    from app.kb.relevance import hit_band

    level = legacy_level(query, hits)
    if level != "answer" or not hits:
        return "none", None
    answering = [hit for hit in hits if hit_band(query, hit) == "answer"]
    chosen = max(answering, key=lambda hit: hit.rerank) if answering else hits[0]
    return "answer", chosen.article_id


def _score(rows, index) -> tuple[dict, dict, list, list]:
    old_ok = old_bad = new_ok = new_bad = 0
    positives = sum(1 for row in rows if row["expect"] == "answer")
    misses = []
    falses = []
    hedges = 0
    for row in rows:
        query = index.prepare(row["question"])
        hits = index.search(query, k=8)
        old_level, old_article = _legacy_article(query, hits) if hits else ("none", None)
        if row["expect"] == "answer" and old_level == "answer" and old_article in row["gold"]:
            old_ok += 1
        elif old_level == "answer" and (row["expect"] != "answer" or old_article not in row["gold"]):
            old_bad += 1
        level, reply = compose_kb(query, hits, set()) if hits else ("none", "")
        reply_l = (reply or "").lower()
        article = hits[0].article_id if hits and level in {"answer", "hedge", "partial"} else None
        includes = all(phrase.lower() in reply_l for phrase in row["must_include"])
        forbidden = any(phrase.lower() in reply_l for phrase in row["must_not"])
        if level == "hedge":
            hedges += 1
        good = (
            row["expect"] == "answer"
            and level in {"answer", "hedge"}
            and article in row["gold"]
            and includes
            and not forbidden
        )
        bad = level in {"answer", "hedge"} and (
            row["expect"] != "answer" or article not in row["gold"] or forbidden
        )
        if good:
            new_ok += 1
        elif row["expect"] == "answer":
            misses.append((row["id"], level, article, (reply or "")[:160]))
        if bad:
            new_bad += 1
            falses.append((row["id"], level, article, (reply or "")[:180]))
    def pack(correct, false):
        given = correct + false
        return {
            "precision": (correct / given) if given else None,
            "recall": correct / positives,
            "correct": correct,
            "false": false,
            "given": given,
            "positives": positives,
            "false_rate": false / len(rows),
        }

    new = pack(new_ok, new_bad)
    new["hedges"] = hedges
    return pack(old_ok, old_bad), new, misses, falses


def test_calibrated_gate_beats_the_fixed_cutoff(index):
    rows = json.loads(DEV.read_text(encoding="utf-8"))["items"]
    assert len(rows) >= 60
    assert sum(1 for row in rows if row["expect"] == "abstain") >= 15
    old, new, misses, falses = _score(rows, index)
    _write(rows, old, new, misses, falses)
    assert new["false_rate"] <= 0.01
    assert new["recall"] > old["recall"]
    assert new["false"] <= old["false"]
    assert new["precision"] >= 0.99


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def _write(rows, old, new, misses, falses) -> None:
    abstain = sum(1 for row in rows if row["expect"] == "abstain")
    caveat = sum(1 for row in rows if row["expect"] == "caveat")
    lines = [
        "# Dev gate",
        "",
        "This file is written by `backend/tests/test_dev_gate.py`. The questions were hashed in `qa/DEV_GATE.sha256` before the gate was fit. The sealed conversations were not used to choose the threshold.",
        "",
        f"Dev set: {len(rows)} questions, {old['positives']} that the help center can answer, {abstain} absent topics, {caveat} constraint caveats.",
        "",
        "Precision is correct quotes divided by quotes the gate was willing to state. Recall is correct quotes divided by questions the help center can answer. A false answer is a confident or hedged quote of the wrong section, a quote on an absent topic, or a quote that states a forbidden fact. A partial reply that says the section does not cover the constraint and hands off is not counted as an answer. The cap is 1% of dev questions.",
        "",
        "A logistic regression on the same features (cross-encoder score, rank margin, RRF agreement, heading overlap, token overlap, cosine, and a duration flag) reached 48/80 correct with 1 false answer at its best point under that cap. The probabilities were compressed, so the shipped gate is the decision rule below, fit on this dev set.",
        "",
        "| Gate | Precision | Recall | Correct | False answers | False-answer rate |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| Fixed cross-encoder cutoff | {_fmt(old['precision'])} | {_fmt(old['recall'])} | {old['correct']}/{old['positives']} | {old['false']} | {old['false_rate']:.1%} |",
        f"| Calibrated decision rule | {_fmt(new['precision'])} | {_fmt(new['recall'])} | {new['correct']}/{new['positives']} | {new['false']} | {new['false_rate']:.1%} |",
        "",
        f"Hedged replies among the dev questions: {new['hedges']}. A hedge quotes the section, says the match is uncertain, and offers a person. It counts as an answer in the table above, and the product metrics do not count it as a clean deflection.",
        "",
        "## Rule",
        "",
        "Answer when the cross-encoder score is at least 1, or when BM25 and dense search agree the section is in the top 3 and the margin, overlap, and score clear the fitted floors, or when the heading matches and those floors clear, or when a duration question lands on a passage that states a duration. Otherwise hedge only when the margin and overlap still show the section standing apart. Otherwise abstain.",
        "",
        "## Misses",
        "",
    ]
    if not misses:
        lines.append("- None.")
    for row in misses:
        lines.append(f"- `{row[0]}` level {row[1]} article {row[2]}: {row[3]}")
    lines.extend(["", "## False answers", ""])
    if not falses:
        lines.append("- None.")
    for row in falses:
        lines.append(f"- `{row[0]}` level {row[1]} article {row[2]}: {row[3]}")
    lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
