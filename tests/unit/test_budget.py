from __future__ import annotations

import pytest

from polymath.core.budget import BudgetExceededError, BudgetTracker
from polymath.core.models import RunBudget


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _tracker(**limits: float | int | None) -> tuple[BudgetTracker, FakeClock]:
    clock = FakeClock()
    base: dict[str, float | int | None] = {
        "max_tokens": None,
        "max_usd": None,
        "max_wall_clock_s": None,
        "max_iterations": None,
    }
    return BudgetTracker(RunBudget(**{**base, **limits}), clock=clock), clock  # type: ignore[arg-type]


def test_unlimited_budget_never_trips() -> None:
    t, clock = _tracker()
    t.record(tokens=10**9, usd=10**6)
    clock.now = 10**9
    t.check()
    assert t.max_fraction() == 0.0


@pytest.mark.parametrize(
    ("limits", "action", "dimension"),
    [
        ({"max_tokens": 100}, lambda t, c: t.record(tokens=100), "tokens"),
        ({"max_usd": 1.0}, lambda t, c: t.record(usd=1.0), "usd"),
        ({"max_wall_clock_s": 30}, lambda t, c: setattr(c, "now", 31.0), "wall_clock_s"),
        ({"max_iterations": 2}, lambda t, c: (t.tick(), t.tick()), "iterations"),
    ],
)
def test_each_dimension_enforced(limits, action, dimension) -> None:  # type: ignore[no-untyped-def]
    t, clock = _tracker(**limits)
    t.check()
    action(t, clock)
    with pytest.raises(BudgetExceededError) as exc:
        t.check()
    assert exc.value.dimension == dimension


def test_near_limit_threshold() -> None:
    t, _ = _tracker(max_usd=1.0, max_tokens=1000)
    t.record(usd=0.5, tokens=100)
    assert not t.is_near_limit(0.8)
    t.record(usd=0.31)
    assert t.is_near_limit(0.8)
    assert t.usage_fractions()["usd"] == pytest.approx(0.81)


def test_negative_usage_rejected() -> None:
    t, _ = _tracker()
    with pytest.raises(ValueError, match="non-negative"):
        t.record(tokens=-1)


def test_snapshot() -> None:
    t, clock = _tracker()
    t.record(tokens=5, usd=0.25)
    t.tick()
    clock.now = 2.5
    assert t.snapshot() == {"tokens_used": 5, "usd_used": 0.25, "elapsed_s": 2.5, "iterations": 1}
