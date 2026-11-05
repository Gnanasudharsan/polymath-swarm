"""The blackboard: every agent action becomes a :class:`BlackboardEvent`.

Events are persisted first (durable history, trace export, SSE replay) and then published on a
per-run Redis channel for live subscribers. Publishing is best-effort; persistence is not.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis

from polymath.blackboard.store import EventStore, InMemoryEventStore
from polymath.core.logging import get_logger
from polymath.core.models import BlackboardEvent, EventKind

log = get_logger(__name__)


def channel(run_id: str) -> str:
    return f"polymath:run:{run_id}:events"


class Blackboard:
    def __init__(self, store: EventStore | None = None, redis: Redis | None = None) -> None:
        self.store: EventStore = store or InMemoryEventStore()
        self.redis = redis

    async def post(self, run_id: str, kind: EventKind, **payload: Any) -> BlackboardEvent:
        event = BlackboardEvent(run_id=run_id, kind=kind, payload=payload)
        await self.publish(event)
        return event

    async def publish(self, event: BlackboardEvent) -> None:
        await self.store.append(event)
        if self.redis is not None:
            try:
                await self.redis.publish(channel(event.run_id), event.model_dump_json())
            except Exception as exc:  # live fan-out must never break a run
                log.warning("blackboard.publish_failed", run_id=event.run_id, error=str(exc))

    async def history(self, run_id: str) -> list[BlackboardEvent]:
        return await self.store.list(run_id)

    async def subscribe(self, run_id: str) -> AsyncIterator[BlackboardEvent]:
        """Yield live events for ``run_id`` until a ``run_finished`` event arrives."""
        if self.redis is None:
            raise RuntimeError("live subscription needs Redis")
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel(run_id))
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    await asyncio.sleep(0)
                    continue
                event = BlackboardEvent.model_validate_json(msg["data"])
                yield event
                if event.kind is EventKind.RUN_FINISHED:
                    return
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(channel(run_id))
                await pubsub.aclose()  # type: ignore[no-untyped-call]
