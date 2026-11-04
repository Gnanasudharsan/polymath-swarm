"""Shared fixtures. Unit tests never touch a real LLM: they use :class:`FakeCompletion`."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from polymath.core.config import Settings


def fake_response(
    content: str,
    *,
    model: str = "fake-model",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> SimpleNamespace:
    """Minimal object with the shape of a LiteLLM ``ModelResponse``."""
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, role="assistant"), finish_reason="stop"
            )
        ],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class FakeCompletion:
    """Async stand-in for ``litellm.acompletion`` that replays scripted outcomes.

    Each item is a response object, a string (wrapped with :func:`fake_response`), or an
    exception instance to raise.
    """

    def __init__(self, script: Sequence[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("FakeCompletion script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            return fake_response(item, model=kwargs["model"])
        return item

    @property
    def models_called(self) -> list[str]:
        return [c["model"] for c in self.calls]


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        fallback_models=["fallback-model"],
        degraded_model="cheap-model",
        llm_max_retries=2,
        llm_retry_base_delay_s=0.0,
        llm_timeout_s=5.0,
    )
