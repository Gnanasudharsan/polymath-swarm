"""A2A Agent Cards for the swarm and for each specialist."""

from __future__ import annotations

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    APIKeySecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)

from polymath import __version__
from polymath.core.models import AgentRole

API_KEY_SCHEME = "polymathApiKey"
SPECIALISTS: tuple[AgentRole, ...] = (
    AgentRole.LITERATURE,
    AgentRole.REASONER,
    AgentRole.COMPUTE,
    AgentRole.FORMALIZER,
    AgentRole.CRITIC,
)

SPECIALIST_SKILLS: dict[AgentRole, tuple[str, str, list[str]]] = {
    AgentRole.LITERATURE: ("literature_search", "Find papers and quote them verbatim (arXiv, "
                           "Semantic Scholar, OpenAlex).", ["literature", "citations"]),
    AgentRole.REASONER: ("reasoning", "Informal mathematical argument with atomic claims.",
                         ["reasoning", "math"]),
    AgentRole.COMPUTE: ("computation", "Compute values exactly and check claims with sandboxed "
                        "programs.", ["computation", "sympy", "python"]),
    AgentRole.FORMALIZER: ("formalization", "State and prove claims in Lean 4 + Mathlib.",
                           ["lean", "formal-verification"]),
    AgentRole.CRITIC: ("critique", "Adversarial review with counterexample searches.",
                       ["critique", "counterexamples"]),
}  # fmt: skip


def _card(name: str, description: str, url: str, skills: list[AgentSkill]) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version=__version__,
        provider=AgentProvider(organization="Polymath Swarm",
                               url="https://github.com/Gnanasudharsan/polymath-swarm"),
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC",
                                             protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/markdown", "application/json"],
        skills=skills,
        security_schemes={API_KEY_SCHEME: SecurityScheme(
            api_key_security_scheme=APIKeySecurityScheme(
                location="header", name="x-api-key",
                description="Polymath API key (POLYMATH_API_KEY)."))},
        security_requirements=[SecurityRequirement(schemes={API_KEY_SCHEME: StringList()})],
    )  # fmt: skip


def swarm_card(base_url: str) -> AgentCard:
    return _card(
        "Polymath Swarm",
        "Verification-first multi-agent swarm for research and mathematics. Every claim in the "
        "answer carries evidence: a verified citation, a reproduced computation or a Lean 4 proof.",
        f"{base_url.rstrip('/')}/a2a",
        [AgentSkill(id="solve", name="Solve with evidence",
                    description="Plan, research, compute, prove, critique and synthesise an "
                                "evidence report (Markdown + JSON).",
                    tags=["research", "mathematics", "verification"],
                    examples=["Prove that n(n+1) is even for every natural number n.",
                              "Compute the sum of the first 100 primes; is it prime?"])],
    )  # fmt: skip


def specialist_card(role: AgentRole, base_url: str) -> AgentCard:
    skill_id, desc, tags = SPECIALIST_SKILLS[role]
    return _card(
        f"Polymath {role.value.capitalize()}",
        f"The Polymath Swarm {role.value} specialist. {desc} Returns its claims; claims from this "
        "agent alone are proposals, not verified results.",
        f"{base_url.rstrip('/')}/agents/{role.value}/a2a",
        [AgentSkill(id=skill_id, name=skill_id.replace("_", " "), description=desc, tags=tags)],
    )
