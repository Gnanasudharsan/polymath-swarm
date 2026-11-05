"""Critique loop: when claims are refuted or challenged before synthesis, insert a revision
round (reasoner revises → critic reviews) in front of the synthesis task."""

from __future__ import annotations

from polymath.agents.base import AgentResult
from polymath.core.models import (
    AgentRole,
    Claim,
    ClaimStatus,
    Task,
    TaskGraph,
    TaskStatus,
    TaskType,
)
from polymath.graph.state import task_outcomes

TRIGGER = (ClaimStatus.REFUTED, ClaimStatus.CHALLENGED)


def synthesis_id(plan: TaskGraph) -> str | None:
    return next((t.id for t in plan.tasks.values() if t.type is TaskType.SYNTHESIS), None)


def triggering_claims(claims: dict[str, Claim], handled: set[str]) -> list[Claim]:
    return [c for c in claims.values() if c.status in TRIGGER and c.id not in handled]


def add_revision_round(
    plan: TaskGraph, results: dict[str, AgentResult], claims: list[Claim], round_no: int
) -> TaskGraph | None:
    """Return a new plan with ``revise_rN → critique_rN`` feeding synthesis, or ``None`` if the
    synthesis already ran (too late to change the answer)."""
    synth = synthesis_id(plan)
    if synth is None or synth in results:
        return None
    outcome = task_outcomes(plan, results)
    done = sorted(tid for tid, st in outcome.items() if st is TaskStatus.DONE and tid != synth)
    listed = "\n".join(f"- [{c.id}] ({c.status.value}) {c.statement}" for c in claims)
    revise = Task(
        id=f"revise_r{round_no}",
        type=TaskType.REASONING,
        assigned_role=AgentRole.REASONER,
        deps=done,
        description=(
            f"Revision round {round_no}. The critic refuted or challenged these claims:\n{listed}\n"
            "Read the critique and counterexamples in the earlier outputs. Propose corrected, "
            "precise claims (or show the original answer changes), avoiding the flagged errors."
        ),
        inputs={"optional": True, "revision_round": round_no},
    )
    critique = Task(
        id=f"critique_r{round_no}",
        type=TaskType.CRITIQUE,
        assigned_role=AgentRole.CRITIC,
        deps=[revise.id],
        description=f"Review the revised claims from `{revise.id}`; search for counterexamples.",
        inputs={"optional": True, "revision_round": round_no},
    )
    tasks = {tid: t.model_copy(deep=True) for tid, t in plan.tasks.items()}
    tasks[synth] = tasks[synth].model_copy(update={"deps": [*tasks[synth].deps, critique.id]})
    tasks[revise.id] = revise
    tasks[critique.id] = critique
    return TaskGraph(tasks=tasks)


def is_optional(task: Task) -> bool:
    return bool(task.inputs.get("optional"))
