# Workflow revision, October 1, 2026

Proof-check and shared core are version 2.3.7. Proof Graphify is version 3.1.14. The useful statement, source, mathematical display and graph functionality from the preceding release is retained. The revision follows the [handoff](proofcheck-workflow-revision-handoff.md).

## Implemented behavior

- Attaching or changing a reviewer qualification preserves prepared primary work that does not consume that qualification. This includes source comparisons, primary checks, and coverage/findings-only submissions. Scope, source, protocol, explicit full-audit bindings, independent assignments and reconciliation remain guarded. An old rejected request still returns its saved receipt; retrying unchanged response bytes uses a new request ID.
- Verified source-only independent reviews no longer become stale solely because coordinator coverage is added or edited. Historical recovery is a read-only comparison limited to actual coverage drift. Original packets, bindings, responses, outcomes and findings are not rewritten. Changed mathematical inputs remain consequential, and missing coverage still prevents completion.
- Independent guidance asks for full substantive reasoning within coherent route judgments. Separate conclusions, routes, local defects and counterexamples retain separate treatment when needed. There is no judgment quota. Mapping corrections preserve the original response and unresolved concerns; fabricated records and altered scientific conclusions are not mapping repairs.
- Immutable boundary source reviews can certify character intervals within stored excerpts for each written argument. Full page evidence stays available. Disjoint segments and continuations are required; legacy reviews retain whole-anchor meaning. Equivalent interval unions and cosmetic argument labels preserve freshness. Changed selectors need new source review evidence. First use adds the `reviewed-proof-spans/1` feature so older readers reject unsupported semantics.
- CLI help identifies legal packet roots and owning item/part targets. Reviewer-profile reuse and current working-report checkpoints are explicit in workflow guidance.

## Evidence

The four qualification-only failures from the original RF-HTE run were reconstructed at revision 54 in separate disposable databases. All four original response byte streams were accepted with fresh request IDs. Each original rejected request still returned its unchanged rejection receipt.

Read-only comparison of the harvested audits found:

| Audit | Before | Revised assessment | Effect |
| --- | --- | --- | --- |
| RF-HTE | 321/365 current obligations | 329/365, still incomplete | 12 saved checks recover solely from coverage drift: six supported and six gap outcomes |
| Previous distributional-RL audit | 239/239, complete | 239/239, complete | Existing completed scope and limitations preserved |

Seven RF-HTE checks with other changed inputs remain noncurrent. Original database hashes, record counts, findings, source limitations, qualifications and publication history remain unchanged. Validation reports no structural errors. These are software compatibility checks, not a fresh mathematical audit.

The final complete shared-core suite passed 1,471 tests with one optional browser test skipped. The final focused integration lane passed 210 tests with one skip, and the installer lane passed 22 tests. Graphify's broader suite passed 381 tests with one skip. An earlier run overlapped implementation and failed stale bundle inventory/identity expectations and the missing test-map entry; those were corrected before the final complete run.

Both generated bundles contain 46 files, have identical wrappers, and use source identity `17a83ead76284ed5cbc134013c7552252759ecc092182dd839e2a5e6c1bb185e`.

Browser inspection checked the regenerated revision-144 RF-HTE report's incomplete status, counts, theorem formulas and captured PDF source link. Graphify statement selection, prerequisite navigation, source expansion and search worked. Sized norm bars and their scripts rendered correctly from all four installations. The optional browser-test skip is not counted as this inspection.

## Installation and remaining live validation

Both skills were installed into the user-wide `.agents/skills` and `.claude/skills` roots with recoverable backups. Fresh processes verified package versions, bundle integrity and identity in all four locations. Graphify creation, public editing, rendering and export passed independently on both surfaces. Claude's explicit-invocation policy was preserved.

The separate test runner now preserves participant history and unique phase logs, prompts, exit codes and elapsed times. Status and waiting inspect each participant's latest phase and prefer recorded exits to process IDs. A harmless three-slot fixture with two follow-ups verified all participants were harvested once and all 18 phase artifacts retained. Active model execution time remains unknown; wall time is not reported as active time.

A fresh full-scope RF-HTE test was launched with both original PDFs, the same Claude model/effort and prescribed independent-review isolation, using the corrected runner in a new workspace. It exited after three wall-clock seconds with Claude's session-limit message, reporting a reset at 11:10 a.m. America/Chicago. No audit database or examination was created. Therefore full live completion and the planned live interruption/resume check remain unverified. The mechanical interruption/replay tests do not substitute for that observation.

Local evidence is retained outside the repositories under `../audit-reports/revision-2026-10-01/`; runner fixtures and backup receipts are under `../audit-reports/implementation-2026-10-01/harness/`. Key files are `primary-replays.json`, `captured-freshness-comparison.json`, `installed-release-independent-receipt.json`, `browser-checks.md`, and `live-validation.md`. The live retry instructions preserve the blocked attempt and reuse the frozen candidate. No automatic retry is scheduled.
