"""Typed payloads stored in :attr:`Evidence.payload`, one per :class:`EvidenceKind`.

Computation protocol: a check program prints ``POLYMATH_RESULT: PASS`` when the claim holds
and ``POLYMATH_RESULT: FAIL`` otherwise; a counterexample search prints
``POLYMATH_COUNTEREXAMPLE: <details>`` when it finds one. The gate re-runs the program and
reads these markers, so evidence is reproduced rather than trusted.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from polymath.core.models import AgentRole, Evidence, EvidenceKind

PASS_MARKER = "POLYMATH_RESULT: PASS"  # noqa: S105 - a test-result marker, not a secret
FAIL_MARKER = "POLYMATH_RESULT: FAIL"
COUNTEREXAMPLE_MARKER = "POLYMATH_COUNTEREXAMPLE:"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CitationPayload(_Payload):
    # Only sources the gate can re-fetch by id (arXiv id, or DOI / OpenAlex W-id).
    source: Literal["arxiv", "openalex"]
    paper_id: str
    title: str
    url: str | None = None
    quote: str = Field(description="Verbatim passage from the source supporting the claim.")


class ComputationPayload(_Payload):
    code: str
    stdout: str = ""
    exit_code: int | None = None
    outcome: Literal["pass", "fail", "error"] = "error"


class FormalProofPayload(_Payload):
    lean_code: str
    theorem_name: str
    lean_verified: bool
    lean_reason: str = ""
    back_translation: str = ""
    equivalent: bool = False
    equivalence_rationale: str = ""


class CritiquePayload(_Payload):
    verdict: Literal["accept", "challenge", "refute"]
    rationale: str
    counterexample_code: str | None = None
    counterexample_output: str | None = None
    counterexample_found: bool = False


Payload = CitationPayload | ComputationPayload | FormalProofPayload | CritiquePayload
_KIND: dict[type[_Payload], EvidenceKind] = {
    CitationPayload: EvidenceKind.CITATION,
    ComputationPayload: EvidenceKind.COMPUTATION,
    FormalProofPayload: EvidenceKind.FORMAL_PROOF,
    CritiquePayload: EvidenceKind.CRITIQUE,
}


def make_evidence(payload: Payload, *, summary: str, source: AgentRole) -> Evidence:
    return Evidence(
        kind=_KIND[type(payload)],
        summary=summary,
        payload=payload.model_dump(mode="json"),
        reproducible=not isinstance(payload, CritiquePayload) or payload.counterexample_found,
        source_agent=source,
    )


def payload_of(evidence: Evidence) -> Payload:
    model: type[_Payload] = {v: k for k, v in _KIND.items()}[evidence.kind]
    return model.model_validate(evidence.payload)  # type: ignore[return-value]


def computation_outcome(stdout: str, exit_code: int) -> Literal["pass", "fail", "error"]:
    if exit_code != 0:
        return "error"
    lines = [line.strip() for line in stdout.splitlines()]
    if FAIL_MARKER in lines:
        return "fail"
    return "pass" if PASS_MARKER in lines else "error"


def counterexample_in(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.strip().startswith(COUNTEREXAMPLE_MARKER):
            return line.strip().removeprefix(COUNTEREXAMPLE_MARKER).strip() or "(found)"
    return None


_WS = re.compile(r"\s+")
_TEX = re.compile(r"[$\\{}]")


def normalise_text(text: str) -> str:
    """Lower-case, strip TeX punctuation and collapse whitespace for quote matching."""
    return _WS.sub(" ", _TEX.sub("", text.lower())).strip()


def quote_in_source(quote: str, source_text: str, *, min_chars: int = 20) -> bool:
    q = normalise_text(quote).strip(" .\"'…")
    return len(q) >= min_chars and q in normalise_text(source_text)
