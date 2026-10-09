# Fresh lemma challenge and coordinator reconciliation

The challenger was /root/recovery_independent_review, a fresh context using the
same model. The task coordinator supplied only the exact blinded packet and
current challenge instructions. This records separate source-based reasoning;
it does not claim statistical independence or a second model.

The initial response was recorded before reconciliation and is preserved at
`audit/05_adversarial/initial-fef88974cf7442a7-fdf4285ee2e2158fefb19e44da4f07462c26e0e15f29a99e47c2855cc89cfacb.json`. All earlier initial responses and reconciliation evidence
remain in their existing supersession history.

The coordinator checked the supplied deterministic construction against every
source condition. On a one-point probability space, $m_n=n$ and
$X_{n,j}=\mathbf{1}\{j=n\}$ are measurable real variables. Every fixed $j$
is eventually zero. Each row maximum equals one, so the tail probability at
$\varepsilon=1/2$ equals one for all $n$. This confirms both the invalidity of
the line-15 to line-16 promotion and direct falsity of the stated lemma.

The primary Bernoulli construction independently reaches the same judgment.
The different witnesses do not constitute a judgment disagreement: both
preserve the exact source assumptions and refute the same conclusion. The
downstream estimator definition makes its error identically one in the fresh
witness, confirming direct downstream refutation as well as unavailable support.

The coordinator agrees with the recorded invalid argument and refuted statement.
No statement, proof, or repair was changed during reconciliation.

## Preserved decisive reason

The normalized obligation faithfully preserves the source's pointwise hypothesis for each fixed $j$ and its stronger conclusion about the entire growing row. Line 15 is justified, but line 16 does not follow. On a one-point probability space, take $m_n=n$ and $X_{n,j}=\mathbf{1}\{j=n\}$ for $1\le j\le n$. For every fixed $j$, the variable is zero for all $n>j$, hence converges to zero in probability as required. Nevertheless $\max_{1\le j\le n}|X_{n,j}|=1$ for every $n$, so for $\varepsilon=1/2$ its exceedance probability is always one. This satisfies all source hypotheses and refutes the conclusion, rather than merely exposing an omitted argument. A finite union bound would leave $\sum_{j=1}^{m_n}P(|X_{n,j}|>\varepsilon)$, whose decay is not supplied by convergence at fixed coordinates. No prerequisite theorem or other assumption in this packet supplies the missing control.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "lem:growing-max",
  "challenge_context_sha256": "e997833e3cbb871243ba540b850f6d8e516963371f22536f29acaad9efbedf4c",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "incorrect",
  "reconciled_verdict": "incorrect",
  "artifact": "audit/05_adversarial/lem-growing-max-challenge-context-recovery-2026-09-07.md",
  "disagreements": [],
  "resolution": "",
  "generated_utc": "2026-09-07T17:09:08.128972Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "a55282aebd9fabb477429cd8cfeab159f679748a19e859e6f1c9b894d3aab215",
      "assessment": "confirmed",
      "target_assessment": "The targeted promotion at paper.tex line 16 is invalid. The assumptions permit $m_n=n$ and $X_{n,j}=\\mathbf{1}\\{j=n\\}$ on one probability space. Every fixed-coordinate tail eventually vanishes, whereas $P(\\max_{1\\le j\\le n}|X_{n,j}|\u003e1/2)=1$ for all $n$. The growing index range is precisely what allows the nonvanishing spike to escape every fixed coordinate.",
      "downstream_assessment": "The packet identifies thm:main as using this maximum convergence and gives its estimator as $\\hat\\theta_n=\\theta_0+\\max_{1\\le j\\le m_n}|X_{n,j}|$. Under the same admissible deterministic array, $\\hat\\theta_n-\\theta_0=1$ for every $n$. Thus this dependency cannot justify the downstream consistency claim, and the displayed downstream statement is itself refuted under its given conditions."
    }
  ],
  "initial_response": {
    "artifact": "audit/05_adversarial/initial-fef88974cf7442a7-fdf4285ee2e2158fefb19e44da4f07462c26e0e15f29a99e47c2855cc89cfacb.json",
    "sha256": "87c71a084e6ef5bf3ecab1ae3feda90dd503c9ccbdc0489ad7627659d3c4eec2",
    "input_sha256": "fdf4285ee2e2158fefb19e44da4f07462c26e0e15f29a99e47c2855cc89cfacb"
  }
}
-->
