"""Per-client sliding-window rate limits for the HTTP API (including A2A JSON-RPC)."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

WINDOW_S = 60.0


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_s: float = WINDOW_S, clock: Callable[[], float] = time.monotonic
    ):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> float | None:
        """Record a hit; return seconds to wait if over the limit, else ``None``."""
        now = self.clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(0.0, self.window_s - (now - hits[0]))
        hits.append(now)
        return None


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

    def __init__(self, app: ASGIApp, *, writes_per_minute: int, reads_per_minute: int) -> None:
        super().__init__(app)
        self.writes = SlidingWindowLimiter(writes_per_minute)
        self.reads = SlidingWindowLimiter(reads_per_minute)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        limiter = self.writes if _is_write(request) else self.reads
        wait = limiter.check(_client_key(request))
        if wait is not None:
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(int(wait) + 1)},
            )
        return await call_next(request)
