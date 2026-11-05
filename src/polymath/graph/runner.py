"""High-level API over the compiled graph: start, resume, inspect and export runs.

``run_id`` is the LangGraph ``thread_id``, so any process with the same checkpointer can
resume a run — after a plan-approval pause, a crash, or ``kill -9``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel

from polymath.blackboard import Blackboard
from polymath.core.budget import BudgetTracker
from polymath.core.models import EventKind, Problem, RunBudget, new_id
from polymath.graph.builder import SwarmGraph
from polymath.graph.context import RunContext
from polymath.graph.state import TERMINAL_STATUSES, RunStatus, SwarmState

ContextFactory = Callable[[BudgetTracker], RunContext]
_UNSET: Any = object()


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    status: RunStatus | None
    values: SwarmState
    interrupt: dict[str, Any] | None
    next_nodes: tuple[str, ...]

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES and not self.next_nodes

    @property
    def awaiting_approval(self) -> bool:
        return self.interrupt is not None and self.interrupt.get("type") == "plan_approval"


def _config(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 500}


class SwarmRunner:
    def __init__(
        self, graph: SwarmGraph, make_context: ContextFactory, blackboard: Blackboard
    ) -> None:
        self.graph = graph
        self.make_context = make_context
        self.blackboard = blackboard

    async def start(
        self,
        problem: Problem,
        *,
        budget: RunBudget | None = None,
        run_id: str | None = None,
        require_approval: bool = False,
    ) -> RunSnapshot:
        run_id = run_id or new_id("run")
        budget = budget or RunBudget()
        await self.blackboard.post(
            run_id, EventKind.RUN_STARTED, problem=problem.model_dump(mode="json"),
            budget=budget.model_dump(),
        )  # fmt: skip
        initial: SwarmState = {
            "run_id": run_id,
            "problem": problem,
            "budget": budget,
            "require_approval": require_approval,
            "status": RunStatus.PLANNING,
        }
        ctx = self.make_context(BudgetTracker(budget))
        await self.graph.ainvoke(initial, _config(run_id), context=ctx)
        return await self.snapshot(run_id)

    async def resume(self, run_id: str, decision: Any = _UNSET) -> RunSnapshot:
        """Continue a run. Pass ``decision`` to answer a pending plan-approval interrupt;
        omit it to pick up a run that stopped mid-way (crash/kill)."""
        current = await self.snapshot(run_id)
        if current.finished:
            return current
        if current.interrupt is not None and decision is _UNSET:
            raise ValueError(f"run {run_id} is waiting for a decision: {current.interrupt}")
        ctx = self.make_context(BudgetTracker(current.values.get("budget") or RunBudget()))
        payload: Any = None if decision is _UNSET else Command(resume=decision)
        await self.graph.ainvoke(payload, _config(run_id), context=ctx)
        return await self.snapshot(run_id)

    async def snapshot(self, run_id: str) -> RunSnapshot:
        snap = await self.graph.aget_state(_config(run_id))
        if not snap.values:
            raise KeyError(f"unknown run {run_id!r}")
        values: SwarmState = snap.values  # type: ignore[assignment]  # untyped in LangGraph
        interrupt = snap.interrupts[0].value if snap.interrupts else None
        return RunSnapshot(
            run_id=run_id,
            status=values.get("status"),
            values=values,
            interrupt=interrupt,
            next_nodes=tuple(snap.next),
        )

    async def export_trace(self, run_id: str) -> dict[str, Any]:
        """Everything needed to audit a run, as plain JSON-compatible data."""
        snap = await self.snapshot(run_id)
        checkpoints = [c async for c in self.graph.aget_state_history(_config(run_id))]
        events = await self.blackboard.history(run_id)
        v = snap.values

        def dump(obj: Any) -> Any:
            return obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj

        results = v.get("results") or {}
        return {
            "run_id": run_id,
            "status": snap.status.value if snap.status else None,
            "stop_reason": v.get("stop_reason", ""),
            "problem": dump(v.get("problem")),
            "budget": dump(v.get("budget")),
            "usage": dump(v.get("usage")),
            "iterations": v.get("iterations", 0),
            "elapsed_s": round(v.get("elapsed_s", 0.0), 3),
            "plan": dump(v.get("plan")),
            "results": {tid: dump(r) for tid, r in results.items()},
            "claims": [c.model_dump(mode="json") for r in results.values() for c in r.claims],
            "answer": v.get("answer", ""),
            "pending_interrupt": snap.interrupt,
            "checkpoints": len(checkpoints),
            "events": [e.model_dump(mode="json") for e in events],
        }
