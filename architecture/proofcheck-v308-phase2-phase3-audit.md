# Phase 2 to Phase 3 transition audit, v3.0.8

Date: 2026-10-07. Scope: bounded workflow and delivery validation by three sol-6.1-xhigh subagents plus parent verification. Production skill files were not edited. The candidate runtime identity is `ff6cbfa8e9ab5f5cc21327981ce5b333013d4b3808a1d90a44a9cd0cc032c3f2`.

## Conclusion

The normal transition is smooth in the tested cases. Phase 2 supplies the scientific content and completion assessment; Phase 3 can produce the report from the frozen bundle without accessing the live database or commissioning more review, summaries or explanations. Retained disagreements can finish as a release. Partial or unavailable review can finish as an honestly limited working report. A failed presentation can retry the same frozen material.

The remaining issues concern completion wording and local delivery diagnostics. They do not justify additional stage gates, agent roles, database records, scientific checks or mandatory writing. A successful finalization also prints more detail than the coordinator needs, but no stall caused by that verbosity was observed.

## What was exercised

| Workstream | Evidence and result |
| --- | --- |
| Fresh Phase 2 handoff | Two synthetic cases used 31 public wrapper commands with zero unexpected failures. A supported primary opinion and independent gap were integrated as unresolved and released; ordinary integration preparation then stopped. A partial independent opinion left only the affected review and dependent integration unfinished, while working HTML still built. Repeated freezing reused the result. Builds worked with the live database renamed out of its original path. Original reviewer bytes, checks and frozen scientific projections were retained. |
| Report delivery and recovery | Seventeen bounded cases exercised space/Unicode paths, blocked live-file reads, absent live paths, rendering failure, receipt-commit failure, protected outputs, ordinary path repair and retry. A separate post-commit cleanup injection exposed the false-failure issue below. Earlier valid outputs survived failures before publication completed. Scientific files remained unchanged. |
| Instruction and report contract | Nine focused tests passed, including three scientific-correction subcases. A real frozen bundle rebuilt without a copied database. A report with no optional proof strategy or overview-scope prose built successfully and retained finding descriptions, consequences, resolved history and external-review limitations. |
| Parent complex-data check | Current Stage 2 finalized an unchanged copy of the saved Codex KEDRL database, then current Stage 3 built its 45-node, 43-connection report. Finalization took 2.095 seconds and presentation 5.794 seconds. The result released successfully with identical node/connection assessments; original and copied database hashes were unchanged. These times measure finalization and presentation only. |
| Parent partial-delivery check | Public `stage2 finalize --partial` followed by `stage3 build` succeeded without changing database, frozen or package bytes, reproducing the wording issue below. |

## Targeted findings

### 1. Cleanup after successful publication is reported as publication failure

When the HTML and matching receipt have both been committed, a later temporary-directory cleanup error still enters the failure handler. The injected test returned `PUBLICATION_FAILED`, exit 6, and `prior_output_retained=true` / `prior_receipt_retained=true`. Hashes showed the prior pair had actually been replaced by a valid newly published pair. An unchanged retry succeeded.

The user-facing consequence is a false failure after useful work is already finished, which can prompt unnecessary rebuilding. This was reproduced by controlled error injection; its frequency in normal host operation was not measured.

Smallest fix: distinguish failure before publication completes from cleanup after both commits. Preserve the successful publication result and add a cleanup warning in the latter case. Do not claim prior bytes were retained merely because an output path exists. Keep real render/commit failures and existing rollback behavior intact. Relevant seams: `scripts/paper_core/publish.py` in `publish_frozen`, and the cleanup exit from `staging_directory`. No automatic retry loop is needed.

### 2. An explicitly partial report can overstate examination completion

The documented `--partial` option covers known unfinished promised review that registered task counts do not represent. It can produce `kind=working`, `process_complete=true` and no registered blockers. The resulting visible headline is:

> Working report · Required examinations complete.

The working label is correct and delivery succeeds. The adjacent sentence can nevertheless be read as completion of the promised audit scope.

Smallest fix: label the count-derived state as completion of registered examinations. For a working report, state that complete coverage of the promised scope is not established. Reuse existing scope notes and limitations. This needs a presentation wording adjustment and its matching acceptance expectation, without requiring a new reason record, extra review or a fresh summary. Relevant seams: `readerReportState` / `summaryHtml` in the renderer and the matching visible-text checks in `publish.py`.

### 3. A simple output-path problem looks like an internal failure

When an output parent is an existing file, directory creation fails outside the publication error wrapper. The public command reports `INTERNAL` with a traceback. Repairing the local path and retrying the identical frozen bundle succeeds.

Smallest fix: report this as a local output-path problem, with a short instruction to choose a valid directory and reuse the same frozen bundle. For presentation acceptance errors such as a missing displayed scientific field, a similarly concise hint should distinguish rendered-content loss from missing scientific work. The existing instructions already assign these failures to Phase 3; no new recovery workflow is needed.

### Lower priority: successful finalization output is verbose

The parent real-data finalization printed 117,175 UTF-8 bytes, mostly full saved status, while the Stage 3 success result was 3,448 bytes. Detailed status is already available in the frozen artifacts. A concise default finalization receipt containing delivery kind, completion/limitation summary and artifact paths would reduce coordinator context consumption. Preserve access to detailed output for callers that need it. This is an efficiency improvement, not a demonstrated transition blocker.

## Recommended order and boundary

First correct the false failure after successful publication. Then clarify registered versus promised completion and local presentation error messages. Compact finalization output can follow as a separate small compatibility-conscious change. Keep Phase 2 responsibilities and the database structure unchanged.

No production implementation or installation was performed during this audit. The tests use synthetic judgments or already saved scientific judgments. They do not establish mathematical accuracy, whole-paper agent completion time, live browser behavior or actual print-preview acceptance. No broader workflow redesign is warranted by these results.

## Evidence

Implementation follow-up: the three Phase 3 fixes above are implemented in candidate 3.0.9. Cleanup after successful publication is a warning, partial-report wording distinguishes registered work from promised scope, and local delivery failures identify recovery using the same frozen bundle. Phase 2 and the lower-priority finalization-output suggestion are unchanged. Validation is recorded in [the candidate validation log](../stat-proof-check-v3/VALIDATION.md#presentation-recovery-309).

- [Fresh handoff report](../../tmp/v308-transition-audit-20261007/phase2/REPORT.md), with `commands.json` and `verification.json` beside it.
- [Recovery report](../tmp/v308-transition-audit-20261007/recovery/REPORT.md), [recovery cases](../tmp/v308-transition-audit-20261007/recovery/results.json) and [post-commit cleanup reproduction](../tmp/v308-transition-audit-20261007/recovery/cleanup-results.json).
- [Instruction and report audit](../tmp/v308-transition-audit-20261007/instructions/REPORT.md).
- [Parent partial reproduction](../tmp/v308-transition-audit-20261007/parent-results.json) and [real-data handoff](../tmp/v308-transition-audit-20261007/real-handoff-results.json).
