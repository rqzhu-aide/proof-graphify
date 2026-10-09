# Independent challenge for `lem:growing-max`

Working only from the blinded packet, I normalized the obligation and re-read lines 13-18. Lines 14-15 are exact definition unfolding. Line 16 promotes per-fixed-j tail convergence to the maximum over 1..m_n with m_n -> infinity; no uniform tail rate, union control, or dependence structure is available in the locked hypotheses. Counterexample check: independent X_{n,j} ~ Bernoulli(1/n), m_n = n^2 satisfies every hypothesis while P(max > 1/2) = 1 - (1 - 1/n)^{n^2} -> 1. Line 17 folds the refuted line-16 claim. Verdict: incorrect, statement refuted at eps = 1/2.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "lem:growing-max",
  "challenge_context_sha256": "d162f61512ae82901b648b4a09192e45939b1908d97bbf9da39f64432c3fd37a",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "incorrect",
  "reconciled_verdict": "incorrect",
  "artifact": "audit/05_adversarial/lem-growing-max-challenge.md",
  "disagreements": [],
  "resolution": "",
  "generated_utc": "2026-09-02T19:35:19.867744Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "a2d101ec5357283027a977690b1c47aedd8d31c52a511e68d1d4185887c37a39",
      "assessment": "confirmed",
      "target_assessment": "Independently re-derived: the pointwise hypothesis cannot control the maximum over the growing range 1..m_n. The Bernoulli(1/n) array with m_n = n^2 satisfies both hypotheses and gives P(max \u003e 1/2) = 1 - (1 - 1/n)^{n^2} -\u003e 1, so the target contract's conclusion is false and the issue's target is confirmed.",
      "downstream_assessment": "thm:main consumes exactly this conclusion through use D001 and offers no independent control of the maximum, so the propagation to thm:main is confirmed."
    }
  ]
}
-->
