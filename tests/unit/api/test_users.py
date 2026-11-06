"""Named API users: keys stored as hashes, each user sees only their own runs, admins see all."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from polymath.api.app import create_app
from polymath.api.auth import KeyRing, Principal, hash_key, new_key
from polymath.api.ratelimit import RedisSlidingWindowLimiter
from polymath.api.runs import RunManager
from polymath.blackboard import Blackboard, InMemoryEventStore
from polymath.core.config import Settings
from polymath.graph.builder import compile_graph
from polymath.graph.checkpointer import memory_checkpointer
from polymath.graph.runner import SwarmRunner
from tests.swarm_fakes import FakeExecutor, FixedPlanner, diamond, make_factory

ALICE, BOB, ROOT = new_key(), new_key(), new_key()
H = {"alice": {"x-api-key": ALICE}, "bob": {"x-api-key": BOB}, "root": {"x-api-key": ROOT}}


def _settings() -> Settings:
    users = {"alice": hash_key(ALICE), "bob": hash_key(BOB), "root": hash_key(ROOT)}
    return Settings(_env_file=None, api_users=users, api_admins=["root"])  # type: ignore[call-arg]


@pytest.fixture
def client() -> Iterator[TestClient]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[RunManager]:
        bb = Blackboard(InMemoryEventStore())
        ctx = make_factory(FixedPlanner(diamond()), FakeExecutor(), bb)
        runner = SwarmRunner(compile_graph(memory_checkpointer()), ctx, bb)
        yield RunManager(runner, bb)

    with TestClient(create_app(_settings(), factory)) as c:
        yield c


def _finished(client: TestClient, run_id: str, who: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if client.get(f"/runs/{run_id}", headers=H[who]).json().get("finished"):
            return
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_keyring_hashes_and_legacy_key() -> None:
    s = Settings(_env_file=None, api_key="old", api_users={"alice": hash_key("a")})  # type: ignore[call-arg]
    ring = KeyRing.from_settings(s)
    assert ring.users == ["admin", "alice"]
    assert ring.authenticate("old") == Principal(user="admin", admin=True)
    assert ring.authenticate("a") == Principal(user="alice", admin=False)
    assert ring.authenticate("nope") is None and ring.authenticate(None) is None
    with pytest.raises(ValueError, match="sha256"):
        KeyRing({"eve": "plaintext-key"}, set())
    assert hash_key("a") != hash_key("b") and new_key() != new_key()


def test_server_refuses_to_start_without_any_key() -> None:
    with pytest.raises(RuntimeError, match="POLYMATH_API_USERS"):
        create_app(Settings(_env_file=None), lambda: None)  # type: ignore[call-arg,arg-type,return-value]


def test_me(client: TestClient) -> None:
    assert client.get("/me", headers=H["alice"]).json() == {"user": "alice", "admin": False}
    assert client.get("/me", headers=H["root"]).json() == {"user": "root", "admin": True}
    assert client.get("/me").status_code == 401


def test_users_see_only_their_own_runs_and_admins_see_all(client: TestClient) -> None:
    rid = client.post("/runs", json={"problem": "alice's"}, headers=H["alice"]).json()["run_id"]
    bob_rid = client.post("/runs", json={"problem": "bob's"}, headers=H["bob"]).json()["run_id"]
    _finished(client, rid, "alice")
    _finished(client, bob_rid, "bob")

    def ids(who: str) -> set[str]:
        return {r["run_id"] for r in client.get("/runs", headers=H[who]).json()["runs"]}

    assert ids("alice") == {rid} and ids("bob") == {bob_rid} and ids("root") == {rid, bob_rid}
    # Another user's run looks exactly like a run that does not exist.
    for method, path, body in [
        ("get", f"/runs/{rid}", None),
        ("get", f"/runs/{rid}/stream", None),
        ("post", f"/runs/{rid}/approve", {"approved": True}),
        ("post", f"/runs/{rid}/resume", None),
    ]:
        r = client.request(method, path, json=body, headers=H["bob"])
        assert r.status_code == 404, (path, r.status_code)
        assert r.json() == client.request(method, path.replace(rid, "run_missing"), json=body,
                                          headers=H["bob"]).json()  # fmt: skip
    assert client.get(f"/runs/{rid}", headers=H["root"]).json()["finished"]
    assert client.post(f"/runs/{rid}/resume", headers=H["alice"]).status_code == 409


def test_runs_without_an_owner_are_admin_only() -> None:
    assert Principal(user="root", admin=True).can_see(None)
    assert not Principal(user="alice").can_see(None)
    assert not Principal(user="alice").can_see("bob")


async def test_redis_limiter_fails_open_when_redis_is_down() -> None:
    redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    try:
        lim = RedisSlidingWindowLimiter(redis, "t", limit=1)
        assert await lim.check("a") is None and await lim.check("a") is None
    finally:
        await redis.aclose()
