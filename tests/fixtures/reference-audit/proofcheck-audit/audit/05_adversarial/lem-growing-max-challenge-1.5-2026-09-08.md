# Independent challenge for lem:growing-max

The fresh context `/root/reference_lemma_blind` received only the exact blinded packet and current challenge response protocol. The actual response and consumed packet were preserved with `record-challenge` before this reconciliation. This is declared fresh-context same-model provenance, not automatic runtime attestation.

The original response assigns `incorrect`, argument `invalid`, and statement `refuted` to C001. These match the current primary record. It confirms the exact I-001 target and downstream consequence.

The coordinator checked the reported witness against the exact source. On the one-point probability space, $m_n=n$ and $X_{n,j}=\mathbf{1}\{j=n\}$ satisfy fixed-coordinate convergence because $X_{n,j}=0$ whenever $n>j$. Each row maximum is one. The estimator definition then gives $\hat\theta_n-\theta_0=1$ for every $n$. Thus both the maximum claim and the exact estimator claim have a tail probability of one at tolerance $1/2$. The written complete argument is invalid and the statement is directly refuted; the latter judgment does not follow merely from an unavailable prerequisite.

No judgment, primary support, or issue-assessment disagreement requires a change. The final issue assessments retain the actual new response. Earlier initial responses and their complete reconciliation artifacts remain linked through the immutable superseded-review chain, including the historical theorem conditional-versus-invalid disagreement. No historical response was edited.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "lem:growing-max",
  "challenge_context_sha256": "20893e32304756357eedea52e150cb52f588b8142d3367248fddd8e9b3c34e2d",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "incorrect",
  "reconciled_verdict": "incorrect",
  "artifact": "audit/05_adversarial/lem-growing-max-challenge-1.5-2026-09-08.md",
  "disagreements": [],
  "resolution": "",
  "generated_utc": "2026-09-08T01:30:09.304669Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "a55282aebd9fabb477429cd8cfeab159f679748a19e859e6f1c9b894d3aab215",
      "assessment": "confirmed",
      "target_assessment": "The targeted move at paper.tex line 16 promotes fixed-coordinate tail convergence to a tail bound for a growing maximum without a supporting hypothesis. The deterministic array $m_n=n$, $X_{n,j}=\\mathbf{1}_{\\{j=n\\}}$ makes every fixed-coordinate tail eventually zero but makes the maximum's tail probability $1$ for $\\varepsilon=1/2$. Thus the targeted inference is invalid and the lemma statement is false, rather than merely lacking an exposition detail.",
      "downstream_assessment": "The packet identifies use D001 in thm:main as requiring precisely the refuted maximum-convergence conclusion. Under the supplied downstream contract $\\hat\\theta_n=\\theta_0+\\max_{1\\le j\\le m_n}|X_{n,j}|$, the same admissible array yields $\\hat\\theta_n=\\theta_0+1$ for every $n$, so $\\Pr(|\\hat\\theta_n-\\theta_0|\u003e1/2)=1$. Consequently the stated downstream consistency conclusion, anchored in the packet at paper.tex line 23, is also refuted under its supplied conditions, and the lemma cannot establish that dependency use."
    }
  ],
  "initial_response": {
    "artifact": "audit/05_adversarial/initial-fef88974cf7442a7-88323660cf364d57609b700cc891bab24b36e3e943a94e2b7db1a0b9233e42e3.json",
    "sha256": "60dd71ac143976f71cf77f2550c47ac0e0cf8c16ad4c67f8725d8804e373fdd5",
    "input_sha256": "88323660cf364d57609b700cc891bab24b36e3e943a94e2b7db1a0b9233e42e3"
  }
}
-->
