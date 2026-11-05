"""Lean automation pass: before asking the model again, try Mathlib's own automation
(`exact?` library search, `omega`, `decide`, ...) on the model's statement."""

from __future__ import annotations

import re

from polymath.agents.tools import ToolCallError, Tools
from polymath.mcp_servers.lean.checker import LeanVerification

AUTO_TACTICS: tuple[str, ...] = (
    "intros; exact?",
    "exact?",
    "intros; omega",
    "decide",
    "norm_num",
    "simp",
    "intros; positivity",
    "intros; nlinarith",
)
_TRY_THIS = re.compile(r"Try this:\s*(?:\[apply\]\s*)?(?P<tac>.+)", re.DOTALL)


def split_theorem(lean_code: str, name: str) -> tuple[str, str] | None:
    """(everything before ``theorem name``, the header up to ``:=``) or ``None``."""
    m = re.search(rf"^\s*theorem\s+{re.escape(name)}\b(.*?):=", lean_code, re.DOTALL | re.MULTILINE)
    if not m:
        return None
    return lean_code[: m.start()].rstrip() + "\n\n", f"theorem {name}{m.group(1)}".rstrip()


def suggestion(v: LeanVerification) -> str | None:
    for d in v.check.diagnostics:
        m = _TRY_THIS.search(d.message)
        if d.severity == "info" and m:
            return " ".join(m["tac"].split())
    return None


async def automate(tools: Tools, lean_code: str, name: str) -> str | None:
    """Return a verified Lean file proving the same statement by automation, or ``None``.

    `exact?` hits are replaced by the concrete term it found and re-verified, so the stored proof
    does not depend on library search.
    """
    parts = split_theorem(lean_code, name)
    if parts is None:
        return None
    prefix, header = parts
    for tactic in AUTO_TACTICS:
        code = f"{prefix}{header} := by\n  {tactic}"
        try:
            v = await tools.lean_verify(code, name)
        except ToolCallError:
            continue
        if not v.verified:
            continue
        if "exact?" not in tactic:
            return code
        found = suggestion(v)
        if found:
            concrete = f"{prefix}{header} := by\n  {tactic.replace('exact?', found)}"
            try:
                if (await tools.lean_verify(concrete, name)).verified:
                    return concrete
            except ToolCallError:
                pass
        return code
    return None
