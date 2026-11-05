"""Docker-backed sandbox tests, including escape attempts.

Needs the image: docker build -f docker/sandbox.Dockerfile -t polymath-sandbox:latest docker/sandbox
"""

from __future__ import annotations

import base64
import time

import pytest

from polymath.mcp_servers.client import MCPToolbox
from polymath.mcp_servers.sandbox import build_server
from polymath.mcp_servers.sandbox.docker import DockerSandbox, SandboxLimits

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def box() -> DockerSandbox:
    return DockerSandbox(limits=SandboxLimits(memory_mb=128, startup_slack_s=20))


async def test_runs_numeric_code(box: DockerSandbox) -> None:
    res = await box.run(
        "import numpy as np, sympy as sp\nprint(np.linalg.det([[2,0],[0,3]]))\n"
        "print(sp.factorint(360))"
    )
    assert res.ok, res.stderr
    assert res.stdout.splitlines() == ["6.0", "{2: 3, 3: 2, 5: 1}"]


async def test_returns_artifacts(box: DockerSandbox) -> None:
    res = await box.run("open('/tmp/artifacts/out.txt','w').write('42')")
    assert res.ok
    assert [a.name for a in res.artifacts] == ["out.txt"]
    assert base64.b64decode(res.artifacts[0].content_b64) == b"42"


async def test_nonzero_exit_and_stderr(box: DockerSandbox) -> None:
    res = await box.run("raise SystemExit('boom')")
    assert res.exit_code == 1 and "boom" in res.stderr


# ----------------------------------------------------------------------- escape attempts


async def test_network_is_unreachable(box: DockerSandbox) -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except OSError as e:\n"
        "    print('BLOCKED', type(e).__name__)\n"
        "try:\n"
        "    socket.getaddrinfo('example.com', 80)\n"
        "    print('RESOLVED')\n"
        "except OSError:\n"
        "    print('NO_DNS')\n"
    )
    res = await box.run(code)
    assert "CONNECTED" not in res.stdout and "RESOLVED" not in res.stdout
    assert "BLOCKED" in res.stdout and "NO_DNS" in res.stdout


@pytest.mark.parametrize("path", ["/etc/pwned", "/opt/sandbox/runner.py", "/home/x", "/usr/x"])
async def test_cannot_write_outside_tmp(box: DockerSandbox, path: str) -> None:
    code = (
        "try:\n"
        f"    open({path!r}, 'w').write('x')\n"
        "    print('WROTE')\n"
        "except OSError as e:\n"
        "    print('DENIED', e.errno)\n"
    )
    res = await box.run(code)
    assert "WROTE" not in res.stdout
    assert "DENIED" in res.stdout


async def test_runs_as_unprivileged_user(box: DockerSandbox) -> None:
    res = await box.run("import os; print(os.getuid(), os.getgid())")
    assert res.stdout.strip() == "65534 65534"


async def test_infinite_loop_is_killed(box: DockerSandbox) -> None:
    started = time.monotonic()
    res = await box.run("while True:\n    pass", timeout_s=2)
    assert res.timed_out and not res.ok
    assert time.monotonic() - started < 2 + 20


async def test_memory_bomb_is_killed(box: DockerSandbox) -> None:
    res = await box.run("x = bytearray(1024 * 1024 * 1024)\nprint('ALLOCATED')", timeout_s=10)
    assert "ALLOCATED" not in res.stdout
    assert not res.ok


async def test_fork_bomb_is_contained(box: DockerSandbox) -> None:
    code = (
        "import os\n"
        "n = 0\n"
        "try:\n"
        "    for _ in range(500):\n"
        "        if os.fork() == 0:\n"
        "            import time; time.sleep(30); os._exit(0)\n"
        "        n += 1\n"
        "except OSError:\n"
        "    pass\n"
        "print('FORKED', n)\n"
    )
    res = await box.run(code, timeout_s=5)
    forked = int(res.stdout.split()[1]) if res.stdout.startswith("FORKED") else 0
    assert forked < 64  # pids-limit holds


async def test_via_mcp_toolbox(box: DockerSandbox) -> None:
    async with MCPToolbox({"sandbox": build_server(box)}) as tb:
        res = await tb.call("sandbox.run_python", {"code": "print(sum(range(10)))"})
        assert not res.is_error
        assert res.structured is not None and res.structured["stdout"] == "45\n"
