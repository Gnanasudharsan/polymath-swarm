"""One handle on the knowledge layer: store + ingestion + retrieval + episodic memory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from redis.asyncio import Redis

from polymath.core.config import Settings
from polymath.mcp_servers.literature.cache import RateLimiter, ResponseCache
from polymath.mcp_servers.literature.http import HttpSource
from polymath.mcp_servers.literature.sources import ArxivClient
from polymath.memory.embeddings import CrossEncoderReranker, Embedder, FastEmbedder, Reranker
from polymath.memory.episodic import EpisodicMemory
from polymath.memory.ingest import Ingestor
from polymath.memory.inmemory import InMemoryKnowledgeStore
from polymath.memory.models import KnowledgeStore
from polymath.memory.pg import PgKnowledgeStore, make_pool
from polymath.memory.retrieval import HybridRetriever


@dataclass
class Knowledge:
    store: KnowledgeStore
    embedder: Embedder
    ingestor: Ingestor
    retriever: HybridRetriever
    episodic: EpisodicMemory


def build_knowledge(
    store: KnowledgeStore,
    embedder: Embedder,
    reranker: Reranker | None,
    *,
    min_similarity: float,
    arxiv: ArxivClient | None = None,
    http: httpx.AsyncClient | None = None,
    limiter: RateLimiter | None = None,
) -> Knowledge:
    return Knowledge(
        store=store,
        embedder=embedder,
        ingestor=Ingestor(store, embedder, arxiv=arxiv, http=http, limiter=limiter),
        retriever=HybridRetriever(store, embedder, reranker),
        episodic=EpisodicMemory(store, embedder, min_similarity=min_similarity),
    )


@asynccontextmanager
async def open_knowledge(
    settings: Settings, *, in_memory: bool = False
) -> AsyncIterator[Knowledge]:
    embedder = FastEmbedder(
        settings.embedding_model, settings.model_cache_dir, settings.embedding_dim
    )
    reranker = (
        CrossEncoderReranker(settings.rerank_model, settings.model_cache_dir)
        if settings.rerank_model
        else None
    )
    if in_memory:
        yield build_knowledge(InMemoryKnowledgeStore(), embedder, reranker,
                              min_similarity=settings.memory_min_similarity)  # fmt: skip
        return
    redis = Redis.from_url(settings.redis_url)
    pool = make_pool(settings.postgres_dsn)
    await pool.open()
    try:
        store = PgKnowledgeStore(pool, settings.postgres_dsn, settings.embedding_dim)
        await store.setup()
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http:
            limiter = RateLimiter(redis)
            arxiv = ArxivClient(
                HttpSource("arxiv", http, ResponseCache(redis), limiter, interval_s=3.0)
            )
            yield build_knowledge(
                store, embedder, reranker, arxiv=arxiv, http=http, limiter=limiter,
                min_similarity=settings.memory_min_similarity,
            )  # fmt: skip
    finally:
        await pool.close()
        await redis.aclose()
