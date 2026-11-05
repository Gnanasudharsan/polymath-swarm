# CLAUDE.md — Polymath Swarm

Project memory for Claude Code sessions. Keep this file current at the end of every phase.

## What this is
**Polymath Swarm** is a verification-first multi-agent system for research and mathematics.
A Supervisor decomposes a problem into a task DAG; specialists (Literature, Reasoner, Compute,
Formalizer, Critic, Synthesizer) collaborate through a shared blackboard. Every claim in the final
answer must carry evidence: a verified citation, a reproduced computation, or a Lean 4 proof with 0 `sorry`.

## Current phase
- Done: Phase 0 (v0.0.0), Phase 1 core runtime (v0.1.0), Phase 2 MCP tools (v0.2.0),
  Phase 3 orchestration (v0.3.0), Phase 4 specialists & verification (v0.4.0)
- Next: Phase 5 — Memory & knowledge (`phase-5-memory`)
- User decisions for LLM work: OpenAI models (no Anthropic key on this machine), **$5 total cap**
  enforced by the spend ledger in `.env` (`.sandbox/spend.jsonl`). Phase 4 spent $0.80.

## What exists (Phase 1)
- `core/models.py` — all domain models; `TaskGraph` validates deps + cycles (Kahn), `ready_tasks()`;
  `Claim.transition()` enforces the lifecycle (verified/refuted are terminal).
- `core/budget.py` — `BudgetTracker` (tokens/USD/wall-clock/iterations, injectable clock), `BudgetExceededError`.
- `core/config.py` — `Settings` (env prefix `POLYMATH_`, `.env`), role→model map; `load_env_file()` puts
  provider keys into `os.environ` for LiteLLM.
- `core/logging.py` (structlog → stderr, trace ids), `core/tracing.py` (OTel, OTLP/HTTP or console).
- `llm/gateway.py` — `LLMGateway.complete(role, messages)`: budget check → model chain (degraded model
  first near limit) → own retries w/ backoff on transient errors → fallback on others → cost + span.
- `llm/cost.py` — `CostTracker`, `estimate_usd` (LiteLLM price map). `llm/structured.py` —
  `complete_structured(gateway, role, messages, Schema)` with repair loop.
- `agents/base.py` — `BaseAgent`, `AgentContext`, `AgentResult`, `ToolSpec`; prompts are
  `agents/prompts/<name>.v<N>.md` loaded by `load_prompt`. `agents/reasoner.py` — `ReasonerAgent`.
- `cli.py` — `polymath ask "..." [--model M] [--max-usd X] [--json]`.
- Tests: fake completion in `tests/conftest.py` (`FakeCompletion`, `settings` fixture).
  Live tests pick Claude Haiku if `ANTHROPIC_API_KEY` else `gpt-5-mini` (dev machine has only OpenAI key).

## What exists (Phase 2)
- `mcp_servers/client.py` — `MCPToolbox({"name": MCPServer | StdioServerParameters})`: async ctx mgr,
  `.tools` (ToolSpec, `server.tool`), `.litellm_tools()` (`server__tool`), `.call(name, args)` →
  `ToolCallResult(structured, text, is_error)`. `stdio_server("sympy")` spawns our server modules.
- Each server: `polymath.mcp_servers.<name>.build_server(...)` (inject deps in tests) + `python -m ...`.
  Raise `ToolError` for user-facing failures (other exceptions are masked by the SDK).
- `sympy/` — ops.py (screened `parse`, pure ops) run in a spawn child with timeout (runner.py).
- `sandbox/` — `DockerSandbox.run(code, timeout_s)` → `SandboxResult`; image `polymath-sandbox:latest`.
- `literature/` — `create_literature(redis, httpx_client, settings)`; `HttpSource` = cache → rate limit
  → GET with 429/5xx retries; parsers in `sources.py` are pure.
- `lean/` — `LeanREPL` (one container, Mathlib imported once, lock, restart on timeout);
  `checker.check/verify` (verify = no errors, no sorry, only propext/Classical.choice/Quot.sound).
- Images: `docker compose --profile tools build` (sandbox, lean ≈15 GB). Lean REPL needs ~3.5 GB RAM.
- Markers: `integration` ⊃ {`network` (public APIs), `lean`}. CI runs
  `integration and not lean and not network`; `lean.yml` is manual.

## What exists (Phase 3)
- `graph/builder.py` — `compile_graph(checkpointer)`; nodes in `graph/nodes.py`
  (plan → approve → dispatch ⇄ execute_task via `Send` → finalize). `mermaid()` → docs/diagrams.
- `graph/state.py` — `SwarmState` (checkpointed), `RunStatus`, `Usage`, `task_outcomes`, `ready_task_ids`.
- `graph/context.py` — `RunContext` (planner, executors, blackboard, BudgetTracker; not checkpointed).
- `graph/planner.py` — `LLMPlanner` (prompt `planner.v1.md`), `to_task_graph` validation, `default_plan`.
- `graph/runner.py` — `SwarmRunner.start/resume/snapshot/export_trace`; `run_id` = thread id.
- `graph/checkpointer.py` — serde with msgpack allowlist; `postgres_checkpointer`, `memory_checkpointer`.
- `graph/infra.py` — `swarm_infra(settings, in_memory=)` → checkpointer + `Blackboard`.
- `blackboard/` — `Blackboard.post/publish/history/subscribe`; `PostgresEventStore` (`polymath_events`).
- `agents/registry.py` — `default_executors(gateway)` (all roles → Reasoner until Phase 4).
- CLI (`cli_swarm.py`): `polymath solve "..." [--approve-plan] [--memory]`, `resume RUN_ID
  [--approve/--reject/--feedback]`, `trace RUN_ID -o f.json`, `graph`.
- Test fakes: `tests/swarm_fakes.py` (FixedPlanner, FakeExecutor, make_factory, run_in_child).

## What exists (Phase 4)
- Specialists (`agents/`): `literature.py`, `reasoner.py`, `compute.py` (explore → assert),
  `formalizer.py` (+ `lean_auto.py`: exact?/omega/... rescue; back-translation sees definitions;
  re-matches proofs to the claim they prove), `critic.py`, `synthesizer.py`. `registry.specialists()`.
- `agents/tools.py` — `Tools` protocol + `MCPTools`; `open_tools(settings)` mounts all servers in-process.
- `verification/` — `evidence.py` (typed payloads, PASS/FAIL/COUNTEREXAMPLE markers, word-level quote
  matching), `claims.py` (merge; refuted > verified > challenged > proposed), `gate.py` (re-checks
  everything), `report.py` (`EvidenceReport`, Markdown).
- Graph: `SwarmState.claims` store; `graph/revision.py` critique loop (≤ 2 rounds, optional tasks
  skipped near budget); synthesis tolerates failed inputs; per-task usage via `llm/usage_scope.py`.
- Planner `ensure_team()` per problem type. Settings `model_profile` (`anthropic`|`openai`),
  `spend_ledger` + `spend_cap_usd` (`llm/ledger.py`).
- Demos: `examples/run_demo.py proof|computation|literature`; outputs committed under `examples/`.
- Test helpers: `tests/agent_fakes.py` (`FakeTools` runs programs locally; `lean_fn` decides by code).

## Gotchas
- Claude 5.x rejects sampling params → gateway always passes `drop_params=True`.
- Catch `openai.OpenAIError` (not `litellm.exceptions.OpenAIError`) as the base of LiteLLM API errors.
- Ruff `TC` rules are disabled: Pydantic needs annotations importable at runtime.
- Postgres in compose is on host port 5544 (5432 is taken locally).
- MCP SDK 2.x: `FastMCP` → `mcp.server.mcpserver.MCPServer`; `mcp.Client(server_or_params)`; pass
  `lifespan=` to the constructor. Don't `pytest.skip` inside a Client context (anyio wraps it).
- Module-scoped async fixtures need `@pytest_asyncio.fixture(scope="module", loop_scope="module")`
  and `pytest.mark.asyncio(loop_scope="module")` on the tests.
- Semantic Scholar throttles unauthenticated IPs hard (429); set `SEMANTIC_SCHOLAR_API_KEY`.
- LangGraph restores top-level TypedDict enum fields from Postgres as plain `str`: compare by value
  (`==`), never `is`. Nested Pydantic fields come back as real enums.
- `graph.add_node(..., input_schema=TaskInput)` needs a `type: ignore[call-overload]` (LangGraph typing).
- **LiteLLM calls `load_dotenv()` on import**, so `.env` values (model profile, spend ledger) enter
  `os.environ`. `tests/conftest.py` strips `POLYMATH_*` per test and sets `POLYMATH_NO_DOTENV=1`;
  never build `Settings` at test-module import time (use the `settings`/`infra_settings` fixtures).
- Never open `MCPToolbox`/`open_tools` in an async-generator fixture: anyio needs enter/exit in
  the same task. Open it inside the test body.
- gpt-5 Formalizer calls take 30–100 s each; formalization has a 1500 s task timeout.
- zsh: don't put a command in a variable (`$R`) — it won't word-split; use a function.

## Architecture (target)
```
Problem → Supervisor/Planner → TaskGraph (Pydantic DAG) → Blackboard (Redis pub/sub + Postgres)
        → Router dispatches ready tasks (parallel where deps allow) → Specialists
        → Verification gate (citation verified | computation reproduced | Lean proof, 0 sorry)
        → Synthesizer: final answer + evidence report (Markdown + JSON) + full trace
```
- Synthesizer may only state `verified` claims; everything else is a conjecture section.
- Budget controller: hard USD/token/wall-clock/iteration ceiling per run; degrade gracefully near it.
- Critique loop: Critic reviews every Reasoner output; refuted claims trigger replanning (max N rounds).
- Adaptive topology: team selected per problem type (proof / computation / literature survey).

Core models live in `src/polymath/core/`: `Problem`, `Task`, `TaskGraph`, `Claim`, `Evidence`,
`AgentMessage`, `BlackboardEvent`, `RunBudget`.

## Stack
Python 3.12 + uv · LangGraph (Postgres checkpointer) · LiteLLM (Claude primary; OpenAI/Gemini/Ollama fallback)
· MCP (FastMCP servers: literature, sandbox, sympy, lean) · A2A SDK · SymPy/NumPy/SciPy · Lean 4 + Mathlib (Docker)
· Postgres 16 + pgvector · Redis · FastAPI + SSE · Next.js + React Flow + shadcn/ui · OpenTelemetry + Langfuse
· pytest + DeepEval (miniF2F, MATH-hard, research-QA) · Docker Compose · GitHub Actions.

## Layout
```
src/polymath/{core,llm,agents,graph,blackboard,memory,mcp_servers,a2a,api}/  cli.py
tests/{unit,integration,live}/   evals/   frontend/   docker/   docs/{architecture.md,adr/}
```

## Commands
```bash
uv sync                          # install deps (incl. dev group)
uv run ruff check .              # lint
uv run ruff format --check .     # format check (drop --check to apply)
uv run mypy src                  # strict type check
uv run pytest -q                 # unit tests (integration/live skipped by default)
uv run pytest -m integration     # Docker-backed tests
uv run pytest -m live            # real LLM calls (costs money)
docker compose up -d --wait      # postgres+pgvector (host :5544), redis (:6379)
uv run pre-commit install        # git hooks
```

## Conventions
- `src/` layout, package `polymath`. Type hints everywhere; mypy strict on `src/`.
- Pydantic v2 for every message/task/claim/tool I/O. Async-first (asyncio, httpx).
- structlog for logs, pydantic-settings for config, OpenTelemetry → Langfuse for traces; every agent call cost-accounted.
- Unit tests never call paid APIs (mock). Markers: `integration` (Docker), `live` (real LLM) — both skipped by default.
- Files ≲ 400 lines. Pin dependency versions. Check installed library versions rather than guessing APIs.
- ADR in `docs/adr/NNNN-title.md` for every significant decision.
- Prompts are versioned files in `src/polymath/agents/prompts/`, never inline strings (Phase 4+).

## Git workflow
- Branch per phase `phase-N-<name>`; Conventional Commits; never `--no-verify`; never commit secrets (`.env` is gitignored).
- **No AI attribution**: no `Co-Authored-By: Claude` trailers in commits, no "Generated with Claude Code"
  footer in PRs. The user must be the only contributor on GitHub.
- Phase gate: ruff check + ruff format --check + mypy src + pytest -q + phase DoD.
- On green: push → `gh pr create` (title `Phase N: <name>`) → `gh pr merge --squash --delete-branch`
  → pull main → `git tag -a v0.N.0 -m "Phase N: <name>"` → push tag.
- After each phase update `PROGRESS.md`, `CHANGELOG.md`, this file. **Pause and ask the user before Phase 4 and Phase 8.**
- Blocked after 3 genuine attempts on one issue → stop and report.

## Phase roadmap
0. Bootstrap — repo, tooling, CI, compose (pg+redis), docs skeleton, ADR-0001
1. Core runtime — models, settings, logging, tracing, LiteLLM gateway, cost tracker, RunBudget, BaseAgent, Reasoner, `polymath ask`
2. MCP tools — literature, sandbox (locked-down Docker), sympy, lean (Lean 4 + Mathlib)
3. Orchestration — LangGraph supervisor, task DAG, router (parallel), blackboard, Postgres checkpointer, HITL, trace export
4. Specialists ⏸ — six agents, claim lifecycle, critic loop, formalizer back-translation, verification gate, synthesizer, adaptive team
5. Memory — paper ingestion → pgvector, hybrid retrieval + rerank, citation verification, episodic memory, claims store
6. Evals — Langfuse, eval harness (miniF2F, MATH-hard, research-QA), single-agent vs swarm report
7. API & UI — FastAPI + SSE, API key auth, Next.js live React Flow graph, claim panel, Playwright e2e
8. Release ⏸ — A2A server/client, security hardening, GHCR images, final README, `v1.0.0`
