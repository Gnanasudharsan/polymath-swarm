"""Run one of the end-to-end demos and save its evidence report and trace.

    uv run python examples/run_demo.py proof|computation|literature|reuse [--max-usd 1.0]

Needs `docker compose up -d --wait`, the tool images, and a provider key in the environment.
Outputs go to examples/<name>/{report.md,report.json,trace.json}.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from polymath.cli_swarm import open_runner
from polymath.core.config import get_settings, load_env_file
from polymath.core.logging import configure_logging
from polymath.core.models import Problem, RunBudget

HERE = Path(__file__).parent

PROBLEMS: dict[str, str] = {
    "proof": "Prove that for every natural number n, the product n * (n + 1) is even.",
    # Run after `proof`: episodic memory recalls its verified lemma (Phase 5).
    "reuse": "Prove that for every natural number n, the product n * (n + 1) * (n + 2) is even.",
    "computation": (
        "Compute the sum of the first 100 prime numbers, and determine whether that sum is itself "
        "a prime number."
    ),
    "literature": (
        "In 2023 an exponential improvement over the Erdős-Szekeres upper bound for the diagonal "
        "Ramsey numbers R(k) was announced. Which paper proved it, and what form does the new "
        "upper bound take?"
    ),
}


async def run(name: str, max_usd: float) -> None:
    load_env_file()
    settings = get_settings()
    configure_logging(settings.log_level)
    budget = RunBudget(
        max_usd=max_usd, max_tokens=600_000, max_wall_clock_s=1800, max_iterations=30
    )
    out = HERE / name
    out.mkdir(exist_ok=True)
    async with open_runner(settings, in_memory=False) as runner:
        snap = await runner.start(Problem(statement=PROBLEMS[name]), budget=budget)
        trace = await runner.export_trace(snap.run_id)
    values = snap.values
    if values.get("report"):
        (out / "report.md").write_text(values["report_markdown"], encoding="utf-8")
        (out / "report.json").write_text(
            json.dumps(values["report"], indent=2, ensure_ascii=False) + "\n"
        )
    (out / "trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n")
    usage = values.get("usage")
    print(f"{name}: run {snap.run_id} → {snap.status}; ${usage.usd if usage else 0:.4f}")
    if values.get("report"):
        report = values["report"]
        print(
            f"  verified={len(report['verified'])} conjectures={len(report['conjectures'])} "
            f"refuted={len(report['refuted'])}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(PROBLEMS))
    parser.add_argument("--max-usd", type=float, default=1.0)
    args = parser.parse_args()
    asyncio.run(run(args.name, args.max_usd))


if __name__ == "__main__":
    main()
