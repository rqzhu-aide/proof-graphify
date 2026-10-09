# Historical reference audit

This repository-only fixture preserves a complete legacy proofcheck audit and its
original evidence. It is excluded from skill delivery. Its validator hash predates
the current code. The stored HTML is a
historical snapshot, and `delivery-check` now reports `NONFINAL` and `stale`.
Do not use it as a current finalized example or copy its mathematical facts into
a real audit. A new release would require actual review under the current
protocol before publication.

## Contents

- `paper/paper.tex` contains a growing-maximum lemma and an estimator theorem
  that invokes it. The lemma promotes convergence for every fixed index to
  convergence of the maximum over a growing number of indices.
- `proofcheck-audit/` is the portable audit root. Its primary deliverable is
  `proofcheck-report.html`, beside its manifest. A Markdown export is derived from the
  same canonical report projection.
- `workbench/` contains reviewed compact annotations and calibration responses.
  Context packets and annotations belong outside the canonical audit root.
- The audit retains earlier ledgers, challenge responses, and the historical
  manifest needed to authenticate the saved evidence. Earlier evidence is
  historical provenance, not a newly performed check under the current protocol.
- Retired report snapshots were moved on 10 September 2026 to the maintainer's
  local `archived/proofcheck/2026-09-10-package-cleanup/` folder, outside this
  package and excluded from Git. It also preserves the complete original audit.
  This historical example remains self-contained; it does not need that archive.

## Reading the result

Start with the report's overall judgment, main reason, impact, and repair
outlook. The complete result records distinguish the written argument from the
statement's truth. A failed dependency proves that a derivation is unsupported;
refuting a downstream statement additionally requires a counterexample to that
specific statement. Read the final per-conclusion records to see which evidence
has actually been recorded.

In this historical example both statements are refuted. The blinded reviewer
found the deterministic array `m_n = n`, `X_{n,j} = 1{j = n}`: every fixed
coordinate is eventually zero, but each row maximum is one and the defined
estimator stays exactly one away from its target. The prior theorem assessment
was only `not_established`; its unchanged historical ledger shows that the
stronger current label came from new direct evidence. Both original first
responses and their explicit reconfirmations after the issue targets changed
remain preserved.

The earlier 7 September renewal uses challenge contract 3 and response schema 2.
Both reviewers received only their exact blinded packets and current response
instructions. That theorem reviewer labeled the local deduction `conditional`;
the final primary argument remains `invalid` under the complete-argument
convention because it consumes a refuted prerequisite. The report records this
actual difference and the coordinator's resolution, while preserving the first
response unchanged. Both reviews directly refute the theorem statement.

The subsequent source and reader repair required new declaration bindings and
actual primary re-review. Its fresh independent reviewers assess both complete
arguments as `invalid` and both statements as `refuted`. Current agreement
does not erase the earlier theorem disagreement: its original response and
resolution remain linked through superseded review history. The current
report names physical paper locations and exposes the line-15 premise,
line-16 failure, line-17 conclusion, and line-29 downstream use, separately
from the citation at lines 27 to 28.

The Paper overview first shows the manuscript lemma and theorem, with their
recorded dependency and qualified assessment summaries. Open either result
for its conclusions and evidence. The Detailed proof view connects assumptions,
definitions, and prerequisite results.
Inputs to one argument are used jointly; separately recorded argument routes
remain distinct. A refutation edge has a different
meaning from a failed support edge. Source links open stable inline excerpts,
so the evidence remains usable after the portable audit moves. Given
assumptions do not acquire a verified status merely by appearing in the graph.

Issue `I-001` records the failed growing-maximum inference. Its repair search
compares a stronger tail-control assumption with a restricted fixed-range claim,
including failed attempts, scientific cost, and required rechecks. The report
keeps the full evidence and result list available in print and with JavaScript
disabled. Its scope, historical finalization status, and non-formal qualification
remain visible.

The current challenge contract preserves each exact consumed blinded packet and
initial per-conclusion response, both judgment dimensions, and primary snapshot
before reconciliation. Renewed records link superseded reviews and their exact
prior reconciliation artifacts. The fixed receipt is
linked from the current ledger's `independent_check.initial_response`. This is
a provenance record of the declared fresh context, not automatic verification
of the identity or independence of the checker.

The primary maintenance review and its two-canary smoke test are disclosed in
`proofcheck-audit/audit/07_runtime/PRIMARY_REFRESH_1_4.md`; the renewed primary review is in
`proofcheck-audit/audit/07_runtime/PRIMARY_RENEWAL_2026_09_07.md`. Those earlier canary responses were
authored in an existing maintenance context. They are not held-out evaluation
results. Research-level release evaluation uses the repository's separate
`stat-proof-check/evals/` harness;
its candidate mathematical keys still require independent expert review.

The source-specific primary relevance review is in
`proofcheck-audit/audit/07_runtime/PRIMARY_USABILITY_REVIEW_2026_09_07.md`. After the final
unreadable auxiliary-context regression repair, the exact unchanged source,
obligations, inferences, counterexamples, and dependency use were reconfirmed
and recompiled. The latest review is in
`proofcheck-audit/audit/07_runtime/PRIMARY_CONTEXT_RECOVERY_2026_09_07.md`. A fresh packet-only
reviewer supplied new current-context initial responses; earlier responses and
reconciliations remain preserved. A separate historical two-result maintenance
exercise used fresh balanced calibration and independent paper responses.
That exercise is local-only and is not part of this fixture's evidence.

The initial proofcheck 1.5 renewal is recorded in
`proofcheck-audit/audit/07_runtime/PRIMARY_RENEWAL_1_5_2026_09_08.md`. A fresh
context fixed all five balanced calibration responses before grading; all passed.
Both units were then freshly extracted, scaffolded, fully re-reviewed and
compiled under the new receipt. Separate fresh packet-only reviewers supplied
the current independent responses. The written arguments remain invalid and
both exact statements remain refuted. All previous initial responses,
reconciliations, ledgers, calibration evidence and release history remain preserved.

The last historical validator-maintenance renewal is recorded in
`proofcheck-audit/audit/07_runtime/PRIMARY_SURGICAL_REVIEW_2026_09_08.md` and
`proofcheck-audit/audit/07_runtime/FINAL_SURGICAL_CONTEXT_2026_09_08.md`.
The complete source and mathematical evidence were re-reviewed with the same
inherited checker configuration and unchanged passing five-canary receipt.
Fresh extraction and the public annotation-renewal workflow updated the validator
context. Separate fresh packet-only reviewers then supplied the actual current
responses, preserved before reconciliation and bound without a judgment change.
Both arguments remain invalid and both statements remain refuted. All original
responses, reconciliations, calibration and source bytes are retained.

## Inspecting the historical fixture

From the repository root:

```bash
python stat-proof-check/scripts/proofcheck.py status --root tests/fixtures/reference-audit/proofcheck-audit
python stat-proof-check/scripts/proofcheck.py delivery-check --root tests/fixtures/reference-audit/proofcheck-audit
```

A newly finalized copy must report `FINAL` with `usable_finalization: true`. This
historical fixture reports `NONFINAL` because its recorded validator is
stale; both inspection commands therefore exit with status 1. The HTML report
records the historical snapshot's outcome and time; merely opening the file does
not rerun validation.

## Maintaining the example honestly

Keep retired presentation snapshots in the maintainer's local `archived/`
folder, outside the skill and repository distribution. Preserve a complete
original before compacting a copy, retain every linked mathematical and review
record, and finalize and delivery-check the copy before publishing it. A blanket
exclusion of `history/` would remove required evidence and must not be used.
Historical review notes retain the paths that existed when those reviews ran.

A renderer-only change does not require new mathematical review. On a copy with
current, valid evidence, publish the new presentation with:

```bash
python tests/fixtures/reference-audit/refresh_reference_audit.py publish <audit-copy>
```

The helper validates all non-report release gates before its first write. It
then uses the explicit report migration when needed, finalizes the HTML and
optional Markdown exports from one projection, and runs `delivery-check`.
Migration preserves the prior Markdown report, manifest, and finalization bytes
in report history. The helper never alters primary work hashes, calibration,
mathematical judgments, challenge dates, or first-response receipts.

If the protocol or mathematical inputs changed, explicitly revalidate or migrate
the copied audit, review affected primary source work, and preserve historical
records. Prepare exact current review assignments outside the audit root:

```bash
python tests/fixtures/reference-audit/refresh_reference_audit.py prepare <audit-copy> <new-packet-directory>
```

Give each fresh challenger only its `*.challenge.json` packet and the current
response instructions. Primary packets contain prior work and are not blinded.
After any semantic edit, regenerate the affected packet. Preserve the actual
initial response before reconciliation:

```bash
python stat-proof-check/scripts/proofcheck.py record-challenge --root <audit-copy> --unit-id <unit> --packet <consumed-challenge.json> --response <actual-initial-response.json>
python stat-proof-check/scripts/proofcheck.py bind-challenge --root <audit-copy> --unit-id <unit>
```

Record disagreements and the final reconciliation honestly. If an initial
response is missing, obtain a new real review; do not reconstruct it from the
mutable final ledger. The helper refuses to publish stale or incomplete evidence
instead of mechanically making it look current.

For an explicitly historical contract-1 or contract-2 audit, `publish` accepts
`--allow-historical-challenges` only to preserve that legacy evidence during
presentation migration. This does not upgrade it to contract 3 or claim a new
independent check. This historical fixture uses contract 3.

`stat-proof-check/tests/test_reference_audit.py` tests the saved evidence as it stands. Tests do
not silently refresh review hashes to make a failing historical fixture pass.
They also check packet read-only behavior, rejection of stale or missing review
evidence, preservation of mathematical records during presentation refresh, and
successful relocated HTML delivery.
