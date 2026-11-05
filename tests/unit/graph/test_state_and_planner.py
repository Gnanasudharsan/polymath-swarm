from __future__ import annotations

import json

import pytest

from polymath.agents.base import AgentResult
from polymath.core.config import Settings
from polymath.core.models import AgentRole, Problem, TaskStatus, TaskType
from polymath.graph.planner import (
    LLMPlanner,
    PlannedTask,
    PlanSpec,
    PlanValidationError,
    to_task_graph,
)
from polymath.graph.state import ready_task_ids, task_outcomes
from polymath.llm.gateway import LLMGateway
from tests.conftest import FakeCompletion, no_sleep
from tests.swarm_fakes import diamond, task


def _result(tid: str, ok: bool = True) -> AgentResult:
    return AgentResult(task_id=tid, role=AgentRole.REASONER, output=tid, success=ok)


def test_ready_tasks_follow_dependencies() -> None:
    g = diamond()
    assert ready_task_ids(g, {}) == ["a", "b"]
    assert ready_task_ids(g, {"a": _result("a")}) == ["b"]
    assert ready_task_ids(g, {"a": _result("a"), "b": _result("b")}) == ["synth"]


def test_failure_skips_dependents_transitively() -> None:
    from polymath.core.models import TaskGraph

    g = TaskGraph.from_tasks([task("a"), task("b", ["a"]), task("c", ["b"]), task("d")])
    out = task_outcomes(g, {"a": _result("a", ok=False), "d": _result("d")})
    assert out == {
        "a": TaskStatus.FAILED,
        "b": TaskStatus.SKIPPED,
        "c": TaskStatus.SKIPPED,
        "d": TaskStatus.DONE,
    }
    assert ready_task_ids(g, {"a": _result("a", ok=False), "d": _result("d")}) == []


def _spec(*tasks: tuple[str, TaskType, list[str]]) -> PlanSpec:
    return PlanSpec(
        problem_type="proof",
        rationale="r",
        tasks=[PlannedTask(id=i, type=t, description=f"do {i}", deps=d) for i, t, d in tasks],
    )


R, S, C = TaskType.REASONING, TaskType.SYNTHESIS, TaskType.CRITIQUE


def test_valid_plan_maps_roles() -> None:
    g = to_task_graph(
        _spec(("reason", R, []), ("crit", C, ["reason"]), ("synth", S, ["reason", "crit"]))
    )
    assert g.tasks["crit"].assigned_role is AgentRole.CRITIC
    assert g.topological_order()[-1] == "synth"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (_spec(("a", R, ["b"]), ("b", R, ["a"]), ("s", S, ["a", "b"])), "cycle"),
        (_spec(("a", R, []), ("a", R, []), ("s", S, ["a"])), "duplicate"),
        (_spec(("a", R, [])), "exactly one synthesis"),
        (_spec(("a", R, []), ("b", R, []), ("s", S, ["a"])), "not feeding"),
        (_spec(("a", R, []), ("s", S, ["a"]), ("late", R, ["s"])), "depend on the synthesis"),
        (_spec(("Bad-Id", R, []), ("s", S, ["Bad-Id"])), "snake_case"),
        (_spec(("a", R, ["ghost"]), ("s", S, ["a"])), "unknown"),
    ],
)
def test_invalid_plans_are_rejected(spec: PlanSpec, message: str) -> None:
    with pytest.raises(PlanValidationError, match=message):
        to_task_graph(spec)


def _plan_json(tasks: list[dict[str, object]]) -> str:
    return json.dumps({"problem_type": "computation", "rationale": "r", "tasks": tasks})


GOOD = _plan_json(
    [
        {"id": "calc", "type": "computation", "description": "compute", "deps": []},
        {"id": "synth", "type": "synthesis", "description": "answer", "deps": ["calc"]},
    ]
)
CYCLIC = _plan_json(
    [
        {"id": "a", "type": "reasoning", "description": "x", "deps": ["b"]},
        {"id": "b", "type": "reasoning", "description": "y", "deps": ["a"]},
        {"id": "synth", "type": "synthesis", "description": "z", "deps": ["a", "b"]},
    ]
)


async def test_llm_planner_repairs_cyclic_plan(settings: Settings) -> None:
    fake = FakeCompletion([CYCLIC, GOOD])
    planner = LLMPlanner(LLMGateway(settings, completion_fn=fake, sleep=no_sleep))
    problem = Problem(statement="What is 2^10?")
    graph, usage = await planner.plan(problem, feedback="keep it short")
    assert set(graph.tasks) == {"calc", "synth"}
    assert problem.problem_type is not None and problem.problem_type.value == "computation"
    assert len(usage) == 2
    assert "cycle" in fake.calls[1]["messages"][-1]["content"]
    assert "keep it short" in fake.calls[0]["messages"][-1]["content"]


async def test_llm_planner_falls_back_to_default(settings: Settings) -> None:
    fake = FakeCompletion([CYCLIC, CYCLIC, CYCLIC])
    planner = LLMPlanner(LLMGateway(settings, completion_fn=fake, sleep=no_sleep))
    graph, _ = await planner.plan(Problem(statement="p"))
    assert set(graph.tasks) == {"reason", "critique", "synthesize"}
