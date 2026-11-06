# ADR-0008: Evaluation harness and observability

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

Phase 6 must show what the swarm buys over a single agent, at what cost, and make every agent and
tool call inspectable. The project runs under a hard LLM spend cap ($5 total), so evaluations must
be small, reproducible and honest about their size.

## Decision

**Observability.** Self-hosted Langfuse v4.76 (web, worker, ClickHouse, MinIO, Redis, Postgres) runs
under the `observability` compose profile, with a pre-created project and local-only keys. When
`LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY` are set, the OTel provider exports over OTLP/HTTP to
`/api/public/otel/v1/traces` with Basic auth. Each graph invocation is a `swarm.run` root span
(Langfuse session = run id); nested under it are `agent.<role>` spans (observation type `agent`),
`mcp.call_tool` spans and `llm.complete` generations carrying `gen_ai.*` model/usage attributes,
cost and truncated input/output. Langfuse v4 is events-only, so the integration test reads back
through `/api/public/v2/observations`.

**Suites.**
- `minif2f`: Lean 4 statements from `yangky11/miniF2F-lean4` (MIT), sampled from the `mathd_*` test
  problems. Statements that no longer elaborate on our Mathlib (the repo targets Lean v4.24, we run
  v4.35) are skipped and listed. Correct = a gate-verified proof whose file contains the benchmark
  statement verbatim (whitespace-insensitive), so a "proof" of a weakened statement does not count.
- `math`: Hendrycks MATH (MIT), Level 5, problems with numeric/fraction answers, via the Hugging Face
  datasets-server. Correct = numeric equivalence of the last `\boxed{}` (else the last number).
- `research_qa`: 8 original questions about well-known papers, with answer keywords. Correct = all
  keywords appear as words in the answer.

Public datasets are fetched and cached under `evals/datasets/cache/` (gitignored), not redistributed.

**Systems.** `single` makes one LLM call per problem with the same per-role models (Reasoner;
Formalizer for Lean; Literature for research QA, asked to cite arXiv ids/DOIs with verbatim quotes)
and is scored by the same checkers (Lean, citation gate). `swarm` is the full pipeline with memory
**disabled**, so answers cannot leak between problems. Each problem gets a fresh `RunBudget` cap.

**Metrics.** accuracy (pass@1), verified-claim rate (gate-verified / all claims; swarm only),
hallucinated-citation rate (citations whose quote is not found in the re-fetched source / all
citations), USD and latency per problem, errors.

**No LLM judges.** Scoring is deterministic. DeepEval was not adopted: its metrics rely on LLM
judges, which would cost budget, add variance and weaken a verification-first evaluation. The
harness is pytest-friendly (pure functions plus a `run_suite` coroutine) and can host DeepEval
metrics later if wanted.

## Consequences

- Results at n ≈ 5–8 per suite are indicative, not leaderboard-grade; the report states n.
- The single-agent baseline gets no repair loop. That is deliberate: it isolates what the swarm's
  architecture (planning, critique, Lean repair/automation, verification gate) adds.
- A verification-first swarm may answer *less* often (it abstains without verified claims), which
  can lower accuracy on suites the baseline guesses well. The report shows both accuracy and
  verified-claim rate so this trade-off is visible.
