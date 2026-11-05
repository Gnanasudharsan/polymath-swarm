"""Fake planner/executors for orchestration tests (importable by spawned child processes)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from polymath.agents.base import AgentContext, AgentResult
from polymath.blackboard import Blackboard
from polymath.core.budget import BudgetTracker
from polymath.core.models import AgentRole, Claim, Problem, Task, TaskGraph, TaskType
from polymath.graph.context import RunContext
from polymath.llm.cost import LLMUsage


def task(tid: str, deps: list[str] | None = None, kind: TaskType = TaskType.REASONING) -> Task:
    role = AgentRole.SYNTHESIZER if kind is TaskType.SYNTHESIS else AgentRole.REASONER
    return Task(id=tid, type=kind, description=f"do {tid}", deps=deps or [], assigned_role=role)


def diamond() -> TaskGraph:
    """a, b independent → synth."""
    return TaskGraph.from_tasks(
        [task("a"), task("b"), task("synth", ["a", "b"], TaskType.SYNTHESIS)]
    )


@dataclass
class FixedPlanner:
    graph: TaskGraph
    calls: list[str | None] = field(default_factory=list)

    async def plan(
        self, problem: Problem, feedback: str | None = None
    ) -> tuple[TaskGraph, list[LLMUsage]]:
        self.calls.append(feedback)
        return self.graph.model_copy(deep=True), []


@dataclass
class FakeExecutor:
    """Sleeps per task id, optionally fails, records (task_id, start, end)."""

    delays: dict[str, float] = field(default_factory=dict)
    fail: set[str] = field(default_factory=set)
    usd_per_task: float = 0.0
    log: list[tuple[str, float, float]] = field(default_factory=list)

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        start = time.monotonic()
        await asyncio.sleep(self.delays.get(task.id, 0.0))
        self.log.append((task.id, start, time.monotonic()))
        if task.id in self.fail:
            raise RuntimeError(f"{task.id} exploded")
        seen = sorted(c.statement for c in context.claims)
        return AgentResult(
            task_id=task.id,
            role=task.assigned_role,
            output=f"{task.id} done; saw {seen}",
            claims=[Claim(statement=f"claim from {task.id}", task_id=task.id)],
            usage=[
                LLMUsage(model="fake", prompt_tokens=10, completion_tokens=5, usd=self.usd_per_task)
            ],
        )

    @property
    def ran(self) -> list[str]:
        return [t for t, _, _ in self.log]


def make_factory(
    planner: FixedPlanner, executor: FakeExecutor, blackboard: Blackboard, **kw: object
):  # type: ignore[no-untyped-def]
    def factory(budget: BudgetTracker) -> RunContext:
        executors = {AgentRole.REASONER: executor, AgentRole.SYNTHESIZER: executor}
        return RunContext(
            planner=planner,
            executors=executors,
            blackboard=blackboard,
            budget=budget,
            **kw,  # type: ignore[arg-type]
        )

    return factory


def run_in_child(run_id: str, dsn: str, redis_url: str) -> None:
    """Spawn target: start a run on real Postgres whose task `b` hangs, so it can be killed."""
    from polymath.core.config import Settings
    from polymath.graph.builder import compile_graph
    from polymath.graph.infra import swarm_infra
    from polymath.graph.runner import SwarmRunner

    settings = Settings(_env_file=None, postgres_dsn=dsn, redis_url=redis_url)  # type: ignore[call-arg]

    async def go() -> None:
        async with swarm_infra(settings) as infra:
            executor = FakeExecutor(delays={"a": 0.0, "b": 600.0})
            runner = SwarmRunner(
                compile_graph(infra.checkpointer),
                make_factory(FixedPlanner(diamond()), executor, infra.blackboard),
                infra.blackboard,
            )
            await runner.start(Problem(statement="kill me"), run_id=run_id)

    asyncio.run(go())
