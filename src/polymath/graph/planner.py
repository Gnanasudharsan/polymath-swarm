"""Supervisor / Planner: problem → validated :class:`TaskGraph`."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from polymath.agents.prompts import load_prompt
from polymath.core.logging import get_logger
from polymath.core.models import (
    AgentRole,
    Problem,
    ProblemType,
    Task,
    TaskGraph,
    TaskGraphError,
    TaskType,
)
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway, Message
from polymath.llm.structured import complete_structured

log = get_logger(__name__)

ROLE_FOR_TYPE: dict[TaskType, AgentRole] = {
    TaskType.LITERATURE_SEARCH: AgentRole.LITERATURE,
    TaskType.REASONING: AgentRole.REASONER,
    TaskType.COMPUTATION: AgentRole.COMPUTE,
    TaskType.FORMALIZATION: AgentRole.FORMALIZER,
    TaskType.CRITIQUE: AgentRole.CRITIC,
    TaskType.SYNTHESIS: AgentRole.SYNTHESIZER,
}
_TASK_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_TASKS = 10


class PlannedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="short snake_case id, unique in the plan")
    type: TaskType
    description: str = Field(min_length=1)
    deps: list[str] = Field(default_factory=list)


class PlanSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_type: Literal["proof", "computation", "literature", "mixed"]
    rationale: str = Field(description="One or two sentences on why this team and shape.")
    tasks: list[PlannedTask] = Field(min_length=1, max_length=MAX_TASKS)


class PlanValidationError(ValueError):
    pass


def to_task_graph(spec: PlanSpec) -> TaskGraph:
    """Validate a plan's shape and convert it; raise :class:`PlanValidationError` with a
    message precise enough to feed back to the model."""
    ids = [t.id for t in spec.tasks]
    bad = [i for i in ids if not _TASK_ID.match(i)]
    if bad:
        raise PlanValidationError(f"task ids must be snake_case: {bad}")
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise PlanValidationError(f"duplicate task ids: {dupes}")
    synth = [t.id for t in spec.tasks if t.type is TaskType.SYNTHESIS]
    if len(synth) != 1:
        raise PlanValidationError(f"exactly one synthesis task is required, got {len(synth)}")
    tasks = [
        Task(
            id=t.id,
            type=t.type,
            description=t.description,
            deps=t.deps,
            assigned_role=ROLE_FOR_TYPE[t.type],
        )
        for t in spec.tasks
    ]
    try:
        graph = TaskGraph.from_tasks(tasks)
    except (ValidationError, TaskGraphError) as exc:
        raise PlanValidationError(str(exc)) from exc
    if any(synth[0] in t.deps for t in tasks):
        raise PlanValidationError("no task may depend on the synthesis task")
    orphans = sorted(set(ids) - {synth[0]} - _ancestors(graph, synth[0]))
    if orphans:
        raise PlanValidationError(f"tasks not feeding the synthesis task: {orphans}")
    return graph


def _ancestors(graph: TaskGraph, task_id: str) -> set[str]:
    seen: set[str] = set()
    stack = list(graph.tasks[task_id].deps)
    while stack:
        tid = stack.pop()
        if tid not in seen:
            seen.add(tid)
            stack.extend(graph.tasks[tid].deps)
    return seen


def default_plan(problem: Problem) -> TaskGraph:
    """Fallback when the planner cannot produce a valid plan: reason, critique, synthesise."""
    return TaskGraph.from_tasks(
        [
            Task(id="reason", type=TaskType.REASONING, assigned_role=AgentRole.REASONER,
                 description=f"Work out a rigorous answer to: {problem.statement}"),
            Task(id="critique", type=TaskType.CRITIQUE, assigned_role=AgentRole.CRITIC,
                 deps=["reason"], description="Review the reasoning for errors and gaps."),
            Task(id="synthesize", type=TaskType.SYNTHESIS, assigned_role=AgentRole.SYNTHESIZER,
                 deps=["reason", "critique"], description="Write the final answer."),
        ]
    )  # fmt: skip


class LLMPlanner:
    def __init__(self, gateway: LLMGateway, *, max_repairs: int = 2) -> None:
        self.gateway = gateway
        self.max_repairs = max_repairs

    async def plan(
        self, problem: Problem, feedback: str | None = None
    ) -> tuple[TaskGraph, list[LLMUsage]]:
        user = f"## Problem\n{problem.statement}"
        if problem.context:
            user += f"\n\n## Background\n{problem.context}"
        if feedback:
            user += f"\n\n## Reviewer feedback on the previous plan\n{feedback}"
        messages: list[Message] = [
            {"role": "system", "content": load_prompt("planner")},
            {"role": "user", "content": user},
        ]
        usage: list[LLMUsage] = []
        for attempt in range(self.max_repairs + 1):
            result = await complete_structured(
                self.gateway, AgentRole.SUPERVISOR, messages, PlanSpec
            )
            usage.extend(r.usage for r in result.responses)
            try:
                graph = to_task_graph(result.value)
            except PlanValidationError as exc:
                log.info("planner.invalid_plan", attempt=attempt + 1, error=str(exc))
                messages = [
                    *messages,
                    {"role": "assistant", "content": result.value.model_dump_json()},
                    {"role": "user", "content": f"That plan is invalid: {exc}. Fix it."},
                ]
                continue
            if problem.problem_type is None:
                problem.problem_type = ProblemType(result.value.problem_type)
            return graph, usage
        log.warning("planner.fallback_plan", problem_id=problem.id)
        return default_plan(problem), usage
