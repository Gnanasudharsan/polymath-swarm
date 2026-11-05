"""Normalised paper records shared by all literature sources."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["arxiv", "semantic_scholar", "openalex"]


class Paper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    source_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    year: int | None = None
    url: str | None = None
    pdf_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    citation_count: int | None = None
    categories: list[str] = Field(default_factory=list)


class PaperList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    source: Source
    papers: list[Paper]
    total: int | None = None
