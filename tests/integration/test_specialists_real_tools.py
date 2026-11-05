"""Specialists and the gate on the real MCP tool servers (Docker sandbox, Lean)."""

from __future__ import annotations

import pytest

from polymath.agents.base import AgentContext
from polymath.agents.critic import CriticAgent
from polymath.agents.tools import open_tools
from polymath.core.config import Settings
from polymath.core.models import AgentRole, Claim, ClaimStatus, Problem, Task, TaskType
from polymath.verification.evidence import FormalProofPayload, make_evidence
from polymath.verification.gate import VerificationGate
from tests.agent_fakes import EULER_COUNTEREXAMPLE, gateway

pytestmark = pytest.mark.integration


# Tools are opened inside each test body: the MCP client's anyio task group must be exited by
# the task that entered it, which pytest-asyncio's async-generator fixtures don't guarantee.


async def test_false_claim_refuted_in_docker_sandbox(infra_settings: Settings) -> None:
    false = Claim(statement="n^2 + n + 41 is prime for every natural number n")
    review = {"reviews": [{"claim_id": false.id, "verdict": "refute",
                           "rationale": "fails at n = 40",
                           "counterexample_program": EULER_COUNTEREXAMPLE}]}  # fmt: skip
    gw, _ = gateway(infra_settings, [review])
    task = Task(id="crit", type=TaskType.CRITIQUE, description="review",
                assigned_role=AgentRole.CRITIC)  # fmt: skip
    ctx = AgentContext(problem=Problem(statement="Is n^2+n+41 always prime?"), claims=[false])
    async with open_tools(infra_settings, lean_enabled=False) as tools:
        result = await CriticAgent(gw, tools).run(task, ctx)
        (claim,) = result.claims
        assert claim.status == ClaimStatus.REFUTED
        output = claim.evidence[-1].payload["counterexample_output"]
        assert "n=40 gives 1681, divisible by 41" in output
        assert (await VerificationGate(tools).decide(claim)).status == ClaimStatus.REFUTED


@pytest.mark.lean
async def test_gate_verifies_real_lean_proof(infra_settings: Settings) -> None:
    proof = FormalProofPayload(
        lean_code="theorem two_dvd_mul_succ (n : ℕ) : 2 ∣ n * (n + 1) := by\n"
                  "  exact even_iff_two_dvd.mp (Nat.even_mul_succ_self n)",
        theorem_name="two_dvd_mul_succ", lean_verified=True, equivalent=True,
    )  # fmt: skip
    claim = Claim(statement="n(n+1) is even for every natural number n").with_evidence(
        make_evidence(proof, summary="", source=AgentRole.FORMALIZER)
    )
    async with open_tools(infra_settings) as tools:
        decision = await VerificationGate(tools).decide(claim)
    assert decision.verified, decision.checks
