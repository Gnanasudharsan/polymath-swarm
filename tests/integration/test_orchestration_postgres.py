"""Orchestration on real Postgres + Redis: SIGKILL mid-run, resume from another process."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import signal

import pytest

from polymath.core.config import Settings
from polymath.core.models import EventKind, Problem
from polymath.graph.builder import compile_graph
from polymath.graph.infra import swarm_infra
from polymath.graph.runner import SwarmRunner
from polymath.graph.state import RunStatus
from tests.swarm_fakes import FakeExecutor, FixedPlanner, diamond, make_factory, run_in_child

pytestmark = pytest.mark.integration

# Only datastore URLs are used here (no LLM, no ledger), so import-time settings are safe.
SETTINGS = Settings(_env_file=None, spend_ledger=None)  # type: ignore[call-arg]


async def _wait_for(predicate, limit_s: float = 60.0) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_running_loop().time() + limit_s
    while not await predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.1)


async def test_sigkilled_run_resumes_from_postgres_checkpoint() -> None:
    run_id = f"run_sigkill_{os.getpid()}_{os.urandom(3).hex()}"
    ctx = mp.get_context("spawn")
    child = ctx.Process(
        target=run_in_child, args=(run_id, SETTINGS.postgres_dsn, SETTINGS.redis_url)
    )
    child.start()
    try:
        async with swarm_infra(SETTINGS) as infra:

            async def a_done_and_b_running() -> bool:
                events = await infra.blackboard.history(run_id)
                finished = {
                    e.payload.get("task_id") for e in events if e.kind is EventKind.TASK_FINISHED
                }
                started = {
                    e.payload.get("task_id") for e in events if e.kind is EventKind.TASK_STARTED
                }
                return "a" in finished and "b" in started

            await _wait_for(a_done_and_b_running)
            await asyncio.sleep(0.5)  # let the checkpoint for a's write land
            assert child.pid is not None
            os.kill(child.pid, signal.SIGKILL)
            child.join(10)
            assert child.exitcode == -signal.SIGKILL

            executor = FakeExecutor()
            runner = SwarmRunner(
                compile_graph(infra.checkpointer),
                make_factory(FixedPlanner(diamond()), executor, infra.blackboard),
                infra.blackboard,
            )
            snap = await runner.snapshot(run_id)
            assert not snap.finished and snap.status is RunStatus.EXECUTING
            snap = await runner.resume(run_id)
            assert snap.status is RunStatus.COMPLETED
            assert sorted(executor.ran) == ["b", "synth"], "finished task `a` was re-run"

            events = await infra.blackboard.history(run_id)
            starts = [e.payload["task_id"] for e in events if e.kind is EventKind.TASK_STARTED]
            assert starts.count("a") == 1 and starts.count("b") == 2  # b restarted after kill

            trace = await runner.export_trace(run_id)
            assert trace["status"] == "completed" and trace["checkpoints"] > 0
    finally:
        if child.is_alive():
            child.kill()


async def test_plan_approval_pause_survives_process_boundary() -> None:
    run_id = f"run_hitl_pg_{os.urandom(4).hex()}"
    async with swarm_infra(SETTINGS) as infra:
        runner = SwarmRunner(
            compile_graph(infra.checkpointer),
            make_factory(FixedPlanner(diamond()), FakeExecutor(), infra.blackboard),
            infra.blackboard,
        )
        snap = await runner.start(Problem(statement="p"), run_id=run_id, require_approval=True)
        assert snap.awaiting_approval

    # A brand-new connection/graph (as if another process) answers the interrupt.
    async with swarm_infra(SETTINGS) as infra:
        executor = FakeExecutor()
        runner = SwarmRunner(
            compile_graph(infra.checkpointer),
            make_factory(FixedPlanner(diamond()), executor, infra.blackboard),
            infra.blackboard,
        )
        snap = await runner.resume(run_id, True)
        assert snap.status is RunStatus.COMPLETED and len(executor.ran) == 3


async def test_live_events_over_redis() -> None:
    run_id = f"run_live_pg_{os.urandom(4).hex()}"
    async with swarm_infra(SETTINGS) as infra:
        seen: list[EventKind] = []

        async def listen() -> None:
            async for event in infra.blackboard.subscribe(run_id):
                seen.append(event.kind)

        listener = asyncio.create_task(listen())
        await asyncio.sleep(0.2)
        runner = SwarmRunner(
            compile_graph(infra.checkpointer),
            make_factory(FixedPlanner(diamond()), FakeExecutor(), infra.blackboard),
            infra.blackboard,
        )
        await runner.start(Problem(statement="p"), run_id=run_id)
        await asyncio.wait_for(listener, 10)
        assert seen[-1] is EventKind.RUN_FINISHED
        assert seen.count(EventKind.TASK_FINISHED) == 3
        assert len(await infra.blackboard.history(run_id)) >= len(seen)
