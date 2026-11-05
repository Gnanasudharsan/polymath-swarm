"""arXiv, Semantic Scholar and OpenAlex clients. Parsers are pure functions for testability."""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element  # only the type; parsing goes through defusedxml

import defusedxml.ElementTree as SafeET

from polymath.mcp_servers.literature.http import HttpSource
from polymath.mcp_servers.literature.models import Paper, PaperList

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$")
S2_FIELDS = "title,abstract,year,authors,externalIds,citationCount,url,openAccessPdf"


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


# --------------------------------------------------------------------------- arXiv


def normalise_arxiv_id(raw: str) -> str:
    """'https://arxiv.org/abs/2101.00001v2' or 'arXiv:2101.00001' → '2101.00001v2'."""
    raw = raw.strip().removeprefix("arXiv:").removeprefix("arxiv:")
    match = _ARXIV_ID.search(raw)
    if not match:
        raise ValueError(f"not an arXiv identifier: {raw!r}")
    return match.group(0)


def parse_arxiv_feed(xml: str) -> tuple[list[Paper], int | None]:
    root: Element = SafeET.fromstring(xml)
    total_el = root.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        entry_id = entry.findtext(f"{ATOM}id") or ""
        if "/abs/" not in entry_id:  # error entries have no abs URL
            continue
        arxiv_id = normalise_arxiv_id(entry_id)
        pdf = next(
            (
                link.get("href")
                for link in entry.findall(f"{ATOM}link")
                if link.get("title") == "pdf" or link.get("type") == "application/pdf"
            ),
            None,
        )
        published = entry.findtext(f"{ATOM}published") or ""
        doi = entry.findtext(f"{ARXIV_NS}doi")
        papers.append(
            Paper(
                source="arxiv",
                source_id=arxiv_id,
                arxiv_id=arxiv_id,
                title=_clean(entry.findtext(f"{ATOM}title")),
                authors=[_clean(a.findtext(f"{ATOM}name")) for a in entry.findall(f"{ATOM}author")],
                abstract=_clean(entry.findtext(f"{ATOM}summary")),
                year=int(published[:4]) if published[:4].isdigit() else None,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=pdf,
                doi=doi,
                categories=[c.get("term", "") for c in entry.findall(f"{ATOM}category")],
            )
        )
    total = int(total_el.text) if total_el is not None and total_el.text else None
    return papers, total


class ArxivClient:
    BASE = "https://export.arxiv.org/api/query"

    def __init__(self, http: HttpSource) -> None:
        self.http = http

    async def search(self, query: str, max_results: int = 10) -> PaperList:
        params = {"search_query": f"all:{query}", "start": 0, "max_results": max_results}
        papers, total = parse_arxiv_feed(await self.http.get(self.BASE, params, as_json=False))
        return PaperList(query=query, source="arxiv", papers=papers, total=total)

    async def fetch(self, arxiv_id: str) -> Paper | None:
        ident = normalise_arxiv_id(arxiv_id)
        xml = await self.http.get(self.BASE, {"id_list": ident, "max_results": 1}, as_json=False)
        papers, _ = parse_arxiv_feed(xml)
        return papers[0] if papers else None


# --------------------------------------------------------------------------- Semantic Scholar


def parse_s2_paper(data: dict[str, Any]) -> Paper:
    ext = data.get("externalIds") or {}
    pdf = (data.get("openAccessPdf") or {}).get("url") or None
    return Paper(
        source="semantic_scholar",
        source_id=str(data.get("paperId") or ""),
        title=_clean(data.get("title")),
        authors=[a.get("name", "") for a in data.get("authors") or []],
        abstract=_clean(data.get("abstract")),
        year=data.get("year"),
        url=data.get("url"),
        pdf_url=pdf,
        doi=ext.get("DOI"),
        arxiv_id=ext.get("ArXiv"),
        citation_count=data.get("citationCount"),
    )


class SemanticScholarClient:
    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, http: HttpSource) -> None:
        self.http = http

    async def search(self, query: str, limit: int = 10) -> PaperList:
        data = await self.http.get(
            f"{self.BASE}/paper/search",
            {"query": query, "limit": limit, "fields": S2_FIELDS},
            as_json=True,
        )
        data = data or {}
        papers = [parse_s2_paper(p) for p in data.get("data") or []]
        return PaperList(
            query=query, source="semantic_scholar", papers=papers, total=data.get("total")
        )

    async def citations(self, paper_id: str, limit: int = 20) -> PaperList:
        """Papers that cite ``paper_id`` (S2 id, ``arXiv:<id>``, ``DOI:<doi>``...)."""
        data = await self.http.get(
            f"{self.BASE}/paper/{paper_id}/citations",
            {"limit": limit, "fields": S2_FIELDS},
            as_json=True,
        )
        rows = (data or {}).get("data") or []
        papers = [parse_s2_paper(r["citingPaper"]) for r in rows if r.get("citingPaper")]
        return PaperList(query=paper_id, source="semantic_scholar", papers=papers)


# --------------------------------------------------------------------------- OpenAlex


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions = {pos: word for word, idxs in inverted.items() for pos in idxs}
    return " ".join(positions[i] for i in sorted(positions))


def parse_openalex_work(data: dict[str, Any]) -> Paper:
    doi = data.get("doi")
    ids = data.get("ids") or {}
    location = data.get("primary_location") or {}
    arxiv = None
    landing = (location.get("landing_page_url") or "").lower()
    if "arxiv.org/abs/" in landing:
        arxiv = normalise_arxiv_id(landing)
    return Paper(
        source="openalex",
        source_id=str(data.get("id", "")).rsplit("/", 1)[-1],
        title=_clean(data.get("title") or data.get("display_name")),
        authors=[
            (a.get("author") or {}).get("display_name", "") for a in data.get("authorships") or []
        ],
        abstract=reconstruct_abstract(data.get("abstract_inverted_index")),
        year=data.get("publication_year"),
        url=location.get("landing_page_url") or ids.get("openalex"),
        pdf_url=location.get("pdf_url"),
        doi=doi.removeprefix("https://doi.org/") if doi else None,
        arxiv_id=arxiv,
        citation_count=data.get("cited_by_count"),
    )


class OpenAlexClient:
    BASE = "https://api.openalex.org"
    SELECT = (
        "id,doi,title,display_name,publication_year,authorships,cited_by_count,"
        "abstract_inverted_index,primary_location,ids"
    )

    def __init__(self, http: HttpSource, *, mailto: str | None = None, api_key: str | None = None):
        self.http = http
        self.extra: dict[str, str] = {}
        if mailto:
            self.extra["mailto"] = mailto
        if api_key:
            self.extra["api_key"] = api_key

    async def search(self, query: str, limit: int = 10) -> PaperList:
        data = await self.http.get(
            f"{self.BASE}/works",
            {"search": query, "per-page": limit, "select": self.SELECT, **self.extra},
            as_json=True,
        )
        data = data or {}
        papers = [parse_openalex_work(w) for w in data.get("results") or []]
        total = (data.get("meta") or {}).get("count")
        return PaperList(query=query, source="openalex", papers=papers, total=total)

    async def lookup(self, identifier: str) -> Paper | None:
        """Look up a single work by DOI (``10.x/...``), OpenAlex id (``W123``) or URL."""
        ident = identifier.strip()
        if ident.lower().startswith(("10.", "https://doi.org/")):
            ident = "doi:" + ident.removeprefix("https://doi.org/")
        data = await self.http.get(
            f"{self.BASE}/works/{ident}", {"select": self.SELECT, **self.extra}, as_json=True
        )
        return parse_openalex_work(data) if data else None
