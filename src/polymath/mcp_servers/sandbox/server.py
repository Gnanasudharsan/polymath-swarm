"""``sandbox`` MCP server: run Python (numpy, scipy, sympy available) in isolation."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from polymath.mcp_servers.sandbox.docker import DockerSandbox, SandboxError, SandboxResult

INSTRUCTIONS = (
    "Runs a self-contained Python 3.12 program in an isolated container with numpy, scipy, "
    "sympy and mpmath. There is no network access and only /tmp is writable. Print results "
    "to stdout; files written to /tmp/artifacts are returned base64-encoded."
)


def build_server(sandbox: DockerSandbox | None = None) -> MCPServer[Any]:
    box = sandbox or DockerSandbox()
    server: MCPServer[Any] = MCPServer("sandbox", instructions=INSTRUCTIONS)

    @server.tool()
    async def run_python(code: str, timeout_s: float = 10.0) -> SandboxResult:
        """Execute a Python program and return stdout, stderr, exit code and artifacts.
        timeout_s is capped by the server (default cap 60s)."""
        try:
            return await box.run(code, timeout_s)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc

    return server


def main() -> None:
    build_server().run("stdio")
