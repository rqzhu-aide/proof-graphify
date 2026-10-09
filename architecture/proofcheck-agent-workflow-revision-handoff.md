# Agent-independent proof-check workflow: revision handoff

Status: implemented in the current working tree; validation is recorded in the [implementation and validation note](proofcheck-agent-workflow-revision-validation.md). Date: October 2, 2026. This handoff is retained as the implementation specification, not a release claim.

Baseline: stat-proof-check and paper_core 2.3.7 at `e2cff9791c844b824787e60e03e6ca31352ea8a9`; companion Proof Graphify 3.1.14 at `0b974173cfa712f19c259eb43f3b438769646293`. Recheck the actual checkout before implementation and preserve unrelated changes.

This is the implementation handoff for the [proof audit workflow design](proofcheck-proof-workflow-design.md). It preserves the useful 2.3.7 changes. The [earlier revision handoff](proofcheck-workflow-revision-handoff.md) describes work already implemented; the [automatic-workflow proposal](proofcheck-automatic-workflow-handoff.md) remains a separate, unimplemented proposal.

## 1. Outcome and scope

An agent should always be able to answer: **Which proof am I examining? What evidence already exists? What specific operation moves it forward? What remains before delivery?**

The revision should reduce repeated setup, premature review, response-format repair and redispatch of already completed work. It must preserve the depth of mathematical examination, source limitations, adverse findings and independent review. Completion means a current examination of the declared scope, possibly with negative conclusions; it does not mean making the paper pass.

The [October 1 audit](../../audit-reports/audit-v2.3.7-2026-10-01/audit.md) found 77 worker-launch attempts, late representation corrections and saved responses containing complete rows for 51 missing primary obligations. These motivate the changes below. They do not establish that every launch was wasteful, or isolate a version effect from the different papers. Runtime improvement remains to be measured.

Implement one clear operating procedure and three small interface improvements: usable assignment guidance, specific next actions, and inspection of recoverable work. Do not add a workflow engine, autonomous dispatcher, persistent phase/owner tables, quota manager or general wrapper. Do not change scientific schemas or weaken existing acceptance, freshness, coverage, qualification or release rules. Proof Graphify needs shared-core compatibility, not the proof-audit workflow.

## 2. Universal execution contract

### Responsibilities, not mandatory worker jobs

| Responsibility | Owns | Required continuity |
| --- | --- | --- |
| Coordinator | Scope, source inventory, graph edits, assignments, unchanged submission, mapping, recovery and delivery | Uses the authoritative database and saved artifacts; never depends only on conversation memory |
| Primary owner | One proof's source comparison, primary reasoning, coverage and later reconciliation | Reuses a coherent context when available; otherwise hands over the saved examination and remaining questions |
| Independent examiner | Separate source-based examination with actual qualification and exposure recorded | May continue its own source-only work when genuinely available; cannot inherit primary reasoning and still claim blindness |

The coordinator is the default primary owner. Delegation is an option for coherent mathematical work, not a requirement for each record type. Reconciliation is a responsibility of the primary owner with coordinator support, not an obligatory third complete examination. Existing write permissions still govern delegated outputs and coordinator edits.

A proof unit is one exact conclusion, one written route, applicable setup and complete relevant source passages. Use existing records; do not introduce a new proof-unit entity. Related units can share an execution context. Each packet retains its own identity and response. Split long proofs at meaningful claims and preserve final integration.

### Adapt to available capabilities

| Available capability | Required behavior |
| --- | --- |
| Isolated workers and parallel execution | Use separate source-only independent contexts. Primary examination of B may proceed while settled A receives independent review |
| No subagents, but separate clean sessions or another reviewer | Run sequentially or hand off the existing neutral delivery files. Import the unchanged returned response with actual provenance |
| No verifiable separate context | Preserve useful primary work and a reviewer handoff. Report required independence as unfinished; never disable it to claim Full or Focused completion |
| Primary session cannot resume | A successor assumes the logical responsibility from saved primary artifacts, identifies itself accurately and continues only remaining or changed work |
| Original independent author cannot resume | Preserve its response and pending issue. A new examiner authors a new response with actual identity/exposure and whatever examination is needed to support its judgment; it does not impersonate or silently edit the previous author |
| Different file/command tools, or a tool unavailable | Use supported equivalents for the same saved artifacts and public interfaces. If submission or source inspection is unavailable, save a precise handoff and disclose the limitation; do not claim a database update or examination that did not occur |

No provider name, model brand, native Agent API or persistent conversation identifier is required by this procedure. Qualification concerns the actual configuration and is reusable only while applicable. A new configuration follows existing qualification rules. A role prompt, compaction, or fork containing primary reasoning does not create a clean independent context.

Primary handoffs may include primary reasoning. Independent delivery contains only its authorized neutral source material, targets, scaffold and role guidance. Coordinator recovery inventories, primary judgments and proposed repairs stay private. Later exposure is recorded honestly and never retroactively described as blind review.

## 3. Normal operating procedure

At startup or resume, inspect current state and saved outputs before commissioning more work. Preserve the audit's declared scope and existing folder. Arrange qualification once for the actual independent configuration. Start with a scope-appropriate result/source inventory: manuscript-wide for Full, requested targets and required internal prerequisites for Focused. Develop detailed intermediate records as each proof is examined. This avoids requiring a fully elaborated graph before useful examination starts, without losing undispatched results, dependencies or alternative routes.

| Step | Work and saved result | Exit condition and next operation |
| --- | --- | --- |
| 1. Settle the local representation | Compare exact statements, hypotheses, setup, formulas and source boundaries with the manuscript. Commit identified transcription/boundary corrections through authorized interfaces | No known correction affecting the planned review input remains pending. Missing material is explicit. Continue to the primary examination |
| 2. Examine and save | The primary owner checks supplier applications, substantive deductions, cases and composition; saves reasoning, findings and coverage using generated guidance | Assigned work has explicit outcomes or a precise unfinished question. Integrate returned primary work before routine independent dispatch |
| 3. Obtain independent examination | Deliver complete authorized neutral context for that unit to a qualified separate examiner | Save its actual reasoning and limitations with original packet identity and provenance. A route-level judgment can contain routine calculations; distinct defects, conclusions or routes remain distinguishable |
| 4. Integrate and compare | Submit unchanged responses, resolve source-target identities, then compare applicable primary and independent reasoning and conditions | Record reconciliation, including a supported negative conclusion or unresolved disagreement. Investigate only a specifically identified remaining issue |
| 5. Checkpoint and continue | Render at a meaningful boundary and state current progress, recoverable output and remaining work | Continue another unit or perform final inventory/global checks when local changes have settled |

These are operating steps, not persisted database states or a new eligibility gate. The default is to complete a unit's primary pass before routine independent dispatch, because that pass can reveal representation errors. An early independent examination is allowed for a specific scientific purpose once its exact target and available source are clear. Record that purpose and limitations in existing assignment/run notes.

Readiness is local: unsettled B does not block settled A. A supplier's full audit need not finish before its application is examined under an explicit premise. Preserve conditional support and the distinction between a checked implication and an established theorem. Missing source does not authorize removing a result from scope.

When a worker returns, inspect and integrate useful output before repeatedly starting more contexts. The number of database rows or role names does not determine worker count. There is no fixed worker quota, judgment-row quota or prescribed parallelism. An independent route judgment must still explain every substantive inference it claims to examine.

Finish with the manuscript/supplement inventory comparison for the declared scope, required global examinations and the existing completion assessment. Publish only when existing rules permit it. A negative mathematical outcome is compatible with completed examination; unresolved required work remains visible. Triage retains its existing limited purpose and makes no completed-proof-audit claim.

### A pathological example

Suppose the stored theorem omits an assumption that is present in the paper. Correct the stored representation before routine independent dispatch. If instead the assumption is absent from the paper and the proof needs it, record the gap. Do not add the assumption to make the audited theorem true.

If the independent examiner returns the same gap but uses a source location instead of a database ID, map that saved judgment. No new mathematical examination is needed solely for the ID. Once the gap is characterized and reconciled, proceed to remaining audit work; do not repeatedly ask for a repaired proof.

## 4. Recovery procedure and stopping rules

At an interruption or a failed operation, first inspect intake receipts and the explicitly known assignment/delivery directories. Match packet identity and exact bytes, not descriptive folder names. Distinguish stored input, accepted/current evidence and remaining mathematical work. Never overwrite the old attempt.

| Evidence or problem | Next operation | Need a new examination? |
| --- | --- | --- |
| Intake remains `received` | Recover and replay the exact saved envelope/response with the same request ID | No, unless subsequently changed scientific inputs require it |
| Valid output exists outside intake | Inspect packet, actual provenance and applicability; submit or follow its specific recovery diagnostic | Not merely because its task is still listed as missing |
| Terminal rejection caused only by an administrative envelope field | Correct the envelope, preserve worker bytes and actual provenance, use a fresh request ID as required | No |
| Saved independent response only awaits source-target correspondence | Map unchanged judgments using coordinator context; preserve whole-response acceptance | No |
| Wrong worker-authored kind, incompatible combined target, scientific wording or malformed worker response | Obtain an authored correction through the existing response contract; preserve the original | Target the actual issue. Prefer genuine author continuity; otherwise use the replacement-examiner rule above |
| Missing neutral source | Capture the source and use the existing independent context-extension mechanism | The examiner must examine the additional material and author the response for the extended packet |
| A consumed statement, setup, boundary or source changed | Commit the correction, inspect changed-input diagnostics and renew affected examinations/dependencies | Yes where required; unrelated current work remains usable |
| A gap/refutation or a substantive disagreement | Save the finding and compare the reasoning; record the actual reconciliation outcome | Only for a specific unanswered scientific question, never solely to obtain agreement or support |
| Existing evidence, reasoning and blocker are unchanged | Follow the existing next action or stop that branch with an explicit remaining need; continue other useful work | Do not generate another identical draft or repeat the same failed operation |

Clerical and scientific problems can coexist. Mapping guidance must not hide a missing-source, wrong-kind, stale-input or provenance problem. An action is advice about the present evidence, not permission to bypass acceptance rules or invent scientific fields.

Before yielding, save reasoning and remaining questions, retained response paths and identities, current database revision and report revision. A short continuation note points to these artifacts and identifies the next operation; it is not a second authoritative task ledger. If rendering fails, label retained HTML as old and link the saved database/work.

Progress communication should name the proof, current operation, meaningful result and next unresolved need. Distinguish “examined and saved,” “awaiting integration,” “needs additional examination,” and “required review unavailable.” These are explanations, not new stored statuses. Avoid claiming that an exit code, returned worker or written HTML proves the audit finished.

## 5. Ordered implementation packages

### A. Consolidate the workflow instructions

Make [controller-workflow.md](../stat-proof-check/references/controller-workflow.md) the canonical operating sequence and recovery procedure. Keep source inventory, meaningful decomposition and scope details in [coordinator-protocol.md](../stat-proof-check/references/coordinator-protocol.md); link instead of duplicating the sequence.

Update [SKILL.md](../stat-proof-check/SKILL.md) with the short ownership/default-order rule and canonical link. Align [primary-checker.md](../stat-proof-check/references/primary-checker.md), [independent-checker.md](../stat-proof-check/references/independent-checker.md) and [reconciler.md](../stat-proof-check/references/reconciler.md). Amend [database-audit.md](../stat-proof-check/references/database-audit.md) stopping guidance and qualification/mapping references only where needed for the capability fallbacks. Preserve explicit invocation and current scientific standards.

Replace overlapping instructions. Do not make agents load this architecture handoff, the design proposal or another mandatory manual during ordinary audits. Examples must work through existing public commands and role-appropriate artifacts, without a named provider API.

### B. Make generated primary guidance sufficient for authoring

Modify maintained [assistance.py](../shared/paper_core/assistance.py) and the assistance integration in [controller.py](../shared/paper_core/controller.py).

- Add a primary-only task table derived from assigned tasks: task ID, exact target/label, check kind and response variant. Derive historical assignment labels and identities from the original pinned packet, not current renamed records. Keep role-only guidance reusable and attach assignment-specific information in the existing assistance integration, without another lookup script written by the agent.
- Generate blank coverage and finding row templates from the current contract, including required nullable fields. Explain eligible check-task links and pinned existing checks. Keep templates in guidance beside the strict response scaffold, rather than inserting invented coverage/findings into a submission.
- Preserve the existing blank/draft response behavior. Do not preselect scientific scope, evidence, classification, outcome, agreement or positive source comparison.
- Keep explanatory metadata outside strict response JSON. Use existing artifact names and `worker_delivery_files`; independent delivery gains no primary table, private decomposition or coordinator recovery information.

Acceptance: a primary examiner can author a mixed response containing source comparison, checks, coverage and a finding from delivered artifacts without reading backend code or guessing required fields.

### C. Make results point to the actual next operation

Use [review.py](../shared/paper_core/review.py), controller submission/preparation and [cli.py](../shared/paper_core/cli.py). Add structured diagnostic categories where the relevant condition is detected. Retain existing human-readable reasons and compatible result fields; do not classify conditions by matching English error strings.

Each new action description identifies its operation, affected packet/request/response or judgment indexes, reason and required input. Give an executable existing command when its arguments are known; otherwise say what authored input is needed. Do not fabricate command flags, mapping targets, reviewer identity or completed scientific records.

Required decisions:

- A saved response awaiting only correspondence points to mapping that response, not a new review. Additional blockers remain separately visible. Partial mapping remains pending until existing whole-response acceptance requirements are met.
- Envelope errors, worker-response corrections, missing neutral source, changed scientific inputs and interrupted intake have distinct remedies from Section 4.
- Explicit task preparation reports requested tasks, actually assigned tasks and the prerequisite relationship, including when a valid packet contains predecessors. Preserve current selection semantics and repeated `--task` behavior.
- A size failure offers a supported bounded retry when justified, or identifies the context that cannot fit. An estimated lower bound is not a promise that the next size will fit. No silent truncation or splitting of a joint mathematical unit.
- Successful preparation with deferred unrelated work is not presented as an error. A negative scientific outcome is not a transport failure.

Share the underlying judgment diagnostics with the optional direct review/mapping path so its remedy cannot contradict controller guidance. New descriptors belong in command output and assistance, not scientific record bodies. Keep historical terminal receipts immutable, including byte-identical retries. New live advice belongs in current inspection and is derived from authoritative state; do not backfill old receipts. Existing record/storage/packet/projection formats and acceptance states remain unchanged.

Implementation audit refinement: stale historical responses may already have applicable current replacements. Inspect their current obligations and replacement evidence before requesting renewal. Preserve unresolved old concerns; satisfied composition alone does not prove every concern was resolved.

### D. Expose current recoverable work through existing inspection

Extend `work inspect` and existing mapping assistance, not a new queue or persisted registry. For a selected request/response, show available packet/request/response identities, actual reviewer provenance, current response acceptance, mapped/pending judgment indexes, relevant changed-input diagnostics and applicable next actions. Separate original receipt facts from the current revision's assessment. Acceptance of intake or a response must not imply every derived check is current or eligible as independent evidence. Reuse existing eligibility assessment, including compromised exposure, rather than implement another evaluator.

Reuse existing paginated audit history and bounded inspection. Fetch detailed current state for selected entries rather than parsing all historical blobs or computing an unbounded report on every command. Clearly disclose omitted/truncated entries. Direct-review responses without controller intake remain inspectable through the existing response/mapping path; do not invent a controller request for them.

For this revision, directory recovery is an explicit coordinator procedure: inspect the known assignment and delivery locations, read candidate packet identities, compare available exact response hashes with intake, and select the applicable saved attempt. Unknown identity/provenance stays unresolved. Files are recovery candidates, never credited merely because they exist. Do not implement a recursive filesystem scanner or automatic import.

This distinction is mandatory: database inspection sees submitted work; it cannot discover an unsubmitted file. The startup/resume and stopping instructions must include both sources. Prefer existing manifests, receipts and saved bytes over a newly maintained inventory file.

### E. Integrate, validate and prepare delivery

Implement and test B/C before D so current inspection reuses the same diagnostics instead of developing another interpretation. Finalize A against the actual interfaces. Rebuild both generated bundles from maintained shared source using [build_paper_core_bundles.py](../tools/build_paper_core_bundles.py); never hand-edit bundled copies.

Use the existing shared runtimes and repository test commands. Do not create a project-local environment. Record the candidate commits, changed files and bundle identity before behavioral validation. Preserve original test-center databases and transcripts; use read-only inspection or disposable copies for replay.

This handoff does not perform a version bump, installation or release. A later release must use the repository's normal compatible versioning, bundle checks and validated installation process, with validation limitations stated accurately. Do not present passing software tests as evidence that the interrupted live audit now completes.

## 6. Validation and acceptance

### Deterministic behavior tests

Extend relevant existing tests rather than introduce a parallel test framework:

| Behavior to demonstrate | Starting test locations under `tests/new_format/` |
| --- | --- |
| Generated mixed primary response is authorable and validates; blank scientific fields and independent privacy remain intact | `test_assistance.py`, `test_revision_interfaces.py`, `test_controller.py` |
| Pending correspondence gives mapping guidance; partial/final mapping updates current state while original receipt and response bytes remain unchanged | `test_revision_guidance.py`, `test_review.py`, `test_controller.py` |
| Mixed pending causes remain distinct; wrong-kind/source/scope problems are not mislabeled as simple mapping | `test_controller_adversarial.py`, `test_context_extension.py`, `test_superset_review.py` |
| Requested tasks expose prerequisite selection; oversized context produces honest bounded advice; valid deferrals remain usable | `test_work.py`, `test_work_packets.py`, `test_cli.py` |
| Interrupted intake, envelope correction, unchanged work, real input changes and primary renewal preserve their different recovery semantics | `test_revision_recovery_trace.py`, `test_revision_interfaces.py`, `test_neutral_freshness.py` |
| Gaps/refutations and unresolved disagreement survive integration without forced agreement; completeness guards remain intact | `test_reconciliation_completion.py`, `test_reconciliation_recovery.py`, `test_acceptance.py` |
| Existing database/bundle compatibility and both installed package entrypoints retain their behavior | `test_packaging.py`, `test_overview_bridge.py`, package/installer suites |

Include explicit regressions for historical task labels after a live rename, accepted-but-compromised reviews receiving no independent credit, audit-level pagination without loading worker blobs, unchanged receipt replay after mapping, and read-only inspection preserving receipts, blobs and mathematical revision. Retain the storage immutability checks in `test_work_storage.py` and the test that independent eligibility does not require primary completion.

Extend the public-interface lifecycle in `test_targeted_workflow.py` or `test_revision_recovery_trace.py`; add a separate trace only if neither can express the new path clearly. It must include an unsent saved response, a misleading folder label, a mapped negative independent judgment, an interruption and an actual scientific input change. Demonstrate which outputs can be recovered and which need reexamination. Synthetic reviewer fixtures test protocol behavior, not independence or mathematical accuracy.

Run focused tests during implementation, then the shared-core, proof-check, installer and Graphify checks listed in the [repository README](../README.md#backend-and-validation). Rebuild before package checks. Do not repeat passing suites without a relevant change or unresolved failure.

### Behavioral tests of the instructions

Use a small realistic proof task with a stored transcription mismatch, a genuine manuscript gap, related assignments and a deliberate interruption. Give the examiner the shipped skill/artifacts, not private hints about the intended next action. Observe whether it follows the procedure without coordinator rescue or newly invented helpers for supported operations.

Exercise these capabilities through controlled runs or truthful handoff drills:

1. Isolated independent workers, with unrelated primary work allowed concurrently.
2. Sequential source-only review through a separate session, without a subagent API.
3. No independent capability: useful primary progress and an honest incomplete handoff.
4. Primary context loss and an unavailable original independent author: saved work survives, successor provenance is truthful, and no exposed context is relabeled blind.

These cases test portability of the workflow. They do not require every branded model, and passing them is not a claim that every future agent will comply. Include at least one real independent source-only examination; role-play by an already exposed coordinator is insufficient. If capacity or tools prevent a case, label it untested or blocked and retain its artifacts.

Then run the same RF-HTE paper, supplement and declared supplier scope as the investigated 2.3.7 attempt on a recorded candidate configuration. Preserve scientific scope and negative findings. Use a stable candidate for the run; record any necessary intervention or version change. A reduced-scope or independence-disabled run is not a full-run success.

Record launches by purpose, reasons for repeated examination, saved outputs awaiting integration, current/remaining required work, actual final assessment and report/database revisions. Separate process elapsed time from measured model time; leave unknown quantities unknown. Compare coordination work, not just worker counts or response rows. Do not infer a speedup from unlike papers or sacrifice scientific detail to achieve a time target.

### Definition of done

- The ordinary path and recovery rules have one canonical location, with matching role briefs and no provider-specific dependency.
- Generated artifacts support authoring, correct next operations and recovery without invented scientific answers or an added workflow system.
- Software tests and capability cases have recorded outcomes, and a representative full audit has either verified completion or an explicit remaining blocker. A blocked/untested live run leaves the workflow improvement unverified end to end, even if implementation is complete.
- Delivery includes the implementation diff, candidate/bundle identity, validation record, preserved scientific findings and any residual limitations. The user can tell what was changed, what actually ran and whether the original failure was reproduced or resolved.
