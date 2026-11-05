"""Retrieval evaluation: recall@k and MRR over a labeled query set."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from polymath.memory.ingest import Ingestor
from polymath.memory.models import PaperRecord
from polymath.memory.retrieval import HybridRetriever, Mode

DATASET = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "retrieval"


class LabeledQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    query: str
    relevant: list[str]


class RetrievalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    queries: int
    recall_at: dict[int, float]
    mrr: float
    misses: list[str]


def load_dataset(path: Path = DATASET) -> tuple[list[dict[str, str]], list[LabeledQuery]]:
    corpus = [json.loads(line) for line in (path / "corpus.jsonl").read_text().splitlines() if line]
    queries = [
        LabeledQuery.model_validate_json(line)
        for line in (path / "queries.jsonl").read_text().splitlines()
        if line
    ]
    return corpus, queries


async def index_corpus(ingestor: Ingestor, corpus: list[dict[str, str]]) -> None:
    """Each passage becomes one single-chunk 'paper' keyed ``eval:<id>``."""
    for row in corpus:
        record = PaperRecord(key=f"eval:{row['id']}", title=row["id"])
        await ingestor.ingest_text(record, text=row["text"])


def passage_id(chunk_paper_key: str) -> str:
    return chunk_paper_key.removeprefix("eval:")


async def evaluate(
    retriever: HybridRetriever,
    queries: list[LabeledQuery],
    mode: Mode,
    ks: tuple[int, ...] = (1, 5, 10),
) -> RetrievalMetrics:
    hits = {k: 0.0 for k in ks}
    rr = 0.0
    misses = []
    for q in queries:
        results = await retriever.search(q.query, k=max(ks), mode=mode)
        ranked = [passage_id(r.chunk.paper_key) for r in results]
        relevant = set(q.relevant)
        for k in ks:
            hits[k] += len(relevant & set(ranked[:k])) / len(relevant)
        first = next((i for i, pid in enumerate(ranked, 1) if pid in relevant), None)
        rr += 1.0 / first if first else 0.0
        if not (relevant & set(ranked[: max(ks)])):
            misses.append(q.id)
    n = len(queries)
    return RetrievalMetrics(
        mode=mode,
        queries=n,
        recall_at={k: round(v / n, 4) for k, v in hits.items()},
        mrr=round(rr / n, 4),
        misses=misses,
    )


def metrics_table(rows: list[RetrievalMetrics]) -> str:
    ks = sorted(rows[0].recall_at) if rows else []
    head = "| mode | " + " | ".join(f"recall@{k}" for k in ks) + " | MRR |"
    sep = "|---|" + "---|" * (len(ks) + 1)
    body = [
        f"| {r.mode} | " + " | ".join(f"{r.recall_at[k]:.3f}" for k in ks) + f" | {r.mrr:.3f} |"
        for r in rows
    ]
    return "\n".join([head, sep, *body])
