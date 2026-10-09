# Independent theorem review and reconciliation, 7 September 2026

The fresh reviewer received only the exact blinded theorem packet and current challenge instructions. This was a fresh context using the same model, not a claim of statistical independence.

## Preserved initial reasoning

The normalized obligation matches the source: the theorem inherits only fixed-coordinate convergence in probability and m_n -> infinity. The invocation at lines 27-28 matches the complete lemma contract, and the equality hat{theta}_n - theta_0 = max_{j <= m_n}|X_{n,j}| makes line 29 valid conditional on that lemma's conclusion. That prerequisite is false under its stated conditions, and the theorem itself is refuted by an exact counterexample. On a singleton probability space, take m_n = n and X_{n,j} = 1 when j = n and 0 otherwise, for 1 <= j <= n. For every fixed j, X_{n,j} is identically zero for all n > j, so the inherited convergence hypothesis holds. However, the maximum is 1 for every n, hence hat{theta}_n = theta_0 + 1 and P(|hat{theta}_n - theta_0| > 1/2) = 1 for every n. Thus the local deduction is conditionally correct but cannot establish the exact, false statement.

## Actual disagreement

For thm:main C001 the first challenger labels the argument conditional, whereas the primary labels it invalid. The challenger assesses the exact substitution at paper.tex:27-29 conditional on the invoked maximum-convergence lemma; the primary assesses the complete written argument including D001.

## Coordinator resolution

The coordinator agrees that the substitution is exact conditional on maximum convergence. Under the current full-argument convention in evidence-and-verdicts.md, a conditional step cannot hide a failed dependency. D001 supplies a refuted lemma under paper.tex:7-10, so the complete argument remains invalid. Independently, m_n=n and X_{n,j}=1{j=n} satisfy every fixed-coordinate hypothesis but make the estimator error one for every n, refuting the exact theorem statement at paper.tex:21-23. The final judgment is invalid/refuted, with aggregate incorrect. The initial conditional/refuted response remains unchanged; this records a coordinator resolution of assessment scope, not a retraction by the challenger.

## Issue I-001

The inference from the fixed-j tail limit at line 15 to the growing maximum tail limit at line 16 is invalid. With m_n = n and deterministic X_{n,j} = 1{j=n}, each fixed-coordinate tail eventually vanishes, while P(max_{j <= n}|X_{n,j}| > 1/2) = 1 for all n. Both listed premises hold on one common probability space, so this directly refutes the targeted inference and the prerequisite lemma's stated conclusion.

Use D001 supplies exactly the maximum-convergence assertion invoked at theorem lines 27-28. The estimator definition then transfers the same counterexample without modification: its error equals 1 for every n. The theorem's final algebraic deduction is sound conditional on maximum convergence, but the actual inherited assumptions do not supply it. The downstream theorem conclusion C001 is therefore false as stated, rather than merely awaiting a proof of its prerequisite.

Preserved initial response: `audit/05_adversarial/initial-7bdd85e78da77a40-f6169a1e24fc75d2b938ce6fb3b0114b1f8178b592837ade57a4a9cbbaa23c59.json`.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "thm:main",
  "challenge_context_sha256": "6bbbbf06398fc27bf8cc5b0f24792cd40151e52222846fc3e61c21f429a57c6f",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "incorrect",
  "reconciled_verdict": "incorrect",
  "artifact": "audit/05_adversarial/thm-main-challenge-2026-09-07.md",
  "disagreements": [
    "For thm:main C001 the first challenger labels the argument conditional, whereas the primary labels it invalid. The challenger assesses the exact substitution at paper.tex:27-29 conditional on the invoked maximum-convergence lemma; the primary assesses the complete written argument including D001."
  ],
  "resolution": "The coordinator agrees that the substitution is exact conditional on maximum convergence. Under the current full-argument convention in evidence-and-verdicts.md, a conditional step cannot hide a failed dependency. D001 supplies a refuted lemma under paper.tex:7-10, so the complete argument remains invalid. Independently, m_n=n and X_{n,j}=1{j=n} satisfy every fixed-coordinate hypothesis but make the estimator error one for every n, refuting the exact theorem statement at paper.tex:21-23. The final judgment is invalid/refuted, with aggregate incorrect. The initial conditional/refuted response remains unchanged; this records a coordinator resolution of assessment scope, not a retraction by the challenger.",
  "generated_utc": "2026-09-07T14:39:19.230587Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "c6da022b7b938bcf793afd337416df3f8887d25065b094c6aec7c317368f7eb3",
      "assessment": "confirmed",
      "target_assessment": "The inference from the fixed-j tail limit at line 15 to the growing maximum tail limit at line 16 is invalid. With m_n = n and deterministic X_{n,j} = 1{j=n}, each fixed-coordinate tail eventually vanishes, while P(max_{j \u003c= n}|X_{n,j}| \u003e 1/2) = 1 for all n. Both listed premises hold on one common probability space, so this directly refutes the targeted inference and the prerequisite lemma's stated conclusion.",
      "downstream_assessment": "Use D001 supplies exactly the maximum-convergence assertion invoked at theorem lines 27-28. The estimator definition then transfers the same counterexample without modification: its error equals 1 for every n. The theorem's final algebraic deduction is sound conditional on maximum convergence, but the actual inherited assumptions do not supply it. The downstream theorem conclusion C001 is therefore false as stated, rather than merely awaiting a proof of its prerequisite."
    }
  ],
  "initial_response": {
    "artifact": "audit/05_adversarial/initial-7bdd85e78da77a40-f6169a1e24fc75d2b938ce6fb3b0114b1f8178b592837ade57a4a9cbbaa23c59.json",
    "sha256": "674f42bb92b48e70c0d5d9005c9bdad65943f3203b3d404fd602797f07f38285",
    "input_sha256": "f6169a1e24fc75d2b938ce6fb3b0114b1f8178b592837ade57a4a9cbbaa23c59"
  }
}
-->
