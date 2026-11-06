"""The Redis rate limiter is shared: two API replicas (two limiter objects) draw on one budget."""

from __future__ import annotations

import os
import uuid

import pytest
import redis.asyncio as aioredis

from polymath.api.ratelimit import RedisSlidingWindowLimiter

pytestmark = pytest.mark.integration
REDIS_URL = os.environ.get("POLYMATH_REDIS_URL", "redis://localhost:6379/0")


async def test_limit_is_shared_across_replicas_and_window_expires() -> None:
    name = f"test-{uuid.uuid4().hex[:8]}"
    a, b = aioredis.from_url(REDIS_URL), aioredis.from_url(REDIS_URL)
    try:
        replica1 = RedisSlidingWindowLimiter(a, name, limit=3, window_s=1.0)
        replica2 = RedisSlidingWindowLimiter(b, name, limit=3, window_s=1.0)
        assert await replica1.check("k") is None
        assert await replica2.check("k") is None
        assert await replica1.check("k") is None
        wait = await replica2.check("k")  # 4th hit in the window, from either replica
        assert wait is not None and 0 <= wait <= 1.0
        assert await replica1.check("other") is None  # separate clients
        import asyncio

        await asyncio.sleep(1.1)
        assert await replica2.check("k") is None
    finally:
        keys = [k async for k in a.scan_iter(f"polymath:rl:{name}:*")]
        if keys:
            await a.delete(*keys)
        await a.aclose()
        await b.aclose()
