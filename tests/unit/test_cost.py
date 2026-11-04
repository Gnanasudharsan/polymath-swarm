from __future__ import annotations

import pytest

from polymath.core.models import AgentRole
from polymath.llm.cost import CostTracker, estimate_usd


def test_estimate_uses_litellm_pricing() -> None:
    # claude-haiku-5-5 is in LiteLLM's bundled price map; cost must be positive and linear.
    one = estimate_usd("claude-haiku-5-5", 1000, 1000)
    two = estimate_usd("claude-haiku-5-5", 2000, 2000)
    assert one > 0
    assert two == pytest.approx(2 * one)


def test_unknown_model_costs_zero() -> None:
    assert estimate_usd("definitely-not-a-model-xyz", 1000, 1000) == 0.0


def test_aggregation_by_model_and_role() -> None:
    t = CostTracker()
    t.record(model="m1", role=AgentRole.REASONER, prompt_tokens=10, completion_tokens=5, usd=0.1)
    t.record(model="m2", role=AgentRole.CRITIC, prompt_tokens=20, completion_tokens=5, usd=0.2)
    t.record(model="m1", prompt_tokens=1, completion_tokens=1, usd=0.05)
    s = t.summary()
    assert s.calls == 3
    assert s.total_tokens == 42
    assert s.usd == pytest.approx(0.35)
    assert s.by_model == pytest.approx({"m1": 0.15, "m2": 0.2})
    assert s.by_role == pytest.approx({"reasoner": 0.1, "critic": 0.2, "unassigned": 0.05})


def test_records_are_immutable_view() -> None:
    t = CostTracker()
    t.record(model="m", prompt_tokens=1, completion_tokens=1, usd=0.0)
    assert isinstance(t.records, tuple)
