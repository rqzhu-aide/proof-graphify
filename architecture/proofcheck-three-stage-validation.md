# Three stage implementation validation

Date: October 2, 2026. Status: implemented, validated and installed.

## Result

The normal workflow now has three stages. Stage 1 prepares evidence, graph records and primary examination across the declared scope. Stage 2 performs independent review, integration, reconciliation and applicable global examinations, then freezes one scientific snapshot. Stage 3 builds the existing Archify report from that snapshot. Small coherent assignments and the common save/recovery commands remain available throughout.

Stages schedule existing scientific obligations. They introduce no database migration, new stage ledger, model executor or automatic repair loop. A current examination that finds a mathematical gap can advance to review. A current source comparison marked `needs_attention` still blocks progression and completed delivery, even when the existing assessment counts it as examined. Working reports disclose that distinction without altering canonical counts.

The implementation also fixes the six reproduced prerequisites: whole-response pending accounting, global selected-proof freshness, neutral extension after harmless edits, mapping guidance consistent with current guards, packet identity advice despite earlier provenance rejection, and explicit not-required task diagnosis.

Three implementing subagents used `gpt-6.1-sol` at `xhigh`. The coordinator reviewed their interfaces, source changes, historical behavior and failure recovery, then integrated the CLI and instructions. Cross-review caught an actual resume failure: a temporary receipt file could make the prescribed continuation reject its own output directory. Cleanup and adversarial recovery tests now cover that case. Existing final receipts are preserved rather than overwritten by resume.

## Candidate

Proof-check and shared core are `2.3.8`; Proof Graphify is `3.1.15`. Storage and record contracts remain version 4. The final shared source identity is `f4fb59880bf943807e3cd37b0899b4e96ae60fdab47f3b8415b73ceb930adf27`. Both generated bundles match maintained source byte for byte. [Candidate manifest](../../audit-reports/three-stage-implementation-2026-10-02/candidate-release.json).

The repositories began at `e2cff9791c844b824787e60e03e6ca31352ea8a9` and `0b974173cfa712f19c259eb43f3b438769646293`. Their earlier uncommitted workflow and recovery changes were retained. Runtime source edits are frozen for final validation.

## Checks

Focused checks cover stage boundaries, ready-subset prerequisite closure, stage-specific size retries, complete facts despite paginated diagnostics, current source mismatch, negative versus unfinished work, same-revision preparation, and unknown readiness after analysis limits. Optional stage-status failure preserves the successful canonical status rather than replacing it with an error.

Delivery checks cover finalization without Node, building without the live database, same-revision reuse after publication metadata changes, concurrent snapshot consistency, exact identity validation, working/Triage output, source protection, retained HTML/receipt pairs on failure, and resume of the frozen revision after a later live edit. The final delivery lane passed 59 tests with no skips. The separate release-resume adversarial lane passed three tests. [Delivery evidence](../../audit-reports/three-stage-implementation-2026-10-02/delivery/tests-results.json), [resume evidence](../../audit-reports/three-stage-implementation-2026-10-02/reliability/release-resume-adversarial-2.log).

| Check | Result |
| --- | --- |
| Shared core, final frozen candidate | 1,569 tests, no failures, one Windows symlink skip |
| Proof-check package | 1,071 tests exercised; its only failure was routine instruction length. Repeated prose was shortened, then all six affected skill-structure tests passed. One Windows symlink skip. |
| Proof Graphify | 381 tests, no failures, one Windows symlink skip |
| Installer | 22 tests, no failures |
| Final release compatibility corrections | 47 tests, no failures |
| Skill packaging | Both quick validators pass; both 48-file bundles match maintained source |
| Installed execution | Four isolated package checks, two proof-check finalize/build exercises and two Graphify edit/render exercises pass |

[Final shared-core log](../../audit-reports/three-stage-implementation-2026-10-02/shared-suite-final.log), [proof-check log](../../audit-reports/three-stage-implementation-2026-10-02/proofcheck-suite.log), [instruction correction](../../audit-reports/three-stage-implementation-2026-10-02/skill-structure-final.log), [Graphify log](../../audit-reports/three-stage-implementation-2026-10-02/graphify-suite.log), [installer log](../../audit-reports/three-stage-implementation-2026-10-02/installer-suite.log).

Initial integration runs exposed outdated release assertions, a legacy diagnostic-shape mismatch, an obsolete export-failure injection point, and missing registrations for the new command/test surface. They were corrected before the clean final shared-core run. An early run also overlapped bundle regeneration and therefore saw mismatched captured identities; the final run used frozen source and bundles. Failed logs are retained. Focused counts overlap full suites and must not be summed as distinct tests.

Routine entrypoint, role references and generated guidance total 3,573 words for primary and 3,608 for independent review, within the unchanged 3,574/3,809 limits. The limits were not raised to accommodate the new workflow.

## Preserved audits

Fifteen saved databases were assessed with the preceding candidate and the revised core: five DRL 2.3.5 cases, four RF-HTE 2.3.6 cases, four RF-HTE 2.3.7 cases, and the completed and unfinished conditional-lemma continuation. Every task's required/state/outcome/freshness facts and every canonical progress count matched. The original files retained their SHA-256 hashes; packet preparation wrote only to disposable copies. [Comparison](../../audit-reports/three-stage-implementation-2026-10-02/preserved-comparison.json), [before](../../audit-reports/three-stage-implementation-2026-10-02/preserved-before.json), [after](../../audit-reports/three-stage-implementation-2026-10-02/preserved-after.json).

The completed Claude DRL case remains 239/239, and the completed RF-HTE 2.3.7 case remains 109/109. Claude RF-HTE 2.3.6 remains 329/365 and 2.3.7 remains 157/286; neither becomes complete through stage naming. Ordinary global preparation waits on the actual primary/review boundary. The unfinished conditional case remains 23/29, with Stage 1 ready and local review still required.

Low-level global preparation remains available for compatibility and was replayed separately at existing limits. All six unfinished-global cases fit the existing maximum, retaining every required selected boundary anchor. The five historical paper packets remain 188,805, 194,908, 803,055, 238,262 and 530,093 bytes respectively, identical to the preceding candidate's corrected payload sizes. Stage naming does not shrink those contexts or waive prerequisites. [Packet summary](../../audit-reports/three-stage-implementation-2026-10-02/global-packet-summary.json). Preparation does not establish that an agent examined the supplied mathematics.

## Behavioral validation and limits

A fresh `gpt-6.1-sol` agent at `xhigh` exercised the candidate skill on a disposable copy of the unfinished multi-proof continuation. It received the skill and raw artifacts, without the implementation diagnosis or intended mathematical answer. Phase 1 inventoried the saved work, prepared one actually unfinished independent review, and stopped after saving its response/envelope but before intake. All 15 earlier responses matched stored intake, so none was needlessly resubmitted or replaced.

Phase 2 first submitted those exact saved bytes. Intake retained an out-of-scope supporting judgment and unmapped source targets as `needs_revision`; it did not credit the whole return. One actual-author correction and one mapping step then completed the lemma review, followed by exact-target reconciliation. The original response and printed-notation concern were preserved. All 23 primary examinations and all three original findings remained unchanged, while progress advanced from 23/29 to 25/29. The remaining theorem independent review/reconciliation and two global checks stayed explicit. This was a bounded checkpoint, not a completed paper audit. [Phase 1](../../audit-reports/three-stage-implementation-2026-10-02/behavior/phase1.md), [Phase 2](../../audit-reports/three-stage-implementation-2026-10-02/behavior/phase2.md).

The coordinator independently queried the resulting database with the installed skill and confirmed revision 35, Stage 1 ready at 23/23, overall completion false at 25/29, and the original three finding identities at version 1. [Independent status check](../../audit-reports/three-stage-implementation-2026-10-02/behavior/root-verified-status.json). No full mathematical reexamination or mechanical retry loop was needed. The observed worker correction remains evidence that stages do not prevent every wrong response; they support retaining it and correcting only the affected work.

Phase 2 completed 17 CLI calls with no transport retries. Partial finalization and the subsequent working-report build each succeeded once. The coordinator independently verified the saved snapshot and HTML hashes against the continuation evidence. The report remains visibly incomplete at 25/29 and preserves the four remaining obligations. [Continuation summary](../../audit-reports/three-stage-implementation-2026-10-02/behavior/summary.json).

The exercise initially loaded candidate `476142d098521f29f6f0467a14035318e207784964ea85f81afbc3660c03481d`. Two final delivery fixes changed it to `4945b8c3b19857de2dbf912b3c7a70935abb09400d9875b11d4ce49400efd7d9`; restoring exact legacy release-failure diagnostics then changed only `cli.py` to the final identity above. Both transitions were disclosed. This is mixed-candidate behavioral evidence, not a fixed-candidate timing benchmark. Stage and scientific examination code stayed unchanged during those transitions.

A separate fresh agent completed the small finished audit's actual delivery cycle. It preserved 28/28 obligations and all three recorded adverse findings, forced one missing-Node rebuild failure, verified that the previous HTML survived, then completed a real Stage 3 rebuild from unchanged frozen files. The original/copy databases and sources were unchanged. [Product validation](../../audit-reports/three-stage-implementation-2026-10-02/product/validation.md). Compact finding previews still show literal TeX, as they did in the preserved 2.3.7 report; full finding descriptions retain complete text and MathML. This pre-existing presentation limitation was not expanded into unrelated runtime changes.

No matched full RF-HTE rerun or whole-paper speed improvement is claimed. Existing report acceptance checks verify content, geometry, identities, disclosure and offline rendering; they do not substitute for a live browser visual review or mathematical evaluation of a whole new paper.

## Installation and release

Proof-check 2.3.8 and Graphify 3.1.15 are installed in both `C:/Users/zrq/.agents/skills` and `C:/Users/zrq/.claude/skills`. Each previous installation was retained under its surface's `skill-backups` directory. All four installed bundles report the final core identity, and isolated executions import their own installed runtime. Claude settings and the explicit-only proof-check policy were preserved. Both installed proof-check copies finalized and rendered the completed fixture without changing its database; both Graphify copies edited and rendered an overview while preserving source/exact-statement evidence.

[Proof-check installation](../../audit-reports/three-stage-implementation-2026-10-02/proofcheck-installation.log), [Graphify installation](../../audit-reports/three-stage-implementation-2026-10-02/graphify-installation-receipt.json), [independent installation verification](../../audit-reports/three-stage-implementation-2026-10-02/installed-release-independent-receipt.json).

See the [release receipt](../../audit-reports/three-stage-implementation-2026-10-02/release-receipt.json) for repository commit and remote verification. Version labels alone do not establish completion of a paper audit.
