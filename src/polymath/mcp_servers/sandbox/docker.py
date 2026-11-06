"""Execute untrusted Python inside a locked-down, throwaway Docker container.

Isolation (all enforced by ``docker run`` flags):
no network · read-only root FS · size-limited ``/tmp`` tmpfs only · memory + swap cap ·
CPU quota · PID limit · all capabilities dropped · ``no-new-privileges`` · uid 65534.
Wall-clock time is enforced twice: inside the container and by the host, which
``docker kill``s the container if it overruns.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from polymath.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_IMAGE = "ghcr.io/gnanasudharsan/polymath-sandbox:latest"
MAX_CODE_CHARS = 100_000


class SandboxLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_mb: int = Field(default=512, ge=32, le=8192)
    cpus: float = Field(default=1.0, gt=0, le=8)
    pids: int = Field(default=64, ge=8, le=1024)
    tmpfs_mb: int = Field(default=64, ge=1, le=1024)
    max_timeout_s: float = Field(default=60.0, gt=0)
    startup_slack_s: float = Field(default=15.0, ge=0)


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    size: int
    content_b64: str


class SandboxResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_s: float
    truncated: bool = False
    artifacts: list[Artifact] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxError(RuntimeError):
    pass


class DockerSandbox:
    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        limits: SandboxLimits | None = None,
        docker_bin: str | None = None,
    ) -> None:
        self.image = image
        self.limits = limits or SandboxLimits()
        self.docker = docker_bin or shutil.which("docker") or "docker"

    def command(self, name: str, timeout_s: float) -> list[str]:
        lim = self.limits
        return [
            self.docker, "run", "--rm", "-i",
            "--name", name,
            "--network", "none",
            "--read-only",
            "--tmpfs", f"/tmp:rw,nosuid,nodev,size={lim.tmpfs_mb}m,mode=1777",  # noqa: S108
            "--memory", f"{lim.memory_mb}m",
            "--memory-swap", f"{lim.memory_mb}m",
            "--cpus", str(lim.cpus),
            "--pids-limit", str(lim.pids),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            "--ipc", "none",
            self.image,
            f"{timeout_s:g}",
        ]  # fmt: skip

    async def run(self, code: str, timeout_s: float = 10.0) -> SandboxResult:
        if len(code) > MAX_CODE_CHARS:
            raise SandboxError(f"program longer than {MAX_CODE_CHARS} characters")
        timeout_s = min(max(timeout_s, 0.1), self.limits.max_timeout_s)
        name = f"polymath-sbx-{uuid4().hex[:12]}"
        proc = await asyncio.create_subprocess_exec(
            *self.command(name, timeout_s),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(code.encode()), timeout_s + self.limits.startup_slack_s
            )
        except TimeoutError:
            await self._kill(name)
            proc.kill()
            await proc.wait()
            log.warning("sandbox.host_timeout", container=name, timeout_s=timeout_s)
            return SandboxResult(
                stdout="",
                stderr="killed by host after exceeding the time limit",
                exit_code=-9,
                timed_out=True,
                duration_s=timeout_s,
            )
        if proc.returncode == 137:  # SIGKILL: almost always the OOM killer
            return SandboxResult(
                stdout="",
                stderr=f"killed: exceeded the {self.limits.memory_mb} MB memory limit",
                exit_code=137,
                timed_out=False,
                duration_s=0.0,
            )
        try:
            return SandboxResult.model_validate(json.loads(out))
        except (json.JSONDecodeError, ValueError) as exc:
            raise SandboxError(
                f"sandbox returned no result (docker exit {proc.returncode}): "
                f"{err.decode(errors='replace')[-2000:]}"
            ) from exc

    async def _kill(self, name: str) -> None:
        killer = await asyncio.create_subprocess_exec(
            self.docker, "kill", name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        await killer.wait()
