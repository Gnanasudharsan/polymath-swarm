"""Literature server against the real public APIs and the compose Redis.

Marked ``network`` as well: public APIs rate-limit shared IPs, so CI skips these.
"""

from __future__ import annotations

import pytest

from polymath.core.config import Settings
from polymath.mcp_servers.client import MCPToolbox
from polymath.mcp_servers.literature import build_server

pytestmark = [pytest.mark.integration, pytest.mark.network]


async def test_arxiv_and_openalex_via_redis() -> None:
    settings = Settings()
    async with MCPToolbox({"lit": build_server(settings=settings)}, timeout_s=180) as tb:
        res = await tb.call("lit.arxiv_fetch", {"arxiv_id": "1706.03762"})
        assert not res.is_error, res.text
        assert res.structured is not None
        assert "Attention" in res.structured["title"]

        search = await tb.call("lit.openalex_search", {"query": "small ramsey numbers", "limit": 3})
        assert not search.is_error, search.text
        assert search.structured is not None and search.structured["papers"]

        lookup = await tb.call("lit.openalex_lookup", {"identifier": "10.37236/21"})
        assert lookup.structured is not None and "Ramsey" in lookup.structured["title"]


async def test_semantic_scholar_search() -> None:
    async with MCPToolbox({"lit": build_server(settings=Settings())}, timeout_s=180) as tb:
        res = await tb.call("lit.semantic_scholar_search", {"query": "graph ramsey", "limit": 3})
    # skip outside the client context: raising inside it gets wrapped by anyio's TaskGroup
    if res.is_error and "429" in res.text:
        pytest.skip("Semantic Scholar is rate-limiting this IP (set SEMANTIC_SCHOLAR_API_KEY)")
    assert not res.is_error, res.text
    assert res.structured is not None and res.structured["papers"]
