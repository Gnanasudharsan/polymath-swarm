# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [1.1.0] - 2026-11-06

### Added
- Named API users (`POLYMATH_API_USERS`, SHA-256-hashed keys) and admins (`POLYMATH_API_ADMINS`);
  `polymath keys new <user>`; `GET /me`.
- Run ownership: REST and A2A runs record their owner; non-admins see only their own runs (others
  get 404). The v1.0 `POLYMATH_API_KEY` still works as the user `admin`.
- Redis-backed rate limiter shared across API replicas (`POLYMATH_RATE_LIMIT_BACKEND=redis`, on in
  the compose app stack). ADR-0011.

### Changed
- Empty environment variables are ignored by settings (compose passes unset values as empty strings).

## [1.0.0] - 2026-11-06

### Added
- A2A server: the swarm and each specialist as A2A agents (Agent Cards, JSON-RPC, API-key auth).
- A2A client delegation (`POLYMATH_A2A_DELEGATES`) with untrusted, evidence-free handling of replies.
- API rate limits; sanitisation of untrusted text (papers, passages, A2A replies); `docs/security.md`.
- API and web Docker images; one-command `app` compose profile; GHCR release workflow.
- Final README with demo GIF; ADR-0010; `examples/a2a_client.py`.

### Fixed
- **Correction to 0.5.0:** the literature agent's full-text citation path was not wired into `run()`,
  so full-text passages were never used, although the release notes said they were. The gate's
  full-text check worked; only the agent never produced full-text quotes. It is now wired in and
  covered by a regression test.
- Task-graph flicker on live updates in the UI.

## [0.7.0] - 2026-11-06

### Added
- FastAPI service with run creation, inspection, plan approval, resume and SSE streaming; API-key auth.
- `polymath serve` (with `--memory` and a deterministic `--mock-llm` mode).
- Next.js web UI: live task graph, claims with evidence badges, cost meter, plan approval, KaTeX report.
- Playwright end-to-end test and CI job; README screenshots; ADR-0009.

## [0.6.0] - 2026-11-05

### Added
- Self-hosted Langfuse in compose; OTLP export with run/agent/tool/generation spans.
- Eval harness and `polymath eval` (miniF2F, MATH Level 5, research QA; single vs swarm).
- Combined eval report with charts; re-run tooling for infrastructure failures; ADR-0008.

### Fixed
- Planner routes value questions to computation instead of formalization (planner v2).
- Provider quota exhaustion fails fast instead of being retried as a rate limit.
- An unmounted tool no longer crashes a run; one crashing eval attempt no longer loses a suite.
- Tests no longer let LiteLLM load the local `.env` (`LITELLM_MODE=PRODUCTION`).

## [0.5.0] - 2026-11-05

### Added
- Knowledge store on Postgres + pgvector; arXiv PDF ingestion; hybrid retrieval with RRF and rerank.
- `knowledge` MCP server; full-text citations and full-text citation verification.
- Episodic memory and claims store with recall of verified claims into related runs.
- Retrieval eval set and runner; `reuse` demo; ADR-0007.

### Fixed
- Memory only stores the gate's verdicts (no cross-run laundering of rejected claims).
- PDF text is stripped of NUL/control characters.

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
