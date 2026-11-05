"""Real Lean 4 + Mathlib checks. Needs the image (see docker/lean.Dockerfile) and ~4 GB RAM.

The REPL is started once per module (~1 min to load Mathlib); each check is then fast.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from polymath.mcp_servers.client import MCPToolbox
from polymath.mcp_servers.lean import build_server, checker
from polymath.mcp_servers.lean.repl import LeanREPL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.lean,
    pytest.mark.asyncio(loop_scope="module"),
]

KNOWN_GOOD = """import Mathlib

/-- The sum of two even numbers is even. -/
theorem even_add_even (a b : ℤ) (ha : Even a) (hb : Even b) : Even (a + b) := by
  obtain ⟨x, rfl⟩ := ha
  obtain ⟨y, rfl⟩ := hb
  exact ⟨x + y, by ring⟩
"""

KNOWN_BAD = """import Mathlib

theorem bogus (n : ℕ) : n + 1 = n := by
  simp
"""

WITH_SORRY = """import Mathlib

theorem sq_pos' (x : ℝ) (h : 0 < x) : 0 < x ^ 2 := by
  sorry
"""

AXIOM_CHEAT = """import Mathlib

axiom cheat : False

theorem fermat_last (n : ℕ) (hn : 2 < n) (a b c : ℕ) (ha : 0 < a) (hb : 0 < b) (hc : 0 < c) :
    a ^ n + b ^ n ≠ c ^ n :=
  cheat.elim
"""


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanREPL]:
    r = LeanREPL()
    await r.start()
    yield r
    await r.close()


async def test_verifies_known_good_proof(repl: LeanREPL) -> None:
    v = await checker.verify(repl, KNOWN_GOOD, "even_add_even")
    assert v.verified, v.reason
    assert v.check.complete and v.check.sorry_count == 0


async def test_rejects_known_bad_proof(repl: LeanREPL) -> None:
    v = await checker.verify(repl, KNOWN_BAD, "bogus")
    assert not v.verified
    assert v.check.unsolved_goals  # simp leaves `False`


async def test_rejects_sorry_and_reports_goal(repl: LeanREPL) -> None:
    v = await checker.verify(repl, WITH_SORRY, "sq_pos'")
    assert not v.verified and "sorry" in v.reason
    assert v.check.sorries[0].goal.endswith("⊢ 0 < x ^ 2")
    assert v.check.sorries[0].line == 4


async def test_rejects_custom_axiom(repl: LeanREPL) -> None:
    v = await checker.verify(repl, AXIOM_CHEAT, "fermat_last")
    assert not v.verified and "non-standard" in v.reason
    assert "cheat" in v.axioms


async def test_via_mcp_toolbox(repl: LeanREPL) -> None:
    async with MCPToolbox({"lean": build_server(repl)}) as tb:
        res = await tb.call(
            "lean.verify_proof", {"code": KNOWN_GOOD, "theorem_name": "even_add_even"}
        )
        assert res.structured is not None and res.structured["verified"] is True
        bad = await tb.call("lean.verify_proof", {"code": KNOWN_BAD, "theorem_name": "bogus"})
        assert bad.structured is not None and bad.structured["verified"] is False
