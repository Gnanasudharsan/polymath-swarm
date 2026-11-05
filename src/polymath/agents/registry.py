"""Role → executor mapping used by the orchestrator."""

from __future__ import annotations

from polymath.agents.compute import ComputeAgent
from polymath.agents.critic import CriticAgent
from polymath.agents.formalizer import FormalizerAgent
from polymath.agents.literature import LiteratureAgent
from polymath.agents.reasoner import ReasonerAgent
from polymath.agents.synthesizer import SynthesizerAgent
from polymath.agents.tools import Tools
from polymath.core.models import AgentRole
from polymath.graph.context import TaskExecutor
from polymath.llm.gateway import LLMGateway


def specialists(gateway: LLMGateway, tools: Tools) -> dict[AgentRole, TaskExecutor]:
    """The six specialists, sharing one gateway (budget) and one tool connection."""
    return {
        AgentRole.LITERATURE: LiteratureAgent(gateway, tools),
        AgentRole.REASONER: ReasonerAgent(gateway),
        AgentRole.COMPUTE: ComputeAgent(gateway, tools),
        AgentRole.FORMALIZER: FormalizerAgent(gateway, tools),
        AgentRole.CRITIC: CriticAgent(gateway, tools),
        AgentRole.SYNTHESIZER: SynthesizerAgent(gateway, tools),
    }


def default_executors(gateway: LLMGateway) -> dict[AgentRole, TaskExecutor]:
    """Tool-less fallback: every role is served by the Reasoner (no verification possible)."""
    reasoner = ReasonerAgent(gateway)
    return {role: reasoner for role in AgentRole if role is not AgentRole.SUPERVISOR}
