"""Retrieval eval on Postgres + pgvector with the production embedder and reranker.

    uv run python evals/runners/retrieval.py

Writes evals/reports/retrieval-<date>.md.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from polymath.core.config import get_settings, load_env_file
from polymath.memory.embeddings import CrossEncoderReranker, FastEmbedder
from polymath.memory.evaluation import evaluate, index_corpus, load_dataset, metrics_table
from polymath.memory.ingest import Ingestor
from polymath.memory.pg import PgKnowledgeStore, make_pool
from polymath.memory.retrieval import HybridRetriever

REPORTS = Path(__file__).resolve().parents[1] / "reports"


async def main() -> None:
    load_env_file()
    s = get_settings()
    embedder = FastEmbedder(s.embedding_model, s.model_cache_dir, s.embedding_dim)
    reranker = CrossEncoderReranker(s.rerank_model or "", s.model_cache_dir)
    pool = make_pool(s.postgres_dsn)
    store = PgKnowledgeStore(pool, s.postgres_dsn, s.embedding_dim)
    await pool.open()
    try:
        await store.setup()
        corpus, queries = load_dataset()
        await index_corpus(Ingestor(store, embedder), corpus)
        retriever = HybridRetriever(store, embedder, reranker)
        rows = [await evaluate(retriever, queries, m)
                for m in ("lexical", "vector", "hybrid", "hybrid_rerank")]  # fmt: skip
    finally:
        await pool.close()
    table = metrics_table(rows)
    print(table)
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"retrieval-{date.today().isoformat()}.md"
    out.write_text(
        f"# Retrieval eval — {date.today().isoformat()}\n\n"
        f"Corpus: {len(corpus)} passages (12 topics, 5 near-neighbour passages each); "
        f"{len(queries)} paraphrased queries. Embedder `{s.embedding_model}`, reranker "
        f"`{s.rerank_model}`, store Postgres 16 + pgvector (HNSW) + full-text search.\n\n"
        f"{table}\n\nMisses (no relevant passage in the top 10): "
        + (", ".join(f"{r.mode}: {r.misses}" for r in rows if r.misses) or "none")
        + "\n"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
