"""Deterministic offline LLM for UI development and end-to-end tests (``--mock-llm``).

It replays one scripted *computation* run regardless of the problem text: plan
(compute → critique → synthesize), an exploration program and a PASS/FAIL check for "the sum of
the first 100 primes is 24133, which is prime", an accepting critique, and a synthesis that cites
the verified claim. Programs still run in the real sandbox and the verification gate still
re-runs them, so the UI shows genuine verification — only the model is fake. Costs nothing.
"""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace
from typing import Any

_CLAIM_ID = re.compile(r"\[(claim_[0-9a-f]+)\]")

PLAN = {
    "problem_type": "computation",
    "rationale": "A value question: compute it exactly, let the critic review, then synthesise.",
    "tasks": [
        {"id": "compute", "type": "computation", "deps": [],
         "description": "Compute the requested value exactly and check it with a program."},
        {"id": "critique", "type": "critique", "deps": ["compute"],
         "description": "Review the computed claims; search for counterexamples."},
        {"id": "synthesize", "type": "synthesis", "deps": ["compute", "critique"],
         "description": "Write the final answer from verified claims only."},
    ],
}  # fmt: skip

EXPLORE = (
    "from sympy import prime, isprime\n"
    "s = sum(prime(i) for i in range(1, 101))\n"
    "print('POLYMATH_VALUE: sum_first_100_primes =', s)\n"
    "print('POLYMATH_VALUE: is_prime =', isprime(s))\n"
)
CHECK = (
    "from sympy import prime, isprime\n"
    "s = sum(prime(i) for i in range(1, 101))\n"
    "print('sum =', s, 'prime =', isprime(s))\n"
    "print('POLYMATH_RESULT: PASS' if s == 24133 and isprime(s) else 'POLYMATH_RESULT: FAIL')\n"
)
CLAIM = "The sum of the first 100 prime numbers is 24133, and 24133 is a prime number."


def _system_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")


def _last_user(messages: list[dict[str, Any]]) -> str:
    users = [m for m in messages if m.get("role") == "user"]
    return str(users[-1].get("content", "")) if users else ""


def scripted_reply(messages: list[dict[str, Any]]) -> dict[str, Any] | str:
    system, user = _system_text(messages), _last_user(messages)
    ids = _CLAIM_ID.findall(user)
    if "Supervisor / Planner" in system:
        return PLAN
    if "First, compute what the task asks for" in system:
        return {"program": EXPLORE}
    if "establish or test claims" in system:
        return {"checks": [{"claim_id": None, "statement": CLAIM, "program": CHECK}]}
    if "adversarial reviewer" in system:
        return {"reviews": [{"claim_id": cid, "verdict": "accept",
                             "rationale": "The program recomputes the sum exactly with sympy."}
                            for cid in ids]}  # fmt: skip
    if "Synthesizer" in system:
        cite = f" [{ids[0]}]" if ids else ""
        return {
            "answer": (
                f"The sum of the first 100 primes is $\\boxed{{24133}}$, and it is prime.{cite}\n\n"
                "With $p_k$ the $k$-th prime, $\\sum_{k=1}^{100} p_k = 24133$, recomputed exactly "
                f"in the sandbox and re-run by the verification gate.{cite}"
            )
        }
    if "Reasoner" in system:
        return {"reasoning": "Delegated to computation.", "answer": "See computation.",
                "claims": []}  # fmt: skip
    return "{}"  # other agents are not part of the scripted run


class ScriptedLLM:
    """Async stand-in for ``litellm.acompletion`` (same call shape as the gateway uses)."""

    def __init__(self, delay_s: float = 0.4) -> None:
        self.delay_s = delay_s  # small pause so the live UI visibly animates

    async def __call__(self, **kwargs: Any) -> Any:
        await asyncio.sleep(self.delay_s)
        messages: list[dict[str, Any]] = kwargs.get("messages", [])
        reply = scripted_reply(messages)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        prompt_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4
        return SimpleNamespace(
            model=f"mock/{kwargs.get('model', 'model')}",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content, role="assistant"),
                                     finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=len(content) // 4),
        )  # fmt: skip
