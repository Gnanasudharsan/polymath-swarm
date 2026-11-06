"""Durable event history: Postgres in production, in-memory for tests."""

from __future__ import annotations

import builtins
from collections import defaultdict
from typing import Protocol

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from polymath.core.models import BlackboardEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS polymath_events (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    seq         BIGSERIAL,
    kind        TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS polymath_events_run_seq ON polymath_events (run_id, seq);
"""


class EventStore(Protocol):
    async def append(self, event: BlackboardEvent) -> None: ...
    async def list(self, run_id: str) -> list[BlackboardEvent]: ...
    async def recent_runs(self, limit: int = 50) -> builtins.list[BlackboardEvent]:
        """The ``run_started`` events of the most recent runs, newest first."""
        ...


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events: defaultdict[str, list[BlackboardEvent]] = defaultdict(list)

    async def append(self, event: BlackboardEvent) -> None:
        self._events[event.run_id].append(event)

    async def list(self, run_id: str) -> list[BlackboardEvent]:
        return list(self._events[run_id])

    async def recent_runs(self, limit: int = 50) -> builtins.list[BlackboardEvent]:
        starts = [e for evs in self._events.values() for e in evs if e.kind.value == "run_started"]
        return sorted(starts, key=lambda e: e.created_at, reverse=True)[:limit]


class PostgresEventStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def setup(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def append(self, event: BlackboardEvent) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO polymath_events (id, run_id, kind, payload, created_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (event.id, event.run_id, event.kind.value, Jsonb(event.payload), event.created_at),
            )

    async def list(self, run_id: str) -> list[BlackboardEvent]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, run_id, kind, payload, created_at FROM polymath_events "
                "WHERE run_id = %s ORDER BY seq",
                (run_id,),
            )
            rows = await cur.fetchall()
        return [
            BlackboardEvent(id=r[0], run_id=r[1], kind=r[2], payload=r[3], created_at=r[4])
            for r in rows
        ]

    async def recent_runs(self, limit: int = 50) -> builtins.list[BlackboardEvent]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, run_id, kind, payload, created_at FROM polymath_events "
                "WHERE kind = 'run_started' ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            rows = await cur.fetchall()
        return [
            BlackboardEvent(id=r[0], run_id=r[1], kind=r[2], payload=r[3], created_at=r[4])
            for r in rows
        ]
