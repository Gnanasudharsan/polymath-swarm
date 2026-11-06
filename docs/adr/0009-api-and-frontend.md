# ADR-0009: HTTP API, live streaming and the web UI

- **Status:** Accepted
- **Date:** 2026-11-06

## Context

Phase 7 exposes the swarm over HTTP and adds a UI that shows a run live: the task graph as agents
work, claims with their evidence, cost, plan approval and the final evidence report. It must be
testable end to end without spending on LLM calls.

## Decision

- **FastAPI service** (`polymath.api`, `polymath serve`). `RunManager` runs `SwarmRunner.start/resume`
  as background asyncio tasks. All state lives in the checkpointer and blackboard, so any API process
  can inspect a run, and `POST /runs/{id}/resume` continues one interrupted by a crash or restart.
  Endpoints: `POST /runs`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/stream` (SSE),
  `POST /runs/{id}/approve` (approve, or reject with feedback → replan), `POST /runs/{id}/resume`,
  `GET /health`.
- **Auth**: one API key in the `x-api-key` header (`POLYMATH_API_KEY`), compared in constant time;
  the server refuses to start without it. `/health` is public.
- **SSE by polling the durable store.** The stream replays the run's blackboard history and then
  follows new events (0.4 s poll) until `run_finished` on a finished run, with keep-alives while a
  plan awaits approval. Polling the store keeps replay and live delivery one ordered, gap-free
  sequence; Redis pub/sub remains available for other consumers.
- **Run detail** maps checkpointed state to UI types: tasks, effective task statuses (running =
  started but no result), claims (the gate report's verdicts once synthesis ran), usage and budget.
- **Frontend**: Next.js 16 (App Router, Cache Components), Tailwind, shadcn/ui, React Flow
  (`@xyflow/react`), react-markdown + remark-math + rehype-katex. The browser talks only to a
  Next.js route (`/api/polymath/[...path]`) that adds the API key server-side and streams SSE through,
  so the key never reaches the client. The run view applies SSE events incrementally (task started or
  finished, claim proposed) and re-reads the run on milestone events.
- **Mock LLM** (`polymath serve --mock-llm`): a deterministic scripted model replays one computation
  run (plan → compute → critique → synthesize) for any problem. Programs still run in the real sandbox
  and the gate still re-runs them, so the UI shows genuine verification. Mock usage is notional and
  never written to the spend ledger.
- **E2E**: Playwright starts the real API (in-memory state, mock LLM) and the production Next.js
  build, submits a problem with plan approval, approves, waits for completion over SSE, and asserts a
  gate-verified computation claim and a KaTeX-rendered report. Screenshots go to `docs/images/`. CI
  runs it in an `e2e` job.

## Consequences

- One API key, not multi-user auth. Adequate for a self-hosted research tool; Phase 8 adds rate limits.
- In-flight runs are tied to the API process; after a restart they are resumed explicitly, not
  automatically.
- Mock mode is a UI/e2e fixture, not a model; it ignores the problem text by design.
