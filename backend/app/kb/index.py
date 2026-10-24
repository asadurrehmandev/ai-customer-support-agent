"""Hybrid search: BM25, bge-small embeddings, then a cross-encoder rerank."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk
from app.textutil import correct_tokens, fold_numbers

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

_embedder = None
_reranker = None


def embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(EMBED_MODEL)
    return _embedder


def reranker():
    global _reranker
    if _reranker is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        _reranker = TextCrossEncoder(model_name=RERANK_MODEL)
    return _reranker


def embed_passages(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    vectors = [np.asarray(vector, dtype=np.float32) for vector in embedder().embed(texts)]
    return np.vstack(vectors)


def embed_query(text: str) -> np.ndarray:
    return embed_passages([QUERY_PREFIX + text])[0]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


@dataclass
class Hit:
    article_id: str
    title: str
    section: str
    text: str
    cosine: float
    bm25: float
    fused: float
    rerank: float
    bm25_rank: int = 0
    dense_rank: int = 0
    rrf: float = 0.0

    def public(self) -> dict:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "section": self.section,
            "text": self.text,
            "cosine": round(float(self.cosine), 4),
            "bm25": round(float(self.bm25), 4),
            "fused": round(float(self.fused), 4),
            "rerank": round(float(self.rerank), 4),
            "bm25_rank": int(self.bm25_rank),
            "dense_rank": int(self.dense_rank),
            "rrf": round(float(self.rrf), 6),
        }


class SearchIndex:
    def __init__(self):
        self.chunks: list[Chunk] = []
        self.matrix: np.ndarray | None = None
        self._bm25: BM25Okapi | None = None
        self.vocab: set[str] = set()

    def prepare(self, query: str) -> str:
        folded = fold_numbers(query or "")
        return correct_tokens(folded, self.vocab)

    def load_or_build(self, session: Session) -> None:
        rows = list(session.scalars(select(Chunk).order_by(Chunk.article_id, Chunk.position)).all())
        missing = [row for row in rows if not row.embedding]
        if missing:
            vectors = embed_passages([row.embed_text for row in missing])
            for row, vector in zip(missing, vectors):
                row.embedding = np.asarray(vector, dtype=np.float32).tobytes()
            session.commit()
        self.chunks = rows
        self.vocab = set()
        for row in rows:
            self.vocab.update(tokenize(row.text))
            self.vocab.update(tokenize(row.title))
        if not rows:
            self.matrix = None
            self._bm25 = None
            return
        stacked = [np.frombuffer(row.embedding, dtype=np.float32) for row in rows]
        self.matrix = np.vstack(stacked)
        self._bm25 = BM25Okapi([tokenize(row.embed_text) for row in rows])

    def search(self, query: str, k: int = 5) -> list[Hit]:
        if not self.chunks or self.matrix is None or self._bm25 is None:
            return []
        query = self.prepare(query)
        tokens = tokenize(query)
        bm25 = np.asarray(self._bm25.get_scores(tokens if tokens else [""]), dtype=np.float64)
        query_vector = embed_query(query)
        query_norm = query_vector / (np.linalg.norm(query_vector) + 1e-9)
        matrix_norm = self.matrix / (np.linalg.norm(self.matrix, axis=1, keepdims=True) + 1e-9)
        cosine = matrix_norm @ query_norm
        bm25_norm = bm25 / (bm25.max() + 1e-9) if float(bm25.max()) > 0 else bm25
        cosine_norm = (cosine + 1) / 2
        fused = 0.45 * bm25_norm + 0.55 * cosine_norm
        # The help center is small enough to rerank the fused pool in full.
        # A 20-hit cutoff was dropping the passage that actually answered.
        take = len(self.chunks) if len(self.chunks) <= 400 else 80
        order = np.argsort(-fused)[:take]
        documents = [self.chunks[int(i)].embed_text for i in order]
        rerank_scores = _rerank(query, documents)
        section_bm25: dict[tuple[str, str], float] = {}
        section_dense: dict[tuple[str, str], float] = {}
        for index, chunk in enumerate(self.chunks):
            key = (chunk.article_id, chunk.section)
            section_bm25[key] = max(section_bm25.get(key, float("-inf")), float(bm25[index]))
            section_dense[key] = max(section_dense.get(key, float("-inf")), float(cosine[index]))
        bm25_order = sorted(section_bm25, key=lambda key: (-section_bm25[key], key))
        dense_order = sorted(section_dense, key=lambda key: (-section_dense[key], key))
        bm25_rank = {key: rank for rank, key in enumerate(bm25_order, 1)}
        dense_rank = {key: rank for rank, key in enumerate(dense_order, 1)}
        # Reciprocal rank fusion of the two retrievers. k=60 is the usual constant.
        rrf_score = {
            key: (1.0 / (60 + bm25_rank[key])) + (1.0 / (60 + dense_rank[key])) for key in bm25_rank
        }
        ranked = []
        for local_index, chunk_index in enumerate(order):
            ranked.append(
                (
                    float(rerank_scores[local_index]),
                    int(chunk_index),
                    float(fused[int(chunk_index)]),
                    float(bm25[int(chunk_index)]),
                    float(cosine[int(chunk_index)]),
                )
            )
        ranked.sort(key=lambda item: -item[0])
        hits: list[Hit] = []
        seen: set[tuple[str, str]] = set()
        for rerank, chunk_index, fused_score, bm25_score, cosine_score in ranked:
            chunk = self.chunks[chunk_index]
            key = (chunk.article_id, chunk.section)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                Hit(
                    article_id=chunk.article_id,
                    title=chunk.title,
                    section=chunk.section,
                    text=chunk.text,
                    cosine=cosine_score,
                    bm25=bm25_score,
                    fused=fused_score,
                    rerank=rerank,
                    bm25_rank=bm25_rank.get(key, 0),
                    dense_rank=dense_rank.get(key, 0),
                    rrf=rrf_score.get(key, 0.0),
                )
            )
            if len(hits) == k:
                break
        return hits


def _rerank(query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    try:
        raw = list(reranker().rerank(query, documents))
    except Exception:
        return [0.0] * len(documents)
    if not raw:
        return [0.0] * len(documents)
    first = raw[0]
    if hasattr(first, "score") and hasattr(first, "index"):
        scores = [0.0] * len(documents)
        for item in raw:
            scores[int(item.index)] = float(item.score)
        return scores
    if isinstance(first, tuple) and len(first) == 2 and isinstance(first[0], int):
        scores = [0.0] * len(documents)
        for index, score in raw:
            scores[int(index)] = float(score)
        return scores
    return [float(score) for score in raw]


class NullIndex:
    def prepare(self, query: str) -> str:
        return fold_numbers(query or "")

    def search(self, query: str, k: int = 5) -> list[Hit]:
        del query, k
        return []
