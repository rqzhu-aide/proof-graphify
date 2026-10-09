# Legacy v1.5: Markdown report format

This file defines the final user report and the release checks. Challenger
semantics remain in [challenge-protocol.md](challenge-protocol.md).

## Report location

Keep the canonical report at `audit/06_reports/FINAL_REPORT.md`. Reserve the
top level of `audit/06_reports/` for that report, `ISSUE_SUMMARY.md`, and
complete manifest-declared user-facing reports. Keep drafts and working notes
elsewhere.

An additional delivered report must be declared in the manifest
`report_deliverables` list with its `Rxxx` ID, role, path, current hash,
issue IDs, and overall verdict. Its four canonical sections and scalar values
must match `FINAL_REPORT.md`; its title and brief orientation prose may
differ.

Keep the `NONFINAL SCAFFOLD` notice and the title
`NONFINAL Proof-Check Working Report` until
`completion.final_report_ready` is true. A final report uses the sole title
`Final Proof-Check Report` and contains no scaffold marker.

## Four-section report

The report is a concise projection of the sealed audit records, not a second
evidence store. It has exactly four H2 sections, in this order.

### Summary

Use exactly four answer-first fields, generated from the canonical assessment,
conclusion judgments, issue log, and repair records:

- `Overall judgment`
- `Main reason`
- `Impact on paper conclusions/results`
- `Repair options and difficulty`

The generated values name affected target conclusions and explain repair
difficulty from the existing repair scope, assumption cost, claim cost,
verification status, and required rechecks. Do not invent another repair score
or schema.

### Results and impact

Generate one row for every in-scope conclusion:

| Result | Conclusion | Contract | Argument | Statement | Dependencies | Later use | Evidence | Issues |
|---|---|---|---|---|---|---|---|---|

`Conclusion` contains both the `Cxxx` ID and the normalized mathematical
claim. `Later use` is derived from outgoing dependency-use applicability, not
authored in the ledger. `Evidence` gives the source location and supporting
step/move. Full dependency rows remain in `DEPENDENCY_REGISTRY.json`.

### Findings and repairs

Generate one compact block per canonical issue. Each block states:

- issue severity, lifecycle, confidence, and whether it is load-bearing;
- exact failure location, source quotation, failed move, and why it fails;
- the affected paper results with their current argument and statement status;
- repair outlook, concrete options, scientific cost, and required rechecks.

Translate the existing repair fields into ordinary language. A local step edit
is localized; a unit-statement change requires downstream rechecks; a
cross-unit or global repair has broader reach. State stronger assumptions,
changed regimes, narrowed scope, weakened rates, lost uniformity, or weaker
guarantees directly.

Do not render raw JSON, hashes, premise arrays, compatibility matrices, or
component maps in this section. They remain in the canonical records.

### Scope and assurance

Put protocol identity, source revision, exact scope sets, confidence,
limitations, finalization path, independent-check levels, and declared
deliverables here. Include the compact independent-verification table:

| Result | Check status | Independence | Challenger verdict | Final verdict | Reconciliation |
|---|---|---|---|---|---|

If external reports are declared, list their ID, role, path, issue IDs, and
overall verdict. Their stored hash remains in the manifest.

Include the non-formal assurance boundary. A passing gate means the recorded
source, scope, atomic checks, dependencies, issues, challenges, and report
passed mechanical closure. It is not a proof-assistant soundness guarantee.

## Generate and release

Generate the issue summary and canonical report projections:

```bash
python "<skill-root>/scripts/proofcheck.py" checkpoint --root "<audit-root>" --clear-active-unit --next-action "Run final issue reconciliation and finalization."
python "<skill-root>/scripts/proofcheck.py" issues --root "<audit-root>" --write-summary --write-report-views --final
python "<skill-root>/scripts/proofcheck.py" sync-views --root "<audit-root>"
python "<skill-root>/scripts/proofcheck.py" finalize --root "<audit-root>"
python "<skill-root>/scripts/proofcheck.py" delivery-check --root "<audit-root>"
```

`issues --write-report-views --final` rewrites the four-field summary,
`Results and impact`, `Findings and repairs`, independent verification, and
declared deliverables. It does not rewrite authored scope or limitations.

`finalize` writes `FINALIZATION.json` with the gate result and sealed
artifact manifest. `delivery-check` is the final read-only release gate.
Deliver the report only when it returns `delivery_status: FINAL` and
`usable_finalization: true`.

After any source, evidence, registry, issue, scope, report, or validator
change, rerun finalization. A prior finalization is not evidence for changed
artifacts.

## Final language

Use "verified within the stated scope" only after all gates pass, and define it
immediately as a non-formal audit judgment. Prefer "no defect found under the
stated non-formal protocol."

Do not say that the paper or theorem is correct when only selected units were
checked or a load-bearing dependency remains unchecked. Do not infer that a
theorem is false merely because its written proof is invalid. Report argument
status and statement status separately.
