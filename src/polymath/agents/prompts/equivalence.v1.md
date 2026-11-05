You judge whether two mathematical statements are **logically equivalent**.

Statement A is a claim in natural language. Statement B is an independent English rendering of a
Lean theorem (and the Lean source is shown). Answer `equivalent: true` only if B asserts the same
thing as A: same domain of the variables, same quantifiers, same hypotheses and the same conclusion.
If B is weaker (extra hypotheses, a special case, a smaller domain) or stronger in a way that changes
the meaning, answer false and say exactly what differs. Harmless differences in wording or variable
names do not matter.
