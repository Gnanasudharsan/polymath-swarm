"""`polymath solve --memory` end to end with LiteLLM's offline mock (planner + reasoner)."""

from __future__ import annotations

import json
from typing import Any

import litellm
import pytest
from typer.testing import CliRunner

import polymath.cli as cli
import polymath.cli_swarm as cli_swarm

PLAN = json.dumps(
    {
        "problem_type": "proof",
        "rationale": "reason then synthesise",
        "tasks": [
            {"id": "reason", "type": "reasoning", "description": "argue", "deps": []},
            {"id": "synth", "type": "synthesis", "description": "answer", "deps": ["reason"]},
        ],
    }
)
REASONED = json.dumps(
    {
        "reasoning": "trivial",
        "answer": "Yes, it is even.",
        "claims": [{"statement": "2n is even", "confidence": 0.99, "justification": "definition"}],
    }
)


@pytest.fixture
def mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    real = litellm.acompletion

    async def fake(**kwargs: Any) -> Any:
        system = " ".join(m["content"] for m in kwargs["messages"] if m["role"] == "system")
        reply = PLAN if "Supervisor / Planner" in system else REASONED
        return await real(**kwargs, mock_response=reply)

    monkeypatch.setattr(litellm, "acompletion", fake)
    monkeypatch.setattr(cli_swarm, "setup_tracing", lambda **_: None)
    monkeypatch.setattr(cli_swarm, "shutdown_tracing", lambda: None)


@pytest.mark.usefixtures("mocked")
def test_solve_in_memory() -> None:
    result = CliRunner().invoke(cli.app, ["solve", "Is 2n even?", "--memory"])
    assert result.exit_code == 0, result.output
    assert "completed" in result.stdout
    assert "Yes, it is even." in result.stdout
    assert "reason" in result.stdout and "synth" in result.stdout


@pytest.mark.usefixtures("mocked")
def test_solve_with_plan_approval_prompt() -> None:
    result = CliRunner().invoke(
        cli.app, ["solve", "Is 2n even?", "--memory", "--approve-plan"], input="y\n"
    )
    assert result.exit_code == 0, result.output
    assert "Proposed plan" in result.stdout and "completed" in result.stdout


def test_graph_command_prints_mermaid() -> None:
    result = CliRunner().invoke(cli.app, ["graph"])
    assert result.exit_code == 0 and "execute_task" in result.stdout
