"""Checkpointers with an explicit deserialisation allowlist (no arbitrary types from the DB)."""

from __future__ import annotations

import enum
import inspect
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from types import ModuleType

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

import polymath.agents.base as agents_base
import polymath.core.models as core_models
import polymath.graph.state as graph_state
import polymath.llm.cost as llm_cost

STATE_MODULES: tuple[ModuleType, ...] = (core_models, agents_base, llm_cost, graph_state)


def _allowed_types(modules: Iterable[ModuleType]) -> list[tuple[str, str]]:
    allowed = []
    for module in modules:
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and obj.__module__ == module.__name__
                and issubclass(obj, BaseModel | enum.Enum)
            ):
                allowed.append((module.__name__, name))
    return sorted(allowed)


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_allowed_types(STATE_MODULES))


def memory_checkpointer() -> InMemorySaver:
    return InMemorySaver(serde=make_serde())


@asynccontextmanager
async def postgres_checkpointer(dsn: str) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(dsn, serde=make_serde()) as saver:
        await saver.setup()
        yield saver
