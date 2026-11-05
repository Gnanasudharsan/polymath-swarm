"""Command-line entry point (`polymath ...`)."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import typer

from polymath import __version__
from polymath.agents.base import AgentContext, AgentResult
from polymath.agents.reasoner import ReasonerAgent
from polymath.core.budget import BudgetExceededError, BudgetTracker
from polymath.core.config import Settings, get_settings, load_env_file
from polymath.core.logging import configure_logging
from polymath.core.models import AgentRole, Problem, RunBudget, Task, TaskType
from polymath.core.tracing import setup_tracing_from_settings as setup_tracing
from polymath.core.tracing import shutdown_tracing
from polymath.llm.cost import CostSummary, CostTracker
from polymath.llm.gateway import LLMError, LLMGateway
from polymath.llm.structured import StructuredOutputError

app = typer.Typer(
    name="polymath",
    help="Polymath Swarm: verification-first multi-agent research & math solver.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Polymath Swarm CLI."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


async def ask_reasoner(
    question: str, settings: Settings, budget: RunBudget, model: str | None = None
) -> tuple[AgentResult, CostSummary]:
    """Run a single Reasoner task on ``question`` under ``budget``."""
    if model:
        settings = settings.model_copy(
            update={"role_models": {**settings.role_models, AgentRole.REASONER: model}}
        )
    costs = CostTracker()
    gateway = LLMGateway(settings, cost_tracker=costs, budget=BudgetTracker(budget))
    problem = Problem(statement=question)
    task = Task(type=TaskType.REASONING, description=question, assigned_role=AgentRole.REASONER)
    result = await ReasonerAgent(gateway).run(task, AgentContext(problem=problem))
    return result, costs.summary()


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="The question or problem to reason about.")],
    model: Annotated[str | None, typer.Option(help="Override the Reasoner's model.")] = None,
    max_usd: Annotated[float, typer.Option(help="Hard USD ceiling for this call.")] = 0.5,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """Ask the Reasoner agent a single question (no verification yet)."""
    load_env_file()
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    setup_tracing(settings)
    budget = settings.budget.model_copy(update={"max_usd": max_usd})
    try:
        result, cost = asyncio.run(ask_reasoner(question, settings, budget, model))
    except (LLMError, StructuredOutputError, BudgetExceededError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    finally:
        shutdown_tracing()

    if as_json:
        payload = {"result": result.model_dump(mode="json"), "cost": cost.model_dump()}
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.secho("Answer", bold=True)
    typer.echo(result.output)
    if result.claims:
        typer.secho("\nClaims (proposed, unverified)", bold=True)
        for claim in result.claims:
            typer.echo(f"  • [{claim.confidence:.2f}] {claim.statement}")
    typer.secho(
        f"\n{cost.calls} call(s) · {cost.total_tokens} tokens · ${cost.usd:.4f}",
        fg=typer.colors.BRIGHT_BLACK,
    )


# Swarm commands live in their own module to keep this file small.
from polymath.cli_swarm import register  # noqa: E402

register(app)


if __name__ == "__main__":  # pragma: no cover
    app()
