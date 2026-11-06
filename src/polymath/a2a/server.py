"""Serve the swarm and each specialist as A2A agents (JSON-RPC + Agent Cards) on the API app."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from a2a import helpers
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    DefaultServerCallContextBuilder,
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from polymath.a2a.cards import SPECIALISTS, specialist_card, swarm_card
from polymath.agents.base import AgentContext
from polymath.api.auth import SCOPE_KEY, KeyRing, Principal
from polymath.core.budget import BudgetTracker
from polymath.core.logging import get_logger
from polymath.core.models import AgentRole, Problem, RunBudget, Task, TaskType
from polymath.graph.planner import ROLE_FOR_TYPE
from polymath.graph.runner import SwarmRunner

log = get_logger(__name__)
RunnerGetter = Callable[[], SwarmRunner]
TYPE_FOR_ROLE: dict[AgentRole, TaskType] = {r: t for t, r in ROLE_FOR_TYPE.items()}
MAX_INPUT_CHARS = 8000


def _text_input(context: RequestContext) -> str:
    text = (context.get_user_input() or "").strip()
    if not text:
        raise ValueError("send the problem as a text part")
    return text[:MAX_INPUT_CHARS]


class PrincipalContextBuilder(DefaultServerCallContextBuilder):
    """Carries the user that ``A2AKeyMiddleware`` authenticated into the executor."""

    def build(self, request: Request) -> ServerCallContext:
        ctx = super().build(request)
        headers = ctx.state.get("headers")
        if isinstance(headers, dict):
            headers.pop("x-api-key", None)  # never keep the raw API key around
        ctx.state["principal"] = request.scope.get(SCOPE_KEY)
        return ctx


def _owner(context: RequestContext) -> str | None:
    who = context.call_context.state.get("principal")
    return who.user if isinstance(who, Principal) else None


async def _begin(context: RequestContext, queue: EventQueue) -> TaskUpdater:
    task = context.current_task
    if task is None:
        if context.message is None:
            raise ValueError("no message")
        task = helpers.new_task_from_user_message(context.message)
        await queue.enqueue_event(task)
    updater = TaskUpdater(queue, task.id, task.context_id)
    await updater.start_work()
    return updater


class SwarmAgentExecutor(AgentExecutor):
    """A2A ``message/send`` → one full verified swarm run (no plan approval)."""

    def __init__(self, get_runner: RunnerGetter, budget: RunBudget) -> None:
        self.get_runner, self.budget = get_runner, budget

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = await _begin(context, event_queue)
        problem = _text_input(context)
        snap = await self.get_runner().start(Problem(statement=problem), budget=self.budget,
                                             owner=_owner(context))  # fmt: skip
        values = snap.values
        markdown = values.get("report_markdown") or values.get("answer") or "(no answer)"
        await updater.add_artifact([helpers.new_text_part(markdown, media_type="text/markdown")],
                                   name="evidence_report")  # fmt: skip
        report = values.get("report") or {}
        summary = {"run_id": snap.run_id, "status": snap.status.value if snap.status else None,
                   "report": report}  # fmt: skip
        await updater.add_artifact([helpers.new_data_part(summary)], name="evidence_report_json")
        log.info("a2a.swarm_run", run_id=snap.run_id, status=summary["status"])
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancellation is not supported")


class SpecialistAgentExecutor(AgentExecutor):
    """A2A ``message/send`` → one specialist task. Its claims are proposals, not verified."""

    def __init__(self, get_runner: RunnerGetter, role: AgentRole, budget: RunBudget) -> None:
        self.get_runner, self.role, self.budget = get_runner, role, budget

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = await _begin(context, event_queue)
        text = _text_input(context)
        ctx = self.get_runner().make_context(BudgetTracker(self.budget))
        task = Task(type=TYPE_FOR_ROLE[self.role], description=text, assigned_role=self.role)
        result = await ctx.executor_for(self.role).run(
            task, AgentContext(problem=Problem(statement=text))
        )
        await updater.add_artifact([helpers.new_text_part(result.output)], name="output")
        payload = {"role": self.role.value, "success": result.success, "error": result.error,
                   "claims": [c.model_dump(mode="json") for c in result.claims]}  # fmt: skip
        await updater.add_artifact([helpers.new_data_part(payload)], name="claims")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancellation is not supported")


class A2AKeyMiddleware(BaseHTTPMiddleware):
    """A2A JSON-RPC endpoints need the API key; Agent Cards stay public for discovery."""

    def __init__(self, app: Any, keys: KeyRing) -> None:
        super().__init__(app)
        self.keys = keys

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        guarded = path == "/a2a" or (path.startswith("/agents/") and path.endswith("/a2a"))
        if guarded:
            who = self.keys.authenticate(request.headers.get("x-api-key"))
            if who is None:
                return JSONResponse({"detail": "missing or invalid API key"}, status_code=401)
            request.scope[SCOPE_KEY] = who
        return await call_next(request)


def mount_a2a(
    app: FastAPI, get_runner: RunnerGetter, *, base_url: str, budget: RunBudget, keys: KeyRing
) -> None:
    """Routes are mounted at app creation; the runner exists only once the lifespan has started,
    so executors resolve it through ``get_runner`` on each request."""
    card = swarm_card(base_url)
    swarm = DefaultRequestHandler(agent_executor=SwarmAgentExecutor(get_runner, budget),
                                  task_store=InMemoryTaskStore(), agent_card=card)  # fmt: skip
    rpc = create_jsonrpc_routes(swarm, "/a2a", PrincipalContextBuilder())
    add_a2a_routes_to_fastapi(app, agent_card_routes=create_agent_card_routes(card),
                              jsonrpc_routes=rpc)  # fmt: skip
    for role in SPECIALISTS:
        scard = specialist_card(role, base_url)
        handler = DefaultRequestHandler(
            agent_executor=SpecialistAgentExecutor(get_runner, role, budget),
            task_store=InMemoryTaskStore(), agent_card=scard,
        )  # fmt: skip
        prefix = f"/agents/{role.value}"
        add_a2a_routes_to_fastapi(
            app,
            agent_card_routes=create_agent_card_routes(
                scard, card_url=f"{prefix}/.well-known/agent-card.json"
            ),
            jsonrpc_routes=create_jsonrpc_routes(
                handler, f"{prefix}/a2a", PrincipalContextBuilder()
            ),
        )
    app.add_middleware(A2AKeyMiddleware, keys=keys)
