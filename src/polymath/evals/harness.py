"""Run a suite against one or more systems and collect scored results."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.tools import ToolCallError, Tools
from polymath.core.logging import get_logger
from polymath.core.models import RunBudget
from polymath.evals.datasets import EvalProblem, Suite
from polymath.evals.scoring import score
from polymath.evals.systems import Attempt, System

log = get_logger(__name__)


class ProblemResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_id: str
    system: str
    correct: bool
    attempt: Attempt


class SuiteMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: str
    system: str
    n: int
    accuracy: float
    verified_claim_rate: float | None
    hallucinated_citation_rate: float | None
    usd_per_problem: float
    latency_s_per_problem: float
    errors: int


class SuiteRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: Suite
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    problems: list[EvalProblem]
    skipped: list[str] = Field(default_factory=list)
    results: list[ProblemResult]

    def metrics(self) -> list[SuiteMetrics]:
        out = []
        for system in sorted({r.system for r in self.results}):
            rs = [r for r in self.results if r.system == system]
            n = len(rs)
            claims = sum(r.attempt.claims_total for r in rs)
            cites = sum(r.attempt.citations for r in rs)
            out.append(
                SuiteMetrics(
                    suite=self.suite,
                    system=system,
                    n=n,
                    accuracy=sum(r.correct for r in rs) / n if n else 0.0,
                    verified_claim_rate=(
                        sum(r.attempt.claims_verified for r in rs) / claims if claims else None
                    ),
                    hallucinated_citation_rate=(
                        sum(r.attempt.unsupported_citations for r in rs) / cites if cites else None
                    ),
                    usd_per_problem=sum(r.attempt.usd for r in rs) / n if n else 0.0,
                    latency_s_per_problem=sum(r.attempt.latency_s for r in rs) / n if n else 0.0,
                    errors=sum(r.attempt.error is not None for r in rs),
                )
            )
        return out


async def valid_minif2f(problems: list[EvalProblem], tools: Tools) -> tuple[list, list[str]]:  # type: ignore[type-arg]
    """Keep statements that still elaborate on our Mathlib (miniF2F targets an older Lean)."""
    keep, skipped = [], []
    for p in problems:
        code = f"{p.meta.get('header', '')}\n\n{p.gold} := by\n  sorry"
        try:
            res = await tools.lean_check(code)
        except ToolCallError:
            res = None
        if res is not None and res.ok:
            keep.append(p)
        else:
            skipped.append(p.id)
    return keep, skipped


async def run_suite(
    suite: Suite,
    problems: list[EvalProblem],
    systems: list[System],
    tools: Tools,
    *,
    usd_per_problem: float,
) -> SuiteRun:
    skipped: list[str] = []
    if suite == "minif2f":
        problems, skipped = await valid_minif2f(problems, tools)
    budget = RunBudget(max_usd=usd_per_problem, max_tokens=400_000, max_wall_clock_s=1500,
                       max_iterations=20)  # fmt: skip
    results = []
    for p in problems:
        for system in systems:
            attempt = await system.solve(p, budget)
            correct = score(p, attempt.answer, attempt.verified_lean)
            log.info("eval.result", suite=suite, problem=p.id, system=system.name,
                     correct=correct, usd=round(attempt.usd, 4))  # fmt: skip
            results.append(ProblemResult(problem_id=p.id, system=system.name, correct=correct,
                                         attempt=attempt))  # fmt: skip
    return SuiteRun(suite=suite, problems=problems, skipped=skipped, results=results)
