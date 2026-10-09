# Targeted proof-check recovery revision: implementation handoff

Date: October 2, 2026. Status: implemented in the working tree. Read the [focused audit](proofcheck-local-recovery-audit.md) for the original failures and the [validation record](proofcheck-local-recovery-validation.md) for implementation results and limits.

## Intended result

An ordinary submission mistake should lead to a specific local correction. Saved valid examinations remain usable. A genuine change to scientific inputs renews only the affected work under the existing rules. A negative conclusion remains a useful examination outcome.

This revision completes six narrow repairs on top of the implemented [agent-independent workflow](proofcheck-agent-workflow-revision-handoff.md). It does not replace that workflow or roll back to 2.3.5. It applies to any agent using the public commands and saved artifacts; it requires no particular model, host or subagent API.

## Starting point and boundaries

The audited source identity is `eb155e69ab7aef79ba1a0a3f92112ac063dd2d98643e9b5425f0127abfb4b82c`. Repository baselines and pre-existing changes are in the [baseline manifest](../../audit-reports/local-recovery-audit-2026-10-02/baseline.json). Recheck them before editing; preserve the existing unreleased implementation and unrelated work. Edit `shared/paper_core`, then regenerate both package bundles. Never hand-edit generated core copies.

Keep these invariants:

- Original worker bytes, terminal receipts and actual provenance remain immutable. Corrected submissions follow existing request-ID rules.
- Scientific scope, qualification, independence, freshness, whole-response acceptance and negative-outcome handling remain intact.
- Compute decisions from authoritative complete facts. A shortened display cannot change what action is eligible.
- Continue coherent primary work and genuine examiner continuity. Record types do not imply separate workers.
- Keep the current command/storage/record/packet contracts. Additive inspection fields are allowed; no migration or new workflow state is needed.
- Keep existing byte/record limits, privacy separation and explicit bounded failures.

Do not add a generic retry engine, automatic dispatcher, failure counter table, second task ledger, new mandatory manual, fuzzy ID matching, scientific-field defaults or automatic rewriting of worker output. Existing no-progress guidance and `repeated_unchanged_draft` remain sufficient for this revision.

## R1. Derive recovery before truncating output

Owner files: [review.py](../shared/paper_core/review.py), `inspect_response` and `response_recovery`. Tests: `test_review_recovery.py`, with CLI coverage in existing CLI/recovery tests as needed.

1. Keep complete pending judgment diagnostics and category-to-index sets available internally. Derive all recovery action eligibility from those sets plus complete global blockers/current-input facts.
2. Only after deriving actions, apply display limits to index lists and diagnostic rows. Preserve the existing `judgment_indexes` field. Add explicit total count and truncation indicators where an action's list is bounded, following existing inspection conventions.
3. Do not reconstruct hidden blockers from shortened output. Give the helper an explicit completeness contract so passing bounded inspection data back into `response_recovery` cannot recreate unsafe eligibility. If complete facts are unavailable, return inspection guidance rather than guessing safe indexes. Do not expose a large internal diagnostic object merely to avoid this separation.
4. Retain per-judgment eligibility: one judgment needing new source must not prevent mapping another eligible judgment. A global pairing/provenance/input blocker still prevents mapping where the current rules require it.
5. Use the same internal decision logic for direct review, controller submission and current inspection. Preserve old saved receipts; recompute advice only in current inspection.

Acceptance: changing `limit` affects presentation only. Every mapping index advertised in unchanged state is compatible with the full diagnostics and an otherwise valid mapping request. Exercise advertised mappings in fresh equivalent fixtures or one valid combined request, so an earlier mapping does not change the guards for the next assertion. An invalid mapping remains rejected by the unchanged acceptance path.

## R2. Verify packet pairing before assigning fault

Owner files: [controller.py](../shared/paper_core/controller.py), `submit_work` and `_failure`; [review.py](../shared/paper_core/review.py), `_worker_diagnostics` and `response_recovery`. Tests: existing controller/adversarial and review-recovery modules.

For two supplied, different packet identities:

1. Preserve existing failure semantics and identifiers: controller intake rejects the attempt; direct review stores a `needs_revision` response without scientific credit. Do not turn direct review into a throwing rejection. Attach a specific structured recovery action using the existing error/recovery mechanism, preferably the existing `inspect_assignment` operation, with `reason_code: PACKET_MISMATCH` and both `envelope_packet_id` and `worker_packet_id`.
2. Explain the concrete next step: compare the saved assignment/delivery artifacts and actual provenance to determine which input belongs to the examination. Neither ID is automatically preferred because it is newer, exists, or matches a folder name.
3. If the envelope is wrong, the coordinator corrects it with actual provenance and the required fresh request ID, preserving response bytes. If the authored response is wrong, its author corrects it; a replacement examiner follows the existing truthful-authorship rule.
4. A missing identity, non-object JSON or malformed response remains an authoring/shape problem. Separate it from a conflict between two provided identities.
5. Direct review must give equivalent advice. Retain its existing diagnostic category for compatibility where practical, but stop translating that category directly into worker fault. Keep the mismatch a mapping blocker.
6. While packet pairing is unresolved, retain raw diagnostics but defer scope correction, source extension and input-renewal advice inferred solely by comparing the response with the disputed packet. Recompute those remedies after pairing is resolved. Independently established format or provenance problems remain visible. Test packets with disjoint source anchors, not only two IDs for identical source context.

Do not automatically rewrite `worker.packet_id`, copy provenance from another attempt, rebind scientific evidence, or guess which request supersedes which.

Acceptance: both directions of mismatch receive neutral pairing advice. Correcting only the envelope accepts the probe's unchanged worker bytes. A genuinely wrong worker identity still requires the appropriate authored correction. The original request replays its exact historical receipt.

## R3. Make current inspection reflect current obligations

Owner file: [controller.py](../shared/paper_core/controller.py), `_current`. Reuse `derive_work` and existing current-obligation extraction patterns rather than create a replacement ledger. Tests: `test_controller.py` and `test_revision_recovery_trace.py`.

For a selected terminal rejected request without a stored response/receipt, derive current status for the original assignment before producing current advice. The original packet determines the assignment; current state determines what evidence is still needed. Bound only the displayed task list, not the decision.

| Current facts | Required current advice |
| --- | --- |
| Complete analysis; every original assigned required obligation is identifiable and satisfied by applicable current evidence | State that the historical rejection alone establishes no missing examination. Show current evidence and direct attention to remaining audit work and any unresolved concerns. Do not request repair of the old submission solely because it failed. |
| Only part of the original assigned work is satisfied | Identify the actual remaining obligations and relevant blockers. Preserve useful saved output; make correction or renewal conditional on that remaining need. |
| Current evidence is stale, draft, disputed or unusable for required independence | Follow existing evidence/changed-input/reconciliation guidance. A later accepted submission is insufficient evidence of completion. |
| Analysis is incomplete, original task identities are absent, scope changed, or packet pairing is unresolved | Report the uncertainty and inspect current assignment/work. Do not treat missing/empty rows as completion or silently choose the worker/envelope scope. |
| Intake is still `received` | Retain the existing exact same-ID replay procedure. This change is about terminal rejection, not interruption recovery. |

Expose enough current data to assess the recommendation: analysis completeness, assigned task identities/statuses, applicable judgment references, outcomes and freshness where available. Prefer existing field conventions. Keep `result`, stored state and blobs historical and unchanged.

A satisfied obligation does not prove that every concern in rejected raw bytes was reconciled. Preserve access to those bytes and explicitly direct comparison of unresolved concerns. Do not parse arbitrary rejected prose to declare it resolved, and do not implement "latest accepted wins." Reuse the assessment's existing dispute and supersession rules.

The all-satisfied branch applies only to original work whose present relevance can be established. Retired/excluded targets and unrelated replacement tasks require inspection, not a vacuous success claim. `analysis_complete` describes derivation completeness, not audit completion.

## R4. Include bounded proof-source evidence in primary global assignments

Owner file: [packets.py](../shared/paper_core/packets.py), `_LocalClosure.task` audit branch. Tests: `test_work_packets.py` and existing packet/scaling/privacy tests. Supporting prose: the recovery section of [controller-workflow.md](../stat-proof-check/references/controller-workflow.md).

Repair the normal assignment path so its global checks can cite the registered proof evidence they need:

1. Retain the existing global audit selection, Full/Focused distinction, scope and exclusions. Do not broaden unrelated local assignments.
2. Add shallow proof-source context for the selected live targets and their registered routes: proof/evidence passages, argument evidence anchors, and anchors selected by linked proof boundaries, including supplementary continuations. A supporting source review is provenance and can cover additional unrelated passages; do not union every anchor it mentions into the assignment.
3. Reuse shallow helpers such as `borrowed_proof` and `proof_boundary`, indexed relations and deduplication. Use existing proof-selection/provenance mechanisms for pinned source reviews; preserve the live-record packet contract. Diagnose a pin that existing representation cannot carry faithfully. Do not change generic `_Closure.add_ref` semantics or introduce a historical packet format. Do not call the full `argument()` or `statement_closure()` for every target: those paths bring unrelated groups, coverage and examinations into the global packet.
4. Apply this to the primary/global branch. Preserve neutral independent delivery and existing write authorization. Adding source context grants no new examination credit.
5. Keep current byte/record accounting and failure diagnostics. If complete selected context exceeds bounds, return the existing explicit size result with measured contributors. Do not silently omit the continuation, increase global limits, or pretend a retry must fit.

Before declaring this repair complete, replay preserved global cases on disposable copies at the normal limit and, when needed, the supported maximum. Record included evidence and payload size. A newly oversized previously fitting case needs investigation and a workable existing bounded recovery route before claiming the workflow problem solved. Absence of a rejection is not evidence that the full proof was examined.

Document exceptional recovery for an already saved primary/global response: inspect the named missing reference, obtain an appropriate current direct `get --mode primary` packet, use direct context extension if needed, then author a permitted direct check through generated templates and `apply`. This is not a controller rebase: a direct packet lacks the controller work assignment, and rebasing cannot invent evidence absent from the original examination.

Preserve the old response and receipt. The original examiner can author the new scientific fields using its saved reasoning without repeating unchanged mathematics. If a different examiner must take over, it identifies itself and examines the relevant evidence sufficiently to support its own judgment. Mechanical preparation can be delegated; neither a coordinator nor a serializer silently becomes the scientific author. Genuinely new source still requires examination. Keep independent missing-source recovery on its existing `work extend` path.

## R5. Explain conditional results in the normal scope guidance

Owner file: [graph-records.md](../stat-proof-check/references/graph-records.md), existing scope discussion. Use the distinction in [probability-example.md](../stat-proof-check/references/probability-example.md) as the source. Do not require all agents to load that example.

Add one concise paired example:

- A reusable lemma saying "for every X satisfying H(X), C(X) holds" carries H in its assertion. Each application establishes H for its chosen X. Do not model the reusable conditional result as available only inside one sibling proof's temporary assumptions.
- A fact established under a temporary premise inside a particular proof remains local until the applicable discharge. Writing it as a globally available unconditional fact is incorrect.

Preserve exact source hypotheses and existing scope/application checks. Do not advise globally clearing `scope_id`, moving every assumption to shared setup, or adding a missing manuscript hypothesis to make the claim true.

Acceptance must inspect support, not just audit completion: the correctly represented conditional lemma is available at a justified application, while a truly inaccessible temporary premise remains unavailable. A negative main theorem in the existing small example does not by itself test this distinction.

## R6. Clarify navigation and local recovery in one existing reference

Owner file: [controller-workflow.md](../stat-proof-check/references/controller-workflow.md). Add a short link from the stopping/inventory guidance in `database-audit.md` only where needed.

- Explain that `work list` is a page, not the entire inventory. Follow non-null `next_cursor` with unchanged audit/focus to inspect the rest. After writes, start a fresh current-state listing; the old cursor belongs to its snapshot. Do not declare completion from one page or require scanning every page before every local operation.
- Align the recovery table with R2 and R3: verify conflicting packet identities first, and inspect current obligations before reviving historical failed work.
- Add the short exceptional primary-context route from R4, clearly separate from independent extension.
- Keep the existing unchanged-blocker rule: take an action that changes the relevant input/evidence/state, resolve the named blocker, or stop that branch and continue other useful work. A new filename, request ID, worker or identical draft is not progress by itself.

Replace overlapping wording. Keep `SKILL.md` as its current router unless a link genuinely needs correction. The runtime skill should not load this handoff, harness research or another recovery manual.

## Ordered implementation and verification

1. Capture the actual baseline and preserve existing changes. Promote the small probes into the existing maintained test modules; keep original test-center databases read-only and use disposable copies for replay.
2. Implement R1-R3 together because they share recovery advice. Run the focused existing tests, including corrected submissions through the public paths. Avoid assertions that merely match prose.
3. Implement R4 and verify packet completeness, limits and independent privacy. Apply R5-R6 and exercise their meaningful behaviors.
4. Rebuild both generated bundles and run the repository's required suites once against the final candidate. Re-run only checks affected by later changes or unresolved failures.
5. Conduct one bounded fresh-agent exercise using only shipped instructions and raw scenario artifacts. It should cover continuation after saved output and a conditional lemma application; retain actual actions, outcomes and limitations. Do not supply the evaluator this plan's expected answers. Reuse the existing small scenario instead of commissioning another general audit of every role.
6. Record implementation changes, validation results, unresolved limits and actual candidate content identity in a short validation note. A later matched RF-HTE run is required to claim full-paper completion or a speed improvement. Software tests and a small exercise alone cannot establish those claims.

### Required behavioral cases

| Case | Observable acceptance condition |
| --- | --- |
| Overlapping blockers at `limit=1` and default overflow at 21 judgments | No blocked judgment is advertised as mappable. Execute advertised mappings in fresh equivalent fixtures or one valid combined request. Include missing-source and wrong-kind/scope variants, and bounded-data helper input. |
| Different judgments with independent remedies | An eligible mapping remains available while another judgment needs extension; the response remains pending until whole-response requirements hold. |
| Both directions of packet mismatch through controller and direct review | Both identities appear; no automatic blame or rewriting; correct envelope reuses exact worker bytes. A disjoint-source mismatch does not prescribe extension or renewal until pairing is resolved. |
| Missing/non-object response identity | Accurate authoring/shape advice remains; it is not disguised as an administrative mismatch. |
| Old rejection after current completion, including `gap`/`refuted` outcomes | Current advice does not demand duplicate examination. Original receipt/hash/state remains unchanged. |
| Partial successor, accepted draft, later source change, dispute, or unusable independence | Remaining work stays explicit; no "latest accepted wins" shortcut. |
| Incomplete derivation, missing task, or ambiguous assignment | Unknown is not reported as completion. |
| Interrupted `received` intake and terminal identical replay | Existing replay behavior and transaction/receipt guarantees remain unchanged. |
| Global proof anchor absent from statement passages; continuation only in a boundary | Normal global preparation includes the registered evidence, and a synthetic check citing it submits without context rejection. An unrelated anchor mentioned only by the supporting source review stays out. |
| Boundary with an older pinned source review; proof evidence or selected route membership changes after preparation | Existing provenance mechanisms handle the pin faithfully or diagnose incompatibility. Consumed scientific changes trigger existing stale-input behavior; unrelated label edits retain their existing treatment. |
| Global payload exceeding byte or record limits | Explicit bounded failure, no misleading successful truncated packet. |
| Local and independent assignment controls | No irrelevant proof-history expansion or private context leakage. |
| Conditional lemma and temporary-premise pair | Correct application support is available; truly local premise remains restricted. |
| Work list with more than 100 rows and a subsequent write | Cursor traversal finds remaining obligations; fresh listing after the write reflects current state. |

Start with existing modules `test_review_recovery.py`, `test_controller.py`, `test_controller_adversarial.py`, `test_revision_recovery_trace.py`, `test_work_packets.py`, `test_work.py`, and relevant support/projection tests. If a genuinely new test module is needed, update the existing test inventory. Preserve existing no-progress, acceptance, freshness and packaging coverage.

Use the [repository validation commands](../README.md#backend-and-validation) and existing shared runtimes. The audited Windows Python is `C:/Users/zrq/AppData/Local/Python/pythoncore-3.14-64/python.exe`; restricted access is not evidence it is missing. Do not create a project-local environment. The bundle commands, run from the maintained repository, are:

```text
python -X utf8 -B tools/build_paper_core_bundles.py
python -X utf8 -B tools/build_paper_core_bundles.py --check --release-manifest <validation-directory>/candidate.json
```

Run the shared-core suite plus the repository-prescribed proof-check, installer and Graphify suites after regeneration. The companion Graphify change is shared-core compatibility, with its overview behavior preserved. Verify the package actually used by a behavioral run through its content identity. Existing installed copies were older than the working candidate in the previous audit; unchanged version labels are insufficient.

## Delivery boundary

This handoff was prepared as an audit/plan deliverable without a runtime patch or release action. Its subsequent implementation is recorded in the [validation note](proofcheck-local-recovery-validation.md); version bump, installation, commit and push remain separate release actions.

When implementation and release are requested, preserve session authorization and follow the normal paired packaging process. If the baselines remain unchanged, compatible patch candidates are proof-check/core 2.3.8 and Graphify 3.1.15; recheck intervening releases first. Update maintained version declarations and relevant expectations, regenerate both bundles, verify user-wide `.agents` and `.claude` installs actually contain the intended packages, and record both repository commits. Do not test an older installed bundle and report it as validation of the revised source.

Implementation can be complete with its bounded tests passing while full RF-HTE performance remains unverified. State those two outcomes separately. No additional general audit stage is part of ordinary proof-check execution.
