"""Eval harness pieces: scorers, attempt extraction, metrics and the report (no LLM calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from polymath.core.models import AgentRole, Claim, ClaimStatus, RunBudget
from polymath.evals.datasets import EvalProblem, last_boxed, research_qa_problems
from polymath.evals.harness import run_suite
from polymath.evals.report import write_report
from polymath.evals.scoring import keywords_correct, lean_statement_preserved, math_correct
from polymath.evals.systems import Attempt, extract_swarm_attempt
from polymath.verification.evidence import CitationPayload, FormalProofPayload, make_evidence
from tests.agent_fakes import FakeTools


@pytest.mark.parametrize(
    ("answer", "gold", "ok"),
    [
        ("so the answer is \\boxed{144}.", "144", True),
        ("\\boxed{\\dfrac{3}{4}}", "\\frac{3}{4}", True),
        ("\\boxed{0.75}", "\\frac{3}{4}", True),
        ("\\boxed{1,000}", "1000", True),
        ("The total is 42", "42", True),
        ("\\boxed{143}", "144", False),
        ("no number here", "7", False),
    ],
)
def test_math_scoring(answer: str, gold: str, ok: bool) -> None:
    assert math_correct(answer, gold) is ok


def test_last_boxed_handles_nested_braces() -> None:
    assert last_boxed("a \\boxed{1} then \\boxed{\\frac{1}{2}}") == "\\frac{1}{2}"


def test_keyword_scoring_needs_every_keyword_as_words() -> None:
    gold = "Attention Is All You Need;2017"
    assert keywords_correct("The paper *Attention is all you need* (2017).", gold)
    assert not keywords_correct("Attention is all you need", gold)
    assert not keywords_correct("Attention Is All You Need, 20170", gold)


def test_lean_statement_must_be_preserved() -> None:
    stmt = "theorem t (n : ℕ) (h : 0 < n) : 0 < n ^ 2"
    assert lean_statement_preserved(
        "theorem t (n : ℕ)\n    (h : 0 < n) : 0 < n ^ 2 := by\n  positivity", stmt
    )
    assert not lean_statement_preserved("theorem t (n : ℕ) : 0 ≤ n ^ 2 := by positivity", stmt)


def test_research_qa_set_is_well_formed() -> None:
    probs = research_qa_problems(100)
    assert len(probs) == 8 and all(p.gold.count(";") >= 1 for p in probs)


def test_extract_swarm_attempt_counts_claims_proofs_and_citations() -> None:
    proof = make_evidence(
        FormalProofPayload(
            lean_code="theorem t : True := trivial",
            theorem_name="t",
            lean_verified=True,
            equivalent=True,
        ),
        summary="",
        source=AgentRole.FORMALIZER,
    )
    good = make_evidence(
        CitationPayload(source="arxiv", paper_id="1", title="T", quote="q"),
        summary="",
        source=AgentRole.LITERATURE,
    )
    bad = make_evidence(CitationPayload(source="arxiv", paper_id="2", title="U", quote="r"),
                        summary="", source=AgentRole.LITERATURE)  # fmt: skip
    verified = Claim(statement="v", status=ClaimStatus.VERIFIED, evidence=[proof, good])
    hunch = Claim(statement="h", evidence=[bad])

    def rc(c: Claim, outcomes: dict[str, str]) -> dict:  # type: ignore[type-arg]
        return {"claim": c.model_dump(mode="json"),
                "decision": {"claim_id": c.id, "status": c.status.value,
                             "checks": [{"evidence_id": k, "kind": "x", "outcome": v, "detail": ""}
                                        for k, v in outcomes.items()]}}  # fmt: skip

    ok = {proof.id: "supports", good.id: "supports"}
    report = {"answer": "A", "verified": [rc(verified, ok)],
              "conjectures": [rc(hunch, {bad.id: "inconclusive"})], "refuted": []}  # fmt: skip
    a = extract_swarm_attempt({"report": report}, "run_x", 2.0)
    assert (a.claims_verified, a.claims_total) == (1, 2)
    assert (a.citations, a.unsupported_citations) == (2, 1)
    assert a.verified_lean == ["theorem t : True := trivial"] and a.error is None


class ScriptedSystem:
    def __init__(self, name: str, answers: dict[str, str], usd: float) -> None:
        self.name, self.answers, self.usd = name, answers, usd

    async def solve(self, problem: EvalProblem, budget: RunBudget) -> Attempt:
        return Attempt(answer=self.answers.get(problem.id, ""), usd=self.usd, latency_s=1.0,
                       claims_total=2, claims_verified=1)  # fmt: skip


async def test_harness_metrics_and_report(tmp_path: Path) -> None:
    probs = [EvalProblem(id=f"p{i}", suite="math", prompt="q", gold=str(i)) for i in range(4)]
    single = ScriptedSystem("single", {"p0": "\\boxed{0}", "p1": "\\boxed{9}"}, 0.01)
    swarm = ScriptedSystem("swarm", {f"p{i}": f"\\boxed{{{i}}}" for i in range(3)}, 0.05)
    run = await run_suite("math", probs, [single, swarm], FakeTools(), usd_per_problem=1.0)
    by = {m.system: m for m in run.metrics()}
    assert by["single"].accuracy == 0.25 and by["swarm"].accuracy == 0.75
    assert by["swarm"].usd_per_problem == pytest.approx(0.05)
    assert by["swarm"].verified_claim_rate == 0.5
    path = write_report([run], tmp_path / "2026-01-01", notes="test notes")
    md = path.read_text()
    assert "| math | swarm | 4 | 75% |" in md and "test notes" in md
    assert (tmp_path / "2026-01-01" / "accuracy.png").stat().st_size > 1000
    assert (tmp_path / "2026-01-01" / "results.json").exists()


async def test_harness_aborts_on_quota_instead_of_recording_failures() -> None:
    from polymath.llm.gateway import QuotaExhaustedError

    class Broke:
        name = "single"

        async def solve(self, problem: EvalProblem, budget: RunBudget) -> Attempt:
            return Attempt(error="LLMError: gpt-5-mini: provider quota exhausted: no credits")

    probs = [EvalProblem(id="p", suite="math", prompt="q", gold="1")]
    with pytest.raises(QuotaExhaustedError):
        await run_suite("math", probs, [Broke()], FakeTools(), usd_per_problem=1.0)


async def test_harness_records_a_crashing_attempt() -> None:
    class Crashy:
        name = "swarm"

        async def solve(self, problem: EvalProblem, budget: RunBudget) -> Attempt:
            raise KeyError("boom")

    probs = [EvalProblem(id="p", suite="math", prompt="q", gold="1")]
    run = await run_suite("math", probs, [Crashy()], FakeTools(), usd_per_problem=1.0)
    assert run.results[0].attempt.error and "crash: KeyError" in run.results[0].attempt.error
