"""Shared HTTP plumbing: cache lookup → rate limit → request with retries → cache store."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from polymath import __version__
from polymath.core.logging import get_logger
from polymath.mcp_servers.literature.cache import RateLimiter, ResponseCache, Sleep, cache_key

log = get_logger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class LiteratureAPIError(RuntimeError):
    pass


class HttpSource:
    """One upstream API: its own rate-limit interval and cache namespace."""

    def __init__(
        self,
        name: str,
        client: httpx.AsyncClient,
        cache: ResponseCache,
        limiter: RateLimiter,
        *,
        interval_s: float,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.cache = cache
        self.limiter = limiter
        self.interval_s = interval_s
        self.headers = {"User-Agent": f"polymath-swarm/{__version__}", **(headers or {})}
        self.max_retries = max_retries
        self._sleep = sleep

    async def get(self, url: str, params: dict[str, Any] | None = None, *, as_json: bool) -> Any:
        key = cache_key(self.name, url, params)
        cached = await self.cache.get(key)
        if cached is not None:
            log.debug("literature.cache_hit", source=self.name, url=url)
            return cached

        for attempt in range(self.max_retries + 1):
            await self.limiter.acquire(self.name, self.interval_s)
            try:
                resp = await self.client.get(url, params=params, headers=self.headers)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise LiteratureAPIError(f"{self.name}: {type(exc).__name__}: {exc}") from exc
                await self._sleep(2**attempt)
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                delay = _retry_after(resp) or float(2**attempt)
                log.info("literature.retry", source=self.name, status=resp.status_code, delay=delay)
                await self._sleep(delay)
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                raise LiteratureAPIError(
                    f"{self.name}: HTTP {resp.status_code} for {url}: {resp.text[:300]}"
                )
            value = resp.json() if as_json else resp.text
            await self.cache.set(key, value)
            return value
        raise LiteratureAPIError(f"{self.name}: retries exhausted for {url}")


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    try:
        return min(float(raw), 60.0) if raw else None
    except ValueError:
        return None
