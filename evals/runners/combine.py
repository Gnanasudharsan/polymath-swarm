"""Merge per-suite eval outputs into one report.

    uv run python evals/runners/combine.py <out_dir> <suite_dir> [<suite_dir> ...]

Each suite dir is the ``--out`` of a ``polymath eval`` run (it holds ``results.json``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from polymath.evals.harness import SuiteRun
from polymath.evals.report import write_report

NOTES = """
Single agent (one LLM call per problem, same models and checkers) vs. the full swarm (planning,
specialists, critique loop, Lean repair + automation, verification gate; memory disabled).
Model profile `openai`: gpt-5 for Lean/formalization, gpt-5-mini elsewhere. Per-problem cap
$0.25 per system. **Small samples** (stated per suite), so treat differences as indicative.
Scoring is deterministic: numeric equivalence (MATH), all answer keywords present (research QA),
and a gate-verified Lean proof that keeps the benchmark statement verbatim (miniF2F).
"""


def main() -> None:
    out, *suite_dirs = (Path(a) for a in sys.argv[1:])
    runs = []
    for d in suite_dirs:
        for raw in json.loads((d / "results.json").read_text()):
            runs.append(SuiteRun.model_validate(raw))
    print(write_report(runs, out, notes=NOTES))


if __name__ == "__main__":
    main()
