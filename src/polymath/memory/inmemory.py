"""In-process knowledge store (tests, ``--memory`` runs). Lexical search is Okapi BM25."""

from __future__ import annotations

import math
import re
from collections import Counter

from polymath.memory.embeddings import cosine
from polymath.memory.models import (
    ChunkRecord,
    PaperRecord,
    RunRecord,
    ScoredChunk,
    StoredClaim,
)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    ]
)


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def bm25_scores(query: str, docs: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    tokenised = [tokens(d) for d in docs]
    n = len(tokenised)
    avg = sum(map(len, tokenised)) / n if n else 0.0
    df: Counter[str] = Counter(t for doc in tokenised for t in set(doc))
    scores = []
    for doc in tokenised:
        tf = Counter(doc)
        s = 0.0
        for term in set(tokens(query)):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / (avg or 1)))
        scores.append(s)
    return scores


class InMemoryKnowledgeStore:
    def __init__(self) -> None:
        self.papers: dict[str, PaperRecord] = {}
        self.chunks: dict[str, ChunkRecord] = {}
        self.vectors: dict[str, list[float]] = {}
        self.runs: dict[str, RunRecord] = {}
        self.claims: dict[str, tuple[StoredClaim, list[float]]] = {}

    async def setup(self) -> None:
        return None

    async def upsert_paper(self, paper: PaperRecord) -> None:
        self.papers[paper.key] = paper

    async def has_chunks(self, paper_key: str) -> bool:
        return any(c.paper_key == paper_key for c in self.chunks.values())

    async def add_chunks(self, chunks: list[ChunkRecord], vectors: list[list[float]]) -> None:
        for c, v in zip(chunks, vectors, strict=True):
            self.chunks[c.id], self.vectors[c.id] = c, v

    async def paper(self, paper_key: str) -> PaperRecord | None:
        return self.papers.get(paper_key)

    async def paper_text(self, paper_key: str) -> str:
        parts = sorted((c for c in self.chunks.values() if c.paper_key == paper_key),
                       key=lambda c: c.ord)  # fmt: skip
        return "\n".join(c.text for c in parts)

    async def lexical(self, query: str, k: int) -> list[ScoredChunk]:
        items = list(self.chunks.values())
        scored = zip(items, bm25_scores(query, [c.text for c in items]), strict=True)
        ranked = sorted((p for p in scored if p[1] > 0), key=lambda p: -p[1])[:k]
        return [ScoredChunk(chunk=c, score=s, sources=["lexical"]) for c, s in ranked]

    async def vector(self, query_vec: list[float], k: int) -> list[ScoredChunk]:
        ranked = sorted(
            ((c, cosine(query_vec, self.vectors[c.id])) for c in self.chunks.values()),
            key=lambda p: -p[1],
        )[:k]
        return [ScoredChunk(chunk=c, score=s, sources=["vector"]) for c, s in ranked]

    async def record_run(self, run: RunRecord, vector: list[float]) -> None:
        self.runs[run.run_id] = run

    async def add_claims(self, claims: list[StoredClaim], vectors: list[list[float]]) -> None:
        for sc, v in zip(claims, vectors, strict=True):
            self.claims[sc.claim.id] = (sc, v)

    async def similar_claims(
        self, query_vec: list[float], k: int, statuses: tuple[str, ...]
    ) -> list[tuple[StoredClaim, float]]:
        hits = [
            (sc, cosine(query_vec, v))
            for sc, v in self.claims.values()
            if sc.claim.status.value in statuses
        ]
        return sorted(hits, key=lambda p: -p[1])[:k]
