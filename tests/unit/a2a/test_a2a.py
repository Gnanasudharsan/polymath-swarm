"""A2A: Agent Cards, an external A2A client calling the swarm and a specialist, and delegation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from a2a import helpers
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Role, SendMessageRequest
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict

from polymath.a2a.client import A2ADelegate
from polymath.agents.base import AgentContext
from polymath.api.app import create_app
from polymath.api.runs import RunManager
from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.config import Settings
from polymath.core.models import AgentRole, ClaimStatus, Problem, Task, TaskType
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from tests.swarm_fakes import FakeExecutor, FixedPlanner, diamond, make_factory

KEY = "a2a-key"
BASE = "http://swarm.test"


def _app() -> FastAPI:
    @asynccontextmanager
    async def factory() -> AsyncIterator[RunManager]:
        bb = Blackboard(InMemoryEventStore())
        fake = FakeExecutor()

        def ctx(budget):  # type: ignore[no-untyped-def]
            c = make_factory(FixedPlanner(diamond()), fake, bb)(budget)
            c.executors = {r: fake for r in AgentRole}
            return c

        yield RunManager(SwarmRunner(compile_graph(memory_checkpointer()), ctx, bb), bb)

    settings = Settings(_env_file=None, api_key=KEY, public_url=BASE)  # type: ignore[call-arg]
    return create_app(settings, factory)


@asynccontextmanager
async def served() -> AsyncIterator[httpx.AsyncClient]:
    app = _app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE, timeout=30) as http:
            yield http


async def _send(http: httpx.AsyncClient, url: str, text: str) -> list:  # type: ignore[type-arg]
    http.headers["x-api-key"] = KEY
    client = await ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create_from_url(
        url
    )
    message = helpers.new_text_message(text, role=Role.ROLE_USER)
    return [r async for r in client.send_message(SendMessageRequest(message=message))]


async def test_agent_cards_are_public_and_rpc_needs_the_key() -> None:
    async with served() as http:
        card = (await http.get("/.well-known/agent-card.json")).json()
        assert card["name"] == "Polymath Swarm"
        assert card["supportedInterfaces"][0]["url"] == f"{BASE}/a2a"
        assert "polymathApiKey" in card["securitySchemes"]
        for role in ("literature", "reasoner", "compute", "formalizer", "critic"):
            c = (await http.get(f"/agents/{role}/.well-known/agent-card.json")).json()
            assert c["supportedInterfaces"][0]["url"].endswith(f"/agents/{role}/a2a")
        assert (await http.post("/a2a", json={})).status_code == 401
        assert (await http.post("/agents/compute/a2a", json={})).status_code == 401


async def test_external_a2a_client_runs_the_swarm() -> None:
    async with served() as http:
        responses = await _send(http, BASE, "toy problem")
    (resp,) = responses
    task = MessageToDict(resp)["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    names = [a["name"] for a in task["artifacts"]]
    assert names == ["evidence_report", "evidence_report_json"]
    data = task["artifacts"][1]["parts"][0]["data"]
    assert data["status"] == "completed" and data["run_id"].startswith("run_")
    assert "synth done" in helpers.get_stream_response_text(resp)


async def test_external_a2a_client_calls_a_specialist() -> None:
    async with served() as http:
        (resp,) = await _send(http, f"{BASE}/agents/reasoner", "is 2+2 = 4?")
    task = MessageToDict(resp)["task"]
    claims = task["artifacts"][1]["parts"][0]["data"]["claims"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert claims and claims[0]["status"] == "proposed"


async def test_delegate_returns_remote_answer_as_an_unverified_claim() -> None:
    async with served() as http:
        http.headers["x-api-key"] = KEY
        delegate = A2ADelegate(BASE, AgentRole.LITERATURE, http=http)
        task = Task(id="lit", type=TaskType.LITERATURE_SEARCH, description="find papers",
                    assigned_role=AgentRole.LITERATURE)  # fmt: skip
        result = await delegate.run(task, AgentContext(problem=Problem(statement="p")))
    assert "synth done" in result.output
    (claim,) = result.claims
    assert claim.status == ClaimStatus.PROPOSED and claim.evidence == []
    assert claim.statement.startswith(f"[external A2A agent at {BASE}]")
    assert claim.confidence <= 0.3


async def test_delegation_is_configured_per_role() -> None:
    from polymath.cli_swarm import context_factory

    settings = Settings(_env_file=None, a2a_delegates={"literature": "http://other"})  # type: ignore[call-arg]
    ctx = context_factory(settings, Blackboard(InMemoryEventStore()), None)
    from polymath.core.budget import BudgetTracker
    from polymath.core.models import RunBudget

    executors = ctx(BudgetTracker(RunBudget())).executors
    assert isinstance(executors[AgentRole.LITERATURE], A2ADelegate)
    assert not isinstance(executors[AgentRole.REASONER], A2ADelegate)
