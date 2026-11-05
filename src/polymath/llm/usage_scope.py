"""Per-task usage capture: every LLM call made inside a scope is recorded there, even if the
task later fails or times out, so the run's budget sees all spend."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from polymath.llm.cost import LLMUsage

_SCOPE: ContextVar[list[LLMUsage] | None] = ContextVar("polymath_usage_scope", default=None)


@contextmanager
def usage_scope() -> Iterator[list[LLMUsage]]:
    """Collect usage for calls made in this context (and tasks spawned from it)."""
    records: list[LLMUsage] = []
    token = _SCOPE.set(records)
    try:
        yield records
    finally:
        _SCOPE.reset(token)


def record_usage(usage: LLMUsage) -> None:
    scope = _SCOPE.get()
    if scope is not None:
        scope.append(usage)
