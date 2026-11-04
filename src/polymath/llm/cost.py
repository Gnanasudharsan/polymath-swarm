"""Token and USD accounting for every LLM call."""

from __future__ import annotations

from collections import defaultdict

import litellm
from pydantic import BaseModel, ConfigDict, Field

from polymath.core.logging import get_logger
from polymath.core.models import AgentRole, utcnow

log = get_logger(__name__)


class LLMUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    role: AgentRole | None = None
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    usd: float = Field(ge=0)
    latency_s: float = Field(default=0.0, ge=0)
    timestamp: str = Field(default_factory=lambda: utcnow().isoformat())

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class CostSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usd: float
    by_model: dict[str, float]
    by_role: dict[str, float]


def estimate_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost from LiteLLM's pricing table; 0.0 (with a warning) for unpriced models."""
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
    except Exception:  # litellm raises a bare Exception for unmapped models
        log.warning("llm.cost.unpriced_model", model=model)
        return 0.0
    return float(prompt_cost + completion_cost)


class CostTracker:
    """Append-only ledger of :class:`LLMUsage` records with aggregate views."""

    def __init__(self) -> None:
        self._records: list[LLMUsage] = []

    @property
    def records(self) -> tuple[LLMUsage, ...]:
        return tuple(self._records)

    def add(self, usage: LLMUsage) -> None:
        self._records.append(usage)

    def record(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        role: AgentRole | None = None,
        usd: float | None = None,
        latency_s: float = 0.0,
    ) -> LLMUsage:
        cost = usd if usd is not None else estimate_usd(model, prompt_tokens, completion_tokens)
        usage = LLMUsage(
            model=model,
            role=role,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd=cost,
            latency_s=latency_s,
        )
        self.add(usage)
        return usage

    @property
    def total_usd(self) -> float:
        return sum(r.usd for r in self._records)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self._records)

    def summary(self) -> CostSummary:
        by_model: defaultdict[str, float] = defaultdict(float)
        by_role: defaultdict[str, float] = defaultdict(float)
        for r in self._records:
            by_model[r.model] += r.usd
            by_role[r.role.value if r.role else "unassigned"] += r.usd
        prompt = sum(r.prompt_tokens for r in self._records)
        completion = sum(r.completion_tokens for r in self._records)
        return CostSummary(
            calls=len(self._records),
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            usd=self.total_usd,
            by_model=dict(by_model),
            by_role=dict(by_role),
        )
