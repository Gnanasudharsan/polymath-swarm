# ADR-0010: A2A interop, hardening and release packaging

- **Status:** Accepted
- **Date:** 2026-11-06

## Context

v1.0.0 must let other agent systems call the swarm and let the swarm call them, survive hostile
input (fetched papers, remote agents, API clients), start with one command, and ship as images.

## Decision

**A2A (a2a-sdk 1.3, protocol 1.0, JSON-RPC binding).**
- The swarm is one agent: its card is at `/.well-known/agent-card.json` and JSON-RPC at `/a2a`.
  `message/send` runs a full verified swarm run (no plan approval) and returns two artifacts: the
  evidence report as Markdown, and `{run_id, status, report}` as data.
- Each specialist (literature, reasoner, compute, formalizer, critic) is an agent at `/agents/<role>/`,
  running that one specialist and returning its output and claims. Specialist claims are explicitly
  *proposals*.
- Cards are public (discovery) and declare an API-key security scheme; JSON-RPC requires `x-api-key`.
- Routes are mounted at app creation; executors obtain the runner via a getter once the lifespan has
  built it.
- **Delegation**: `A2ADelegate` is a `TaskExecutor` that sends a task to any A2A agent
  (`POLYMATH_A2A_DELEGATES`, per role). The remote reply is sanitised and becomes one low-confidence,
  **evidence-free** proposed claim, so the verification gate can never accept it on the remote's word.

**Hardening.** Untrusted-text sanitiser for papers, passages and A2A replies (`polymath.security`);
per-client sliding-window API rate limits; dependency audit; written threat model
(`docs/security.md`). The architectural guarantee is unchanged: claims only become verified when the
gate reproduces their evidence.

**Packaging.**
- Images: `polymath-api` (Python 3.12 slim + uv + Docker CLI; `polymath serve`), `polymath-web`
  (Next.js standalone, non-root) and `polymath-sandbox`, built and pushed to GHCR by `release.yml` on
  `v*` tags. The ~15 GB Lean image is not published.
- Compose profiles: default (Postgres, Redis), `tools` (sandbox, Lean builds), `app` (+ API on :8000
  and web on :3100, one command), `observability` (Langfuse).
- The API container mounts the Docker socket to start sandbox and Lean containers as siblings. This
  is root-equivalent on the host, so it is documented with mitigations.

## Consequences

- External agents get evidence reports, not just answers, and cannot inject "verified" facts.
- Release images are reproducible from tags; Lean stays opt-in because of its size.
- The A2A surface reuses the API key and rate limits rather than adding a second auth system.
