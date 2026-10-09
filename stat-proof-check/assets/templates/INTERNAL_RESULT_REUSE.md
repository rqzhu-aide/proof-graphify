# Compact annotation example: use an exact lemma result

Use this when a source step repeats a checked prerequisite conclusion. Suppose
a lemma establishes $\mathbb{E}[(\bar X_n-\mu)^2]=\sigma^2/n$ for positive
integers $n$ under a fixed iid law with finite variance. The theorem first
invokes that identity, then proves convergence. The invocation is `reuse`;
the subsequent limit argument needs its own `derivation` records.

The JSON blocks below are excerpts, not a complete annotation file. Start from
the current packet-bound scaffold, retain its other required fields, and
complete the source-specific risks, conditions, inputs and review. Example
IDs must be replaced with the exact IDs from that paper's packet and registry.

In top-level `dependencies`, mirror the reviewed direct use:

```json
{
  "id": "lem:variance",
  "use_id": "D001",
  "kind": "internal_result",
  "status": "verified",
  "needed_form": "$\\mathbb{E}[(\\bar X_n-\\mu)^2]=\\sigma^2/n$.",
  "compatibility_check": "The theorem invokes exactly the lemma's finite-n mean-square identity for the same iid sequence, mean, variance and sample average; its later limit keeps the law fixed.",
  "conclusion_id": "C001"
}
```

The consuming step has `mode: "reuse"` and `claim` equal to that exact
`needed_form`. Keep its authored rule and justification. Among its `inputs`:

```json
{
  "kind": "dependency",
  "reference": "D001",
  "role": "fact",
  "evidence": "The exact lemma conclusion supplies this finite-n identity for the same sequence and average.",
  "source_reference_id": "lem:variance",
  "source_reference_occurrence_id": "R-880e675344ef6f7a"
}
```

Here `kind` is `dependency`, and `compatibility_check` belongs to the top-level
dependency row. Do not add ledger fields `step_keys` or `issue_ids` there.
The registry separately binds the exact invoking `Sxxx` steps and its full
compatibility matrix. Prior-step inputs still require their own compatibility
checks. An identical resolved premise is reuse, not a new derivation.

Reconcile the actual source reference in `review.source_reference_dispositions`:

```json
{
  "occurrence_id": "R-880e675344ef6f7a",
  "target": "lem:variance",
  "command": "ref",
  "disposition": "internal_result",
  "evidence": "The first included theorem proof line invokes the exact finite-sample conclusion through the single D001 result use.",
  "dependency_use_id": "D001"
}
```

The corresponding `candidate_dependency_dispositions` row also uses
`disposition: "internal_result"` and `dependency_use_id: "D001"`, with the
packet's exact `candidate_id`, every associated `path_ids`, and evidence.
Do not use `use_id` in either review disposition. An assumption reference
remains `obligation_context` with a source-locked obligation input.

Run the existing aggregate `annotation-check`, then `compile-annotations`.
Verified status requires the current named conclusion, compatible assumptions,
and complete local evidence; copying these excerpts supplies none of those
judgments for another paper.

Use only the actual hypothesis or variable-domain facts needed for each input.
The complete `quantifier_scope` can include the result being checked. Keep that
target as obligation metadata; do not copy it into an assumed premise.
