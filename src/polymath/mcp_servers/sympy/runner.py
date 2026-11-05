"""Run a SymPy operation in a fresh child process so runaway computations can be killed."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from multiprocessing.connection import Connection
from typing import Any

from polymath.mcp_servers.sympy.ops import OPERATIONS, SympyInputError


class SympyTimeoutError(TimeoutError):
    pass


def _child(op: str, kwargs: dict[str, Any], conn: Connection) -> None:
    try:
        conn.send(("ok", OPERATIONS[op](**kwargs)))
    except SympyInputError as exc:
        conn.send(("input_error", str(exc)))
    except Exception as exc:
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def run_blocking(op: str, kwargs: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(op, kwargs, child), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout_s):
            raise SympyTimeoutError(f"sympy {op} exceeded {timeout_s:g}s")
        status, payload = parent.recv()
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(1)
        parent.close()
    if status == "input_error":
        raise SympyInputError(payload)
    if status == "error":
        raise RuntimeError(payload)
    result: dict[str, Any] = payload
    return result


async def run(op: str, kwargs: dict[str, Any], timeout_s: float = 10.0) -> dict[str, Any]:
    return await asyncio.to_thread(run_blocking, op, kwargs, timeout_s)
