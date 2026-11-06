"""HTTP request/response models (mirrored in frontend/src/lib/types.ts)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from polymath.core.models import Claim, TaskStatus
from polymath.graph.state import RunStatus


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRun(_Model):
    problem: str = Field(min_length=1, max_length=8000)
    max_usd: float = Field(default=0.5, gt=0, le=10)
    require_approval: bool = False


class Created(_Model):
    run_id: str


class Decision(_Model):
    approved: bool
    feedback: str | None = Field(default=None, max_length=4000)


class Accepted(_Model):
    run_id: str
    status: str


class RunSummary(_Model):
    run_id: str
    problem: str
    status: RunStatus | None
    created_at: datetime


class RunList(_Model):
    runs: list[RunSummary]


class TaskInfo(_Model):
    id: str
    type: str
    description: str
    deps: list[str]
    assigned_role: str


class UsageOut(_Model):
    tokens: int = 0
    usd: float = 0.0


class RunDetail(_Model):
    run_id: str
    status: RunStatus | None
    stop_reason: str = ""
    problem: str
    tasks: list[TaskInfo] = Field(default_factory=list)
    task_status: dict[str, TaskStatus] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    usage: UsageOut = Field(default_factory=UsageOut)
    max_usd: float | None = None
    awaiting_approval: bool = False
    answer: str = ""
    report_markdown: str = ""
    report: dict[str, Any] | None = None
    finished: bool = False
