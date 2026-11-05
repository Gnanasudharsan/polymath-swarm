"""Markdown + PNG charts for a set of suite runs."""

from __future__ import annotations

import json
from pathlib import Path

from polymath.evals.harness import SuiteMetrics, SuiteRun


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def metrics_table(rows: list[SuiteMetrics]) -> str:
    head = ("| suite | system | n | accuracy | verified-claim rate | hallucinated-citation rate | "
            "$ / problem | latency / problem | errors |")  # fmt: skip
    sep = "|---|---|---|---|---|---|---|---|---|"
    body = [
        f"| {r.suite} | {r.system} | {r.n} | {_pct(r.accuracy)} | {_pct(r.verified_claim_rate)} "
        f"| {_pct(r.hallucinated_citation_rate)} | ${r.usd_per_problem:.4f} "
        f"| {r.latency_s_per_problem:.0f} s | {r.errors} |"
        for r in rows
    ]
    return "\n".join([head, sep, *body])


def charts(rows: list[SuiteMetrics], out: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    suites = sorted({r.suite for r in rows})
    systems = sorted({r.system for r in rows})
    paths = []
    for metric, label, fname in (
        ("accuracy", "accuracy (pass@1)", "accuracy.png"),
        ("usd_per_problem", "USD per problem", "cost.png"),
    ):
        fig, ax = plt.subplots(figsize=(6.5, 3.2), dpi=120)
        width = 0.8 / max(len(systems), 1)
        for i, system in enumerate(systems):
            vals = [
                next((getattr(r, metric) for r in rows if r.suite == s and r.system == system), 0)
                for s in suites
            ]
            xs = [k + i * width for k in range(len(suites))]
            ax.bar(xs, vals, width, label=system, color=["#5b6abf", "#e0884b"][i % 2])
        ax.set_xticks([k + width * (len(systems) - 1) / 2 for k in range(len(suites))], suites)
        ax.set_ylabel(label)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        fig.tight_layout()
        path = out / fname
        fig.savefig(path)
        plt.close(fig)
        paths.append(path)
    return paths


def write_report(runs: list[SuiteRun], out: Path, *, notes: str = "") -> Path:
    out.mkdir(parents=True, exist_ok=True)
    rows = [m for run in runs for m in run.metrics()]
    (out / "results.json").write_text(
        json.dumps([run.model_dump(mode="json") for run in runs], indent=2, ensure_ascii=False)
        + "\n"
    )
    pngs = charts(rows, out) if rows else []
    per_problem = []
    for run in runs:
        for r in run.results:
            mark = "✅" if r.correct else "❌"
            err = f" — {r.attempt.error[:80]}" if r.attempt.error else ""
            per_problem.append(
                f"| {run.suite} | {r.problem_id} | {r.system} | {mark} | "
                f"{r.attempt.claims_verified}/{r.attempt.claims_total} | ${r.attempt.usd:.4f} "
                f"| {r.attempt.latency_s:.0f} s{err} |"
            )
    skipped = [f"{run.suite}: {', '.join(run.skipped)}" for run in runs if run.skipped]
    md = [
        f"# Polymath Swarm — eval report ({out.name})",
        "",
        notes.strip(),
        "",
        "## Summary",
        "",
        metrics_table(rows),
        "",
        *(f"![{p.stem}]({p.name})" for p in pngs),
        "",
        "## Per problem",
        "",
        "| suite | problem | system | correct | verified claims | $ | latency |",
        "|---|---|---|---|---|---|---|",
        *per_problem,
        "",
    ]
    if skipped:
        md += ["Skipped (statement does not elaborate on Mathlib v4.35): " + "; ".join(skipped), ""]
    path = out / "report.md"
    path.write_text("\n".join(md))
    return path
