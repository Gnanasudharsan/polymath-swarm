"""Compute, Formalizer, Literature and Synthesizer with scripted LLM replies and fake tools."""

from __future__ import annotations

from polymath.agents.base import AgentContext
from polymath.agents.compute import ComputeAgent
from polymath.agents.formalizer import FormalizerAgent, theorem_statement
from polymath.agents.literature import LiteratureAgent
from polymath.agents.synthesizer import SynthesizerAgent, strip_unverified_citations
from polymath.core.config import Settings
from polymath.core.models import AgentRole, Claim, ClaimStatus, Problem, Task, TaskType
from polymath.mcp_servers.literature.models import Paper
from polymath.verification.evidence import ComputationPayload, make_evidence
from tests.agent_fakes import FakeTools, gateway, lean_result

PROBLEM = Problem(statement="What is the sum of the first 10 positive integers?")
CHECK = (
    "total = sum(range(1, 11))\nprint('total =', total)\n"
    "print('POLYMATH_RESULT: PASS' if total == 55 else 'POLYMATH_RESULT: FAIL')"
)


def _task(role: AgentRole, kind: TaskType) -> Task:
    return Task(id=f"t_{role.value}", type=kind, description="do it", assigned_role=role)


async def test_compute_creates_reproducible_evidence_and_repairs(settings: Settings) -> None:
    plan = {"checks": [
        {"claim_id": None, "statement": "1 + ... + 10 = 55", "program": "print('no verdict')"},
    ]}  # fmt: skip
    gw, fake = gateway(settings, [plan, {"program": CHECK}])
    tools = FakeTools()
    res = await ComputeAgent(gw, tools).run(
        _task(AgentRole.COMPUTE, TaskType.COMPUTATION), AgentContext(problem=PROBLEM)
    )
    (claim,) = res.claims
    payload = claim.evidence[0].payload
    assert payload["outcome"] == "pass" and payload["code"] == CHECK
    assert "total = 55" in payload["stdout"]
    assert len(tools.programs) == 2 and len(fake.calls) == 2  # one repair round
    assert claim.status == ClaimStatus.PROPOSED  # the gate, not the agent, verifies


async def test_compute_attaches_to_existing_claim(settings: Settings) -> None:
    existing = Claim(statement="the sum is 55")
    gw, _ = gateway(
        settings,
        [
            {
                "checks": [
                    {"claim_id": existing.id, "statement": existing.statement, "program": CHECK}
                ]
            }
        ],
    )
    res = await ComputeAgent(gw, FakeTools()).run(
        _task(AgentRole.COMPUTE, TaskType.COMPUTATION),
        AgentContext(problem=PROBLEM, claims=[existing]),
    )
    assert res.claims[0].id == existing.id and len(res.claims[0].evidence) == 1


GOOD_LEAN = "theorem sum_ten : (Finset.range 11).sum id = 55 := by\n  decide"


async def test_formalizer_repairs_then_backtranslates(settings: Settings) -> None:
    claim = Claim(statement="The sum of the integers from 0 to 10 is 55")
    replies = [
        {"claim_ids": [claim.id]},
        {
            "theorem_name": "sum_ten",
            "lean_code": "theorem sum_ten : (Finset.range 11).sum id = 55 := by\n  simp",
        },
        {"theorem_name": "sum_ten", "lean_code": GOOD_LEAN},
        {"statement": "The sum of the natural numbers 0 through 10 equals 55."},
        {"equivalent": True, "rationale": "same statement"},
    ]
    gw, fake = gateway(settings, replies)
    tools = FakeTools(lean_results=[lean_result(False), lean_result(True)])
    res = await FormalizerAgent(gw, tools).run(
        _task(AgentRole.FORMALIZER, TaskType.FORMALIZATION),
        AgentContext(problem=PROBLEM, claims=[claim]),
    )
    payload = res.claims[0].evidence[0].payload
    assert payload["lean_verified"] and payload["equivalent"]
    assert payload["lean_code"] == GOOD_LEAN
    assert [n for _, n in tools.lean_calls] == ["sum_ten", "sum_ten"]
    assert "did not accept" in fake.calls[2]["messages"][-1]["content"]
    # back-translation only sees the statement, never the original claim
    backtranslate_input = fake.calls[3]["messages"][-1]["content"]
    assert "decide" not in backtranslate_input and claim.statement not in backtranslate_input


def test_theorem_statement_extraction() -> None:
    assert (
        theorem_statement(GOOD_LEAN, "sum_ten") == "theorem sum_ten : (Finset.range 11).sum id = 55"
    )


ABSTRACT = (
    "The dominant sequence transduction models are based on complex recurrent networks. "
    "We propose a new simple network architecture, the Transformer, based solely on "
    "attention mechanisms, dispensing with recurrence and convolutions entirely."
)


async def test_literature_keeps_only_verbatim_quotes(settings: Settings) -> None:
    paper = Paper(source="arxiv", source_id="1706.03762v7", arxiv_id="1706.03762v7",
                  title="Attention Is All You Need", abstract=ABSTRACT, year=2017)  # fmt: skip
    replies = [
        {"queries": [{"source": "arxiv", "query": "attention is all you need transformer"}]},
        {"summary": "The Transformer was introduced in 2017.", "findings": [
            {"statement": "The Transformer is based solely on attention mechanisms.", "paper": 1,
             "quote": "the Transformer, based solely on attention mechanisms", "confidence": 0.9},
            {"statement": "Transformers beat all RNNs on every task.", "paper": 1,
             "quote": "Transformers beat every recurrent network on all tasks", "confidence": 0.5},
        ]},
    ]  # fmt: skip
    gw, fake = gateway(settings, replies)
    res = await LiteratureAgent(gw, FakeTools(search_hits=[paper])).run(
        _task(AgentRole.LITERATURE, TaskType.LITERATURE_SEARCH), AgentContext(problem=PROBLEM)
    )
    supported, unsupported = res.claims
    assert supported.evidence[0].payload["paper_id"] == "1706.03762v7"
    assert unsupported.evidence == []  # fabricated quote → no evidence
    assert "<paper n=1>" in fake.calls[1]["messages"][-1]["content"]


async def test_synthesizer_gates_claims_and_cites_only_verified(settings: Settings) -> None:
    ok = Claim(statement="1 + ... + 10 = 55").with_evidence(
        make_evidence(
            ComputationPayload(code=CHECK, outcome="pass"), summary="", source=AgentRole.COMPUTE
        )
    )
    hunch = Claim(statement="the answer is also 56")
    answer = f"**55** [{ok.id}], and maybe 56 [{hunch.id}]."
    gw, _ = gateway(settings, [{"answer": answer}])
    res = await SynthesizerAgent(gw, FakeTools()).run(
        _task(AgentRole.SYNTHESIZER, TaskType.SYNTHESIS),
        AgentContext(problem=PROBLEM, claims=[ok, hunch]),
    )
    report = res.data["report"]
    assert [rc["claim"]["id"] for rc in report["verified"]] == [ok.id]
    assert [rc["claim"]["id"] for rc in report["conjectures"]] == [hunch.id]
    assert f"[{ok.id}]" in res.output and hunch.id not in res.output
    assert "## Verified claims (1)" in res.data["markdown"]
    assert "🧮 computation" in res.data["markdown"]


async def test_synthesizer_without_verified_claims_says_so(settings: Settings) -> None:
    gw, fake = gateway(settings, [])
    res = await SynthesizerAgent(gw, FakeTools()).run(
        _task(AgentRole.SYNTHESIZER, TaskType.SYNTHESIS),
        AgentContext(problem=PROBLEM, claims=[Claim(statement="guess")]),
    )
    assert "No claim passed the verification gate" in res.output and fake.calls == []


def test_strip_unverified_citations() -> None:
    text, bad = strip_unverified_citations("a [claim_aa] b [claim_bb]", {"claim_aa"})
    assert text == "a [claim_aa] b [unverified]" and bad == ["claim_bb"]
