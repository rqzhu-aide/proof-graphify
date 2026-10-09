# Independent source review for lem:growing-max

The following mathematical reasons are transcribed from the genuine preserved response for the exact current blinded packet. Earlier first responses remain immutable.

## C001
The final packet's obligation faithfully preserves paper.tex:7-10: every fixed j converges to zero in probability, m_n tends to infinity, and the claimed conclusion controls the maximum over 1<=j<=m_n. These mathematical conditions and the submitted proof remain unchanged from the context previously examined by this checker. They admit the following counterexample on a one-point probability space: set m_n=n and X_{n,j}=1 if j=n and 0 otherwise, for 1<=j<=n. For every fixed j, X_{n,j}=0 for all n>j, so the required convergence holds. Yet every row maximum equals 1, and its exceedance probability at epsilon=1/2 is identically 1. Thus C001 is refuted as a statement under its exact assumptions. Proof line 15 correctly restates fixed-j convergence, but line 16 incorrectly extends those separate limits to a growing maximum. The inference at line 17 would be valid if line 16 held for every epsilon>0, but the counterexample makes that premise false.

## Issue I-001
The exact current target at /issue_triggers/0/target_contract/current_target/source_anchor is the growing-maximum inference in paper.tex:16. Its premises are the fixed-j tails at line 15 and m_n tending to infinity at line 9. The hypothesis contracts and lemma-conclusion contract accurately record those scopes. With m_n=n and X_{n,j}=1{j=n}, both premises hold while P(max_j|X_{n,j}|>1/2)=1 for every n. Hence the targeted inference and its claimed lemma conclusion are false. The final supplied target contracts have no mathematical changes requiring a different assessment.

The current contract at /issue_triggers/0/target_contract/contracts/2 records thm:main/C001, anchored to paper.tex:23-24, with the inherited conditions and hat theta_n=theta_0+max_j|X_{n,j}|. The same admissible array makes hat theta_n-theta_0=1 identically and directly refutes that downstream consistency conclusion. The dependency-use contract and /dependencies/downstream_internal_uses identify thm:main/D001 as requiring exactly the false maximum-convergence conclusion. Therefore the dependency cannot justify the downstream proof, and the estimator calculation independently refutes the downstream statement. This direct refutation is not inferred solely from the failure of a cited lemma.

Initial response record: `audit/05_adversarial/initial-fef88974cf7442a7-b8ce091439e1a1031770a84095a3ebef584dbeb0dc7630fb59a935c07f4b6769.json`.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "lem:growing-max",
  "challenge_context_sha256": "d2f436d11e8632a8f93bdf48a909551a1ab9df7a537ac1aebe16741a7e665a68",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "incorrect",
  "reconciled_verdict": "incorrect",
  "artifact": "audit/05_adversarial/lem-growing-max-challenge-1.4.md",
  "disagreements": [],
  "resolution": "",
  "generated_utc": "2026-09-05T02:20:02.813421Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "a55282aebd9fabb477429cd8cfeab159f679748a19e859e6f1c9b894d3aab215",
      "assessment": "confirmed",
      "target_assessment": "The exact current target at /issue_triggers/0/target_contract/current_target/source_anchor is the growing-maximum inference in paper.tex:16. Its premises are the fixed-j tails at line 15 and m_n tending to infinity at line 9. The hypothesis contracts and lemma-conclusion contract accurately record those scopes. With m_n=n and X_{n,j}=1{j=n}, both premises hold while P(max_j|X_{n,j}|\u003e1/2)=1 for every n. Hence the targeted inference and its claimed lemma conclusion are false. The final supplied target contracts have no mathematical changes requiring a different assessment.",
      "downstream_assessment": "The current contract at /issue_triggers/0/target_contract/contracts/2 records thm:main/C001, anchored to paper.tex:23-24, with the inherited conditions and hat theta_n=theta_0+max_j|X_{n,j}|. The same admissible array makes hat theta_n-theta_0=1 identically and directly refutes that downstream consistency conclusion. The dependency-use contract and /dependencies/downstream_internal_uses identify thm:main/D001 as requiring exactly the false maximum-convergence conclusion. Therefore the dependency cannot justify the downstream proof, and the estimator calculation independently refutes the downstream statement. This direct refutation is not inferred solely from the failure of a cited lemma."
    }
  ],
  "initial_response": {
    "artifact": "audit/05_adversarial/initial-fef88974cf7442a7-b8ce091439e1a1031770a84095a3ebef584dbeb0dc7630fb59a935c07f4b6769.json",
    "sha256": "135426ab140d2f47331ff640eb8d1b22721b9039ea346d84475f318cfb002a1e",
    "input_sha256": "b8ce091439e1a1031770a84095a3ebef584dbeb0dc7630fb59a935c07f4b6769"
  }
}
-->
