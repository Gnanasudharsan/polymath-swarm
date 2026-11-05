"""Memory on Postgres + pgvector with the real local embedder and reranker."""

from __future__ import annotations

import psycopg
import pytest

from polymath.core.config import Settings
from polymath.core.models import AgentRole, ClaimStatus, Problem
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from polymath.memory.embeddings import CrossEncoderReranker, FastEmbedder
from polymath.memory.episodic import EpisodicMemory
from polymath.memory.evaluation import evaluate, index_corpus, load_dataset
from polymath.memory.ingest import Ingestor
from polymath.memory.knowledge import open_knowledge
from polymath.memory.pg import PgKnowledgeStore, make_pool
from polymath.memory.retrieval import HybridRetriever
from tests.swarm_fakes import FixedPlanner, make_factory
from tests.unit.memory.test_lemma_reuse import LEMMA, Prover, plan

pytestmark = pytest.mark.integration


async def test_retrieval_eval_meets_recall_target(infra_settings: Settings) -> None:
    s = infra_settings
    embedder = FastEmbedder(s.embedding_model, s.model_cache_dir, s.embedding_dim)
    pool = make_pool(s.postgres_dsn)
    await pool.open()
    try:
        store = PgKnowledgeStore(pool, s.postgres_dsn, s.embedding_dim)
        await store.setup()
        corpus, queries = load_dataset()
        await index_corpus(Ingestor(store, embedder), corpus)
        retriever = HybridRetriever(
            store, embedder, CrossEncoderReranker(s.rerank_model or "", s.model_cache_dir)
        )
        metrics = await evaluate(retriever, queries, "hybrid_rerank")
    finally:
        await pool.close()
    assert metrics.recall_at[10] >= 0.8, metrics
    assert metrics.mrr >= 0.8, metrics


async def test_related_problem_reuses_lemma_from_postgres_memory(infra_settings: Settings) -> None:
    s = infra_settings
    async with await psycopg.AsyncConnection.connect(s.postgres_dsn) as conn:
        await conn.execute("DELETE FROM polymath_claims WHERE statement = %s", (LEMMA,))
        await conn.commit()
    async with open_knowledge(s) as knowledge:
        memory: EpisodicMemory = knowledge.episodic

        async def run(problem: str, prover: Prover):  # type: ignore[no-untyped-def]
            from polymath.blackboard import Blackboard, InMemoryEventStore

            bb = Blackboard(InMemoryEventStore())
            base = make_factory(FixedPlanner(plan()), prover, bb)

            def factory(budget):  # type: ignore[no-untyped-def]
                ctx = base(budget)
                ctx.executors = {r: prover for r in AgentRole}
                ctx.memory = memory
                return ctx

            runner = SwarmRunner(compile_graph(memory_checkpointer()), factory, bb)
            return await runner.start(Problem(statement=problem))

        first, second = Prover(), Prover()
        snap1 = await run("Prove that for every natural number n, n(n+1) is even.", first)
        snap2 = await run("Prove that for every natural number n, n(n+1)(n+2) is even.", second)
    assert first.proved == [LEMMA] and second.proved == []
    reused = [c for c in snap2.values["claims"].values() if c.statement == LEMMA]
    assert reused and reused[0].origin_run_id == snap1.run_id
    assert reused[0].status == ClaimStatus.VERIFIED


@pytest.mark.network
async def test_ingests_arxiv_pdf_full_text(infra_settings: Settings) -> None:
    async with open_knowledge(infra_settings) as knowledge:
        record = await knowledge.ingestor.ingest_arxiv("2303.09521")
        text = await knowledge.store.paper_text(record.key)
        hits = await knowledge.retriever.search("book algorithm monochromatic red blue", k=5)
    assert record.key == "arxiv:2303.09521"
    assert len(text) > 20_000, "expected PDF full text, not just the abstract"
    assert "book" in text.lower()
    assert any(h.chunk.paper_key == record.key for h in hits)
