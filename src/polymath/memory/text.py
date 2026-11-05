"""PDF text extraction and chunking."""

from __future__ import annotations

import io
import re

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t\f\v]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# NUL and other C0 control characters (except tab/newline) appear in real PDF extractions and
# are rejected by Postgres text columns.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    text: str


class TextChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ord: int
    page: int | None
    text: str


def clean(text: str) -> str:
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text.replace("\r", "\n"))
    text = _SPACES.sub(" ", text)
    return _MANY_NEWLINES.sub("\n\n", text).strip()


def pdf_pages(data: bytes, *, max_pages: int = 80) -> list[Page]:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages[:max_pages], 1):
        text = clean(page.extract_text() or "")
        if text:
            pages.append(Page(number=i, text=text))
    return pages


def chunk_pages(pages: list[Page], *, size: int = 900, overlap: int = 150) -> list[TextChunk]:
    """Sentence-aware chunks of ~``size`` characters with ``overlap`` carried over."""
    chunks: list[TextChunk] = []
    for page in pages:
        sentences = [s for s in _SENTENCE_END.split(page.text.replace("\n", " ")) if s.strip()]
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > size:
                chunks.append(TextChunk(ord=len(chunks), page=page.number, text=current.strip()))
                current = current[-overlap:] if overlap else ""
            current = f"{current} {sentence}" if current else sentence
        if current.strip():
            chunks.append(TextChunk(ord=len(chunks), page=page.number, text=current.strip()))
    return chunks


def chunk_text(text: str, **kw: int) -> list[TextChunk]:
    return chunk_pages([Page(number=1, text=clean(text))], **kw)
