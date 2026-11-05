"""Turn Lean source + REPL replies into typed check / verification results.

The REPL session already has ``import Mathlib``; user code may only import Mathlib, Lean or
Std modules (all covered by that import), so import lines are stripped and line numbers
mapped back to the user's file.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_IMPORT_ROOTS = ("Mathlib", "Lean", "Std", "Batteries", "Aesop", "Qq", "Init")
MAX_CODE_CHARS = 200_000
_IMPORT = re.compile(r"^\s*import\s+(.+)$")
_THEOREM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_'.]*$")
_AXIOMS = re.compile(r"depends on axioms: \[(?P<axioms>[^\]]*)\]")
_NO_AXIOMS = "does not depend on any axioms"
_SORRY_TOKEN = re.compile(r"\b(sorry|admit)\b")
STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})

Severity = Literal["error", "warning", "info"]


class LeanInputError(ValueError):
    pass


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None
    message: str


class SorryGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: int
    column: int
    goal: str


class LeanCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="No errors (sorries allowed).")
    complete: bool = Field(description="No errors and no sorry/admit: a full proof.")
    diagnostics: list[Diagnostic]
    sorries: list[SorryGoal] = Field(default_factory=list)
    sorry_count: int
    unsolved_goals: list[str] = Field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


class LeanVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theorem: str
    verified: bool
    reason: str
    axioms: list[str] = Field(default_factory=list)
    check: LeanCheckResult


class REPLRunner(Protocol):
    async def run(self, body: str, timeout_s: float = ...) -> dict[str, Any]: ...


def prepare(code: str) -> tuple[str, int]:
    """Strip the import header; return (body, number of lines removed)."""
    if len(code) > MAX_CODE_CHARS:
        raise LeanInputError(f"Lean source longer than {MAX_CODE_CHARS} characters")
    lines = code.splitlines()
    header = 0
    for line in lines:
        match = _IMPORT.match(line)
        if match:
            for module in match.group(1).split():
                if module.split(".")[0] not in ALLOWED_IMPORT_ROOTS:
                    raise LeanInputError(f"import of {module!r} is not allowed")
            header += 1
        elif not line.strip() or line.strip().startswith("--"):
            header += 1
        else:
            break
    body_lines = lines[header:]
    if any(_IMPORT.match(line) for line in body_lines):
        raise LeanInputError("imports must come before any other command")
    return "\n".join(body_lines), header


def strip_comments(code: str) -> str:
    """Remove ``--`` line comments and (nested) ``/- -/`` block comments; keep newlines."""
    out: list[str] = []
    i, depth, n = 0, 0, len(code)
    in_string = False
    while i < n:
        two = code[i : i + 2]
        ch = code[i]
        if depth == 0 and in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            in_string = ch != '"'
        elif two == "/-":
            depth += 1
            i += 2
            continue
        elif depth and two == "-/":
            depth -= 1
            i += 2
            continue
        elif depth:
            out.append("\n" if ch == "\n" else " ")
        elif two == "--":
            while i < n and code[i] != "\n":
                i += 1
            continue
        else:
            in_string = ch == '"'
            out.append(ch)
        i += 1
    return "".join(out)


def count_sorry_tokens(code: str) -> int:
    """Occurrences of ``sorry``/``admit`` outside comments and string literals."""
    no_comments = strip_comments(code)
    no_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', no_comments)
    return len(_SORRY_TOKEN.findall(no_strings))


def parse_reply(reply: dict[str, Any], line_offset: int, source: str) -> LeanCheckResult:
    diagnostics: list[Diagnostic] = []
    for msg in reply.get("messages", []):
        pos, end = msg.get("pos") or {}, msg.get("endPos") or {}
        severity = msg.get("severity", "info")
        diagnostics.append(
            Diagnostic(
                severity=severity if severity in ("error", "warning") else "info",
                line=int(pos.get("line", 0)) + line_offset,
                column=int(pos.get("column", 0)),
                end_line=int(end["line"]) + line_offset if "line" in end else None,
                end_column=int(end["column"]) if "column" in end else None,
                message=str(msg.get("data", "")),
            )
        )
    sorries = [
        SorryGoal(
            line=int(s["pos"]["line"]) + line_offset,
            column=int(s["pos"]["column"]),
            goal=str(s.get("goal", "")),
        )
        for s in reply.get("sorries", [])
    ]
    unsolved = [
        d.message.removeprefix("unsolved goals\n")
        for d in diagnostics
        if d.severity == "error" and d.message.startswith("unsolved goals")
    ]
    has_error = any(d.severity == "error" for d in diagnostics)
    sorry_warnings = sum("declaration uses `sorry`" in d.message for d in diagnostics)
    sorry_count = max(len(sorries), sorry_warnings, count_sorry_tokens(source))
    return LeanCheckResult(
        ok=not has_error,
        complete=not has_error and sorry_count == 0,
        diagnostics=diagnostics,
        sorries=sorries,
        sorry_count=sorry_count,
        unsolved_goals=unsolved,
    )


async def check(repl: REPLRunner, code: str, timeout_s: float = 60.0) -> LeanCheckResult:
    body, offset = prepare(code)
    reply = await repl.run(body, timeout_s)
    return parse_reply(reply, offset, body)


async def verify(
    repl: REPLRunner, code: str, theorem: str, timeout_s: float = 60.0
) -> LeanVerification:
    """A theorem is verified iff the file has no errors, no sorry/admit, and the kernel
    reports that ``theorem`` exists and does not depend on ``sorryAx``."""
    if not _THEOREM_NAME.match(theorem):
        raise LeanInputError(f"invalid theorem name {theorem!r}")
    body, offset = prepare(code)
    probe = f"{body}\n\n#print axioms {theorem}\n"
    reply = await repl.run(probe, timeout_s)
    result = parse_reply(reply, offset, body)
    axioms_msg = next(
        (
            d
            for d in result.diagnostics
            if d.severity == "info" and (_AXIOMS.search(d.message) or _NO_AXIOMS in d.message)
        ),
        None,
    )
    axioms: list[str] = []
    if axioms_msg and (match := _AXIOMS.search(axioms_msg.message)):
        axioms = [a.strip() for a in match["axioms"].split(",") if a.strip()]

    def outcome(verified: bool, reason: str) -> LeanVerification:
        return LeanVerification(
            theorem=theorem, verified=verified, reason=reason, axioms=axioms, check=result
        )

    if not result.ok:
        return outcome(False, f"Lean reported {len(result.errors)} error(s)")
    if axioms_msg is None:
        return outcome(False, f"theorem {theorem!r} was not found")
    if "sorryAx" in axioms or result.sorry_count:
        return outcome(False, "proof uses sorry/admit")
    extra = sorted(set(axioms) - STANDARD_AXIOMS)
    if extra:
        return outcome(False, f"proof depends on non-standard axioms {extra}")
    return outcome(True, "compiles with no errors, no sorry, and only standard axioms")
