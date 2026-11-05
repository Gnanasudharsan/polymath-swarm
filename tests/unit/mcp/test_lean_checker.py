"""Lean checker logic with a fake REPL replaying real REPL replies (no Docker)."""

from __future__ import annotations

from typing import Any

import pytest

from polymath.mcp_servers.client import MCPToolbox
from polymath.mcp_servers.lean import build_server, checker
from polymath.mcp_servers.lean.checker import LeanInputError


class FakeREPL:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.bodies: list[str] = []

    async def run(self, body: str, timeout_s: float = 60.0) -> dict[str, Any]:
        self.bodies.append(body)
        return self.reply


def _msg(sev: str, line: int, data: str) -> dict[str, Any]:
    return {
        "severity": sev,
        "pos": {"line": line, "column": 0},
        "endPos": {"line": line, "column": 5},
        "data": data,
    }


GOOD = _msg("info", 3, "'t' depends on axioms: [propext, Quot.sound]")
SORRY = {
    "sorries": [
        {
            "pos": {"line": 2, "column": 2},
            "endPos": {"line": 2, "column": 7},
            "goal": "x : ℝ\nh : 0 < x\n⊢ 0 < x ^ 2",
            "proofState": 0,
        }
    ],
    "messages": [
        _msg("warning", 1, "declaration uses `sorry`"),
        _msg("info", 4, "'s' depends on axioms: [propext, sorryAx, Quot.sound]"),
    ],
    "env": 2,
}
BAD = {"messages": [_msg("error", 1, "unsolved goals\nn : ℕ\n⊢ False")], "env": 3}


def test_prepare_strips_imports_and_maps_lines() -> None:
    body, offset = checker.prepare(
        "import Mathlib\nimport Mathlib.Tactic\n\n-- c\ntheorem x : True := trivial"
    )
    assert body == "theorem x : True := trivial" and offset == 4


@pytest.mark.parametrize(
    "code",
    ["import Evil\ntheorem x : True := trivial", "theorem x : True := trivial\nimport Mathlib"],
)
def test_prepare_rejects_bad_imports(code: str) -> None:
    with pytest.raises(LeanInputError):
        checker.prepare(code)


def test_count_sorry_ignores_comments_and_strings() -> None:
    code = (
        "-- sorry in a line comment\n"
        "/- block sorry /- nested sorry -/ still comment -/\n"
        'def s := "sorry"\n'
        "theorem a : True := by sorry\n"
        "theorem b : True := by admit\n"
        "theorem sorryless : True := trivial\n"
    )
    assert checker.count_sorry_tokens(code) == 2


async def test_check_maps_diagnostics_and_goals() -> None:
    res = await checker.check(
        FakeREPL(SORRY), "import Mathlib\ntheorem s (x : ℝ) (h : 0 < x) : 0 < x ^ 2 := by\n  sorry"
    )
    assert res.ok and not res.complete
    assert res.sorry_count == 1
    assert res.sorries[0].goal.endswith("⊢ 0 < x ^ 2")
    assert res.sorries[0].line == 3  # shifted by the stripped import line


async def test_unsolved_goals_extracted() -> None:
    res = await checker.check(FakeREPL(BAD), "theorem bad (n : ℕ) : n + 1 = n := by simp")
    assert not res.ok and res.unsolved_goals == ["n : ℕ\n⊢ False"]


async def test_verify_accepts_complete_proof() -> None:
    repl = FakeREPL({"messages": [GOOD], "env": 1})
    v = await checker.verify(repl, "theorem t (a b : ℕ) : a + b = b + a := by omega", "t")
    assert v.verified and v.axioms == ["propext", "Quot.sound"]
    assert repl.bodies[0].rstrip().endswith("#print axioms t")


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (SORRY, "sorry"),
        (BAD, "error"),
        ({"messages": [], "env": 1}, "not found"),
        (
            {"messages": [_msg("info", 2, "'t' depends on axioms: [cheat]")], "env": 1},
            "non-standard",
        ),
    ],
)
async def test_verify_rejects(reply: dict[str, Any], reason: str) -> None:
    v = await checker.verify(FakeREPL(reply), "theorem t : True := trivial", "t")
    assert not v.verified and reason in v.reason


async def test_verify_rejects_bad_theorem_name() -> None:
    with pytest.raises(LeanInputError):
        await checker.verify(FakeREPL({}), "x", "t\n#eval 1")


async def test_server_tools_with_fake_repl() -> None:
    async with MCPToolbox({"lean": build_server(FakeREPL(SORRY))}) as tb:
        assert {t.name for t in tb.tools} == {
            "lean.check",
            "lean.get_goals",
            "lean.count_sorry",
            "lean.verify_proof",
        }
        goals = await tb.call("lean.get_goals", {"code": "theorem s : True := by\n  sorry"})
        assert goals.structured is not None and goals.structured["sorries"]
        count = await tb.call("lean.count_sorry", {"code": "theorem s : True := by\n  sorry"})
        assert count.structured is not None and count.structured["sorry_count"] == 1
        bad = await tb.call("lean.check", {"code": "import Evil"})
        assert bad.is_error and "not allowed" in bad.text
