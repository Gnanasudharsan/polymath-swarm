# ADR-0001: Technology stack

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Polymath Swarm must coordinate several LLM-backed specialists on long-running research and
mathematics problems, call external tools safely, and attach verifiable evidence to every claim.
Requirements: resumable runs, parallel task execution, provider independence, strict cost control,
sandboxed code execution, formal proof checking, and interoperability with other agent systems.

## Decision

| Concern | Choice | Why |
|---|---|---|
| Language / tooling | Python 3.12, uv, ruff, mypy strict, pytest | Best ecosystem for LLM + math tooling; uv gives fast, locked, reproducible envs |
| Orchestration | LangGraph | Explicit `StateGraph`, first-class checkpointing (Postgres), interrupts for human-in-the-loop, parallel fan-out |
| LLM access | LiteLLM | One API over Anthropic/OpenAI/Gemini/Ollama; fallbacks, retries, built-in cost tables |
| Primary models | Claude (Anthropic) | Strong reasoning and tool use; others are fallbacks via LiteLLM |
| Tools | MCP (official SDK, FastMCP) | Standard protocol; tools reusable by any MCP client, isolated per server |
| Agent interop | A2A (official SDK) | Standard Agent Cards so the swarm and specialists are callable by external agents |
| Math | SymPy, NumPy/SciPy, Docker-sandboxed Python | Exact symbolic checks plus numerics, with no network and hard resource limits |
| Formal verification | Lean 4 + Mathlib (Docker) via `lean-lsp-mcp` | The de-facto standard for formal math; compile with zero `sorry` = proof |
| Data | Postgres 16 + pgvector, Redis | One durable store for checkpoints, claims and embeddings; Redis for pub/sub, queues, rate limits |
| Models / config | Pydantic v2, pydantic-settings | Typed contracts for every message and tool I/O; env-driven config |
| Observability | structlog, OpenTelemetry → Langfuse (self-hosted) | Vendor-neutral traces with LLM-specific views and cost |
| API / UI | FastAPI + SSE; Next.js, Tailwind, shadcn/ui, React Flow | Async streaming of live runs; graph visualisation of the task DAG |
| Evals | pytest harness + DeepEval; miniF2F, MATH-hard, research-QA | Reproducible, CI-friendly benchmarks covering proof, computation and literature |
| Infra | Docker Compose, GitHub Actions, pre-commit, GHCR | One-command dev stack, gated CI, published images |

## Consequences

- Positive: each layer is replaceable behind a standard protocol (MCP, A2A, LiteLLM, OTel).
- Positive: Postgres serves checkpoints, blackboard history, claims and vectors — fewer moving parts.
- Negative: Lean + Mathlib images are large (multi-GB) and slow to build; mitigated by caching and
  keeping Lean tests behind the `integration` marker.
- Negative: LangGraph and the MCP/A2A SDKs move quickly; versions are pinned and upgrades go through ADRs.
- Postgres defaults to host port 5544 in compose to avoid clashing with local installations.
