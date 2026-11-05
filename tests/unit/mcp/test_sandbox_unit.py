"""Sandbox hardening flags (no Docker needed)."""

from __future__ import annotations

import pytest

from polymath.mcp_servers.sandbox.docker import DockerSandbox, SandboxError, SandboxLimits


def test_command_applies_all_isolation_flags() -> None:
    cmd = DockerSandbox(limits=SandboxLimits(memory_mb=256, pids=32)).command("box", 5)
    joined = " ".join(cmd)
    for flag in (
        "--network none",
        "--read-only",
        "--memory 256m",
        "--memory-swap 256m",
        "--pids-limit 32",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user 65534:65534",
        "--ipc none",
    ):
        assert flag in joined
    assert "/tmp:rw,nosuid,nodev" in joined
    assert cmd[-1] == "5"


async def test_rejects_oversized_program() -> None:
    with pytest.raises(SandboxError, match="longer than"):
        await DockerSandbox().run("x = 1\n" * 50_000)
