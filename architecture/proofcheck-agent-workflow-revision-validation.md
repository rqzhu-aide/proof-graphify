# Agent-independent workflow revision: implementation and validation

Date: October 2, 2026. Implementation and local validation are complete in the working tree. The small continuation audit completed; the full RF-HTE rerun remains blocked. This is not a skill release or a claim that the original full audit now completes.

## Plan audit and implemented behavior

The [handoff](proofcheck-agent-workflow-revision-handoff.md) was checked against the maintained core, current role instructions and preserved RF-HTE evidence before implementation. The review retained local primary-before-independent ordering as an operating default, source-only independence, useful negative outcomes and the existing acceptance rules. Ownership can pass through saved evidence when a session cannot resume. No workflow engine, persisted phases, schema migration or worker quota was added.

The implementation consolidates the normal path and recovery rules in `controller-workflow.md`. Primary guidance now supplies task labels from the original pinned packet and blank contract-derived coverage/finding rows. Preparation explains requested tasks versus selected prerequisites and gives bounded size-retry guidance. Submission and current inspection distinguish mapping, authored correction, missing neutral context, changed inputs, provenance problems and interrupted intake. Historical receipts and response bytes remain unchanged.

`work inspect --response` exposes current response state, pending/mapped judgments, usable independent evidence and original task status. Audit-history enumeration remains bounded and does not load historical worker blobs. Known unsubmitted files are recovered through explicit coordinator inspection, not automatic filesystem scanning or credit based on file existence.

Real-data inspection found an additional issue worth correcting: an old response can be stale while a newer review already satisfies its task. Current guidance therefore checks current obligations and applicable replacement reviews before suggesting renewal. It preserves unresolved old concerns instead of inferring that every concern disappeared when a composition task became satisfied.

## Candidate identity and compatibility

The final maintained-core identity is `eb155e69ab7aef79ba1a0a3f92112ac063dd2d98643e9b5425f0127abfb4b82c`. Both generated bundles contain 46 identical files; their manifest hash is `aecc7914f4cb4c83ba90bea4737b24b5fc513a5611a7af25139811af076186a5`. Generated bundles were rebuilt from maintained source, not edited directly.

Version labels remain proof-check/core 2.3.7 and Graphify 3.1.14. Record/storage formats remain 4, packet/projection formats remain 2 and the protocol remains `item-audit/1`. The changed source identity identifies this unreleased candidate. No installation, version bump, commit or push is part of this implementation record.

The [candidate manifest](../../audit-reports/workflow-revision-2026-10-02/candidate-manifest.json) records repository baselines, dirty file identities, runtimes and bundle identities. Validation uses existing shared runtimes without project-local environments.

## Software checks

| Check | Observed result |
| --- | --- |
| Initial complete shared-core suite | 1,489 tests; one failure because the new recovery test module was missing from the test inventory; one optional browser skip |
| Final integration, inspection, receipt, CLI, assistance, packaging and inventory checks | 157 tests, successful with one optional browser skip; the missing inventory entry is fixed |
| Focused review, source-extension and recovery checks after the real-data correction | 110 passed |
| Proof-check package suite | 1,071 tests, successful with one optional browser skip |
| Graphify package suite | 381 tests, successful with one optional browser skip, before the final read-only replacement-evidence guidance adjustment |
| Installer suite using disposable targets | 22 passed |
| Skill frontmatter/structure and instruction-size checks | Passed |
| Final complete shared-core rerun | 1,490 tests, successful with one optional browser skip |

The negative-path error messages printed by the passing legacy proof-check suite are expected assertions, not successful mathematical examinations. Synthetic qualifications and judgments in software fixtures test mechanics only.

The stitched recovery trace now covers an unsubmitted negative response in a misleadingly named folder, no credit before submission, incorrect packet identity, interrupted intake, exact-byte replay, partial mapping and genuine input changes. Inspection tests preserve the original receipts and bytes, distinguish accepted-but-compromised evidence from qualifying review, and retain secondary blockers when detailed output is truncated.

Logs are retained in [the local validation directory](../../audit-reports/workflow-revision-2026-10-02/).

## Preserved RF-HTE evidence

The [real-data inspection report](../../audit-reports/workflow-revision-2026-10-02/real-inspection.md) and its saved script/JSON use read-only access to the user's harvested 2.3.7 database. It remains at revision 101 with SHA-256 `89fc91e5ac432bb0b3fbbc2cc3b92efc8ed86a2e0ee8b539707daae59427a907`. Hashes of the database, all commit receipts, intake rows, response versions and original blobs remain unchanged.

The pending Proposition 5 response exposes its changed proof boundary and pending correspondence. The older accepted Theorem 3.5 response retains one usable check while identifying three stale checks. Both old responses now show that their original tasks already have current replacement evidence. The accepted replacement's seven current eligible checks lead to reconciliation guidance. These observations validate recovery advice on real saved work; they do not finish that audit or establish the correctness of its mathematics.

## Behavioral validation

A fresh agent received only the shipped skill, a small two-result probability manuscript and permission to work in an isolated folder. It saved two accepted primary responses, a revision-8 working report and a continuation handoff. It found the omitted covariance terms and an exact common-Rademacher counterexample, and preserved the manuscript's literal `mu` notation defect separately. The source was not edited.

The first phase stopped intentionally before independent review. It disclosed remaining supplier verification, coverage, global work and reconciliation. Minor setup corrections were recorded: a missing output parent, an invalid ID-kind guess and an application template needing an existing use ID. Public templates supplied record shapes. The handoff's phrase “automatically rebased” is imprecise: the actual envelope has `rebase_packet_id: null` and the acceptance packet is the original packet; unchanged bindings permitted acceptance at the later revision.

A new primary context resumed the saved handoff, registered and examined the external suppliers, completed remaining primary/coverage/global work, and used two fresh contexts for real balanced calibration and source-only examination. The independent examiner examined both results in its own neutral context, returned two unchanged responses and independently found the same defects. Private source mapping and five exact-target reconciliations completed the audit without a replacement favorable review.

The [continuation result](../../audit-reports/workflow-revision-2026-10-02/behavior/proof-check-paper/RESUME_RESULT.json) records all 28 required obligations satisfied at database/report revision 26, with no returned mathematics awaiting integration. Both independent responses are currently accepted, with respectively one and four eligible checks and no pending judgments. The original intake receipts still say `needs_revision`, correctly preserving their historical mapping state. A separate coordinator verification through public `status` and `validate` confirmed completion, revision 26 and structural validity. The [completed local report](../../audit-reports/workflow-revision-2026-10-02/behavior/proof-check-paper/releases/completed-resume-2026-10-02/report.html) matches its publication hash. The manuscript hash remains `430b688146345731f3e79b97baef2a2d1f1dabaa0cd65fd2a4db948664a0a356`.

The first phase used core identity `5f6cff4e2110a58fbb5b067472c3401714294e633c10033b75cccea0b617190b`; the successor was told when the final additive inspection correction changed that identity. This is an intervention disclosed in the validation, not an uninterrupted fixed-candidate performance benchmark. Exact provider/model/effort metadata were unavailable; the qualification evidence identifies the unchanged inherited configuration and discloses the missing metadata instead of guessing it.

The continuation exposed a remaining authoring round trip: its bounded global assignment omitted a full proof anchor cited by the worker. The controller retained the failed attempt and identified missing assignment context. The agent obtained a broader public primary packet and saved the global checks through `apply` at revision 20, without repeating the mathematical examination. The original packet, response, envelope and rejection remain intact in `primary-global-resume-1`. This validates specific recovery guidance, but does not demonstrate that all ordinary assignments avoid context repair.

Three predecessor drafts remain under their original author. Validation reports six historical stale bindings: those drafts and three explicitly superseded completed checks; required current work is satisfied. The saved graph also places the lemma and theorem hypotheses in sibling scopes, so the support display reports `scope_unavailable` for one lemma use even though both reviewers explicitly established its assumptions. This representation limitation is disclosed in the result, not silently removed to improve the display. It does not change the independent counterexample or turn audit completion into a claim that the theorem is true.

The separate [no-independent-capability drill](../../audit-reports/workflow-revision-2026-10-02/behavior/no-independent-capability.md) correctly produced a limited handoff, retained required independence and explained replacement-examiner provenance. It was a read-only decision exercise, not an actual independent examination. Local browser inspection of the small report was blocked by browser policy; no workaround or visual-verification claim was made.

A second fresh agent completed the [portable-session decision drill](../../audit-reports/workflow-revision-2026-10-02/behavior/portable-session-drill.md), using only public instructions. It correctly distinguished a stored transcription error from a missing manuscript assumption and described neutral file delivery to a separate clean session when no subagent API exists. It preserved the unavailable author's response and required a replacement examiner's own work for an authored correction. This tests instruction clarity; it does not execute file transfer, source correction or replacement review on another host. The small manuscript's literal `mu` defect was a real manuscript defect, not the separate stored-transcription scenario.

## Full RF-HTE run and remaining limit

A reproducible isolated runner was prepared for the same RF-HTE main paper, supplement and required supplier scope using the existing Claude CLI. Automatic approval review rejected launching it because explicit authorization was required for giving Claude the PDFs and file, shell, subagent and web tools. No external validation process was launched. The permission question is pending; no workaround or indirect launch was attempted.

The implementation and local evidence must therefore be distinguished from full-run completion and performance. Until the real audit runs to completion, this revision has no verified RF-HTE runtime improvement or full-workflow completion result. Process elapsed and active model time must remain separate, and unmeasured model time must not be invented.
