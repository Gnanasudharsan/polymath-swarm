from __future__ import annotations

import pytest
from pydantic import BaseModel

from polymath.core.config import Settings
from polymath.core.models import AgentRole
from polymath.llm.gateway import LLMGateway
from polymath.llm.structured import (
    StructuredOutputError,
    complete_structured,
    extract_json,
    schema_instruction,
)
from tests.conftest import FakeCompletion, no_sleep


class Answer(BaseModel):
    value: int
    unit: str


@pytest.mark.parametrize(
    "text",
    [
        '{"value": 3, "unit": "m"}',
        '```json\n{"value": 3, "unit": "m"}\n```',
        'Sure! Here it is: {"value": 3, "unit": "m"} Hope that helps.',
    ],
)
def test_extract_json_variants(text: str) -> None:
    assert Answer.model_validate_json(extract_json(text)) == Answer(value=3, unit="m")


def test_schema_instruction_embeds_schema() -> None:
    assert '"unit"' in schema_instruction(Answer)


async def test_parses_valid_reply_first_time(settings: Settings) -> None:
    fake = FakeCompletion(['{"value": 7, "unit": "kg"}'])
    gw = LLMGateway(settings, completion_fn=fake, sleep=no_sleep)
    res = await complete_structured(
        gw, AgentRole.COMPUTE, [{"role": "user", "content": "q"}], Answer
    )
    assert res.value == Answer(value=7, unit="kg")
    assert res.attempts == 1
    assert fake.calls[0]["messages"][0]["role"] == "system"


async def test_repairs_invalid_reply(settings: Settings) -> None:
    fake = FakeCompletion(['{"value": "seven"}', '{"value": 7, "unit": "kg"}'])
    gw = LLMGateway(settings, completion_fn=fake, sleep=no_sleep)
    res = await complete_structured(
        gw, AgentRole.COMPUTE, [{"role": "user", "content": "q"}], Answer
    )
    assert res.value.value == 7
    assert res.attempts == 2
    repair_prompt = fake.calls[1]["messages"][-1]["content"]
    assert "did not validate" in repair_prompt


async def test_gives_up_after_max_repairs(settings: Settings) -> None:
    fake = FakeCompletion(["nope", "still nope", "never"])
    gw = LLMGateway(settings, completion_fn=fake, sleep=no_sleep)
    with pytest.raises(StructuredOutputError, match="3 attempts"):
        await complete_structured(
            gw, AgentRole.COMPUTE, [{"role": "user", "content": "q"}], Answer, max_repairs=2
        )
