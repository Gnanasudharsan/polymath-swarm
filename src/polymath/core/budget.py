"""Run-budget enforcement: tokens, USD, wall-clock time and iterations."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from polymath.core.models import RunBudget


class BudgetExceededError(RuntimeError):
    """Raised when a run hits any hard ceiling."""

    def __init__(self, dimension: str, used: float, limit: float) -> None:
        super().__init__(f"run budget exceeded: {dimension} used {used:g} of {limit:g}")
        self.dimension = dimension
        self.used = used
        self.limit = limit


@dataclass
class BudgetTracker:
    """Mutable accounting against an immutable :class:`RunBudget`.

    ``clock`` is injectable so tests can control wall-clock time.
    """

    budget: RunBudget
    clock: Callable[[], float] = time.monotonic
    tokens_used: int = 0
    usd_used: float = 0.0
    iterations: int = 0
    _started_at: float = field(init=False)

    def __post_init__(self) -> None:
        self._started_at = self.clock()

    @property
    def elapsed_s(self) -> float:
        return self.clock() - self._started_at

    def record(self, *, tokens: int = 0, usd: float = 0.0) -> None:
        if tokens < 0 or usd < 0:
            raise ValueError("usage must be non-negative")
        self.tokens_used += tokens
        self.usd_used += usd

    def tick(self) -> None:
        """Count one supervisor iteration."""
        self.iterations += 1

    def usage_fractions(self) -> dict[str, float]:
        """Fraction of each bounded dimension consumed (unbounded ones are omitted)."""
        b = self.budget
        fractions: dict[str, float] = {}
        if b.max_tokens is not None:
            fractions["tokens"] = self.tokens_used / b.max_tokens
        if b.max_usd is not None:
            fractions["usd"] = self.usd_used / b.max_usd
        if b.max_wall_clock_s is not None:
            fractions["wall_clock_s"] = self.elapsed_s / b.max_wall_clock_s
        if b.max_iterations is not None:
            fractions["iterations"] = self.iterations / b.max_iterations
        return fractions

    def max_fraction(self) -> float:
        return max(self.usage_fractions().values(), default=0.0)

    def is_near_limit(self, threshold: float = 0.8) -> bool:
        """True once any dimension passes ``threshold`` — the cue to degrade gracefully."""
        return self.max_fraction() >= threshold

    def check(self) -> None:
        """Raise :class:`BudgetExceededError` if any ceiling has been reached."""
        b = self.budget
        checks: list[tuple[str, float, float | None]] = [
            ("tokens", self.tokens_used, b.max_tokens),
            ("usd", self.usd_used, b.max_usd),
            ("wall_clock_s", self.elapsed_s, b.max_wall_clock_s),
            ("iterations", self.iterations, b.max_iterations),
        ]
        for name, used, limit in checks:
            if limit is not None and used >= limit:
                raise BudgetExceededError(name, used, limit)

    def snapshot(self) -> dict[str, float]:
        return {
            "tokens_used": self.tokens_used,
            "usd_used": round(self.usd_used, 6),
            "elapsed_s": round(self.elapsed_s, 3),
            "iterations": self.iterations,
        }
