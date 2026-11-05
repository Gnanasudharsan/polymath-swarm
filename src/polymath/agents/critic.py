"""Critic: adversarial review; counterexample searches run in the sandbox."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.base import (
    AgentContext,
    AgentResult,
    BaseAgent,
    open_claims,
    render_claims,
    task_brief,
)
from polymath.agents.tools import ToolCallError, Tools
from polymath.core.models import AgentRole, Claim, ClaimStatus, Task
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway
from polymath.verification.evidence import CritiquePayload, counterexample_in, make_evidence


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    verdict: Literal["accept", "challenge", "refute"]
    rationale: str
    counterexample_program: str | None = Field(
        default=None, description="bounded search printing POLYMATH_COUNTEREXAMPLE: ..."
    )


class Reviews(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviews: list[Review] = Field(default_factory=list)


class CriticAgent(BaseAgent):
    role: ClassVar[AgentRole] = AgentRole.CRITIC
    prompt_name: ClassVar[str] = "critic"

    def __init__(self, gateway: LLMGateway, tools: Tools) -> None:
        super().__init__(gateway)
        self.toolset = tools

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        usage: list[LLMUsage] = []
        candidates = open_claims(context)
        if not candidates:
            return self.result(task, "No open claims to review.", usage)
        reviewed = await self.ask(
            Reviews,
            f"{task_brief(task, context)}\n\n## Claims to review\n{render_claims(candidates)}",
            usage,
        )
        by_id = {c.id: c for c in candidates}
        claims: list[Claim] = []
        lines: list[str] = []
        for r in reviewed.reviews:
            claim = by_id.get(r.claim_id)
            if claim is None:
                continue
            found: str | None = None
            output: str | None = None
            if r.counterexample_program and r.verdict != "accept":
                try:
                    res = await self.toolset.run_python(r.counterexample_program, 60.0)
                    output = (res.stdout + res.stderr)[-3000:]
                    found = counterexample_in(res.stdout) if res.exit_code == 0 else None
                except ToolCallError as exc:
                    output = f"sandbox error: {exc}"
            # A refutation counts only if its counterexample actually reproduces.
            verdict = r.verdict if (r.verdict != "refute" or found) else "challenge"
            payload = CritiquePayload(
                verdict=verdict,
                rationale=r.rationale,
                counterexample_code=r.counterexample_program,
                counterexample_output=output,
                counterexample_found=found is not None,
            )
            summary = f"critic: {verdict}" + (f" — counterexample {found}" if found else "")
            claim = claim.with_evidence(make_evidence(payload, summary=summary, source=self.role))
            if verdict == "refute":
                claim = claim.transition(ClaimStatus.REFUTED)
            elif verdict == "challenge" and claim.status == ClaimStatus.PROPOSED:
                claim = claim.transition(ClaimStatus.CHALLENGED)
            claims.append(claim)
            lines.append(f"- [{verdict}] {claim.statement}: {r.rationale}")
        return self.result(task, "Review:\n" + "\n".join(lines), usage, claims=claims)
