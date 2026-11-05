"""Literature clients, cache and rate limiter — offline (httpx.MockTransport + fakeredis)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from polymath.core.config import Settings
from polymath.mcp_servers.client import MCPToolbox
from polymath.mcp_servers.literature import build_server, create_literature
from polymath.mcp_servers.literature.cache import RateLimiter, ResponseCache
from polymath.mcp_servers.literature.http import HttpSource, LiteratureAPIError
from polymath.mcp_servers.literature.sources import (
    normalise_arxiv_id,
    parse_arxiv_feed,
    parse_openalex_work,
    parse_s2_paper,
    reconstruct_abstract,
)

ARXIV_XML = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>897</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2605.07322v2</id>
    <title>New results on the odd- and
      unique-Ramsey numbers</title>
    <link href="https://arxiv.org/abs/2605.07322v2" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/2605.07322v2" rel="related" type="application/pdf"
          title="pdf"/>
    <summary>The odd-Ramsey number of a graph H ...</summary>
    <category term="math.CO" scheme="http://arxiv.org/schemas/atom"/>
    <published>2026-05-08T06:28:44Z</published>
    <arxiv:doi>10.1000/xyz</arxiv:doi>
    <author><name>Shagnik Das</name></author>
    <author><name>Ying-Sian Wu</name></author>
  </entry>
</feed>"""

S2_PAPER = {
    "paperId": "abc123",
    "externalIds": {"ArXiv": "1706.03762", "DOI": "10.48550/arXiv.1706.03762"},
    "url": "https://www.semanticscholar.org/paper/abc123",
    "title": "Attention Is All You Need",
    "abstract": "The dominant sequence transduction models ...",
    "year": 2017,
    "citationCount": 100000,
    "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762"},
    "authors": [{"authorId": "1", "name": "Ashish Vaswani"}],
}

OPENALEX_WORK = {
    "id": "https://openalex.org/W1604945782",
    "doi": "https://doi.org/10.37236/21",
    "title": "Small Ramsey Numbers",
    "publication_year": 2011,
    "authorships": [{"author": {"display_name": "Stanisław Radziszowski"}}],
    "cited_by_count": 500,
    "abstract_inverted_index": {"We": [0], "survey": [1], "Ramsey": [3], "small": [2]},
    "primary_location": {"landing_page_url": "https://doi.org/10.37236/21", "pdf_url": None},
    "ids": {"openalex": "https://openalex.org/W1604945782"},
}


# --------------------------------------------------------------------------- parsers


def test_parse_arxiv_feed() -> None:
    papers, total = parse_arxiv_feed(ARXIV_XML)
    assert total == 897
    (p,) = papers
    assert p.arxiv_id == "2605.07322v2"
    assert p.title == "New results on the odd- and unique-Ramsey numbers"
    assert p.authors == ["Shagnik Das", "Ying-Sian Wu"]
    assert p.pdf_url == "https://arxiv.org/pdf/2605.07322v2"
    assert p.year == 2026 and p.doi == "10.1000/xyz" and p.categories == ["math.CO"]


def test_arxiv_parser_rejects_xml_entity_attacks() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><feed>&a;</feed>'
    with pytest.raises(Exception, match=r"(?i)entit"):
        parse_arxiv_feed(bomb)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2101.00001", "2101.00001"),
        ("arXiv:2101.00001v3", "2101.00001v3"),
        ("https://arxiv.org/abs/2101.00001v2", "2101.00001v2"),
        ("math/0601001", "math/0601001"),
    ],
)
def test_normalise_arxiv_id(raw: str, expected: str) -> None:
    assert normalise_arxiv_id(raw) == expected


def test_arxiv_query_ands_plain_keywords() -> None:
    from polymath.mcp_servers.literature.sources import arxiv_query

    assert arxiv_query("exponential improvement diagonal Ramsey") == (
        "all:exponential AND all:improvement AND all:diagonal AND all:Ramsey"
    )
    assert arxiv_query("Erdős-Szekeres bound") == "all:Erdős-Szekeres AND all:bound"
    assert arxiv_query("ti:Ramsey AND au:Campos") == "ti:Ramsey AND au:Campos"


def test_normalise_arxiv_id_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="arXiv"):
        normalise_arxiv_id("not-an-id")


def test_parse_s2_paper() -> None:
    p = parse_s2_paper(S2_PAPER)
    assert (p.source_id, p.arxiv_id, p.citation_count) == ("abc123", "1706.03762", 100000)
    assert p.pdf_url == "https://arxiv.org/pdf/1706.03762"


def test_parse_openalex_work() -> None:
    p = parse_openalex_work(OPENALEX_WORK)
    assert p.source_id == "W1604945782"
    assert p.doi == "10.37236/21"
    assert p.abstract == "We survey small Ramsey"
    assert reconstruct_abstract(None) == ""


# --------------------------------------------------------------------------- http layer


Handler = Callable[[httpx.Request], httpx.Response]


def _source(handler: Handler, redis: FakeAsyncRedis, **kw: object) -> HttpSource:
    async def no_sleep(_s: float) -> None:
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpSource(
        "test",
        client,
        ResponseCache(redis),
        RateLimiter(redis, sleep=no_sleep),
        interval_s=0.001,
        sleep=no_sleep,
        **kw,  # type: ignore[arg-type]
    )


async def test_cache_hit_skips_network() -> None:
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json={"n": len(calls)})

    src = _source(handler, FakeAsyncRedis())
    first = await src.get("https://x.test/a", {"q": "1"}, as_json=True)
    second = await src.get("https://x.test/a", {"q": "1"}, as_json=True)
    other = await src.get("https://x.test/a", {"q": "2"}, as_json=True)
    assert first == second == {"n": 1}
    assert other == {"n": 2}
    assert len(calls) == 2
    assert calls[0].headers["User-Agent"].startswith("polymath-swarm/")


async def test_retries_429_then_succeeds() -> None:
    statuses = iter([429, 503, 200])

    def handler(_req: httpx.Request) -> httpx.Response:
        code = next(statuses)
        return httpx.Response(code, json={"ok": code == 200}, headers={"Retry-After": "1"})

    assert await _source(handler, FakeAsyncRedis()).get("https://x.test", as_json=True) == {
        "ok": True
    }


async def test_persistent_error_raises_and_404_is_none() -> None:
    src = _source(lambda _r: httpx.Response(400, text="bad"), FakeAsyncRedis())
    with pytest.raises(LiteratureAPIError, match="HTTP 400"):
        await src.get("https://x.test", as_json=True)
    missing = _source(lambda _r: httpx.Response(404), FakeAsyncRedis())
    assert await missing.get("https://x.test", as_json=True) is None


async def test_rate_limiter_spaces_requests() -> None:
    limiter = RateLimiter(FakeAsyncRedis())
    started = time.monotonic()
    for _ in range(3):
        await limiter.acquire("api", 0.1)
    assert time.monotonic() - started >= 0.18  # 2 enforced gaps of ~0.1 s


async def test_rate_limiter_gives_up_after_max_wait() -> None:
    limiter = RateLimiter(FakeAsyncRedis())
    await limiter.acquire("slow", 10)
    with pytest.raises(TimeoutError):
        await limiter.acquire("slow", 10, max_wait_s=0.05)


# --------------------------------------------------------------------------- server


def _router(req: httpx.Request) -> httpx.Response:
    host, path = req.url.host, req.url.path
    if host == "export.arxiv.org":
        return httpx.Response(200, text=ARXIV_XML)
    if host == "api.semanticscholar.org" and path.endswith("/citations"):
        return httpx.Response(200, json={"data": [{"citingPaper": S2_PAPER}]})
    if host == "api.semanticscholar.org":
        return httpx.Response(200, json={"total": 1, "data": [S2_PAPER]})
    if host == "api.openalex.org" and path.startswith("/works/"):
        assert path == "/works/doi:10.37236/21"
        return httpx.Response(200, json=OPENALEX_WORK)
    if host == "api.openalex.org":
        assert req.url.params["mailto"] == "me@example.org"
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [OPENALEX_WORK]})
    return httpx.Response(404)


async def test_server_tools_end_to_end() -> None:
    settings = Settings(_env_file=None, OPENALEX_MAILTO="me@example.org")  # type: ignore[call-arg]
    http = httpx.AsyncClient(transport=httpx.MockTransport(_router))
    lit = create_literature(FakeAsyncRedis(), http, settings)
    # keep unit tests fast: no politeness delay against the mock transport
    for src in (lit.arxiv.http, lit.s2.http, lit.openalex.http):
        src.interval_s = 0.001
    async with MCPToolbox({"lit": build_server(lit)}) as tb:
        assert len(tb.tools) == 6
        res = await tb.call("lit.arxiv_search", {"query": "ramsey", "max_results": 5})
        assert res.structured is not None
        assert res.structured["papers"][0]["arxiv_id"] == "2605.07322v2"
        res = await tb.call("lit.semantic_scholar_citations", {"paper_id": "arXiv:1706.03762"})
        assert res.structured is not None and res.structured["papers"][0]["year"] == 2017
        res = await tb.call("lit.openalex_lookup", {"identifier": "10.37236/21"})
        assert res.structured is not None and res.structured["title"] == "Small Ramsey Numbers"
        res = await tb.call("lit.openalex_search", {"query": "ramsey"})
        assert not res.is_error
        bad = await tb.call("lit.arxiv_fetch", {"arxiv_id": "garbage"})
        assert bad.is_error and "arXiv" in bad.text


def test_payload_is_json_serialisable() -> None:
    json.dumps(parse_s2_paper(S2_PAPER).model_dump())
