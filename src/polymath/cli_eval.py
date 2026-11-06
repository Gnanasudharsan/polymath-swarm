"""`polymath eval` — single-agent vs swarm on the eval suites."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from polymath.agents.tools import open_tools
from polymath.core.config import get_settings, load_env_file
from polymath.core.logging import configure_logging
from polymath.core.tracing import flush_tracing, setup_tracing_from_settings
from polymath.evals.datasets import Suite, load_suite
from polymath.evals.harness import SuiteRun, run_suite
from polymath.evals.report import metrics_table, write_report
from polymath.evals.systems import SingleAgent, Swarm, System

SUITES: tuple[Suite, ...] = ("minif2f", "math", "research_qa")


def register(app: typer.Typer) -> None:
    @app.command("eval")
    def eval_(
        suite: Annotated[str, typer.Option(help="minif2f | math | research_qa | all")] = "all",
        n: Annotated[int, typer.Option(help="Problems per suite.")] = 5,
        system: Annotated[str, typer.Option(help="single | swarm | both")] = "both",
        usd_per_problem: Annotated[
            float, typer.Option(help="Hard cap per problem per system.")
        ] = 0.3,
        seed: Annotated[int, typer.Option(help="Sampling seed.")] = 0,
        out: Annotated[Path | None, typer.Option(help="Report directory.")] = None,
    ) -> None:
        """Evaluate single-agent vs swarm; writes evals/reports/<date>/report.md."""
        load_env_file()
        settings = get_settings()
        configure_logging(settings.log_level)
        setup_tracing_from_settings(settings)
        if suite != "all" and suite not in SUITES:
            raise typer.BadParameter(f"unknown suite {suite!r}; choose from {SUITES} or 'all'")
        suites: tuple[Suite, ...] = (
            SUITES if suite == "all" else tuple(s for s in SUITES if s == suite)
        )
        out_dir = out or Path("evals/reports") / date.today().isoformat()

        async def go() -> list[SuiteRun]:
            runs = []
            async with open_tools(settings) as tools:
                systems: list[System] = []
                if system in ("single", "both"):
                    systems.append(SingleAgent(settings, tools))
                if system in ("swarm", "both"):
                    systems.append(Swarm(settings, tools))
                for s in suites:
                    problems = load_suite(s, n, seed)
                    runs.append(await run_suite(s, problems, systems, tools,
                                                usd_per_problem=usd_per_problem))  # fmt: skip
            return runs

        try:
            runs = asyncio.run(go())
        finally:
            flush_tracing()
        typer.echo(metrics_table([m for r in runs for m in r.metrics()]))
        typer.echo(f"report: {write_report(runs, out_dir)}")
