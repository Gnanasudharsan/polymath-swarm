# End-to-end demos

Each demo runs the full swarm (planner → specialists → critique loop → verification gate →
synthesizer) on real infrastructure: Postgres checkpoints, Redis, the Docker sandbox, Lean 4 +
Mathlib and the public literature APIs. Committed outputs come from runs with the `openai` model
profile (gpt-5 for the Formalizer, gpt-5-mini elsewhere).

| Demo | Problem | Verified result | Evidence | Cost |
|---|---|---|---|---|
| [`proof/`](proof/report.md) | For every natural number n, n·(n+1) is even. | ✅ main theorem | Lean 4 proof, re-verified by the gate (standard axioms only), back-translation judged faithful | $0.063 |
| [`computation/`](computation/report.md) | Sum of the first 100 primes; is it prime? | ✅ 24133, and it is prime | two sandbox programs printing PASS, re-run by the gate | $0.011 |
| [`reuse/`](reuse/report.md) | For every n, n·(n+1)·(n+2) is even (run after an earlier run proved it) | ✅ theorem, **recalled from episodic memory** (♻️) and re-verified | recalled claim's Lean proof re-checked by this run's gate; similarity 0.934 | $0.096 |
| [`literature/`](literature/report.md) | Who proved the 2023 exponential improvement for diagonal Ramsey numbers, and what bound? | ✅ Campos–Griffiths–Morris–Sahasrabudhe; R(k,k) ≤ 3.8^(k+o(k)) (optimised) | verbatim quotes re-found in the re-fetched arXiv abstract | $0.007 |

Each folder holds `report.md` (human-readable), `report.json` (the `EvidenceReport`) and
`trace.json` (plan, every task result, every claim version and every blackboard event).

## Run them

```bash
docker compose up -d --wait
```

```bash
docker compose --profile tools build
```

```bash
uv run python examples/run_demo.py proof --max-usd 1.0
```

Replace `proof` with `computation`, `literature` or `reuse` (run `reuse` after a proof run so
episodic memory has something to recall). A provider key must be in the environment.
Set `POLYMATH_MODEL_PROFILE=openai` in `.env` if you only have an OpenAI key.

## What the demos taught us (fixed before release)

The first live runs found real bugs, each now covered by a test:

- a Formalizer timeout dropped its spend from the run budget → usage is captured per task by the gateway;
- one failed checker skipped synthesis → synthesis runs once all inputs have finished;
- Compute "verified" a restatement of the task → it now computes first and states claims from values;
- a correct proof was filed under the wrong claim → proofs are re-matched to the claim they establish;
- back-translation saw only the theorem header, so a custom definition could fake faithfulness → it now sees every definition;
- citation quotes failed across differently typeset TeX → quotes match on word sequences;
- arXiv's bare-term search ranked poorly → plain keywords are AND-ed.

In the `reuse` run the Reasoner also proposed the same statement and the Formalizer proved it again,
so reuse showed up at the gate (the recalled proof was re-checked) rather than as skipped work. The
recalled claim is marked ♻️ in the report and the recall is a `memory_recall` event in the trace.

Model output varies between runs, especially literature search results; a re-run may verify a
different set of claims.
