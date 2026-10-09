**Proof-check v3.0.3: targeted micro-experiments, 2026-10-06**

Three GPT-6.1 Sol agents at xhigh ran independent, parallel investigations of record creation, returned-work intake, and correction recovery. Each investigation lasted approximately seven to eight minutes. The coordinator monitored their scope, challenged the intake comparison with an existing-field control and historical replay, checked the creation experiment's coverage claims, and reran all three completed runners successfully.

These are executed software experiments on small synthetic source fixtures. They do not establish that a fresh agent will finish a real paper faster. They give bounded evidence for choosing the next small changes. All prototypes are isolated under `tmp/v303-micro-experiments-20261006`; the 235-file source manifest is unchanged. No installed skill or original paper-test artifact was changed.

| Experiment | Useful result | Decision |
|---|---|---|
| Ordinary record creation | A small helper can create accurate assumption, definition and derivation records without compulsory proof work for setup | Promising, modify before adoption |
| Returned-work intake | Existing replay information already permits a caller to stop; replayed unfinished-task lists can describe historical work | Drop the extra status field, improve replay guidance |
| Correction handling | Synchronizing the exact target from the already corrected current item avoids resupplying stale statement text | Strongest small recovery candidate |

**Ordinary record creation**

The fixture has two consuming theorems sharing an assumption, a definition and an owned derivation. The baseline rejects all three kinds through its ordinary proof-unit helper. Correct records can still be created through manual lower-level edits.

The candidate uses the existing schema and authoring implementation. It adds a lightweight setup path for assumptions and definitions, and extends proof-unit authoring to an explicitly chosen derivation. The scratch delta is 42 added and 6 removed lines in one file. It is an API prototype, not a completed production CLI interface.

Both lanes consolidate eight local proposals into five canonical items and preserve two distinct consuming uses. The candidate keeps all five kinds accurate and creates zero proof duties for setup. Source-match observations are supplied explicitly by the caller; the helper does not infer source correctness. All 16 relevant existing authoring/draft tests pass.

The experiment also exposed the boundary of that improvement. Default Full selection still creates two primary and two independent proof examinations. Creating an owned derivation argument does not automatically create a separate required examination. Explicitly selecting it produces three of each, with the candidate's derivation question ready instead of waiting for manual establishment.

An owner-only independent packet includes the derivation statement but omits its separate proof passage. Therefore the helper alone does not demonstrate coverage of that derivation within the owner's review. Grouped examination remains valid when its actual proof source is included; a separate examination should remain optional. An ownership/dependency ordering cycle also requires one existing local graph edit in this fixture.

Adoption should preserve the useful authoring convenience and handle the intended grouped source delivery. It should not automatically turn every intermediate equation into another review task or introduce a general graph-ordering system.

**Returned-work intake**

The fixture saves an actual generated response scaffold containing a gap judgment with a partial examination and an explicit unexamined portion. Both baseline and candidate accept the response while leaving one task pending. Unchanged replay adds no checks, responses or submission rows and leaves the database file hash identical.

The first candidate adds an `intake_status` field and a replay stop message. A bounded naive loop makes three unchanged attempts in the baseline and stops after one using the candidate marker. However, the coordinator requested a fairer control: the baseline's existing `replayed` field also stops the loop after one attempt. The new status field is therefore unnecessary for the demonstrated mechanical behavior. No fresh-agent behavioral benefit has been established.

A corrected continuation is accepted, preserves the original judgment, and finishes the local question while retaining the adverse gap outcome. The runner also exposes a usability detail: a completed partial examination is continued through a successor judgment using `supersedes`, rather than the draft-only `replaces` path.

The coordinator's historical-replay challenge found a more useful issue. After continuation has completed the question, resubmitting the old partial response still returns its historical list of one unfinished task. Current status has zero remaining tasks for that question. This is consistent with immutable receipts, but misleading if the returned list is treated as current work.

The smaller recommendation is to retain the existing replay field and identify an unchanged replay as a historical receipt: it saves no new work, and its old remaining-task list is not authoritative current status. A caller deciding what remains can use the existing current queue/status. No new state storage or automatic repair is needed. This revised wording was recommended after the challenge; it was not a third executed candidate.

This experiment does not test DSH's malformed envelope fields or stage2 intake. That part of returned-work friction remains open for a separate small experiment.

**Correction handling**

The existing `correct-claim` helper already copies current records, synchronizes their direct exact target, preserves unrelated fields and retains history. The experiment reproduced why it did not prevent GLM's recovery error: a generic edit corrects item version 2, then a caller passes old statement text to the helper. The helper faithfully saves that old text as version 3.

A factual before/after receipt exposes this reversal. It cannot prevent an intentionally or accidentally wrong requested statement.

The useful small addition is an explicit recovery option meaning: synchronize the linked exact target to the current item's saved statement and statement anchors. Its caller supplies item identity and expected version, without rebuilding the text from an old template. It reuses the existing correction helper and version checks.

In the fixture, this changes only the stale target specification, keeps the corrected item at version 2, preserves its caption, aliases and proof passages, and aligns current statement anchors. Repeating the operation makes no new revision. A genuinely changed claim still makes the affected check historical; a disconnected unrelated check stays current. No favorable verdict or new scientific examination is created. All seven existing correction tests pass.

The option should be explicit. It must not silently substitute current text for a caller's intended new transcription. Its prototype assumes a valid live item and direct specification; production input handling would use the existing command's error path. The experiment does not establish correctness of the selected text or freshness behavior for every connected consumer.

**Priorities supported by this round**

1. Add the small sync-current recovery entry point and factual correction feedback around the existing helper.
2. Make replay feedback accurately describe historical receipts, using existing fields.
3. Refine ordinary record creation together with delivery of the intended grouped proof source. Keep setup free of mathematical proof duties and leave examination grouping to the coordinator.

No production change was adopted in this research round. The evidence does not support additional audit stages, automatic re-review, a new status machine, or broader database redesign.

**Evidence and reproduction**

- [Record creation report and commands](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-20261006/record-creation/REPORT.md)
- [Returned-work intake report and commands](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-20261006/returned-intake/REPORT.md)
- [Correction report and commands](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-20261006/corrections/REPORT.md)
- [Coordinator reruns and unchanged-source comparison](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-20261006/parent-validation.json)

The coordinator's complete reruns exited zero. Record creation took approximately three seconds including subprocess startup, intake reported 9.803 seconds, and correction reported approximately 5.537 seconds. Those are fixture execution times, separate from the seven-to-eight-minute investigations and not estimates of real-paper speed improvements.
