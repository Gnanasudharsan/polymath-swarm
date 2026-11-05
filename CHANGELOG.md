# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [0.4.0] - 2026-11-05

### Added
- Literature, Compute, Formalizer, Critic and Synthesizer agents; Reasoner prompt v2.
- Verification gate, typed evidence payloads, claims store, evidence report (Markdown + JSON).
- Critique loop with bounded revision rounds; adaptive team selection; budget degradation.
- Model profiles (`POLYMATH_MODEL_PROFILE`), spend ledger with hard cap.
- End-to-end demos in `examples/`; ADR-0006.

### Fixed
- Spend of failed or timed-out tasks is charged to the run budget.
- Synthesis runs even when some inputs failed.
- Tests are isolated from local `.env` settings (LiteLLM loads `.env` on import).
- Citation quotes match across different TeX typesetting; arXiv keyword queries are AND-ed.

## [0.3.0] - 2026-11-05

### Added
- LangGraph orchestration: planner, parallel dispatch, plan approval, budget termination, finalize.
- Postgres checkpointer with deserialisation allowlist; resumable runs (`polymath resume`).
- Blackboard with Postgres persistence and Redis pub/sub.
- Run trace export (`polymath trace`), `polymath solve`, `polymath graph`; ADR-0005.

### Fixed
- Run status checks after a Postgres restore (enum fields come back as strings).

## [0.2.0] - 2026-11-05

### Added
- MCP client adapter `MCPToolbox`.
- MCP servers: `sympy`, `sandbox` (locked-down Docker), `literature` (arXiv, Semantic Scholar, OpenAlex with Redis cache
  and rate limiting), `lean` (Lean 4 + Mathlib via a persistent REPL).
- Sandbox and Lean Docker images; compose `tools` profile; on-demand Lean CI workflow.
- ADR-0003, ADR-0004.

## [0.1.0] - 2026-11-04

### Added
- Core domain models with DAG validation and claim lifecycle.
- Settings, structured logging, OpenTelemetry tracing.
- LiteLLM gateway: per-role models, retries, fallbacks, timeouts, budget-aware degradation.
- Token/USD cost tracker and run-budget enforcement.
- Structured-output helper with repair loop.
- `BaseAgent`, versioned prompts, Reasoner agent, `polymath ask` CLI.
- ADR-0002.

## [0.0.0] - 2026-11-04

### Added
- Project bootstrap: uv project, src layout, ruff/mypy/pytest/pre-commit configuration.
- GitHub Actions CI running the phase gate and compose-backed integration tests.
- Docker Compose with Postgres 16 + pgvector and Redis.
- README, architecture doc, ADR-0001 (technology stack), CLAUDE.md, MIT license.
