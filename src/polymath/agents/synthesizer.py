"""Synthesizer: run the verification gate, then write an answer from verified claims only."""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.base import AgentContext, AgentResult, BaseAgent, render_claims, task_brief
from polymath.agents.tools import Tools
from polymath.core.models import AgentRole, Claim, Task
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway
from polymath.verification.gate import VerificationGate
from polymath.verification.report import EvidenceReport, ReportedClaim, bucket, render_markdown

_CITE = re.compile(r"\[(claim_[0-9a-f]+)\]")


class Synthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, description="Markdown; cite verified claims as [claim_id]")


def strip_unverified_citations(answer: str, verified_ids: set[str]) -> tuple[str, list[str]]:
    """Remove citations of anything that is not a verified claim; return the offenders."""
    bad = sorted({m for m in _CITE.findall(answer) if m not in verified_ids})
    for cid in bad:
        answer = answer.replace(f"[{cid}]", "[unverified]")
    return answer, bad


class SynthesizerAgent(BaseAgent):
    role: ClassVar[AgentRole] = AgentRole.SYNTHESIZER
    prompt_name: ClassVar[str] = "synthesizer"

    def __init__(self, gateway: LLMGateway, tools: Tools) -> None:
        super().__init__(gateway)
        self.gate = VerificationGate(tools)

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        usage: list[LLMUsage] = []
        reported: list[ReportedClaim] = []
        for claim in context.claims:
            gated, decision = await self.gate.apply(claim)
            reported.append(ReportedClaim(claim=gated, decision=decision))
        groups = bucket(reported)
        verified: list[Claim] = [rc.claim for rc in groups["verified"]]

        if verified:
            synthesis = await self.ask(
                Synthesis,
                f"{task_brief(task, context)}\n\n## Verified claims\n{render_claims(verified)}",
                usage,
            )
            answer, bad = strip_unverified_citations(synthesis.answer, {c.id for c in verified})
            if bad:
                answer += "\n\n_(References to unverified claims were removed.)_"
        else:
            answer = (
                "No claim passed the verification gate, so the swarm cannot state a verified "
                "answer. See the conjectures below for what was proposed but not established."
            )
        report = EvidenceReport(
            problem=context.problem,
            answer=answer,
            verified=groups["verified"],
            conjectures=groups["conjectures"],
            refuted=groups["refuted"],
        )
        return self.result(
            task,
            answer,
            usage,
            claims=[rc.claim for rc in reported],
            data={"report": report.model_dump(mode="json"), "markdown": render_markdown(report)},
        )
