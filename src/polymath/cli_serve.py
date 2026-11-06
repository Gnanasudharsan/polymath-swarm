"""`polymath serve` — run the HTTP API (FastAPI + SSE) with uvicorn."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import typer

from polymath.agents.tools import open_tools
from polymath.api.app import create_app
from polymath.api.auth import hash_key, new_key
from polymath.api.runs import RunManager
from polymath.cli_swarm import context_factory
from polymath.core.config import Settings, get_settings, load_env_file
from polymath.core.logging import configure_logging
from polymath.core.tracing import setup_tracing_from_settings
from polymath.graph.builder import compile_graph
from polymath.graph.infra import swarm_infra
from polymath.graph.runner import SwarmRunner
from polymath.llm.gateway import CompletionFn
from polymath.llm.mock import ScriptedLLM
from polymath.memory.knowledge import open_knowledge


def manager_factory(settings: Settings, *, in_memory: bool, mock_llm: bool):  # type: ignore[no-untyped-def]
    completion: CompletionFn | None = ScriptedLLM() if mock_llm else None
    use_memory = settings.memory_enabled and not mock_llm

    @asynccontextmanager
    async def factory() -> AsyncIterator[RunManager]:
        async with swarm_infra(settings, in_memory=in_memory) as infra:
            if use_memory:
                async with (
                    open_knowledge(settings, in_memory=in_memory) as knowledge,
                    open_tools(settings, knowledge=knowledge) as tools,
                ):
                    ctx = context_factory(settings, infra.blackboard, tools, knowledge.episodic)
                    runner = SwarmRunner(compile_graph(infra.checkpointer), ctx, infra.blackboard)
                    yield RunManager(runner, infra.blackboard)
                return
            # Mock mode needs only the sandbox (computation); no Lean, no memory.
            async with open_tools(settings, lean_enabled=not mock_llm) as tools:
                ctx = context_factory(settings, infra.blackboard, tools, None, completion)
                runner = SwarmRunner(compile_graph(infra.checkpointer), ctx, infra.blackboard)
                yield RunManager(runner, infra.blackboard)

    return factory


keys_app = typer.Typer(help="Manage API users and keys.", no_args_is_help=True)


@keys_app.command("new")
def keys_new(user: Annotated[str, typer.Argument(help="User name, e.g. alice.")]) -> None:
    """Create a key for USER. Prints the key once (give it to the user) and the hash to put in
    POLYMATH_API_USERS (the server stores only hashes)."""
    if not user.replace("-", "").replace("_", "").isalnum():
        raise typer.BadParameter("use letters, digits, '-' and '_'")
    key = new_key()
    typer.echo(f"key  (give to {user}; shown once): {key}")
    typer.echo(f"hash (server config):  {json.dumps({user: hash_key(key)})}")
    typer.echo('Merge into POLYMATH_API_USERS, e.g. POLYMATH_API_USERS=\'{"alice":"sha256:..."}\'')


def register(app: typer.Typer) -> None:
    app.add_typer(keys_app, name="keys")

    @app.command()
    def serve(
        host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
        port: Annotated[int, typer.Option(help="Port.")] = 8000,
        in_memory: Annotated[
            bool, typer.Option("--memory", help="In-memory checkpoints/events (no Postgres/Redis).")
        ] = False,
        mock_llm: Annotated[
            bool, typer.Option("--mock-llm", help="Scripted offline LLM (UI dev / e2e; $0).")
        ] = False,
        cors: Annotated[str, typer.Option(help="Comma-separated allowed origins.")] = "",
    ) -> None:
        """Serve the Polymath API (POLYMATH_API_KEY or POLYMATH_API_USERS required)."""
        import uvicorn

        load_env_file()
        settings = get_settings()
        if mock_llm:
            # Notional mock usage must never reach the real spend ledger.
            settings = settings.model_copy(update={"spend_ledger": None, "memory_enabled": False})
        configure_logging(settings.log_level, json=settings.log_json)
        setup_tracing_from_settings(settings)
        try:
            api = create_app(
                settings,
                manager_factory(settings, in_memory=in_memory, mock_llm=mock_llm),
                cors_origins=[o for o in cors.split(",") if o] or None,
            )
        except RuntimeError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        uvicorn.run(api, host=host, port=port, log_level="warning")
