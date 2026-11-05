"""Base class for every specialist agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.prompts import load_prompt
from polymath.core.models import AgentMessage, AgentRole, Claim, ClaimStatus, Problem, Task
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway
from polymath.llm.structured import complete_structured


class ToolSpec(BaseModel):
    """Description of a tool an agent may call (MCP-backed from Phase 2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class AgentContext(BaseModel):
    """What an agent sees when it runs a task: the problem plus shared state."""

    model_config = ConfigDict(extra="forbid")

    problem: Problem
    claims: list[Claim] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    notes: str = ""


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    role: AgentRole
    output: str
    claims: list[Claim] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    usage: list[LLMUsage] = Field(default_factory=list)
    success: bool = True
    error: str | None = None
    data: dict[str, Any] = Field(default_factory=dict, description="Structured outputs.")

    @property
    def usd(self) -> float:
        return sum(u.usd for u in self.usage)


class BaseAgent(ABC):
    """An LLM-backed specialist with a versioned system prompt and optional tools."""

    role: ClassVar[AgentRole]
    prompt_name: ClassVar[str]
    prompt_version: ClassVar[int | None] = None  # None → latest

    def __init__(self, gateway: LLMGateway, *, tools: list[ToolSpec] | None = None) -> None:
        self.gateway = gateway
        self.tools: list[ToolSpec] = tools or []

    @property
    def system_prompt(self) -> str:
        return load_prompt(self.prompt_name, self.prompt_version)

    @abstractmethod
    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        """Execute ``task`` and return claims/messages for the blackboard."""

    async def ask[T: BaseModel](
        self,
        schema: type[T],
        user: str,
        usage: list[LLMUsage],
        *,
        prompt: str | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> T:
        """One structured LLM call with a versioned system prompt; usage is appended to ``usage``
        (agents are shared across concurrent tasks, so nothing is kept on ``self``)."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": load_prompt(prompt or self.prompt_name)},
            *(history or []),
            {"role": "user", "content": user},
        ]
        result = await complete_structured(self.gateway, self.role, messages, schema)
        usage.extend(r.usage for r in result.responses)
        return result.value

    def result(
        self,
        task: Task,
        output: str,
        usage: list[LLMUsage],
        *,
        claims: list[Claim] | None = None,
        data: dict[str, Any] | None = None,
    ) -> AgentResult:
        claims = claims or []
        return AgentResult(
            task_id=task.id,
            role=self.role,
            output=output,
            claims=claims,
            messages=[
                AgentMessage(sender=self.role, task_id=task.id, content=output, claims=claims)
            ],
            usage=usage,
            data=data or {},
        )


def open_claims(context: AgentContext) -> list[Claim]:
    """Claims still awaiting a verdict."""
    final = {ClaimStatus.VERIFIED, ClaimStatus.REFUTED}
    return [c for c in context.claims if c.status not in final]


def render_claims(claims: list[Claim]) -> str:
    if not claims:
        return "(none)"
    return "\n".join(
        f"- [{c.id}] ({c.status.value}, p={c.confidence:.2f}) {c.statement}" for c in claims
    )


def task_brief(task: Task, context: AgentContext) -> str:
    parts = [f"## Problem\n{context.problem.statement}", f"## Your task\n{task.description}"]
    if context.problem.context:
        parts.insert(1, f"## Background\n{context.problem.context}")
    if context.notes:
        parts.append(f"## Outputs of earlier tasks\n{context.notes}")
    return "\n\n".join(parts)
