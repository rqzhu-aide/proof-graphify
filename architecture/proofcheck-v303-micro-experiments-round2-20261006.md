**Proof-check v3.0.3: refined micro-experiments, round 2, 2026-10-06**

The second round supports two small implementation candidates: an explicit correction-recovery command and accurate historical-replay feedback. Ordinary record creation and grouped source delivery also work in the tested cases, but reusable support for a shared intermediate result remains unresolved. Delivering its proof inside a grouped review is not sufficient to make its database node appear examined.

Three GPT-6.1 Sol agents at xhigh worked in parallel with ten-minute limits. All froze their experiments within the limit, from the parent assignment at 14:35:40 UTC to the last freeze at 14:45:13 UTC. The coordinator reviewed the candidate changes, challenged their comparisons, reran all three experiments, and performed a final integration check on copied stores. The 235-file production source manifest remained unchanged. Installations and original paper-test artifacts were not modified.

| Area | Refinement tested | Result | Decision |
|---|---|---|---|
| Correction recovery | Actual CLI option that synchronizes from the current item, with additive factual feedback | Passed recovery, replay, no-op, connected-consumer and local-failure cases | Ready for a small implementation review |
| Returned-work intake | Existing replay flag plus accurate historical-receipt wording | Passed primary and independent intake, local malformed-return repair, and old receipt replay | Ready for a small implementation review |
| Creation and grouped delivery | Existing owner proof-anchor selection, with the prior creation helper | Correct sources delivered and judgments accepted without additional proof duties | Delivery refinement supported; reusable child-result credit still needs work |

These are executed mechanical experiments on synthetic fixtures. They do not measure fresh-agent behavior or real-paper completion time. No combined production package was built or installed.

**Correction recovery now has a tested command interface**

The scratch CLI adds `--sync-current` to `stage1 correct-claim`. It is mutually exclusive with the existing explicit `--correction JSON` input. The recovery path reads the current item's saved statement and statement anchors and calls the existing correction implementation. It does not introduce another versioning or correction engine.

The fixture reproduces an item already corrected from minus to plus while its direct target specification still selects the old version. The new option changes only that specification. The corrected item, its version, caption, aliases and proof passages remain intact. Repetition reuses the saved result; an already aligned item produces a no-op. Both leave database bytes unchanged.

The connected control includes the corrected claim, a consuming proof, its application of the claim, and an unrelated result. The correction and synchronization preserve all saved scientific records. Affected examinations remain stale under the existing rules; the unrelated examination remains current. Sync does not restore invalid review credit or generate another examination.

Eight rejected CLI requests, including stale versions, mixed inputs, a missing item and an advanced exact specification, leave database bytes unchanged. All seven existing correction tests pass.

The coordinator identified two presentation concerns during review. Established response fields, including the original receipt, must remain available. The refined candidate preserves them and adds facts. Prefix-only excerpts can hide a correction late in a long statement, so the tested feedback shows a short excerpt near the first changed character. A sign change after a shared 16,000-character prefix is visible. The feedback remains factual on replay and is explicitly an excerpt, not a complete diff of all changes.

This supports the small input option and compatible feedback. It does not establish correctness of the current statement or support universal synchronization of advanced targets.

**Returned-work intake needs clearer feedback, not another status system**

The refined candidate keeps `replayed` and changes only invocation guidance. Four added lines identify an unchanged submission as a historical saved receipt. One guard adjustment prevents the old rejection guidance from overwriting that explanation when a rejected response is replayed.

Both lanes execute twelve real CLI calls. Each saves a partial adverse judgment, replays it, accepts a successor that finishes the local question, then replays the old partial return. The old receipt still lists one remaining task; current status lists zero. Both callers stop using the existing replay flag. The refinement adds no measured mechanical capability, but accurately explains the historical data and avoids telling a caller that an old remaining-task list is current work.

A second case reproduces one DSH error: a forbidden administrative `exposure` field inside a primary worker response. The original rejected return is preserved. Reusing the generated scaffold and copying its allowed fields repairs that one submission, with no guessed outcome or new examination. A separate accepted packet's saved checks and response remain unchanged. Replaying the old rejected return after repair is also correctly described as historical.

Both lanes additionally execute accepted Stage 2 independent intake and replay. Replays preserve original response bytes and leave the database hash unchanged. This probe does not cover independent partial continuation or integration intake.

The evidence favors the small wording change. It does not justify automatic schema repair, new persistent status, another compulsory audit check, or a claim that prose alone will prevent every agent from retrying.

**Grouped source delivery improves without additional runtime code**

This experiment starts from the first round's record-creation prototype. It uses real local drafts, actual consolidation output IDs and two consuming theorems sharing one derivation. Eight local proposals become five canonical items. Named setup records have no mathematical proof duties.

The refinement changes the owning examination's existing `proof_anchors` from its immediate proof passage to that passage plus the selected shared derivation proof. No package code is added beyond the previous creation prototype. The same source selection reaches both primary and independent assignments. A separate supplier's statement is delivered, while its proof and an unrelated captured paragraph remain excluded. The refinement does not recursively gather all supplier proofs.

The actual generated primary and independent response scaffolds accept the intended source references and save the judgments under the assigned owner and reviewer identities. Assignment task counts are unchanged, and no separate derivation review becomes compulsory. Synthetic gap and supported-outcome controls distinguish accepted intake from favorable support.

The supported control reveals the remaining issue: the owning composition and the application of the shared result within it receive local support, but the shared result itself remains open and visually unassessed. Its availability to another consumer remains conditional. An owned-item control without a separate child argument shows the same observation. That latter control lacks the helper's exact-target and source-observation setup, so it is not a fully matched source-fidelity comparison and does not isolate every cause.

The coordinator then copied both supported-control databases and performed ordinary integration of the saved owner reviews. Integration was accepted, the owner's independent-review status became complete, and no check or response was added. The shared intermediate result still remained open/unassessed in both stores. Thus the observed limitation is not merely an outstanding integration step.

The experiment also retains the earlier authoring-order issue: an owner and its owned prerequisite require one existing local connection edit. Neither this issue nor grouped child-result credit was repaired by introducing a larger graph system.

The supported next target is narrow: determine how the already recorded grouped examination should establish the particular shared result it actually examined, in its stated context. Delivery and identity consolidation alone do not finish that association. A separate compulsory proof examination for every intermediate node is not supported by these findings.

**Implementation judgment**

Proceed with reviewing the small correction-recovery interface and historical-replay feedback. Retain explicit grouped source selection and the useful record-creation convenience. Do not describe the broader creation path as fully smooth yet: shared-result assessment and the local authoring-order case remain open.

No extra audit stage, universal re-review, automatic source crawler or broad database redesign is indicated. The tests narrow the remaining work rather than adding a new checklist to every paper.

**Evidence and reproduction**

- [Correction CLI experiment](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/corrections/REPORT.md)
- [Returned-work intake experiment](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/returned-intake/REPORT.md)
- [Creation and grouped delivery experiment](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/record-creation/REPORT.md)
- [Coordinator reruns and source comparison](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/parent-validation.json)
- [Coordinator integration results](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/parent-integration-check/results.json)
- [Reproducible integration check](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-micro-experiments-r2-20261006/parent-integration-check/run.py)

All three coordinator reruns exited zero. Creation completed its four lanes in about six seconds including process startup; intake reported 15.975 seconds for both lanes; correction reported 12.461 seconds. These are fixture execution times, not paper-runtime estimates. The reports preserve prototype diffs, source selections, actual commands, receipts and limitations.
