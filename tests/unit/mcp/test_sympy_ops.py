from __future__ import annotations

import pytest

from polymath.mcp_servers.sympy import ops
from polymath.mcp_servers.sympy.ops import SympyInputError


@pytest.mark.parametrize(
    "bad",
    [
        "__import__('os').system('id')",
        "x.func",
        "open('/etc/passwd')",
        "lambda: 1",
        "x; y",
        "a[0]",
        "",
        "x" * (ops.MAX_INPUT_CHARS + 1),
    ],
)
def test_parse_rejects_dangerous_or_invalid_input(bad: str) -> None:
    with pytest.raises(SympyInputError):
        ops.parse(bad)


def test_parse_accepts_math_syntax() -> None:
    assert str(ops.parse("2x^2 + sin(pi/2) + 1.5")) == "2*x**2 + 2.5"


def test_simplify() -> None:
    assert ops.simplify("sin(x)^2 + cos(x)^2")["result"] == "1"


def test_solve_equation_and_system() -> None:
    quad = ops.solve(["x^2 = 4"])
    assert sorted(s["x"] for s in quad["solutions"]) == ["-2", "2"]
    system = ops.solve(["x + y = 3", "x - y = 1"], ["x", "y"])
    assert system["solutions"] == [{"x": "2", "y": "1"}]


def test_integrate_definite_and_indefinite() -> None:
    assert ops.integrate("exp(-x^2)", "x", "-oo", "oo")["result"] == "sqrt(pi)"
    indefinite = ops.integrate("2*x", "x")
    assert indefinite["result"] == "x**2" and not indefinite["definite"]
    with pytest.raises(SympyInputError):
        ops.integrate("x", "x", lower="0")


def test_series() -> None:
    res = ops.series("exp(x)", "x", order=4)
    assert res["without_order_term"] == "x**3/6 + x**2/2 + x + 1"


def test_verify_identity_proved_refuted_numeric() -> None:
    assert ops.verify_identity("(a+b)^2", "a^2 + 2a b + b^2")["status"] == "proved"
    refuted = ops.verify_identity("(a+b)^2", "a^2 + b^2")
    assert refuted["status"] == "refuted"
    assert set(refuted["counterexample"]) == {"a", "b"}


def test_invalid_symbol_name() -> None:
    with pytest.raises(SympyInputError):
        ops.integrate("x", "__x")
