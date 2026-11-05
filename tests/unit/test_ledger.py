from __future__ import annotations

from pathlib import Path

import pytest

from polymath.core.budget import BudgetExceededError
from polymath.core.config import Settings
from polymath.core.models import AgentRole
from polymath.llm.gateway import LLMGateway
from tests.conftest import FakeCompletion, no_sleep


async def test_ledger_records_calls_and_enforces_cap(tmp_path: Path, settings: Settings) -> None:
    ledger = tmp_path / "spend.jsonl"
    # each fake call costs ≈ $0.000035 on claude-haiku-5-5 pricing
    capped = settings.model_copy(update={"spend_ledger": ledger, "spend_cap_usd": 0.00005})
    msgs = [{"role": "user", "content": "x"}]
    gw = LLMGateway(capped, completion_fn=FakeCompletion(["a", "b", "c"]), sleep=no_sleep)
    await gw.complete(AgentRole.CRITIC, msgs, model="claude-haiku-5-5")
    assert ledger.exists() and gw.ledger is not None
    first = gw.ledger.total_usd()
    assert first > 0
    await gw.complete(AgentRole.CRITIC, msgs, model="claude-haiku-5-5")
    # a new gateway (another process) sees the same ledger and refuses to spend more
    gw2 = LLMGateway(capped, completion_fn=FakeCompletion(["d"]), sleep=no_sleep)
    with pytest.raises(BudgetExceededError, match="ledger_usd"):
        await gw2.complete(AgentRole.CRITIC, msgs, model="claude-haiku-5-5")


def test_openai_profile_fills_unset_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYMATH_MODEL_PROFILE", "openai")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.model_for(AgentRole.FORMALIZER) == "gpt-5"
    assert s.model_for(AgentRole.CRITIC) == "gpt-5-mini"
    assert s.degraded_model == "gpt-5-nano" and s.reasoning_effort == "low"
    explicit = Settings(_env_file=None, degraded_model="custom")  # type: ignore[call-arg]
    assert explicit.degraded_model == "custom"
