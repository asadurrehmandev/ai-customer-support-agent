"""Hybrid search: BM25, bge-small embeddings, then a cross-encoder rerank."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk

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
        }


class SearchIndex:
    def __init__(self):
        self.chunks: list[Chunk] = []
        self.matrix: np.ndarray | None = None
        self._bm25: BM25Okapi | None = None

    def load_or_build(self, session: Session) -> None:
        rows = list(session.scalars(select(Chunk).order_by(Chunk.article_id, Chunk.position)).all())
        missing = [row for row in rows if not row.embedding]
        if missing:
            vectors = embed_passages([row.embed_text for row in missing])
            for row, vector in zip(missing, vectors):
                row.embedding = np.asarray(vector, dtype=np.float32).tobytes()
            session.commit()
        self.chunks = rows
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
        tokens = tokenize(query)
        bm25 = np.asarray(self._bm25.get_scores(tokens if tokens else [""]), dtype=np.float64)
        query_vector = embed_query(query)
        query_norm = query_vector / (np.linalg.norm(query_vector) + 1e-9)
        matrix_norm = self.matrix / (np.linalg.norm(self.matrix, axis=1, keepdims=True) + 1e-9)
        cosine = matrix_norm @ query_norm
        bm25_norm = bm25 / (bm25.max() + 1e-9) if float(bm25.max()) > 0 else bm25
        cosine_norm = (cosine + 1) / 2
        fused = 0.45 * bm25_norm + 0.55 * cosine_norm
        take = min(20, len(self.chunks))
        order = np.argsort(-fused)[:take]
        documents = [self.chunks[int(i)].embed_text for i in order]
        rerank_scores = _rerank(query, documents)
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
        for rerank, chunk_index, fused_score, bm25_score, cosine_score in ranked[:k]:
            chunk = self.chunks[chunk_index]
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
                )
            )
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
    def search(self, query: str, k: int = 5) -> list[Hit]:
        del query, k
        return []
