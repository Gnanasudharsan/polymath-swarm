"""Postgres + pgvector knowledge store.

Lexical retrieval uses Postgres full-text search (``websearch_to_tsquery`` + ``ts_rank_cd``,
a BM25-like ranking); vector retrieval uses an HNSW cosine index.
"""

from __future__ import annotations

from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from polymath.core.models import Claim
from polymath.memory.models import (
    ChunkRecord,
    PaperRecord,
    RunRecord,
    ScoredChunk,
    StoredClaim,
)


def schema(dim: int) -> str:
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS polymath_papers (
    key TEXT PRIMARY KEY, title TEXT NOT NULL, authors JSONB NOT NULL DEFAULT '[]',
    abstract TEXT NOT NULL DEFAULT '', year INT, url TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS polymath_chunks (
    id TEXT PRIMARY KEY,
    paper_key TEXT NOT NULL REFERENCES polymath_papers(key) ON DELETE CASCADE,
    ord INT NOT NULL, page INT, text TEXT NOT NULL,
    embedding vector({dim}) NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS polymath_chunks_paper ON polymath_chunks (paper_key, ord);
CREATE INDEX IF NOT EXISTS polymath_chunks_tsv ON polymath_chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS polymath_chunks_vec
    ON polymath_chunks USING hnsw (embedding vector_cosine_ops);
CREATE TABLE IF NOT EXISTS polymath_runs (
    run_id TEXT PRIMARY KEY, problem TEXT NOT NULL, status TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '', report JSONB NOT NULL DEFAULT '{{}}',
    embedding vector({dim}) NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS polymath_claims (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, problem TEXT NOT NULL, status TEXT NOT NULL,
    statement TEXT NOT NULL, claim JSONB NOT NULL, embedding vector({dim}) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS polymath_claims_vec
    ON polymath_claims USING hnsw (embedding vector_cosine_ops);
"""


async def _configure(conn: AsyncConnection[Any]) -> None:
    await register_vector_async(conn)


def make_pool(dsn: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(dsn, min_size=1, max_size=8, open=False, configure=_configure)


def _chunk(row: tuple[Any, ...]) -> ChunkRecord:
    return ChunkRecord(id=row[0], paper_key=row[1], ord=row[2], page=row[3], text=row[4])


class PgKnowledgeStore:
    def __init__(self, pool: AsyncConnectionPool, dsn: str, dim: int) -> None:
        self.pool, self.dsn, self.dim = pool, dsn, dim

    async def setup(self) -> None:
        # The extension must exist before the pool's vector adapter can register.
        async with await AsyncConnection.connect(self.dsn) as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.commit()
        async with self.pool.connection() as conn:
            await conn.execute(schema(self.dim))

    async def upsert_paper(self, paper: PaperRecord) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO polymath_papers (key, title, authors, abstract, year, url) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO UPDATE SET "
                "title = EXCLUDED.title, authors = EXCLUDED.authors, "
                "abstract = EXCLUDED.abstract, year = EXCLUDED.year, url = EXCLUDED.url",
                (paper.key, paper.title, Jsonb(paper.authors), paper.abstract, paper.year,
                 paper.url),
            )  # fmt: skip

    async def has_chunks(self, paper_key: str) -> bool:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM polymath_chunks WHERE paper_key = %s LIMIT 1", (paper_key,)
            )
            return await cur.fetchone() is not None

    async def add_chunks(self, chunks: list[ChunkRecord], vectors: list[list[float]]) -> None:
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO polymath_chunks (id, paper_key, ord, page, text, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector) ON CONFLICT (id) DO NOTHING",
                [(c.id, c.paper_key, c.ord, c.page, c.text, v)
                 for c, v in zip(chunks, vectors, strict=True)],
            )  # fmt: skip

    async def paper(self, paper_key: str) -> PaperRecord | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT key, title, authors, abstract, year, url FROM polymath_papers "
                "WHERE key = %s", (paper_key,),
            )  # fmt: skip
            row = await cur.fetchone()
        if row is None:
            return None
        return PaperRecord(key=row[0], title=row[1], authors=row[2], abstract=row[3],
                           year=row[4], url=row[5])  # fmt: skip

    async def paper_text(self, paper_key: str) -> str:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT text FROM polymath_chunks WHERE paper_key = %s ORDER BY ord", (paper_key,)
            )
            return "\n".join(r[0] for r in await cur.fetchall())

    async def lexical(self, query: str, k: int) -> list[ScoredChunk]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, paper_key, ord, page, text, ts_rank_cd(tsv, q, 32) AS score "
                "FROM polymath_chunks, websearch_to_tsquery('english', %s) q "
                "WHERE tsv @@ q ORDER BY score DESC LIMIT %s",
                (_or_query(query), k),
            )
            rows = await cur.fetchall()
        return [ScoredChunk(chunk=_chunk(r), score=float(r[5]), sources=["lexical"]) for r in rows]

    async def vector(self, query_vec: list[float], k: int) -> list[ScoredChunk]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, paper_key, ord, page, text, 1 - (embedding <=> %s::vector) AS sim "
                "FROM polymath_chunks ORDER BY embedding <=> %s::vector LIMIT %s",
                (query_vec, query_vec, k),
            )
            rows = await cur.fetchall()
        return [ScoredChunk(chunk=_chunk(r), score=float(r[5]), sources=["vector"]) for r in rows]

    async def record_run(self, run: RunRecord, vector: list[float]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO polymath_runs (run_id, problem, status, answer, report, embedding, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s::vector, %s) ON CONFLICT (run_id) DO "
                "UPDATE SET status = EXCLUDED.status, answer = EXCLUDED.answer, "
                "report = EXCLUDED.report",
                (run.run_id, run.problem, run.status, run.answer, Jsonb(run.report), vector,
                 run.created_at),
            )  # fmt: skip

    async def add_claims(self, claims: list[StoredClaim], vectors: list[list[float]]) -> None:
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO polymath_claims (id, run_id, problem, status, statement, claim, "
                "embedding) VALUES (%s, %s, %s, %s, %s, %s, %s::vector) ON CONFLICT (id) DO "
                "UPDATE SET status = EXCLUDED.status, claim = EXCLUDED.claim",
                [(sc.claim.id, sc.run_id, sc.problem, sc.claim.status.value, sc.claim.statement,
                  Jsonb(sc.claim.model_dump(mode="json")), v)
                 for sc, v in zip(claims, vectors, strict=True)],
            )  # fmt: skip

    async def similar_claims(
        self, query_vec: list[float], k: int, statuses: tuple[str, ...]
    ) -> list[tuple[StoredClaim, float]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT claim, run_id, problem, 1 - (embedding <=> %s::vector) AS sim "
                "FROM polymath_claims WHERE status = ANY(%s) "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (query_vec, list(statuses), query_vec, k),
            )
            rows = await cur.fetchall()
        return [
            (StoredClaim(claim=Claim.model_validate(r[0]), run_id=r[1], problem=r[2]), float(r[3]))
            for r in rows
        ]


def _or_query(query: str) -> str:
    """websearch syntax ANDs terms; recall is better with OR (ranking still rewards overlap)."""
    words = [w for w in query.replace('"', " ").split() if w.isalnum() or "-" in w]
    return " OR ".join(words) if words else query
