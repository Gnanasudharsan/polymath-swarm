"""Verification gate + the DoD test: a deliberately false claim is refuted by the Critic."""

from __future__ import annotations

import pytest

from polymath.agents.base import AgentContext
from polymath.agents.critic import CriticAgent
from polymath.core.config import Settings
from polymath.core.models import AgentRole, Claim, ClaimStatus, Problem, Task, TaskType
from polymath.mcp_servers.literature.models import Paper
from polymath.verification.claims import merge_claim
from polymath.verification.evidence import (
    CitationPayload,
    ComputationPayload,
    CritiquePayload,
    FormalProofPayload,
    make_evidence,
    quote_in_source,
)
from polymath.verification.gate import VerificationGate
from tests.agent_fakes import EULER_COUNTEREXAMPLE, FakeTools, gateway, lean_result

FALSE_CLAIM = "n^2 + n + 41 is prime for every natural number n"
PASS = "print('POLYMATH_RESULT: PASS')"
FAIL = "print('POLYMATH_RESULT: FAIL')"


def _claim(*payloads: object, status: ClaimStatus = ClaimStatus.PROPOSED) -> Claim:
    c = Claim(statement="s", status=status)
    for p in payloads:
        c = c.with_evidence(make_evidence(p, summary="", source=AgentRole.COMPUTE))  # type: ignore[arg-type]
    return c


class TestGate:
    async def test_no_evidence_stays_proposed(self) -> None:
        d = await VerificationGate(FakeTools()).decide(_claim())
        assert d.status == ClaimStatus.PROPOSED and d.checks == []

    async def test_computation_is_rerun(self) -> None:
        tools = FakeTools()
        gate = VerificationGate(tools)
        ok = await gate.decide(_claim(ComputationPayload(code=PASS, outcome="pass")))
        assert ok.verified and tools.programs == [PASS]
        # an agent claiming "pass" does not matter: the re-run says FAIL
        bad = await gate.decide(_claim(ComputationPayload(code=FAIL, outcome="pass")))
        assert bad.status == ClaimStatus.REFUTED
        crash = await gate.decide(_claim(ComputationPayload(code="1/0", outcome="pass")))
        assert crash.status == ClaimStatus.PROPOSED

    async def test_citation_quote_must_be_in_refetched_source(self) -> None:
        paper = Paper(source="arxiv", source_id="1706.03762", title="Attention Is All You Need",
                      abstract="We propose a new simple network architecture, the Transformer, "
                               "based solely on attention mechanisms.")  # fmt: skip
        tools = FakeTools(papers={"arxiv:1706.03762": paper})
        gate = VerificationGate(tools)
        good = CitationPayload(
            source="arxiv",
            paper_id="1706.03762",
            title=paper.title,
            quote="a new simple network architecture, the Transformer",
        )
        fake = good.model_copy(update={"quote": "the Transformer is the best model ever built"})
        assert (await gate.decide(_claim(good))).verified
        assert not (await gate.decide(_claim(fake))).verified
        missing = good.model_copy(update={"paper_id": "9999.99999"})
        d = await gate.decide(_claim(missing))
        assert d.checks[0].outcome == "inconclusive"

    async def test_formal_proof_needs_reverify_and_equivalence(self) -> None:
        proof = FormalProofPayload(lean_code="theorem t : True := trivial", theorem_name="t",
                                   lean_verified=True, equivalent=True)  # fmt: skip
        assert (await VerificationGate(FakeTools(lean_results=[lean_result(True)])).decide(
            _claim(proof))).verified  # fmt: skip
        # the agent said verified, but the gate's own Lean re-check fails
        assert not (await VerificationGate(FakeTools(lean_results=[lean_result(False)])).decide(
            _claim(proof))).verified  # fmt: skip
        unfaithful = proof.model_copy(update={"equivalent": False})
        tools = FakeTools(lean_results=[lean_result(True)])
        assert not (await VerificationGate(tools).decide(_claim(unfaithful))).verified
        assert tools.lean_calls == []  # not even re-checked

    async def test_reproduced_counterexample_refutes_even_a_verified_claim(self) -> None:
        crit = CritiquePayload(
            verdict="refute",
            rationale="n=40",
            counterexample_code=EULER_COUNTEREXAMPLE,
            counterexample_found=True,
        )
        proof = ComputationPayload(code=PASS, outcome="pass")
        d = await VerificationGate(FakeTools()).decide(_claim(proof, crit))
        assert d.status == ClaimStatus.REFUTED


def test_merge_prefers_refuted_and_unions_evidence() -> None:
    base = Claim(statement="x")
    a = base.with_evidence(
        make_evidence(ComputationPayload(code=PASS), summary="", source=AgentRole.COMPUTE)
    ).transition(ClaimStatus.VERIFIED)
    b = base.with_evidence(
        make_evidence(
            CritiquePayload(verdict="refute", rationale="r"), summary="", source=AgentRole.CRITIC
        )
    )
    b = b.transition(ClaimStatus.REFUTED)
    merged = merge_claim(a, b)
    assert merged.status == ClaimStatus.REFUTED and len(merged.evidence) == 2
    assert merge_claim(merged, base).status == ClaimStatus.REFUTED  # never downgraded


def test_quote_matching_survives_different_typesetting() -> None:
    # Semantic Scholar vs arXiv renderings of the same abstract sentence (arXiv 2303.09521)
    s2 = (
        "We prove that \\[ R(k) \\leqslant (4 - \\varepsilon)^k \\] "
        "for some constant \\varepsilon>0."
    )
    arxiv = (
        "We prove that \\[ R(k) \\leqslant (4 - \\varepsilon)^k \\] for some constant "
        "$\\varepsilon > 0$. This is the first exponential improvement"
    )
    assert quote_in_source(s2, arxiv)
    # word boundaries matter: a quote can't match across a partial word
    assert not quote_in_source(
        "prove that r k 4 k for some constant varepsilon 0 this is the fir", arxiv
    )
    assert not quote_in_source("We prove that R(k) is at most 3^k for every k", arxiv)


def test_quote_matching_is_whitespace_and_tex_insensitive() -> None:
    src = "The odd-Ramsey number $r_{odd}(n,H)$ of a graph\n  H is the minimum number of colors"
    assert quote_in_source("the odd-Ramsey number r_odd(n,H) of a graph H is the minimum", src)
    assert not quote_in_source("short", src)


# ---------------------------------------------------------------- DoD: false claim refuted


def _task() -> Task:
    return Task(id="crit", type=TaskType.CRITIQUE, description="Review the claims",
                assigned_role=AgentRole.CRITIC)  # fmt: skip


async def test_critic_refutes_deliberately_false_claim(settings: Settings) -> None:
    false = Claim(statement=FALSE_CLAIM, confidence=0.9, proposed_by=AgentRole.REASONER)
    review = {"reviews": [{
        "claim_id": false.id, "verdict": "refute",
        "rationale": "Euler's polynomial fails at n = 40: 40^2 + 40 + 41 = 41^2.",
        "counterexample_program": EULER_COUNTEREXAMPLE,
    }]}  # fmt: skip
    gw, _ = gateway(settings, [review])
    tools = FakeTools()
    ctx = AgentContext(problem=Problem(statement="Is n^2+n+41 always prime?"), claims=[false])
    result = await CriticAgent(gw, tools).run(_task(), ctx)

    (claim,) = result.claims
    assert claim.id == false.id and claim.status == ClaimStatus.REFUTED
    crit = claim.evidence[-1].payload
    assert crit["counterexample_found"] is True
    assert "n=40 gives 1681" in crit["counterexample_output"]
    # and the gate, re-running the search independently, agrees
    decision = await VerificationGate(tools).decide(claim)
    assert decision.status == ClaimStatus.REFUTED


async def test_refutation_without_working_counterexample_is_only_a_challenge(
    settings: Settings,
) -> None:
    true = Claim(statement="n^2 + n is even for every natural number n")
    review = {"reviews": [{
        "claim_id": true.id, "verdict": "refute", "rationale": "I doubt it",
        "counterexample_program": "for n in range(100):\n    assert (n*n+n) % 2 == 0",
    }]}  # fmt: skip
    gw, _ = gateway(settings, [review])
    ctx = AgentContext(problem=Problem(statement="p"), claims=[true])
    result = await CriticAgent(gw, FakeTools()).run(_task(), ctx)
    (claim,) = result.claims
    assert claim.status == ClaimStatus.CHALLENGED
    assert claim.evidence[-1].payload["verdict"] == "challenge"


@pytest.mark.parametrize("verdict", ["accept"])
async def test_accept_leaves_claim_open(settings: Settings, verdict: str) -> None:
    c = Claim(statement="1 + 1 = 2")
    gw, _ = gateway(settings, [{"reviews": [{"claim_id": c.id, "verdict": verdict,
                                              "rationale": "fine"}]}])  # fmt: skip
    result = await CriticAgent(gw, FakeTools()).run(_task(), AgentContext(
        problem=Problem(statement="p"), claims=[c]))  # fmt: skip
    assert result.claims[0].status == ClaimStatus.PROPOSED
