from __future__ import annotations

import litellm
import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from polymath.core.budget import BudgetExceededError, BudgetTracker
from polymath.core.config import Settings
from polymath.core.models import AgentRole, RunBudget
from polymath.core.tracing import setup_tracing
from polymath.llm.gateway import LLMError, LLMGateway
from tests.conftest import FakeCompletion, no_sleep

MSGS = [{"role": "user", "content": "hi"}]


def _rate_limit() -> litellm.exceptions.RateLimitError:
    return litellm.exceptions.RateLimitError("slow down", llm_provider="anthropic", model="m")


def _auth_error() -> litellm.exceptions.AuthenticationError:
    return litellm.exceptions.AuthenticationError("bad key", llm_provider="anthropic", model="m")


def _gateway(settings: Settings, fake: FakeCompletion, **kw: object) -> LLMGateway:
    return LLMGateway(settings, completion_fn=fake, sleep=no_sleep, **kw)  # type: ignore[arg-type]


async def test_routes_role_to_configured_model(settings: Settings) -> None:
    fake = FakeCompletion(["hello"])
    resp = await _gateway(settings, fake).complete(AgentRole.CRITIC, MSGS)
    assert resp.content == "hello"
    assert fake.models_called == [settings.model_for(AgentRole.CRITIC)]
    assert fake.calls[0]["drop_params"] is True


async def test_retries_transient_errors_then_succeeds(settings: Settings) -> None:
    fake = FakeCompletion([_rate_limit(), _rate_limit(), "ok"])
    resp = await _gateway(settings, fake).complete(AgentRole.REASONER, MSGS)
    assert resp.content == "ok"
    assert len(set(fake.models_called)) == 1 and len(fake.calls) == 3


async def test_falls_back_after_retries_exhausted(settings: Settings) -> None:
    fake = FakeCompletion([_rate_limit(), _rate_limit(), _rate_limit(), "from fallback"])
    resp = await _gateway(settings, fake).complete(AgentRole.REASONER, MSGS)
    assert resp.content == "from fallback"
    assert fake.models_called[-1] == "fallback-model"


async def test_non_transient_error_skips_straight_to_fallback(settings: Settings) -> None:
    fake = FakeCompletion([_auth_error(), "fallback ok"])
    resp = await _gateway(settings, fake).complete(AgentRole.REASONER, MSGS)
    assert resp.content == "fallback ok"
    assert fake.models_called == [settings.model_for(AgentRole.REASONER), "fallback-model"]


async def test_all_models_failing_raises(settings: Settings) -> None:
    fake = FakeCompletion([_auth_error(), _auth_error()])
    with pytest.raises(LLMError, match="all models failed"):
        await _gateway(settings, fake).complete(AgentRole.REASONER, MSGS)


async def test_records_cost_and_budget(settings: Settings) -> None:
    budget = BudgetTracker(RunBudget(max_tokens=10_000, max_usd=5.0))
    fake = FakeCompletion(["a", "b"])
    gw = _gateway(settings, fake, budget=budget)
    await gw.complete(AgentRole.REASONER, MSGS)
    await gw.complete(AgentRole.CRITIC, MSGS)
    assert gw.costs.summary().calls == 2
    assert budget.tokens_used == 300  # 2 x (100 prompt + 50 completion)
    assert budget.usd_used == pytest.approx(gw.costs.total_usd)
    assert gw.costs.total_usd > 0  # claude models are priced by LiteLLM


async def test_budget_exhausted_blocks_call(settings: Settings) -> None:
    budget = BudgetTracker(RunBudget(max_tokens=100))
    budget.record(tokens=100)
    fake = FakeCompletion(["never"])
    with pytest.raises(BudgetExceededError):
        await _gateway(settings, fake, budget=budget).complete(AgentRole.REASONER, MSGS)
    assert fake.calls == []


async def test_degrades_to_cheap_model_near_limit(settings: Settings) -> None:
    budget = BudgetTracker(RunBudget(max_usd=1.0))
    budget.record(usd=0.9)
    fake = FakeCompletion(["cheap"])
    gw = _gateway(settings, fake, budget=budget)
    assert gw.model_chain(AgentRole.REASONER)[0] == "cheap-model"
    await gw.complete(AgentRole.REASONER, MSGS)
    assert fake.models_called == ["cheap-model"]


async def test_model_override(settings: Settings) -> None:
    fake = FakeCompletion(["x"])
    await _gateway(settings, fake).complete(AgentRole.REASONER, MSGS, model="custom")
    assert fake.models_called == ["custom"]


async def test_emits_genai_span(settings: Settings) -> None:
    exporter = InMemorySpanExporter()
    setup_tracing().add_span_processor(SimpleSpanProcessor(exporter))
    await _gateway(settings, FakeCompletion(["x"])).complete(AgentRole.REASONER, MSGS)
    spans = [s for s in exporter.get_finished_spans() if s.name == "llm.complete"]
    assert spans
    attrs = spans[-1].attributes or {}
    assert attrs["polymath.agent.role"] == "reasoner"
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert "polymath.cost.usd" in attrs
