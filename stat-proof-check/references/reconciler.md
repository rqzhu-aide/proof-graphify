# Integrate a proof examination

The coordinator owns integration. Use Stage 2 integration preparation and its generated response. Read the saved primary and independent reasoning with the exact source question.

Resolve each disputed or newly added concern from its decisive inference under the exact assigned question's applicable hypotheses and regime; use the saved evidence to explain acceptance, rejection or uncertainty before selecting the whole-unit judgment. Adopting a reviewer's finding from the saved reasoning is integration, not a new examination. Agreement is not required. A concern first noticed here may remain a finding or uncertainty; reflect its consequence in the affected conclusions without automatically reopening the related proofs.

For the saved whole-unit opinions, use adopt_independent to adopt the independent conclusion, adopt_primary to adopt the primary conclusion, agree for compatible opinions, or unresolved when the disagreement remains. Leave successor_checks empty or omitted with either adopt choice; scripts attach the selected saved checks. Existing primary_revised and independent_revised inputs remain supported for compatibility and advanced explicit selection. This choice does not dismiss a distinct local concern.

When the adopted reasoning resolves or changes an identified finding, update that finding's lifecycle/resolution or category accordingly. A supported integration or a sentence in its rationale does not update an open finding automatically. Keep unrelated concerns and earlier reviewer records intact; uncertainty can remain open. This is disposition of the saved reasoning, not a new examination or a sweep of all findings.

For that local update, obtain a current `get audit.db --target items:OWNER_ID --mode reconcile --out finding-context.json` packet, using the owning result from the graph (or `parts:PART_ID` for a result part). This command accepts result targets, not argument, group or use IDs; do not infer an owner by changing an ID prefix. Use `template ... --collection findings --id FINDING_ID --packet PACKET_ID --out finding-edit.json` for the current body, edit only the intended fields, and submit its `template` member with `review reconcile audit.db --batch BATCH.json`. Use lifecycle `resolved` with a resolution when the concern is settled, or retain an open `presentation` concern when only wording remains.

Correct material database errors. If a correction changes the claim, conditions or evidence, do not transfer an old favorable judgment to it. Obtain examination of the affected question before claiming support for the corrected version, or record that it needs verification. Administrative mapping and equivalent explanatory detail do not require another examination.

Keep distinct local outcomes and all relevant adverse concerns. Valid separable returned work remains useful when another row needs local repair. When the scaffold lists response_dispositions, explain how the preserved extra rows are handled without rewriting the reviewer response. Potentially material content remains a limitation until incorporated or explicitly resolved in the integration reasoning.

Scripts select current references. Original response bytes and previous judgments remain historical evidence. Do not manually enumerate all superseded checks or create clean-agreement rows for every optional detail.

To correct a completed comparison without changing its scientific inputs, use `stage2 prepare --mode integration --correct --task TASK_ID`, then submit its generated response normally. See [controller-workflow.md](controller-workflow.md) for partial selection and recovery. Only requested comparisons are revised.

An unresolved scientific conclusion, assessed proof omission or unavailable external source can be fully examined and integrated. Record usable partial returns with their omissions, but submit only integration tasks actually exported as ready. The unresolved decision does not waive missing required examination or unread supplied material.
