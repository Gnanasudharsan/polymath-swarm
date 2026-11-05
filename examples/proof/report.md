# Polymath Swarm — evidence report

**Problem.** Prove that for every natural number n, the product n * (n + 1) is even.

## Answer

Yes — for every natural number n, n*(n+1) is even, i.e. 2 divides n*(n+1) [claim_ae51c27846ae].

This follows by the parity dichotomy (every natural n is either even or odd) together with the usual case analysis in the formal proof [claim_e6354ab22e11].

## Verified claims (2)

- `claim_ae51c27846ae` For every natural number n, 2 divides n * (n + 1); formally: ∀ n : ℕ, 2 ∣ (n * (n + 1)).
  - ✅ Lean-verified: Lean 4 `two_dvd_mul_succ`: proved, faithful — gate: **supports** (Lean re-verified `two_dvd_mul_succ` (propext, Classical.choice, Quot.sound))
  - 🔍 critique: critic: accept
- `claim_e6354ab22e11` Every natural number n is either even or odd (parity dichotomy): either ∃ k, n = 2*k, or ∃ k, n = 2*k + 1.
  - ✅ Lean-verified: Lean 4 `two_dvd_mul_succ`: proved, faithful — gate: **supports** (Lean re-verified `two_dvd_mul_succ` (propext, Classical.choice, Quot.sound))
  - 🔍 critique: critic: accept

## Conjectures — not verified (4)

- `claim_e2d251b9f920` (proposed) n(n+1) is even for every natural number n
  - (no evidence)
- `claim_d2a0064a8790` (proposed) n(n+1) is even for every natural number n
  - (no evidence)
- `claim_1e2636f3daed` (proposed) If n is even, so n = 2*k for some k, then 2 divides n*(n+1).
  - 🔍 critique: critic: accept
- `claim_38916976d024` (proposed) If n is odd, so n = 2*k + 1 for some k, then n+1 is even (n+1 = 2*(k+1)), and hence 2 divides n*(n+1).
  - 🔍 critique: critic: accept

---
Run `run_618d4184c4e2` · 19699 tokens · $0.1028 · verified-claim rate 33%
