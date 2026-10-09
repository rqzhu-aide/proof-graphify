# Targeted handoff: finish the v3 proof audit without avoidable rework

Status: implemented in the v3 source package as 3.0.1. See [validation results](../stat-proof-check-v3/VALIDATION.md). Installation and publication remain separate operations. The specification and original evidence below are retained for traceability.

## Objective and boundary

Make the existing workflow reliably reach a useful delivery: build the source-backed graph, examine the selected proofs and their important connections, integrate the reviews, and present the findings. An uncertain or adverse mathematical judgment can finish an examination. Producing a missing proof, repairing the paper or obtaining a favorable verdict is not required.

Keep the three stages, existing scientific standards and database format. Fix the commands and instructions that currently turn saved work, unavailable evidence or administrative changes into unnecessary repetition. Do not add a fourth stage, another reviewer, a repair agent, a task registry, a coverage ledger or a new certification checklist.

Implementation target: `stat-proof-check-v3/` in this repository. It is the development directory for the canonical skill **`stat-proof-check`**, currently version **3.0.0**. Its runtime is maintained inside `scripts/paper_core/`. Do not run the shared repository bundle builder over it or change the older proof-check or Graphify packages. This handoff supplements the baseline rebuild plan only in the areas below.

This is model-independent. A separate reviewer means a genuinely separate review context with truthful exposure, not a particular model or provider.

## Evidence driving the patch

The test is `stat-proof-check@v3.0.0+distributional-rl-main__20261004-175252`, under `C:/Users/zrq/projects/skills/_testing-center/results/`. All five saved results identify runtime `557181dbb6e4cdb1587716977e78ece3e6c4ddf0c963388e0722d3e25c77e3bb`.

| Observed problem | Revision needed |
| --- | --- |
| GLM saved 23 identical compromised reviews for one assignment. Receipts said accepted and instructed it to prepare again; preparation returned the same assignment. | Distinguish storage success from fulfilled work, and route the known review limitation to the coordinator. |
| GLM retried one malformed response 778 times with fresh request IDs. | Make the existing simple, idempotent stage submission path the normal interface; report the offending row clearly. Do not build another retry system. |
| After Codex corrected a graph connection and obtained new examinations, integration still required historical checks. Its next integration also reused a packet missing the reconciliation it would supersede. | Use current eligible opinions consistently and refresh inadequate integration context without repeating examination. |
| Runs disagreed about whether an accessible supplement belonged to the paper. DS4 later marked already retrieved and examined evidence as missing merely because it was not originally attached. | Clarify source scope and separate evidence availability from provenance. |
| K3 followed the helper's instruction to set `proof_complete: true` while its note still said the supplement was unavailable. | Let the existing helper represent unavailable proof material without misclassifying it as an omitted proof. |
| K3's final explanation attributed every blocker to independent review, although primary and source work also remained. | Report the existing frozen status rather than infer completion from accepted records or earlier counts. |

The malformed-response loop was an agent-authored automation defect as well as an interface weakness. This patch should make the ordinary path clearer and less repetitive; it cannot guarantee that arbitrary caller-written loops will obey feedback.

Read-only audit evidence: [run outcomes](../tmp/v3-distributional-audit-20261005/run-summary.json), [PI diagnosis](../tmp/v3-distributional-audit-20261005/pi/pi-findings.md), [Codex revision 64 assessment](../tmp/v3-distributional-audit-20261005/codex/revision64.json), and [Claude/K3 evidence](../tmp/v3-distributional-audit-20261005/claude-k3/). These local files supplement the original test artifacts; do not modify those artifacts.

## 1. Make the next action reflect actual progress

**Responsibility:** scripts explain what was recorded and what remains; the coordinator chooses an available reviewer or a limited delivery. Examiners do not repair administrative envelopes.

Changes belong in `scripts/paper_core/controller.py`, `work.py`, `stage1.py` and, where necessary, `cli.py`. Keep changes under the v3 protocol where legacy behavior differs.

- Keep `accepted` as truthful storage acceptance. When submitted work does not fulfill its obligation, use the existing diagnostics and `next_actions` to explain why and name the relevant remaining task. A compromised review should say that the response was saved but independent review is still missing. Partial examination and unresolved source comparison should identify their own remaining work, rather than imply another generic review will fix them.
- For an unmet independent obligation with an already returned current compromised review, ordinary preparation should defer automatic reassignment and return a coordinator action: arrange a fresh independent context, then explicitly prepare that task using the existing `--task` option. Continue offering other useful assignments. If none remain, return the limitation instead of recycling the same packet as fresh work.
- This is a derived selection decision, not a permanent block on the obligation. A genuinely new independent response may satisfy it. A prior compromised response must not obstruct a later usable review, nor be silently relabeled as independent. Keep ordinary unfinished drafts resumable.
- Preserve the distinction between caller-selected tasks and the internally generated eligible-task list. `prepare_stage` currently expands an unspecified selection before calling the selector; that internal expansion must not accidentally count as an explicit retry override.
- Check the actually available delegation routes when arranging independent review. If an available route works, use it. If no usable route is available, finish the remaining useful work and disclose the missing review. This is a practical capability check, not a new calibration exercise or an exhaustive search for tools.

**Normal response submission:** generated preparation guidance should lead with `stage1 examine`, `stage2 review` and `stage2 integrate` using packet, reviewer, response and actual exposure. The CLI already derives stable request IDs from these inputs. Keep manual envelopes available for existing recovery uses, but stop presenting their construction as the ordinary first step.

Fill the generated response scaffold by its row type. A source comparison records a match or source problem; an examination records mathematical reasoning and an outcome. Do not populate both with the same generic check object. Do not require optional coverage rows, successor pins or other advanced bookkeeping for an ordinary response. Keep existing compatibility fields; no response-schema redesign is needed.

On rejection, show the offending row/field and a local correction. Replaying unchanged input through the normal CLI must retain its existing idempotent behavior: no new examination or stored attempt. Make a replay distinguishable from a new commit in command feedback without changing the saved historical receipt. Changed response bytes already produce a new CLI request ID. Do not add content-deduplication tables, automatic retries, permissive field dropping or a universal batch driver.

Replace contradictory generated guidance and the corresponding short paragraph in `references/controller-workflow.md`; do not append another long list of retry warnings. The existing stopping policy remains: inspect the error, make a targeted correction, and if that operation still cannot proceed, preserve the valid work and deliver the limitation. A recoverable interrupted intake remains resumable through its existing recovery path.

## 2. Let integration finish against the current examinations

**Responsibility:** the coordinator compares saved reasoning and chooses a conclusion, including unresolved disagreement. Scripts select the correct pins and supply the context needed to save that decision.

Changes belong in `assessment.py::_coherent_integration`, the matching selection in `assistance.py::coordinator_guidance`, and `stage1.py::_reuse_assignment`. Coordinate any related `controller.py::_reconcile_plan` change with the same runtime owner.

1. Compute the required primary and independent comparison pins from complete, current, nonsuperseded, otherwise eligible examinations. Use consistent eligibility for the generated integration candidate and the completion calculation. Preserve historical `check_refs` for history; do not use every historical reference as a current comparison requirement.
2. Keep current local group/use opinions and retained substantive concerns in the integration. Narrowing historical pin requirements must not discard a current adverse finding or let an obsolete opinion establish the corrected claim.
3. Before reusing a reconciliation packet, check whether it includes the latest same-audit, same-target reconciliation that submission would supersede. If that context is absent or outdated, prepare a fresh administrative packet. Existing packet construction already includes reconciliation context. Do not invalidate the scientific examinations merely because another reconciliation was saved.
4. Preserve reuse when context is unchanged. Preserve genuine source, claim and condition conflict checks. Do not silently authorize superseding records the coordinator did not receive.

The acceptance result should be simple: after a material graph correction, only the affected question is re-examined; its current primary and independent responses can then be integrated through the ordinary scaffold, without manual historical pins or lower-level reconciliation commands. Adopting an existing judgment still requires no new examination.

## 3. Settle source limits without creating extra work

**Responsibility:** the coordinator chooses the relevant sources and records genuine limitations during ordinary preparation. Source discovery is not a new stage gate.

Make the source guidance changes in `references/database-audit.md` and `graph-records.md`, with a short consistent clarification in `evidence-and-verdicts.md` or `external-result-verification.md` where the distinction is already discussed.

- A named main PDF identifies the target paper. When it refers to a supplement and an identified companion file is supplied in an allowed input location, inspect the relevant continuation before declaring the proof omitted or unavailable. Honor explicit source restrictions. Avoid broad filesystem searches and importing unrelated accessible material.
- Full scope still accounts for the related supplied manuscript and supplements. Retrieving a needed proof continuation does not by itself commission an audit of every additional result in a retrieved document. Keep the source/scope decision in existing notes and scope records; no separate inventory artifact is required.
- Captured, inspected evidence that has been matched to the target paper is available evidence even if retrieved rather than originally attached. Preserve its provenance. Do not create an open missing-source issue solely for that difference. Resolve an existing issue when its actual cause has been removed, using its current lifecycle and a short explanation; do not retrieve the same source again merely to clear bookkeeping.
- A proof the manuscript actually omits may finish as an assessed omission. A referenced continuation that has not been accessed remains unavailable evidence. Reading only a statement does not count as examining an accessible supplied proof. Nontrivial external uses retain the existing bounded source/applicability check; routine facts need no new node, and outside papers do not receive recursive audits.

**Small authoring correction:** `stage1 add-unit` currently rejects empty `proof_anchors` with `proof_complete: false` while its diagnostic suggests setting the flag true. In `authoring.py`, let that input save the existing statement-only records and an open `missing_source` issue, without creating an argument or dummy proof anchor. Anchor the issue to the known statement so unrelated proofs can proceed. Permit this existing record type in the `unit` command's create allowance in `validation.py`; do not relax other command permissions. Keep the confirmed-manuscript-omission case distinct. A wholly unavailable promised proof must remain working, not obtain completion credit as an assessed omission. Use existing source-issue lifecycle and affected-record edits when evidence later becomes available. No new database collection, proof state vocabulary or general authoring framework is needed.

In `references/reporting-and-release.md`, make delivery consume the frozen summary and finalization receipt for the completion label, required-work counts and remaining limitations. Do not add a separate final audit to verify these counts. An accepted check, a provisional integration or process exit 0 is not a completed audit.

## The intended run, after these changes

| Stage | Work and responsibility | Natural stopping point |
| --- | --- | --- |
| 1. Prepare and examine | Coordinator settles relevant sources and graph units. Primary examiner judges the written reasoning and important connections. Scripts save records. | Each reachable assigned unit has a reasoned examination; unavailable material is identified. No proof reconstruction is required. |
| 2. Review and integrate | Separate reviewers examine the assigned sources. Coordinator integrates saved judgments and corrects material representation errors. Scripts handle pins and status. | Promised examinations and integration are done, or a specific remaining limitation prevents useful progress. Freeze the actual result, as release or working. |
| 3. Present | Renderer uses the frozen result. Coordinator checks that the presentation shows its findings and limits. | Deliver database, frozen summary and HTML, or disclose a presentation failure alongside the valid scientific artifacts. |

These are workflow boundaries, not perfect readiness barriers. A ready unit can advance while an unrelated source is unavailable. Stage 2 does not launch another global audit, and Stage 3 does not reopen scientific work to improve appearance. Working delivery is the fallback for genuinely unfinished work, not a shortcut around an available reviewer or readable supplied proof.

Do not mandate smaller assignments across the board. Keep a written proof or meaningful subsection as the normal examination. Split only when the material genuinely does not fit the available context or has distinct scientific questions. Splitting every connection would multiply exactly the coordination work this patch aims to remove.

## Implementation and bounded validation

Use one runtime owner for sections 1 and 2 because they share `controller.py`, `work.py` and `stage1.py`. A second owner can handle the source helper, its `unit` create allowance in `validation.py`, and its tests. One integration lead owns instruction edits, shared test support and package identity. Independent implementation is possible across those boundaries; do not have multiple workers patch shared runtime files concurrently.

Implement the integration defects first, then progress feedback/routing, then source authoring and guidance. Keep the prior v3 changes for adopted judgments, current local concerns and focused prerequisite scope. Do not port additional v2.3.9 machinery into this revision.

Use the existing synthetic fixtures for these regression scenarios. They test the program's behavior; they do not assign extra validation work to agents running the skill.

| Scenario | Required result |
| --- | --- |
| Correct a previously integrated supplier/claim, then save new examinations | Old opinions remain in history. They cannot supply current support or block one ordinary integration of the new opinions. |
| Save an integration with a genuine retained-response disposition still outstanding, then prepare again | Preparation supplies current reconciliation context; finishing the disposition causes no `WRITE_SCOPE` error or new examination. Unchanged preparation still reuses. |
| Integrate current whole-unit opinions alongside a current local gap | Integration can finish, while the local concern and its effect on support remain visible. |
| Submit a compromised review and use ordinary preparation again | Response is retained with an explicit explanation; the same review is not automatically recycled. Other useful work remains selectable and the review limitation stays visible. |
| Arrange a fresh reviewer for that deferred task | Existing explicit task selection accepts a genuine independent response and permits integration, without deleting history or resetting the audit. |
| Submit a malformed source-comparison row twice through the normal CLI, then correct it | Replay stores no duplicate attempt and is identified as a replay; the corrected row succeeds without new mathematical examination. |
| Register a wholly unavailable promised proof, contrasted with a confirmed manuscript omission | Both retain the known claim without a fabricated proof. Unavailable evidence remains working; a genuinely assessed omission retains its existing completion policy. |
| Capture the needed continuation and resolve its earlier absence | Its retrieval provenance remains visible but does not itself block completion. Only affected records/work change; the final frozen counts reflect the actual result. |

Extend existing integration, recovery, omitted-proof and delivery tests where they already cover these paths. Run affected tests during development, then the combined v3 suite once after integration. Include one normal CLI-to-freeze-to-HTML fixture so internal tests cannot hide an unusable public command path. Do not repeatedly run the whole paper or build a new evaluation framework to complete this patch.

Refresh and verify the candidate's own runtime manifest with `scripts/build_manifest.py`; retain the existing protocol/storage format. Update `VALIDATION.md` with the checks actually performed and their limitations. A subsequent paper test should observe completion, repeated identical submissions and final scope against the same inputs; passing synthetic tests alone is not evidence of improved paper-run speed.

Do not install or publish as part of writing this plan. For later release, keep the canonical skill name and use the normal patch-release process, with **3.0.1** as the proposed version. Installation targets remain the user-wide `.agents/skills/stat-proof-check` and `.claude/skills/stat-proof-check`, not a new `stat-proof-check-v3` skill.

## Explicitly outside this patch

- Database redesign, new persistent progress states, mandatory source inventories, calibration, per-edge certification, automated mathematical repair and blanket permissive schema handling.
- A general workflow runner, automatic retry loops or global time limits. Existing useful commands should become easier to finish with.
- Broad changes to external-result authoring, Graphify, rendering design or historical readers unless a focused regression demonstrates a direct dependency.
- Investigation of the test runner's silent process tail. Codex produced its final output at about 45 minutes, while its process exited much later. The cause is unproven. Investigate process lifetime and background tool cleanup separately; do not turn that discrepancy into additional proof-skill duties.

The patch is ready for practical testing when the normal commands finish these scenarios without historical-pin repairs, repeated unchanged submissions or fabricated completeness, while preserving honest scientific uncertainty and unperformed-work limitations.
