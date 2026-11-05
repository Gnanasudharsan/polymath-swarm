"""Optional on-disk spend ledger: a hard cap on cumulative LLM spend across runs/processes."""

from __future__ import annotations

import json
from pathlib import Path

from polymath.core.budget import BudgetExceededError
from polymath.llm.cost import LLMUsage


class SpendLedger:
    """Append-only JSONL of every priced LLM call. ``check()`` raises once ``cap_usd`` is hit."""

    def __init__(self, path: Path, cap_usd: float | None = None) -> None:
        self.path = path
        self.cap_usd = cap_usd

    def total_usd(self) -> float:
        if not self.path.exists():
            return 0.0
        total = 0.0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += float(json.loads(line).get("usd", 0.0))
        return total

    def append(self, usage: LLMUsage) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(usage.model_dump_json() + "\n")

    def check(self) -> None:
        if self.cap_usd is None:
            return
        spent = self.total_usd()
        if spent >= self.cap_usd:
            raise BudgetExceededError("ledger_usd", spent, self.cap_usd)
