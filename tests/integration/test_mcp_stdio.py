"""Spawn the sympy server as a real stdio subprocess, as agents will in production."""

from __future__ import annotations

import pytest

from polymath.mcp_servers.client import MCPToolbox, stdio_server

pytestmark = pytest.mark.integration


async def test_sympy_over_stdio() -> None:
    async with MCPToolbox({"sympy": stdio_server("sympy")}) as tb:
        res = await tb.call("sympy.solve", {"equations": ["x^2 - 5x + 6"]})
        assert res.structured is not None
        assert sorted(s["x"] for s in res.structured["solutions"]) == ["2", "3"]
