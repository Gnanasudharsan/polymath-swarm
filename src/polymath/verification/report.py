"""The final evidence report (JSON model + Markdown rendering)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from polymath.core.models import Claim, ClaimStatus, Problem, utcnow
from polymath.verification.gate import GateDecision


class ReportedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: Claim
    decision: GateDecision


class EvidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    problem: Problem
    answer: str
    verified: list[ReportedClaim] = Field(default_factory=list)
    conjectures: list[ReportedClaim] = Field(default_factory=list)
    refuted: list[ReportedClaim] = Field(default_factory=list)
    usd: float = 0.0
    tokens: int = 0
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def verified_claim_rate(self) -> float:
        total = len(self.verified) + len(self.conjectures) + len(self.refuted)
        return len(self.verified) / total if total else 0.0


_BADGE = {
    "citation": "📚 citation",
    "computation": "🧮 computation",
    "formal_proof": "✅ Lean-verified",
    "critique": "🔍 critique",
}


def _evidence_lines(rc: ReportedClaim) -> list[str]:
    lines = []
    checks = {c.evidence_id: c for c in rc.decision.checks}
    for e in rc.claim.evidence:
        check = checks.get(e.id)
        if e.kind.value == "critique" and check and check.outcome != "refutes":
            status = ""  # reviews are opinions; only reproduced counterexamples affect the gate
        else:
            status = f" — gate: **{check.outcome}** ({check.detail})" if check else ""
        lines.append(f"  - {_BADGE.get(e.kind.value, e.kind.value)}: {e.summary}{status}")
    return lines or ["  - (no evidence)"]


def render_markdown(report: EvidenceReport) -> str:
    out = [
        "# Polymath Swarm — evidence report",
        "",
        f"**Problem.** {report.problem.statement}",
        "",
        "## Answer",
        "",
        report.answer.strip(),
        "",
        f"## Verified claims ({len(report.verified)})",
        "",
    ]
    for rc in report.verified:
        reused = (
            f" ♻️ _reused from run `{rc.claim.origin_run_id}`_" if rc.claim.origin_run_id else ""
        )
        out += [f"- `{rc.claim.id}` {rc.claim.statement}{reused}", *_evidence_lines(rc)]
    if not report.verified:
        out.append("_No claim passed the verification gate._")
    out += ["", f"## Conjectures — not verified ({len(report.conjectures)})", ""]
    for rc in report.conjectures:
        out += [f"- `{rc.claim.id}` ({rc.claim.status.value}) {rc.claim.statement}",
                *_evidence_lines(rc)]  # fmt: skip
    if report.refuted:
        out += ["", f"## Refuted ({len(report.refuted)})", ""]
        for rc in report.refuted:
            out += [f"- `{rc.claim.id}` ~~{rc.claim.statement}~~", *_evidence_lines(rc)]
    out += [
        "",
        "---",
        f"Run `{report.run_id or '-'}` · {report.tokens} tokens · ${report.usd:.4f} · "
        f"verified-claim rate {report.verified_claim_rate:.0%}",
        "",
    ]
    return "\n".join(out)


def bucket(claims: list[ReportedClaim]) -> dict[str, list[ReportedClaim]]:
    groups: dict[str, list[ReportedClaim]] = {"verified": [], "conjectures": [], "refuted": []}
    for rc in claims:
        if rc.claim.status == ClaimStatus.VERIFIED:
            groups["verified"].append(rc)
        elif rc.claim.status == ClaimStatus.REFUTED:
            groups["refuted"].append(rc)
        else:
            groups["conjectures"].append(rc)
    return groups
