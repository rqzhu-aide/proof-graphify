# Targeted RF-HTE workflow revision handoff

Date: 2026-10-08. Baseline: canonical `stat-proof-check` version 3.0.9 in `stat-proof-check-v3`. Proposed next patch: 3.0.10. This document specifies work; it does not implement or install it.

## Intended result and boundary

Let a coordinator finish the planned audit with less command interpretation and fewer administrative repairs. Keep the three stages, one database owner, coherent proof assignments, original returned judgments and frozen HTML delivery. The workflow remains independent of agent, model and host.

The immediate revision has two independently deliverable parts: clearer preparation/response guidance and clearer reviewer dispatch/source navigation. A third part, adding explicit targets to an active audit, requires the bounded compatibility validation below before exposure as a normal command. Do not ship its prototype alone or turn its current limitation into a new instruction to wait for every reviewer.

No database schema expansion, compulsory source inventory, PDF concatenation, reviewer launcher, automatic proof repair, additional review round or new runtime completion gate is proposed. Do not change mathematical outcome semantics, silently normalize returned judgments, or modify Phase 3 rendering. `proof-graphify` and the shared/legacy cores are outside this revision.

## Evidence and what it does not establish

The RF-HTE run used the main paper and its supplied supplement. K3 skipped reviewer-route discovery and confused six examined proof shortcomings with unfinished coverage. Claude's attempt to include Footnote 8 and Remark 3 encountered an unsupported audit-edit route. GLM spent approximately 126 minutes in serial independent review. These are separate causes, not a demonstrated two-file ingestion failure.

The experiments are preserved under `../tmp/rf-hte-v309-fix-experiments-20261008/`:

- [Parent validation](../tmp/rf-hte-v309-fix-experiments-20261008/parent/validation.json): independent replays, source/install hashes and cross-experiment cautions.
- [Preparation experiment](../tmp/rf-hte-v309-fix-experiments-20261008/preparation/REPORT.md): 34 engineered API/storage/export checks passed. Existing guidance already explains coverage correctly; the experiment shortens it and makes conditional command feedback explicit.
- [Scope experiment](../tmp/rf-hte-v309-fix-experiments-20261008/scope/REPORT.md): completed old work survives additive scope changes; outstanding packets conflict and can then be reused incorrectly. A second audit loses credit for some old audit-specific work.
- [Source/dispatch experiment](../tmp/rf-hte-v309-fix-experiments-20261008/review-sources/REPORT.md): correctly selected split/combined TeX excerpts reach disjoint source-only groups identically. This does not test PDF glyph readability or automatic proof-boundary discovery.
- [Fresh operator exercise](../tmp/rf-hte-v309-fix-experiments-20261008/operator-probe/answers.json): six semantic decisions were appropriate. No baseline comparison or native scaffold was supplied; the list-form omissions in those answers are not valid native-submission evidence.

These results support narrow mechanics and guidance changes. They do not prove fewer errors for every model, mathematical accuracy or faster whole-paper runs. Synthetic reviewer responses are not actual independent scientific examinations.

## A. Clarify preparation and native response authoring

Primary seams: `scripts/paper_core/stage1.py`, `assistance.py`, `review_groups.py` and the public stage preparation handlers in `cli.py`. Verify `_compact_work` preserves feedback; its current behavior may need only a regression test. Inspect common callers so Stage 1 and Stage 2 report the same existing result consistently.

Add short coordinator-facing guidance only for these existing result states:

| Existing state | Information to expose |
| --- | --- |
| `prepared=true`, `reused=true` | This is the same saved assignment, not another task. Reuse its actual saved work, or select distinct ready work while excluding assigned task IDs. Generic repeated preparation does not advance the queue. |
| `prepared=false` | No worker packet or response scaffold was produced by this operation. Preserve the existing reason and diagnostics; do not suggest opening assumed files. |
| Oversized context | Point to the existing size diagnostic. An appropriate explicit larger cap or a coherent smaller selection may help. Do not prescribe repeatedly increasing limits or splitting every proof. |

Do not call a reused packet "current" or "valid" solely from its reuse flag. The scope experiment gives a counterexample. Preserve the actual task IDs and `conditional_on_task_ids`; explicit selection may still include prerequisites and is not a promise that arbitrary work is ready. Never dispatch work automatically.

Keep these hints in the coordinator's preparation result. Verify that the public CLI retains them after output compaction. They must not enter source-only worker evidence or become report content. Empty export directories need no cleanup workflow or new error condition.

Cover `stage2 prepare-group` explicitly. Group re-export and member packet reuse are different facts: a new group can contain a saved pending packet even when the group reports `reused=false`. Preserve existing membership/resume behavior and expose member reuse or saved-work cues. Preserve actionable size diagnostics for unassigned members, including mixed ready/oversized groups. An empty group may have an index and reviewer-delivery file, but no worker packet or response scaffold. Keep coordinator feedback out of reviewer delivery.

In generated `worker_guidance.examination_note`, replace overlapping prose with a shorter statement of the existing distinctions:

- Coverage describes examined material. An examined manuscript omission can finish with `outcome=gap` and whole-unit coverage. Unexamined assigned material, including a necessary unreadable passage, remains partial and names that material.
- A check/judgment uses `gap`; `proof_gap` is a primary finding category. Use the generated native scaffold and its field types rather than a reconstructed response shape.
- An assessed unavailable external source can finish inconclusive. Preserve actual conditions, adverse reasoning and limitations. Do not clear omissions to obtain acceptance.
- Preserve the role-specific placement of concerns and the qualification that **unrelated** discoveries do not expand the assignment. Relevant new dependencies may still require coordinator attention. No proof, mathematical repair or counterexample construction is required.

Keep the scaffold, packet, manifest, native enums and validation behavior unchanged. Do not add a second explanatory paragraph, blanket prose classifier or automatic conversion from partial to whole-unit. Source-fidelity-only preparation should not acquire composition instructions.

Retain the existing primary composition distinctions for important applications, meaningful local outcomes and missing suppliers, optional local checks/coverage, and omitted proof routes within the shortened note. Independent workers must not acquire primary-only finding fields or primary authoring duties; retain their assigned composition examination.

Acceptance evidence for A: public CLI reuse/no-packet/oversize outputs; distinct ready task selection and prerequisite handling; actual exported role guidance; valid and malformed native primary/independent returns retaining their original bytes and judgments; examined gap completion versus unread material remaining pending. Extend existing group tests for a fresh group containing a reused pending packet, empty and mixed oversized groups, saved-membership re-export and unchanged response provenance. Adapt the existing checks rather than duplicating them as a second suite of wording assertions.

## B. Add meaningful targets without restarting the audit

This is a conditional implementation workstream. Its prototype preserves accepted work but is not safe for unrestricted live addition. Validate the combined behavior before adding the public helper. If the narrow solution fails, deliver A and C and report B as unresolved; do not add a new runtime waiting rule or silently create a second audit.

### User-facing operation

Provide one coordinator operation for appending explicitly selected, already registered item targets to an existing Full coherent audit. A proposed CLI spelling is `stage1 add-targets DB --audit AUDIT --expected-version VERSION --target items:ID`, with repeatable targets. The final spelling should follow existing CLI conventions. Initially advertise item targets only; preserve any existing part targets and their semantics. Broader part-target convenience is outside this patch.

Keep the same audit ID and preserve mode, exclusions, protocol, independence requirements and all other scientific policy. Retain existing expected-version, transactional acceptance and replay conventions. Do not broaden arbitrary audit editing, automatically select every footnote/equation, reinterpret exclusions, or create scientific support.

The experiment uses an existing primary packet targeting the audit and ordinary `apply_batch`; an author packet does not authorize audit replacement. Reuse that legitimate seam without rewriting saved packet bytes or changing permission rules. Validate live targets in the same paper and conflicts using existing contracts, including inherited exclusions and excluded source anchors. Report an excluded addition as ineffective rather than silently removing an exclusion or claiming it creates work. Replays and already included targets should add no revision or duplicated work. Never hide a stale caller version by retrying against the newest audit.

Retain the prototype's bounded replay behavior: an identical addition request reuses its receipt while that resulting audit version is current; a later audit edit causes conflict. Adding already-present targets with the current expected version is a no-op. Do not promise successful historical replay after intervening edits or restore an older target list.

A meaningful owned claim can remain within its coherent owner examination when actually covered there, or be explicitly selected for its own question. Registration alone supplies no examination. For an explicitly selected owned claim with a separate registered argument, preparation should reach that exact question when selected by item or expose the exact usable argument selection. Check both focus filters in `work.build_work` and `work.select_assignment`; keep exact argument identity and necessary predecessors without broadening to its whole owner or unrelated siblings. Ambiguous multiple routes must retain existing explicit selection behavior.

The prototype's added claim has an argument; the saved Claude footnote/remark claims did not. Preserve the existing direct statement question when no route exists: assess its captured statement and setup and record a gap or uncertainty as appropriate. An argument or proof boundary is not mandatory merely to prepare that examination. If a supplied derivation warrants separate examination, register its actual bounded route on the existing claim through ordinary versioned edits, without creating a duplicate claim. Resolve item focus to an exact route only when it exists. Target addition must not invent a proof, dummy argument or completed examination, or reopen unrelated proofs.

### Unchanged outstanding questions

Primary seams to investigate together: audit updates in `authoring.py`, audit compatibility in `controller._freshness`, saved-packet reuse in `stage1._reuse_assignment`, and the audit-scope comparison in `packets.extend_work_assignment`. The last path supplies additional independent source context and has a separate scope guard. The experiment proves that updating only the audit helper is insufficient.

The candidate compatibility rule is deliberately narrow: an old local assignment may remain usable after **only appended explicit targets** when it is still an authorized required question in the same audit and its task identity, target, kind, role, action, exact consumed mathematical inputs and independent source/setup context have not changed. Require the old target list to remain an exact prefix and every other meaningful audit field to remain unchanged. Preserve existing report-path and primary-global qualification exceptions separately; do not broaden them through this new local exception.

An audit-wide/global question is not covered by this exception: adding scope can change what that question promises to examine. Changes to the assigned statement, proof, hypotheses, uses, source passages, relevant relations, protocol or review requirements still require affected work under existing freshness rules. Do not ignore audit targets universally, accept a response for the newly added claim from an old packet, or relax historical protocols.

Use one shared read-only audit compatibility decision for acceptance, reuse and the source-extension scope guard. A packet rejected because its actual context is stale must not be repeatedly returned as the usable replacement. Reuse must compare saved tasks with current selected tasks, while retaining binding, independent-context, latest-reconciliation and size checks. Submission must establish current authorization: comparing two copies of the saved task map is insufficient. Accepted prerequisites may change progress without changing the mathematical question, so do not compare administrative status as if it were scientific input.

Whole-packet reuse requires every assigned task to qualify. For a submitted local subset, retain all actual consumed inputs and the packet's independent context, even if that context is broader than the submitted subset. Keep existing auxiliary-evidence and write-version checks. Source extension retains its exact source-only guards: new evidence yields a new packet and a response to that context, never a rebadged old answer. If this combined behavior cannot be implemented narrowly, defer B as a unit.

Keep original packet IDs, manifests, payload hashes and returned bytes as provenance. A new acceptance context may use existing mechanisms, but must not fabricate a new independent examination or change the question silently. Preserve existing request-id behavior: an already saved conflict replays its original receipt; corrected/rebased intake follows the existing new-request convention using saved work when genuinely unchanged.

### Required bounded validation before B is exposed

These are implementation regression cases, not tasks added to paper audits:

1. Add a separately selected claim before dispatch and after old local work is complete. Preserve accepted records, bindings and response blobs as provenance, and preserve completion for genuinely unchanged local questions. Complete newly required work through primary, independent and integration intake. If an existing audit-wide question changes with the added scope, retain its old return and apply existing freshness rules only to that affected question; do not commission a new global sweep.
2. Add during outstanding primary, independent and integration assignments. For genuinely unchanged local questions, accept the actual saved returns once, without another scientific examination, duplicate findings or packet rewriting. Repeated preparation and submission must converge rather than cycle.
3. Replay an addition immediately and after an intervening addition; add an already included target. Expect immediate receipt reuse, conflict after intervening audit edits, and a no-op for an already included target only with the current expected version. Preserve receipts and the latest target set. Reject concurrent stale writes and invalid, wrong-paper or retired targets without partial mutation. Preserve exclusions, including excluded parents and source anchors.
4. Reject false reuse after target removal/reordering, exclusion/policy changes, changed source/setup/relations or a changed mathematical question. Cover saved-conflict replay, mixed local/global assignments and independent context extension after addition. Retain strict audit-wide/global behavior when expanded scope changes the question.
5. Select a newly included owned item by its documented route. Inspect public selection and packet task/argument identity, with owner siblings absent and ambiguous routes left explicit. Include both the separate-argument fixture and a faithful no-argument footnote/remark case, retaining the latter's direct statement question through primary, independent and integration intake. Existing part-target behavior must remain unchanged.
6. Run one public-command walkthrough from completed work through addition, unchanged outstanding returns, new work, integration, freezing and normal HTML production. Inspect completion and original judgment hashes, not merely command exits.

Do not bypass freshness checks or claim live-addition readiness from passing the completed-work-only case. A second audit is not the default workaround because some old audit-specific completion credit is lost.

## C. Put dispatch and source cues at the assignment point

Primary seams: `references/controller-workflow.md`, with short consistent links in `coordinator-protocol.md` or `graph-records.md` only where useful. Move or shorten the existing guidance rather than adding another policy file or expanding every role brief.

At reviewer preparation, make the coordinator's responsibility explicit: obtain a genuinely separate review context through available native delegation or a permitted fresh CLI session. Establish a usable route once and reuse it while its capability is unchanged. Missing a native tool alone does not establish unavailability. Preparation exports work; submission records returns. Neither launches reviewers.

Give reviewers the generated delivery files, relevant role references and matching original evidence; keep coordinator manifests and group indexes private. Preserve the existing advice for continuing an interrupted group rather than preparing overlapping work again.

For several ready proofs, a few disjoint groups may run concurrently where the host permits it. Sequential execution remains valid when required by the host or dependencies. Do not add a scheduler, mandatory parallelism, recurring capability probes or a host/model-specific launcher. If no usable route exists, preserve the actual review limitation and deliver available work honestly.

Use the existing source navigation and proof records to supply the exact statement, applicable setup and known proof segments from their actual files. Match differently numbered results by their statements and hypotheses. Include known supplied continuations in the affected assignment; ambiguous consequential PDF symbols call for the relevant original passage/image or a disclosed local limitation. Do not require rendering every page, merging PDFs, a second manuscript sweep or a new correspondence ledger.

During the ordinary Phase 1 reading, include meaningful footnote/remark claims by mathematical role, within an appropriate coherent examination or as explicit targets. Do not promote every graph child to its own examination. B supplies the later-addition path only after its compatibility cases pass; the existing honest partial-delivery route remains available for genuinely unfinished scope.

Acceptance evidence for C: retain split/combined excerpt and disjoint source-only group checks, with distinct hypotheses kept separate. Use one small fresh-agent forward exercise with actual generated scaffold/guidance for native response authoring and coordinator decisions. Submit the authored native return through public stage intake, inspecting acceptance, original response bytes and judgments, and the examined-gap versus unread-material completion distinction. Deliver only source-only worker files to the independent context. Score route choice separately from any actual fresh CLI launch. Do not treat a decision vignette or hard-coded dispatch matrix as proof of a working CLI route, PDF readability, parallel speedup or cross-model reliability.

## Implementation ownership, sequence and release

These are responsibilities, not a required worker count; separate workers and parallel execution are optional. The integrator owns shared `stage1.py`/`cli.py`/`review_groups.py` wiring and the final prose. An assistance worker can own A's `assistance.py` changes and focused tests. A scope worker can prototype B's authoring, shared compatibility and exact focus resolution in isolation, requesting shared-file changes from the integrator. A workflow reviewer owns C's concise edits and independently checks that A/B add no examination duties. Do not let multiple workers edit the same shared file concurrently.

Implement A and C first or in parallel. Validate B separately against the listed counterexamples before integration. These are development workstreams, not additional stages for skill users. Required checks belong to the implementation process; routine audits gain no verification checklist.

After implementation settles, run the relevant focused tests and one full `test_v3*.py` suite using existing shared Python and Node. For A/C-only changes, validate exact preservation of stored scientific semantics and delivered source-only packets. For B, validate intentional narrowly additive compatibility while retaining negative controls. Run a small public freeze/build smoke check; no whole-paper mathematical rerun is necessary to verify the mechanics of this patch.

Set skill/core metadata to 3.0.10 only when the implementation is ready, refresh and verify the runtime manifest, and record exactly whether B is included. Keep the canonical name `stat-proof-check`. Save validation evidence separately from the user-facing report. Installation, commits and remote publication are separate requested actions, not effects of writing this handoff.

## Plan validation and disposition

Three independent Sol 6.1 agents at xhigh reviewed this handoff against current source and the saved experiments. Their findings were incorporated. The workflow and interface reviewers also checked the revised wording. Evidence is preserved under `../tmp/rf-hte-v309-handoff-validation-20261008/`.

| Review | Evidence and disposition |
| --- | --- |
| [Workflow](../tmp/rf-hte-v309-handoff-validation-20261008/workflow/review.md) | Qualified completion preservation to unchanged local questions, fixed item-only scope, and clarified optional development staffing and private coordinator files. [Closing review](../tmp/rf-hte-v309-handoff-validation-20261008/workflow/final-check.md) found no new routine audit obligations. |
| [Interfaces](../tmp/rf-hte-v309-handoff-validation-20261008/interfaces/review.md) | A public-command probe confirmed hidden member reuse and lost group size diagnostics. A now includes that interface, preserves primary-only composition cues and explicit expected-version handling, and requires actual native intake in the later forward exercise. The [closing review](../tmp/rf-hte-v309-handoff-validation-20261008/interfaces/final-check.md) prompted a wording fix preserving independent composition examination while excluding primary authoring duties. |
| [Scope and saved work](../tmp/rf-hte-v309-handoff-validation-20261008/scope/review.md) | A fresh replay reproduced conflict followed by stale reuse for all three roles. B now covers one shared compatibility decision, current task authorization, both focus filters, exclusions and the separate source-extension guard. This is conditional feasibility, not a validated compatibility implementation. |
| [Scope follow-up](../tmp/rf-hte-v309-handoff-validation-20261008/scope/addendum.md) | Scratch probes established the actual replay contract and successful native primary intake for an owned claim without an argument. The plan preserves that direct statement route. Independent/integration intake for that shape remains an implementation regression case. |

At plan signoff, the handoff was ready for targeted implementation: A and C were independently deliverable, and B required its bounded combined validation before public exposure. No live-paper speedup, cross-model reliability or mathematical accuracy claim followed from that review. Production and installed 3.0.9 copies were unchanged during plan validation.

## Implementation outcome

Implemented A, B and C as candidate **3.0.10** on 2026-10-08. The combined 265-test suite completed without failures, with one existing Windows symlink privilege subcase skipped. The public addition/intake/freeze/HTML walkthrough and a fresh source-only native response exercise passed. See [candidate validation](../stat-proof-check-v3/VALIDATION.md#rf-hte-preparation-and-scope-patch-3010) and the [implementation report](../tmp/rf-hte-v310-implementation-20261008/REPORT.md). Installed copies remain 3.0.9; implementation did not install, commit or push.
