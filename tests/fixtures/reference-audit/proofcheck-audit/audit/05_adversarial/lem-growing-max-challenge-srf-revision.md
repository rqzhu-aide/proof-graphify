# Independent renewal of lem:growing-max

The reviewer used a fresh context with the challenge protocol and assigned complete packet. The exact first response was preserved before reconciliation. Previous reviews remain historical.

The fresh reviewer and retained primary analysis agree on the exact fixed-coordinate versus growing-maximum failure. The deterministic moving-coordinate array satisfies the normalized hypotheses and directly refutes C001. The new source-anchored I-001 assessment is accepted; no source, failure target or mathematical verdict changed.

C001: The proposed obligation preserves the source distinction between each fixed $j$ and the growing maximum. On a one-point probability space, take $m_n=n$ and $X_{n,j}=\mathbf{1}_{\{j=n\}}$ for $1\le j\le n$. For every fixed $j$, $X_{n,j}=0$ for every $n>j$, so the hypotheses hold. Yet $\max_{1\le j\le n}|X_{n,j}|=1$ for every $n$, giving $P(\max_{1\le j\le n}|X_{n,j}|>1/2)=1$. Thus line 16 does not follow from line 15, and the counterexample refutes C001 itself.

<!-- proofcheck-challenge-binding-v2
{
  "schema_version": 2,
  "unit_id": "lem:growing-max",
  "challenge_context_sha256": "4c896c54f344dbd74354d9e9c38f60a4d372e62abfb9faba7fbd07bb0f34b94e",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "incorrect",
  "reconciled_verdict": "incorrect",
  "artifact": "audit/05_adversarial/lem-growing-max-challenge-srf-revision.md",
  "disagreements": [],
  "resolution": "",
  "generated_utc": "2026-09-08T23:08:11.982959Z",
  "issue_assessments": [
    {
      "issue_id": "I-001",
      "target_contract_sha256": "a55282aebd9fabb477429cd8cfeab159f679748a19e859e6f1c9b894d3aab215",
      "assessment": "confirmed",
      "target_assessment": "The targeted inference at paper.tex:16 promotes fixed-coordinate tail convergence to convergence of a maximum over an increasing number of coordinates. The deterministic array $m_n=n$, $X_{n,j}=\\mathbf{1}_{\\{j=n\\}}$ has all fixed-coordinate tails eventually zero while the maximum tail at $\\varepsilon=1/2$ equals $1$. This directly disproves the targeted move under its stated premises.",
      "downstream_assessment": "The packet records that thm:main uses exactly this maximum-convergence conclusion. For its estimator $\\hat\\theta_n=\\theta_0+\\max_{1\\le j\\le m_n}|X_{n,j}|$, the same admissible array gives $\\hat\\theta_n=\\theta_0+1$ for every $n$. Consequently the dependency cannot establish consistency, and the stated downstream consistency claim is also refuted."
    }
  ],
  "initial_response": {
    "artifact": "audit/05_adversarial/initial-fef88974cf7442a7-058588ccb1752142804eb23cb34cf196b0440e00ec8c6b0ab094fbdacbaa2c7a.json",
    "sha256": "7c4e50592bc6b3e7fe99205f796fce05eb22d62b57ec798f18ceeb487d7d7629",
    "input_sha256": "058588ccb1752142804eb23cb34cf196b0440e00ec8c6b0ab094fbdacbaa2c7a"
  }
}
-->
