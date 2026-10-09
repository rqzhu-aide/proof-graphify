# Targeted handoff: reviewer identity and reliable returns

Baseline: stat-proof-check 3.0.10. Status: implemented and independently validated as 3.0.11, now in the formal `stat-proof-check` folder; the testing-center harness patch is applied, while installed skills remain 3.0.10. See `../stat-proof-check/VALIDATION.md` and local `../tmp/v311-implementation/` for implementation evidence. Original audit evidence and planning experiments remain under local `../tmp/v310-rf-hte-results-audit-20261009/` and `../tmp/v310-revision-experiments-20261009/`. The sections below preserve the approved revision plan and its original development paths.

## Intended result

The coordinator obtains independent review from its own provider/model in an isolated context, retains each worker's original return, and fixes ordinary packaging errors locally. Completed unchanged science does not repeat because a combined message was clipped or optional metadata was malformed. Keep the current three stages, database structure and scientific obligations.

## 1. Define same-model commissioning

Owner: skill maintainer. Update the Stage 2 commissioning paragraph in `stat-proof-check-v3/references/controller-workflow.md`, and clarify the model-agnostic sentence in `references/independent-checker.md`. Keep the existing coordinator reference to this policy rather than duplicating it throughout the skill.

- Independent review uses the same effective provider and model as the coordinator. Native delegation may rely on trusted configured inheritance, with no inherited primary conversation. A fresh subprocess uses the effective root model/profile explicitly, including configured reasoning settings when available. Derive this from the actual root configuration, including overrides, rather than only the slot name.
- A different provider/model requires explicit user authorization. Existing authorization remains valid. Record actual available identity in existing reviewer and run evidence; no qualification record or model registry is needed.
- Trusted launch configuration or established native inheritance is sufficient when backend identity metadata is unavailable. Do not create a model-attestation task or probe repeatedly. If available returned metadata contradicts the intended model, preserve the response with its actual identity and do not count it as satisfying a same-model requirement. A known contradiction takes precedence over presumed inheritance.
- Initial review starts separately from the primary session. Continuation may use the same known source-only reviewer session and saved reasoning. A directory-based `--last` or continue flag is not sufficient evidence that the resumed session is that reviewer rather than the coordinator. If exact reviewer resumption is unsupported, use a fresh same-model context with its source-only saved work.
- Use the known route and correct a concrete local launch error if possible. If same-model review cannot be obtained, retain the missing-review limitation and finish useful work at its actual level. Do not search unrelated CLIs or change model merely to obtain a release.

This is a relationship between coordinator and reviewer, not a prescribed model brand. Keep the scientific protocol usable with any provider.

## 2. Supply a reliable host launch recipe

Owner: testing-harness maintainer. The relevant external file is `C:/Users/zrq/projects/skills/_testing-center/run-test.sh`; deployment belongs to the testing-center workstream. The skill carries the universal rule, while this harness carries provider-specific syntax.

Derive one initial reviewer recipe from the same effective configuration as the root launch, using the initial/fresh path rather than the root followup path. The existing model mapping and argument construction already cover the five current slot families. Include the role prompt, explicit source-only delivery paths and generated scaffold. Supply arguments without reconstructing a shell command from concatenated prose. Capture stdout separately when the worker cannot save its response file.

Respect root overrides and the current DSH profile/patch mechanism. Reasoning settings not carried in argv remain a host responsibility; lack of optional effort metadata is not an audit blocker. Record the selected route and configured/resolved identity in existing run evidence. Do not introduce PATH lockdown, another model catalog or a general launcher framework.

The scratch tests validate argument construction and Windows argument transport, not provider authentication or successful live model execution. Before the next paper test, perform one small same-model launch check for each affected harness route that lacks live evidence, especially DSH and Pi. Test launch, source-only input access and usable return capture, not mathematical performance or calibration. Do not make each paper repeat that setup test while the route is unchanged.

## 3. Preserve individual returns before aggregate clipping

Owner: skill maintainer for assignment/recovery guidance; host for byte capture. Make a short addition to `references/phase1-drafts.md` and the relevant delivery/recovery paragraphs of `references/controller-workflow.md`.

Name an original-return location with each existing coherent assignment. A writable worker saves its draft or generated response there and returns a concise path/status. For a worker without write access, capture the full individual return/stdout before combined-message formatting or clipping. The aggregate message is a notification; it must not be the only copy. Use existing assignment IDs and response paths. No new queue, return ledger or receipt format is required.

After interruption or truncation, retrieve those individual originals through ordinary draft mapping, packet intake and current status. Keep covered unchanged questions and continue only unavailable, unexamined or materially changed work. Source freshness rules still apply. File existence, a successful process exit, parseable JSON, or acceptance of a partial response does not mean the scientific examination is complete. Existing coverage and remaining-work status already express that distinction.

Freeform Phase 1 drafts remain valid. Do not impose independent-review JSON on them. If no complete retained copy exists, do not reconstruct discarded reasoning or relaunch completed unrelated groups. The affected missing content remains a limitation or receives only its necessary continuation. Instructions cannot recover bytes that the host discarded before saving them.

## 4. Keep intake and diagnostics direct

Owner: skill maintainer. Limit executable changes to diagnostic text in `scripts/paper_core/controller.py`; preserve acceptance conditions and error codes.

Replace:

`primary/reconcile work has null qualification and exposure fields`

with:

`primary/reconcile work requires qualification_id and exposure to be null`

For coherent-protocol optional qualification errors, add a concise explanation that ordinary review uses null when no calibration exists. Preserve genuine calibration claims and correct actual reviewer/protocol mismatches. Do not automatically clear a failed qualification or manufacture passing cases. Historical protocols retain their existing requirements.

In the Stage 2 delivery instructions, say that the generated independent scaffold is also the return format for stdout-only reviewers. The coordinator captures it instead of inventing a replacement schema. `independent-checker.md` needs at most the matching short stdout clarification. Existing `reviewer-delivery.json` already supplies scaffold and response paths; do not add another interface or required metadata record.

Preserve original returned bytes. An empty extra field can be repaired locally when unambiguous. A nonempty concern must survive in the appropriate supported reasoning/coverage fields and be accounted for in integration. Do not discard adverse material to obtain acceptance or infer a missing scientific judgment. No general response converter is justified by these experiments.

## Validation evidence

Three Sol 6.1 xhigh subagents ran bounded experiments, each below ten minutes. The parent reviewed scripts and results and requested adversarial refinements where the first interpretation was too permissive.

- [Route experiment](../tmp/v310-revision-experiments-20261009/routes/REPORT.md): extracted actual harness argument builders, five slot families, overrides, Windows multiline/quoted argument transport, initial vs followup routes, and synthetic decisions for identity uncertainty, observed mismatch, explicit authorization and valid reviewer continuation. A parent check required observed model mismatch to override presumed configuration/inheritance. These are argv/stub and decision tests, not live provider runs.
- [Return experiment](../tmp/v310-revision-experiments-20261009/returns/REPORT.md): three originals of 208,860 bytes each survive simulated aggregate clipping. Native intake stores exact originals, repeated recovery keeps one submission per original and creates no new packets. Missing, malformed, valid-but-empty, partial, stale, stdout-only and interrupted-after-capture cases retain the correct local remaining work. The transport simulation also demonstrates that intake cannot detect content lost before a host rewrites valid complete JSON.
- [Intake experiment](../tmp/v310-revision-experiments-20261009/intake/REPORT.md): corrected metadata accepts the identical primary/integration response and preserves adverse reasoning; normal independent review succeeds with null qualification; false or mismatched qualification claims still reject. The actual nine malformed GLM returns have empty extra findings; DSH's handwritten R1 envelope contains nonempty concerns. Explicit local correction preserves those concerns through integration. No normalization helper is needed.

During implementation, retain these representative behavioral cases as focused regressions where relevant. Check normal null review, invalid metadata correction, invalid claimed qualification, preserved adverse content, no duplicate recovery and unchanged source-only exposure. Verify the runtime manifest and existing installation packaging normally. Do not require a whole-paper rerun to validate an error-message edit.

## Keep outside this patch

Do not change schemas, review obligations, qualification semantics, packet scope, mathematical outcomes or Phase 3 visuals. Citation-to-packet mismatches and external-source navigation remain separately tracked issues; widening all packets or adding another manuscript sweep is not supported by this validation. Do not treat mock process success as evidence that current DSH aggregation safely retains full child output.

Publish the next patch only after implementation and focused verification. The candidate is now 3.0.11 and installed copies remain 3.0.10. These changes are intended to remove launch and recovery detours, not to establish improved whole-paper speed or scientific accuracy before the next practical run.
