"""``sympy`` MCP server: exact symbolic computation for the Compute and Critic agents."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from polymath.mcp_servers.sympy import runner
from polymath.mcp_servers.sympy.ops import SympyInputError

INSTRUCTIONS = (
    "Exact symbolic mathematics with SymPy. Expressions use SymPy syntax: ** or ^ for powers, "
    "sqrt, exp, log, sin, pi, E, I, oo. Equations may be written 'lhs = rhs'."
)


def build_server(timeout_s: float = 10.0) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer("sympy", instructions=INSTRUCTIONS)

    async def call(op: str, **kwargs: Any) -> dict[str, Any]:
        try:
            return await runner.run(op, kwargs, timeout_s)
        except SympyInputError as exc:
            raise ToolError(f"invalid input: {exc}") from exc
        except runner.SympyTimeoutError as exc:
            raise ToolError(str(exc)) from exc
        except RuntimeError as exc:
            raise ToolError(f"sympy failed: {exc}") from exc

    @server.tool()
    async def simplify(expression: str) -> dict[str, Any]:
        """Simplify an expression. Returns the simplified form and its LaTeX."""
        return await call("simplify", expression=expression)

    @server.tool()
    async def solve(equations: list[str], symbols: list[str] | None = None) -> dict[str, Any]:
        """Solve equations ('x^2 = 4', or an expression meaning '= 0') for the given symbols."""
        return await call("solve", equations=equations, symbols=symbols)

    @server.tool()
    async def integrate(
        expression: str, variable: str, lower: str | None = None, upper: str | None = None
    ) -> dict[str, Any]:
        """Indefinite integral, or definite when both bounds are given (use 'oo' for infinity)."""
        return await call(
            "integrate", expression=expression, variable=variable, lower=lower, upper=upper
        )

    @server.tool()
    async def series(
        expression: str, variable: str, point: str = "0", order: int = 6
    ) -> dict[str, Any]:
        """Taylor/Laurent series of an expression around a point, up to O(var^order)."""
        return await call(
            "series", expression=expression, variable=variable, point=point, order=order
        )

    @server.tool()
    async def verify_identity(lhs: str, rhs: str, samples: int = 24) -> dict[str, Any]:
        """Check lhs == rhs. status: proved | refuted (with counterexample) |
        numerically_equal (random samples agree; evidence, not proof) | unknown."""
        return await call("verify_identity", lhs=lhs, rhs=rhs, samples=samples)

    return server


def main() -> None:
    build_server().run("stdio")
