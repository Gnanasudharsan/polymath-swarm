"""Merging claim versions produced by different agents into one authoritative record."""

from __future__ import annotations

from polymath.core.models import Claim, ClaimStatus

# Higher wins. Refuted beats verified: a reproduced counterexample overrides any proof attempt.
_RANK = {
    ClaimStatus.PROPOSED: 0,
    ClaimStatus.CHALLENGED: 1,
    ClaimStatus.VERIFIED: 2,
    ClaimStatus.REFUTED: 3,
}


def merge_claim(old: Claim, new: Claim) -> Claim:
    status = new.status if _RANK[new.status] >= _RANK[old.status] else old.status
    seen = {e.id for e in old.evidence}
    evidence = [*old.evidence, *(e for e in new.evidence if e.id not in seen)]
    return old.model_copy(
        update={"status": status, "evidence": evidence, "confidence": new.confidence}
    )


def merge_claims(left: dict[str, Claim] | None, right: dict[str, Claim] | None) -> dict[str, Claim]:
    merged = dict(left or {})
    for cid, claim in (right or {}).items():
        merged[cid] = merge_claim(merged[cid], claim) if cid in merged else claim
    return merged


def by_status(claims: dict[str, Claim], status: ClaimStatus) -> list[Claim]:
    return [c for c in claims.values() if c.status == status]
