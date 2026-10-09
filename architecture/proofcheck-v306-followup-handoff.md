# Targeted proof-check revision after v3.0.6

Date: 2026-10-07, America/Chicago. Status: implemented in the v3.0.7 source candidate after two rounds of scratch experiments. See stat-proof-check-v3/VALIDATION.md for implementation validation. Installation is separate.

## Objective

Finish the planned audit smoothly by reducing response-format mistakes, local intake repair, and repeated submission of saved work. Preserve the three stages, coordinator ownership of the database, independent review, and existing scientific completion rules.

The main gap is now the execution interface. Much of the correct recovery guidance already exists in controller-workflow.md and coordinator-protocol.md. Replace the contradictory instruction and provide a small supported path for repetitive mechanics. Do not add another general workflow specification.

The implementation belongs in `stat-proof-check-v3`, whose canonical skill name remains `stat-proof-check`. This handoff does not authorize changes to proof-graphify or the historical v2 package.

## Evidence and confidence

Three sol-6.1-xhigh subagents conducted the second round, each within ten minutes. Tests used small synthetic databases and the current production runtime. The parent inspected the prototypes, challenged their boundaries, and checked the saved results. These are mechanical tests, not full-paper reruns or measurements of model compliance.

| Finding | Executed evidence | Revision consequence |
| --- | --- | --- |
| Independent instructions mention a nonexistent response field. | The role reference and generated examination note say `findings`; the independent schema has no such field. An actual submission rejected it. A faithful local repair was accepted with all judgment values and concern text preserved. | Correct the generated and written role interface. Keep primary and integration findings unchanged. |
| One malformed primary result need not discard useful results. | Null, non-object, missing-ID and ambiguous rows were preserved while separable actual judgments were accepted. No inconclusive placeholder was generated. | Offer local splitting of existing native responses, using the existing task mapping and validators. |
| Ancillary records can depend on a deferred result. | Filtering only result rows caused a linked finding to fail acceptance. Deferring that finding by its explicit task link preserved its content and allowed unrelated results to proceed. | Handle only existing explicit task links. Do not build a general dependency partitioner or erase the concern. |
| Restart and packet recreation do not necessarily mean new work. | Fresh-process resume, formatting-only changes, unchanged results in a newly generated packet, and unrelated revisions created no further submissions under the finite-return prototype. Changed legitimate returns could proceed. | Use existing submission history and current assignment bindings; no separate retry ledger. |
| Integration corrections have different identity rules. | The same authored decision can legitimately be applied after a newer comparison, through explicit correction preparation. | Keep integration and `--correct` on their existing path, outside ordinary return deduplication. |
| Saved-opinion adoption and unresolved completion already work. | Adoption preserved an unrelated open finding and uncertainty. Changed statements/evidence rejected stale adoption. An actual primary gap versus independent support finished as an unresolved release, without new examinations. | Preserve the existing mechanism. No new adjudication helper or compulsory review is justified. |

Second-round evidence:

- [Native primary intake](../tmp/v306-targeted-experiments-round2-20261007/intake/REPORT.md)
- [Finite saved-return submission](../tmp/v306-targeted-experiments-round2-20261007/submission/REPORT.md)
- [Reviewer interface and correction](../tmp/v306-targeted-experiments-round2-20261007/correction-delivery/REPORT.md)
- [Parent validation](../tmp/v306-targeted-experiments-round2-20261007/parent-validation.json)

First-round staging evidence is in [the staging report](../tmp/v306-targeted-experiments-20261007/staging/REPORT.md). Both original and candidate staging succeeded on this host; the historical sandbox permission failure was not reproduced.

## 1. Make the independent return interface consistent

Priority: first. Smallest change with direct failure evidence.

Change these production locations:

- `scripts/paper_core/assistance.py`, `worker_guidance`: make the independent examination note use its actual fields. Retain legitimate primary finding guidance.
- `scripts/paper_core/review_groups.py`, `_finish`: explicitly direct workers to the already delivered scaffold and guidance.
- `references/independent-checker.md`: replace the ambiguous `reasoning or findings` and `original findings` instructions.

Suggested short wording:

> Fill each response-scaffold.json using worker-guidance.json and save it at its listed response_path. Keep the generated fields and question_id. Put concerns about the assigned conclusion in judgment reasoning and outcome, and other concerns in coverage_note.

The coordinator can turn an additional concern into a formal finding during existing integration when appropriate. Merely placing text in coverage_note neither resolves it nor establishes new scientific support. A local format repair keeps the original file and all scientific content; it does not silently sanitize arbitrary findings.

Do not add a `findings` field to independent responses, another return document, a new reviewer checklist, or extra independent-review calls. Replace the conflicting sentences rather than append duplicate recovery guidance elsewhere.

## 2. Add optional local repair for native primary responses

Priority: second. This is a convenience for an already authored response with separable malformed rows, not a prerequisite for every examination.

Add a small read-only helper adjacent to the existing response assistance. A proposed CLI entry is `stage1 intake-response DB --packet PACKET_ID --response ORIGINAL --out CANDIDATE`; finalize naming against the existing parser conventions during implementation. It reads the saved manifest from the database, so the coordinator need not produce another mapping file.

Inputs and outputs:

- Input is the current native primary response shape and its original saved assignment. `manifest.work.tasks` provides the authoritative task identity. Phase 1 prose drafts remain valid and are mapped by the coordinator as today.
- Output is an ordinary response candidate containing usable rows, plus structured diagnostics with original JSON paths for every deferred row. Keep the original file untouched. Existing stage submission performs acceptance.
- Missing or ambiguous answers stay absent. Never fill scientific scaffold defaults, infer completion, convert a mapping failure to inconclusive, merge reviewers, guess target IDs, or change a packet ID.
- Multiple rows claiming the same task defer that task rather than choosing a judgment. Unrelated usable tasks can proceed.
- Defer a coverage/finding row with its original content when its explicit `check_task_ids` or `related_task_ids` depend on a deferred check. This is local bookkeeping, not resolution of the concern.
- Malformed whole-file JSON or ancillary structures receive a local diagnostic. Do not turn this helper into a parser-repair engine or a general graph partitioner.
- Shape-valid is not accepted. Existing scope, reference, freshness and scientific-body validation remains authoritative. A candidate containing no usable work is not submitted automatically.

Implementation seams are `contract.py` row schemas, `controller.py` response assistance and submission, and `cli.py` for the optional command. Keep `_primary_plan`, stored response semantics, and transaction acceptance unchanged. Use source paths in diagnostics instead of inventing a new persistent tracking collection.

Update only the existing local-recovery paragraph to point to this helper. The happy path still submits the authored native response directly. Acceptance of a subset does not claim the deferred concerns have been integrated or that all planned work is complete.

## 3. Provide a finite pass for saved reviewer-group returns

Priority: third. Use the existing group index so coordinators need not write a submission loop or another batch manifest.

Proposed public entry:

```text
AUDIT stage2 submit-group audit.db --audit AUDIT_ID --group-index work/reviewer-a/group-index.json --reviewer ACTUAL_REVIEWER --exposure ACTUAL_EXPOSURE
```

`review_groups.submit_group` should reuse `_saved_packets` to validate the existing membership. `cli.py` supplies the command. The shared implementation should call the existing submission machinery rather than duplicate envelope construction, contract-version constants, acceptance logic, or request identity code.

Behavior:

1. Take a fixed set of saved group entries for this invocation. Process each expected response once and return an entry-level result. There is no loop over all pending audit tasks, automatic re-preparation, dispatch, format repair, or mathematical continuation.
2. Missing, unreadable or malformed files produce local diagnostics and allow other saved returns to proceed. A database-wide failure may end the invocation; preserve committed per-response work and expose recovery through existing records.
3. Reuse current work status and saved submissions after restart. An accepted-but-pending response is saved work, not an instruction to submit itself repeatedly. Read structured state and replay information, not only process exit code.
4. Compare structurally unchanged returns with existing saved attempts while retaining truthful reviewer/exposure identity. Whitespace, another directory, an unrelated database revision, or a new packet wrapper alone do not establish a new attempt. Use existing assignment bindings to distinguish context; do not build a semantic equivalence classifier.
5. An interrupted `received` submission resumes its exact saved envelope and bytes through the current recovery path. Never substitute reformatted bytes under that request ID.
6. Changed usable responses can proceed. A stale original assignment needs affected current work or a limitation. The helper never relabels old answers with a new packet ID. A separately authored current answer may have the same conclusion or wording; new phrasing is not proof of new examination.
7. End with submitted, already-saved, missing, deferred and locally failed entries plus current remaining work. Finishing the pass does not mark the audit complete or clear uncertainty.

Use the response_path recorded in the existing group index. When it is absent, report any known prior locations for explicit selection; do not silently choose a historical answer. If distinct files make the intended return ambiguous, identify that packet for explicit selection instead of picking by modification time. An optional per-packet response-path override may support a local repair; do not require a new file manifest for ordinary use. One command uses truthful common reviewer provenance; differently authored returns remain separate.

For Stage 1, retain the existing single-response command. The same finite internal primitive may support a coordinator that already has an explicit list of primary preparations and saved returns; do not add a new compulsory primary batch format. This does not prevent a custom driver from ignoring the interface. The next paper test must check whether coordinators actually use the supported path.

Keep reconciliation and explicit `--correct` outside this helper. Do not use ordinary pending-task status or historical answer equality to suppress a requested integration correction. The existing correction preparation validates its selected current predecessor.

## 4. Preserve the working correction mechanism

No new correction engine is part of this revision.

Retain `stage2 prepare --mode integration --correct --task ...` and the four existing integration choices. The coordinator compares saved reasoning, authors the disposition, and can keep an unresolved disagreement. A separate open finding retains its own lifecycle. Only materially changed or unexamined content can require affected examination; adopting saved reasoning does not.

Keep the useful regression cases from the experiments. Avoid another explanatory section duplicating reconciler.md. If a generated command needs a discoverability improvement, link to the existing correction route at that decision point.

## 5. Keep staging as a separate small delivery change

The demonstrated defect is that cleanup can mask the original failure. Preserve the primary exception in `finalization.py` and frozen publication in `publish.py`, while retaining cleanup information and existing output rollback behavior.

An operation-local staging helper using an approved sibling directory is a plausible Windows compatibility change. The first-round candidate used inherited Windows permissions, private POSIX permissions, exclusive random directory creation, and no process-wide monkeypatch or permission fallback. Its freeze/render and failure controls passed, but the historical sandbox mismatch did not reproduce.

Before treating the permission issue as fixed, run a tiny create/write/freeze/render probe in the affected execution environment. This is an implementation validation step, not a new preflight required for every proof audit. If that environment is unavailable, retain the compatibility uncertainty explicitly. A delivery failure never causes the scientific audit to rerun.

## Validation and stopping criteria

Use a compact regression set around the changed mechanics:

| Case | Required observable result |
| --- | --- |
| Normal primary and independent responses | Existing direct submission remains accepted and content remains unchanged. |
| Malformed primary row beside a complete adverse row | Candidate preserves the adverse outcome; deferred content is retained; no placeholder examination appears. |
| Duplicate same-task rows, plus linked finding | Only affected rows and explicitly dependent ancillary records defer. No concern is resolved or silently lost. |
| Unsupported independent findings field | Local repair retains judgments, locations and concern text; original bytes remain available; another group packet can succeed. |
| Accepted-but-pending, replay, restart and formatting-only change | Finite pass ends and repeated invocations do not create repeated scientific records or new equivalent attempts. |
| Genuine changed return or question | Changed return can be accepted; stale bound response cannot supply current support; only affected work changes. |
| Interrupted received input | Resume the same saved request and bytes. |
| Explicit correction after completed work or newer predecessor | Existing correction remains available; no ordinary-return deduplication suppresses it. |
| Adoption with an open concern; genuine unresolved disagreement | Concern stays open; completed disagreement can freeze with its actual scientific status and no extra proof work. |
| Staging write/render plus cleanup failure | First error remains visible, prior valid output survives, and scientific records are unchanged. |

Use current `test_v3_intake_replay`, `test_v3_review_groups`, `test_v3_recovery`, `test_v3_integration_corrections`, and `test_v3_delivery` fixtures where they fit. Add only the missing behavioral cases. Run focused tests first, then the existing v3 regression suite once because the new helpers touch shared preparation/submission. Regenerate and verify the packaged runtime manifest through the existing package process. Record the tested version and actual installed identity when a later installation is requested.

The next full-paper run measures operational effect: repeated submissions, format-only reviewer redispatches, retained usable returns, and delivery completion at the declared scope. Differences in supported/gap/inconclusive counts are not themselves evidence of this mechanical revision succeeding or failing.

Stop implementation when these targeted behaviors pass and normal workflows remain compatible. Do not expand this patch into scientific calibration, a database redesign, new proof decomposition, automatic conflict resolution, general scheduling, or another round of universal checks.
