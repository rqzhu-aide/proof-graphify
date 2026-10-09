# Handoff: automatic audit workflow

Status: proposed revision, second audit incorporated; not implemented. Baseline: stat-proof-check 2.3.1.

The proposed folder name and layout below are historical. Current work follows the [database-audit folder convention](../stat-proof-check/references/database-audit.md#choose-the-work-folder), rooted at `proof-check-<paper-name>/`; the wrapper and managed-run design in this proposal remain unimplemented.

## Decision and size

Implement a **moderate, bounded workflow revision**. A documentation patch cannot reliably fix output placement, interrupted execution or inconsistent delivery. The existing database, controller, validation and renderer already provide most of the difficult functionality, so this does not require a replacement system.

Planning estimate: **5 to 8 focused engineering days**, including integration tests and packaging, conditional on reusing the existing backend and limiting adapters to the native operations listed below. This estimate remains provisional until the first complete and interrupted lifecycle fixtures pass. Crash recovery and publication consistency are the main uncertainties. Deliver three cohesive implementation slices; reassess scope if they require a storage migration or a new scheduling subsystem. Cut generalized authoring conveniences first, not the required qualification/mapping path or interruption recovery.

The objective is to make routine administration automatic: paths, identities, envelopes, recovery, report generation and completion reporting. Mathematical targets, source interpretation, coverage classification, proof judgments and adjudication remain explicit inputs. Do not add another layer of prose instructions asking executions to perform bookkeeping carefully.

## Evidence and boundaries

The reviewed test set is `stat-proof-check@v2.3.1+distributional-rl-main__20260926-220218`. All five databases passed structural validation; four remained process-incomplete. The released case completed its recorded scope with source limitations and did not establish examination of every supplementary proof.

Observed failures relevant to this revision:

- Inconsistent database/report locations and many loose intermediate files.
- Custom scripts repeatedly constructing schemas, request IDs, envelopes and output directories.
- Restart conflicts, stale-work renewal and useful reviews left outside the database workflow.
- A custom renewal script changing negative judgments to `supported` while retaining negative reasoning.
- A custom reconciliation loop inserting `agree` without comparing the judgments.

The shipped response scaffolds already leave verdicts unfinished. Do not misdiagnose them as defaulting to success. The supported workflow should remove the need to replace those scaffolds with disposable scripts.

A reported general scheduler failure was not reproduced across saved revisions. Preserve current selection and bounded-unit behavior. Improve the presentation of actual blockers; do not redesign scheduling on that allegation.

## Architecture choice

Add one skill-local entrypoint: `stat-proof-check/scripts/audit_workflow.py`. It imports the bundled `paper_core` and uses its existing APIs. Put filesystem conventions and skill-specific completion policy here, not in the shared generic CLI.

Keep SQLite authoritative. A small `run.json` stores only workflow format, run identity, database generation/path, paper/audit identifiers and creation package identity. Paths managed by the wrapper are relative to its root. It must not store a second copy of task state, scientific verdicts or completion truth. Derive those from the database. Verify the database generation on resume so replacing `audit.db` cannot silently attach another run. Record the actual package identity per operation; a compatible software upgrade preserves old evidence/deliveries and uses a new delivery identity.

Use existing transaction, packet, intake, provenance, freshness, validation and publication mechanisms. Changes to shared behavior are made in `shared/paper_core` and then bundled into both skills. Do not edit either generated bundle directly.

Default managed layout:

```text
proofcheck-audit/
  run.json
  audit.db
  sources.json                 generated inventory of captured source identities
  work/
    operations/<operation-id>/ saved administrative intent and recovery inputs
    authoring/<request-id>/    generated shape, authored input, receipt
    packets/<packet-id>/      existing packet, scaffold and guidance artifacts
    guidance/<packet-id>/<revision>/ current coordinator guidance
    submissions/<request-id>/
      response.json           exact submitted bytes, never overwritten
      envelope.json
      receipt.json
    scratch/                  extraction and other temporary working files
  deliveries/<delivery-key>/
    report.html
    status.json
    remaining-work.json
    export.json
    receipt.json
  delivery.json               current validated delivery locator
```

The command prints an absolute clickable report path. `delivery.json` provides a stable machine-readable location without maintaining a second report copy. Original source files need not move. All wrapper-generated files go inside this root; reject path escapes and collisions with registered source files. Do not recursively police unrelated user files or delete loose artifacts from earlier runs.

## Slice 1: managed workspace and ordinary execution

Estimate: 2 to 3 days. Implement the following supported surface. Names below are proposed commands, not existing functionality.

| Command | Automatic work | Explicit input |
|---|---|---|
| `start ROOT` | Check package/runtime, establish layout, initialize database, capture named sources, allocate run/audit identities, save administrative metadata | Source root/files, title and audit mode; focused scope remains unconfigured until actual registered targets are supplied |
| `resume ROOT` | Load existing identities, derive status/work, recover saved administrative artifacts, report the current assignment or exact next operation | Only an ambiguous choice of an existing assignment, if needed |
| `author ROOT` | Generate current-contract authoring shapes, IDs, packet/version pins and a fixed request directory; expose exact stored excerpts and lengths | Record kinds/counts, target references, source locators, graph content and classifications |
| `prepare ROOT` | Reuse controller selection, write the packet/guidance/scaffold at its canonical location, stage an administrative submission envelope | Role and optional focus; actual reviewer/qualification/exposure when required |
| `submit ROOT` | Validate the selected request type, preserve input bytes, complete administrative fields, invoke existing acceptance/intake, save receipt and next action | Completed authoring input or role response; no generated scientific decisions |
| `finish ROOT` | Produce the revision-consistent complete or incomplete delivery described in Slice 3 | No manually selected completion label |

For `author` and `submit`, use a fixed adapter table selected by an explicit operation kind. The saved operation records the selected native command so submit never guesses from JSON fields. Required adapters are source capture, source anchoring, source review, graph edits, audit configuration, qualification recording/attachment, independent-response mapping, and ordinary controller responses. Generate native shapes and administrative fields; reuse their different validation rules. Do not introduce arbitrary command adaptation, a compact graph language, a second proof-record schema or automatic proof decomposition.

Qualification packing hashes and encodes the exact authored evidence/response files, calls the existing dedicated qualification API, then attaches its saved ID through an audit configuration packet in the permitted mode. Recording and attachment are separately resumable steps. Grades and actual review provenance are supplied inputs, never inferred. Mapping retains the original response/packet A, obtains private authorization packet B, and scaffolds/submits the existing mapping request. Target matches and rationales remain authored; bytes from A are unchanged. For additional source context, expose the existing extension operation through `prepare --extend`; never relabel the old response as covering new material.

The existing probability example is primary-only and deliberately incomplete. Keep that limitation. Its walkthrough alone cannot validate the completion promise: add one small full-lifecycle integration fixture covering qualification, attachment, pending-response mapping and reconciliation. Synthetic fixture records test software behavior and must not be reused as real qualification evidence.

Return compact command receipts containing saved paths, counts, the relevant blocker and next operation. Keep full status and detailed evidence in files instead of emitting the whole snapshot after each command. Preparation also returns the exact delivery-file list for its role. An independent source-only assignment must exclude the private coordinator manifest, mapping, qualification and reconciliation material from that list; do not instruct the caller to deliver the entire packet directory.

Safe defaults for a new Full/Focused audit are `independent_required:true` and the three existing global tasks required. Never automatically invent exclusions, mark a global task inapplicable or infer that the manuscript inventory is exhaustive. Missing qualification must allow primary work to be saved.

A Focused audit with no registered targets can save sources and graph edits, but proof preparation must report `scope_required`. The core already prevents Full/Focused completion when its effective statement set is empty; reuse that assessment and expose the missing-scope reason in delivery instead of adding another scope evaluator. Use the audit configuration adapter to attach the authored targets without recreating the run.

Expose the exact captured anchor excerpt and its character count through existing query data. A coverage scaffold may supply anchor identities and span bounds, but must leave substantive/structural classification, claim links and examination evidence unfinished. Do not fill full-span coverage as proof credit. Surface missing boundaries and coverage before composition so they can be handled in the same response where appropriate.

Configure UTF-8 for the wrapper's input/output and subprocesses using `audit_io.py`. Use shared installed runtimes. Do not create a private environment or add a dependency.

Completion criteria for this slice:

- The supplied walkthrough can start, author a small graph, record supplied qualification evidence, prepare/map/reconcile supplied review responses and deliver the result without custom orchestration scripts or repeated output-path choices.
- Running from a different working directory produces the same managed locations.
- Repeating `start` with matching identity does not recreate the database or recapture unchanged evidence; conflicting reuse returns a clear error.

## Slice 2: recovery and judgment-preserving assistance

Estimate: 1 to 2 days, overlapping Slice 1 testing.

### Identities and partial failures

Persist an operation intent, native request IDs and input hashes before invoking its mutating step. Reuse the existing receipts and stored packet/submission history as the recovery authority; operation files track administration, not proof status. Support sequential wrapper commands for one root. Concurrent dispatch/orchestration is out of scope; retain native transaction/conflict checks.

Initialization currently allocates paper and database identities internally. Save start intent first, then recover a successfully initialized database from its generation and initial paper commit if the manifest write was interrupted. Verify the saved source-root/title intent and owned path; never reinitialize or blindly adopt an arbitrary existing database. Do not automatically recapture changed source files on resume.

Packet creation also allocates identities internally today. Add narrow optional caller-supplied packet IDs to the creation paths used by the wrapper, including authoring, ordinary work and supplied-route/extension work. Save that ID, normalized preparation options and starting revision in the operation intent. If the packet already exists, verify its audit/mode/context against the saved intent and inspect it; never select a new assignment under the old ID. If it does not exist and the relevant starting state has changed, return a conflict/new-operation action. Default lower-level behavior stays unchanged; no storage migration or task ledger is required.

- Before native preprocessing, look up the saved request ID and compare its canonical request digest or exact-response/envelope digest, using the native command's digest rules. Return an existing commit/intake receipt on an identical retry. This preflight is necessary for source anchors/reviews as well as submissions: native source validation can reject an already accepted request before reaching the acceptance kernel's replay check. A saved receipt remains historical; show current freshness separately.
- A revised input uses a new attempt directory and identity. The previous bytes remain intact.
- If intake is `received`, recover its saved envelope/response and replay those exact bytes once when resuming that operation. A repeated interruption is returned as a blocker; no retry loop.
- If database preparation succeeded before artifact writing failed, inspect the stored packet and reconstruct missing generated files instead of preparing duplicate work.
- Existing authored response files are never replaced by a newly generated scaffold.
- For reconciliation, allocate and persist the request identity before editing the response because it also appears inside the response. Never change submitted response bytes to make an envelope match.
- If an uncommitted source-capture attempt encounters different physical source bytes, return a new-attempt requirement instead of replaying its old ID against new evidence. Replaying an accepted request does not reread or recapture those files.

There are two concrete artifact-recovery edges. `controller.response_scaffold()` mints a reconciliation request ID on each inspection, and `inspect_work()` regenerates coordinator guidance from the current assessment. Freeze the packet, original scaffold and original delivered material once saved; preserve the administrative request identity. Store newly computed coordinator guidance under its assessed revision, not over an immutable original file. Recovery after a later database commit must not fail solely because guidance changed. Do not copy fresh candidate pins into a saved response automatically.

Repeated `prepare` may reuse an outstanding managed assignment only when role, focus/task/route selection, context limits and relevant input bindings match. An envelope or draft is reused only for the same supplied reviewer, qualification and exposure provenance as well. Changed provenance creates a separate attempt; it must never inherit another examination's response. With changed consumed evidence, show the existing freshness/recovery action instead of silently rebasing it. If several assignments are outstanding, return their identities rather than guessing. No background dispatch or concurrency manager is required.

### Preserve judgments mechanically

Extend existing coordinator guidance with the exact prior outcome, conditions, reasoning, evidence references and changed-input summary for eligible renewal predecessors. A requested renewal draft copies the selected predecessor's content and `supersedes` pin while retaining `state:draft`. Do not mark it complete or treat old evidence as newly examined. If references are no longer eligible, preserve the historical material in guidance and leave invalid response fields unfinished with an explicit diagnostic.

Select a predecessor only when unambiguous under current eligibility rules, otherwise require the exact pin. Preserve `gap`, `refuted` and `inconclusive` values; never substitute a successful default. An examiner may deliberately revise a verdict through the existing response protocol after reexamination.

For reconciliation, present the eligible paired outcomes and condition sets with their pins. Prepopulate only administrative/reference fields. Leave decision and rationale unauthored even when outcome labels match. Do not infer agreement from role presence or identical labels.

Do not add natural-language contradiction detection or a new verdict-change approval protocol in this revision. These would be costly semantic mechanisms with weaker guarantees than their names suggest. The mechanical guarantee is that official preparation/recovery helpers do not change scientific judgments themselves.

### Bounded diagnostics

Reuse current unit selection and packet-size limits. When preparation returns no packet, return a structured reason, the existing coordinator action and an eligible alternative focus if one is directly available. Distinguish no remaining work, prerequisite work and an oversized selected unit. Never equate `prepared:false` with completion.

Do not automatically truncate arguments, increase limits to the maximum on every run or repeatedly probe focuses. Those changes are unnecessary for the demonstrated failures.

## Slice 3: consistent complete and incomplete delivery

Estimate: 2 to 3 days including lifecycle tests, documentation and packaging.

`finish` is a normal required operation for every run, including an unfinished run. It automatically produces either a completed release or an explicitly incomplete working delivery. A fully examined negative result can be complete; missing examination/review cannot.

1. Choose one database revision and compute validation, status, source identity, projection, remaining work and export inputs for that revision. Save the exact delivery/render payloads before publishing and reuse them on recovery. Record revision alone is insufficient: publication history and `published_revision` can change without a new mathematical revision. Live head/publication metadata is observational, not part of the pinned scientific identity.
2. Enforce the skill policy: Full/Focused cannot receive a completed delivery with independent review disabled. Triage never receives a proof-completion claim. Keep this policy at the skill boundary; do not remove generic partial-audit flexibility from the shared schema.
3. For a complete audit, reuse the existing release gate and publication behavior. For an incomplete audit, reuse working publication and include unfinished obligations, source limitations/exclusions and an exact resume command. Do not require scientific findings to be resolved merely to deliver a useful incomplete report.
4. Build an unadvertised generation at its final delivery path, using the existing atomic per-file writes. Write the validated receipt last, then atomically update `delivery.json` only after all required files exist and validate. An interrupted generation without its valid receipt is pending and may be resumed under the same saved operation identity; it is not an immutable release yet. Failure preserves the prior valid delivery and returns an error receipt; do not advertise a missing report. This avoids recording temporary staging paths in publication records and then breaking them by renaming the directory.
5. Repeated finish for the same audit/revision/source/package/render identity verifies and reuses the delivered artifact set. If existing artifacts fail verification, preserve them and return a diagnostic rather than overwriting an allegedly immutable release.

The delivery receipt must contain: delivery state, core process-complete value, skill-policy completion value/reasons, paper/audit identity, database revision, captured-source identity, package/render identity, artifact paths and hashes, exclusions/limitations, and the resume command when incomplete. Keep operational failure distinct from a successfully delivered incomplete assessment. Ordinary success exit status alone is not proof of completion.

Pass the computed skill-policy result as an optional rendering context. Every prominent completion label in HTML must agree with the delivery receipt, including empty scope and disabled required review; retain raw core completion in the recorded details. Merely calling the report a working copy is insufficient because the current reader also prints core completion independently. Limit renderer changes to these status labels/reasons and their acceptance checks; do not redesign cards or alter mathematical node assessments.

Define the delivery key as a digest of workflow-format/policy identity, database generation, audit ID, chosen revision, captured-source digest, and actual workflow/core/render package identities and explicit render options. Exclude timestamps, file locations, current head and publication history. `delivery.json` means latest successfully delivered snapshot, not necessarily latest database revision. Resume compares its revision with the live head and reports any lag.

Persist the publication-attempt ID before rendering. If interruption occurs after publication commits but before export/receipt, inspect that ID, verify the saved artifact/blob hash and reuse the successful publication while writing missing sidecars. Reusing the ID through `publish_report()` would currently hit a duplicate insert; assigning a new ID would duplicate publication. If no committed row exists, verify any partial file against the saved operation before rerendering. A recorded failed publication uses a fresh attempt ID under the same delivery operation. A completed generation missing only `delivery.json` is promoted after verification without rendering again. No receipt means pending, not permission to overwrite unrelated files.

Extract reusable release eligibility/build logic from the existing CLI as needed. Preserve its refusal to overwrite a nonempty release directory. The managed workflow may resume only its own pending generation with matching saved operation identity and artifacts; it must not relax the generic release command's directory guard.

**Important implementation detail:** `publish.render_input()` reads the live paper title, and publication derives a current source digest by default. Build the title and source identity from the selected snapshot using existing snapshot/status accessors, then publish the saved render input without rebuilding it from live records. Do not extend packet digest behavior merely for reporting. Export already derives source provenance from records at the selected revision; cover it in regression without changing it unless a defect is demonstrated. Later database activity must not change a pending generation's saved inputs. Fresh resume information remains separate from delivered status.

Reproducibility means the same pinned evidence and package produce the same assessment and inspectable report content. Newly rendered files currently include build timestamps. Do not promise byte-identical fresh rendering; repeated finish should reuse verified artifact bytes instead.

## File boundaries

| Area | Expected changes |
|---|---|
| `stat-proof-check/scripts/audit_workflow.py` | New skill-local command surface, root/path policy, administrative artifacts, recovery and delivery orchestration |
| `stat-proof-check/scripts/audit_io.py` | Reuse UTF-8 handling; add a small shared atomic-write helper only if needed |
| `shared/paper_core/controller.py`, `packets.py`, `assistance.py` | Optional persisted packet identities, stable-scaffold recovery, revision-labeled guidance and judgment-preserving assistance |
| `shared/paper_core/publish.py`, `cli.py`, `renderer/render_projection.mjs` | Publish saved snapshot input, reuse release eligibility and render consistent policy-completion labels; existing export behavior is regression-tested |
| `stat-proof-check/SKILL.md`, `references/database-audit.md`, `references/controller-workflow.md`, qualification/mapping references | Make the managed workflow the normal route; retain lower-level recovery interfaces; replace bookkeeping snippets with the supported commands |
| `tests/new_format/test_audit_workflow.py` | New user-visible lifecycle and interruption tests using existing fixtures |
| Existing assistance/controller/reconciliation/publication tests | Add the narrow regressions below |

Do not modify mathematical assessment/freshness semantics merely to make more work appear complete. If a separately reproduced defect requires that, isolate it with its own regression and scope decision.

## Acceptance tests and evaluation budget

Use the existing test fixtures and shared runtimes. Test observable consequences rather than documentation wording or copied implementation logic.

| Case | Required outcome |
|---|---|
| New run from another working directory | All generated artifacts use the declared root; source files unchanged |
| Matching start/resume repeated | Same identities and source versions; no duplicate authoring/source-review records |
| Interrupt after initialization before run manifest | Recover the matching initialized database; reject another database generation |
| Interrupt between database commit and artifact write | Original packet/request recovered; saved response preserved |
| Repeat accepted anchor/source-review request after later source edits | Return the original receipt before native preprocessing; report current freshness separately |
| Source bytes change before an uncommitted capture retry | No reuse of old request identity for changed evidence |
| Identical submission replay, then revised submission | Original receipt reused; revised bytes get a separate attempt |
| Reconciliation prepare/inspect/resume | Scaffold/envelope request identity stays consistent; no output conflict caused by regeneration |
| Another commit occurs before interrupted preparation resumes | Frozen material is preserved; current guidance has its own revision-labeled path |
| Reviewer/qualification/exposure changes | No reuse of another examination's envelope or response; private files absent from independent delivery list |
| Complete native qualification-to-mapping path | Supplied evidence packed/attached and original response mapped/reconciled without custom scripts or altered response bytes |
| Negative or inconclusive renewal | Draft preserves outcome/conditions; no automatic completion or conversion to supported |
| Conflicting review pair | Both opinions retained; no generated agree decision |
| Complete audit with an examined defect | Completed delivery truthfully retains the defect |
| Required review unfinished, required source obligation unresolved, or Full/Focused independence disabled | Successful limited delivery with remaining work; no completed-skill claim; explicitly scoped limitations alone do not force incompletion |
| Focused targets absent or effective target set empty | Authoring can continue; no proof-work preparation or completed-skill delivery |
| Core complete but skill policy incomplete | HTML completion labels and receipt both show incomplete; raw core value remains inspectable |
| Evidence/title/source changes during finish | Every delivered artifact uses one recorded revision and identity |
| Renderer/export failure, then retry | Previous valid delivery locator survives; partial output is not advertised |
| Interrupt after publication commit, before receipt, or before locator update | Resume only missing steps; no duplicate publication, changed render inputs or unnecessary render |
| Delivery becomes current | Saved publication and receipt paths resolve to final artifacts, with no temporary-directory references |
| Repeat finish unchanged | Verified existing artifact set returned without another render/release |

For evaluation, first run the focused suites, then the required database and package suites once the source is stable. If shared code changes, rebuild both bundles and run the companion compatibility suite. Avoid repeatedly rerunning the full suites without a new failure or change.

Use copies of the five harvested databases to check neutral status preservation and complete/incomplete delivery; never modify the originals. Do not rerun five full paper audits merely to validate path and recovery automation.

Add two small source-grounded behavioral cases: a correct final identity with a defective preceding equality, and a valid cited supplier that is initially unavailable. These examine source-faithful judgment quality; do not pretend that a mechanical assertion can decide their mathematics. Bound the cases to the relevant passages and run them once after the workflow is stable. This is a bounded release evaluation, not an extra semantic stage added to every future audit. Broader mathematical evaluation is separate from this release's deterministic acceptance.

Reuse existing telemetry for preparation, submission, renewal and rendering. Record retries and duplicate operations in lifecycle fixtures. Do not add a performance framework or fragile wall-clock assertions. Expected savings are reduced custom scripting and repeated bookkeeping; do not promise a percentage runtime reduction.

## Explicit cost limits

- No database format migration, second task database, generic workflow engine or new scheduler.
- No automatic scientific verdicts, automatic reconciliation, speculative graph construction or semantic prose validator.
- No reader/card redesign; only the completion labels needed to keep HTML and the delivery receipt consistent may change.
- No background execution service, recursive retry system or new tool dependency.
- No general migration/cleanup of historical folder layouts. Existing databases and lower-level commands remain usable; adoption automation can be a later demonstrated need.
- No automatic external-source acquisition policy or assertion of exhaustive inventory from parser candidates.
- No additional semantic fields requiring every proof step to satisfy a new checklist.

This plan adds functionality, so a minor skill release is more appropriate than describing the result as only a patch. Do not change versions during planning. Shared-core changes require synchronized bundles; Proof Graphify's ordinary overview behavior should remain unchanged. Release, installation and remote publication are subsequent implementation steps, not part of this planning deliverable.

## Handoff completion criterion

First prove one small completed path and the same path interrupted at the packet/publication boundaries, including qualification and mapping. Confirm the effort estimate at that point before expanding authoring conveniences.

A fresh execution can follow the shipped workflow from startup to a completed or explicitly limited report without writing orchestration code, guessing administrative JSON fields or choosing new artifact paths. Interrupting and resuming does not duplicate accepted work. All delivered files agree on their saved evidence snapshot and completion policy. The software supplies unfinished scientific fields and preserves authored decisions; it never fills missing mathematical work with a successful status.
