"""Formalizer: claim → Lean 4 theorem + proof, repaired against Lean errors, then a
back-translation check (Lean → English, judged against the original claim)."""

from __future__ import annotations

import asyncio
import re
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
from polymath.agents.lean_auto import automate
from polymath.agents.tools import ToolCallError, Tools
from polymath.core.models import AgentRole, Claim, Evidence, Task
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway
from polymath.mcp_servers.lean.checker import LeanVerification
from polymath.verification.evidence import FormalProofPayload, make_evidence

_THEOREM = re.compile(r"^\s*theorem\s+([A-Za-z_][A-Za-z0-9_'.]*)", re.MULTILINE)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_ids: list[str] = Field(default_factory=list, max_length=2)


class LeanAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theorem_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_']*$")
    lean_code: str = Field(min_length=1)


class BackTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str


class ClaimMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str | None
    rationale: str


class Equivalence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equivalent: bool
    rationale: str


def theorem_statement(lean_code: str, name: str) -> str:
    """The theorem header (everything before ``:=``), which is what back-translation sees."""
    match = re.search(rf"theorem\s+{re.escape(name)}\b(.*?):=", lean_code, re.DOTALL)
    return f"theorem {name}{match.group(1)}".strip() if match else lean_code


def diagnostics_text(v: LeanVerification) -> str:
    lines = [f"line {d.line}: {d.severity}: {d.message}" for d in v.check.diagnostics]
    lines += [f"goal at sorry (line {s.line}): {s.goal}" for s in v.check.sorries]
    return "\n".join(lines[:30]) or v.reason


class FormalizerAgent(BaseAgent):
    role: ClassVar[AgentRole] = AgentRole.FORMALIZER
    prompt_name: ClassVar[str] = "formalizer"

    def __init__(self, gateway: LLMGateway, tools: Tools, *, max_attempts: int = 3) -> None:
        super().__init__(gateway)
        self.toolset = tools
        self.max_attempts = max_attempts

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        usage: list[LLMUsage] = []
        candidates = open_claims(context)
        if not candidates:
            return self.result(task, "No open claims to formalize.", usage)
        brief = task_brief(task, context)
        chosen = await self.ask(
            Selection,
            f"{brief}\n\n## Open claims\n{render_claims(candidates)}\n\n"
            "Pick up to 2 claim ids worth formalizing: prefer the claim that states the main "
            "result in full, then one key lemma. Most important first.",
            usage,
            prompt="formalizer",
        )
        by_id = {c.id: c for c in candidates}
        picked = [by_id[cid] for cid in dict.fromkeys(chosen.claim_ids) if cid in by_id]
        # LLM rounds run concurrently; the Lean REPL serialises the checks themselves.
        done = await asyncio.gather(*(self._formalize(c, candidates, brief, usage) for c in picked))
        claims = [c for pair in done for c in pair[0]]
        notes = [pair[1] for pair in done]
        return self.result(task, "Formalization:\n" + "\n".join(notes), usage, claims=claims)

    async def _formalize(
        self, claim: Claim, candidates: list[Claim], brief: str, usage: list[LLMUsage]
    ) -> tuple[list[Claim], str]:
        history: list[dict[str, str]] = []
        request = f"{brief}\n\n## Claim to formalize\n{claim.statement}"
        attempt: LeanAttempt | None = None
        verification: LeanVerification | None = None
        for _ in range(self.max_attempts):
            attempt = await self.ask(LeanAttempt, request, usage, history=history)
            name = attempt.theorem_name
            if not any(m == name for m in _THEOREM.findall(attempt.lean_code)):
                feedback = f"The file has no `theorem {name}`. Use exactly that name."
            else:
                try:
                    verification = await self.toolset.lean_verify(attempt.lean_code, name)
                except ToolCallError as exc:
                    feedback = f"Lean rejected the input: {exc}"
                    verification = None
                else:
                    if verification.verified:
                        break
                    # Cheap rescue before another model round: Mathlib automation.
                    auto = await automate(self.toolset, attempt.lean_code, name)
                    if auto is not None:
                        attempt = LeanAttempt(theorem_name=name, lean_code=auto)
                        verification = await self.toolset.lean_verify(auto, name)
                        if verification.verified:
                            break
                    feedback = f"Lean did not accept the proof ({verification.reason}):\n" + (
                        diagnostics_text(verification)
                    )
            history += [
                {"role": "user", "content": request},
                {"role": "assistant", "content": attempt.model_dump_json()},
            ]
            request = f"{feedback}\n\nFix the Lean file. Keep the statement faithful to the claim."
        if attempt is None:
            return [claim], f"- {claim.statement}: no attempt"

        statement = theorem_statement(attempt.lean_code, attempt.theorem_name)
        back = await self.ask(BackTranslation, f"```lean\n{statement}\n```", usage,
                              prompt="backtranslate")  # fmt: skip
        judge = await self.ask(
            Equivalence,
            f"## Statement A (claim)\n{claim.statement}\n\n## Statement B (from Lean)\n"
            f"{back.statement}\n\n## Lean source\n```lean\n{statement}\n```",
            usage,
            prompt="equivalence",
        )
        verified = bool(verification and verification.verified)

        def evidence_for(equivalent: bool, rationale: str) -> Evidence:
            payload = FormalProofPayload(
                lean_code=attempt.lean_code,
                theorem_name=attempt.theorem_name,
                lean_verified=verified,
                lean_reason=verification.reason if verification else "not checked",
                back_translation=back.statement,
                equivalent=equivalent,
                equivalence_rationale=rationale,
            )
            status = "proved" if verified else "not proved"
            faithful = "faithful" if equivalent else "NOT faithful"
            return make_evidence(
                payload, summary=f"Lean 4 `{attempt.theorem_name}`: {status}, {faithful}",
                source=self.role,
            )  # fmt: skip

        out = [claim.with_evidence(evidence_for(judge.equivalent, judge.rationale))]
        note = f"- {claim.statement}: {'proved' if verified else 'not proved'}, " + (
            "faithful" if judge.equivalent else "NOT faithful"
        )
        if verified and not judge.equivalent:
            # The proof may establish a *different* open claim: attach it there instead.
            others = [c for c in candidates if c.id != claim.id]
            if others:
                match = await self.ask(
                    ClaimMatch,
                    f"## Proved statement\n{back.statement}\n\n```lean\n{statement}\n```\n\n"
                    f"## Claims\n{render_claims(others)}",
                    usage,
                    prompt="claim_match",
                )
                target = next((c for c in others if c.id == match.claim_id), None)
                if target is not None:
                    out.append(target.with_evidence(evidence_for(True, match.rationale)))
                    note += f"; matches `{target.id}` instead"
        return out, note
