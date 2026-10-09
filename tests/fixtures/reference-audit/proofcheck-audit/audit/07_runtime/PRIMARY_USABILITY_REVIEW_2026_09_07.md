# Primary review after the practical source and report repairs

This is a new primary review in the implementation maintenance context. It is
not a blinded challenge. The unchanged manuscript, both complete normalized
obligations, all four lemma annotations, both theorem annotations, both exact
counterexample programs, the issue targets, and the eight D001 compatibility
checks were read and checked before recompilation. Earlier ledger, skeleton,
challenge, and reconciliation bytes remain preserved.

The source has two ordinary declared result environments. Their declarations
at paper.tex lines 2 and 3 now have explicit kind and source metadata. Statements
remain at lines 6 to 11 and 20 to 24, and proofs at lines 13 to 18 and 26 to 30.
There are no hidden included arguments in this reference. Adding these exact
declaration bindings changes the parser context, so the existing primary work
must be reviewed and compiled again. It does not change the mathematical claim.

The lemma correctly fixes arbitrary $\varepsilon>0$ at line 14 and unfolds the
fixed-index convergence hypothesis at line 15. At line 16 it promotes pointwise
tail convergence to control over an increasing number of coordinates. The
hypothesis supplies no such control. On one countable product probability space
let $X_{n,j}$ be independent Bernoulli variables with probability $1/n$ and put
$m_n=n^2$. Each fixed coordinate has vanishing tails. However,

$$
P\left(\max_{1\le j\le n^2}|X_{n,j}|>1/2\right)
=1-(1-1/n)^{n^2}\longrightarrow1,
\qquad (1-1/n)^{n^2}\le e^{-n}.
$$

The finite rational program confirms the stated construction, while the bound
above proves the asymptotic contradiction. The folded conclusion at line 17 is
also refuted. The line-15 premise is valid; the line-16 growing-maximum assertion
is where the invalid transition occurs.

For the theorem, the line-21 reference inherits the lemma conditions. The
reference and quoted conclusion at lines 27 to 28 identify D001, consumed by
line 29. All eight compatibility dimensions match: domain and quantifiers,
probability model, hypotheses, definitions, conclusion, uniformity, regime,
and constants. The equality
$\hat\theta_n-\theta_0=\max_j|X_{n,j}|$ is exact, so that local implication
would be valid if the maximum convergence premise held. The written complete
argument is invalid because that premise is unavailable.

The theorem is independently false under its own stated conditions: on a
one-point probability space let $m_n=n$ and
$X_{n,j}=\mathbf{1}\{j=n\}$. For every fixed $j$, the coordinate is zero once
$n>j$. Every row maximum and every estimator error equals one, and hence
$P(|\hat\theta_n-\theta_0|>1/2)=1$ for every $n$. This directly refutes the
theorem, without inferring falsity merely from a failed supporting proof.

Both statements therefore remain refuted. The lemma has no missing external
result, and the theorem's dependency closure remains incorrect through D001.
The uniform tail-rate proposal is sufficient, not necessary; replacing the
growing range by a fixed finite range narrows the claim. Both remain candidate
repairs requiring a full affected-result review. No repair is applied here.

The prior theorem challenger described the local conditional deduction while
the primary judgment concerned the whole written argument. That historical
disagreement and its resolution are preserved, rather than relabeled as
agreement. Fresh independent responses, if required by current context, are
obtained separately. Existing calibration provenance is retained only because
the current validator accepts the same recorded configuration; no new
calibration event is claimed.
