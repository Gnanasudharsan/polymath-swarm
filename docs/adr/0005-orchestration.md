# ADR-0005: Orchestration with LangGraph — DAG dispatch, checkpoints, approval, budget

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

A run must turn a problem into a task DAG, execute independent tasks concurrently, survive
crashes (resume from the last checkpoint), optionally wait for a human to approve the plan, and
stop cleanly at its budget ceiling. Every action must be observable on a shared blackboard.

## Decision

- **Graph shape** (`polymath.graph.builder`): `plan → approve → dispatch ⇄ execute_task → finalize`.
  `plan` and `approve` return `Command(goto=...)`. `dispatch` is followed by a conditional edge
  (`route`) that emits one `Send("execute_task", TaskInput)` per ready task, so a whole wave of
  independent tasks runs in one superstep. The diagram is generated (`polymath graph`) and kept in
  `docs/diagrams/swarm-graph.mmd`; a test fails if it drifts.
- **State vs context**: everything durable (problem, budget, plan, per-task `AgentResult`s, usage,
  iterations, active elapsed time, status, `require_approval`) is in the checkpointed `SwarmState`.
  Live objects (planner, executors, blackboard, `BudgetTracker`) are LangGraph **runtime context**.
  `dispatch` re-syncs the tracker from state on every round, so a resumed run keeps counting.
- **Readiness** is derived, not stored: `task_outcomes()` computes done/failed/skipped/pending from
  results. Dependents of a failed task are skipped. `finalize` writes final statuses into the plan.
- **Wall-clock budget** counts active time only: earlier processes' recorded time plus this process's
  segment. Time paused at an approval prompt or after a crash is not charged.
- **Checkpointing**: `AsyncPostgresSaver` (`langgraph-checkpoint-postgres`). `run_id` = `thread_id`.
  Completed parallel tasks are saved as pending writes, so after `kill -9` only unfinished tasks
  re-run. The serializer uses an explicit **msgpack allowlist** of our Pydantic/enum types rather
  than LangGraph's permissive default.
- **Human-in-the-loop**: `approve` calls `interrupt({...plan...})`. Resume with `True`/`False` or
  `{"approved": false, "feedback": "..."}`, which replans (up to `max_plan_rounds`).
- **Planner**: LLM → `PlanSpec` (structured output) → `to_task_graph()`, which validates snake_case
  ids, uniqueness, exactly one synthesis task, no dependents of synthesis, every task feeding
  synthesis, and DAG-ness (cycle detection). Invalid plans are fed back for repair; after
  `max_repairs` a safe default plan (reason → critique → synthesize) is used.
- **Blackboard**: events are persisted to Postgres (`polymath_events`, ordered by `seq`), then
  published on `polymath:run:<id>:events` for live subscribers. Publishing is best-effort;
  persistence is not.

## Consequences

- Waves are barriers: a task that becomes ready mid-wave waits for the wave to finish. This is simpler
  and fully checkpointable; finer-grained scheduling can come later if profiling shows idle time.
- Top-level enum fields come back from Postgres as plain strings. Code compares by value, and
  `RunSnapshot` coerces `status`.
- Phase 3 maps every specialist role to the Reasoner (`agents/registry.py`); Phase 4 swaps in the
  real specialists without touching the graph.
