"""Base class for every specialist agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.prompts import load_prompt
from polymath.core.models import AgentMessage, AgentRole, Claim, Problem, Task
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway


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
