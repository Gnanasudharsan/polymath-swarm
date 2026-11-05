# Polymath Swarm — evidence report

**Problem.** Prove that for every natural number n, the product n * (n + 1) is even.

## Answer

Yes — for every natural number n, the product n(n+1) is even [claim_e23b05fb0458].

This is the formalized and verified theorem: for all n : ℕ, n * (n + 1) is even [claim_e23b05fb0458].

## Verified claims (1)

- `claim_e23b05fb0458` For every natural number n, the product n(n+1) is even.
  - 🔍 critique: critic: accept
  - ✅ Lean-verified: Lean 4 `forall_n_mul_succ_even`: proved, faithful — gate: **supports** (Lean re-verified `forall_n_mul_succ_even` (propext, Classical.choice, Quot.sound))

## Conjectures — not verified (2)

- `claim_6af5de20c612` (proposed) Every integer is either even or odd (i.e., for each integer m exactly one of the following holds: there exists k with m = 2k, or there exists k with m = 2k+1).
  - 🔍 critique: critic: accept
- `claim_39125dcbe569` (proposed) If n is even then n(n+1) is even; if n is odd then n+1 is even, hence n(n+1) is even.
  - 🔍 critique: critic: accept
  - ✅ Lean-verified: Lean 4 `even_mul_succ_of_parity_cases`: proved, NOT faithful — gate: **inconclusive** (Lean statement not judged equivalent to the claim)

---
Run `run_14f7b830feec` · 15310 tokens · $0.0631 · verified-claim rate 33%
