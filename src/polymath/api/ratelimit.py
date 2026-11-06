"""Per-client sliding-window rate limits for the HTTP API (including A2A JSON-RPC).

Two backends: in-process (one API replica) and Redis (shared by every replica, so the limit holds
for the whole deployment, not per process).
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Protocol

from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from polymath.core.logging import get_logger

log = get_logger(__name__)
WINDOW_S = 60.0


class Limiter(Protocol):
    async def check(self, key: str) -> float | None:
        """Record a hit; return seconds to wait if over the limit, else ``None``."""
        ...


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_s: float = WINDOW_S, clock: Callable[[], float] = time.monotonic
    ):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    async def check(self, key: str) -> float | None:
        now = self.clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(0.0, self.window_s - (now - hits[0]))
        hits.append(now)
        return None


# Atomic sliding window on a sorted set. Uses the Redis server clock so replicas with skewed
# clocks still agree. Returns -1 when allowed, else milliseconds to wait.
_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return math.max(0, window - (now - tonumber(oldest[2])))
end
local seq = redis.call('INCR', KEYS[1] .. ':seq')
redis.call('ZADD', KEYS[1], now, now .. '-' .. seq)
redis.call('PEXPIRE', KEYS[1], window)
redis.call('PEXPIRE', KEYS[1] .. ':seq', window)
return -1
"""


class RedisSlidingWindowLimiter:
    """Shared limiter. If Redis is unreachable the request is allowed (fail open) and the error
    is logged: an outage of the limiter must not take the API down."""

    def __init__(self, redis: Redis, name: str, limit: int, window_s: float = WINDOW_S) -> None:
        self.redis, self.limit = redis, limit
        self.window_ms = int(window_s * 1000)
        self.prefix = f"polymath:rl:{name}:"
        self._script = redis.register_script(_SCRIPT)

    async def check(self, key: str) -> float | None:
        try:
            wait_ms = int(await self._script(keys=[self.prefix + key],
                                             args=[self.window_ms, self.limit]))  # fmt: skip
        except Exception as exc:
            log.warning("ratelimit.redis_unavailable", error=repr(exc))
            return None
        return None if wait_ms < 0 else wait_ms / 1000


def _client_key(request: Request) -> str:
    """The API key (hashed) if present, else the client address."""
    key = request.headers.get("x-api-key")
    if key:
        return "k:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    return "ip:" + (request.client.host if request.client else "unknown")


def _is_write(request: Request) -> bool:
    path = request.url.path
    return request.method == "POST" and (
        path.startswith("/runs") or path == "/a2a" or path.endswith("/a2a")
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Separate budgets for writes (start runs, approvals, A2A calls) and reads. Health and the
    long-lived SSE streams are exempt (a stream counts once, at connect, as a read)."""

    def __init__(self, app: ASGIApp, *, writes: Limiter, reads: Limiter) -> None:
        super().__init__(app)
        self.writes, self.reads = writes, reads

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        limiter = self.writes if _is_write(request) else self.reads
        wait = await limiter.check(_client_key(request))
        if wait is not None:
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(int(wait) + 1)},
            )
        return await call_next(request)


def build_limiters(
    *, backend: str, redis_url: str, writes_per_minute: int, reads_per_minute: int
) -> tuple[Limiter, Limiter, Redis | None]:
    """(writes, reads, redis client to close on shutdown or ``None``)."""
    if backend == "redis":
        redis: Redis = Redis.from_url(redis_url)
        return (RedisSlidingWindowLimiter(redis, "w", writes_per_minute),
                RedisSlidingWindowLimiter(redis, "r", reads_per_minute), redis)  # fmt: skip
    return SlidingWindowLimiter(writes_per_minute), SlidingWindowLimiter(reads_per_minute), None
