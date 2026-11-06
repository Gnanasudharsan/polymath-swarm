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
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
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
async def postgres_checkpointer(dsn: str, max_size: int = 10) -> AsyncIterator[AsyncPostgresSaver]:
    """A checkpointer on a connection *pool*, not one shared connection.

    The API reads checkpoints from many requests at once, and a client disconnect (e.g. a closed
    SSE stream) cancels a read mid-query. On a single connection that left it busy and every
    later read failed with "another command is already in progress" until restart. The pool
    checks each connection on return and discards a broken one.
    """
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
        dsn,
        min_size=1,
        max_size=max_size,
        open=False,
        # What AsyncPostgresSaver.from_conn_string uses for its single connection.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        check=AsyncConnectionPool.check_connection,
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(conn=pool, serde=make_serde())
        await saver.setup()
        yield saver
    finally:
        await pool.close()
