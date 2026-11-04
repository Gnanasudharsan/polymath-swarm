# CLAUDE.md — Polymath Swarm

Project memory for Claude Code sessions. Keep this file current at the end of every phase.

## What this is
**Polymath Swarm** is a verification-first multi-agent system for research and mathematics.
A Supervisor decomposes a problem into a task DAG; specialists (Literature, Reasoner, Compute,
Formalizer, Critic, Synthesizer) collaborate through a shared blackboard. Every claim in the final
answer must carry evidence: a verified citation, a reproduced computation, or a Lean 4 proof with 0 `sorry`.

## Current phase
- **Phase 0 — Bootstrap** (branch `phase-0-bootstrap`, tag `v0.0.0`) — in progress
- Next: Phase 1 — Core runtime & LLM gateway

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
