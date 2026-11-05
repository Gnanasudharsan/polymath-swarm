"""End-to-end orchestration with an in-memory checkpointer and fake agents."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis

from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.models import EventKind, Problem, RunBudget, TaskGraph, TaskType
from polymath.graph.builder import compile_graph, mermaid
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from polymath.graph.state import RunStatus
from tests.swarm_fakes import FakeExecutor, FixedPlanner, diamond, make_factory, task

PROBLEM = Problem(statement="toy problem")


def _runner(
    planner: FixedPlanner, executor: FakeExecutor, saver: object | None = None, **kw: object
) -> tuple[SwarmRunner, Blackboard]:
    bb = Blackboard(InMemoryEventStore())
    graph = compile_graph(saver or memory_checkpointer())  # type: ignore[arg-type]
    return SwarmRunner(graph, make_factory(planner, executor, bb, **kw), bb), bb


async def test_full_run_completes_with_answer_and_events() -> None:
    executor = FakeExecutor()
    runner, bb = _runner(FixedPlanner(diamond()), executor)
    snap = await runner.start(PROBLEM, run_id="run_full")
    assert snap.finished and snap.status is RunStatus.COMPLETED
    assert set(snap.values["results"]) == {"a", "b", "synth"}
    assert snap.values["answer"].startswith("synth done")
    # the synthesiser saw the claims produced by its dependencies
    assert "claim from a" in snap.values["answer"] and "claim from b" in snap.values["answer"]
    kinds = [e.kind for e in await bb.history("run_full")]
    assert kinds[0] is EventKind.RUN_STARTED and kinds[-1] is EventKind.RUN_FINISHED
    assert kinds.count(EventKind.TASK_STARTED) == 3


async def test_independent_tasks_run_concurrently() -> None:
    executor = FakeExecutor(delays={"a": 0.5, "b": 0.5})
    runner, _ = _runner(FixedPlanner(diamond()), executor)
    started = time.monotonic()
    snap = await runner.start(PROBLEM)
    elapsed = time.monotonic() - started
    assert snap.status is RunStatus.COMPLETED
    spans = {tid: (s, e) for tid, s, e in executor.log}
    (a0, a1), (b0, b1) = spans["a"], spans["b"]
    assert a0 < b1 and b0 < a1, "a and b did not overlap"
    assert elapsed < 0.9, f"took {elapsed:.2f}s; sequential would be ≥ 1.0s"
    assert spans["synth"][0] >= max(a1, b1)  # synth waited for both


async def test_max_parallel_caps_fan_out() -> None:
    executor = FakeExecutor(delays={"a": 0.3, "b": 0.3})
    runner, _ = _runner(FixedPlanner(diamond()), executor, max_parallel=1)
    started = time.monotonic()
    await runner.start(PROBLEM)
    assert time.monotonic() - started >= 0.6


async def test_failed_task_skips_dependents_but_not_synthesis() -> None:
    chain = TaskGraph.from_tasks(
        [task("a"), task("a2", ["a"]), task("b"), task("synth", ["a2", "b"], TaskType.SYNTHESIS)]
    )
    executor = FakeExecutor(fail={"a"})
    runner, _ = _runner(FixedPlanner(chain), executor)
    snap = await runner.start(PROBLEM)
    assert snap.status is RunStatus.COMPLETED
    results = snap.values["results"]
    assert results["a"].success is False and "exploded" in (results["a"].error or "")
    assert "a2" not in results  # ordinary dependents are skipped...
    assert results["synth"].success  # ...but synthesis still reports on what happened
    plan = snap.values["plan"]
    assert plan.tasks["a2"].status.value == "skipped"
    assert snap.values["answer"].startswith("synth done")


async def test_synthesis_skipped_when_every_input_failed() -> None:
    runner, _ = _runner(FixedPlanner(diamond()), FakeExecutor(fail={"a", "b"}))
    snap = await runner.start(PROBLEM)
    assert "synth" not in snap.values["results"]
    assert snap.status is RunStatus.FAILED


async def test_spend_of_a_timed_out_task_is_charged_to_the_run(settings) -> None:  # type: ignore[no-untyped-def]
    from polymath.agents.base import AgentContext, AgentResult
    from polymath.core.models import AgentRole, Task
    from polymath.llm.gateway import LLMGateway
    from tests.conftest import FakeCompletion, no_sleep

    gw = LLMGateway(settings, completion_fn=FakeCompletion(["x"] * 3), sleep=no_sleep)

    class Slow:
        async def run(self, task: Task, context: AgentContext) -> AgentResult:
            await gw.complete(AgentRole.REASONER, [{"role": "user", "content": "q"}],
                              model="claude-haiku-5-5")  # fmt: skip
            await asyncio.sleep(30)
            raise AssertionError("unreachable")

    slow = Slow()
    bb = Blackboard(InMemoryEventStore())
    factory = make_factory(FixedPlanner(diamond()), FakeExecutor(), bb, task_timeout_s=0.2)

    def ctx_factory(budget):  # type: ignore[no-untyped-def]
        ctx = factory(budget)
        ctx.executors[AgentRole.REASONER] = slow  # type: ignore[assignment]
        return ctx

    snap = await SwarmRunner(compile_graph(memory_checkpointer()), ctx_factory, bb).start(PROBLEM)
    a = snap.values["results"]["a"]
    assert not a.success and "exceeded" in (a.error or "")
    assert a.usage and snap.values["usage"].tokens >= 150  # both a and b's calls counted
    assert snap.values["usage"].usd > 0


async def test_budget_exhaustion_stops_dispatch() -> None:
    chain = TaskGraph.from_tasks(
        [task("a"), task("b", ["a"]), task("c", ["b"]), task("synth", ["c"], TaskType.SYNTHESIS)]
    )
    executor = FakeExecutor(usd_per_task=0.45)
    runner, bb = _runner(FixedPlanner(chain), executor)
    snap = await runner.start(PROBLEM, budget=RunBudget(max_usd=1.0), run_id="run_budget")
    # $0.45 ok → $0.90 (≥ 80%: warn, keep going) → $1.35 (≥ 100%: stop before synth)
    assert snap.status is RunStatus.BUDGET_EXHAUSTED
    assert executor.ran == ["a", "b", "c"]
    assert "usd" in snap.values["stop_reason"]
    assert snap.values["usage"].usd == pytest.approx(1.35)
    assert EventKind.BUDGET_WARNING in [e.kind for e in await bb.history("run_budget")]


async def test_iteration_ceiling() -> None:
    chain = TaskGraph.from_tasks(
        [task("a"), task("b", ["a"]), task("synth", ["b"], TaskType.SYNTHESIS)]
    )
    runner, _ = _runner(FixedPlanner(chain), FakeExecutor())
    snap = await runner.start(PROBLEM, budget=RunBudget(max_iterations=2))
    assert snap.status is RunStatus.BUDGET_EXHAUSTED and "iterations" in snap.values["stop_reason"]


class TestPlanApproval:
    async def test_pauses_before_any_task_then_approves(self) -> None:
        executor = FakeExecutor()
        runner, _ = _runner(FixedPlanner(diamond()), executor)
        snap = await runner.start(PROBLEM, run_id="run_hitl", require_approval=True)
        assert snap.awaiting_approval and not snap.finished
        assert snap.status is RunStatus.AWAITING_APPROVAL
        assert set(snap.interrupt["plan"]["tasks"]) == {"a", "b", "synth"}  # type: ignore[index]
        assert executor.ran == []
        with pytest.raises(ValueError, match="waiting for a decision"):
            await runner.resume("run_hitl")
        snap = await runner.resume("run_hitl", True)
        assert snap.status is RunStatus.COMPLETED and len(executor.ran) == 3

    async def test_feedback_triggers_replan(self) -> None:
        planner = FixedPlanner(diamond())
        runner, _ = _runner(planner, FakeExecutor())
        await runner.start(PROBLEM, run_id="run_replan", require_approval=True)
        snap = await runner.resume("run_replan", {"approved": False, "feedback": "add a critic"})
        assert snap.awaiting_approval
        assert planner.calls == [None, "add a critic"]
        assert snap.values["plan_rounds"] == 2
        snap = await runner.resume("run_replan", {"approved": True})
        assert snap.status is RunStatus.COMPLETED

    async def test_plain_rejection_ends_run(self) -> None:
        executor = FakeExecutor()
        runner, _ = _runner(FixedPlanner(diamond()), executor)
        await runner.start(PROBLEM, run_id="run_reject", require_approval=True)
        snap = await runner.resume("run_reject", False)
        assert snap.status is RunStatus.REJECTED and executor.ran == []


async def test_killed_run_resumes_without_redoing_finished_tasks() -> None:
    """Cancel the run while `b` is in flight; a new runner on the same checkpointer resumes."""
    saver = memory_checkpointer()
    slow = FakeExecutor(delays={"a": 0.0, "b": 30.0})
    runner, _ = _runner(FixedPlanner(diamond()), slow, saver)
    job = asyncio.create_task(runner.start(PROBLEM, run_id="run_kill"))
    for _ in range(200):
        if "a" in slow.ran:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    fresh = FakeExecutor()
    runner2, _ = _runner(FixedPlanner(diamond()), fresh, saver)
    before = await runner2.snapshot("run_kill")
    assert not before.finished and before.next_nodes
    snap = await runner2.resume("run_kill")
    assert snap.status is RunStatus.COMPLETED
    assert "a" not in fresh.ran  # a's write was checkpointed before the kill
    assert sorted(fresh.ran) == ["b", "synth"]


async def test_trace_export() -> None:
    runner, _ = _runner(FixedPlanner(diamond()), FakeExecutor())
    await runner.start(PROBLEM, run_id="run_trace")
    trace = await runner.export_trace("run_trace")
    assert trace["status"] == "completed"
    assert set(trace["plan"]["tasks"]) == {"a", "b", "synth"}
    assert len(trace["claims"]) == 3
    assert trace["checkpoints"] > 3
    assert trace["events"][0]["kind"] == "run_started"
    import json

    json.dumps(trace)  # fully serialisable


async def test_blackboard_live_subscription() -> None:
    redis = FakeAsyncRedis()
    bb = Blackboard(InMemoryEventStore(), redis)
    received: list[EventKind] = []

    async def listen() -> None:
        async for event in bb.subscribe("run_live"):
            received.append(event.kind)

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0.05)
    await bb.post("run_live", EventKind.TASK_STARTED, task_id="a")
    await bb.post("run_live", EventKind.RUN_FINISHED, status="completed")
    await asyncio.wait_for(listener, 5)
    assert received == [EventKind.TASK_STARTED, EventKind.RUN_FINISHED]
    assert len(await bb.history("run_live")) == 2


def test_mermaid_doc_is_current() -> None:
    doc = Path(__file__).parents[3] / "docs" / "diagrams" / "swarm-graph.mmd"
    assert doc.read_text().strip() == mermaid().strip(), "run: uv run polymath graph > " + str(doc)
