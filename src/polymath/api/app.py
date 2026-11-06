"""FastAPI application: create runs, inspect them, approve plans, stream events (SSE)."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from polymath import __version__
from polymath.api.runs import RunBusyError, RunManager, RunNotFoundError
from polymath.api.schemas import Accepted, Created, CreateRun, Decision, RunDetail, RunList
from polymath.core.config import Settings
from polymath.core.models import RunBudget

ManagerFactory = Callable[[], AbstractAsyncContextManager[RunManager]]


def _manager(request: Request) -> RunManager:
    m: RunManager = request.app.state.manager
    return m


# Module level: with postponed annotations FastAPI resolves these names in module globals.
ManagerDep = Annotated[RunManager, Depends(_manager)]


def create_app(
    settings: Settings, manager_factory: ManagerFactory, *, cors_origins: list[str] | None = None
) -> FastAPI:
    api_key = settings.api_key.get_secret_value() if settings.api_key else ""
    if not api_key:
        raise RuntimeError("POLYMATH_API_KEY must be set to serve the API")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with manager_factory() as manager:
            app.state.manager = manager
            yield

    app = FastAPI(title="Polymath Swarm API", version=__version__, lifespan=lifespan)
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"],
                           allow_headers=["*"])  # fmt: skip

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if not x_api_key or not hmac.compare_digest(x_api_key, api_key):
            raise HTTPException(status_code=401, detail="missing or invalid API key")

    auth = Depends(require_key)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/runs", status_code=201, dependencies=[auth])
    async def create_run(body: CreateRun, m: ManagerDep) -> Created:
        budget = settings.budget.model_copy(update={"max_usd": body.max_usd})
        run_id = await m.start(body.problem, RunBudget.model_validate(budget.model_dump()),
                               body.require_approval)  # fmt: skip
        return Created(run_id=run_id)

    @app.get("/runs", dependencies=[auth])
    async def list_runs(m: ManagerDep, limit: int = 50) -> RunList:
        return RunList(runs=await m.list(max(1, min(limit, 200))))

    @app.get("/runs/{run_id}", dependencies=[auth])
    async def get_run(run_id: str, m: ManagerDep) -> RunDetail:
        try:
            return await m.detail(run_id)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="run not found") from None

    @app.get("/runs/{run_id}/stream", dependencies=[auth])
    async def stream(run_id: str, m: ManagerDep) -> EventSourceResponse:
        try:
            await m.detail(run_id)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="run not found") from None
        return EventSourceResponse(m.stream(run_id), ping=15)

    @app.post("/runs/{run_id}/approve", status_code=202, dependencies=[auth])
    async def approve(run_id: str, body: Decision, m: ManagerDep) -> Accepted:
        try:
            await m.decide(run_id, body.approved, body.feedback)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="run not found") from None
        except RunBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return Accepted(run_id=run_id, status="resuming")

    @app.post("/runs/{run_id}/resume", status_code=202, dependencies=[auth])
    async def resume(run_id: str, m: ManagerDep) -> Accepted:
        """Continue a run interrupted by a crash or restart (from its last checkpoint)."""
        try:
            await m.resume(run_id)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="run not found") from None
        except RunBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return Accepted(run_id=run_id, status="resuming")

    return app
