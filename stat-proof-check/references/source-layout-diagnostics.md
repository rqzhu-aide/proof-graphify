# Legacy v1.5: Source layout diagnostics

Use this procedure when the read-only source check reports `review_required`
items or inventory review finds an unsupported proof boundary or association.
It concerns whether proofcheck can represent the supplied argument, not whether
that argument is mathematically valid.

## Inspect before checking mathematics

Run the helper on new or changed LaTeX source before calibration and mathematical
checking, using the same `--project-root`, `--additional-source`, and `--fls`
options as doctor and scaffold:

```text
python "<skill-root>/scripts/proofcheck_source_check.py" --paper "<source>" --input-kind latex
```

The helper prints Markdown by default; use `--format json` to inspect all
warnings, recognized ranges, and candidate headings. It writes no diagnostic
or audit files. Exit 2 means `review_required`; inspect its output before
dependent work. Exit 1 means `check_failed`; resolve the reported input or
environment problem first. Exit 0 (`no_layout_flags`) is not an acceptance
certificate.

Source-selection warnings also identify active literal `\includeonly` controls
and content following `\end{document}`. The parser retains candidate source
instead of choosing the manuscript's scope. Review whether the audit covers
the selected build or the full manuscript, and record source-backed exclusions
for inactive results before checking mathematics. Comments, verbatim text,
definitions, and inactive conditional branches do not supply active controls.

Inspect each reported location against the statement, surrounding source, and
rendered paper when needed. The helper reports parser association limitations;
a missing association does not establish an absent argument or a split proof.
Confirm whether the complete argument is present, what boundaries contain it,
and which formal result its labels identify. Two labels on one statement do
not create two proof obligations. A clean helper result also does not replace
the ordinary inventory review or prove mathematical completeness.

Keep the current local-proof rule: one complete proof environment per unit
or one uniquely targeted named-heading region with a recognized boundary.
`reviewed_manual` can correct a parser miss within that rule; it cannot join
separate proof regions or widen an environment past its closing delimiter.
If the inspected source requires that unsupported representation, stop the
affected audit work and explain the required source revision. Do not seek a
routine protocol waiver or mark the result as a mathematical gap merely to
proceed.

## Give an actionable rejection

Use a short plain-text or Markdown diagnostic, not an HTML proof report:

- **Title:** "Proofcheck needs a source-layout revision."
- **Result and location:** name the affected formal result, statement file and
  lines, and each relevant proof passage.
- **Observed cause:** say what the parser recognizes and which written passage
  the supported region cannot include. Separate observed source facts from
  an inferred intended association. State that this is a representation limit,
  with no mathematical verdict from this diagnostic.
- **Suggested revision:** give exact delimiter, heading, or reference edits
  that produce one complete region. For a confirmed split proof of one result,
  prefer enclosing all its parts in one explicitly targeted proof environment
  and retaining internal part headings. Preserve the mathematical text and
  existing result labels. Adding "Proof" to each separate part does not combine
  their regions.
- **Resume action:** rerun the source check, review the complete new association,
  then rebuild the affected source locks and continue the audit.

Test a proposed formatting revision on a temporary copy of the relevant project
before calling it checked. Rerun the helper and inspect the resulting inventory
for the exact full boundary and target; confirm that all intended passages are
included. Parser acceptance checks representation only. Identify the tested
copy as modified source and leave the authoritative manuscript untouched unless
editing it is already authorized. If no supported minimal revision has been
tested, describe the suggestion as untested.

## Preserve work for resumption

If an audit workspace exists, keep it NONFINAL and record the observed limit
and affected unit IDs in `audit_scope.source_or_parser_limits`. Supply source
evidence in any matching `parser_warning_reviews`; helper-only observations
do not create new parser warnings. Checkpoint a specific next action through
the existing command before
any source change. Preserve the exact manuscript snapshot, prior records, and
unaffected work. Do not manufacture a ledger verdict or edit snapshot hashes
to suppress the blocker. With no audit workspace, retain the concise diagnostic
and proposed revision without creating completion state.

After an authorized manuscript revision, follow the existing
[source renewal and resume procedure](workspace-and-resume.md#resume-contract):
rescan, reconcile the inventory and dependencies, and re-extract affected work
against the revised source. A patch or successful parser check alone does not
resume a mathematical verdict or complete the audit.
