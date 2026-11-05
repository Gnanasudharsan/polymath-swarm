"""Hybrid retrieval: lexical (BM25 / Postgres FTS) + dense vectors, fused with reciprocal rank
fusion, then reranked by a cross-encoder."""

from __future__ import annotations

from typing import Literal

from polymath.memory.embeddings import Embedder, Reranker
from polymath.memory.models import KnowledgeStore, ScoredChunk

Mode = Literal["lexical", "vector", "hybrid", "hybrid_rerank"]
RRF_K = 60


def rrf(rankings: list[list[ScoredChunk]], k: int = RRF_K) -> list[ScoredChunk]:
    """Reciprocal rank fusion: score = Σ 1 / (k + rank)."""
    fused: dict[str, ScoredChunk] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            cid = hit.chunk.id
            prev = fused.get(cid)
            score = (prev.score if prev else 0.0) + 1.0 / (k + rank)
            sources = sorted({*(prev.sources if prev else []), *hit.sources})
            fused[cid] = ScoredChunk(chunk=hit.chunk, score=score, sources=sources)
    return sorted(fused.values(), key=lambda h: -h.score)


class HybridRetriever:
    def __init__(
        self,
        store: KnowledgeStore,
        embedder: Embedder,
        reranker: Reranker | None = None,
        *,
        candidates: int = 40,
        rerank_top: int = 25,
    ) -> None:
        self.store, self.embedder, self.reranker = store, embedder, reranker
        self.candidates, self.rerank_top = candidates, rerank_top

    async def search(
        self, query: str, k: int = 10, mode: Mode = "hybrid_rerank"
    ) -> list[ScoredChunk]:
        lexical = vector = []
        if mode in ("lexical", "hybrid", "hybrid_rerank"):
            lexical = await self.store.lexical(query, self.candidates)
        if mode in ("vector", "hybrid", "hybrid_rerank"):
            qvec = await self.embedder.embed_query(query)
            vector = await self.store.vector(qvec, self.candidates)
        if mode == "lexical":
            return lexical[:k]
        if mode == "vector":
            return vector[:k]
        fused = rrf([lexical, vector])
        if mode == "hybrid" or self.reranker is None:
            return fused[:k]
        head = fused[: self.rerank_top]
        scores = await self.reranker.scores(query, [h.chunk.text for h in head])
        reranked = [
            ScoredChunk(chunk=h.chunk, score=s, sources=[*h.sources, "rerank"])
            for h, s in sorted(zip(head, scores, strict=True), key=lambda p: -p[1])
        ]
        return reranked[:k]
