"""Core domain models shared by every layer of the swarm.

Everything that crosses a boundary (agent ↔ agent, agent ↔ tool, process ↔ store) is one of
these Pydantic models, so it can be validated, serialised to JSON and persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def new_id(prefix: str) -> str:
    """Short, prefixed, collision-resistant identifier (e.g. ``task_3f9a1c2b4d5e``)."""
    return f"{prefix}_{uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- enums


class ProblemType(StrEnum):
    PROOF = "proof"
    COMPUTATION = "computation"
    LITERATURE = "literature"
    MIXED = "mixed"


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    LITERATURE = "literature"
    REASONER = "reasoner"
    COMPUTE = "compute"
    FORMALIZER = "formalizer"
    CRITIC = "critic"
    SYNTHESIZER = "synthesizer"


class TaskType(StrEnum):
    LITERATURE_SEARCH = "literature_search"
    REASONING = "reasoning"
    COMPUTATION = "computation"
    FORMALIZATION = "formalization"
    CRITIQUE = "critique"
    SYNTHESIS = "synthesis"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    CHALLENGED = "challenged"
    VERIFIED = "verified"
    REFUTED = "refuted"


class EvidenceKind(StrEnum):
    CITATION = "citation"
    COMPUTATION = "computation"
    FORMAL_PROOF = "formal_proof"
    CRITIQUE = "critique"


class EventKind(StrEnum):
    RUN_STARTED = "run_started"
    PLAN_CREATED = "plan_created"
    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    CLAIM_PROPOSED = "claim_proposed"
    CLAIM_UPDATED = "claim_updated"
    MESSAGE = "message"
    BUDGET_WARNING = "budget_warning"
    RUN_FINISHED = "run_finished"


# --------------------------------------------------------------------------- budget


class RunBudget(_Model):
    """Hard ceilings for a run. ``None`` means unlimited for that dimension."""

    max_tokens: int | None = Field(default=200_000, gt=0)
    max_usd: float | None = Field(default=2.0, gt=0)
    max_wall_clock_s: float | None = Field(default=600.0, gt=0)
    max_iterations: int | None = Field(default=50, gt=0)


class TaskBudget(_Model):
    """Optional per-task ceilings, enforced inside the run budget."""

    max_tokens: int | None = Field(default=None, gt=0)
    max_usd: float | None = Field(default=None, gt=0)
    max_wall_clock_s: float | None = Field(default=None, gt=0)


# --------------------------------------------------------------------------- problem & tasks


class Problem(_Model):
    id: str = Field(default_factory=lambda: new_id("prob"))
    statement: str = Field(min_length=1)
    problem_type: ProblemType | None = None
    context: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Task(_Model):
    id: str = Field(default_factory=lambda: new_id("task"))
    type: TaskType
    description: str = Field(min_length=1)
    deps: list[str] = Field(default_factory=list)
    assigned_role: AgentRole
    status: TaskStatus = TaskStatus.PENDING
    budget: TaskBudget = Field(default_factory=TaskBudget)
    inputs: dict[str, Any] = Field(default_factory=dict)


class TaskGraphError(ValueError):
    """Raised for structurally invalid task graphs (unknown deps, cycles)."""


class TaskGraph(_Model):
    """A DAG of tasks keyed by id. Validation rejects dangling deps and cycles."""

    tasks: dict[str, Task] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_dag(self) -> Self:
        for task_id, task in self.tasks.items():
            if task.id != task_id:
                raise TaskGraphError(f"task key {task_id!r} does not match task.id {task.id!r}")
            missing = [d for d in task.deps if d not in self.tasks]
            if missing:
                raise TaskGraphError(f"task {task_id!r} depends on unknown tasks {missing}")
            if task_id in task.deps:
                raise TaskGraphError(f"task {task_id!r} depends on itself")
        self.topological_order()  # raises on cycles
        return self

    @classmethod
    def from_tasks(cls, tasks: list[Task]) -> TaskGraph:
        return cls(tasks={t.id: t for t in tasks})

    def topological_order(self) -> list[str]:
        """Kahn's algorithm; deterministic (insertion order) for equal-rank tasks."""
        indegree = {tid: len(t.deps) for tid, t in self.tasks.items()}
        dependents: dict[str, list[str]] = {tid: [] for tid in self.tasks}
        for tid, task in self.tasks.items():
            for dep in task.deps:
                dependents[dep].append(tid)
        queue = [tid for tid, deg in indegree.items() if deg == 0]
        order: list[str] = []
        while queue:
            tid = queue.pop(0)
            order.append(tid)
            for child in dependents[tid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if len(order) != len(self.tasks):
            cyclic = sorted(tid for tid, deg in indegree.items() if deg > 0)
            raise TaskGraphError(f"task graph contains a cycle among {cyclic}")
        return order

    def ready_tasks(self) -> list[Task]:
        """Pending tasks whose dependencies are all done."""
        return [
            t
            for t in self.tasks.values()
            if t.status is TaskStatus.PENDING
            and all(self.tasks[d].status is TaskStatus.DONE for d in t.deps)
        ]

    def is_complete(self) -> bool:
        terminal = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED}
        return all(t.status in terminal for t in self.tasks.values())


# --------------------------------------------------------------------------- claims & evidence


class Evidence(_Model):
    id: str = Field(default_factory=lambda: new_id("ev"))
    kind: EvidenceKind
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    reproducible: bool = False
    source_agent: AgentRole | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ClaimTransitionError(ValueError):
    """Raised for an illegal claim status change."""


_CLAIM_TRANSITIONS: dict[ClaimStatus, frozenset[ClaimStatus]] = {
    ClaimStatus.PROPOSED: frozenset(
        {ClaimStatus.CHALLENGED, ClaimStatus.VERIFIED, ClaimStatus.REFUTED}
    ),
    ClaimStatus.CHALLENGED: frozenset(
        {ClaimStatus.PROPOSED, ClaimStatus.VERIFIED, ClaimStatus.REFUTED}
    ),
    ClaimStatus.VERIFIED: frozenset(),
    ClaimStatus.REFUTED: frozenset(),
}


class Claim(_Model):
    id: str = Field(default_factory=lambda: new_id("claim"))
    statement: str = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: ClaimStatus = ClaimStatus.PROPOSED
    evidence: list[Evidence] = Field(default_factory=list)
    proposed_by: AgentRole | None = None
    task_id: str | None = None
    origin_run_id: str | None = Field(
        default=None, description="Set when the claim was recalled from an earlier run's memory."
    )
    created_at: datetime = Field(default_factory=utcnow)

    def transition(self, new_status: ClaimStatus) -> Claim:
        """Return a copy in ``new_status``; raise if the lifecycle forbids it."""
        if new_status not in _CLAIM_TRANSITIONS[self.status]:
            raise ClaimTransitionError(f"cannot move claim from {self.status} to {new_status}")
        return self.model_copy(update={"status": new_status})

    def with_evidence(self, evidence: Evidence) -> Claim:
        return self.model_copy(update={"evidence": [*self.evidence, evidence]})


# --------------------------------------------------------------------------- messaging


class AgentMessage(_Model):
    id: str = Field(default_factory=lambda: new_id("msg"))
    sender: AgentRole
    recipient: AgentRole | None = None  # None = broadcast to the blackboard
    task_id: str | None = None
    content: str
    claims: list[Claim] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class BlackboardEvent(_Model):
    id: str = Field(default_factory=lambda: new_id("evt"))
    run_id: str
    kind: EventKind
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
