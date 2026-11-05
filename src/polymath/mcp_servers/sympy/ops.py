"""Pure SymPy operations behind the ``sympy`` MCP server.

``parse_expr`` evaluates Python under the hood, so every input is screened by
:func:`parse` first, and the server runs each operation in a throwaway child process with a
timeout (see ``runner.py``). Untrusted *programs* belong in the sandbox server, not here.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

MAX_INPUT_CHARS = 2000
_FORBIDDEN = re.compile(
    r"__|\b(?:import|lambda|exec|eval|compile|open|getattr|setattr|globals|locals|vars|"
    r"input|breakpoint|os|sys|subprocess)\b|[\"'`;\\\[\]{}@$!]|\.\s*[A-Za-z_]"
)
_TRANSFORMS = (*standard_transformations, implicit_multiplication_application, convert_xor)


class SympyInputError(ValueError):
    """Input rejected by the safety screen or unparsable as an expression."""


def parse(text: str) -> sp.Expr:
    text = text.strip()
    if not text:
        raise SympyInputError("empty expression")
    if len(text) > MAX_INPUT_CHARS:
        raise SympyInputError(f"expression longer than {MAX_INPUT_CHARS} characters")
    if _FORBIDDEN.search(text):
        raise SympyInputError(f"expression contains forbidden syntax: {text!r}")
    try:
        expr = parse_expr(text, transformations=_TRANSFORMS, evaluate=True)
    except Exception as exc:  # SyntaxError, TokenError, TypeError, ...
        raise SympyInputError(f"could not parse {text!r}: {exc}") from exc
    if not isinstance(expr, sp.Basic):
        raise SympyInputError(f"{text!r} is not a symbolic expression")
    return expr


def _symbol(name: str) -> sp.Symbol:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", name):
        raise SympyInputError(f"invalid symbol name {name!r}")
    return sp.Symbol(name)


def _equation(text: str) -> sp.Basic:
    """``"lhs = rhs"`` (or ``==``) becomes ``Eq(lhs, rhs)``; a bare expression means ``= 0``."""
    parts = re.split(r"==|=", text)
    if len(parts) == 1:
        return sp.Eq(parse(parts[0]), 0)
    if len(parts) == 2:
        return sp.Eq(parse(parts[0]), parse(parts[1]))
    raise SympyInputError(f"equation has more than one '=': {text!r}")


def _render(expr: Any) -> dict[str, str]:
    return {"result": sp.sstr(expr), "latex": sp.latex(expr)}


def simplify(expression: str) -> dict[str, Any]:
    expr = parse(expression)
    return {"input": sp.sstr(expr), **_render(sp.simplify(expr))}


def solve(equations: list[str], symbols: list[str] | None = None) -> dict[str, Any]:
    if not equations:
        raise SympyInputError("no equations given")
    eqs = [_equation(e) for e in equations]
    syms = (
        [_symbol(s) for s in symbols]
        if symbols
        else sorted(set().union(*(e.free_symbols for e in eqs)), key=str)
    )
    raw = sp.solve(eqs, syms, dict=True)
    solutions = [{sp.sstr(k): sp.sstr(v) for k, v in sol.items()} for sol in raw]
    return {"symbols": [str(s) for s in syms], "solutions": solutions, "count": len(solutions)}


def integrate(
    expression: str, variable: str, lower: str | None = None, upper: str | None = None
) -> dict[str, Any]:
    expr, var = parse(expression), _symbol(variable)
    if (lower is None) != (upper is None):
        raise SympyInputError("give both bounds for a definite integral, or neither")
    if lower is not None and upper is not None:
        result = sp.integrate(expr, (var, parse(lower), parse(upper)))
    else:
        result = sp.integrate(expr, var)
    return {
        **_render(result),
        "definite": lower is not None,
        "evaluated": not result.has(sp.Integral),
    }


def series(expression: str, variable: str, point: str = "0", order: int = 6) -> dict[str, Any]:
    if not 1 <= order <= 30:
        raise SympyInputError("order must be between 1 and 30")
    expr, var = parse(expression), _symbol(variable)
    result = sp.series(expr, var, parse(point), order)
    return {**_render(result), "without_order_term": sp.sstr(result.removeO())}


def verify_identity(lhs: str, rhs: str, samples: int = 24, seed: int = 0) -> dict[str, Any]:
    """Decide ``lhs == rhs``: symbolic proof first, then a randomised numeric search.

    Status is ``proved`` (difference simplifies to 0), ``refuted`` (a numeric counterexample),
    ``numerically_equal`` (all samples agree — strong evidence, not proof) or ``unknown``.
    """
    left, right = parse(lhs), parse(rhs)
    diff = sp.simplify(left - right)
    if diff == 0:
        return {"status": "proved", "method": "symbolic", "difference": "0"}

    rng = random.Random(seed)  # noqa: S311 - sampling, not crypto
    free = sorted(diff.free_symbols, key=str)
    checked = 0
    for _ in range(samples * 4):
        point = {s: sp.Rational(rng.randint(-300, 300), 100) for s in free}
        try:
            lv = complex(left.evalf(30, subs=point))
            rv = complex(right.evalf(30, subs=point))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if any(map(_not_finite, (lv, rv))):
            continue
        checked += 1
        if abs(lv - rv) > 1e-9 * max(1.0, abs(lv), abs(rv)):
            return {
                "status": "refuted",
                "method": "numeric",
                "difference": sp.sstr(diff),
                "counterexample": {str(k): str(v) for k, v in point.items()},
                "lhs_value": str(lv),
                "rhs_value": str(rv),
            }
        if checked >= samples:
            break
    status = "numerically_equal" if checked >= samples else "unknown"
    return {"status": status, "method": "numeric", "difference": sp.sstr(diff), "samples": checked}


def _not_finite(z: complex) -> bool:
    return any(v != v or v in (float("inf"), float("-inf")) for v in (z.real, z.imag))


OPERATIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "simplify": simplify,
    "solve": solve,
    "integrate": integrate,
    "series": series,
    "verify_identity": verify_identity,
}
