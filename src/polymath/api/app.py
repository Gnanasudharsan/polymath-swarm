"""FastAPI application: create runs, inspect them, approve plans, stream events (SSE)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from polymath import __version__
from polymath.a2a.server import mount_a2a
from polymath.api.auth import KeyRing, Principal
from polymath.api.ratelimit import RateLimitMiddleware, build_limiters
from polymath.api.runs import RunBusyError, RunManager, RunNotFoundError
from polymath.api.schemas import Accepted, Created, CreateRun, Decision, RunDetail, RunList
from polymath.core.config import Settings
from polymath.core.models import RunBudget
from polymath.graph.runner import SwarmRunner

ManagerFactory = Callable[[], AbstractAsyncContextManager[RunManager]]


def _manager(request: Request) -> RunManager:
    m: RunManager = request.app.state.manager
    return m


def _principal(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> Principal:
    keys: KeyRing = request.app.state.keys
    who = keys.authenticate(x_api_key)
    if who is None:
        raise HTTPException(status_code=401, detail="missing or invalid API key")
    return who


# Module level: with postponed annotations FastAPI resolves these names in module globals.
ManagerDep = Annotated[RunManager, Depends(_manager)]
UserDep = Annotated[Principal, Depends(_principal)]


async def _visible(m: RunManager, run_id: str, who: Principal) -> None:
    """404 for unknown runs *and* for other users' runs (no probing for run ids)."""
    try:
        owner = await m.owner_of(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None
    if not who.can_see(owner):
        raise HTTPException(status_code=404, detail="run not found")


def create_app(
    settings: Settings, manager_factory: ManagerFactory, *, cors_origins: list[str] | None = None
) -> FastAPI:
    keys = KeyRing.from_settings(settings)
    if not keys:
        raise RuntimeError("set POLYMATH_API_KEY or POLYMATH_API_USERS to serve the API")
    writes, reads, redis = build_limiters(
        backend=settings.rate_limit_backend, redis_url=settings.redis_url,
        writes_per_minute=settings.api_writes_per_minute,
        reads_per_minute=settings.api_reads_per_minute,
    )  # fmt: skip

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            async with manager_factory() as manager:
                app.state.manager = manager
                holder["runner"] = manager.runner
                yield
        finally:
            if redis is not None:
                await redis.aclose()

    app = FastAPI(title="Polymath Swarm API", version=__version__, lifespan=lifespan)
    app.state.keys = keys
    holder: dict[str, SwarmRunner] = {}
    # A2A: the swarm and each specialist as agents (cards public, JSON-RPC needs the key).
    mount_a2a(
        app,
        lambda: holder["runner"],
        base_url=settings.public_url,
        budget=RunBudget.model_validate(settings.budget.model_dump()),
        keys=keys,
    )
    app.add_middleware(RateLimitMiddleware, writes=writes, reads=reads)
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"],
                           allow_headers=["*"])  # fmt: skip

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/me")
    async def me(who: UserDep) -> Principal:
        return who

    @app.post("/runs", status_code=201)
    async def create_run(body: CreateRun, m: ManagerDep, who: UserDep) -> Created:
        budget = settings.budget.model_copy(update={"max_usd": body.max_usd})
        run_id = await m.start(body.problem, RunBudget.model_validate(budget.model_dump()),
                               body.require_approval, owner=who.user)  # fmt: skip
        return Created(run_id=run_id)

    @app.get("/runs")
    async def list_runs(m: ManagerDep, who: UserDep, limit: int = 50) -> RunList:
        owner = None if who.admin else who.user
        return RunList(runs=await m.list(max(1, min(limit, 200)), owner=owner))

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str, m: ManagerDep, who: UserDep) -> RunDetail:
        await _visible(m, run_id, who)
        try:
            return await m.detail(run_id)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="run not found") from None

    @app.get("/runs/{run_id}/stream")
    async def stream(run_id: str, m: ManagerDep, who: UserDep) -> EventSourceResponse:
        await _visible(m, run_id, who)
        return EventSourceResponse(m.stream(run_id), ping=15)

    @app.post("/runs/{run_id}/approve", status_code=202)
    async def approve(run_id: str, body: Decision, m: ManagerDep, who: UserDep) -> Accepted:
        await _visible(m, run_id, who)
        try:
            await m.decide(run_id, body.approved, body.feedback)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="run not found") from None
        except RunBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return Accepted(run_id=run_id, status="resuming")

    @app.post("/runs/{run_id}/resume", status_code=202)
    async def resume(run_id: str, m: ManagerDep, who: UserDep) -> Accepted:
        """Continue a run interrupted by a crash or restart (from its last checkpoint)."""
        await _visible(m, run_id, who)
        try:
            await m.resume(run_id)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="run not found") from None
        except RunBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return Accepted(run_id=run_id, status="resuming")

    return app
