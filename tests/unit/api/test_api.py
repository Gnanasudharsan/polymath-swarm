"""HTTP API with fake agents (in-memory checkpointer and blackboard; no LLM, no Docker)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from polymath.api.app import create_app
from polymath.api.runs import RunManager
from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.config import Settings
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from polymath.llm.mock import scripted_reply
from tests.swarm_fakes import FakeExecutor, FixedPlanner, diamond, make_factory

KEY = {"x-api-key": "test-key"}


def _settings() -> Settings:
    return Settings(_env_file=None, api_key="test-key")  # type: ignore[call-arg]


@pytest.fixture
def client() -> Iterator[TestClient]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[RunManager]:
        bb = Blackboard(InMemoryEventStore())
        runner = SwarmRunner(
            compile_graph(memory_checkpointer()),
            make_factory(FixedPlanner(diamond()), FakeExecutor(delays={"a": 0.2}), bb),
            bb,
        )
        yield RunManager(runner, bb)

    with TestClient(create_app(_settings(), factory)) as c:
        yield c


def _wait(client: TestClient, run_id: str, pred, timeout: float = 15.0) -> dict:  # type: ignore[no-untyped-def,type-arg]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = client.get(f"/runs/{run_id}", headers=KEY).json()
        if pred(d):
            return d  # type: ignore[no-any-return]
        time.sleep(0.05)
    raise AssertionError(f"timeout; last state {d}")


def test_health_is_public_everything_else_needs_the_key(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/runs").status_code == 401
    assert client.get("/runs", headers={"x-api-key": "wrong"}).status_code == 401
    assert client.get("/runs", headers=KEY).json() == {"runs": []}


def test_refuses_to_start_without_api_key() -> None:
    with pytest.raises(RuntimeError, match="POLYMATH_API_KEY"):
        create_app(Settings(_env_file=None), lambda: None)  # type: ignore[arg-type,call-arg]


def test_create_run_and_follow_it_to_completion(client: TestClient) -> None:
    resp = client.post("/runs", headers=KEY, json={"problem": "toy", "max_usd": 0.5})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    listed = client.get("/runs", headers=KEY).json()["runs"]
    assert [r["run_id"] for r in listed] == [run_id] and listed[0]["problem"] == "toy"
    d = _wait(client, run_id, lambda d: d["finished"])
    assert d["status"] == "completed"
    assert d["task_status"] == {"a": "done", "b": "done", "synth": "done"}
    assert {t["id"] for t in d["tasks"]} == {"a", "b", "synth"}
    assert len(d["claims"]) == 3 and d["max_usd"] == 0.5
    assert d["answer"].startswith("synth done")


def test_plan_approval_over_http(client: TestClient) -> None:
    run_id = client.post("/runs", headers=KEY, json={"problem": "p", "require_approval": True}
                         ).json()["run_id"]  # fmt: skip
    d = _wait(client, run_id, lambda d: d["awaiting_approval"])
    assert d["status"] == "awaiting_approval" and d["tasks"]
    assert set(d["task_status"].values()) == {"pending"}
    assert client.post(f"/runs/{run_id}/resume", headers=KEY).status_code == 409
    assert client.post(f"/runs/{run_id}/approve", headers=KEY, json={"approved": True}
                       ).status_code == 202  # fmt: skip
    d = _wait(client, run_id, lambda d: d["finished"])
    assert d["status"] == "completed"
    # once finished, a second decision is a conflict
    assert client.post(f"/runs/{run_id}/approve", headers=KEY, json={"approved": True}
                       ).status_code == 409  # fmt: skip


def test_reject_with_feedback_replans(client: TestClient) -> None:
    run_id = client.post("/runs", headers=KEY, json={"problem": "p", "require_approval": True}
                         ).json()["run_id"]  # fmt: skip
    _wait(client, run_id, lambda d: d["awaiting_approval"])
    client.post(f"/runs/{run_id}/approve", headers=KEY,
                json={"approved": False, "feedback": "add a critic"})  # fmt: skip
    _wait(client, run_id, lambda d: d["awaiting_approval"])  # a fresh plan awaits approval
    client.post(f"/runs/{run_id}/approve", headers=KEY, json={"approved": True})
    assert _wait(client, run_id, lambda d: d["finished"])["status"] == "completed"


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/runs/run_nope", headers=KEY).status_code == 404
    assert client.get("/runs/run_nope/stream", headers=KEY).status_code == 404
    assert client.post("/runs/run_nope/approve", headers=KEY, json={"approved": True}
                       ).status_code == 404  # fmt: skip


def test_validation(client: TestClient) -> None:
    assert client.post("/runs", headers=KEY, json={"problem": ""}).status_code == 422
    assert client.post("/runs", headers=KEY, json={"problem": "x", "max_usd": 100}
                       ).status_code == 422  # fmt: skip


def test_stream_replays_and_ends_after_run_finished(client: TestClient) -> None:
    run_id = client.post("/runs", headers=KEY, json={"problem": "toy"}).json()["run_id"]
    _wait(client, run_id, lambda d: d["finished"])
    kinds = []
    with client.stream("GET", f"/runs/{run_id}/stream", headers=KEY) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data:"):
                kinds.append(json.loads(line[5:])["kind"])
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    assert kinds.count("task_finished") == 3


def test_mock_llm_script_covers_the_scripted_agents() -> None:
    def sys_msg(text: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": text}, {"role": "user", "content": "[claim_ab12] x"}]

    assert (
        scripted_reply(sys_msg("You are the **Supervisor / Planner**"))["problem_type"]
        == "computation"
    )  # type: ignore[index]
    assert (
        "POLYMATH_RESULT"
        in scripted_reply(sys_msg("You establish or test claims"))["checks"][0]["program"]
    )  # type: ignore[index]
    review = scripted_reply(sys_msg("an adversarial reviewer"))
    assert review["reviews"][0]["claim_id"] == "claim_ab12"  # type: ignore[index]
    assert "[claim_ab12]" in scripted_reply(sys_msg("You are the **Synthesizer**"))["answer"]  # type: ignore[index]
