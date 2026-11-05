"""`polymath solve | resume | trace | graph` — the orchestrated swarm from the command line."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from polymath.agents.registry import default_executors, specialists
from polymath.agents.tools import Tools, open_tools
from polymath.blackboard import Blackboard
from polymath.core.budget import BudgetTracker
from polymath.core.config import Settings, get_settings, load_env_file
from polymath.core.logging import configure_logging
from polymath.core.models import Problem
from polymath.core.tracing import setup_tracing, shutdown_tracing
from polymath.graph.builder import compile_graph, mermaid
from polymath.graph.context import RunContext
from polymath.graph.infra import swarm_infra
from polymath.graph.planner import LLMPlanner
from polymath.graph.runner import ContextFactory, RunSnapshot, SwarmRunner
from polymath.graph.state import task_outcomes
from polymath.llm.gateway import LLMGateway
from polymath.memory.episodic import EpisodicMemory
from polymath.memory.knowledge import open_knowledge

MemoryOpt = Annotated[
    bool, typer.Option("--memory", help="In-memory checkpoints/events (no Postgres/Redis).")
]


NoToolsOpt = Annotated[
    bool, typer.Option("--no-tools", help="Reasoner-only, no tool servers (nothing verifies).")
]


def context_factory(
    settings: Settings,
    blackboard: Blackboard,
    tools: Tools | None,
    memory: EpisodicMemory | None = None,
) -> ContextFactory:
    def make(budget: BudgetTracker) -> RunContext:
        gateway = LLMGateway(settings, budget=budget)
        executors = specialists(gateway, tools) if tools else default_executors(gateway)
        return RunContext(
            planner=LLMPlanner(gateway), executors=executors, blackboard=blackboard,
            budget=budget, memory=memory,
        )  # fmt: skip

    return make


@asynccontextmanager
async def open_runner(
    settings: Settings, *, in_memory: bool, with_tools: bool = True
) -> AsyncIterator[SwarmRunner]:
    async with swarm_infra(settings, in_memory=in_memory) as infra:
        if not with_tools:
            yield SwarmRunner(
                compile_graph(infra.checkpointer),
                context_factory(settings, infra.blackboard, None),
                infra.blackboard,
            )
            return
        if not settings.memory_enabled:
            async with open_tools(settings) as tools:
                yield SwarmRunner(
                    compile_graph(infra.checkpointer),
                    context_factory(settings, infra.blackboard, tools),
                    infra.blackboard,
                )
            return
        async with (
            open_knowledge(settings, in_memory=in_memory) as knowledge,
            open_tools(settings, knowledge=knowledge) as tools,
        ):
            yield SwarmRunner(
                compile_graph(infra.checkpointer),
                context_factory(settings, infra.blackboard, tools, knowledge.episodic),
                infra.blackboard,
            )


def write_report(snap: RunSnapshot, directory: Path) -> list[Path]:
    """Write ``<run_id>.md`` and ``<run_id>.json`` if the run produced an evidence report."""
    v = snap.values
    if not v.get("report"):
        return []
    directory.mkdir(parents=True, exist_ok=True)
    md, js = directory / f"{snap.run_id}.md", directory / f"{snap.run_id}.json"
    md.write_text(v.get("report_markdown", ""), encoding="utf-8")
    js.write_text(json.dumps(v["report"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return [md, js]


def _setup() -> Settings:
    load_env_file()
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    setup_tracing(
        service_name=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_endpoint,
        console=settings.otel_console,
    )
    return settings


def _print_plan(plan: dict[str, Any]) -> None:
    typer.secho("Proposed plan", bold=True)
    for tid, task in plan["tasks"].items():
        deps = f"  ← {', '.join(task['deps'])}" if task["deps"] else ""
        typer.echo(f"  • {tid} [{task['assigned_role']}]{deps}\n      {task['description']}")


def _ask_decision() -> bool | dict[str, Any]:
    reply = typer.prompt("Approve? [y]es / [n]o / or type feedback to replan", default="y")
    if reply.strip().lower() in {"y", "yes"}:
        return True
    if reply.strip().lower() in {"n", "no"}:
        return False
    return {"approved": False, "feedback": reply}


def _print_result(snap: RunSnapshot) -> None:
    v = snap.values
    color = typer.colors.GREEN if snap.status and snap.status.value == "completed" else None
    typer.secho(f"\nRun {snap.run_id}: {snap.status}", bold=True, fg=color)
    if v.get("stop_reason"):
        typer.echo(f"  reason: {v['stop_reason']}")
    if "plan" in v:
        for tid, status in task_outcomes(v["plan"], v.get("results") or {}).items():
            typer.echo(f"  {status.value:>8}  {tid}")
    if v.get("report_markdown"):
        typer.echo("\n" + v["report_markdown"])
    elif v.get("answer"):
        typer.secho("\nAnswer", bold=True)
        typer.echo(v["answer"])
    usage = v.get("usage")
    if usage:
        typer.secho(
            f"\n{usage.tokens} tokens · ${usage.usd:.4f} · {v.get('iterations', 0)} round(s)",
            fg=typer.colors.BRIGHT_BLACK,
        )


async def _drive(runner: SwarmRunner, snap: RunSnapshot, interactive: bool) -> RunSnapshot:
    while snap.awaiting_approval and interactive and snap.interrupt is not None:
        _print_plan(snap.interrupt["plan"])
        snap = await runner.resume(snap.run_id, _ask_decision())
    return snap


def register(app: typer.Typer) -> None:
    @app.command()
    def solve(
        problem: Annotated[str, typer.Argument(help="Problem statement.")],
        approve_plan: Annotated[
            bool, typer.Option("--approve-plan", help="Pause for human approval of the plan.")
        ] = False,
        max_usd: Annotated[float, typer.Option(help="Hard USD ceiling for the run.")] = 2.0,
        run_id: Annotated[str | None, typer.Option(help="Explicit run id.")] = None,
        in_memory: MemoryOpt = False,
        no_tools: NoToolsOpt = False,
        report_dir: Annotated[
            Path, typer.Option(help="Where to write the evidence report (.md + .json).")
        ] = Path("reports"),
    ) -> None:
        """Plan and run the swarm on a problem (resumable by run id)."""
        settings = _setup()
        budget = settings.budget.model_copy(update={"max_usd": max_usd})

        async def go() -> RunSnapshot:
            async with open_runner(
                settings, in_memory=in_memory, with_tools=not no_tools
            ) as runner:
                snap = await runner.start(
                    Problem(statement=problem),
                    budget=budget,
                    run_id=run_id,
                    require_approval=approve_plan,
                )
                typer.secho(f"run id: {snap.run_id}", fg=typer.colors.BRIGHT_BLACK)
                return await _drive(runner, snap, interactive=True)

        try:
            snap = asyncio.run(go())
            _print_result(snap)
            for path in write_report(snap, report_dir):
                typer.secho(f"report: {path}", fg=typer.colors.BRIGHT_BLACK)
        finally:
            shutdown_tracing()

    @app.command()
    def resume(
        run_id: Annotated[str, typer.Argument(help="Run to continue.")],
        approve: Annotated[bool | None, typer.Option("--approve/--reject")] = None,
        feedback: Annotated[str | None, typer.Option(help="Reject with feedback → replan.")] = None,
    ) -> None:
        """Resume a paused or interrupted run from its last checkpoint."""
        settings = _setup()

        async def go() -> RunSnapshot:
            async with open_runner(settings, in_memory=False) as runner:
                snap = await runner.snapshot(run_id)
                if snap.awaiting_approval:
                    if feedback:
                        decision: Any = {"approved": False, "feedback": feedback}
                    elif approve is not None:
                        decision = approve
                    else:
                        return await _drive(runner, snap, interactive=True)
                    snap = await runner.resume(run_id, decision)
                else:
                    snap = await runner.resume(run_id)
                return await _drive(runner, snap, interactive=True)

        try:
            _print_result(asyncio.run(go()))
        finally:
            shutdown_tracing()

    @app.command()
    def trace(
        run_id: Annotated[str, typer.Argument(help="Run to export.")],
        output: Annotated[
            Path | None, typer.Option("-o", "--output", help="Write to file.")
        ] = None,
    ) -> None:
        """Export a run's full trace (plan, results, claims, events) as JSON."""
        settings = _setup()

        async def go() -> dict[str, Any]:
            async with open_runner(settings, in_memory=False) as runner:
                return await runner.export_trace(run_id)

        data = json.dumps(asyncio.run(go()), indent=2, ensure_ascii=False)
        if output:
            output.write_text(data, encoding="utf-8")
            typer.echo(f"wrote {output}")
        else:
            typer.echo(data)

    @app.command()
    def graph() -> None:
        """Print the orchestration graph as Mermaid."""
        typer.echo(mermaid())
