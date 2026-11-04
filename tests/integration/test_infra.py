"""Docker Compose infrastructure is reachable (run `docker compose up -d` first)."""

import os

import psycopg
import pytest
import redis.asyncio as aioredis

pytestmark = pytest.mark.integration

POSTGRES_DSN = os.environ.get(
    "POLYMATH_POSTGRES_DSN", "postgresql://polymath:polymath@localhost:5544/polymath"
)
REDIS_URL = os.environ.get("POLYMATH_REDIS_URL", "redis://localhost:6379/0")


async def test_postgres_has_pgvector() -> None:
    async with await psycopg.AsyncConnection.connect(POSTGRES_DSN) as conn:
        cur = await conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        row = await cur.fetchone()
        assert row is not None, "pgvector extension not installed"
        cur = await conn.execute("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")
        distance = await cur.fetchone()
        assert distance is not None
        assert distance[0] == pytest.approx(1.0)


async def test_redis_ping_and_pubsub() -> None:
    client = aioredis.from_url(REDIS_URL)
    try:
        assert await client.ping()
        await client.set("polymath:smoke", "ok", ex=10)
        assert await client.get("polymath:smoke") == b"ok"
    finally:
        await client.aclose()
