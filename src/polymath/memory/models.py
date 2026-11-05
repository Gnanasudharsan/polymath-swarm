"""Records kept in the knowledge store, and the store protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from polymath.core.models import Claim, utcnow


class PaperRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="'arxiv:<id>' or 'openalex:<id>' or 'local:<name>'")
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    year: int | None = None
    url: str | None = None


class ChunkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    paper_key: str
    ord: int
    page: int | None
    text: str


class ScoredChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk: ChunkRecord
    score: float
    sources: list[str] = Field(default_factory=list, description="which retrievers found it")


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    problem: str
    status: str
    answer: str = ""
    report: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class StoredClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: Claim
    run_id: str
    problem: str


class KnowledgeStore(Protocol):
    async def setup(self) -> None: ...
    async def upsert_paper(self, paper: PaperRecord) -> None: ...
    async def has_chunks(self, paper_key: str) -> bool: ...
    async def add_chunks(self, chunks: list[ChunkRecord], vectors: list[list[float]]) -> None: ...
    async def paper(self, paper_key: str) -> PaperRecord | None: ...
    async def paper_text(self, paper_key: str) -> str: ...
    async def lexical(self, query: str, k: int) -> list[ScoredChunk]: ...
    async def vector(self, query_vec: list[float], k: int) -> list[ScoredChunk]: ...
    async def record_run(self, run: RunRecord, vector: list[float]) -> None: ...
    async def add_claims(self, claims: list[StoredClaim], vectors: list[list[float]]) -> None: ...
    async def similar_claims(
        self, query_vec: list[float], k: int, statuses: tuple[str, ...]
    ) -> list[tuple[StoredClaim, float]]: ...
