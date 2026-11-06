"""The two systems compared: a single LLM agent (one call) and the full swarm."""

from __future__ import annotations

import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.formalizer import LeanAttempt
from polymath.agents.tools import ToolCallError, Tools
from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.budget import BudgetExceededError, BudgetTracker
from polymath.core.config import Settings
from polymath.core.models import AgentRole, Claim, Problem, RunBudget
from polymath.evals.datasets import EvalProblem
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from polymath.llm.cost import CostTracker
from polymath.llm.gateway import LLMError, LLMGateway
from polymath.llm.structured import StructuredOutputError, complete_structured
from polymath.verification.evidence import CitationPayload, make_evidence
from polymath.verification.gate import VerificationGate


class Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = ""
    verified_lean: list[str] = Field(default_factory=list)
    citations: int = 0
    unsupported_citations: int = 0
    claims_total: int = 0
    claims_verified: int = 0
    usd: float = 0.0
    tokens: int = 0
    latency_s: float = 0.0
    error: str | None = None
    run_id: str | None = None


class System(Protocol):
    name: str

    async def solve(self, problem: EvalProblem, budget: RunBudget) -> Attempt: ...


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="'arxiv' or 'openalex'")
    paper_id: str = Field(description="arXiv id (e.g. 1706.03762) or DOI")
    title: str
    quote: str = Field(description="verbatim sentence from the paper's abstract")


class CitedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[Citation] = Field(default_factory=list, max_length=4)


SINGLE_SYSTEM = "You are an expert mathematician and researcher. Answer accurately and concisely."


class SingleAgent:
    """One LLM call per problem — same models and the same checkers, but no planning, critique,
    repair or verification loop."""

    name = "single"

    def __init__(self, settings: Settings, tools: Tools) -> None:
        self.settings, self.tools = settings, tools

    async def solve(self, problem: EvalProblem, budget: RunBudget) -> Attempt:
        costs = CostTracker()
        gw = LLMGateway(self.settings, cost_tracker=costs, budget=BudgetTracker(budget))
        started = time.monotonic()
        attempt = Attempt()
        try:
            if problem.suite == "minif2f":
                attempt = await self._lean(gw, problem)
            elif problem.suite == "research_qa":
                attempt = await self._cited(gw, problem)
            else:
                msgs = [{"role": "system", "content": SINGLE_SYSTEM},
                        {"role": "user", "content": problem.prompt}]  # fmt: skip
                attempt = Attempt(answer=(await gw.complete(AgentRole.REASONER, msgs)).content)
        except (LLMError, StructuredOutputError, BudgetExceededError, ToolCallError) as exc:
            attempt = Attempt(error=f"{type(exc).__name__}: {exc}")
        s = costs.summary()
        return attempt.model_copy(update={"usd": s.usd, "tokens": s.total_tokens,
                                          "latency_s": time.monotonic() - started})  # fmt: skip

    async def _lean(self, gw: LLMGateway, problem: EvalProblem) -> Attempt:
        from polymath.agents.prompts import load_prompt

        msgs = [{"role": "system", "content": load_prompt("formalizer")},
                {"role": "user", "content": problem.prompt}]  # fmt: skip
        res = await complete_structured(gw, AgentRole.FORMALIZER, msgs, LeanAttempt)
        code = f"{problem.meta.get('header', '')}\n\n{res.value.lean_code}"
        v = await self.tools.lean_verify(code, str(problem.meta.get("name")))
        return Attempt(answer=res.value.lean_code, verified_lean=[code] if v.verified else [])

    async def _cited(self, gw: LLMGateway, problem: EvalProblem) -> Attempt:
        msgs = [{"role": "system", "content": SINGLE_SYSTEM + " Cite your sources: give each "
                 "paper's arXiv id or DOI, title and a verbatim quote from its abstract."},
                {"role": "user", "content": problem.prompt}]  # fmt: skip
        res = await complete_structured(gw, AgentRole.LITERATURE, msgs, CitedAnswer)
        gate = VerificationGate(self.tools)
        bad = 0
        for c in res.value.citations:
            source: Literal["arxiv", "openalex"] = (
                "arxiv" if c.source.lower().startswith("arxiv") else "openalex"
            )
            payload = CitationPayload(source=source, paper_id=c.paper_id.removeprefix("arXiv:"),
                                      title=c.title, quote=c.quote)  # fmt: skip
            evidence = make_evidence(payload, summary="", source=AgentRole.LITERATURE)
            check = await gate.check(evidence)
            bad += check.outcome != "supports"
        n = len(res.value.citations)
        return Attempt(answer=res.value.answer, citations=n, unsupported_citations=bad)


class Swarm:
    name = "swarm"

    def __init__(self, settings: Settings, tools: Tools) -> None:
        # Memory off: problems must not leak answers into each other.
        self.settings = settings.model_copy(update={"memory_enabled": False})
        self.tools = tools

    async def solve(self, problem: EvalProblem, budget: RunBudget) -> Attempt:
        from polymath.cli_swarm import context_factory

        bb = Blackboard(InMemoryEventStore())
        runner = SwarmRunner(
            compile_graph(memory_checkpointer()),
            context_factory(self.settings, bb, self.tools),
            bb,
        )
        started = time.monotonic()
        try:
            snap = await runner.start(Problem(statement=problem.prompt), budget=budget)
        except Exception as exc:  # a crashed run is a failed attempt, not a crashed eval
            return Attempt(error=f"{type(exc).__name__}: {exc}",
                           latency_s=time.monotonic() - started)  # fmt: skip
        return extract_swarm_attempt(snap.values, snap.run_id, time.monotonic() - started)


def extract_swarm_attempt(values: Any, run_id: str, latency_s: float) -> Attempt:
    report: dict[str, Any] = values.get("report") or {}
    usage = values.get("usage")
    buckets = [rc for b in ("verified", "conjectures", "refuted") for rc in report.get(b, [])]
    verified_lean, citations, unsupported = [], 0, 0
    for rc in buckets:
        claim = Claim.model_validate(rc["claim"])
        outcomes = {c["evidence_id"]: c["outcome"] for c in rc["decision"]["checks"]}
        for e in claim.evidence:
            if e.kind.value == "citation":
                citations += 1
                unsupported += outcomes.get(e.id) != "supports"
            if e.kind.value == "formal_proof" and outcomes.get(e.id) == "supports":
                verified_lean.append(str(e.payload.get("lean_code", "")))
    return Attempt(
        answer=report.get("answer") or values.get("answer", ""),
        verified_lean=verified_lean,
        citations=citations,
        unsupported_citations=unsupported,
        claims_total=len(buckets),
        claims_verified=len(report.get("verified", [])),
        usd=usage.usd if usage else 0.0,
        tokens=usage.tokens if usage else 0,
        latency_s=latency_s,
        error=None if report else (values.get("stop_reason") or "no report"),
        run_id=run_id,
    )
