"""Episodic memory: past runs and their claims, so later runs can reuse verified lemmas."""

from __future__ import annotations

from polymath.core.models import Claim, ClaimStatus, Problem
from polymath.memory.embeddings import Embedder
from polymath.memory.models import KnowledgeStore, RunRecord, StoredClaim


class EpisodicMemory:
    def __init__(self, store: KnowledgeStore, embedder: Embedder, *, min_similarity: float) -> None:
        self.store, self.embedder, self.min_similarity = store, embedder, min_similarity

    async def record_run(
        self, run_id: str, problem: Problem, status: str, answer: str,
        claims: list[Claim], report: dict[str, object] | None = None,
    ) -> int:  # fmt: skip
        """Store the run and every claim it produced (verified ones are reusable later)."""
        (pvec,) = await self.embedder.embed([problem.statement])
        await self.store.record_run(
            RunRecord(run_id=run_id, problem=problem.statement, status=status, answer=answer,
                      report=dict(report or {})),
            pvec,
        )  # fmt: skip
        if not claims:
            return 0
        vectors = await self.embedder.embed([c.statement for c in claims])
        stored = [StoredClaim(claim=c, run_id=run_id, problem=problem.statement) for c in claims]
        await self.store.add_claims(stored, vectors)
        return len(stored)

    async def reusable_claims(
        self, problem: Problem, k: int = 5
    ) -> list[tuple[StoredClaim, float]]:
        """Verified claims from earlier runs that are relevant to ``problem``."""
        (qvec,) = await self.embedder.embed([problem.statement])
        hits = await self.store.similar_claims(qvec, k, (ClaimStatus.VERIFIED.value,))
        return [(sc, sim) for sc, sim in hits if sim >= self.min_similarity]
