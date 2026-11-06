"""Deterministic scorers (no LLM judges): numeric answers, keywords, exact Lean statements."""

from __future__ import annotations

import re
from fractions import Fraction

from polymath.evals.datasets import EvalProblem, last_boxed
from polymath.verification.evidence import normalise_text

_FRAC = re.compile(r"^(-?)\\frac\{(-?\d+)\}\{(\d+)\}$")


def normalise_answer(ans: str) -> str:
    a = ans.strip().strip("$").rstrip(".")
    for tex in ("\\left", "\\right", "\\!", "\\,", "\\ ", " "):
        a = a.replace(tex, "")
    return a.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")


def as_number(ans: str) -> Fraction | None:
    a = normalise_answer(ans)
    m = _FRAC.match(a)
    try:
        if m:
            value = Fraction(int(m.group(2)), int(m.group(3)))
            return -value if m.group(1) else value
        return Fraction(a.replace(",", ""))
    except (ValueError, ZeroDivisionError):
        return None


def extract_final_answer(text: str) -> str | None:
    boxed = last_boxed(text)
    if boxed is not None:
        return boxed
    numbers = re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", text)
    return numbers[-1] if numbers else None


def math_correct(answer_text: str, gold: str) -> bool:
    got = extract_final_answer(answer_text)
    if got is None:
        return False
    a, b = as_number(got), as_number(gold)
    if a is not None and b is not None:
        return a == b
    return normalise_answer(got) == normalise_answer(gold)


def keywords_correct(answer_text: str, gold: str) -> bool:
    text = f" {normalise_text(answer_text)} "
    return all(f" {normalise_text(k)} " in text for k in gold.split(";") if k.strip())


def _squash(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip()


def lean_statement_preserved(lean_code: str, statement: str) -> bool:
    """The proof file must contain the benchmark statement verbatim (modulo whitespace)."""
    return _squash(statement) in _squash(lean_code)


def score(problem: EvalProblem, answer_text: str, verified_lean: list[str]) -> bool:
    if problem.suite == "math":
        return math_correct(answer_text, problem.gold)
    if problem.suite == "research_qa":
        return keywords_correct(answer_text, problem.gold)
    return any(lean_statement_preserved(code, problem.gold) for code in verified_lean)
