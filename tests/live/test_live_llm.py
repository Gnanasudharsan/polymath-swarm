"""Real-model smoke tests. Run with: uv run pytest -m live (needs a provider API key).

Uses the cheapest available model: Claude Haiku if ANTHROPIC_API_KEY is set, otherwise an
OpenAI mini model. Each call is capped by a small RunBudget.
"""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from polymath.cli import app, ask_reasoner
from polymath.core.config import Settings, load_env_file
from polymath.core.models import RunBudget

pytestmark = pytest.mark.live

load_env_file()

if os.environ.get("ANTHROPIC_API_KEY"):
    LIVE_MODEL: str | None = "claude-haiku-5-5"
elif os.environ.get("OPENAI_API_KEY"):
    LIVE_MODEL = "gpt-5-mini"
else:
    LIVE_MODEL = None

requires_key = pytest.mark.skipif(LIVE_MODEL is None, reason="no LLM provider API key set")


@requires_key
async def test_reasoner_on_real_model() -> None:
    assert LIVE_MODEL is not None
    result, cost = await ask_reasoner(
        "Is the sum of two odd integers always even? Answer briefly.",
        Settings(),
        RunBudget(max_usd=0.10, max_tokens=20_000),
        model=LIVE_MODEL,
    )
    assert "even" in result.output.lower()
    assert result.claims
    assert cost.calls >= 1
    assert 0 < cost.usd < 0.10


@requires_key
def test_cli_ask_end_to_end() -> None:
    assert LIVE_MODEL is not None
    result = CliRunner().invoke(
        app, ["ask", "What is 17 * 23? Answer briefly.", "--model", LIVE_MODEL, "--max-usd", "0.1"]
    )
    assert result.exit_code == 0, result.output
    assert "391" in result.stdout
