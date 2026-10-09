> Historical v2 reference retained from the baseline. Its workflow and completion requirements do not govern v3. Use [the v3 workflow](controller-workflow.md) and [graph authoring](graph-records.md).

# Legacy v1.5: Checked Statement Supplements

Load this optional contract only when a separate reviewer reconstruction can
establish a conclusion despite a defect in its written proof, or when a later
use needs an explicitly restricted version of a defective lemma. Ordinary
units keep their existing records and independent-review procedure.

## Preserve the two judgments

The existing conclusion `support`, `argument_status`, `dependency_closure`,
and issue links continue to describe the written argument. The weakest written
step still controls the unit verdict. Do not replace a failed step with a
successful reconstruction or call a false statement verified.

Author the reconstruction as separate ordinary `derivation` steps at the
relevant source location. Their literal checks must distinguish what is
printed from what the reviewer supplies. Existing move, premise, assumption,
risk, source, dependency and side-condition checks apply without relaxation.
The supplemental move must reach exactly the original normalized claim. It
cannot inherit a failed or unchecked proof move, unchecked dependency, open
risk, or assumptions outside the conclusion contract.

Add this optional object to its compact conclusion annotation:

```json
{
  "statement_support": {
    "support_step": "supplied-conclusion",
    "extra_conditions": [],
    "evidence": "Describe the particular derivation supplied here and why the written defect remains."
  }
}
```

The compiler creates `statement_support.schema_version: 1`, exact
`support.step_id` and `move_id`, and `target_contract_sha256`. It retains the
authored evidence and conditions. The target digest identifies the existing
conclusion and its source-locked assumptions. A short optional normalized
conclusion `reader_description` is display metadata, limited to 120 characters
on one line. Keep it faithful to the paper; it neither changes the claim nor
invents a theorem number.

`extra_conditions` must list exactly the distinct open side-condition texts
encountered in the supplemental backward support closure, in ledger order.
No extra condition permits `statement_status: established`; use `conditional`
for the restricted result. A full-domain counterexample remains `refuted`
even when a restricted supplement is supplied. Without extra conditions, a
verified reconstruction may establish the unchanged statement while the
written argument remains `gap` or `invalid`. The two support moves must differ.

## Preserve an actual supplemental review

Complete primary authoring and ordinary readiness first. Readiness may use
checked supplemental mathematics provisionally; it does not claim independent
acceptance or authorize publication. Acceptance metadata alone does not alter
the primary mathematical work context.

Preserve the initial blind written-proof response with `record-challenge`
before exposing the reviewer reconstruction. That first packet and response
remain unchanged. Then generate a separate optional packet:

```text
python "<skill-root>/scripts/proofcheck.py" packet --root "<audit-root>" --unit-id "<unit-id>" --mode statement-support --output "<outside-audit>/support-packet.json"
```

Have a fresh independent context inspect this packet's exact target,
assumptions, complete proposed move graph, prerequisites, and conditions.
It contains proposed reasoning, without the primary proof verdicts. A hash
or coordinator approval is not a review. Supply exactly this response shape,
with one assessment for every packet proposal:

```json
{
  "response_schema_version": 1,
  "unit_id": "lem:example",
  "packet_sha256": "<canonical_sha256 of the complete consumed packet>",
  "independence_level": "fresh_context_same_model",
  "assessments": [
    {
      "conclusion_id": "C001",
      "statement_support_sha256": "<exact proposal digest from packet>",
      "assessment": "accepted",
      "reason": "Explain the checked derivation, its exact target and its conditions."
    }
  ]
}
```

The exact `assessment` enums are `accepted`, `rejected`, and `unclear`.
Independence levels retain the ordinary contract. Use explicit LaTeX
delimiters for mathematical reasons and JSON escaping for backslashes.

```text
python "<skill-root>/scripts/proofcheck.py" record-statement-support --root "<audit-root>" --unit-id "<unit-id>" --packet "<outside-audit>/support-packet.json" --response "<outside-audit>/support-response.json"
```

This command authenticates the current packet, preserves packet and response
together in an immutable audit artifact, and attaches its hash reference to
`independent_check.statement_support_review`. The ordinary `bind-challenge`
then binds that reference with the reconciliation. It requires acceptance of
each claimed supplement. Rejection or uncertainty requires revising or
removing the proposed support and reconciling the actual judgment; never
change the preserved response to accepted. Final delivery requires both the
ordinary independent check and the current accepted supplemental response.

## Restrict a dependency use explicitly

An ordinary use still inherits the original conclusion judgment. To use the
checked restricted form, set `statement_support_sha256` to the exact derived
support digest in both the invoking compact dependency and its registry
`internal_uses` row. The existing original conclusion identity and contract
hash remain unchanged. Add this registry map for every extra condition:

```json
{
  "statement_support_conditions": [
    {
      "condition": "<exact extra-condition text>",
      "status": "satisfied",
      "evidence": "Explain why this particular use satisfies the condition.",
      "evidence_spans": [
        {"file": "paper.tex", "start_line": 12, "end_line": 12,
         "sha256": "<exact span digest>", "role": "use-site condition evidence"}
      ]
    }
  ]
}
```

The map is exact, with no missing, extra, or duplicate condition. Statuses
are `satisfied`, `not_satisfied`, `partial`, or `unclear`. Its current locked
evidence must lie in the dependent unit's source or recorded assumptions.
Every condition must be satisfied before the selected form supplies verified
availability. Existing compatibility checks still apply. No selected-use
status changes the broad lemma's original judgment. Pending supplemental
acceptance is allowed only in primary work, never as final availability.

## Checked proposal versus applied repair

An open or deferred issue may mark an exact proposed change
`verified_sufficient` only through an accepted review of that proposal as
well as its supporting derivation. Link the proposal using
`statement_support_ref: {unit_id, conclusion_id, sha256}`, where the unit is
the root affected result. Leave lifecycle and finding status open or deferred
as appropriate. Retain the failed manuscript move and its issue backlink.

The supplemental packet then includes the exact source-locked proposed edits.
Its response must additionally have `change_assessments`, one row per packet
change, with exactly `issue_id`, one-based integer `change_index`, its packet
`sha256`, `assessment`, and a substantive `reason`. Acceptance must establish
the sufficiency of that exact edit for its stated target and conditions.
Accepted proof support alone cannot verify unrelated repair prose. A candidate
proposal never supplies support by itself.

Actual resolution continues to require the existing archive-before-edit,
source revision, historical-current affected closure, fresh checking, and
resolution evidence. Checked sufficiency does not mean the manuscript was
edited, the issue is resolved, or the original statement was repaired.

## Renewal and history

A changed target, condition, mathematical context, proof support, or linked
proposal invalidates its old supplemental acceptance. Recheck the mathematics,
preserve any old active review reference in
`statement_support_review_history`, and clear only the active reference when
preparing its replacement. Keep the immutable old artifacts. Renew the ordinary
blind response if its inputs changed, then record a new supplemental packet
and response and bind the reconciliation. Never supersede missing or altered
prior evidence by restamping it. Repair archives automatically seal the
supplemental and initial responses needed to reconstruct prior support.

This remains a non-formal audit: mechanical checks enforce exact evidence,
review, and dependency bookkeeping; the reviewer must judge the mathematics.
