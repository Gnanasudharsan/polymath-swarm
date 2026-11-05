"""Runtime (non-checkpointed) dependencies of a swarm run, passed as LangGraph context."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from polymath.agents.base import AgentContext, AgentResult
from polymath.blackboard import Blackboard
from polymath.core.budget import BudgetTracker
from polymath.core.models import AgentRole, Problem, Task, TaskGraph, TaskType
from polymath.llm.cost import LLMUsage


class TaskExecutor(Protocol):
    async def run(self, task: Task, context: AgentContext) -> AgentResult: ...


class Planner(Protocol):
    async def plan(
        self, problem: Problem, feedback: str | None = None
    ) -> tuple[TaskGraph, list[LLMUsage]]: ...


@dataclass
class RunContext:
    planner: Planner
    executors: dict[AgentRole, TaskExecutor]
    blackboard: Blackboard
    budget: BudgetTracker
    require_approval: bool = False
    max_plan_rounds: int = 3
    max_revision_rounds: int = 2
    max_parallel: int = 8
    task_timeout_s: float = 600.0
    # Lean repair rounds with a reasoning model can take a minute per call.
    type_timeouts_s: dict[TaskType, float] = field(
        default_factory=lambda: {TaskType.FORMALIZATION: 1500.0}
    )
    _segment_start: float | None = field(default=None, init=False, repr=False)
    _segment_base: float = field(default=0.0, init=False, repr=False)

    def executor_for(self, role: AgentRole) -> TaskExecutor:
        try:
            return self.executors[role]
        except KeyError:
            raise LookupError(f"no executor registered for role {role.value!r}") from None

    def timeout_for(self, task: Task) -> float:
        if task.budget.max_wall_clock_s is not None:
            return task.budget.max_wall_clock_s
        return self.type_timeouts_s.get(task.type, self.task_timeout_s)

    def elapsed(self, checkpointed_s: float) -> float:
        """Active wall-clock time: what earlier processes recorded plus this process's share.

        Time spent paused (awaiting approval, or after a crash) is not counted.
        """
        now = time.monotonic()
        if self._segment_start is None:
            self._segment_start, self._segment_base = now, checkpointed_s
        return self._segment_base + (now - self._segment_start)
