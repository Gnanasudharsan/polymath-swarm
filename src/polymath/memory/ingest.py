"""Paper ingestion: arXiv PDF → text → chunks → embeddings → knowledge store."""

from __future__ import annotations

import httpx

from polymath import __version__
from polymath.core.logging import get_logger
from polymath.mcp_servers.literature.cache import RateLimiter
from polymath.mcp_servers.literature.models import Paper
from polymath.mcp_servers.literature.sources import ArxivClient, arxiv_base_id
from polymath.memory.embeddings import Embedder
from polymath.memory.models import ChunkRecord, KnowledgeStore, PaperRecord
from polymath.memory.text import Page, TextChunk, chunk_pages, chunk_text, pdf_pages

log = get_logger(__name__)
MAX_PDF_BYTES = 25 * 1024 * 1024


def paper_key(paper: Paper) -> str:
    if paper.arxiv_id:
        return f"arxiv:{arxiv_base_id(paper.arxiv_id)}"
    return f"{paper.source}:{paper.source_id}"


class IngestError(RuntimeError):
    pass


class Ingestor:
    def __init__(
        self,
        store: KnowledgeStore,
        embedder: Embedder,
        *,
        arxiv: ArxivClient | None = None,
        http: httpx.AsyncClient | None = None,
        limiter: RateLimiter | None = None,
        batch: int = 64,
    ) -> None:
        self.store, self.embedder = store, embedder
        self.arxiv, self.http, self.limiter, self.batch = arxiv, http, limiter, batch

    async def ingest_text(
        self, record: PaperRecord, text: str | None = None, pages: list[Page] | None = None
    ) -> int:
        """Chunk + embed + store; idempotent per paper. Returns the number of new chunks."""
        await self.store.upsert_paper(record)
        if await self.store.has_chunks(record.key):
            return 0
        chunks: list[TextChunk] = chunk_pages(pages) if pages else chunk_text(text or "")
        if record.abstract:
            # The abstract is chunk 0 so citations of it are always retrievable.
            chunks = [TextChunk(ord=0, page=None, text=f"{record.title}. {record.abstract}"),
                      *(c.model_copy(update={"ord": c.ord + 1}) for c in chunks)]  # fmt: skip
        records = [
            ChunkRecord(id=f"{record.key}#{c.ord}", paper_key=record.key, ord=c.ord,
                        page=c.page, text=c.text)
            for c in chunks
        ]  # fmt: skip
        for i in range(0, len(records), self.batch):
            part = records[i : i + self.batch]
            await self.store.add_chunks(part, await self.embedder.embed([c.text for c in part]))
        log.info("memory.ingested", paper=record.key, chunks=len(records))
        return len(records)

    async def ingest_arxiv(self, arxiv_id: str, *, full_text: bool = True) -> PaperRecord:
        if self.arxiv is None or self.http is None:
            raise IngestError("arXiv ingestion needs an ArxivClient and an HTTP client")
        paper = await self.arxiv.fetch(arxiv_id)
        if paper is None:
            raise IngestError(f"arXiv paper {arxiv_id!r} not found")
        record = PaperRecord(key=paper_key(paper), title=paper.title, authors=paper.authors,
                             abstract=paper.abstract, year=paper.year, url=paper.url)  # fmt: skip
        if await self.store.has_chunks(record.key):
            return record
        pages: list[Page] = []
        if full_text and paper.pdf_url:
            pages = await self._pdf(paper.pdf_url)
        await self.ingest_text(record, pages=pages or None, text="" if pages else None)
        return record

    async def _pdf(self, url: str) -> list[Page]:
        if self.http is None:
            return []
        if self.limiter is not None:
            await self.limiter.acquire("arxiv", 3.0)
        try:
            resp = await self.http.get(
                url, headers={"User-Agent": f"polymath-swarm/{__version__}"},
                follow_redirects=True, timeout=60.0,
            )  # fmt: skip
        except httpx.HTTPError as exc:
            log.warning("memory.pdf_failed", url=url, error=str(exc))
            return []
        if resp.status_code != 200 or len(resp.content) > MAX_PDF_BYTES:
            log.warning("memory.pdf_unavailable", url=url, status=resp.status_code)
            return []
        try:
            return pdf_pages(resp.content)
        except Exception as exc:  # malformed PDFs are common; fall back to the abstract
            log.warning("memory.pdf_unparsable", url=url, error=str(exc))
            return []
