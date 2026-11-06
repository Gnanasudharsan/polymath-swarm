from __future__ import annotations

import json
from functools import partial

import litellm
import pytest
from typer.testing import CliRunner

import polymath.cli as cli
from tests.unit.test_reasoner import REPLY


@pytest.fixture
def mocked_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route LiteLLM to its built-in offline mock so the CLI runs end to end without network."""
    monkeypatch.setattr(litellm, "acompletion", partial(litellm.acompletion, mock_response=REPLY))
    monkeypatch.setattr(cli, "setup_tracing", lambda *_, **__: None)
    monkeypatch.setattr(cli, "shutdown_tracing", lambda: None)


@pytest.mark.usefixtures("mocked_llm")
def test_ask_prints_answer_claims_and_cost() -> None:
    result = CliRunner().invoke(cli.app, ["ask", "Is n^2 - n always even?"])
    assert result.exit_code == 0, result.output
    assert "Yes: n^2 - n is always even." in result.stdout
    assert "n(n-1) is even" in result.stdout
    assert "call(s)" in result.stdout


@pytest.mark.usefixtures("mocked_llm")
def test_ask_json_output() -> None:
    result = CliRunner().invoke(cli.app, ["ask", "q", "--json", "--model", "claude-haiku-5-5"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["result"]["role"] == "reasoner"
    assert payload["cost"]["calls"] == 1
    assert payload["cost"]["by_model"].keys() == {"claude-haiku-5-5"}
