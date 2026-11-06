"""Re-run only the attempts that failed for infrastructure reasons (provider quota / rate limits),
keeping every valid result, then rewrite the suite's results.json.

    uv run python evals/runners/rerun_failed.py <suite_dir> [--usd-per-problem 0.25]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from polymath.agents.tools import open_tools
from polymath.core.config import get_settings, load_env_file
from polymath.core.logging import configure_logging
from polymath.core.models import RunBudget
from polymath.core.tracing import flush_tracing, setup_tracing_from_settings
from polymath.evals.harness import ProblemResult, SuiteRun
from polymath.evals.scoring import score
from polymath.evals.systems import SingleAgent, Swarm, System

INFRA_ERRORS = ("RateLimitError", "quota exhausted", "no credits", "all models failed")


def infra_failure(r: ProblemResult) -> bool:
    """An attempt that errored on the provider, or errored after spending almost nothing (its
    agents' calls failed before doing real work, e.g. quota running out mid-run)."""
    err = r.attempt.error or ""
    return bool(err) and (any(m in err for m in INFRA_ERRORS) or r.attempt.usd < 0.01)


async def main(suite_dir: Path, usd_per_problem: float) -> None:
    load_env_file()
    settings = get_settings()
    configure_logging(settings.log_level)
    setup_tracing_from_settings(settings)
    path = suite_dir / "results.json"
    runs = [SuiteRun.model_validate(r) for r in json.loads(path.read_text())]
    budget = RunBudget(max_usd=usd_per_problem, max_tokens=400_000, max_wall_clock_s=1500,
                       max_iterations=20)  # fmt: skip
    async with open_tools(settings) as tools:
        systems: dict[str, System] = {"single": SingleAgent(settings, tools),
                                      "swarm": Swarm(settings, tools)}  # fmt: skip
        for run in runs:
            problems = {p.id: p for p in run.problems}
            todo = [i for i, r in enumerate(run.results) if infra_failure(r)]
            print(f"{run.suite}: re-running {len(todo)} of {len(run.results)} attempts")
            for i in todo:
                old = run.results[i]
                problem = problems[old.problem_id]
                attempt = await systems[old.system].solve(problem, budget)
                correct = score(problem, attempt.answer, attempt.verified_lean)
                run.results[i] = ProblemResult(problem_id=old.problem_id, system=old.system,
                                               correct=correct, attempt=attempt)  # fmt: skip
                print(
                    f"  {old.problem_id} [{old.system}] correct={correct} "
                    f"usd={attempt.usd:.4f} error={(attempt.error or '')[:80]}"
                )
                path.write_text(json.dumps([r.model_dump(mode="json") for r in runs], indent=2,
                                           ensure_ascii=False) + "\n")  # fmt: skip
    flush_tracing()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--usd-per-problem", type=float, default=0.25)
    args = parser.parse_args()
    asyncio.run(main(args.suite_dir, args.usd_per_problem))
