"""Structured output: ask for JSON matching a Pydantic model, validate, and repair on failure.

Provider-agnostic: the JSON schema goes into the system prompt and the reply is parsed
leniently (code fences, leading prose). On a validation error the model is shown the
error and asked to fix its JSON, up to ``max_repairs`` times.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, ValidationError

from polymath.core.logging import get_logger
from polymath.core.models import AgentRole
from polymath.llm.gateway import LLMGateway, LLMResponse, Message

log = get_logger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(ValueError):
    """The model never produced JSON that validated against the schema."""


class StructuredResult[T: BaseModel](BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: T
    responses: list[LLMResponse]

    @property
    def attempts(self) -> int:
        return len(self.responses)


def schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "Respond with a single JSON object and nothing else (no prose, no code fences). "
        "It must validate against this JSON Schema:\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}"
    )


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may include fences or surrounding prose."""
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def parse_as[T: BaseModel](schema: type[T], text: str) -> T:
    return schema.model_validate_json(extract_json(text))


async def complete_structured[T: BaseModel](
    gateway: LLMGateway,
    role: AgentRole,
    messages: list[Message],
    schema: type[T],
    *,
    max_repairs: int = 2,
    model: str | None = None,
    max_tokens: int | None = None,
) -> StructuredResult[T]:
    convo: list[Message] = [
        {"role": "system", "content": schema_instruction(schema)},
        *messages,
    ]
    responses: list[LLMResponse] = []
    last_error = ""
    for attempt in range(max_repairs + 1):
        response = await gateway.complete(role, convo, model=model, max_tokens=max_tokens)
        responses.append(response)
        try:
            value = parse_as(schema, response.content)
        except ValidationError as exc:
            last_error = str(exc)
            log.info("llm.structured.repair", schema=schema.__name__, attempt=attempt + 1)
            convo = [
                *convo,
                {"role": "assistant", "content": response.content},
                {
                    "role": "user",
                    "content": (
                        "Your reply did not validate against the schema. Errors:\n"
                        f"{last_error}\nReturn only the corrected JSON object."
                    ),
                },
            ]
            continue
        return StructuredResult[T](value=value, responses=responses)
    raise StructuredOutputError(
        f"{schema.__name__}: no valid JSON after {max_repairs + 1} attempts; last error: "
        f"{last_error}"
    )
