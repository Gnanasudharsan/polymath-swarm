# Security review

Polymath Swarm runs LLM-written code, reads untrusted text from the internet, exposes an HTTP API
and talks to other agents. This document lists what it protects, how, and what remains.

## Trust boundaries

| Boundary | Untrusted input | Main controls |
|---|---|---|
| Sandbox | Python written by models (Compute, Critic) | Throwaway Docker container: `--network none`, read-only root FS, size-capped `/tmp` tmpfs, memory = swap cap, CPU quota, `--pids-limit`, `--cap-drop ALL`, `no-new-privileges`, `--ipc none`, uid 65534, host-side kill on timeout. Escape tests: network, writes outside `/tmp`, uid, infinite loop, 1 GB allocation, fork bomb (`tests/integration/test_sandbox.py`). |
| Lean | Lean files written by the Formalizer (can run `#eval` / metaprograms) | Persistent REPL container with no network, read-only FS, memory and PID caps, dropped capabilities; restart on timeout. Proofs are accepted only with no errors, no `sorry`/`admit` and only `propext`, `Classical.choice`, `Quot.sound` (custom axioms rejected). |
| SymPy | Expressions from models (parsed with `eval` inside SymPy) | Deny-list screen (dunder, attribute access, quotes, brackets, `import`/`eval`/…), length limit, and a fresh child process per call, killed on timeout. The sandbox, not this screen, is the boundary for arbitrary programs. |
| Fetched papers | Titles, abstracts, PDF text (prompt injection) | `polymath.security.untrusted`: control/bidi characters, chat-template tokens and our wrapper tags are stripped; instruction-like text is flagged; text is wrapped in `<paper>` and declared data. **Architectural control**: text is only ever quoted, and every citation is re-checked by the gate (re-fetch the paper, match title and a ≥ 6-word verbatim quote). Injected text can at worst cause a wrong *proposal*; it cannot make a claim verified. |
| External A2A agents | Replies from delegated agents | Sanitised as untrusted text and turned into a low-confidence *proposed* claim with **no evidence**, so the gate cannot accept it on the remote's word. |
| HTTP API / A2A | Requests from clients | One API key (`x-api-key`, constant-time compare); the server refuses to start without it. A2A JSON-RPC requires the key; Agent Cards are public for discovery. Per-client sliding-window rate limits (default 20 writes and 600 reads per minute; 429 with `Retry-After`). Input sizes bounded (problem ≤ 8000 characters, budget ≤ 10 USD per run). |
| Web UI | Browser | The API key stays server-side: the Next.js proxy adds it. The browser never sees it. |
| Memory | Claims from earlier runs | Recalled claims re-enter as *proposed*; only the current run's gate can verify them. Memory stores the gate's verdicts, never merged agent state (this closed a cross-run laundering bug found in Phase 5). |
| Spend | Runaway agent loops | Per-run `RunBudget` (USD, tokens, wall clock, iterations), checked before every call; an optional cross-run spend ledger with a hard cap; provider quota exhaustion fails fast. |
| Secrets | Keys in the repo | `.env` is gitignored; pre-commit runs `detect-private-key` and gitleaks on every commit; tests never read `.env` (`LITELLM_MODE=PRODUCTION`, `POLYMATH_NO_DOTENV=1`). |

## Docker socket

To start sandbox and Lean containers, the process running the tool servers needs the Docker API.
In the one-command compose stack the API container mounts `/var/run/docker.sock`, which is
equivalent to root on the host. Mitigations: the API binds to `127.0.0.1` by default, requires the
API key, and only ever starts containers from the two fixed images with the flags above. For a
multi-tenant deployment, run sandboxes on a separate host or use a rootless runtime (gVisor, Kata).

## Dependency audit (2026-11-06)

- Python: versions pinned in `uv.lock`.
- Frontend production dependencies: 4 low-severity advisories, all in the KaTeX chain (prototype
  pollution under unusual trust settings). npm's suggested "fix" downgrades to older majors. KaTeX
  renders only the swarm's own report Markdown with default trust settings, so this is accepted.
  The `shadcn` CLI is a build-time dev dependency.

## Residual risks

- A single shared API key, not per-user auth or roles.
- The SymPy screen is a deny-list (defence in depth only).
- Rate limits are per process (in memory). Multiple API replicas need a shared limiter (Redis).
- The Lean equivalence check uses an LLM judge. It can only *block* a proof, never admit one, but a
  wrong "not equivalent" lowers recall.
- The Docker socket mount (above).

## Reporting

Open a private security advisory on the GitHub repository.
