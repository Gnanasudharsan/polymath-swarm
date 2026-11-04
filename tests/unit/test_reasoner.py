from __future__ import annotations

import json

import pytest

from polymath.agents.base import AgentContext
from polymath.agents.prompts import PromptNotFoundError, available_versions, load_prompt
from polymath.agents.reasoner import ReasonerAgent
from polymath.core.config import Settings
from polymath.core.models import AgentRole, Claim, ClaimStatus, Problem, Task, TaskType
from polymath.llm.gateway import LLMGateway
from tests.conftest import FakeCompletion, no_sleep

REPLY = json.dumps(
    {
        "reasoning": "n^2 - n = n(n-1), a product of consecutive integers, one of which is even.",
        "answer": "Yes: n^2 - n is always even.",
        "claims": [
            {
                "statement": "n(n-1) is even for all integers n",
                "confidence": 0.98,
                "justification": "one of n, n-1 is even",
            },
        ],
    }
)


def test_prompt_is_versioned_file() -> None:
    assert 1 in available_versions("reasoner")
    assert "Reasoner" in load_prompt("reasoner")
    with pytest.raises(PromptNotFoundError):
        load_prompt("reasoner", 999)


async def test_reasoner_returns_proposed_claims(settings: Settings) -> None:
    fake = FakeCompletion([REPLY])
    agent = ReasonerAgent(LLMGateway(settings, completion_fn=fake, sleep=no_sleep))
    problem = Problem(statement="Is n^2 - n always even?")
    task = Task(
        type=TaskType.REASONING, description=problem.statement, assigned_role=AgentRole.REASONER
    )
    existing = Claim(statement="n is an integer")
    result = await agent.run(task, AgentContext(problem=problem, claims=[existing]))

    assert result.success and result.task_id == task.id
    assert result.output.startswith("Yes")
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.status is ClaimStatus.PROPOSED
    assert claim.proposed_by is AgentRole.REASONER and claim.task_id == task.id
    assert claim.evidence == []  # informal reasoning is not evidence
    assert result.usage and result.usd >= 0

    sent = fake.calls[0]["messages"]
    assert "Reasoner" in sent[1]["content"]  # versioned system prompt after schema instruction
    assert "n is an integer" in sent[-1]["content"]  # blackboard claims are shown
