# ADR-0003: MCP tool layer and the Python sandbox

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

Agents need literature search, exact symbolic maths, arbitrary numeric code and formal proof
checking. Tools must be reusable outside the swarm, isolated from each other, testable without
Docker, and safe against untrusted (LLM-written) input.

## Decision

- **Every tool is an MCP server** built with the official SDK (`mcp==2.3.0`). In SDK 2.x the
  high-level server class is `MCPServer` (formerly `FastMCP`). Each server lives in
  `polymath.mcp_servers.<name>` with `build_server(...)` (dependency-injected, used by tests) and a
  `__main__` that runs it over stdio.
- **`MCPToolbox`** is the single client adapter. It mounts several servers (in-process `MCPServer`
  for tests, or `StdioServerParameters` subprocesses in production), namespaces tools as
  `server.tool`, exports LiteLLM function-calling schemas (`server__tool` on the wire), and traces
  every call (`mcp.call_tool` span).
- **User-facing failures raise `ToolError`**, so the agent sees an actionable message. Unexpected
  exceptions are masked by the SDK.
- **sympy server**: SymPy's parser evaluates Python, so input goes through a deny-list screen (dunder,
  attribute access, quotes, brackets, `import`/`eval`/...) and length limit. Each operation then runs
  in a fresh `spawn` child process that is killed on timeout. `verify_identity` returns
  `proved | refuted | numerically_equal | unknown`; only `proved` and `refuted` are decisive.
- **sandbox server**: a throwaway `docker run` per program with `--network none`, `--read-only`,
  a size-capped `/tmp` tmpfs, memory = swap cap, CPU quota, `--pids-limit`, `--cap-drop ALL`,
  `no-new-privileges`, `--ipc none` and uid 65534. Time is limited inside the container (runner
  subprocess timeout) and by the host (`docker kill` after timeout + startup slack). The runner
  returns one JSON envelope (stdout/stderr capped at 256 KB, files from `/tmp/artifacts`).
  Escape tests cover network, filesystem writes, uid, infinite loop, memory bomb and fork bomb.
- **literature server**: arXiv (Atom via `defusedxml`), Semantic Scholar Graph API, OpenAlex. A
  Redis response cache (TTL, default 24 h) and a Redis `SET NX PX` min-interval rate limiter shared by
  all processes (arXiv 3 s, S2 1.1 s unauthenticated, OpenAlex 0.15 s). 429/5xx retry with
  `Retry-After`. Returned text is marked as untrusted data in the server instructions.
- **Test markers**: `integration` (Docker/compose), with subsets `network` (public APIs, skipped in CI
  because shared runner IPs get throttled) and `lean` (multi-GB image, run via `lean.yml` on demand).

## Consequences

- Any MCP-capable client (Claude Desktop, other agents) can use the tools directly.
- Each sandbox run pays ~0.2–1 s of container start-up; acceptable for verification work.
- The SymPy screen is a deny-list. It is defence in depth on top of process isolation; arbitrary
  programs must go through the sandbox, which is the real security boundary.
