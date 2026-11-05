# ADR-0007: Memory & knowledge — ingestion, hybrid retrieval, episodic memory

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

Phase 5 gives the swarm long-term memory: full-text papers it can search and cite, and a record of
past runs whose verified results can be reused. Retrieval quality has to be measured, and reuse must
not weaken verification-first guarantees.

## Decision

- **Local models, no API cost.** Embeddings `BAAI/bge-small-en-v1.5` (384-d) and reranker
  `Xenova/ms-marco-MiniLM-L-6-v2` run locally via `fastembed` (ONNX Runtime, Apache-2.0; no PyTorch),
  cached under `~/.cache/polymath`. The BGE query instruction is applied to queries only. Unit tests
  use a deterministic hashing embedder and never download models.
- **PDF text with `pypdf`** (BSD). PyMuPDF was rejected because it is AGPL, which is incompatible
  with an MIT project. Text is cleaned (de-hyphenation, NUL/control characters stripped) and split
  into ~900-character sentence-aware chunks with 150 characters of overlap. The abstract is chunk 0.
- **Store: Postgres 16 + pgvector.** Tables `polymath_papers`, `polymath_chunks` (HNSW cosine index
  and a generated `tsvector` with a GIN index), `polymath_runs`, `polymath_claims` (HNSW). An
  in-memory store with Okapi BM25 backs tests and `--memory` runs.
- **Hybrid retrieval.** Lexical (Postgres FTS `ts_rank_cd` over OR-ed terms; BM25 in memory) and
  dense candidates (40 each) are fused with reciprocal rank fusion (k = 60). The top 25 are reranked
  by the cross-encoder.
- **Measured, not assumed.** `evals/datasets/retrieval` holds 60 original passages (12 topics × 5
  near-neighbours, so other passages in a topic act as hard negatives) and 30 paraphrased queries
  with labels. On Postgres: hybrid + rerank recall@10 = 0.983, MRR = 0.950 (target recall@10 ≥ 0.8).
  The passages were written for this project rather than copied from abstracts.
- **Knowledge MCP server** (`knowledge.search`, `knowledge.ingest_arxiv`, `knowledge.paper_text`)
  keeps memory behind the same tool boundary as every other capability.
- **Full-text citation verification.** The Literature agent ingests its top arXiv hits' PDFs and can
  quote retrieved passages (`location = "full_text"`). The gate verifies a quote against the abstract,
  or else re-ingests the paper from arXiv itself and checks the full text. It also confirms that the
  cited title matches the re-fetched paper.
- **Episodic memory.** `finalize` records every run and all its claims (with embeddings). At the first
  plan of a new run, verified claims whose embedding similarity to the problem is ≥ 0.80 are recalled
  as *new* claims with `origin_run_id` set, keeping their evidence. Recalled claims are verified, so
  checkers do not redo them, but **the gate re-verifies them at synthesis**: memory can save work, it
  cannot launder an unverified claim. The threshold was chosen from measurements: related problems
  score 0.85–0.93, unrelated ones 0.59–0.68.

## Consequences

- No per-query cost; first use downloads about 130 MB of models.
- Postgres FTS is BM25-like rather than exact BM25. Good enough at this scale, and measured.
- Re-verifying recalled claims costs tool time (Lean re-check, program re-run), not LLM tokens.
- Similar-but-not-equivalent claims can be recalled; that is harmless, because recalled claims are
  context for the agents and are re-verified before they can appear in an answer.
