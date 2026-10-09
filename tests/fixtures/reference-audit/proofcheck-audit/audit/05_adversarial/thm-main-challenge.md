# Independent challenge for `thm:main`

Working only from the blinded packet, I checked lines 26-30 against the normalized obligation. Lines 27-28 name Lemma 1's conclusion in exactly the registered form; line 29 consumes it through use D001, substitutes hat-theta_n - theta_0 = max_{1<=j<=m_n} |X_{n,j}| exactly from the stated definition, and folds the convergence-in-probability definition. The algebra is exact, so the only mathematical input is the refuted growing-maximum claim; nothing in this proof supplies independent control of the maximum. The written proof therefore leaves the conclusion not established. Verdict: gap.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "thm:main",
  "challenge_context_sha256": "fd5e4c7fded0b23f29eb6f61823ccbb2d721a9a87b2381e7fd511937f9e0e505",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "gap",
  "reconciled_verdict": "gap",
  "artifact": "audit/05_adversarial/thm-main-challenge.md",
  "disagreements": [],
  "resolution": "",
  "generated_utc": "2026-09-02T19:35:20.600284Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "2c1ef625adc0687b3a28e6316d2729c3cb809a138836cb444b1a8f049f548ec7",
      "assessment": "confirmed",
      "target_assessment": "The neutral target for thm:main is the growing-maximum premise consumed on line 29 through use D001. Re-derivation confirms the premise is exactly Lemma 1's refuted conclusion, and lines 26-30 supply no independent control of the maximum, so the target defect is confirmed at this unit.",
      "downstream_assessment": "thm:main has no recorded downstream uses; the propagation terminates here with the conclusion not established."
    }
  ]
}
-->
