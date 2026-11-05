"""Subprocess body for test_langfuse: run a tiny traced swarm (fake LLM) and flush to Langfuse."""

from __future__ import annotations

import asyncio
import sys

from polymath.agents.base import AgentContext, AgentResult
from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.config import Settings
from polymath.core.models import AgentRole, Problem, Task
from polymath.core.tracing import flush_tracing, setup_tracing_from_settings
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from polymath.llm.gateway import LLMGateway
from tests.conftest import FakeCompletion, no_sleep
from tests.swarm_fakes import FixedPlanner, diamond, make_factory


async def main(run_id: str) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    setup_tracing_from_settings(settings)
    gateway = LLMGateway(settings, completion_fn=FakeCompletion(["ok"] * 10), sleep=no_sleep)

    class Talker:
        async def run(self, task: Task, context: AgentContext) -> AgentResult:
            resp = await gateway.complete(task.assigned_role, [{"role": "user", "content": "hi"}],
                                          model="claude-haiku-5-5")  # fmt: skip
            return AgentResult(task_id=task.id, role=task.assigned_role, output=resp.content,
                               usage=[resp.usage])  # fmt: skip

    bb = Blackboard(InMemoryEventStore())
    base = make_factory(FixedPlanner(diamond()), Talker(), bb)  # type: ignore[arg-type]

    def factory(budget):  # type: ignore[no-untyped-def]
        ctx = base(budget)
        ctx.executors = {r: Talker() for r in AgentRole}  # type: ignore[misc]
        return ctx

    runner = SwarmRunner(compile_graph(memory_checkpointer()), factory, bb)
    await runner.start(Problem(statement="trace me"), run_id=run_id)
    flush_tracing()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
