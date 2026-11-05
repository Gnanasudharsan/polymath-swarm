"""``lean`` MCP server: check Lean 4 + Mathlib code, inspect goals, verify theorems."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict

from polymath.core.config import get_settings
from polymath.mcp_servers.lean import checker
from polymath.mcp_servers.lean.checker import (
    LeanCheckResult,
    LeanInputError,
    LeanVerification,
    SorryGoal,
)
from polymath.mcp_servers.lean.repl import LeanREPL, LeanREPLError

INSTRUCTIONS = (
    "Lean 4 with Mathlib (v4.35.0). Every file is checked as if it began with "
    "`import Mathlib`. The first call may take ~1 minute while Mathlib loads; later calls "
    "take about a second. A proof counts as verified only via verify_proof."
)


class GoalsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sorries: list[SorryGoal]
    unsolved_goals: list[str]


class SorryCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sorry_count: int
    textual: int
    compiler_reported: int


def build_server(repl: checker.REPLRunner | None = None, timeout_s: float = 60.0) -> MCPServer[Any]:
    owned = repl is None
    runner: checker.REPLRunner = repl or LeanREPL(get_settings().lean_image)

    @asynccontextmanager
    async def lifespan(_server: MCPServer[Any]) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owned and isinstance(runner, LeanREPL):
                await runner.close()

    server: MCPServer[Any] = MCPServer("lean", instructions=INSTRUCTIONS, lifespan=lifespan)

    async def guarded_check(code: str) -> LeanCheckResult:
        try:
            return await checker.check(runner, code, timeout_s)
        except (LeanInputError, LeanREPLError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    async def check(code: str) -> LeanCheckResult:
        """Elaborate a Lean file. ok = no errors; complete = no errors and no sorry."""
        return await guarded_check(code)

    @server.tool()
    async def get_goals(code: str) -> GoalsResult:
        """Goal states at every `sorry`, plus goals left open by failing tactics."""
        res = await guarded_check(code)
        return GoalsResult(sorries=res.sorries, unsolved_goals=res.unsolved_goals)

    @server.tool()
    async def count_sorry(code: str) -> SorryCount:
        """Count sorry/admit: textual occurrences outside comments and compiler-reported."""
        res = await guarded_check(code)
        body, _ = checker.prepare(code)
        textual = checker.count_sorry_tokens(body)
        return SorryCount(
            sorry_count=res.sorry_count, textual=textual, compiler_reported=len(res.sorries)
        )

    @server.tool()
    async def verify_proof(code: str, theorem_name: str) -> LeanVerification:
        """Verify that `theorem_name` in `code` is fully proved: no errors, no sorry, and
        only the standard axioms (propext, Classical.choice, Quot.sound)."""
        try:
            return await checker.verify(runner, code, theorem_name, timeout_s)
        except (LeanInputError, LeanREPLError) as exc:
            raise ToolError(str(exc)) from exc

    return server


def main() -> None:
    build_server().run("stdio")
