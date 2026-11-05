# ADR-0006: Specialists, claim lifecycle and the verification gate

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

Phase 4 turns the orchestrator into a verification-first swarm: six specialists, a claim lifecycle
shared across tasks, a critique loop, Lean back-translation, and a gate that decides what the final
answer may state. LLM output must never be accepted on the model's own word.

## Decision

**Code drives tools; LLMs produce artifacts.** No free-form function-calling loops. Each agent asks
for one structured artifact (`complete_structured`), and the agent's code runs it through MCP tools
(`agents/tools.py`, `MCPTools` over `MCPToolbox`):

| Agent | LLM produces | Code does | Evidence |
|---|---|---|---|
| Literature | search queries, then findings with verbatim quotes | searches arXiv/OpenAlex/S2, keeps a finding's evidence only if the quote is found in the abstract and the paper is re-fetchable (arXiv id / DOI / OpenAlex id) | `citation` |
| Reasoner | argument + atomic claims | — | none (proposals) |
| Compute | check programs (protocol below) | runs them in the sandbox, one repair round | `computation` |
| Formalizer | Lean theorem + proof; then back-translation; then an equivalence judgement | `lean.verify_proof`, up to 3 repair rounds with diagnostics/goals; back-translation sees only the theorem header | `formal_proof` |
| Critic | verdict per claim + counterexample search | runs the search; `refute` is downgraded to `challenge` unless a counterexample is printed | `critique` |
| Synthesizer | answer citing `[claim_id]`s | runs the gate first; strips citations of unverified claims | report |

Prompts are versioned files (`agents/prompts/*.v1.md`). Retrieved paper text is wrapped in `<paper>`
tags and declared untrusted in the prompt.

**Computation protocol.** Programs print `POLYMATH_RESULT: PASS|FAIL`; counterexample searches print
`POLYMATH_COUNTEREXAMPLE: ...`. The verdict comes from the computation, never from the model's say-so.

**Verification gate** (`verification/gate.py`) re-checks every piece of evidence independently:
re-fetch the paper and match the quote (whitespace/TeX-insensitive); re-run the program; re-verify
the Lean proof *and* require the back-translation to be judged equivalent; re-run the
counterexample. Any reproduced refutation → `refuted` (even if other evidence supports the claim);
else any supporting check → `verified`; else the claim remains a conjecture.

**Claims store.** `SwarmState.claims` is merged with `merge_claim`: evidence is unioned, status takes
the higher rank (proposed < challenged < verified < refuted). Every task sees the current claims.

**Critique loop.** Before synthesis, if refuted/challenged claims appear that have not been handled,
`dispatch` inserts `revise_rN → critique_rN` into the plan and makes synthesis depend on it, up to
`max_revision_rounds` (2). Revision tasks are `optional`: near the budget ceiling, optional work is
skipped (recorded as a successful no-op) instead of failing the run.

**Adaptive team.** After the planner's plan is validated, `ensure_team()` adds any specialist the
problem type requires (proof → reasoning + formalization + critique; computation → computation +
critique; literature → literature search; mixed → reasoning + critique). Checkers depend on all
producers.

**Report.** The Synthesizer emits an `EvidenceReport` (JSON) and Markdown: answer, verified claims
with evidence badges and gate outcomes, conjectures, refuted claims, cost and the verified-claim rate.

**Models and spend.** `POLYMATH_MODEL_PROFILE` selects `anthropic` (default, per ADR-0001) or `openai`
(gpt-5 for the Formalizer, gpt-5-mini elsewhere, gpt-5-nano degraded, `reasoning_effort=low`). An
optional on-disk spend ledger (`POLYMATH_SPEND_LEDGER` + `POLYMATH_SPEND_CAP_USD`) enforces a hard
cap across runs and processes.

## Consequences

- Behaviour is predictable and unit-testable with scripted LLM replies and a fake toolset; the real
  tools are exercised in integration tests.
- The gate costs extra tool time (re-running programs, re-checking Lean), not extra LLM tokens.
- Citation verification is limited to titles/abstracts until Phase 5 ingests full text.
- The equivalence judgement is itself an LLM call. It can only *block* a proof (a proof is accepted
  only if Lean verifies and the judge says equivalent), so a judge error makes the gate stricter, not
  looser.
