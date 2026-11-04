from __future__ import annotations

import pytest
from pydantic import ValidationError

from polymath.core.models import (
    AgentRole,
    BlackboardEvent,
    Claim,
    ClaimStatus,
    ClaimTransitionError,
    EventKind,
    Evidence,
    EvidenceKind,
    Problem,
    RunBudget,
    Task,
    TaskGraph,
    TaskGraphError,
    TaskStatus,
    TaskType,
)


def _task(tid: str, deps: list[str] | None = None) -> Task:
    return Task(
        id=tid,
        type=TaskType.REASONING,
        description=f"do {tid}",
        deps=deps or [],
        assigned_role=AgentRole.REASONER,
    )


class TestTaskGraph:
    def test_topological_order_respects_deps(self) -> None:
        g = TaskGraph.from_tasks([_task("c", ["a", "b"]), _task("a"), _task("b", ["a"])])
        order = g.topological_order()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_rejects_cycle(self) -> None:
        with pytest.raises(ValidationError, match="cycle"):
            TaskGraph.from_tasks([_task("a", ["b"]), _task("b", ["a"])])

    def test_rejects_self_dependency(self) -> None:
        with pytest.raises(ValidationError, match="itself"):
            TaskGraph.from_tasks([_task("a", ["a"])])

    def test_rejects_unknown_dependency(self) -> None:
        with pytest.raises(ValidationError, match="unknown"):
            TaskGraph.from_tasks([_task("a", ["ghost"])])

    def test_topological_order_detects_cycle_introduced_by_mutation(self) -> None:
        g = TaskGraph.from_tasks([_task("a"), _task("b", ["a"])])
        g.tasks["a"].deps = ["b"]  # mutating a task bypasses graph-level validation
        with pytest.raises(TaskGraphError, match="cycle"):
            g.topological_order()

    def test_ready_tasks_and_completion(self) -> None:
        g = TaskGraph.from_tasks([_task("a"), _task("b", ["a"]), _task("c")])
        assert {t.id for t in g.ready_tasks()} == {"a", "c"}
        g.tasks["a"].status = TaskStatus.DONE
        assert {t.id for t in g.ready_tasks()} == {"b", "c"}
        assert not g.is_complete()
        g.tasks["b"].status = TaskStatus.DONE
        g.tasks["c"].status = TaskStatus.SKIPPED
        assert g.is_complete()

    def test_json_round_trip(self) -> None:
        g = TaskGraph.from_tasks([_task("a"), _task("b", ["a"])])
        assert TaskGraph.model_validate_json(g.model_dump_json()) == g


class TestClaim:
    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Claim(statement="x", confidence=1.5)

    def test_lifecycle_transitions(self) -> None:
        c = Claim(statement="2 + 2 = 4")
        challenged = c.transition(ClaimStatus.CHALLENGED)
        assert challenged.status is ClaimStatus.CHALLENGED
        assert c.status is ClaimStatus.PROPOSED  # original untouched
        verified = challenged.transition(ClaimStatus.VERIFIED)
        with pytest.raises(ClaimTransitionError):
            verified.transition(ClaimStatus.REFUTED)

    def test_with_evidence_appends(self) -> None:
        ev = Evidence(kind=EvidenceKind.COMPUTATION, payload={"code": "2+2"}, reproducible=True)
        c = Claim(statement="2 + 2 = 4").with_evidence(ev)
        assert c.evidence == [ev]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Claim(statement="x", bogus=1)  # type: ignore[call-arg]


def test_ids_are_prefixed_and_unique() -> None:
    a, b = Problem(statement="p"), Problem(statement="p")
    assert a.id.startswith("prob_") and a.id != b.id


def test_problem_requires_statement() -> None:
    with pytest.raises(ValidationError):
        Problem(statement="")


def test_run_budget_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        RunBudget(max_usd=0)
    assert RunBudget(max_usd=None).max_usd is None


def test_blackboard_event_serialises() -> None:
    evt = BlackboardEvent(run_id="run_1", kind=EventKind.CLAIM_PROPOSED, payload={"id": "c1"})
    assert BlackboardEvent.model_validate_json(evt.model_dump_json()) == evt
