"""Typed tool facade for agents. Production calls go through MCP (:class:`MCPToolbox`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from polymath.core.config import Settings
from polymath.mcp_servers import lean, literature, sandbox, sympy
from polymath.mcp_servers.client import MCPToolbox
from polymath.mcp_servers.lean.checker import LeanCheckResult, LeanVerification
from polymath.mcp_servers.lean.repl import LeanREPL
from polymath.mcp_servers.literature.models import Paper, PaperList
from polymath.mcp_servers.sandbox.docker import DockerSandbox, SandboxResult


class ToolCallError(RuntimeError):
    """A tool reported an error (bad input, timeout, upstream failure)."""


class Tools(Protocol):
    async def run_python(self, code: str, timeout_s: float = 30.0) -> SandboxResult: ...
    async def sympy(self, op: str, **kwargs: Any) -> dict[str, Any]: ...
    async def search_papers(self, source: str, query: str, limit: int = 5) -> PaperList: ...
    async def fetch_paper(self, source: str, identifier: str) -> Paper: ...
    async def lean_check(self, code: str) -> LeanCheckResult: ...
    async def lean_verify(self, code: str, theorem_name: str) -> LeanVerification: ...


SEARCH_TOOLS = {
    "arxiv": ("literature.arxiv_search", "max_results"),
    "semantic_scholar": ("literature.semantic_scholar_search", "limit"),
    "openalex": ("literature.openalex_search", "limit"),
}
FETCH_TOOLS = {
    "arxiv": ("literature.arxiv_fetch", "arxiv_id"),
    "openalex": ("literature.openalex_lookup", "identifier"),
}


class MCPTools:
    def __init__(self, toolbox: MCPToolbox) -> None:
        self.toolbox = toolbox

    async def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        result = await self.toolbox.call(tool, args)
        if result.is_error or result.structured is None:
            raise ToolCallError(f"{tool}: {result.text or 'no result'}")
        return result.structured

    async def run_python(self, code: str, timeout_s: float = 30.0) -> SandboxResult:
        data = await self._call("sandbox.run_python", {"code": code, "timeout_s": timeout_s})
        return SandboxResult.model_validate(data)

    async def sympy(self, op: str, **kwargs: Any) -> dict[str, Any]:
        return await self._call(f"sympy.{op}", kwargs)

    async def search_papers(self, source: str, query: str, limit: int = 5) -> PaperList:
        tool, limit_arg = SEARCH_TOOLS[source]
        return PaperList.model_validate(await self._call(tool, {"query": query, limit_arg: limit}))

    async def fetch_paper(self, source: str, identifier: str) -> Paper:
        if source not in FETCH_TOOLS:
            raise ToolCallError(f"cannot fetch single papers from {source!r}")
        tool, arg = FETCH_TOOLS[source]
        return Paper.model_validate(await self._call(tool, {arg: identifier}))

    async def lean_check(self, code: str) -> LeanCheckResult:
        return LeanCheckResult.model_validate(await self._call("lean.check", {"code": code}))

    async def lean_verify(self, code: str, theorem_name: str) -> LeanVerification:
        data = await self._call("lean.verify_proof", {"code": code, "theorem_name": theorem_name})
        return LeanVerification.model_validate(data)


@asynccontextmanager
async def open_tools(settings: Settings, *, lean_enabled: bool = True) -> AsyncIterator[MCPTools]:
    """Mount all tool servers (in-process MCP) for one run."""
    servers: dict[str, Any] = {
        "sandbox": sandbox.build_server(DockerSandbox(settings.sandbox_image)),
        "sympy": sympy.build_server(),
        "literature": literature.build_server(settings=settings),
    }
    repl: LeanREPL | None = None
    if lean_enabled:
        repl = LeanREPL(settings.lean_image)
        servers["lean"] = lean.build_server(repl, timeout_s=120.0)
    try:
        # Mathlib loads on the first Lean call (~1 min), so allow long tool calls.
        async with MCPToolbox(servers, timeout_s=600.0) as toolbox:
            yield MCPTools(toolbox)
    finally:
        if repl is not None:
            await repl.close()
