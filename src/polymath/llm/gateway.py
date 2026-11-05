"""LiteLLM-backed gateway: role→model routing, retries, fallbacks, timeouts, cost + budget.

Every call:
1. checks the run budget (raises :class:`BudgetExceededError` when exhausted);
2. picks a model chain — the role's primary, then fallbacks — or starts with the cheap
   degraded model once the budget is near its ceiling;
3. retries transient errors with exponential backoff, moves to the next model otherwise;
4. records tokens + USD in the :class:`CostTracker` and budget, inside an OTel span.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import litellm
import openai
from pydantic import BaseModel, ConfigDict

from polymath.core.budget import BudgetTracker
from polymath.core.config import Settings
from polymath.core.logging import get_logger
from polymath.core.models import AgentRole
from polymath.core.tracing import get_tracer
from polymath.llm.cost import CostTracker, LLMUsage
from polymath.llm.ledger import SpendLedger
from polymath.llm.usage_scope import record_usage

log = get_logger(__name__)

Message = dict[str, Any]
CompletionFn = Callable[..., Awaitable[Any]]

TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.Timeout,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.ServiceUnavailableError,
    TimeoutError,
)


def _preview(messages: list[Message], limit: int = 4000) -> str:
    """Last user message, truncated — enough to debug a trace without storing whole prompts."""
    users = [m for m in messages if m.get("role") == "user"]
    return str(users[-1].get("content", ""))[:limit] if users else ""


class LLMError(RuntimeError):
    """All models in the chain failed."""


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    model: str
    usage: LLMUsage
    finish_reason: str | None = None


class LLMGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        cost_tracker: CostTracker | None = None,
        budget: BudgetTracker | None = None,
        completion_fn: CompletionFn | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.costs = cost_tracker or CostTracker()
        self.budget = budget
        self._completion_fn = completion_fn
        self._sleep = sleep
        self.ledger = (
            SpendLedger(settings.spend_ledger, settings.spend_cap_usd)
            if settings.spend_ledger
            else None
        )

    def model_chain(self, role: AgentRole, override: str | None = None) -> list[str]:
        """Ordered, de-duplicated list of models to try for ``role``."""
        primary = override or self.settings.model_for(role)
        chain = [primary, *self.settings.fallback_models]
        if self.budget is not None and self.budget.is_near_limit(self.settings.degrade_threshold):
            chain.insert(0, self.settings.degraded_model)
        return list(dict.fromkeys(chain))

    async def complete(
        self,
        role: AgentRole,
        messages: list[Message],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if self.budget is not None:
            self.budget.check()
        if self.ledger is not None:
            self.ledger.check()

        errors: list[str] = []
        tracer = get_tracer()
        for candidate in self.model_chain(role, model):
            with tracer.start_as_current_span("llm.complete") as span:
                span.set_attribute("gen_ai.system", "litellm")
                span.set_attribute("gen_ai.request.model", candidate)
                span.set_attribute("polymath.agent.role", role.value)
                try:
                    response, latency_s = await self._call_with_retries(
                        candidate,
                        messages,
                        max_tokens=max_tokens or self.settings.llm_max_output_tokens,
                        temperature=temperature,
                        response_format=response_format,
                    )
                except TRANSIENT_ERRORS as exc:
                    errors.append(f"{candidate}: retries exhausted ({type(exc).__name__})")
                    span.record_exception(exc)
                    log.warning("llm.model_failed", model=candidate, error=type(exc).__name__)
                    continue
                except openai.OpenAIError as exc:  # base class of every LiteLLM API error
                    errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
                    span.record_exception(exc)
                    log.warning("llm.model_failed", model=candidate, error=type(exc).__name__)
                    continue

                result = self._to_response(role, candidate, response, latency_s)
                span.set_attribute("gen_ai.response.model", result.model)
                span.set_attribute("gen_ai.usage.input_tokens", result.usage.prompt_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", result.usage.completion_tokens)
                span.set_attribute("polymath.cost.usd", result.usage.usd)
                span.set_attribute("gen_ai.usage.cost", result.usage.usd)
                span.set_attribute("langfuse.observation.type", "generation")
                span.set_attribute("langfuse.observation.input", _preview(messages))
                span.set_attribute("langfuse.observation.output", result.content[:4000])
                return result

        raise LLMError("all models failed: " + "; ".join(errors))

    async def _call_with_retries(
        self,
        model: str,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float | None,
        response_format: dict[str, Any] | None,
    ) -> tuple[Any, float]:
        completion = self._completion_fn or litellm.acompletion
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout": self.settings.llm_timeout_s,
            "drop_params": True,  # e.g. Claude 5.x rejects sampling params
            "num_retries": 0,  # retries are ours, so they are visible and testable
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if response_format is not None:
            kwargs["response_format"] = response_format
        if self.settings.reasoning_effort:
            kwargs["reasoning_effort"] = self.settings.reasoning_effort

        attempts = self.settings.llm_max_retries + 1
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                async with asyncio.timeout(self.settings.llm_timeout_s):
                    response = await completion(**kwargs)
            except TRANSIENT_ERRORS as exc:
                if attempt == attempts - 1:
                    raise
                delay = self.settings.llm_retry_base_delay_s * (2**attempt)
                log.info(
                    "llm.retry", model=model, attempt=attempt + 1, delay_s=delay, error=str(exc)
                )
                await self._sleep(delay)
                continue
            return response, time.monotonic() - started
        raise AssertionError("unreachable")  # pragma: no cover

    def _to_response(
        self, role: AgentRole, requested_model: str, response: Any, latency_s: float
    ) -> LLMResponse:
        choice = response.choices[0]
        content = choice.message.content or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        record = self.costs.record(
            model=requested_model,
            role=role,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_s=latency_s,
        )
        if self.budget is not None:
            self.budget.record(tokens=record.total_tokens, usd=record.usd)
        if self.ledger is not None:
            self.ledger.append(record)
        record_usage(record)
        log.info(
            "llm.call",
            role=role.value,
            model=requested_model,
            tokens=record.total_tokens,
            usd=round(record.usd, 6),
            latency_s=round(record.latency_s, 3),
        )
        return LLMResponse(
            content=content,
            model=str(getattr(response, "model", None) or requested_model),
            usage=record,
            finish_reason=getattr(choice, "finish_reason", None),
        )
