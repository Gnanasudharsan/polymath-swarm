"""LangGraph state for a swarm run. Everything here is checkpointed, so it must be durable data."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.base import AgentResult
from polymath.core.models import Claim, Problem, RunBudget, TaskGraph, TaskStatus, TaskType
from polymath.verification.claims import merge_claims


class RunStatus(StrEnum):
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    REJECTED = "rejected"
    FAILED = "failed"


TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.BUDGET_EXHAUSTED, RunStatus.REJECTED, RunStatus.FAILED}
)


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tokens: int = Field(default=0, ge=0)
    usd: float = Field(default=0.0, ge=0)

    def __add__(self, other: Usage) -> Usage:
        return Usage(tokens=self.tokens + other.tokens, usd=self.usd + other.usd)


def merge_results(
    left: dict[str, AgentResult] | None, right: dict[str, AgentResult] | None
) -> dict[str, AgentResult]:
    return {**(left or {}), **(right or {})}


def add_usage(left: Usage | None, right: Usage | None) -> Usage:
    return (left or Usage()) + (right or Usage())


class SwarmState(TypedDict, total=False):
    run_id: str
    problem: Problem
    budget: RunBudget
    require_approval: bool
    plan: TaskGraph
    plan_rounds: int
    plan_feedback: str
    approved: bool
    results: Annotated[dict[str, AgentResult], merge_results]
    claims: Annotated[dict[str, Claim], merge_claims]
    revision_rounds: int
    handled_claims: list[str]
    report: dict[str, Any]
    report_markdown: str
    usage: Annotated[Usage, add_usage]
    iterations: int
    elapsed_s: float
    status: RunStatus
    stop_reason: str
    answer: str


_BAD = (TaskStatus.FAILED, TaskStatus.SKIPPED)
_TERMINAL = (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED)


def _tolerant(plan: TaskGraph, tid: str) -> bool:
    """Synthesis must report on whatever happened, so failed inputs never skip it."""
    return plan.tasks[tid].type is TaskType.SYNTHESIS


def task_outcomes(plan: TaskGraph, results: dict[str, AgentResult]) -> dict[str, TaskStatus]:
    """Effective status of every task: done/failed from results; skipped if a dependency
    failed or was skipped (except for synthesis, which tolerates failures); else pending."""
    outcome: dict[str, TaskStatus] = {}
    for tid in plan.topological_order():
        result = results.get(tid)
        deps = plan.tasks[tid].deps
        if result is not None:
            outcome[tid] = TaskStatus.DONE if result.success else TaskStatus.FAILED
        elif _tolerant(plan, tid):
            all_bad = bool(deps) and all(outcome[d] in _BAD for d in deps)
            outcome[tid] = TaskStatus.SKIPPED if all_bad else TaskStatus.PENDING
        elif any(outcome[d] in _BAD for d in deps):
            outcome[tid] = TaskStatus.SKIPPED
        else:
            outcome[tid] = TaskStatus.PENDING
    return outcome


def ready_task_ids(plan: TaskGraph, results: dict[str, AgentResult]) -> list[str]:
    """Pending tasks whose dependencies are satisfied, in topological order: all succeeded, or
    (for synthesis) all finished one way or another."""
    outcome = task_outcomes(plan, results)
    ready = []
    for tid in plan.topological_order():
        if outcome[tid] is not TaskStatus.PENDING:
            continue
        deps = [outcome[d] for d in plan.tasks[tid].deps]
        needed = _TERMINAL if _tolerant(plan, tid) else (TaskStatus.DONE,)
        if all(d in needed for d in deps):
            ready.append(tid)
    return ready
