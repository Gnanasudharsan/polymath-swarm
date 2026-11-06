# Progress

## v1.1.0 — API users and shared rate limits (2026-11-06)

**Shipped** (closes two v1.0 known gaps)
- Named API users with SHA-256-hashed keys, admins, `polymath keys new`, `GET /me`
- Run ownership over REST and A2A: non-admins see only their own runs; others' runs return 404
- Redis-backed sliding-window rate limiter shared by all API replicas (atomic Lua script, Redis
  clock, fails open); on in the compose app stack
- ADR-0011; README, security doc and `.env.example` updated

**Metrics**: 222 unit tests, 40 integration tests. LLM spend: 0 USD (ledger unchanged at 2.62 of 5 USD).

**Still open**: Lean image not published (about 15 GB); Anthropic profile untested live (no key);
small eval samples; no per-user spend quotas.

## Phase 8 — A2A interop, hardening, release (2026-11-06)

**Shipped**
- A2A: the swarm and five specialists as A2A agents (Agent Cards + JSON-RPC, API-key auth); delegation of
  any role to an external A2A agent, with replies treated as untrusted, evidence-free proposals
- Security: per-client API rate limits; sanitiser for untrusted paper text and A2A replies; dependency
  audit; threat model in `docs/security.md`
- One-command stack (`docker compose --profile app up -d --build`: Postgres, Redis, API, web, sandbox
  image); API and web images; GHCR release workflow
- Final README (problem, architecture, results, demo GIF, quickstart, limitations), ADR-0010,
  `examples/a2a_client.py`
- Fixed: the literature agent's full-text path (helpers existed since Phase 5 but `run()` never called
  them); task-graph flicker in the UI

**Metrics**: 215 unit tests, 38 integration tests, 1 e2e test. Clean-machine check: fresh clone, only
the README's steps, both quickstart options passed. Total LLM spend for the whole project: about 2.62 USD of the 5 USD cap (Phase 4: 0.80, Phase 5: 0.37, Phase 6: 1.41, Phase 8: 0.04; Phases 0-3 and 7: about 0).

**Known gaps**: single shared API key; per-process rate limits; Lean image not published (15 GB);
Anthropic profile untested live; small eval samples.

## Phase 7 — API & live frontend (2026-11-06)

**Shipped**
- FastAPI service (`polymath serve`): `POST /runs`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/stream`
  (SSE replay + live), `POST /runs/{id}/approve`, `POST /runs/{id}/resume`, `/health`; API-key auth
- Next.js 16 UI: problem input (budget, plan approval), live React Flow task graph, claim panel with evidence
  badges, cost meter, approve / replan-with-feedback, KaTeX evidence report, activity stream; server-side
  proxy keeps the key out of the browser
- Deterministic mock-LLM mode for UI development and e2e (real sandbox + gate, no cost, no ledger)
- Playwright e2e (plan approval -> live graph -> verified claim -> KaTeX report) in CI; screenshots in README
- ADR-0009

**Metrics**: 202 unit tests, 37 integration tests, 1 e2e test, all passing. LLM spend in Phase 7: 0 USD
(ledger unchanged at 2.58 of 5 USD).

**Known gaps**: single shared API key (no users); runs interrupted by an API restart must be resumed
explicitly; mock mode always replays the same computation run.

## Phase 6 — Evals, observability, cost (2026-11-05)

**Shipped**
- Self-hosted Langfuse v4.76 (compose profile `observability`) with OTLP trace export: one trace per run,
  spans per agent task and tool call, LLM generations with model, tokens and cost; verified by an
  integration test against Langfuse's API
- Eval harness `polymath eval`: miniF2F (Lean 4), MATH Level 5 and an original research-QA set;
  single-agent baseline vs swarm; deterministic scoring; metrics: accuracy, verified-claim rate,
  hallucinated-citation rate, cost and latency per problem; Markdown + chart report
- Report committed: `evals/reports/2026-11-05/` (numbers in the README)
- Planner v2 (value questions -> compute); quota fail-fast; harness survives crashing attempts
- ADR-0008

**Metrics**: 193 unit tests, 37 integration tests. Eval (n = 3/6/6): miniF2F 0% -> 33%, MATH 100% -> 100%
(64% of swarm claims verified), research QA 67% -> 33% accuracy but hallucinated citations 50% -> 0%.
Eval spend about 1.25 USD; Phase 6 total about 1.41 USD (ledger 2.58 of 5 USD).

**Known gaps**: tiny samples (budget); miniF2F sampled from the easier `mathd_*` half; strict keyword
scoring penalises paraphrase; DeepEval not used (deterministic scorers instead, ADR-0008).

## Phase 5 — Memory & knowledge (2026-11-05)

**Shipped**
- Paper ingestion: arXiv PDF → pypdf text → sentence-aware chunks → local bge-small embeddings → Postgres + pgvector
- Hybrid retrieval: Postgres full-text + HNSW vectors, reciprocal rank fusion, local cross-encoder rerank
- `knowledge` MCP server; Literature agent ingests top arXiv hits and cites full-text passages
- Citation verification against the re-ingested full text (and title match)
- Episodic memory and claims store: runs and gate verdicts recorded; verified claims recalled into
  related runs as proposed claims with provenance, re-verified by the gate
- Labeled retrieval eval set (original passages) and runner; ADR-0007; model cache in CI

**Metrics**: 176 unit tests, 36 integration tests, all passing. Retrieval (Postgres, real models):
hybrid + rerank recall@10 0.983, MRR 0.950 (lexical 0.983 / 0.897, vector 0.933 / 0.867). Live reuse
demo: a verified theorem from an earlier run was recalled (similarity 0.934) and re-verified ($0.096).

**Fixed along the way**: cross-run laundering (claims could be remembered as verified after the gate
rejected them), test data leaking into shared memory, NUL bytes from PDFs, missing BGE query prefix.

**Known gaps**: lexical side is Postgres FTS (BM25-like, not exact BM25); recall can return claims
that the Reasoner then re-proposes (no semantic de-duplication); the eval corpus is small (60 passages).

## Phase 4 — Specialists & verification loop (2026-11-05)

**Shipped**
- Six specialists with versioned prompts: Literature (verbatim-quote citations), Reasoner, Compute
  (explore → assert, sandbox PASS/FAIL programs), Formalizer (Lean repair loop, Mathlib automation
  rescue, back-translation + equivalence judge, proof re-matching), Critic (counterexample searches),
  Synthesizer (cites only verified claims)
- Claim lifecycle across tasks (run-wide claims store with merge rules)
- Verification gate that independently re-checks every piece of evidence
- Critique loop: refuted/challenged claims insert revision rounds before synthesis (≤ 2)
- Adaptive team per problem type; budget degradation skips optional work near the ceiling
- Evidence report (Markdown + JSON); `polymath solve` writes it
- Model profiles (`anthropic` default, `openai`) and a cross-run spend ledger with a hard cap
- Three live demos in `examples/` (proof, computation, literature), each with a verified report
- ADR-0006

**Metrics**: 162 unit tests, 30 integration tests, all passing. Demo cost: proof $0.063, computation
$0.011, literature $0.007. Total Phase 4 LLM spend incl. development runs: $0.80 of the $5 cap.
The false claim "n² + n + 41 is prime for all n" is refuted by the Critic (n = 40) and the gate
reproduces it, with fake tools and on the real Docker sandbox.

**Known gaps**: literature results vary between runs (search ranking); citation checks use titles and
abstracts only (full text in Phase 5); the equivalence judge is an LLM (it can only block proofs, not
admit them); duplicate claims from different agents are not merged by meaning.

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
