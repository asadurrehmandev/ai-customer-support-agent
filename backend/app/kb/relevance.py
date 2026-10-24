"""Decide whether a retrieved chunk is strong enough to quote.

The legacy gate is a fixed cross-encoder cutoff. The calibrated gate is a
logistic regression fit on qa/dev_gate.json only. Its features are the
cross-encoder score, the gap to the next section, reciprocal-rank agreement
between BM25 and dense search, and a heading match. A duration question is
one feature, not a boost for a single article.

Bands:

- answer: quote the help center
- hedge: quote it, say the match is uncertain, and offer a person
- low: legacy only; do not guess
- none: the help center does not cover the question
"""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.textutil import content_tokens

# A single shared word (a product name in an unrelated question) is not enough
# to answer or to hand off. Two content words, or a very high cosine, are.
# Cross-encoder logits from ms-marco MiniLM. A clearly positive score means
# the passage answers the question. A strongly negative score means it does not,
# even when a couple of words overlap.
ANSWER_RERANK = 1.0
LOW_RERANK = -2.0


def overlap_count(query: str, text: str) -> int:
    return len(content_tokens(query) & content_tokens(text))


_DURATION_Q = re.compile(r"\bhow (?:long|many days|many hours|many weeks)\b", re.I)
_DURATION_A = re.compile(r"\b\d+\s+(?:day|days|hour|hours|week|weeks|business days)\b", re.I)


def _rerank_for_gate(query: str, text: str, rerank: float) -> float:
    if _DURATION_Q.search(query or "") and _DURATION_A.search(text or ""):
        return rerank + 6.0
    return rerank


def band(cosine: float, overlap: int, rerank: float = -10.0) -> str:
    if rerank >= ANSWER_RERANK:
        return "answer"
    if rerank >= -2 and overlap >= 2 and cosine >= 0.70:
        return "answer"
    if rerank <= -4 and overlap < 4:
        return "none"
    if rerank >= LOW_RERANK or cosine >= 0.72:
        return "low"
    return "none"


def hit_band(query: str, hit) -> str:
    blob = f"{hit.title} {hit.section} {hit.text}"
    overlap = overlap_count(query, blob)
    adjusted = _rerank_for_gate(query, hit.text, getattr(hit, "rerank", -10.0))
    return band(hit.cosine, overlap, adjusted)


def best_band(query: str, hits: list) -> str:
    ranks = {"none": 0, "low": 1, "answer": 2}
    current = "none"
    for hit in hits:
        found = hit_band(query, hit)
        if ranks[found] > ranks[current]:
            current = found
    return current


_MODEL_PATH = Path(__file__).resolve().parents[2].parent / "qa" / "dev_gate_model.json"
_MODEL: dict | None = None


def model_path() -> Path:
    return _MODEL_PATH


def load_model(force: bool = False) -> dict | None:
    global _MODEL
    if _MODEL is not None and not force:
        return _MODEL
    if not _MODEL_PATH.exists():
        _MODEL = None
        return None
    _MODEL = json.loads(_MODEL_PATH.read_text(encoding="utf-8"))
    return _MODEL


def feature_names() -> list[str]:
    model = load_model()
    if model and model.get("features"):
        return list(model["features"])
    return ["ce", "margin", "rrf", "heading", "agree", "overlap", "cosine", "duration"]


def feature_vector(query: str, hits: list) -> list[float]:
    """Signals for the top section. Ranks come from the hybrid index."""
    from app.kb.span import heading_overlap

    top = hits[0]
    margin = float(top.rerank) - (float(hits[1].rerank) if len(hits) > 1 else float(top.rerank))
    heading = heading_overlap(query, getattr(top, "title", ""), getattr(top, "section", ""))
    bm25_rank = int(getattr(top, "bm25_rank", 0) or 0)
    dense_rank = int(getattr(top, "dense_rank", 0) or 0)
    agree = 1.0 if bm25_rank and dense_rank and bm25_rank <= 3 and dense_rank <= 3 else 0.0
    blob = f"{getattr(top, 'title', '')} {getattr(top, 'section', '')} {getattr(top, 'text', '')}"
    overlap = float(overlap_count(query, blob))
    duration = 1.0 if _DURATION_Q.search(query or "") and _DURATION_A.search(getattr(top, "text", "") or "") else 0.0
    return [
        float(getattr(top, "rerank", -10.0)),
        float(margin),
        float(getattr(top, "rrf", 0.0) or 0.0),
        float(heading),
        agree,
        overlap,
        float(getattr(top, "cosine", 0.0)),
        duration,
    ]


def _sigmoid(value: float) -> float:
    if value > 30:
        return 1.0
    if value < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def probability(query: str, hits: list) -> float | None:
    model = load_model()
    if not model or not hits or getattr(hits[0], "rrf", None) is None:
        return None
    if not hasattr(hits[0], "bm25_rank"):
        return None
    mean = model["mean"]
    std = model["std"]
    coef = model["coef"]
    vector = feature_vector(query, hits)
    logit = float(model["intercept"])
    for weight, value, center, scale in zip(coef, vector, mean, std):
        denom = scale if scale else 1.0
        logit += float(weight) * ((value - center) / denom)
    return _sigmoid(logit)


@dataclass
class Gate:
    level: str
    probability: float | None


def legacy_level(query: str, hits: list) -> str:
    """The fixed cutoff, including the old duration fallback on the top hit."""
    if not hits:
        return "none"
    if any(hit_band(query, hit) == "answer" for hit in hits):
        return "answer"
    top = hits[0]
    if _DURATION_Q.search(query or "") and _DURATION_A.search(getattr(top, "text", "") or ""):
        adjusted = float(getattr(top, "rerank", -10.0)) + 6.0
        cosine = float(getattr(top, "cosine", 0.0))
        if adjusted >= 1.0 or (adjusted >= -1.0 and cosine >= 0.70) or (adjusted >= 0.5 and cosine >= 0.62):
            return "answer"
    if best_band(query, hits) == "low":
        return "low"
    return "none"


def _rule_level(vector: list[float], params: dict) -> str:
    ce, margin, _rrf, heading, agree, overlap, cosine, duration = vector
    if ce >= float(params["ce_hi"]):
        return "answer"
    if (
        duration
        and overlap >= 1
        and margin >= float(params["m_dur"])
        and ce >= float(params["ce_dur"])
        and cosine >= float(params["cos_dur"])
    ):
        return "answer"
    if (
        agree
        and margin >= float(params["m_ag"])
        and overlap >= float(params["ov_ag"])
        and ce >= float(params["ce_ag"])
        and cosine >= float(params["cos_ag"])
    ):
        return "answer"
    if (
        heading >= 1
        and agree
        and margin >= float(params["m_hd"])
        and overlap >= float(params["ov_hd"])
        and ce >= float(params["ce_hd"])
        and cosine >= float(params["cos_hd"])
    ):
        return "answer"
    if (
        overlap >= 2
        and margin >= float(params["m_he"])
        and ce >= float(params["ce_he"])
        and cosine >= float(params["cos_he"])
        and (heading >= 1 or agree)
    ):
        return "hedge"
    return "none"


def decide(query: str, hits: list) -> Gate:
    """Calibrated accept / hedge / abstain. Falls back to the legacy cutoff.

    The shipped gate is a decision rule fit on the dev set. A logistic
    regression on the same features was less accurate at the 1% false-answer cap.
    """
    if not hits:
        return Gate("none", None)
    if not hasattr(hits[0], "bm25_rank"):
        return Gate(legacy_level(query, hits), None)
    model = load_model()
    if not model or model.get("kind") != "rule":
        score = probability(query, hits)
        if score is None:
            return Gate(legacy_level(query, hits), None)
        t_answer = float(model.get("t_answer", 1.0))
        t_hedge = float(model.get("t_hedge", 1.0))
        if score >= t_answer:
            return Gate("answer", score)
        vector = feature_vector(query, hits)
        if (
            score >= t_hedge
            and (vector[3] >= 1 or vector[4] >= 1)
            and vector[1] >= float(model.get("hedge_min_margin", 0.5))
        ):
            return Gate("hedge", score)
        return Gate("none", score)
    vector = feature_vector(query, hits)
    return Gate(_rule_level(vector, model["params"]), None)
