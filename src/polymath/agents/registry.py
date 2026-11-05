"""Role → executor mapping used by the orchestrator."""

from __future__ import annotations

from polymath.agents.reasoner import ReasonerAgent
from polymath.core.models import AgentRole
from polymath.graph.context import TaskExecutor
from polymath.llm.gateway import LLMGateway


def default_executors(gateway: LLMGateway) -> dict[AgentRole, TaskExecutor]:
    """Phase 3 placeholder: every role is served by the Reasoner, which follows the task
    description. Phase 4 replaces this with the dedicated specialists."""
    reasoner = ReasonerAgent(gateway)
    return {role: reasoner for role in AgentRole if role is not AgentRole.SUPERVISOR}
