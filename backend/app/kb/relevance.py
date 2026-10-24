"""Decide whether a retrieved chunk is strong enough to quote.

Cosine similarity on bge-small is the main signal. Token overlap keeps a
semantically nearby but topically wrong article from being quoted. Bands:

- answer: quote the help center
- low: do not guess; hand off
- none: the help center does not cover the question
"""

from app.textutil import content_tokens

# A single shared word (a product name in an unrelated question) is not enough
# to answer or to hand off. Two content words, or a very high cosine, are.
ANSWER_OVERLAP = 2
ANSWER_OVERLAP_COSINE = 0.28
ANSWER_COSINE = 0.74
LOW_OVERLAP = 2
LOW_OVERLAP_COSINE = 0.20
LOW_COSINE = 0.70


def overlap_count(query: str, text: str) -> int:
    return len(content_tokens(query) & content_tokens(text))


def band(cosine: float, overlap: int) -> str:
    if overlap >= 3 and cosine >= 0.22:
        return "answer"
    if overlap >= ANSWER_OVERLAP and cosine >= ANSWER_OVERLAP_COSINE:
        return "answer"
    if cosine >= ANSWER_COSINE:
        return "answer"
    if overlap >= LOW_OVERLAP and cosine >= LOW_OVERLAP_COSINE:
        return "low"
    if cosine >= LOW_COSINE:
        return "low"
    return "none"


def best_band(query: str, hits: list) -> str:
    ranks = {"none": 0, "low": 1, "answer": 2}
    current = "none"
    for hit in hits:
        overlap = overlap_count(query, f"{hit.title} {hit.section} {hit.text}")
        found = band(hit.cosine, overlap)
        if ranks[found] > ranks[current]:
            current = found
    return current
