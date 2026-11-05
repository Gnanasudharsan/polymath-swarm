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
from polymath.graph.nodes import claims_to_remember
from polymath.graph.runner import SwarmRunner
from polymath.memory.embeddings import HashEmbedder
from polymath.memory.episodic import EpisodicMemory
from polymath.memory.inmemory import InMemoryKnowledgeStore
from polymath.verification.evidence import FormalProofPayload, make_evidence
from polymath.verification.gate import GateDecision
from polymath.verification.report import EvidenceReport, ReportedClaim
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
            recalled = [c for c in context.claims if c.statement == LEMMA and c.origin_run_id]
            if not recalled:
                self.proved.append(LEMMA)
                proof = make_evidence(
                    FormalProofPayload(lean_code="theorem t : True := trivial", theorem_name="t",
                                       lean_verified=True, equivalent=True),
                    summary="Lean", source=AgentRole.FORMALIZER,
                )  # fmt: skip
                claims = [Claim(statement=LEMMA, task_id=task.id, evidence=[proof])
                          .transition(ClaimStatus.VERIFIED)]  # fmt: skip
        out = "; ".join(f"{c.statement} [{c.status.value}]" for c in context.claims)
        data: dict[str, object] = {}
        if task.type is TaskType.SYNTHESIS:
            # Stand-in for the gate: claims with formal evidence pass; the report is what
            # memory stores.
            gated = [c.model_copy(update={"status": ClaimStatus.VERIFIED}) if c.evidence else c
                     for c in context.claims]  # fmt: skip
            report = EvidenceReport(
                problem=context.problem, answer=out,
                verified=[ReportedClaim(claim=c, decision=GateDecision(claim_id=c.id,
                                                                       status=c.status))
                          for c in gated if c.status == ClaimStatus.VERIFIED],
            )  # fmt: skip
            data = {"report": report.model_dump(mode="json"), "markdown": ""}
            claims = gated
        return AgentResult(task_id=task.id, role=task.assigned_role, output=out, claims=claims,
                           data=data)  # fmt: skip


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
    assert reused[0].origin_run_id == "run_a"
    assert reused[0].evidence and reused[0].evidence[0].kind.value == "formal_proof"
    # agents received it as *proposed* (with its evidence); only this run's gate re-verified it
    (seen,) = [c for c in second.seen[0] if c.statement == LEMMA]
    assert seen.status == ClaimStatus.PROPOSED
    assert reused[0].status == ClaimStatus.VERIFIED
    # the formalizer saw it on the blackboard, and the recall is an auditable event
    assert any(c.origin_run_id == "run_a" for c in second.seen[0])
    events = await bb2.history("run_b")
    recalls = [e for e in events if e.payload.get("topic") == "memory_recall"]
    assert all(e.kind is EventKind.MESSAGE for e in recalls)
    assert recalls and recalls[0].payload["origin_run_id"] == "run_a"


def test_memory_never_stores_verified_without_the_gate() -> None:
    """Regression: the merged run state never downgrades a claim, so storing it directly let a
    gate-rejected claim be remembered as verified."""
    from polymath.core.models import Problem

    sneaky = Claim(statement="x", status=ClaimStatus.VERIFIED)
    state = {"run_id": "r", "problem": Problem(statement="p"), "claims": {sneaky.id: sneaky}}
    (stored,) = claims_to_remember(state, None)  # type: ignore[arg-type]
    assert stored.status == ClaimStatus.PROPOSED
    gated = sneaky.model_copy(update={"status": ClaimStatus.PROPOSED})
    report = {"verified": [], "conjectures": [{"claim": gated.model_dump(mode="json")}],
              "refuted": []}  # fmt: skip
    (from_report,) = claims_to_remember(state, report)  # type: ignore[arg-type]
    assert from_report.status == ClaimStatus.PROPOSED
