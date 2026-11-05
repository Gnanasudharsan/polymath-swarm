"""Verification gate: independently re-checks every piece of evidence before a claim is accepted.

A claim is **verified** only if at least one piece of evidence re-checks successfully:

- ``citation``     — the source is re-fetched and the quoted passage is found in its text;
- ``computation``  — the program is re-run in the sandbox and prints the PASS marker;
- ``formal_proof`` — the Lean file re-verifies (no errors, no sorry, standard axioms) *and* the
  back-translation was judged equivalent to the claim.

A claim is **refuted** if a critique's counterexample program re-runs and still reports one, or a
computation re-runs and prints the FAIL marker. Agents' own verdicts are never trusted alone.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.tools import ToolCallError, Tools
from polymath.core.logging import get_logger
from polymath.core.models import Claim, ClaimStatus, ClaimTransitionError, Evidence
from polymath.mcp_servers.literature.sources import arxiv_base_id
from polymath.verification.evidence import (
    CitationPayload,
    ComputationPayload,
    CritiquePayload,
    FormalProofPayload,
    computation_outcome,
    counterexample_in,
    normalise_text,
    payload_of,
    quote_in_source,
)

log = get_logger(__name__)

CheckOutcome = Literal["supports", "refutes", "inconclusive"]


class EvidenceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    kind: str
    outcome: CheckOutcome
    detail: str


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    status: ClaimStatus
    checks: list[EvidenceCheck] = Field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.status == ClaimStatus.VERIFIED


class VerificationGate:
    def __init__(self, tools: Tools, *, sandbox_timeout_s: float = 60.0) -> None:
        self.tools = tools
        self.sandbox_timeout_s = sandbox_timeout_s

    async def decide(self, claim: Claim) -> GateDecision:
        checks = [await self.check(e) for e in claim.evidence]
        if any(c.outcome == "refutes" for c in checks):
            status = ClaimStatus.REFUTED
        elif any(c.outcome == "supports" for c in checks):
            status = ClaimStatus.VERIFIED
        elif claim.status == ClaimStatus.CHALLENGED:
            status = ClaimStatus.CHALLENGED
        else:
            status = ClaimStatus.PROPOSED
        return GateDecision(claim_id=claim.id, status=status, checks=checks)

    async def apply(self, claim: Claim) -> tuple[Claim, GateDecision]:
        """Return the claim moved to the gate's status (if the lifecycle allows it)."""
        decision = await self.decide(claim)
        if decision.status == claim.status:
            return claim, decision
        try:
            return claim.transition(decision.status), decision
        except ClaimTransitionError:
            # e.g. an agent already marked it verified/refuted: the gate's view is authoritative
            return claim.model_copy(update={"status": decision.status}), decision

    async def check(self, evidence: Evidence) -> EvidenceCheck:
        try:
            payload = payload_of(evidence)
            if isinstance(payload, CitationPayload):
                outcome, detail = await self._citation(payload)
            elif isinstance(payload, ComputationPayload):
                outcome, detail = await self._computation(payload)
            elif isinstance(payload, FormalProofPayload):
                outcome, detail = await self._formal(payload)
            else:
                outcome, detail = await self._critique(payload)
        except (ToolCallError, ValueError) as exc:
            outcome, detail = "inconclusive", f"re-check failed: {exc}"
        log.info("gate.check", kind=evidence.kind.value, outcome=outcome)
        return EvidenceCheck(
            evidence_id=evidence.id, kind=evidence.kind.value, outcome=outcome, detail=detail
        )

    async def _citation(self, p: CitationPayload) -> tuple[CheckOutcome, str]:
        paper = await self.tools.fetch_paper(p.source, p.paper_id)
        if normalise_text(paper.title) != normalise_text(p.title):
            return "inconclusive", f"cited title does not match {p.source}:{p.paper_id}"
        text = f"{paper.title}\n{paper.abstract}"
        if quote_in_source(p.quote, text):
            return "supports", f"quote found in {p.source}:{p.paper_id} ({paper.title})"
        if p.source == "arxiv":
            # Full text: (re-)ingest the paper from its arXiv PDF and search the stored text.
            key = f"arxiv:{arxiv_base_id(p.paper_id)}"
            if not (await self.tools.paper_text(key)).text:
                await self.tools.ingest_arxiv(p.paper_id)
            full = (await self.tools.paper_text(key)).text
            if quote_in_source(p.quote, full):
                return "supports", f"quote found in the full text of {key} ({paper.title})"
        return "inconclusive", f"quote not found in {p.source}:{p.paper_id}"

    async def _computation(self, p: ComputationPayload) -> tuple[CheckOutcome, str]:
        res = await self.tools.run_python(p.code, self.sandbox_timeout_s)
        outcome = computation_outcome(res.stdout, res.exit_code)
        if res.timed_out:
            return "inconclusive", "re-run timed out"
        if outcome == "pass":
            return "supports", "re-run printed PASS"
        if outcome == "fail":
            return "refutes", "re-run printed FAIL"
        return "inconclusive", f"re-run gave no verdict (exit {res.exit_code})"

    async def _formal(self, p: FormalProofPayload) -> tuple[CheckOutcome, str]:
        if not p.equivalent:
            return "inconclusive", "Lean statement not judged equivalent to the claim"
        v = await self.tools.lean_verify(p.lean_code, p.theorem_name)
        if v.verified:
            return "supports", f"Lean re-verified `{p.theorem_name}` ({', '.join(v.axioms)})"
        return "inconclusive", f"Lean re-check failed: {v.reason}"

    async def _critique(self, p: CritiquePayload) -> tuple[CheckOutcome, str]:
        if not (p.verdict == "refute" and p.counterexample_code):
            return "inconclusive", f"critique ({p.verdict}) without a runnable counterexample"
        res = await self.tools.run_python(p.counterexample_code, self.sandbox_timeout_s)
        found = counterexample_in(res.stdout) if res.exit_code == 0 else None
        if found:
            return "refutes", f"counterexample reproduced: {found}"
        return "inconclusive", "counterexample did not reproduce"
