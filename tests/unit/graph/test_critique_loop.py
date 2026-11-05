"""Graph-level critique loop and budget degradation."""

from __future__ import annotations

from dataclasses import dataclass, field

from polymath.agents.base import AgentContext, AgentResult
from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.models import (
    AgentRole,
    Claim,
    ClaimStatus,
    Problem,
    RunBudget,
    Task,
    TaskGraph,
    TaskType,
)
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from polymath.graph.state import RunStatus
from polymath.llm.cost import LLMUsage
from tests.swarm_fakes import FixedPlanner, make_factory


def plan() -> TaskGraph:
    return TaskGraph.from_tasks([
        Task(id="reason", type=TaskType.REASONING, description="r",
             assigned_role=AgentRole.REASONER),
        Task(id="critique", type=TaskType.CRITIQUE, description="c", deps=["reason"],
             assigned_role=AgentRole.CRITIC),
        Task(id="synth", type=TaskType.SYNTHESIS, description="s", deps=["reason", "critique"],
             assigned_role=AgentRole.SYNTHESIZER),
    ])  # fmt: skip


@dataclass
class RoleAgents:
    """Reasoner proposes a claim; critic refutes everything it sees; synth echoes claim states."""

    usd: float = 0.0
    ran: list[str] = field(default_factory=list)

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        self.ran.append(task.id)
        usage = [LLMUsage(model="f", prompt_tokens=1, completion_tokens=1, usd=self.usd)]
        claims: list[Claim] = []
        if task.type is TaskType.REASONING:
            claims = [Claim(statement=f"claim from {task.id}", task_id=task.id)]
        elif task.type is TaskType.CRITIQUE:
            claims = [c.transition(ClaimStatus.REFUTED) for c in context.claims
                      if c.status == ClaimStatus.PROPOSED]  # fmt: skip
        out = "; ".join(f"{c.statement}={c.status.value}" for c in context.claims)
        return AgentResult(task_id=task.id, role=task.assigned_role, output=out, claims=claims,
                           usage=usage)  # fmt: skip


def _runner(agents: RoleAgents, **kw: object) -> SwarmRunner:
    bb = Blackboard(InMemoryEventStore())
    factory = make_factory(FixedPlanner(plan()), agents, bb, **kw)  # type: ignore[arg-type]

    def with_all_roles(budget):  # type: ignore[no-untyped-def]
        ctx = factory(budget)
        ctx.executors = {r: agents for r in AgentRole}
        return ctx

    return SwarmRunner(compile_graph(memory_checkpointer()), with_all_roles, bb)


async def test_refuted_claims_trigger_bounded_revision_rounds() -> None:
    agents = RoleAgents()
    snap = await _runner(agents).start(Problem(statement="p"))
    assert snap.status is RunStatus.COMPLETED
    assert agents.ran == ["reason", "critique", "revise_r1", "critique_r1",
                          "revise_r2", "critique_r2", "synth"]  # fmt: skip
    assert snap.values["revision_rounds"] == 2  # max_revision_rounds
    claims = snap.values["claims"]
    assert len(claims) == 3 and all(c.status == ClaimStatus.REFUTED for c in claims.values())
    assert {"critique_r1", "critique_r2"} <= set(snap.values["plan"].tasks["synth"].deps)


async def test_revision_rounds_can_be_disabled() -> None:
    agents = RoleAgents()
    await _runner(agents, max_revision_rounds=0).start(Problem(statement="p"))
    assert agents.ran == ["reason", "critique", "synth"]


async def test_optional_revision_work_is_skipped_near_budget_limit() -> None:
    agents = RoleAgents(usd=0.3)
    snap = await _runner(agents).start(Problem(statement="p"), budget=RunBudget(max_usd=1.0))
    # reason+critique cost 0.6 (< 80%); revise_r1 → 0.9 ≥ 80%: critique_r1 is optional → skipped
    assert "critique_r1" not in agents.ran
    assert snap.values["results"]["critique_r1"].output.startswith("(skipped")
    assert snap.status in (RunStatus.COMPLETED, RunStatus.BUDGET_EXHAUSTED)
