> Historical v2 reference retained from the baseline. Its workflow and completion requirements do not govern v3. Use [the v3 workflow](controller-workflow.md) and [graph authoring](graph-records.md).

# Legacy v1.5: Independent Verification Protocol

Every unit in `audit_scope.in_scope_units` needs a fresh independent check.
`critical_units` controls priority, never coverage. The challenger reads this
protocol and its exact packet, without the primary reasoning or conversation.
Use `fresh_context_same_model`, `different_model`, or `independent_human` as
the declared independence level. For an S0 issue, prefer another model or a
human when available. These declarations do not prove runtime independence.

Use mathematical derivations; do not run numerical experiments or computational
searches. Explain a substantively examined but unresolved conclusion as
**Unable to verify**, using the existing `unclear` verdict.

## Build the blinded packet

The coordinator first passes the
[primary readiness checkpoint](issues-and-repairs.md#primary-readiness-before-independent-dispatch).
Write the complete blinded packet outside the audit root:

    python "<skill-root>/scripts/proofcheck.py" packet --root "<audit-root>" --unit-id <unit-id> --mode challenge --output "<challenge-packet.json>"

It contains the locked statement and proof, proposed normalized obligation,
complete direct prerequisite contracts, relevant later uses, neutral issue
targets, and risk aspects. Internal contracts include resolved applicability,
locked statement and conclusion excerpts, and relevant context; repeated uses
share one contract. A contract hash alone is not prerequisite evidence.

Primary normalization verdicts and their rationale are excluded, together
with primary severity, compatibility judgments, proof verdicts, finding prose, and
repairs. Independently compare the proposed obligation with the exact source,
then check each conclusion, its premises, prerequisite applicability, material
side conditions, and adversarial cases. Read separately any external source
evidence named by the packet when needed for that application. Text sources
appear as complete locked excerpts beside the authored contract and hypothesis
mapping. Compare the mapping with the actual source, including inherited
conditions, rather than assuming that the transcription is complete. For PDF
evidence, inspect the hash-locked document at its recorded locator. Unavailable
essential theorem text or an omitted source hypothesis leaves that application
unresolved until it has been inspected and mapped.

## Preserve the first response before reconciliation

New audits use `protocol.challenge_contract_version: 3`. Write a response
outside the audit root, assessing exactly every packet conclusion. This small
example illustrates the shape; substitute the actual conclusion and reason:

```json
{
  "response_schema_version": 2,
  "unit_id": "lem:example",
  "independence_level": "fresh_context_same_model",
  "challenger_verdict": "verified",
  "conclusions": [
    {
      "conclusion_id": "C001",
      "verdict": "verified",
      "argument_status": "valid",
      "statement_status": "established",
      "decisive_reason": "Reflexivity proves x=x for the arbitrary real x introduced in the statement.",
      "source_refs": [
        {"packet_pointer": "/source/proof", "start_line": 5, "end_line": 5}
      ]
    }
  ],
  "issue_assessments": []
}
```

Use the unit-status vocabulary for each `verdict`; `not_checked` cannot
complete a challenge. The unit verdict is the weakest conclusion verdict in
the existing order: incorrect, gap, unclear, conditionally verified, verified.
Record `argument_status` separately as `valid`, `conditional`, `gap`, `invalid`,
or `unclear`, and `statement_status` as `established`, `conditional`, `refuted`,
`not_established`, or `unclear`. An invalid written argument need not refute its
statement. Do not infer either dimension from the aggregate verdict or prose.
Each `source_refs` pointer must select a canonical locked excerpt under
`/source`, `/dependencies`, or `/issue_triggers`; the selected range must lie
inside its authenticated lines. Operational notes, even with copied `lines`,
are not source evidence. Use `/source/statement`, `/source/proof`, or an exact
prerequisite excerpt pointer as appropriate.

Ordinary units have no issue assessments. When neutral issue targets appear,
assess exactly those IDs with `issue_id`, `assessment` (`confirmed`,
`not_confirmed`, or `unclear`), `target_assessment`, and `downstream_assessment`.
Do not supply machine-owned target hashes. Explain the target and consequence
independently, including repaired or historically retained material issues.

Use explicit LaTeX delimiters for formulas in new mathematical reasons:
`$...$` or `\(...\)` inline, and `$$...$$` or `\[...\]` for display math.
Escape backslashes in JSON strings, for example
`"$\\Pr(A_n) \\to 0$"`. Preserve the exact mathematical content.

A generic assertion that every step was checked cannot replace the
conclusion-specific reason and exact source references. Structural validation
does not grade the truth of that reason. Keep the account concise; a second
atomic ledger is unnecessary.

Before inspecting the primary judgment or reconciling disagreements, run:

    python "<skill-root>/scripts/proofcheck.py" record-challenge --root "<audit-root>" --unit-id <unit-id> --packet "<challenge-packet.json>" --response "<initial-response.json>"

The command preserves the exact consumed packet and response in a
deterministically named `initial-*.json` artifact under `audit/05_adversarial/`.
It also captures the existing primary conclusion judgments and support before
reconciliation, outside the blinded packet. It binds that artifact's exact hash into the ledger before publication, and
refuses an existing destination. Never edit the initial artifact or remove its
ledger reference. A new
source or relevant contract requires a fresh check under its new context;
the earlier response and its bound reconciliation remain historical evidence
linked through the new initial artifact's `superseded_review`. Routine progress metadata
does not require another check. Original packet identity is preserved even
when reconciliation changes the primary judgment.
If reconciliation recompiles the same unit, retain the ledger's exact
`independent_check.initial_response` reference along with the initial artifact.
Do not reset that historical evidence with the new primary verdict.

## Reconcile and bind

After fixing the first response, compare it with the primary result. Record
source-anchored disagreements, their substantive resolution, and the explicit
`reconciled_verdict` in the ledger's `independent_check`. The reconciled verdict
must equal the final primary unit judgment. Revise and recheck the primary
ledger first when the resolution changes its mathematics.

For contract 3, author one JSON file outside the audit root with exactly
`reconciliation_schema_version: 1`, `unit_id`, `status`, `reconciled_verdict`,
`conclusions`, `disagreements`, `resolution`, and `issue_assessments`.
The conclusion rows use the response-schema-2 fields above, including each
reviewer's final `decisive_reason` and exact `source_refs`. Cover every conclusion
and issue target once. Do not fill missing judgments by copying a default verdict.

    python "<skill-root>/scripts/proofcheck.py" submit-reconciliation --root "<audit-root>" --review "<reconciliation.json>"

Use `agreed` with no disagreements and empty resolution; `resolved` with explicit
disagreements and a substantive resolution. Both require each submitted judgment
to match the rechecked primary ledger. For `unresolved`, record the disagreement,
use `reconciled_verdict: not_checked` and empty resolution, and retain explicit
provisional conclusion judgments. It records an unfinished check, never FINAL.
Submission derives the narrative, locations and binding fields, then publishes
artifact and ledger together. It preserves the first response and primary
judgments, retains prior reconciliation artifacts, rejects changed inputs, and
returns unchanged on an identical successful retry.

Manual artifacts and older contracts retain
[CHALLENGE_ARTIFACT.md](../assets/templates/CHALLENGE_ARTIFACT.md) followed by
`bind-challenge --root "<audit-root>" --unit-id <unit-id>`. Replace its scaffold
notice and author the actual reconciliation fields. The preserved first response
supplies independence level and challenger verdict on both routes.

Binding reads the preserved initial response, checks its current mathematical
inputs and already recorded hash, validates reconciliation, and derives final
coverage, target hashes, ledger and artifact hashes, and time. A
changed initial artifact cannot be restamped. Binding and full freshness checks
compare each initial conclusion ID, support verdict, argument status, and
statement status with the final primary result. Any changed judgment or primary
support requires explicit disagreement and substantive resolution; equal
aggregate verdicts do not hide opposite conclusions. If issue assessments change
during reconciliation, record the disagreement and its resolution. An agreed
check has identical challenger, reconciled, and final primary unit verdicts,
with no disagreements, and equal recorded per-conclusion judgment dimensions.

The final artifact and ledger update use the existing transaction lock.
Do not edit them while binding runs. Finalization checks every in-scope unit,
the initial evidence required by its contract, exact issue coverage, current
packet context, final artifact binding, and reconciliation. An unavailable
challenger leaves the required audit NONFINAL.

## Historical compatibility

When separate reviewer proof support is claimed, preserve the ordinary blind
response first, then follow the optional
[statement-supplement review](statement-support.md#preserve-an-actual-supplemental-review).
Its immutable acceptance supplements this check; it never replaces it or
rewrites the initial written-proof judgment.

An absent challenge-contract field, or version 1, identifies the historical
protocol without preserved initial responses. Version 2 uses response schema 1
and records a per-conclusion verdict, but no separate statement judgment. Read
that missing dimension as not recorded; do not retroactively fill it in.
Presentation upgrades do not manufacture first responses or certify independence.
To adopt the new contract on a repair working copy, explicitly set
`protocol.challenge_contract_version` to `3`, renew each affected initial
response using schema 2, reconcile, and finalize through the ordinary workflow.
Preserve old references so renewed records can link their history. The upgrade
does not convert a historical judgment into a fresh review. Declared reviewer
or context identities describe available provenance, not runtime attestation.
