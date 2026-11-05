# Polymath Swarm — evidence report

**Problem.** Prove that for every natural number n, the product n * (n + 1) * (n + 2) is even.

## Answer

Theorem. For every natural number n, the product n(n+1)(n+2) is even. [claim_cc223b9f0b2f][claim_291e34b739dd]

Short proof (formalized). The machine-checked formalization directly proves this theorem; see the verified formal proof [claim_cc223b9f0b2f].

## Verified claims (2)

- `claim_cc223b9f0b2f` For every natural number n, the product n(n+1)(n+2) is even. ♻️ _reused from run `run_9f444ad01268`_
  - 🔍 critique: critic: accept
  - ✅ Lean-verified: Lean 4 `triple_consecutive_product_even`: proved, faithful — gate: **supports** (Lean re-verified `triple_consecutive_product_even` (propext, Classical.choice, Quot.sound))
- `claim_291e34b739dd` For every natural number n, the product n(n+1)(n+2) is even.
  - ✅ Lean-verified: Lean 4 `even_triple_product_nat`: proved, faithful — gate: **supports** (Lean re-verified `even_triple_product_nat` (propext, Classical.choice, Quot.sound))
  - 🔍 critique: critic: accept
  - 🔍 critique: critic: accept

## Conjectures — not verified (7)

- `claim_8b4da1c8a42d` (proposed) Definition: an integer m is even iff 2 divides m (i.e. there exists k with m = 2k).
  - 🔍 critique: critic: accept
  - 🔍 critique: critic: accept
- `claim_bbd92860997d` (challenged) Lemma: For every integer n, among the three consecutive integers n, n+1, n+2 at least one is even.
  - ✅ Lean-verified: Lean 4 `even_triple_product_nat`: proved, NOT faithful — gate: **inconclusive** (Lean statement not judged equivalent to the claim)
  - 🔍 critique: critic: challenge
  - 🔍 critique: critic: accept
- `claim_4b0a7d705d6d` (proposed) If one factor in a product of integers is even, then the entire product is even (divisible by 2).
  - 🔍 critique: critic: accept
  - 🔍 critique: critic: accept
- `claim_d4101c1569f4` (proposed) For every natural number n, the product n(n+1)(n+2) is even.
  - 🔍 critique: critic: accept
- `claim_a8f5c7a47b65` (proposed) For every integer n, among the three consecutive integers n, n+1, n+2 at least one is even.
  - 🔍 critique: critic: accept
- `claim_f1dae3591341` (proposed) An integer m is even iff 2 divides m (i.e. there exists k in Z with m = 2k).
  - 🔍 critique: critic: accept
- `claim_516166819028` (proposed) If one factor in a product of integers is even, then the entire product is even (divisible by 2).
  - 🔍 critique: critic: accept

---
Run `run_ce34122a04b6` · 23541 tokens · $0.0958 · verified-claim rate 22%
