"""Redis-backed response cache and cross-process rate limiter for literature APIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis

Sleep = Callable[[float], Awaitable[None]]


def cache_key(namespace: str, url: str, params: dict[str, Any] | None) -> str:
    raw = json.dumps([url, sorted((params or {}).items())], default=str)
    return f"polymath:lit:cache:{namespace}:{hashlib.sha256(raw.encode()).hexdigest()}"


class ResponseCache:
    """JSON-serialisable values with a TTL."""

    def __init__(self, redis: Redis, ttl_s: int = 86_400) -> None:
        self.redis = redis
        self.ttl_s = ttl_s

    async def get(self, key: str) -> Any | None:
        raw = await self.redis.get(key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any) -> None:
        await self.redis.set(key, json.dumps(value), ex=self.ttl_s)


class RateLimiter:
    """Minimum interval between requests per key, shared by every process on the same Redis.

    ``SET key NX PX interval`` succeeds for exactly one caller per interval; others wait for the
    key's remaining TTL and try again.
    """

    def __init__(self, redis: Redis, *, sleep: Sleep = asyncio.sleep) -> None:
        self.redis = redis
        self._sleep = sleep

    async def acquire(self, key: str, interval_s: float, *, max_wait_s: float = 120.0) -> float:
        """Block until a slot is free; return seconds waited."""
        waited = 0.0
        name = f"polymath:lit:rl:{key}"
        while True:
            if await self.redis.set(name, "1", nx=True, px=max(1, int(interval_s * 1000))):
                return waited
            ttl_ms = await self.redis.pttl(name)
            delay = max(ttl_ms, 10) / 1000 if ttl_ms > 0 else 0.01
            if waited + delay > max_wait_s:
                raise TimeoutError(f"rate limiter for {key!r} waited more than {max_wait_s}s")
            await self._sleep(delay)
            waited += delay
