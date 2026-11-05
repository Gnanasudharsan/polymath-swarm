"""DoD: a second run on a related problem reuses a lemma stored by the first run."""

from __future__ import annotations

from dataclasses import dataclass, field

from polymath.agents.base import AgentContext, AgentResult
from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.models import (
    AgentRole,
    Claim,
    ClaimStatus,
    EventKind,
    Problem,
    Task,
    TaskGraph,
    TaskType,
)
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from polymath.memory.embeddings import HashEmbedder
from polymath.memory.episodic import EpisodicMemory
from polymath.memory.inmemory import InMemoryKnowledgeStore
from tests.swarm_fakes import FixedPlanner, make_factory

LEMMA = "n(n+1) is even for every natural number n"


def plan() -> TaskGraph:
    return TaskGraph.from_tasks([
        Task(id="formalize", type=TaskType.FORMALIZATION, description="prove it",
             assigned_role=AgentRole.FORMALIZER),
        Task(id="synth", type=TaskType.SYNTHESIS, description="answer", deps=["formalize"],
             assigned_role=AgentRole.SYNTHESIZER),
    ])  # fmt: skip


@dataclass
class Prover:
    """Formalizer stand-in: 'proves' the lemma unless a verified copy is already available."""

    proved: list[str] = field(default_factory=list)
    seen: list[list[Claim]] = field(default_factory=list)

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        self.seen.append(list(context.claims))
        claims: list[Claim] = []
        if task.type is TaskType.FORMALIZATION:
            known = [c for c in context.claims if c.statement == LEMMA
                     and c.status == ClaimStatus.VERIFIED]  # fmt: skip
            if not known:
                self.proved.append(LEMMA)
                claims = [Claim(statement=LEMMA, task_id=task.id).transition(ClaimStatus.VERIFIED)]
        out = "; ".join(f"{c.statement} [{c.status.value}]" for c in context.claims)
        return AgentResult(task_id=task.id, role=task.assigned_role, output=out, claims=claims)


async def test_second_run_reuses_stored_lemma() -> None:
    memory = EpisodicMemory(InMemoryKnowledgeStore(), HashEmbedder(), min_similarity=0.3)

    async def run(problem: str, prover: Prover, run_id: str):  # type: ignore[no-untyped-def]
        bb = Blackboard(InMemoryEventStore())
        base = make_factory(FixedPlanner(plan()), prover, bb)

        def factory(budget):  # type: ignore[no-untyped-def]
            ctx = base(budget)
            ctx.executors = {r: prover for r in AgentRole}
            ctx.memory = memory
            return ctx

        runner = SwarmRunner(compile_graph(memory_checkpointer()), factory, bb)
        return await runner.start(Problem(statement=problem), run_id=run_id), bb

    first = Prover()
    _, _ = await run("Prove that n(n+1) is even for every natural number n.", first, "run_a")
    assert first.proved == [LEMMA]

    second = Prover()
    snap2, bb2 = await run(
        "Prove that n(n+1)(n+2) is even for every natural number n.", second, "run_b"
    )
    assert second.proved == [], "the lemma was proved again instead of reused"
    reused = [c for c in snap2.values["claims"].values() if c.statement == LEMMA]
    assert len(reused) == 1
    assert reused[0].origin_run_id == "run_a" and reused[0].status == ClaimStatus.VERIFIED
    # the formalizer saw it on the blackboard, and the recall is an auditable event
    assert any(c.origin_run_id == "run_a" for c in second.seen[0])
    events = await bb2.history("run_b")
    recalls = [e for e in events if e.payload.get("topic") == "memory_recall"]
    assert all(e.kind is EventKind.MESSAGE for e in recalls)
    assert recalls and recalls[0].payload["origin_run_id"] == "run_a"
