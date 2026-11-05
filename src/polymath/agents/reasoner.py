"""Reasoner: informal mathematical argument construction."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.base import AgentContext, AgentResult, BaseAgent
from polymath.core.models import AgentMessage, AgentRole, Claim, Task
from polymath.llm.gateway import Message
from polymath.llm.structured import complete_structured


class ProposedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, description="One atomic, checkable statement.")
    confidence: float = Field(ge=0.0, le=1.0, description="Calibrated probability it is true.")
    justification: str = Field(description="Why the claim follows; cite prior steps.")


class ReasonerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(description="Step-by-step argument.")
    answer: str = Field(description="Concise direct answer to the problem.")
    claims: list[ProposedClaim] = Field(default_factory=list, max_length=8)


class ReasonerAgent(BaseAgent):
    role: ClassVar[AgentRole] = AgentRole.REASONER
    prompt_name: ClassVar[str] = "reasoner"

    def build_messages(self, task: Task, context: AgentContext) -> list[Message]:
        parts = [f"## Problem\n{context.problem.statement}"]
        if context.problem.context:
            parts.append(f"## Background\n{context.problem.context}")
        if task.description != context.problem.statement:
            parts.append(f"## Your task\n{task.description}")
        if context.claims:
            listed = "\n".join(f"- [{c.status}] {c.statement}" for c in context.claims)
            parts.append(f"## Claims already on the blackboard\n{listed}")
        if context.notes:
            parts.append(f"## Notes\n{context.notes}")
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "\n\n".join(parts)},
        ]

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        result = await complete_structured(
            self.gateway, self.role, self.build_messages(task, context), ReasonerOutput
        )
        out = result.value
        claims = [
            Claim(
                statement=c.statement,
                confidence=c.confidence,
                proposed_by=self.role,
                task_id=task.id,
            )
            for c in out.claims
        ]
        message = AgentMessage(
            sender=self.role, task_id=task.id, content=out.reasoning, claims=claims
        )
        return AgentResult(
            task_id=task.id,
            role=self.role,
            output=out.answer,
            claims=claims,
            messages=[message],
            usage=[r.usage for r in result.responses],
        )
