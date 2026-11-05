"""A long-lived Lean REPL in a locked-down container, with Mathlib imported once.

Loading Mathlib costs ~1 minute and ~3 GB; after that each command reuses the saved
environment and checks in well under a second. Commands are serialised with a lock; a
command that exceeds its timeout kills the container, and the next call restarts it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from typing import Any
from uuid import uuid4

from polymath.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_IMAGE = "polymath-lean:v4.35.0"
HEADER = "import Mathlib"


class LeanREPLError(RuntimeError):
    pass


class LeanTimeoutError(LeanREPLError, TimeoutError):
    pass


class LeanREPL:
    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        *,
        memory_mb: int = 6144,
        startup_timeout_s: float = 600.0,
        docker_bin: str | None = None,
    ) -> None:
        self.image = image
        self.memory_mb = memory_mb
        self.startup_timeout_s = startup_timeout_s
        self.docker = docker_bin or shutil.which("docker") or "docker"
        self._proc: asyncio.subprocess.Process | None = None
        self._name: str | None = None
        self._base_env: int | None = None
        self._lock = asyncio.Lock()

    def command(self, name: str) -> list[str]:
        return [
            self.docker, "run", "--rm", "-i",
            "--name", name,
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",  # noqa: S108 - inside the container
            "--memory", f"{self.memory_mb}m",
            "--memory-swap", f"{self.memory_mb}m",
            "--pids-limit", "256",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            self.image,
        ]  # fmt: skip

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        """Start the container and import Mathlib (idempotent)."""
        async with self._lock:
            await self._ensure_started()

    async def _ensure_started(self) -> int:
        if self.running and self._base_env is not None:
            return self._base_env
        await self._shutdown()
        self._name = f"polymath-lean-{uuid4().hex[:12]}"
        self._proc = await asyncio.create_subprocess_exec(
            *self.command(self._name),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=32 * 1024 * 1024,  # REPL replies are single long JSON lines
        )
        log.info("lean.repl.starting", container=self._name)
        reply = await self._send({"cmd": HEADER}, self.startup_timeout_s)
        errors = [m for m in reply.get("messages", []) if m.get("severity") == "error"]
        if errors or "env" not in reply:
            await self._shutdown()
            raise LeanREPLError(f"failed to import Mathlib: {errors or reply}")
        self._base_env = int(reply["env"])
        log.info("lean.repl.ready", container=self._name, env=self._base_env)
        return self._base_env

    async def run(self, body: str, timeout_s: float = 60.0) -> dict[str, Any]:
        """Elaborate ``body`` (no imports) on top of ``import Mathlib``."""
        async with self._lock:
            env = await self._ensure_started()
            return await self._send({"cmd": body, "env": env}, timeout_s)

    async def _send(self, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise LeanREPLError("REPL is not running")
        proc.stdin.write((json.dumps(payload) + "\n\n").encode())
        try:
            await proc.stdin.drain()
            raw = await asyncio.wait_for(self._read_reply(proc.stdout), timeout_s)
        except TimeoutError as exc:
            await self._shutdown()
            raise LeanTimeoutError(f"Lean did not answer within {timeout_s:g}s") from exc
        except (BrokenPipeError, ConnectionResetError) as exc:
            await self._shutdown()
            raise LeanREPLError("Lean REPL exited (out of memory?)") from exc
        try:
            reply: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            await self._shutdown()
            raise LeanREPLError(f"unparsable REPL output: {raw[:500]!r}") from exc
        return reply

    @staticmethod
    async def _read_reply(stdout: asyncio.StreamReader) -> str:
        lines: list[str] = []
        while True:
            line = await stdout.readline()
            if not line:
                if lines:
                    break
                raise LeanREPLError("Lean REPL exited (out of memory?)")
            text = line.decode()
            if not text.strip():
                if lines:
                    break
                continue
            lines.append(text)
        return "".join(lines)

    async def _shutdown(self) -> None:
        proc, name = self._proc, self._name
        self._proc, self._base_env = None, None
        if proc is None:
            return
        if proc.returncode is None and name:
            killer = await asyncio.create_subprocess_exec(
                self.docker, "kill", name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            await killer.wait()
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()

    async def close(self) -> None:
        async with self._lock:
            await self._shutdown()
