"""Chunking, BM25, RRF, hybrid retrieval, ingestion and episodic memory (in-memory store)."""

from __future__ import annotations

import pytest

from polymath.core.models import Claim, ClaimStatus, Problem
from polymath.memory.embeddings import HashEmbedder
from polymath.memory.episodic import EpisodicMemory
from polymath.memory.evaluation import evaluate, index_corpus, load_dataset
from polymath.memory.ingest import Ingestor
from polymath.memory.inmemory import InMemoryKnowledgeStore, bm25_scores
from polymath.memory.models import ChunkRecord, PaperRecord, ScoredChunk
from polymath.memory.retrieval import HybridRetriever, rrf
from polymath.memory.text import Page, chunk_pages, chunk_text, clean


def test_clean_joins_hyphenated_line_breaks() -> None:
    assert clean("expo-\nnential   growth\n\n\n\nnext") == "exponential growth\n\nnext"
    assert clean("bad\x00byte\x07s") == "badbytes"  # Postgres rejects NUL


def test_chunks_respect_size_overlap_and_pages() -> None:
    sentences = " ".join(f"Sentence number {i} talks about Ramsey numbers." for i in range(60))
    chunks = chunk_pages([Page(number=3, text=sentences)], size=300, overlap=60)
    assert len(chunks) > 5
    assert all(len(c.text) <= 300 + 60 for c in chunks)
    assert {c.page for c in chunks} == {3}
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    # overlap: consecutive chunks share text
    assert chunks[0].text[-30:] in chunks[1].text
    assert chunk_text("")[:1] == []


def test_bm25_prefers_documents_with_rare_query_terms() -> None:
    docs = ["the cat sat", "ramsey numbers grow", "the ramsey theory of cats"]
    scores = bm25_scores("ramsey numbers", docs)
    assert scores.index(max(scores)) == 1 and scores[0] == 0.0


def _hit(cid: str, src: str) -> ScoredChunk:
    return ScoredChunk(chunk=ChunkRecord(id=cid, paper_key="p", ord=0, page=None, text=cid),
                       score=0.0, sources=[src])  # fmt: skip


def test_rrf_rewards_agreement() -> None:
    fused = rrf([[_hit("a", "lex"), _hit("b", "lex")], [_hit("b", "vec"), _hit("c", "vec")]])
    assert fused[0].chunk.id == "b"
    assert fused[0].sources == ["lex", "vec"]


class OverlapReranker:
    """Scores by query-word overlap — enough to test the reranking stage."""

    async def scores(self, query: str, texts: list[str]) -> list[float]:
        q = set(query.lower().split())
        return [len(q & set(t.lower().split())) for t in texts]


async def _indexed() -> tuple[InMemoryKnowledgeStore, HybridRetriever]:
    store, emb = InMemoryKnowledgeStore(), HashEmbedder()
    corpus, _ = load_dataset()
    await index_corpus(Ingestor(store, emb), corpus)
    return store, HybridRetriever(store, emb, OverlapReranker())


@pytest.mark.parametrize("mode", ["lexical", "vector", "hybrid", "hybrid_rerank"])
async def test_eval_machinery_runs_every_mode(mode: str) -> None:
    _, retriever = await _indexed()
    _, queries = load_dataset()
    m = await evaluate(retriever, queries, mode)  # type: ignore[arg-type]
    assert m.queries == 30 and 0 <= m.mrr <= 1
    assert m.recall_at[1] <= m.recall_at[5] <= m.recall_at[10]


async def test_bm25_hybrid_meets_target_even_with_hash_embeddings() -> None:
    _, retriever = await _indexed()
    _, queries = load_dataset()
    m = await evaluate(retriever, queries, "hybrid")
    assert m.recall_at[10] >= 0.8


async def test_ingest_is_idempotent_and_puts_abstract_first() -> None:
    store = InMemoryKnowledgeStore()
    ing = Ingestor(store, HashEmbedder())
    rec = PaperRecord(key="arxiv:1", title="T", abstract="An abstract about primes.")
    assert await ing.ingest_text(rec, text="Body text. " * 50) > 1
    assert await ing.ingest_text(rec, text="ignored") == 0
    assert (await store.paper_text("arxiv:1")).startswith("T. An abstract about primes.")


async def test_episodic_recall_returns_only_relevant_verified_claims() -> None:
    store, emb = InMemoryKnowledgeStore(), HashEmbedder()
    mem = EpisodicMemory(store, emb, min_similarity=0.3)
    lemma = Claim(statement="n(n+1) is even for every natural number n",
                  status=ClaimStatus.VERIFIED)  # fmt: skip
    hunch = Claim(statement="n(n+1) is a perfect square for every natural number n")
    other = Claim(statement="The Transformer relies on self-attention", status=ClaimStatus.VERIFIED)
    await mem.record_run("run_1", Problem(statement="Is n(n+1) even?"), "completed", "yes",
                         [lemma, hunch, other])  # fmt: skip
    hits = await mem.reusable_claims(Problem(statement="Prove n(n+1)(n+2) is even for natural n"))
    assert [sc.claim.id for sc, _ in hits] == [lemma.id]
    assert hits[0][0].run_id == "run_1"
