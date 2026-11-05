"""Compute: write check programs, run them in the sandbox, attach reproducible evidence."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.base import (
    AgentContext,
    AgentResult,
    BaseAgent,
    open_claims,
    render_claims,
    task_brief,
)
from polymath.agents.tools import ToolCallError, Tools
from polymath.core.models import AgentRole, Claim, Task
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway
from polymath.verification.evidence import ComputationPayload, computation_outcome, make_evidence


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str | None = Field(default=None, description="existing claim id, or null for new")
    statement: str = Field(description="the claim being checked, stated precisely")
    program: str = Field(min_length=1, description="Python 3.12 program following the protocol")


class CheckPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[Check] = Field(min_length=1, max_length=5)


class Exploration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: str = Field(min_length=1, description="prints POLYMATH_VALUE: name = value lines")


_IMPERATIVE = ("compute ", "determine ", "find ", "calculate ", "evaluate ", "show ", "prove ")


def is_assertion(statement: str) -> bool:
    """Reject 'claims' that merely restate the task as an instruction."""
    return not statement.strip().lower().startswith(_IMPERATIVE)


class FixedProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: str = Field(min_length=1)


class ComputeAgent(BaseAgent):
    role: ClassVar[AgentRole] = AgentRole.COMPUTE
    prompt_name: ClassVar[str] = "compute"

    def __init__(self, gateway: LLMGateway, tools: Tools, *, max_fixes: int = 1) -> None:
        super().__init__(gateway)
        self.toolset = tools
        self.max_fixes = max_fixes

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        usage: list[LLMUsage] = []
        candidates = open_claims(context)
        brief = f"{task_brief(task, context)}\n\n## Open claims\n{render_claims(candidates)}"
        # Explore first, then assert: claims are stated from computed values, not guessed.
        explored = await self._explore(task, context, usage)
        plan = await self.ask(
            CheckPlan, f"{brief}\n\n## Computed values\n{explored}", usage, prompt="compute"
        )
        by_id = {c.id: c for c in context.claims}

        claims: list[Claim] = []
        lines: list[str] = []
        for check in plan.checks:
            if check.claim_id is None and not is_assertion(check.statement):
                lines.append(f"- dropped non-assertion: {check.statement}")
                continue
            program, res = check.program, None
            for attempt in range(self.max_fixes + 1):
                try:
                    res = await self.toolset.run_python(program, 60.0)
                except ToolCallError as exc:
                    lines.append(f"- {check.statement}: sandbox error {exc}")
                    break
                if (
                    computation_outcome(res.stdout, res.exit_code) != "error"
                    or attempt == self.max_fixes
                ):
                    break
                fix = await self.ask(
                    FixedProgram,
                    f"{brief}\n\nThis program for `{check.statement}` failed to give a verdict.\n"
                    f"```python\n{program}\n```\nexit={res.exit_code}\nstdout:\n{res.stdout[-2000:]}"
                    f"\nstderr:\n{res.stderr[-2000:]}\nReturn a corrected program.",
                    usage,
                )
                program = fix.program
            if res is None:
                continue
            outcome = computation_outcome(res.stdout, res.exit_code)
            payload = ComputationPayload(
                code=program, stdout=res.stdout[-4000:], exit_code=res.exit_code, outcome=outcome
            )
            evidence = make_evidence(payload, summary=f"sandbox check: {outcome}", source=self.role)
            base = by_id.get(check.claim_id or "")
            claim = base or Claim(
                statement=check.statement, confidence=0.5, proposed_by=self.role, task_id=task.id
            )
            claims.append(claim.with_evidence(evidence))
            lines.append(f"- [{outcome}] {check.statement}")
        output = f"Computed values:\n{explored}\n\nComputational checks:\n" + "\n".join(lines)
        return self.result(task, output, usage, claims=claims)

    async def _explore(self, task: Task, context: AgentContext, usage: list[LLMUsage]) -> str:
        explore = await self.ask(
            Exploration, task_brief(task, context), usage, prompt="compute_explore"
        )
        try:
            res = await self.toolset.run_python(explore.program, 60.0)
        except ToolCallError as exc:
            return f"(exploration failed: {exc})"
        values = [ln for ln in res.stdout.splitlines() if ln.startswith("POLYMATH_VALUE:")]
        body = "\n".join(values) or res.stdout[-3000:]
        return body if res.exit_code == 0 else f"{body}\n(stderr: {res.stderr[-1500:]})"
