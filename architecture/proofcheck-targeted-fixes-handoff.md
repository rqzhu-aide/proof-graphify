# Handoff: targeted proof-check reliability fixes

Status: implemented locally on 2026-09-27 against stat-proof-check 2.3.1 and Proof Graphify 3.1.4. See the [implementation and validation record](proofcheck-targeted-fixes-validation.md) for results and the remaining browser-inspection limitation. The requirements below are retained as the agreed scope.

The user's constraint is to retain the existing architecture and fix demonstrated details. This plan is the implementation scope for that request. The broader [automatic-workflow proposal](proofcheck-automatic-workflow-handoff.md) remains a separate proposal; its new wrapper and managed-run design are not dependencies of this work.

## Objective and boundaries

Make the existing prepare, examine, submit, inspect, checkpoint and release workflow less error-prone. A checker should spend less effort reconstructing administrative JSON, recover saved work without changing its meaning, and deliver a clear report even when the audit remains incomplete.

Keep SQLite authoritative, the current record and packet formats, source bindings, freshness rules, controller selection, reviewer qualification, independent isolation, reconciliation and renderer. Preserve focused, full, triage and legacy capabilities, and the shared-core boundary between proof-check and Proof Graphify.

Make additive changes to existing helpers and command output. Do not add a workflow wrapper, run manifest, task store, automatic dispatcher, scheduler, storage migration, new proof schema, or general authoring language. Do not weaken completion rules to improve success counts. Existing commands and explicitly supplied output paths remain supported.

The implementation updates maintained source and both generated bundles. At the user's subsequent request, patch versions `2.3.2` and `3.1.5` were installed into both user-wide skill roots; see the validation record. Remote publication was not part of that installation step.

## Evidence and what is already working

The five-run distributional-RL sample passed structural validation in every case, but four audits remained incomplete. The completed audit had explicit source/scope limitations. The most serious observed errors were in custom scripts: a renewal script changed negative judgments to `supported` while retaining negative reasoning, and a reconciliation script selected `agree` from role presence without comparing opinions.

Official scaffolds already leave scientific outcomes unfinished. The core already saves raw submissions, supports exact replay and inspection, maps independent responses, produces incomplete working reports, and refuses incomplete releases. Improve those surfaces rather than recreate them.

Two older completion bugs, stale reconciliation after a primary successor and omitted source issues on consumed focused setup, were already fixed in v2.3.1. Preserve their regressions; do not count them as new work. See [the prior validation note](../tmp/proofcheck-fixes-2026-09-26/VALIDATION.md).

The exact requested `experimental/REVISION-HANDOFF.md` was absent during review. The experimental implementation actually inspected is the small patch series ending at stat-paper-skills `1a270ea` and Proof Graphify `5a2b611`. Do not assume an unseen handoff has been implemented.

## 1. Retain the useful maintenance fixes

Carry forward the reviewed fixes through the maintained repositories, avoiding duplicate application:

- Shared core: empty projections use the existing index display; distinctive damaged JSON/LaTeX escapes produce a visible fallback.
- Proof Graphify: common-store backup and change export work; exact source ranges ending in blank lines survive refresh; retain the useful command and source-storage documentation.
- Preserve the documented decision that discovered TeX inputs outside the manuscript or registered compilation root require explicit source registration. Missing inputs remain visible; they must not become a claim of complete coverage. Verify that an explicitly registered external appendix and its local inputs still work.

Correct the new math-display false positive: a tab followed by valid little-o notation `o (1)` must not be diagnosed as a damaged command. Cover legal whitespace before the parenthesis and the genuinely corrupted examples already supported. Keep the heuristic narrow; do not attempt a general TeX repair system or silently rewrite stored mathematics.

Files: `shared/paper_core/{math_render,projection}.py`; companion `scripts/{overview_math,paper_database,paper_records}.py` and their existing tests. Rebuild both generated core bundles from maintained source.

## 2. Put previous judgments where renewal and reconciliation need them

User-facing result: a previous gap, restriction or disagreement remains visible when work is renewed. The agent does not have to reconstruct an earlier opinion from IDs or write a loop that replaces it with a successful default.

In `assistance.coordinator_guidance`, augment existing eligible draft/renewal candidates with the exact prior state, outcome, reasoning, conditions, evidence references, reviewer and predecessor pin. Include the existing bounded changed-input explanation where available. Read the named historical version, not whichever record is newest. Keep the present eligibility and authorization checks.

For reconciliation, retain the existing pin lists and add the corresponding eligible opinions' outcomes, conditions and reasoning. Keep historical/nonqualifying opinions visibly distinct from current eligible ones. `has_both_roles` means only that both roles are present. It must never produce an `agree` decision. Even matching outcome labels require an authored comparison and rationale.

Start with this reference material and the current blank scientific scaffolds. Do not automatically copy a completed old verdict into a new completed check. Preserve existing `replaces` versus `supersedes` semantics. If a continuation helper is needed after the bounded walkthrough, restrict it to an explicitly selected eligible predecessor and produce a separate draft, with its historical origin visible and no new proof credit. There is no automatic choice among conflicting predecessors.

Keep enriched prior-opinion guidance out of fresh source-only independent delivery. The coordinator and reconciler may inspect it; a primary renewal receives only the permissible predecessor context needed for its assigned reexamination, under the existing read-set rules. No natural-language contradiction classifier, verdict-change approval protocol or automatic adjudication is part of this patch.

Files: `shared/paper_core/assistance.py`, existing work change diagnostics, `references/{controller-workflow,reconciler}.md`, and assistance/reconciliation tests. Do not change assessment semantics.

## 3. Repair preparation and inspection within the current controller

### Stable initial identities and an envelope template

`controller.response_scaffold` currently allocates a new reconciliation request ID whenever a packet is inspected. Make the initial scaffold identity stable for that packet. Existing saved response/submission identities take precedence when recovering old work. Never rewrite submitted bytes to agree with a regenerated envelope.

Generate a coordinator-only `submission-envelope-template.json` alongside the existing assignment files, using the current submission schema. Fill administrative fields such as contract version, original packet ID, initial request ID and null rebase. Leave actual reviewer identity and independent qualification/exposure unfinished until the coordinator supplies the facts. The reconciliation scaffold and envelope template must use the same initial request ID.

This is assistance for the first attempt, not a one-submission-per-packet restriction. A revised response, changed reviewer/provenance, or explicit rebase uses a fresh attempt ID. Preserve the existing submit API and exact-byte replay behavior. An incomplete template must fail ordinary validation rather than acquire default qualification or scientific credit.

Return an explicit worker-delivery file list in prepare/inspect receipts. The new envelope template and other private coordinator files are excluded from independent delivery. No new command family is needed.

### Recover the saved assignment, not a newly selected one

Keep `work inspect --packet` and `work inspect --request` as the recovery interfaces. After preparation has saved a packet, every artifact-write failure, including an ordinary filesystem error, must return its packet ID and an actionable inspection command. Do not prepare a replacement assignment just because its files were not written.

Same-packet inspection with the same software package and assessed state should reproduce reusable generated files. Preserve the current no-overwrite behavior for differing files and authored responses. Coordinator guidance intentionally reflects the current assessment, so it may legitimately change after another commit. Identify that distinction and direct recovery to a fresh explicitly chosen directory when needed. Do not freeze obsolete eligibility advice just to make files identical.

Use existing history to find an interrupted packet when its error receipt was lost. If several assignments match, show them and require an explicit selection. Do not introduce automatic assignment adoption, hidden retry loops, concurrent dispatch management or a claim of universal crash recovery.

Files: `controller.{response_scaffold,_assist,inspect_work,write_artifacts}`, `assistance.py`, and the current `cli.cmd_work_prepare`, `cmd_work_extend` and `cmd_work_inspect` handlers.

## 4. Make accepted source requests replay correctly

There is a narrow replay gap in `sources.anchor_sources` and `sources.review_sources`: live-source and existing-record checks can reject an already accepted request before the acceptance kernel reaches its replay check.

After basic request-shape validation, check the existing commit/request identity using the native command's canonical digest and command identity. An identical already accepted request returns its historical commit receipt without rerunning current source validation or creating records. Conflicting reuse of an ID still fails. The receipt must not imply that its old evidence is current; current freshness comes from the existing status/inspection surfaces.

Keep this change limited to replaying accepted requests. New and uncommitted requests still undergo all current source, packet and version checks. Source capture has a content-dependent digest and is a separate operation; do not transplant the anchor/review replay shortcut into capture or automatically recapture changed files.

Files: `sources.py`, with a small reuse of acceptance request-lookup logic if necessary. No new receipt store or storage migration. Preserve return-shape compatibility; do not fabricate a current anchor listing when returning historical acceptance.

## 5. Make unfinished work and delivery easier to act on

### Expose existing diagnostics

Use `status`, `work list` and prepare receipts as the existing sources of truth. Expose the structured coverage diagnostics, counts and truncation information already produced by assessment but omitted from `queries.status`. Improve the compact prepare receipt to distinguish completed recorded scope, prerequisite/coordinator work, and a selected unit exceeding the packet limit. Reuse existing reasons and actions; do not add a second readiness calculation.

`prepared:false` and exit code 0 never establish completion. Do not automatically raise packet limits, repeatedly probe focuses, truncate a joint argument, or classify missing coverage as structural just to finish.

### Close the independent-review loop

In the existing coordinator instructions and one worked path, make the sequence explicit: record genuine qualification, attach it to the audit, save the unchanged independent response, map pending source targets where needed, and reconcile the exact opinions. Use the existing qualification packing example and `review mapping-template`; do not invent a new adapter framework.

If independent execution is unavailable, preserve primary work and deliver a limited report with that limitation. A software fixture is not genuine qualification evidence, and a completed text response outside the database is not completed recorded review.

### Deliver incomplete work through checkpoint

Make an unfinished audit's normal stopping step: save substantive responses, run `checkpoint`, inspect `status` and `work list`, and return the report/database paths with a short handoff stating scope, findings, unfinished work and the next command. Apply this at a stopping or handoff boundary, not after every record.

Keep `release` strict. Its refusal should point to `checkpoint` and the relevant existing work diagnostics. A completed negative audit remains a valid completed audit. Full/Focused skill completion still requires the prescribed independent work; a generic core configuration with review disabled must be disclosed, not advertised as a full skill audit. Triage retains its limited meaning.

Use the existing factual summary for HTML and status so scope, exclusions and counts agree. Source/inventory review remains authored: a parser inventory or complete registered graph cannot establish that all supplementary proofs were examined. Any excluded supplement is named in the delivery. New sources are examined through the existing capture/anchor/extension path.

For output placement, document one simple database-relative convention first. If repeated path selection remains a problem in the walkthrough, make `checkpoint --out` optional with a deterministic database-adjacent report name. Preserve explicitly supplied paths, multiple-audit clarity, source collision checks and absolute paths in receipts. Do not relocate databases or create a managed run layout.

On rendering failure, retain the prior report and clearly say no current report was produced. Link the saved work and diagnostics. Do not present the retained old HTML as current. Partial multi-file release recovery is not a new subsystem in this patch; if a release write fails, report which artifacts exist and that delivery did not finish.

Files: `queries.py`, compact CLI receipts, and `references/{database-audit,controller-workflow,coordinator-protocol,probability-example}.md`. Preserve the existing probability example's deliberately incomplete status. Keep changes to reader presentation limited to demonstrated omissions.

## Acceptance and evaluation

Add meaningful cases to the existing suites. Reuse fixtures and shared installed runtimes; do not install project-local environments. The programmer should establish the failure before each behavioral fix and keep the check after it.

| Case | Required visible outcome |
|---|---|
| Negative/conditional previous examination after changed inputs | Guidance retains exact negative outcome, conditions and reasoning; no automatic completion or successful replacement |
| Conflicting or merely same-label review pair | Both opinions are inspectable; decision and rationale remain unauthored until actual reconciliation |
| Reconciliation prepare, inspect and recover | Initial IDs agree; identical export can be reused; original submitted response bytes remain unchanged |
| Another commit changes coordinator guidance | Current eligibility is correct; old files/response survive; recovery names a usable fresh destination |
| Artifact I/O fails after packet save | Receipt identifies the existing packet and inspection action; recovery creates no second packet |
| First submission, exact retry and changed attempt | Exact retry adds no work; changed bytes cannot reuse the accepted ID; explicit new attempt still works |
| Accepted anchor/review retry after later source changes | Historical receipt returns without duplicate records; new requests still undergo live checks |
| Independent assignment | Worker delivery excludes envelope templates, previous outcomes, private mapping and qualification material |
| Partial audit and a packet-size/prerequisite blocker | Working report is available; actual unfinished reason remains visible; no false completion |
| Examined defect, focused exclusion and triage | Negative findings are preserved; scope is accurate; triage and undone review cannot acquire a completed-skill claim |
| Renderer failure | Old report survives and is identified as old; command reports the failure |
| Display/source maintenance cases | Empty graph works; valid spaced little-o renders; damaged-escape warnings and explicit external-source intake still work |

Run one small complete integration path through the current CLI with sources, graph authoring, primary work, supplied synthetic qualification records, independent submission, mapping, reconciliation and report output. Also interrupt it at packet export and submission intake, then recover using the documented commands. Fixture qualification checks software behavior only. Keep an incomplete variant to verify useful handoff without relaxing release.

Use copies of the five harvested databases to compare factual status, negative judgments and report limits before and after the patch. Their scientific completion state should not improve merely because administration/display changed. Do not rerun five full paper audits for these mechanical changes.

Separately run a bounded behavioral evaluation with fresh checker contexts and preserved first responses:

- A correct final identity whose written derivation contains a defective preceding equality, plus a correct control. The checker must evaluate the written step and keep any proposed repair separate.
- A load-bearing cited result whose exact source is initially unavailable, then supplied through the existing context path. The checker should distinguish missing evidence from a refuted theorem and reassess the application when evidence arrives.

Keep expected answers private from the checker and evaluate substantive reasoning, including false alarms. If a case fails, make a targeted correction in the existing scientific guidance or implementation supported by that failure. Do not replace the scientific workflow with a new checklist or claim mathematical improvement from structural tests alone.

## Implementation order and stopping point

1. Preserve the small experimental maintenance fixes and fix the little-o regression.
2. Add complete prior-opinion guidance, the envelope template, stable scaffold IDs and useful artifact-recovery errors.
3. Fix accepted source-request replay; expose existing blockers and clarify independent-review and incomplete-delivery instructions.
4. Run the bounded lifecycle walkthrough. Add a continuation draft helper or optional report-path default only if it exposes a remaining concrete burden; keep each addition within existing commands and record shapes.
5. Rebuild both bundles and run affected tests, then the current core, companion compatibility and packaging suites once the changes are stable. Preserve the existing v2.3.1 completion regressions. Inspect one actual report in the browser and run the bounded mathematical cases separately.

Record which checks passed, which require follow-up, and the exact changed behavior. Update existing test indexes if tests are added. Do not repeatedly rerun broad suites without a new change or failure.

The handoff is complete when the existing workflow can save, recover, review and report a small audit without improvised administrative reconstruction; negative/conditional judgments survive unchanged unless an examiner explicitly revises them; unfinished scope remains visible; and the existing proof-checking capabilities remain intact. The result does not promise automatic orchestration of every run or automatic detection of arbitrary contradictions between prose and verdicts.
