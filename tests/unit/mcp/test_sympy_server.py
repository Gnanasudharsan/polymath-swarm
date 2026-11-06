"""The sympy server through the MCP client adapter, connected in-process."""

from __future__ import annotations

import pytest

from polymath.mcp_servers.client import MCPToolbox, UnknownToolError
from polymath.mcp_servers.sympy import build_server


async def test_toolbox_lists_namespaced_tools() -> None:
    async with MCPToolbox({"sympy": build_server()}) as tb:
        names = {t.name for t in tb.tools}
        assert {
            "sympy.simplify",
            "sympy.solve",
            "sympy.integrate",
            "sympy.series",
            "sympy.verify_identity",
        } <= names
        fn = {t["function"]["name"] for t in tb.litellm_tools()}
        assert "sympy__verify_identity" in fn


async def test_call_returns_structured_result() -> None:
    async with MCPToolbox({"sympy": build_server()}) as tb:
        res = await tb.call("sympy.verify_identity", {"lhs": "x^2 - 1", "rhs": "(x-1)(x+1)"})
        assert not res.is_error
        assert res.structured is not None and res.structured["status"] == "proved"
        # LiteLLM-style wire name works too
        res2 = await tb.call("sympy__simplify", {"expression": "2x + 3x"})
        assert res2.structured is not None and res2.structured["result"] == "5*x"


async def test_bad_input_is_tool_error_not_crash() -> None:
    async with MCPToolbox({"sympy": build_server()}) as tb:
        res = await tb.call("sympy.simplify", {"expression": "__import__('os')"})
        assert res.is_error and "invalid input" in res.text


async def test_runaway_computation_times_out() -> None:
    async with MCPToolbox({"sympy": build_server(timeout_s=1.0)}) as tb:
        res = await tb.call("sympy.simplify", {"expression": "factorial(factorial(20))"})
        assert res.is_error and "exceeded" in res.text


async def test_unknown_tool() -> None:
    async with MCPToolbox({"sympy": build_server()}) as tb:
        with pytest.raises(UnknownToolError):
            await tb.call("sympy.nope")


def test_server_names_cannot_contain_dots() -> None:
    with pytest.raises(ValueError, match="must not contain"):
        MCPToolbox({"a.b": build_server()})


async def test_unmounted_tool_is_a_tool_call_error() -> None:
    from polymath.agents.tools import MCPTools, ToolCallError

    async with MCPToolbox({"sympy": build_server()}) as tb:
        with pytest.raises(ToolCallError, match="not mounted"):
            await MCPTools(tb).paper_text("arxiv:1")
