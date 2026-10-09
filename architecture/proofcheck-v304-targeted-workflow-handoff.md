**Targeted workflow fixes for proof-check: implementation handoff**

Status: implemented and validated as 3.0.4 on 2026-10-06. Baseline: `stat-proof-check-v3`, version 3.0.3. The canonical skill name remains `stat-proof-check`. See [the implementation results](../stat-proof-check-v3/VALIDATION.md#targeted-workflow-patch-304) for the 158-test run, workflow trial, local delivery correction and remaining limits. The design and confidence distinctions below record the pre-implementation handoff; this file is not a new runtime checklist.

**Objective and boundaries**

Make ordinary graph creation, returned-work intake and local corrections easier to finish. The coordinator should be able to save the work actually performed, retain shared results for reuse, and repair a local record without commissioning another proof examination merely to satisfy bookkeeping.

Keep the three stages, one coordinator as database writer, source-based local drafts, independent proof groups, coordinator integration, and frozen-report rendering. Preserve actual scope, hypotheses, adverse judgments and limitations. A scientific gap can finish an examination; the agent need not construct a proof, find a counterexample or resolve every disagreement.

Implement inside this package's own `scripts/paper_core`, references and tests. Older proof-check, shared core and proof-graphify are outside scope. Use existing record kinds, groups, packets, receipts and freshness rules. No new database collection, audit stage, worker scheduler, mandatory coverage ledger, automatic source crawler or general repair engine is planned.

This is an engineering handoff. It must not become another document that every paper-auditing agent must read.

**Evidence and confidence**

| Workstream | Established by experiments | Still to establish during implementation |
|---|---|---|
| A. Correction recovery | A small sync-current wrapper and real CLI preserve current data, history, compatibility and affected-only freshness behavior in the tested graphs | Production integration and the combined regression suite |
| B. Returned-work intake | Historical replay wording works with existing fields; a representative malformed return is repairable locally without disturbing accepted work | Combined CLI regression; no general automatic repair is proposed |
| C. Ordinary creation and shared-result reuse | Accurate kinds, canonical reuse and explicit grouped source delivery work; owner examination can be accepted while its shared intermediate remains unassessed, even after integration | The narrow grouped-derivation representation described below must demonstrate correct local assessment and reusable availability |

The experiments are mechanical fixtures, not evidence of real-paper speed improvements. C is a concrete implementation hypothesis supported by code inspection, not an already tested fix. Do not conceal that distinction by copying all scratch code into production.

**A. Direct correction recovery**

Add `--sync-current` to the existing `stage1 correct-claim` command. Require exactly one of that option and the existing `--correction JSON`. Ordinary intentional changes continue to use explicit correction input.

Sync means: read this current item's saved statement and statement anchors, and align its ordinary direct exact specification with them. Pass the caller's expected version to the existing `authoring.correct_claim`; reuse its atomic edit, replay, conflict and advanced-target handling. Do not select what is mathematically correct, reconstruct a full old item body, or silently substitute current text for an intentional replacement.

Preserve the existing command result, including `item_id`, `receipt`, `reused` and `unchanged`. Add concise factual before/after feedback from saved versions. A target-only correction must show the unchanged item and the changed target selection. Replay describes the original saved change, not a second mutation. Show a bounded excerpt near the first text difference, with its offset/truncation information; identify it as an excerpt. The scratch `receipt_kind` field is redundant and is not part of the required change.

Preserve current aliases, captions, proof passages and other unrequested fields. Preserve all checks, responses, reviewers and findings. Materially affected work must remain affected under the existing freshness rules; syncing bookkeeping does not revive its support. Unrelated work remains current. Keep ordinary local failure guidance for distinct or multiple advanced specifications instead of inventing a universal synchronization operation.

Primary code targets: `authoring.py` and `cli.py`. A small presentation helper is optional code organization, not a new subsystem. Update the existing correction paragraph in `references/graph-records.md` and its command example in `references/controller-workflow.md`; avoid duplicating the rules across role guides.

**B. Returned-work intake and bounded recovery**

Use the existing `replayed` field. In `cmd_stage_submit`, an unchanged replay should explain that it returns a historical saved receipt, performs no new work, and may contain an old remaining-task list. Preserve stored receipt fields and immutable response bytes. Apply the tested `and not replayed` guard so ordinary rejection guidance cannot overwrite the replay explanation.

When deciding what remains after such a replay, the coordinator uses the existing current queue/status. Do not make a new status call mandatory after every successful submission, automatically resubmit, or add a second completion state. An accepted partial judgment remains partial. A successor examination uses the existing continuation/supersession route and preserves the earlier judgment.

Keep mechanical return repair direct: read the exact diagnostic, reuse the generated scaffold, and repair only the affected response. Preserve its original rejected bytes. Keep administrative exposure information in the established CLI/submission fields. Do not guess scientific values, delete adverse concerns, change a finding's target to make a packet accept it, or retry a whole batch because one packet failed. The stage command continues to derive the request ID from the actual corrected input.

This workstream does not add a generic normalizer. The demonstrated malformed-field case is a usability example, not authority to discard arbitrary unknown scientific rows. Existing preservation and integration of such rows remain in force.

Primary code target: the shared stage-submission handler in `cli.py`. Refine the existing recovery paragraph and one generated-response example in `references/controller-workflow.md`. Keep generated role instructions consistent only where they currently contradict the revised feedback.

**C. Ordinary records and grouped shared results**

Use the following distinction throughout authoring and intake:

| Source content | Intended representation and responsibility |
|---|---|
| Named assumption or definition | Reusable source/setup item. No mathematical proof duty is created by registration. |
| Intermediate equation, claim or derivation examined inside an owning proof | Shared owned item, plus the actual local derivation association when that derivation is represented. Its examination can remain inside the existing proof group. |
| Meaningful subsection deliberately assigned its own examination | Ordinary proof-unit records with its actual kind, source and existing owner requirements. Separate assignment is an explicit scope choice. |
| Use of a result in another proof | A distinct consuming application. It does not re-establish the supplier or inherit another consumer's application verdict. |

Extend ordinary creation to these existing kinds without requiring callers to assemble storage pairs or relabel assumptions as lemmas. Prefer a thin `stage1 add-record --input ...` dispatcher around current authoring functions, while retaining `stage1 add-unit` and its existing proof callers. The ordinary record input uses existing source and identity fields. Setup records need no invented proof-completeness answers. Existing intermediate kinds retain their owner requirement. External-resource verification stays on its current path.

For a grouped intermediate, creating an item alone must not imply a separate proof assignment or a favorable verdict. Do not automatically create a standalone child argument merely because proof passages are available. A deliberately separate subsection can use the proof-unit path. Update draft consolidation to emit ready authoring inputs for the chosen path, using actual canonical IDs and preserving original authors, examinations and source selections. Readable worker drafts remain acceptable; no new mandatory worker schema is introduced.

**C1. Establish the missing association using existing inference groups**

The preferred implementation candidate is to represent the selected derivation of intermediate result R as an existing inference group inside the owning argument A:

- The group's conclusion is R, its argument is A, and its premises, scope and evidence describe R's actual derivation.
- A's final group still concludes A. A may consume R, and another argument B may also consume that same canonical R through a separate use.
- The coordinator creates this association from the actual returned grouped work and selected sources. An `owner_id`, a shared page, or a consuming application alone is insufficient evidence that R's derivation was examined.

This is an internal graph association, not a new worker certificate or per-node review task. The normal whole-unit return should cover the selected grouped reasoning; separate local outcomes remain optional when they matter.

The code already offers a plausible route: `coherent.py` finds arguments through groups concluding a target, records examined group conclusions as historical members, and checks unchanged facets and located evidence. `support_semantics.py` already establishes an internal result from its own concluding group. This avoids making R depend on the final truth of A, which would create the cycle R supports A, A supports R.

Do not implement a blanket owner fallback in `arguments_for`, copy A's availability to all owned nodes, or convert an application verdict into a derivation verdict. First test the existing group route before changing the support reducer or resolver.

The bound source for the selected grouped work must include R's statement, relevant setup and actual derivation, not only its final application in A. Existing explicit `proof_anchors` and source selections already deliver chosen passages. `grounded` currently requires all relevant item passage anchors in its saved source set, so adding a concluding group alone may not suffice. If necessary, narrowly align binding assembly with the explicitly selected group's statement and proof evidence. Do not recursively absorb supplier proofs, infer examination from every delivered page, or loosen grounding globally. The helper should manage these records and pins; the paper auditor should not acquire another anchor-reconciliation checklist.

Retain current exact-target/source fidelity, context admissibility, freshness and adverse-opinion behavior. A result established under a private condition remains limited to that condition. A partial, inconclusive or adverse return must not silently become positive child support. Integration selects among saved work and retains disagreement; it creates no new examination. Where a group's actual returned reasoning separately establishes R despite a later failure in A, preserve that local outcome through the existing explicit local-result route rather than synthesizing it from A's overall label.

Code inspection targets: `authoring.py`, `drafts.py`, `coherent.py`, `bindings.py`, `assessment.py` and `support_semantics.py`. The latter four are investigation targets, not a requirement to edit every file. Prefer an authoring/binding correction that lets existing assessment work.

**C2. Keep ordinary ordering and handoffs direct**

For the owner/owned-prerequisite authoring cycle, use the already demonstrated sequence inside coordinator intake: register the owner, register its owned result and local derivation, then attach the consuming connection through existing edits. Finish these known associations before preparing the affected examination packet. The creation helper or consolidation output should expose this sequence so the coordinator need not invent it from validation errors. No graph-wide fixed-point builder or perfect-database gate is needed.

Workers continue to draft independently. The coordinator merges the same source claim in the same context once, preserves each consuming use, and maps the saved primary work to the resulting questions. An unchanged grouped examination does not require a new mathematical pass because IDs were consolidated. Materially new questions receive only affected continuation or remain explicit limitations.

This revision targets normal fresh runs and bounded current corrections. Do not mass-rewrite old audit stores or retroactively pin old opinions to newly represented scientific work. Late graph additions use the established affected-work rules; unrelated accepted work survives.

Update `references/phase1-drafts.md`, the ordinary creation examples in `references/graph-records.md`, and the relevant controller paragraph. Keep one explanation of grouping and ownership. Add only a short cross-reference to `SKILL.md` if necessary; do not lengthen every checker prompt.

**Implementation order and ownership**

A and B can be implemented independently. One contributor should own C's authoring and grouped-assessment association together, because splitting them risks a helper that saves records without producing the intended review state. The integrator owns shared CLI/reference edits and final validation. These engineering workstreams do not prescribe the agents, models or harness used when auditing a paper.

Start C with the round-two fixture and the proposed concluding group. Demonstrate local R assessment, reusable support in the right context, and unchanged examination counts before broadening the helper. That mechanism remains unproven. If it fails, record the exact remaining mismatch and revise this local design; do not conceal it with a favorable display label or introduce compulsory child reviews. A and B remain independently useful.

**Small sufficient acceptance set**

These are development tests, not additional obligations for paper-auditing agents.

| Case | Required observable result |
|---|---|
| Generic item text/anchor correction followed by sync | Item stays corrected; only stale paired data changes; unrelated fields and judgments remain intact. |
| Sync replay, aligned no-op and local input errors | No new revision or partial mutation; original CLI fields remain compatible. Include the long-prefix sign example. |
| Connected correction | Affected claim/application/consumer remain appropriately stale; unrelated control remains current; no blanket renewal. |
| Partial submission, successor, then old replay | Historical receipt is identified; current completion is not undone; no extra checks, responses or dispatch. |
| One malformed return beside an accepted one | Only that response is repaired; original bytes and the accepted packet remain intact. Replay the original rejected input after repair: historical guidance must survive the rejection branch, current work stays completed, and database bytes/rows remain unchanged. Include accepted Stage 2 replay through the shared handler. |
| Shared setup and ordinary intermediate creation | Correct kinds, one canonical shared result, distinct uses, and no assumption proof duties. Cover the supported intermediate-kind input shapes without inventing new types. |
| Grouped R established within A, then used by B | After actual primary, independent and integration intake, R's assessment and availability reflect its examined derivation in context; B's application still needs its ordinary examination. No extra child assignment is created. |
| Ownership or application without selected derivation | No invented R proof credit. Unrelated source passages and supplier proofs remain excluded. |
| Changed source/claim/premise, private condition or adverse return | No inappropriate inherited support or erased disagreement. Include a current adverse independent judgment on R or its separate derivation, as well as on A: grouped credit must not silently override or hide it, while preserving route-specific distinctions. A mere integration operation does not create proof credit. |

Reuse the two rounds' fixtures, the parent integration check and relevant existing v3 tests. Add a matched child-record control where needed; the round-two item-only control had different source-fidelity metadata and is not sufficient by itself. Assert actual assessment/availability and task behavior, not only packet contents or generated wording.

After focused cases pass, run the package's normal v3 suite once, refresh and verify its runtime manifest, and perform one compact documented workflow smoke test through frozen summary and HTML. Use existing shared Python/Node installations; create no project-local runtime environment. Judge that smoke test on preserved findings and intended completion, not whether every result is green. Repeat or expand checks only for a new failure or material change. A long KEDRL rerun is a later evaluation, not a prerequisite for every local edit.

**Completion and release**

The handoff is satisfied when A and B behave as tested, ordinary records need no type mislabeling or custom storage pairing, and the selected grouped shared result has honest reusable assessment without an extra review round. Preserve source-only independent delivery and the existing three-stage responsibilities.

Prepare the patch as 3.0.4 only after the implemented scope passes validation; keep the canonical name `stat-proof-check`. Update the package's implementation/validation notes and content manifest with actual results. Do not include scratch runners, comparison labels or experiment-only fixture code in installed runtime files. Installation, Git commits and remote publication are separate execution requests, not actions performed by this planning task.

**Evidence for the implementer**

- [Live-run database and workflow audit](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/architecture/proofcheck-v303-kedrl-workflow-audit-20261006.md)
- [Round-one experiments](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/architecture/proofcheck-v303-micro-experiments-20261006.md)
- [Round-two experiments and coordinator validation](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/architecture/proofcheck-v303-micro-experiments-round2-20261006.md)
- [Correction candidate diff](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/corrections/candidate.diff)
- [Intake candidate diff](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/returned-intake/candidate-diff.patch)
- [Grouped-source fixture and unresolved case](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/record-creation/REPORT.md)
- [Post-integration reproduction](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/parent-integration-check/run.py)
