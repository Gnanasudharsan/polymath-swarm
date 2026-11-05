# Progress

## Phase 3 — Orchestration (2026-11-05)

**Shipped**
- LangGraph `StateGraph`: plan → approve → dispatch ⇄ execute_task (parallel `Send` fan-out) → finalize
- Supervisor/Planner (LLM → validated task DAG with repair loop and safe fallback plan)
- Router with dependency-aware readiness, failure propagation (skip dependents), `max_parallel`
- Postgres checkpointer (msgpack allowlist); resumable runs by `run_id`, including after `kill -9`
- Human-in-the-loop plan approval via `interrupt()`; feedback → replan
- Budget-aware termination (tokens/USD/active wall-clock/iterations) with near-limit warnings
- Blackboard: Postgres event history + Redis pub/sub live stream
- Run trace export (JSON); CLI `solve`, `resume`, `trace`, `graph`; Mermaid diagram in docs; ADR-0005

**Metrics**: 130 unit tests, 26 integration tests (19 in CI, plus 7 lean/network) — all passing.
Concurrency: two 0.5 s tasks finish in < 0.9 s with overlapping execution. SIGKILL test: a run killed
while task `b` was in flight resumed in a new process; `a` ran once, `b` restarted, run completed.

**Known gaps**: every role still runs the Reasoner (specialists arrive in Phase 4); waves are barriers
(a task ready mid-wave waits for the wave).

## Phase 2 — MCP tool layer (2026-11-05)

**Shipped**
- `MCPToolbox` client adapter: mounts in-process or stdio MCP servers, namespaced tools, LiteLLM tool schemas, traced calls
- `sympy` server: simplify / solve / integrate / series / verify_identity, with an input screen and killable child processes
- `sandbox` server: Python in a throwaway container (no network, read-only FS, memory/CPU/PID caps, dropped caps, uid 65534, host-side kill)
- `literature` server: arXiv, Semantic Scholar (search + citations), OpenAlex (search + lookup), Redis cache + shared rate limiter, 429 retries
- `lean` server: Lean 4 + Mathlib v4.35.0 image with the community REPL; check / get_goals / count_sorry / verify_proof
- Compose `tools` profile builds both images; CI builds the sandbox and runs its escape tests; `lean.yml` on demand
- ADR-0003 (tool layer + sandbox), ADR-0004 (Lean via persistent REPL)

**Metrics**: 102 unit tests; 23 integration tests (all passing locally). Sandbox escapes blocked: network, writes outside
/tmp, root uid, infinite loop, 1 GB allocation, fork bomb. Lean: Mathlib load ≈55 s once, then ≈0.1 s per check;
known-good proof verified, wrong proof, `sorry`, and `axiom cheat : False` all rejected.

**Known gaps**: Lean tests are not part of PR CI (image ≈15 GB); one REPL serialises checks (pool later if needed);
Semantic Scholar live test skips when the IP is throttled and no API key is set.

## Phase 1 — Core runtime & LLM gateway (2026-11-04)

**Shipped**
- Core Pydantic models: `Problem`, `Task`, `TaskGraph` (dep + cycle validation, ready-task selection),
  `Claim` (lifecycle state machine), `Evidence`, `AgentMessage`, `BlackboardEvent`, `RunBudget`, `TaskBudget`
- `Settings` (pydantic-settings), structlog logging with trace correlation, OpenTelemetry tracing
- `LLMGateway` on LiteLLM: role→model map, retries with backoff, fallbacks, timeouts, degraded model near budget
- `CostTracker` (tokens + USD by model/role), `BudgetTracker` enforcement
- Structured output helper (schema prompt → lenient parse → Pydantic validation → repair loop)
- `BaseAgent`, versioned prompt files, `ReasonerAgent`, `polymath ask` CLI
- ADR-0002 (gateway design)

**Metrics**: 50 unit tests, 2 integration, 2 live (verified against `gpt-5-mini`; a `polymath ask`
proof of √2 irrationality cost $0.004 for ~2.5k tokens).

**Known gaps**: live tests not yet run against Claude (no `ANTHROPIC_API_KEY` on the dev machine);
claims are proposed only — verification arrives in Phases 2–4.

## Phase 0 — Bootstrap (2026-11-04)

**Shipped**
- GitHub repo, uv project (`src/polymath`), Python 3.12, pinned dependencies, `uv.lock`
- ruff (lint + format), mypy strict on `src/`, pytest with `integration` / `live` markers (skipped by default)
- pre-commit: whitespace/EOF/YAML/TOML checks, private-key + gitleaks secret scanning, ruff, mypy
- GitHub Actions CI: gate job (ruff, format, mypy, unit tests) + integration job (docker compose)
- `docker-compose.yml`: Postgres 16 + pgvector 0.8.7 (host :5544), Redis 7.4 (:6379), healthchecks
- Docs: README with Mermaid architecture, `docs/architecture.md`, ADR-0001 (stack), `CLAUDE.md`
- Typer CLI skeleton (`polymath version`)

**Metrics**: 2 unit tests, 2 integration tests — all passing.

**Known gaps**: no runtime logic yet (Phase 1). Langfuse, sandbox, Lean and API services not yet in compose.
