# Primary reconfirmation after the unreadable-context regression repair

This is an actual primary review in the implementation maintenance context,
performed before recompilation. It is not a blinded challenge. The published
release and workbench are preserved byte for byte in this directory. The new
validator keeps unreadable auxiliary sources locked and warning-reviewed while
still rejecting unreadable required proof fragments. This reference contains
neither unreadable files nor included fragments, so the fix changes review
context without changing any source premise, inference, or mathematical result.

The exact paper, both complete normalized obligations, all six substantive
annotations, both counterexample programs, the issue targets, and all eight
dependency compatibility dimensions were reread. The two declarations at lines
2 and 3 and all source locations are unchanged. The lemma statement occupies
lines 6 to 11 and its proof lines 13 to 18. The theorem statement occupies
lines 20 to 24 and its proof lines 26 to 30.

For the lemma, fixing arbitrary $\varepsilon>0$ at line 14 and unfolding
fixed-coordinate convergence at line 15 are valid. Line 16 incorrectly promotes
that pointwise hypothesis to a growing maximum. On one countable product
probability space let the coordinates be independent Bernoulli variables with
success probability $1/n$ and let $m_n=n^2$. Every fixed coordinate converges
to zero in probability. Nevertheless,

$$
P\left(\max_{1\le j\le n^2}|X_{n,j}|>1/2\right)
=1-(1-1/n)^{n^2}\longrightarrow1,
\qquad (1-1/n)^{n^2}\le e^{-n}.
$$

The exact rational program checks finite instances of the formula. The bound
proves the asymptotic limit; finite computation alone does not establish it.
Thus line 16 is invalid and the folded conclusion at line 17 is directly false.

For the theorem, line 21 inherits only the lemma conditions, not its conclusion.
Lines 27 to 28 invoke that conclusion through D001. The substitution at line 29,
$\hat\theta_n-\theta_0=\max_j|X_{n,j}|$, is algebraically exact, conditional on
the cited maximum convergence. The complete written proof is invalid because
that premise is unavailable. All eight compatibility dimensions still match:
domains and quantifiers, probability model, hypotheses, definitions, conclusion,
uniformity, asymptotic regime, and constants.

Direct falsity follows independently on a one-point probability space: choose
$m_n=n$ and $X_{n,j}=\mathbf{1}\{j=n\}$. Each fixed coordinate is zero once
$n>j$, but every row maximum equals one. Consequently,

$$
P\left(|\hat\theta_n-\theta_0|>1/2\right)=1
\quad\text{for every }n.
$$

The source conditions and estimator definition are satisfied exactly. Both
statements remain refuted; both complete arguments remain invalid. The lemma
has no unresolved external dependency and the theorem closure remains incorrect
through D001. Issue I-001 remains at the actual line-16 transition and propagates
to the theorem, without treating a failed proof alone as a statement refutation.

A uniform tail-rate condition $m_n a_n(\varepsilon)\to0$ would be sufficient,
not necessary. A fixed finite index range narrows the statement. Both remain
candidate repairs requiring a new affected-result review; neither was applied.
Prior independent responses and the earlier conditional-versus-whole-argument
disagreement remain preserved. Fresh current-context challenge responses will
be obtained separately. The existing calibration receipt is used only if the
current validator accepts it; no new calibration event is claimed here.
