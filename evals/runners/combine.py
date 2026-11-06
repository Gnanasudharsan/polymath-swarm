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

## Findings (2026-11-05 run)

- **miniF2F**: the swarm proved 1/3 (Lean repair + Mathlib automation), the single agent 0/3, and
  the swarm was cheaper per problem ($0.12 vs $0.14), because its gpt-5 calls were shorter.
- **MATH (Level 5)**: both 6/6. The swarm costs about 15 times more ($0.007 vs $0.0005 per
  problem) and backs 64% of its claims with re-run computations; the single agent's answers carry
  no evidence.
- **Research QA**: the single agent answered more (4/6 vs 2/6) but **3 of its 6 citations were
  unsupported** (quote not found in the re-fetched paper): a 50% hallucinated-citation rate. Every
  swarm citation (15/15) was verified. The swarm's misses come from verification-first behaviour
  (it abstained on ResNet when search did not surface the original paper) and from strict keyword
  scoring (e.g. "generative model" instead of "generator"). The scorer was fixed before the run and
  was not changed after seeing results.
- An earlier attempt of this run was invalidated when the OpenAI account ran out of credit; only
  the affected attempts were re-run (`evals/runners/rerun_failed.py`), so no valid result was
  replaced.
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
