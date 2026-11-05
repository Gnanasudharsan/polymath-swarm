"""Client adapter: lets any agent discover and call tools on one or more MCP servers.

Tools are namespaced ``<server>.<tool>`` so several servers can be mounted at once. A server
spec is either an in-process ``MCPServer`` (tests, embedded use) or ``StdioServerParameters``
(the server runs as a subprocess, e.g. ``python -m polymath.mcp_servers.sympy``).
"""

from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Self

from mcp import Client, StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent
from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.base import ToolSpec
from polymath.core.logging import get_logger
from polymath.core.tracing import get_tracer

log = get_logger(__name__)

ServerSpec = MCPServer[Any] | StdioServerParameters

SERVER_MODULES: dict[str, str] = {
    "sympy": "polymath.mcp_servers.sympy",
    "sandbox": "polymath.mcp_servers.sandbox",
    "literature": "polymath.mcp_servers.literature",
    "lean": "polymath.mcp_servers.lean",
}


def stdio_server(name: str) -> StdioServerParameters:
    """Spawn one of our servers as a subprocess with the current interpreter."""
    return StdioServerParameters(command=sys.executable, args=["-m", SERVER_MODULES[name]])


class ToolCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    is_error: bool
    structured: dict[str, Any] | None = None
    text: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class UnknownToolError(KeyError):
    pass


class MCPToolbox:
    """Async context manager holding live connections to a set of MCP servers."""

    def __init__(self, servers: dict[str, ServerSpec], *, timeout_s: float = 120.0) -> None:
        if any("." in name for name in servers):
            raise ValueError("server names must not contain '.'")
        self._servers = servers
        self._timeout_s = timeout_s
        self._clients: dict[str, Client] = {}
        self._tools: dict[str, ToolSpec] = {}
        self._stack: AsyncExitStack | None = None

    async def __aenter__(self) -> Self:
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            for name, spec in self._servers.items():
                client = await stack.enter_async_context(
                    Client(spec, read_timeout_seconds=self._timeout_s)
                )
                self._clients[name] = client
                listing = await client.list_tools()
                for tool in listing.tools:
                    qualified = f"{name}.{tool.name}"
                    self._tools[qualified] = ToolSpec(
                        name=qualified,
                        description=tool.description or "",
                        input_schema=dict(tool.input_schema),
                    )
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        log.info("mcp.connected", servers=list(self._servers), tools=len(self._tools))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc, tb)
        self._stack = None
        self._clients.clear()
        self._tools.clear()

    @property
    def tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def litellm_tools(self) -> list[dict[str, Any]]:
        """Tool definitions in the OpenAI/LiteLLM function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    # function names may not contain '.', so use '__' on the wire
                    "name": t.name.replace(".", "__"),
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in self._tools.values()
        ]

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        qualified = tool.replace("__", ".", 1) if "." not in tool else tool
        if qualified not in self._tools:
            raise UnknownToolError(qualified)
        server, name = qualified.split(".", 1)
        args = arguments or {}
        with get_tracer().start_as_current_span("mcp.call_tool") as span:
            span.set_attribute("mcp.server", server)
            span.set_attribute("mcp.tool", name)
            result = await self._clients[server].call_tool(name, args)
            span.set_attribute("mcp.is_error", bool(result.is_error))
        text = "\n".join(b.text for b in result.content if isinstance(b, TextContent))
        structured = result.structured_content
        if structured is None and text and not result.is_error:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            structured = parsed if isinstance(parsed, dict) else None
        return ToolCallResult(
            tool=qualified,
            is_error=bool(result.is_error),
            structured=structured,
            text=text,
            arguments=args,
        )
