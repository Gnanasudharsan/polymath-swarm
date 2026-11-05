# ADR-0004: Lean 4 verification through a persistent REPL container

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

The Formalizer needs to check Lean 4 + Mathlib code, read goals and count `sorry`s, and the
verification gate needs a trustworthy "this theorem is proved" signal. The brief suggested
adapting `lean-lsp-mcp` (v0.33.0).

Measurements on the dev machine (Docker VM with 8 GB):
- One-shot `lake env lean --json --stdin` with `import Mathlib`: **55–110 s per check**. A second
  concurrent cold load was OOM-killed (exit 137).
- [leanprover-community/repl](https://github.com/leanprover-community/repl) `v4.35.0`: `import
  Mathlib` once (~55 s, ~3.2 GB resident), then **~0.1 s per check**. It also reports the goal at
  every `sorry`.

## Decision

- Image `polymath-lean:v4.35.0` (`docker/lean.Dockerfile`): Ubuntu 24.04, elan, a Lake project
  pinned to Mathlib `v4.35.0` with the prebuilt olean cache (`lake exe cache get`), plus the REPL
  built for the same toolchain. Unpacked size is ~15 GB.
- `LeanREPL` keeps **one long-lived container** (`--network none`, read-only rootfs, tmpfs, 6 GB
  memory cap, PID limit, all caps dropped), imports Mathlib once and runs every check in that saved
  environment. Calls are serialised with a lock. A timeout or crash kills the container and the next
  call restarts it.
- User files may only import Mathlib/Lean/Std/Batteries/Aesop/Qq modules (covered by `import
  Mathlib`). Import lines are stripped and diagnostics are mapped back to the original line numbers.
- **Verification rule** (`verify_proof`): no errors, no `sorry`/`admit` (compiler sorries, `hasSorry`
  warnings and comment-aware token count), and `#print axioms <thm>` lists only `propext`,
  `Classical.choice`, `Quot.sound`. This rejects `sorryAx` and custom axioms (e.g.
  `axiom cheat : False`), which a "compiles with 0 sorry" check alone would miss.
- `lean-lsp-mcp` is **not** used directly: it needs a host-side Lean install and an LSP session per
  project, which conflicts with keeping Lean fully containerised and network-less. Our tool surface
  (`check`, `get_goals`, `count_sorry`, `verify_proof`) covers what the Formalizer needs. If
  richer LSP features (hover, completions, search) become necessary, `lean-lsp-mcp` can run *inside*
  this image.

## Consequences

- First call per server process costs ~1 minute; MCP clients mounting `lean` need a long read timeout.
- One REPL serialises checks. Scaling out means a pool of REPL containers (~3.5 GB each).
- Lean code can run `#eval`/metaprograms inside the REPL; the container (no network, read-only
  filesystem, resource caps) is the containment boundary.
- CI runs Lean tests only on demand (`lean.yml`), since the image barely fits on a standard runner.
