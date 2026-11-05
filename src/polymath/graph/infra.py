"""Wire checkpointer + blackboard to real infrastructure (Postgres, Redis) or to memory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from polymath.blackboard import Blackboard, InMemoryEventStore, PostgresEventStore
from polymath.core.config import Settings
from polymath.graph.checkpointer import memory_checkpointer, postgres_checkpointer


@dataclass
class SwarmInfra:
    checkpointer: BaseCheckpointSaver[Any]
    blackboard: Blackboard


@asynccontextmanager
async def swarm_infra(settings: Settings, *, in_memory: bool = False) -> AsyncIterator[SwarmInfra]:
    if in_memory:
        yield SwarmInfra(memory_checkpointer(), Blackboard(InMemoryEventStore()))
        return
    redis = Redis.from_url(settings.redis_url)
    pool = AsyncConnectionPool(settings.postgres_dsn, min_size=1, max_size=8, open=False)
    await pool.open()
    try:
        store = PostgresEventStore(pool)
        await store.setup()
        async with postgres_checkpointer(settings.postgres_dsn) as saver:
            yield SwarmInfra(saver, Blackboard(store, redis))
    finally:
        await pool.close()
        await redis.aclose()
