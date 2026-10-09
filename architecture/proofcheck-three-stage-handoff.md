# Three stage proof check revision handoff

Status: implemented, validated and installed. Date: October 2, 2026.

Reaudited against current code and disposable fixtures on October 2. See the [plan validation note](proofcheck-three-stage-plan-audit.md) for the design corrections and the [implementation validation](proofcheck-three-stage-validation.md) for execution evidence and remaining limits.

Organize the normal proof-check workflow into three stages: prepare evidence and examine, review and finalize the audit, then produce the Archify HTML. Separate their scheduling and delivery functions while retaining one database, one scientific assessment engine, and the existing submission and recovery interfaces. The purpose is to finish useful work with fewer premature reviews and fewer repeated examinations, not to add another audit system.

This document is the implementation handoff. It changes the earlier recommendation to routinely overlap primary work on one proof with independent review of another: the new default completes Stage 1 across the declared audit scope before routine Stage 2 dispatch. Explicit review of a ready subset remains possible when another part is blocked. That exception neither narrows the audit nor declares the unfinished part complete.

## Baseline and evidence

The maintained repository is this document's parent repository, with core source in [shared/paper_core](../shared/paper_core). Its Git HEAD is `e2cff9791c844b824787e60e03e6ca31352ea8a9`, but substantial subsequent work is uncommitted. Preserve that work. Do not implement this plan by resetting to HEAD or an earlier release.

The current candidate has proof-check/core version 2.3.7 and content identity `d9e892be6227c324ec00b004dd268ddf0f7d0f24c75949c7714de3c459b81f94`. The companion Graphify package is 3.1.14. Capture the actual identities again before implementation because labels alone do not identify the tested code. The most recent audit found older bundles in the user-wide installations.

Use these records as evidence:

- [Current friction audit](../../audit-reports/full-friction-audit-2026-10-02/audit.md): two correctness defects and four mechanical frictions, with reproductions.
- [Current workflow rationale](proofcheck-proof-workflow-design.md): the earlier RF-HTE run dispatched reviews before known statement corrections settled and accumulated saved output awaiting integration. The historical comparison does not establish matched runtime performance.
- [Local recovery validation](proofcheck-local-recovery-validation.md): fixes already implemented, preserved-case preparation results, and the bounded continuation exercise.

Two code findings shape this revision. First, `primary` is an examination role, not Stage 1: audit-level global consistency, adversarial, and method-interface work currently also uses that role. Second, the report already uses [the bundled Archify adapter](../shared/paper_core/renderer/archify_adapter.mjs). Stage 3 should reuse that renderer. It needs neither the separately installed Archify skill nor a conversion through the Graphify overview database.

## Intended experience

| Stage | Agent responsibility | Durable result |
| --- | --- | --- |
| 1 Prepare and examine | Inventory the manuscript and supplements, capture evidence, settle exact statements and proof boundaries, construct the necessary graph, perform primary examination and save coverage | Current source, graph, primary reasoning, findings, and explicit remaining work in `audit.db` |
| 2 Review and finalize | Obtain independent examinations, integrate unchanged responses, map source targets, reconcile reasoning, finish applicable global checks and the final scope comparison | The current audit records, plus a fixed-revision report snapshot and finalization receipt |
| 3 Produce HTML | Render the frozen results through the existing Archify viewer and verify their presentation | `report.html` and a build receipt tied to the exact snapshot |

There are still many small saves and coherent assignments inside each stage. There should not be one enormous worker assignment per stage. A proof's primary owner can retain context through multiple saves and later reconciliation. Independence still requires a genuinely separate, qualified context; three stage names do not create it.

Stage 1 and Stage 2 are about examining and recording the mathematics. Stage 3 is about presenting it. A rendering failure must never require another scientific examination. A negative examination is not a transport failure or a request to keep trying until a favorable result appears.

## Boundaries and readiness

### Stage 1

Begin with a manuscript-wide inventory appropriate to Full, Focused, or Triage scope. Develop detailed proof records while examining each proof, rather than constructing every intermediate node for the entire paper before examining anything. Capture complete source passages and settle known transcription, hypothesis, setup, and boundary corrections before preparing routine independent review.

Stage 1 owns required local primary work, including source fidelity, external-result verification when required, applications, derivations, cases, discharges, coverage and composition. Stage membership must use the task's kind and target as well as its role. Exclude audit-target global examinations from Stage 1.

Derive Stage 1 readiness from a complete current assessment of the audit's registered scope:

1. Analysis completed successfully, and the relevant scope is valid and nonempty where required.
2. Required local primary obligations are satisfied by current qualifying evidence.
3. Relevant source, statement, structure, proof-boundary and coverage blockers have been cleared.

Do not require independent qualification, independent review, reconciliation, global examinations, favorable outcomes, or an empty findings list. A completed gap or refutation can satisfy the existing examination requirements. An unfinished draft or an unavailable required source does not become complete merely because someone recorded it.

Source fidelity is a specific exception to outcome-neutral readiness. The current engine can count a completed `needs_attention` source comparison as a satisfied examination. Routine Stage 2 preparation must nevertheless wait for the latest current required comparison of each affected item or exact target to be `matched`. Correct the representation and compare again, or preserve the unresolved mismatch for a limited handoff. This concerns whether the recorded statement matches the source, not whether that source statement is mathematically true. Do not require mathematical checks to have favorable outcomes.

Its recovery advice must identify the actual comparison and affected record. Use existing authorized correction and current `get`/`compare` operations when the comparison is already counted satisfied; do not repeatedly request the same satisfied task through `stage1 prepare --task`. Preserve the earlier observation. A real statement correction can naturally make the old comparison historical and restore ordinary pending work.

Readiness describes registered work. It does not certify that software discovered every theorem, premise or omitted supplement. The coordinator still performs the manuscript inventory comparison and commits known corrections using the existing records. Do not add a checkbox purporting to certify undiscovered mathematics.

### Stage 2

The normal Stage 2 preparation command first checks Stage 1 readiness across the declared audit scope. It then prepares independent examination and reconciliation in coherent units. Integrate available saved responses before commissioning replacements. Keep source-only delivery, qualification, provenance, immutable worker bytes, exact mapping, and current evidence rules unchanged.

Finish required local review and reconciliation before normal preparation of applicable audit-level global checks. These include `global_consistency`, `adversarial`, and `method_interface` where required. They remain primary-role examinations in the underlying contract. Their Stage 2 placement does not require new scientific record kinds.

Global preparation should consider only the local work relevant to the audit's declared scope. A task explicitly marked not required must not delay either stage. A global finding may require a local correction; that is affected work to revisit, not a reason to add a fourth stage or repeat every global examination unconditionally.

At the end, check the manuscript inventory and scope again and retain the existing assessment engine's `process_complete` result unchanged. Completed release additionally requires structural validity, complete analysis and settled required source representation. Reuse the Stage 1 source-fidelity decision for this last condition; do not invent another checker. This is delivery eligibility, not a redefinition of canonical obligation counts. Completed audits may contain characterized mathematical defects; unresolved review disagreements and missing required examinations remain limitations under the existing rules.

### A blocked part and a ready part

Suppose proof A has current primary work, but proof B lacks a supplement. The default Stage 2 preparation reports B's blocker. An explicit `--ready-subset` together with `--focus` on A permits a limited Stage 2 assignment only if A's own required primary prerequisite closure is ready. Ordinary `--focus` selects the assignment target and does not bypass the whole-scope boundary. Merely selecting A must not discard an unfinished prerequisite shared with B.

This reuses the existing focus mechanism with one explicit scheduling option rather than adding a waiver file or an independently maintained subset ledger. Allow the option only for focused independent/reconciliation preparation, never for audit-level globals. Return `scope_limited: true` with the declared audit scope, selected focus, and a bounded account of the work left outside the assignment. Recompute readiness when preparing. Neither a prior status report nor a saved handoff grants permission to ignore changed inputs.

Keep the whole audit incomplete where appropriate. Do not rewrite audit targets or exclusions to make progress appear complete. When nothing useful can proceed, retain a partial handoff with exact remaining needs. Stage 3 can present a partial snapshot, but cannot promote it to a completed audit.

### Derived information only

Implement one shared stage assessment over the existing complete work/assessment derivation. Report the audit identity, revision, declared scope, analysis completeness, required/completed counts, relevant blockers, and bounded remaining task identities with continuation guidance. Compute all decisions and counts before pagination or diagnostic truncation. If derivation limits prevent a complete answer, return unknown readiness and the limit, not a guess.

Use the untruncated derivation facts for coverage and scope diagnostics. The current `build_work.coordinator_actions` and public assessment coverage diagnostics are already bounded to 100 entries, so those returned lists cannot be the readiness authority. For ready-subset dispatch, scope relevant blockers to the target's actual primary prerequisite closure. A focused work view may still contain whole-audit coordinator diagnostics; their mere presence must not block an unrelated ready target.

No database schema migration, mutable `current_stage` flag, stage lock, new task ledger, or stage-completion certificate is needed. Do not add stage prerequisite edges to the mathematical obligation graph, or bind a scientific check to a stage report or the database revision alone.

Stage readiness governs new routine assignment preparation. It must not prevent saving a returned response, inspecting an old attempt, mapping valid saved work, extending source context, or performing an authorized correction. Previously valid independent examinations do not become invalid solely because they predate the new scheduling default.

## Script and module separation

Keep [paper_audit.py](../stat-proof-check/scripts/paper_audit.py) as the single public script. Give it three clear command groups instead of three standalone scripts that each invent their own setup, parsing, submission or retry behavior.

| Maintained file | Planned responsibility |
| --- | --- |
| New `shared/paper_core/stages.py` | Stage task classification, derived readiness, and stage-specific assignment selection over the existing assessment |
| New `shared/paper_core/finalization.py` | Stage 2 completion validation and fixed-revision snapshot/receipt creation, extracted from the current release orchestration |
| Existing `shared/paper_core/publish.py` | Stage 3 rendering, mechanical acceptance and publication; add a frozen-input path that does not read live scientific state |
| Existing `shared/paper_core/cli.py` | Register stage commands and delegate; preserve common commands and legacy command compatibility |
| Existing renderer directory | Keep the Archify adapter, viewer assets, graph/index fallback, mathematical display and rich audit details |

Keep `sources.py`, `work.py`, `controller.py`, `packets.py`, `review.py`, `bindings.py` and `assessment.py` shared. Stage 2 legitimately reuses Stage 1 authoring operations when review discovers a correction. Moving these modules wholesale into separate stage directories would create duplication or circular dependencies.

Do not touch the older `proofcheck*.py` script family to implement the database workflow. Those scripts serve the legacy format. Generated `scripts/paper_core` copies are outputs of the bundle builder, not independent source trees to edit.

Proposed public commands, not commands available today:

```text
paper_audit.py stage1 status AUDIT.db --audit aud_ID
paper_audit.py stage1 prepare AUDIT.db --audit aud_ID --focus items:itm_ID --out work/assignments/primary-result-1

paper_audit.py stage2 status AUDIT.db --audit aud_ID
paper_audit.py stage2 prepare AUDIT.db --audit aud_ID --mode independent --focus items:itm_ID --out work/assignments/independent-result-1
paper_audit.py stage2 prepare AUDIT.db --audit aud_ID --mode reconcile --focus items:itm_ID --out work/assignments/reconcile-result-1
paper_audit.py stage2 prepare AUDIT.db --audit aud_ID --mode global --out work/assignments/global-1
paper_audit.py stage2 finalize AUDIT.db --audit aud_ID --out work/finalized/result-1

paper_audit.py stage3 build work/finalized/result-1 --out report.html
```

Both stage status commands call the same stage assessment, with different presentation emphasis. The existing `status` command should include the compact stage summary when an audit is selected. Stage 1 prepare fixes the underlying role to primary and excludes Stage 2 global tasks. Stage 2 `global` selects the applicable global kinds and translates to the existing primary role. Do not expand the stored role enum.

The commands above show the normal path. Only the blocked-part exception adds `--ready-subset` to a focused independent/reconcile preparation; it must not be present in generated normal-path examples. Global preparation always checks the relevant completed local work across the declared audit scope. Triage has no required independent/global review workflow and must not appear ready for a Full/Focused audit through an empty task count; it can produce an explicitly partial snapshot.

Stage preparation accepts existing task selection, exclusions, size bounds and provisional-work options where meaningful. Preserve coherent context and joint arguments when filtering. Explicitly selecting work from another stage should identify its correct stage; selecting a not-required task should explain that it is not required. An empty selection is not successful completion.

Compute the readiness boundary before assignment task/exclusion filters. Neither `--task`, `--exclude-task`, nor `--allow-provisional` may erase unfinished required work from that boundary. The explicit ready-subset option changes only the scheduling scope and still requires current local readiness.

Use the same commands for both stages to save and recover work:

```text
paper_audit.py work submit ...
paper_audit.py work inspect ...
paper_audit.py work extend ...
paper_audit.py review map ...
paper_audit.py get ...
paper_audit.py apply ...
```

Keep existing `work prepare`, `checkpoint`, and `release` available. The skill's normal instructions should use the stage commands; the older low-level interfaces remain available for compatibility and exceptional scoped investigations. Do not impose the new scheduling default retroactively through intake eligibility or silently discard existing packets.

Add a distinct internal stage candidate filter to the existing selection path. The current `task_ids` argument means requested starting tasks, can add their prerequisites, and treats an empty list as automatic unrestricted selection. It is not a stage allowlist. Preserve that user-facing meaning. Apply the stage filter to complete work units while retaining prerequisite facts and joint context. An empty stage candidate set returns explicit no-work/blocked guidance and must never become `task_ids=[]` passed to an unrestricted selector. A unit containing work outside the stage is diagnosed rather than silently split or widened across stages.

Share one selection function for status advice and actual preparation. Add an internal controller path that consumes the assessed work view and stage filter rather than calling `derive_work` again. One assessed revision supplies readiness, selection, and the packet preparation request. Retain the existing revision checks at packet construction and persistence; a concurrent scientific edit returns a conflict and asks for current preparation. Do not add a stage lock or automatic retry loop.

Stage-aware size and prerequisite advice must keep the same stage command, mode, focus, ready-subset choice, task/exclusion selection and applicable limits. Do not reuse guidance that emits raw `work prepare --mode global`, which is invalid, or changes to a low-level command that bypasses the boundary. Treat `prepared:false` as a structured diagnostic, independently of CLI exit success, and reuse the assessed facts for its explanation.

Keep supplied-route review on its documented existing `work prepare --mode independent --route ...` path in this revision. It retains the initial source-only review and actual supplied-route provenance. Do not silently forward it through the ordinary stage selector, whose current preparation branch it bypasses. If a later revision exposes `--route` under Stage 2, it must apply the same readiness boundary explicitly before entering that branch.

## Stage 2 artifacts and the Stage 3 input contract

The current `cmd_release` in [cli.py](../shared/paper_core/cli.py) validates completion, renders HTML, then writes an export and release receipt. Extract the scientific finalization before rendering. A machine without Node or a working math-display converter must still be able to complete and preserve Stage 1 and Stage 2.

### Minimal frozen bundle

The new stage path should save one substantial file, `report-snapshot.json`, and one small `finalization.json` receipt. SQLite remains authoritative for scientific records and continuation. A snapshot is a derived presentation input, not a replacement audit database.

`report-snapshot.json` contains a versioned envelope around the existing projection, with:

- Paper and audit identity, exact revision, declared scope, and pinned paper title.
- Snapshot source identity and the captured source/provenance information already required by the projection.
- The canonical projection with findings, exact targets, dependencies, supporting records, evidence, limitations and remaining work.
- Completion status and output kind derived at that revision, plus producer core/bundle identity for traceability.

Also carry `representation_settled` and bounded `finalization_blockers` with exact affected references, derived by the shared stage assessment. These distinguish an unresolved source mismatch from a mathematical gap without rewriting the canonical projection or its examination counts.

`finalization.json` identifies the snapshot file and hash, audit/revision, analysis and structural-validation result, canonical completion status, `representation_settled`, `finalization_blockers`, and bounded remaining-work summary. Counts and eligibility use full facts. It is a mechanical receipt, not an additional scientific verdict or a hand-authored summary.

Do not save separate redundant `projection.json` and `render-input.json` files by default. Generate MathML/display fragments during Stage 3 from the frozen record text. That keeps missing rendering dependencies and mathematical display repairs out of Stage 2. The Stage 3 temporary render input must still be exactly hash-identified by its receipt.

Retain existing `export.json` production for the legacy `release` contract, using the same revision as the snapshot. The normal stage path can use the existing export command when a portable export is needed; it need not write another large copy by default. Exports do not contain the full packet/intake history and must not be described as recovery backups. Preserve `audit.db` and known authored response files, and use the existing SQLite backup operation for a recovery handoff when needed.

### Snapshot consistency

Choose revision R inside a consistent read transaction, then derive status, title, source identity, projection and any requested export from that same database snapshot. Read revisioned metadata at R. Do not combine a historical projection with `paper_record(db)` or `source_context_digest(db)` at a later live head; both currently appear in the publication path.

Finish the read transaction before any publication logging or other write begins. The compatibility `release` path must freeze its requested export during that read, then render and register publication afterward. Preserve the public `report.html`, `export.json`, `receipt.json` package without nesting `publish_report`'s write transaction inside the read transaction. Retain its private frozen preparation and export if any subsequent publication step fails, returning their exact paths and an executable resume operation. Clean up private preparation only after all public outputs and their final receipt succeed. Resume must not silently finalize a newer live revision.

Define that exceptional recovery as `paper_audit.py release AUDIT.db --audit aud_ID --out RELEASE_DIR --resume PREPARATION_DIR`. The new optional flag consumes the saved preparation, finishes only the delivery steps, and validates the original audit identity and output association. Permit a nonempty release directory only when its existing members are verified artifacts of that preparation; retain the normal conflict protection for unrelated contents. The ordinary release invocation and successful three-file contract remain unchanged.

If implementation uses a SQLite backup to establish a read snapshot, derive R from the reopened copy. The current backup helper's returned live revision after copying is not sufficient under concurrent writes. A backup is an implementation option, not an additional mandatory artifact for every rendering attempt.

Write into a temporary directory and publish the finalization bundle only after its members and hashes agree. For an existing destination, first validate its receipt, hashes, audit/revision and format compatibility. Return that existing bundle for the same requested snapshot; do not regenerate it merely to compare bytes. Projection metadata such as `summary.published_revision` changes after publication even without a scientific revision. Neither that operational change nor a fresh timestamp should create a snapshot conflict or another examination. Refuse genuinely conflicting contents. A later audit revision, or deliberate regeneration with a changed projection implementation, uses a new destination. No audit lock or persistent finalization state is required.

The default `stage2 finalize` requires the existing completed-audit conditions and settled required source representation, and produces kind `release`. `--partial` requests kind `working`, retaining all limitations and canonical counts, including when examination accounting is complete but source representation still needs attention. Both kinds require structural validity and successful complete derivation of the recorded facts. Use the existing `working` and `release` values accepted by the renderer and publication schema; do not introduce a stored `partial` enum. If analysis fails or hits a limit, save diagnostic/continuation information and preserve any last valid snapshot; refuse a new canonical report snapshot. Do not manufacture counts or introduce an unknown-count projection format in this revision. Triage can produce only the working form after successful derivation.

### Stage 3 behavior

Stage 3 verifies the bundle and hashes, constructs display fragments from frozen text, and calls the existing Node renderer and Python mechanical acceptance. It never re-derives scientific assessment from the live database, launches a reviewer, creates a finding, changes a claim, or maps a response.

Validate agreement between the finalization receipt, snapshot envelope and projection: audit/paper identity where represented, revision and canonical completion status must match. Receipt and envelope must also agree on output kind, `representation_settled` and finalization blockers. Kind `release` requires true process completion and settled required representation; kind `working` may have either canonical completion value but must not claim finalized delivery. Hash agreement alone cannot detect internally inconsistent producer output. Derive the renderer's build revision, audit identity and source identity only from the validated frozen envelope.

Refactor the renderer call to accept the frozen payload directly. The current live-database publication path should call the same underlying rendering and acceptance functions. Preserve rich result details, source references, negative findings, conditions, unresolved work, support distinctions and print/no-JavaScript access. Do not compress the audit into a small generic diagram or apply the separate Archify skill's small-diagram node limit.

Display frozen finalization blockers beside the working/release label with links to the affected records. If source representation is unresolved, say that this is a working report and has not been finalized, even when the canonical examination count is complete. Preserve that count in the progress details and qualify generic completion headlines rather than changing the recorded mathematics. A limitation hidden only in a receipt does not meet this requirement.

Preserve existing mathematical-display fallback: missing Node is a build failure; an unavailable converter or unsupported formula keeps visibly labeled literal TeX with diagnostics where current rendering permits it. Neither case invalidates scientific work. Do not introduce mandatory formula-repair rounds or a new converter requirement for Stage 2.

Record snapshot hash, revision, renderer/math-adapter/assets identity, generated render-input hash, HTML hash and acceptance result in the build receipt. Presentation identity is separate from scientific freshness. A renderer upgrade can rebuild the same snapshot without repeating review. Record the producing core identity for provenance; a bundle hash change alone must not reopen mathematics.

The new build can operate without the live audit database. If the compatibility publication path appends a publication row/blob to the original database, treat that as operational history and bind it to the exact snapshot. No scientific record revision may change. Do not compare whole-database byte hashes to determine scientific freshness because publication logging legitimately changes those bytes.

Keep destination protections for the database, registered manuscript files, snapshot/receipt inputs, and previously accepted outputs. Carry necessary protected-path information into the frozen contract so building without the live database does not lose those protections. Preserve usable embedded source excerpts; check external source links from the final HTML location and disclose unavailable external originals rather than silently dropping evidence.

A successful build must have a receipt matching the exact HTML. Failed or interrupted builds must not report an old page as the new output. Retain the last accepted output through the existing staged publication behavior, and report any incomplete artifact pair truthfully. A retry uses the same scientific snapshot. Reuse a matching existing artifact and receipt when possible; no general automatic repair loop is needed.

If the live audit later changes, the frozen output remains an identified historical snapshot. It must not be described as representing the current audit without a fresh comparison. Rendering a snapshot does not itself claim current workspace freshness.

## Corrections and recovery across stages

| Event | Required action | Work preserved |
| --- | --- | --- |
| Stage 2 discovers a missing hypothesis or omitted proof passage | Correct the affected records, inspect existing change/freshness diagnostics, examine new or changed inputs, then review/reconcile affected results as required | Unchanged reasoning, original responses, and unrelated current judgments |
| A label, private note, or layout changes | Update the relevant metadata or presentation; determine scientific relevance through existing semantic bindings | Mathematical examination credit where consumed inputs are unchanged |
| A response needs only valid source-to-record mapping | Map its unchanged bytes through the existing interface | Authorship, provenance and scientific reasoning |
| A source request occurs after harmless metadata edits | Extend neutral context using demonstrated semantic equivalence | Existing assignment reasoning and immutable original packet |
| A renderer, browser, or display conversion fails | Repair or retry only Stage 3 against the same snapshot | Finalized audit artifacts and all examinations |
| Work stops or the examiner cannot continue | Preserve accepted records, known saved files, actual provenance and exact next need | Recoverable work without impersonating the original examiner |

A correction is a local return to earlier work, not a whole-audit restart. Stage 1 status may now show affected unfinished work, while explicit ready-subset Stage 2 preparation can still serve unrelated ready targets. Do not automatically reissue all reviews or all global checks. Renew only judgments whose consumed inputs changed, or whose required examination was never completed.

Do not commission a third full examination merely to reconcile two completed examinations. The primary owner or coordinator compares the actual reasoning and investigates specific remaining questions. If the same unchanged blocker recurs, stop that branch and preserve a concrete handoff rather than generate another filename, worker, or request ID as a substitute for progress.

## Targeted repairs required before trusting the stage boundaries

The [current audit](../../audit-reports/full-friction-audit-2026-10-02/audit.md) documents these six repairs. Implement them in their existing modules, with focused regression tests. Stage status cannot compensate for incorrect acceptance or freshness facts underneath it.

| Repair | File and intended change | Required behavior |
| --- | --- | --- |
| Complete pending-judgment accounting | `review.py`: share the complete judgment facts used by intake, mapping completion and inspection | A valid partial mapping is preserved, but another unresolved judgment keeps the whole response pending and ineligible for completion credit |
| Global proof-selection freshness | `bindings.py` and `packets.py`: bind the same shallow proof passages and boundary selections actually delivered | A newly selected proof passage invalidates affected prepared and saved global work; unrelated bookkeeping does not |
| Harmless-version source extension | `packets.py`: check mathematical and neutral-context equivalence before rejecting solely on record version | Label/private-note changes need no replacement examination; changed scientific inputs still require it |
| Accurate mapping recovery advice | `controller.py` and `review.py`: supply the current mapping guards when generating advice | Submission and inspection agree about what can actually be mapped in the same state |
| Conflicting packet diagnosis | `controller.py`: retain neutral identity-pairing information even when provenance checks reject first | Diagnose both supplied identities without assuming which is wrong or weakening provenance checks |
| Not-required task selection | `work.py` and CLI guidance | An explicitly selected inapplicable task says it is not required, rather than prescribing nonexistent prerequisites |

Do not convert every historical pending or rejected response into a permanent stage blocker. Preserve history, retain unresolved scientific concerns through the existing finding/reconciliation rules, and base completion on currently required qualifying evidence. The acceptance repair must prevent unresolved responses from contributing evidence; it must not make abandoned or superseded attempts veto all future completion.

Global freshness should share a shallow source-selection helper with packet construction. Avoid separate lists that drift again, and avoid binding the entire proof graph or all primary findings into neutral independent context. Adding primary coverage must not accidentally reveal primary reasoning to an independent examiner.

## Documentation changes

Revise the normal entry point and workflow reference together so the agent sees one consistent sequence:

- `stat-proof-check/SKILL.md`: the three stages, normal command routing, and distinctions between incomplete work and negative outcomes.
- `references/controller-workflow.md`: the canonical stage sequence, focused exception, coherent ownership, shared submit/recovery path, and local return after a substantive correction. Replace conflicting instructions rather than appending another workflow beside them.
- `references/database-audit.md`: stage commands, ordinary work folders, artifact locations, frozen versus current status, and stopping/resume behavior.
- `references/coordinator-protocol.md`: inventory responsibility, known corrections before routine review, and Stage 2 scope integration.
- Existing checker, reconciler and mapping references: only necessary command/context adjustments. Workers need their role brief and packet, not all three stage manuals.

Keep detailed recovery in its existing canonical location. Do not add three long manuals repeating source, provenance and submission rules. Clarify database workflow versus legacy report instructions; do not route new database users into legacy `proofcheck.py finalize` commands.

The companion Graphify skill keeps its selective overview purpose and independent database workflow. It receives the updated shared core bundle and compatibility testing, not the proof-check three-stage procedure.

## Implementation sequence

1. **Correct the six reproduced defects.** Add failing transition tests from the saved reproductions, implement targeted fixes, and confirm current acceptance and freshness facts before building stage readiness on them.
2. **Add stage assessment and selection.** Implement `stages.py`, the stage status/prepare commands, and semantic tests. Keep low-level scientific eligibility and stored contracts unchanged.
3. **Separate finalization and presentation.** Extract `finalization.py`, add the minimal frozen contract, and refactor `publish.py` to render it. Make old `release` compose both stages while retaining its existing files and public result contract. Keep working `checkpoint` available as an optional preview, not a required step after every save.
4. **Replace conflicting workflow instructions.** Update the normal path and targeted references after command behavior exists. Regenerate both core bundles from maintained source.
5. **Validate the integrated continuation and delivery.** Run the regressions below, the required repository suites, and bounded fresh-agent exercises with the actual candidate package. Record implementation success separately from full-paper runtime evidence.

Each package has a concrete stopping point. There is no separate general audit stage, scheduler, model-call executor, automatic retry engine, or background work queue in this revision.

## Validation and acceptance

Test observable transitions rather than matching documentation headings or adding tests that mirror every helper.

| Test | Required observation |
| --- | --- |
| Stages versus roles | Stage 1 never selects audit-level global tasks; Stage 2 selects them only in its global branch, preserving stored primary roles |
| Ordinary boundary | Unfinished required local work blocks default Stage 2 preparation; saved submissions and recovery remain available |
| Focused exception | Ordinary focus still respects the normal boundary; explicit ready-subset review permits ready A while B is blocked, never evades A's unfinished shared prerequisite, and cannot be used for globals |
| Negative versus unfinished | Current completed gaps/refutations can advance; drafts, missing sources and unknown analysis cannot appear complete |
| Source mismatch versus mathematical defect | Item and exact-target `needs_attention` comparisons block normal review and release, including affected subset review, even if local tasks are counted satisfied; working output shows the mismatch without changing canonical counts; correction advice does not retry a satisfied task |
| No independence cycle | Missing reviewer qualification does not block Stage 1 readiness, but blocks independent dispatch when required |
| Full inventory | Readiness/counts remain correct across multiple work-list pages and truncated diagnostics; size/analysis limits cannot create a false ready result |
| Scope and empty work | Full, Focused, Triage, no-target and not-required cases retain their actual completion semantics |
| Partial mapping | Map the valid judgment while another scope-invalid judgment remains pending; neither direct nor controller paths accept the whole response |
| Global selection change | Adding proof passages or boundary anchors after preparation and after acceptance reopens exactly the affected global examinations |
| Harmless changes | Label/private-note edits retain scientific credit and permit semantically equivalent neutral extension |
| Executable advice | Mapping advice agrees with enforced guards; cross-mode identity mismatch explains both packet identities |
| Stage selection and retry | An empty stage allowlist never selects global work; requested-task prerequisites and complete units remain intact; overflow advice retains the valid stage command and options |
| Preparation consistency | One assessed revision determines readiness and selection; a concurrent edit triggers existing packet revision conflicts, not a mixed or silently renewed assignment |
| Local scientific correction | Changed hypothesis or proof evidence reopens affected work, preserves unrelated independent examinations, and retains original adverse findings |
| Saved output on resume | Integrate a known unsubmitted response before issuing replacement work; terminal receipts remain historical |
| Consistent finalization | Concurrent/live changes cannot mix title, scope, source identity, projection or export from different snapshots; receipt/envelope/projection mismatches fail before rendering |
| Renderer unavailable | Stage 2 finalization works without Node or the math converter; Stage 3 reports the missing shared dependency without modifying audit records |
| Frozen build | Change the live database after finalization; Stage 3 still renders exactly the chosen snapshot and never calls the examination path |
| Presentation retry | Renderer failure, interruption, or a template-only change can be handled from the same frozen bundle; scientific records and freshness are unchanged |
| Repeated finalization | Publication-only metadata changes do not prevent reuse of the existing valid bundle at the same revision; changed projection regeneration uses a new destination |
| Compatibility release recovery | Failure after frozen preparation retains that preparation and its export with an exact resume path; successful public release still has its established three-file contract |
| Output protection | Building cannot overwrite the database, manuscript, or frozen inputs; stale last-good HTML is never reported as a successful new build |
| Partial delivery | Working/Triage output retains missing work, disagreements, source limits, its actual canonical completion value and a not-finalized delivery label; Stage 3 cannot upgrade it; failed derivation saves diagnostics instead of a fabricated projection |
| Existing product | Rich details, source links, exact targets, mathematical display, print access and graph/index fallback still satisfy current renderer acceptance checks |
| Compatibility | Existing direct work, old valid independent evidence, checkpoint/release contracts, and Graphify overview behavior remain usable |

Use disposable copies of the preserved 2.3.5 DRL and 2.3.6/2.3.7 RF-HTE databases. Check task counts and current evidence before and after the revision. Expected differences must be attributable to a demonstrated correctness repair, not merely to the new stage labels. Hash originals before and after; never repair the preserved evidence in place.

Include the prior conditional-lemma continuation and both already-finished and unfinished fixtures. Its retained negative findings must remain visible, and ready/satisfied work must not be repeated merely because the workflow changed. Replay global packet preparation at supported limits: stage naming does not solve payload size, and no required passage may be silently truncated.

For behavioral validation, give a fresh agent the revised skill and raw artifacts for a bounded multi-proof continuation without the intended answer or diagnosis. Observe preparation, actual examination, saved responses, integration and an interruption/resume. A separate small completed fixture must exercise finalization and HTML delivery, including a forced renderer failure followed by Stage 3-only recovery. Record actual package identities, attempted/completed worker calls, invalidated examinations, saved work reused and completion reached. Do not infer end-to-end speed from unit tests or compare different papers as a matched benchmark.

Run the shared-core, proof-check, Graphify and installer suites required by the repositories after regeneration, plus applicable renderer and packaging checks. Use only existing shared runtimes/packages. A full fresh RF-HTE run is valuable performance evidence if available, but must not be claimed from a bounded continuation or attempted through an already-rejected external execution route.

## Delivery and release

The originally proposed commands and modules have now been implemented, preserving the preceding uncommitted workflow and recovery work. The separate [implementation validation](proofcheck-three-stage-validation.md) records actual checks, package identities and remaining limits.

When implementation and release proceed under the session's authorization, recheck intervening releases before choosing patch versions. If the baseline is unchanged, proof-check/core 2.3.8 and Graphify 3.1.15 are the existing patch candidates. Regenerate both bundles, verify content identities in user-wide `.agents` and `.claude` installations, and record each repository's commit and push separately. A version label or successful installation alone does not demonstrate that the revised workflow completed a paper audit.
