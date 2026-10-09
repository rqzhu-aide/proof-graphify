# Primary review for the proofcheck 1.4 reference refresh

The maintenance primary reviewer reread the snapshotted manuscript and all
normalized conditions and annotations on 2026-09-04 in the existing audit
maintenance context. This review is not a fresh-context independent challenge.
The two newly authored balanced canary responses are recorded in session
`cal-reference-1.4-primary-20260904`; their prior exposure is disclosed and they
are a smoke test, not held-out behavioral evaluation.

For the lemma, proof line 15 unfolds the fixed-index convergence hypothesis.
Line 16 introduces control over a growing index set without a tail rate or
other valid control of its union. On one countable product probability space,
choose independent Bernoulli(1/n) coordinates and m_n = n^2. For every fixed j,
the tail is 1/n for 0 < epsilon < 1, and zero for epsilon >= 1, so the original
pointwise hypothesis holds. At epsilon = 1/2 the maximum tail is
1 - (1 - 1/n)^(n^2), which tends to one since (1 - 1/n)^(n^2) <= exp(-n).
The definition folding on line 17 cannot repair this refuted intermediate
claim. The new annotations clarify the epsilon range in the old counterexample
wording. The unused setup row at line 14 is not consumed as a factual premise;
subsequent derivations link the actual normalized hypothesis and definition.

For the theorem, the inherited conditions and the estimator definition match
the source. Line 29 uses the registered lemma conclusion and exact substitution.
The primary missing-premise record establishes that this written proof does
not establish the theorem. A direct counterexample to the theorem is also
available by applying its exact estimator definition to the same array. The
fresh independent review and reconciliation decide whether to record that
stronger conclusion-specific refutation explicitly; an unsupported proof alone
is not sufficient reason to label a statement false.

The annotated candidates were rebuilt with the compiler library against current
reviewed packets and passed local final validation. The first-time compiler CLI
requires a skeleton packet and an absent output ledger; a live issue target
cannot be removed to obtain that packet during this refresh. The reviewer used
the library's candidate construction and the local final gate while retaining
the old issue target until replacement. The full non-report release gate then
reported only the two outstanding independent challenge passes.

Original ledgers remain unchanged under
`audit/04_local_checks/history/protocol-1.3/`. Historical challenge files retain
their original prose and dates. Initial responses for protocol 2 must come from
the new genuinely blinded contexts and be preserved by `record-challenge` before
reconciliation. No response is reconstructed from the historical final ledger.

The existing exact-rational counterexample script was replayed with the shared
user-wide Python interpreter during this review. Captured standard output:

```text
n=10: per-index tail=0.1000, P(max > 1/2)=0.999973
n=100: per-index tail=0.0100, P(max > 1/2)=1.000000
n=1000: per-index tail=0.0010, P(max > 1/2)=1.000000
conclusion tail approaches 1, refuting max -> 0 in probability
```

The finite computations illustrate the formula. The exponential bound above is
the mathematical asymptotic argument.

## Reconciliation with the genuine blinded review

The new fresh-context reviewer supplied the deterministic witness
m_n=n, X_{n,j}=1{j=n} on a one-point probability space, and checked it directly
against both exact conclusions. The primary reviewer independently verified
that each fixed coordinate is zero for every n>j, each row maximum is one, and
the estimator error is exactly one for every n. The theorem's current record
therefore contains an explicit counterexample and is `refuted`.

The earlier primary `not_established` record is retained in
`audit/04_local_checks/history/pre-challenge-1.4/`. Its immutable original
challenge response is retained as well. After adding the theorem's conclusion
to issue I-001's target set, the same still-blinded checker inspected the new
exact packets and returned explicit reconfirmations. Those responses were
preserved through `record-challenge` before further binding or publication.
The historical root issue and manuscript source were not silently replaced.

The separate moving-coordinate script printed row maximum=1 and estimator
error=1 at n=1,2,5,20. The symbolic eventual-zero and always-one identities
supply the mathematical argument; these finite computations are illustrations.
