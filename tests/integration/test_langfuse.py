"""Traces reach self-hosted Langfuse (`docker compose --profile observability up -d`)."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.observability]

HOST = os.environ.get("POLYMATH_TEST_LANGFUSE_HOST", "http://localhost:3000")
AUTH = ("pk-lf-polymath-local", "sk-lf-polymath-local")


async def test_run_is_traced_in_langfuse() -> None:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            (await c.get(f"{HOST}/api/public/health")).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Langfuse is not running (docker compose --profile observability up -d)")
    run_id = f"run_lf_{uuid.uuid4().hex[:8]}"
    # The subprocess must not inherit local settings (e.g. the spend ledger) or reload .env.
    env = {k: v for k, v in os.environ.items() if not k.startswith("POLYMATH_")}
    env |= {"POLYMATH_NO_DOTENV": "1", "LANGFUSE_HOST": HOST, "LANGFUSE_PUBLIC_KEY": AUTH[0],
            "LANGFUSE_SECRET_KEY": AUTH[1]}  # fmt: skip
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.integration.langfuse_probe", run_id, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    out, _ = await asyncio.wait_for(proc.communicate(), 120)
    assert proc.returncode == 0, out.decode()[-2000:]

    # Langfuse v4 is events-only: read back through the v2 observations API.
    async with httpx.AsyncClient(base_url=HOST, auth=AUTH, timeout=10) as client:
        roots: list[dict] = []  # type: ignore[type-arg]
        for _ in range(60):  # ingestion is asynchronous (worker → ClickHouse)
            resp = await client.get("/api/public/v2/observations", params={"sessionId": run_id})
            roots = [o for o in resp.json().get("data", []) if o["name"] == "swarm.run"]
            if roots:
                break
            await asyncio.sleep(2)
        assert roots, f"no Langfuse trace for session {run_id}"
        obs: list[dict] = []  # type: ignore[type-arg]
        for _ in range(30):
            resp = await client.get(
                "/api/public/v2/observations",
                params={"traceId": roots[0]["traceId"], "limit": 100,
                        "fields": "core,basic,usage,model"},
            )  # fmt: skip
            obs = resp.json().get("data", [])
            if sum(o["type"] == "GENERATION" for o in obs) >= 3:
                break
            await asyncio.sleep(2)
    names = {o["name"] for o in obs}
    assert {"swarm.run", "agent.reasoner", "agent.synthesizer"} <= names, names
    generations = [o for o in obs if o["type"] == "GENERATION"]
    assert len(generations) == 3  # a, b and synth each made one LLM call
    g = generations[0]
    assert g["model"] == "claude-haiku-5-5"
    assert g["usageDetails"]["total"] == 150 and g["totalCost"] > 0
