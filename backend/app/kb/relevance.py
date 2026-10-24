"""Decide whether a retrieved chunk is strong enough to quote.

The cross-encoder is the main signal. Token overlap keeps a nearby but
off-topic article from being quoted. A duration question ("how long",
"how many days") also looks for a passage that states a number of days
or hours. That is a question shape, not a boost for one article.

Bands:

- answer: quote the help center
- low: do not guess; hand off
- none: the help center does not cover the question
"""

import re

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
