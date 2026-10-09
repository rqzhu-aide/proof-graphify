"""Exact counterexample instantiation for lem:growing-max (issue I-001).

Independent X_{n,j} ~ Bernoulli(1/n) with m_n = n^2 satisfy both stated
hypotheses, yet P(max_{j <= m_n} |X_{n,j}| > 1/2) = 1 - (1 - 1/n)^(n^2) -> 1.
Exact rational arithmetic; no rounding is involved in the comparison.
"""

from fractions import Fraction

for n in (10, 100, 1000):
    per_index = Fraction(1, n)                      # P(|X_{n,j}| > 1/2)
    miss_all = (1 - per_index) ** (n * n)           # P(max <= 1/2), m_n = n^2
    tail = 1 - miss_all
    assert per_index <= Fraction(1, 10)             # hypothesis: per-index tail -> 0
    assert tail > Fraction(99, 100)                 # conclusion tail -> 1, not 0
    print(f"n={n}: per-index tail={float(per_index):.4f}, "
          f"P(max > 1/2)={float(tail):.6f}")
print("conclusion tail approaches 1, refuting max -> 0 in probability")
