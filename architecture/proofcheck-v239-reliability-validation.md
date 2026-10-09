# Workflow reliability implementation validation

Date: October 3, 2026. Status: implemented and validated; installed on both requested user surfaces.

The [revision handoff](proofcheck-v238-reliability-handoff.md) is implemented in the existing three-stage workflow. GPT-6.1 Sol workers with xhigh reasoning handled separate source-grounding, evidence-maintenance, and intake/recovery scopes. The coordinator reviewed the interfaces, corrected integration regressions, and owns the release validation. These execution choices are test provenance; the shipped workflow has no agent or model requirement.

Release versions are proof-check/core 2.3.9 and Proof Graphify 3.1.16. Both generated bundles contain the same 48 shared-core files, with source identity `770c4f91f9bcc8c4f8a05002f68aa877798b8c42fa12011f3e1ee2f6040eb25c`. Storage, packet and scientific record contracts have not changed. Graphify retains its selective overview workflow and receives the shared backend update.

Local raw evidence is in [the implementation evidence folder](../../audit-reports/reliability-implementation-2026-10-03). Portable regression tests are committed with the code and do not depend on that folder.

## Implemented behavior

| Defect | Result and focused evidence |
| --- | --- |
| WF-01 | Routine review requires source associations on required written-proof arguments, groups and applications. Arguments retain reviewed boundary checks; supporting derivations may be elsewhere in the manuscript. `test_workflow_grounding_policy.py` covers missing links, valid external-to-proof support, supplied routes, focused readiness and unknown assessment. |
| WF-02 | Newly recorded bindings may preserve strictly additive source links only when their exact source extent was already delivered and consumed. Original pins and digests remain intact. `test_workflow_evidence_maintenance.py` includes independent-delivery versus coordinator-only evidence, source and condition changes, unmarked histories, export metadata, and SQLite backup/reopen. There is no new full-history JSON importer. |
| WF-03 | An unresolved explicit proof selection requests boundary recovery instead of creating whole-page coverage work. Existing absent selectors retain legacy semantics. Reviewed-span, coverage and grounding tests cover shared-page and stale-selection behavior. |
| WF-04 | Untouched scaffold rows are omitted; placeholder-only intake saves no scientific records. Useful drafts and authored mixed responses remain valid. Unchanged authorized continuations preserve the existing draft, and receipts distinguish saved work from satisfied tasks. Intake tests cover interruption, replay, malformed rows, supporting-check links and changed-input negatives. |
| WF-05 | New successor writes reject superseded ancestors and duplicate branches, while same-author draft completion and distinct current opinions remain supported. Existing historical records are readable. Transactional and focused recovery tests cover direct writes and controller submissions. |
| WF-06 | Ordinary compatibility preparation uses stage eligibility. Explicit investigations record purpose and limitations privately. Tests cover global selection, old response intake, source-only packet privacy, executable size retries and one scientific assessment per preparation. |
| WF-07 | Coordinator instructions require one bounded discovery of an actually available reviewer route, with available, unavailable or unknown recorded truthfully. This is an instruction correction, not automatic execution discovery. |

The exact mapping instructions also address C-01/C-02: use the actual saved response and judgment indices, preserve original bytes, and retain real reviewer authorship for corrections.

## Integration corrections

Preserved audits exposed an overly strict first implementation of WF-01: a supporting derivation could be outside the argument's proof span. The corrected rule uses each group's or application's own source links, matching the existing review-mapping contract. A portable regression now demonstrates successful mapping of such support without rewriting the independent return.

Focused preparation initially inherited unrelated full-audit coverage guidance. It now builds a focused projection from the same assessment while retaining full facts for the stage gate. Compatibility diagnostics also retain executable `work list` commands and exception flags in size retries.

Cross-review found that a terminal predecessor ID could still be referenced at an old version after draft completion. New branches now require the prospective current pin under the writer lock. An existing same-author draft still preserves its inherited predecessor pin. Direct-write and saved-controller-packet regressions verify rejection with no scientific writes, along with legitimate current-pin and inherited-pin continuations.

One plan detail changed to avoid a storage migration solely for a label: an unchanged-only draft continuation is stored as `needs_revision`, with `no_change: true`, `UNCHANGED_DRAFT`, exit 0 and no scientific commit. The draft remains unfinished. Exact replay returns the original receipt.

## Preserved cases and limits

All 18 preserved databases were assessed read-only before and after the revision. File hashes, scientific revision numbers, progress, record-version counts, and every task's state, outcome and freshness were identical. Original files remained unchanged. See [comparison](../../audit-reports/reliability-implementation-2026-10-03/preserved-comparison.json).

New scheduling readiness is deliberately stricter where old graph records lack usable source links. The completed Claude 2.3.5 distributional-RL audit retains its scientific results but has 22 missing-link blockers before new staged work or finalization. The completed DS4 audit remains ready after the locality correction. An older RF-HTE audit adds one missing-link blocker. No historical check is silently rebound or granted fresh credit. An inferred or unavailable prerequisite must retain its limitation; a convenient manuscript location must not be invented to pass readiness.

The renewal-heavy RF-HTE 2.3.8 database was inspected and copied for a rejected-write test. Its 726 checks include 327 superseded checks and 22 stale terminal checks. Recovery guidance references five terminal checks across four tasks, with zero ancestor references. A proposed ancestor successor was rejected with actual current candidates, without changing revision, records or bindings. This demonstrates bounded recovery authorization, not completion of the unfinished paper. See [terminal recovery evidence](../../audit-reports/reliability-implementation-2026-10-03/terminal-recovery/results.json).

## Validation and release record

| Check | Result |
| --- | --- |
| Complete shared-core suite, final identity | 1,632 tests passed, one platform skip; `shared-suite-release.log` |
| Complete proof-check package suite | 1,071 tests passed, one platform skip; `proofcheck-suite-final.log` |
| Complete Graphify suite, final identity | 381 tests passed, one platform skip; `graphify-suite-release.log` |
| Proof-check installer suite | 22 tests passed; `installer-suite.log` |
| Exact final instruction/package structure | Six tests passed with unchanged reading budgets; `instruction-structure-release.log` |
| Both skill frontmatter validators | Passed |
| Final source and both bundles | Byte-identical, verified by the existing builder |
| Installed runtimes | Four isolated imports/version checks, two Graphify edit/render smokes and two proof-check freeze/build smokes passed |

The proof-check package run began before the last acceptance-only correction. Its sole shared-core-facing module, `test_skill_structure.py`, was rerun on the final candidate; the full final shared-core suite covers the changed acceptance behavior. No broad suite failure remains. Expected error text in legacy negative tests is not a failing test.

The bounded fresh exercise used a short manuscript with a proposition and a prerequisite. Its first checkpoint preserved one substantive draft and 8/22 completed obligations, plus a working HTML. That checkpoint used identity `4039dc4bd66606a33cc88b712116d17e86d5aab26d18503b648a176090248752`. Primary continuation and independent packet preparation used `87d141787eb5b054369625c324e4c1eb4909e1ecf96f2c89bd70bde42aa65647`; submission, mapping, reconciliation and final delivery used the final identity above. Candidate changes did not trigger mathematical repetition or qualification churn.

The fresh checker received only two calibration cases, mathematical guides and the two neutral source assignments. Its actual context continuity and exposure are saved. Both real returns were mapped unchanged and reconciled without redispatch. The same saved primary draft completed at version 2. The exercise finished at revision 19 with all 22 obligations current, no drafts, no successor renewals, and no formula diagnostics. The coordinator independently verified reviewer blob equality, completion, producer identity and report hash. See [verification](../../audit-reports/reliability-implementation-2026-10-03/behavior-root-verification.json) and [HTML](../../audit-reports/reliability-implementation-2026-10-03/behavior/proof-check-conditional-normalization/report.html).

The run was not friction-free. It corrected a helper's record lookup, an early application-template request and an invalid boundary state without repeating unchanged attempts. A global return cited an anchor absent from that assignment's delivered context. The retained `WRITE_SCOPE` response was recovered through the documented current direct primary packet and authored check path; local examinations and independent returns remained current. These bounded authoring/context corrections remain visible in the saved artifacts. The exercise does not prove that agents will never make such mistakes.

Stage 3 passed automated representation, geometry and formula acceptance. Browser screenshot inspection was not performed because the browser policy blocks local file URLs; no workaround was used. Stage 3 failure/resume behavior is covered by the full finalization and release-resume suites.

Both releases are installed under `C:/Users/zrq/.agents/skills` and `C:/Users/zrq/.claude/skills`, with prior copies backed up outside discovery. All four isolated installed runtimes match the final source identity. Proof-check remains explicit-only, and the Claude settings file is byte-identical before and after installation. [Installation verification](../../audit-reports/reliability-implementation-2026-10-03/installed-release-independent-receipt.json) records paths and smokes. The local release receipt records the published Git commit identities.

This revision cannot establish a full-paper runtime improvement from a bounded example. It also does not retroactively certify old stale bindings. Formula presentation (O-01) remains a separate issue; the provider startup failure (O-02) remains outside the skill. Do not interpret a passing render or fewer records as mathematical completion.
