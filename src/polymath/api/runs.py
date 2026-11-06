"""Background run management for the API: start, approve/resume, inspect, stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from polymath.api.schemas import RunDetail, RunSummary, TaskInfo, UsageOut
from polymath.blackboard import Blackboard
from polymath.core.logging import get_logger
from polymath.core.models import Claim, EventKind, Problem, RunBudget, TaskStatus, new_id
from polymath.graph.runner import RunSnapshot, SwarmRunner
from polymath.graph.state import RunStatus, task_outcomes

log = get_logger(__name__)


class RunNotFoundError(KeyError):
    pass


class RunBusyError(RuntimeError):
    pass


class RunManager:
    """Runs execute as background tasks; state lives in the checkpointer + blackboard, so any
    API process can inspect a run and a restarted one can resume it."""

    def __init__(self, runner: SwarmRunner, blackboard: Blackboard) -> None:
        self.runner, self.blackboard = runner, blackboard
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def _spawn(self, run_id: str, coro: Any) -> None:
        task = asyncio.create_task(coro, name=f"run:{run_id}")
        self._tasks[run_id] = task

        def done(t: asyncio.Task[Any]) -> None:
            self._tasks.pop(run_id, None)
            if not t.cancelled() and t.exception() is not None:
                log.error("api.run_crashed", run_id=run_id, error=repr(t.exception()))

        task.add_done_callback(done)

    def busy(self, run_id: str) -> bool:
        return run_id in self._tasks

    async def start(
        self, problem: str, budget: RunBudget, require_approval: bool, owner: str | None = None
    ) -> str:
        run_id = new_id("run")
        coro = self.runner.start(
            Problem(statement=problem), budget=budget, run_id=run_id,
            require_approval=require_approval, owner=owner,
        )  # fmt: skip
        self._spawn(run_id, coro)
        # Wait until run_started is on the blackboard so the run is immediately listable.
        for _ in range(100):
            if await self.blackboard.history(run_id):
                break
            await asyncio.sleep(0.02)
        return run_id

    async def decide(self, run_id: str, approved: bool, feedback: str | None) -> None:
        snap = await self._snapshot(run_id)
        if self.busy(run_id):
            raise RunBusyError(f"run {run_id} is still executing")
        if not snap.awaiting_approval:
            raise RunBusyError(f"run {run_id} is not waiting for approval")
        decision: Any = {"approved": approved, "feedback": feedback} if feedback else approved
        self._spawn(run_id, self.runner.resume(run_id, decision))

    async def resume(self, run_id: str) -> None:
        snap = await self._snapshot(run_id)
        if self.busy(run_id) or snap.finished:
            raise RunBusyError(f"run {run_id} is running or already finished")
        if snap.awaiting_approval:
            raise RunBusyError(f"run {run_id} is waiting for a decision")
        self._spawn(run_id, self.runner.resume(run_id))

    async def _snapshot(self, run_id: str) -> RunSnapshot:
        try:
            return await self.runner.snapshot(run_id)
        except KeyError as exc:
            raise RunNotFoundError(run_id) from exc

    async def owner_of(self, run_id: str) -> str | None:
        """The user who started the run; raises ``RunNotFoundError`` for unknown runs."""
        events = await self.blackboard.history(run_id)
        if not events:
            try:
                await self.runner.snapshot(run_id)
            except KeyError:
                raise RunNotFoundError(run_id) from None
            return None
        owner = events[0].payload.get("owner")
        return owner if isinstance(owner, str) else None

    async def list(self, limit: int = 50, owner: str | None = None) -> list[RunSummary]:
        starts = await self.blackboard.store.recent_runs(limit, owner=owner)
        out = []
        for e in starts:
            try:
                status = (await self.runner.snapshot(e.run_id)).status
            except KeyError:
                status = RunStatus.PLANNING
            problem = (e.payload.get("problem") or {}).get("statement", "")
            out.append(RunSummary(run_id=e.run_id, problem=problem, status=status,
                                  created_at=e.created_at))  # fmt: skip
        return out

    async def detail(self, run_id: str) -> RunDetail:
        events = await self.blackboard.history(run_id)
        try:
            snap = await self.runner.snapshot(run_id)
        except KeyError:
            if not events:
                raise RunNotFoundError(run_id) from None
            problem = (events[0].payload.get("problem") or {}).get("statement", "")
            return RunDetail(run_id=run_id, status=RunStatus.PLANNING, problem=problem)
        return to_detail(snap, events, busy=self.busy(run_id))

    async def stream(self, run_id: str, poll_s: float = 0.4) -> AsyncIterator[dict[str, Any]]:
        """Replay the run's history, then follow new events until ``run_finished``.

        Polling the durable store (Postgres or memory) keeps replay and live delivery in one
        ordered sequence with no subscribe/replay race.
        """
        sent = 0
        idle = 0
        while True:
            events = await self.blackboard.history(run_id)
            for e in events[sent:]:
                yield {"event": "message", "id": e.id, "data": e.model_dump_json()}
                if e.kind is EventKind.RUN_FINISHED and not self.busy(run_id):
                    snap = await self.runner.snapshot(run_id)
                    if snap.finished:
                        return
            sent = len(events)
            idle += 1
            if idle % 25 == 0:
                yield {"comment": "keep-alive"}
            await asyncio.sleep(poll_s)


def to_detail(snap: RunSnapshot, events: list[Any], *, busy: bool) -> RunDetail:
    v = snap.values
    plan = v.get("plan")
    results = v.get("results") or {}
    tasks: list[TaskInfo] = []
    status: dict[str, TaskStatus] = {}
    if plan is not None:
        tasks = [
            TaskInfo(id=t.id, type=t.type.value, description=t.description, deps=t.deps,
                     assigned_role=t.assigned_role.value)
            for t in plan.tasks.values()
        ]  # fmt: skip
        status = task_outcomes(plan, results)
        started = {e.payload.get("task_id") for e in events if e.kind is EventKind.TASK_STARTED}
        for tid in started:
            if tid in status and status[tid] is TaskStatus.PENDING and tid not in results:
                status[tid] = TaskStatus.RUNNING
    report = v.get("report")
    claims = (
        [Claim.model_validate(rc["claim"]) for b in ("verified", "conjectures", "refuted")
         for rc in report.get(b, [])]
        if report
        else list((v.get("claims") or {}).values())
    )  # fmt: skip
    usage = v.get("usage")
    budget = v.get("budget")
    return RunDetail(
        run_id=snap.run_id,
        status=snap.status,
        stop_reason=v.get("stop_reason", ""),
        problem=v["problem"].statement if v.get("problem") else "",
        tasks=tasks,
        task_status=status,
        claims=claims,
        usage=UsageOut(tokens=usage.tokens, usd=usage.usd) if usage else UsageOut(),
        max_usd=budget.max_usd if budget else None,
        awaiting_approval=snap.awaiting_approval and not busy,
        answer=v.get("answer", ""),
        report_markdown=v.get("report_markdown", ""),
        report=report,
        finished=snap.finished and not busy,
    )
