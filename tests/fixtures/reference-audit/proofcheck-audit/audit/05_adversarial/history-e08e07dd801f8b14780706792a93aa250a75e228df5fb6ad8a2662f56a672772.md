# Independent challenge for lem:growing-max

A genuinely fresh packet-only context supplied the actual final-context response. It received only the exact current blinded packet and challenge protocol. The coordinator preserved that response and consumed packet through public `record-challenge` before this reconciliation. The declaration is `fresh_context_same_model`; it records available provenance, not automatic runtime attestation.

The first response assigns C001 verdict `incorrect`, argument status `invalid`, and statement status `refuted`, and confirms I-001 with its downstream consequence. These dimensions agree with the current primary conclusion and support.

The reviewer independently constructs the singleton-space array $m_n=n$, $X_{n,j}=\mathbf{1}_{\{j=n\}}$ for $1\leq j\leq n$. The coordinator checked that for every fixed $j$, $X_{n,j}=0$ for all $n>j$, while every row maximum is one. Thus the exact lemma hypotheses at paper.tex lines 7 to 9 hold, but the maximum tail at $\varepsilon=1/2$ is one for every $n$, refuting the statement at line 10 and the line-16 inference. The estimator identity at line 22 gives $\hat\theta_n-\theta_0=1$, so the same witness directly refutes the theorem conclusion at line 23. The substitution at line 29 would be valid if its imported premise held; the complete written argument is invalid because that premise is refuted. The statement refutation is supported by the explicit witness, not inferred merely from D001 unavailability.

There is no new disagreement or change to the primary judgment, support move, issue classification or propagation. The final issue assessments are the actual unchanged response assessments. All older initial responses and reconciliation artifacts, including the historical theorem argument-status disagreement, remain linked through the preserved superseded-review chain.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "lem:growing-max",
  "challenge_context_sha256": "b89e9d699513048e7cdbd64955189ec7336cdf534bb766ae681cc51938a98c6b",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "incorrect",
  "reconciled_verdict": "incorrect",
  "artifact": "audit/05_adversarial/lem-growing-max-challenge-surgical-final-2026-09-08.md",
  "disagreements": [],
  "resolution": "",
  "generated_utc": "2026-09-08T03:22:25.223537Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "a55282aebd9fabb477429cd8cfeab159f679748a19e859e6f1c9b894d3aab215",
      "assessment": "confirmed",
      "target_assessment": "The challenged promotion at proof line 16 is invalid: pointwise convergence in a fixed coordinate gives no control over a coordinate that moves with $n$. The deterministic array $m_n=n$, $X_{n,j}=\\mathbf{1}_{\\{j=n\\}}$ satisfies the stated assumptions and makes the maximum-tail probability equal to one at $\\varepsilon=1/2$.",
      "downstream_assessment": "The downstream use in $\\mathrm{thm{:}main}$ cannot establish consistency from this lemma. Under the estimator identity supplied in its target contract, $\\hat\\theta_n=\\theta_0+\\max_{1\\le j\\le m_n}|X_{n,j}|$, the same admissible array yields $\\hat\\theta_n=\\theta_0+1$ for every $n$, contradicting the convergence claimed in the locked downstream conclusion at lines 23-24. The issue therefore affects the downstream statement as well as its dependence on this lemma."
    }
  ],
  "initial_response": {
    "artifact": "audit/05_adversarial/initial-fef88974cf7442a7-e40221e211aa307d1034103c736e7685cf2108a2259ec87e7e770a91a97e4c6d.json",
    "sha256": "cf28685b26e40c6a106ae033c199f7123fe47f777b868e0cd69c5bdb70f4e485",
    "input_sha256": "e40221e211aa307d1034103c736e7685cf2108a2259ec87e7e770a91a97e4c6d"
  }
}
-->
