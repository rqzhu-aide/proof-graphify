# Focused audit of proof-check recovery

Date: October 2, 2026. Status: audit complete; the companion [targeted handoff](proofcheck-local-recovery-handoff.md) is now implemented in the working tree. Findings below describe the audited pre-change candidate. See the [validation record](proofcheck-local-recovery-validation.md) for the subsequent repairs and their limits.

## Conclusion

The current workflow has the right overall structure. Its remaining repair loops arise mainly from incorrect recovery advice, incomplete global context and two omissions in normal instructions. Target those places. Preserve the continuing primary owner, independent examination, saved responses and strict scientific acceptance.

Three recovery defects were reproduced on fresh disposable fixtures in this audit. The packet-pairing defect also reproduces through direct review, extending the previous audit's controller finding. The other findings were rechecked against current source and the preserved earlier evidence. There is no evidence here of full RF-HTE completion or a measured speed improvement.

## Candidate and evidence

- Maintained repository: `stat-paper-skills`, HEAD `e2cff9791c844b824787e60e03e6ca31352ea8a9`, with 31 pre-existing changed/untracked files.
- Companion repository: `proof-graphify`, HEAD `0b974173cfa712f19c259eb43f3b438769646293`, with six pre-existing changed files.
- Both working bundles match maintained core identity `eb155e69ab7aef79ba1a0a3f92112ac063dd2d98643e9b5425f0127abfb4b82c`. The bundle check passed. Version labels remain proof-check/core 2.3.7 and Graphify 3.1.14.
- [Baseline manifest](../../audit-reports/local-recovery-audit-2026-10-02/baseline.json) records repository state and content identities before these documentation additions.
- All four user-wide installed manifests still report the older core identity `17a83ead76284ed5cbc134013c7552252759ecc092182dd839e2a5e6c1bb185e`. This was rechecked by reading the manifests; installed file integrity was not rerun. A future behavioral test must verify the package it actually executes.
- The current candidate already implements the [agent-independent workflow revision](proofcheck-agent-workflow-revision-handoff.md). This audit does not reopen that design or revive the separate automatic-workflow proposal.

The following probes ran with the existing user-wide Python 3.14.7, using `-X utf8 -B`. Each created its own synthetic fixture under the new audit directory. Their invented judgments test software behavior, not mathematics. Original test-center results and prior probe outputs were not modified.

| Fresh check | Observed result |
| --- | --- |
| [Controller pairing and historical inspection](../../audit-reports/local-recovery-audit-2026-10-02/recovery/probe_attempt_recovery.json) | Wrong envelope prescribed authored correction. Correct envelope accepted identical response bytes. An earlier malformed attempt still prescribed correction after all its required tasks were satisfied with adverse judgments. |
| [Two-judgment inspection](../../audit-reports/local-recovery-audit-2026-10-02/recovery/probe_truncated_recovery.json) | `limit=1` advertised mapping a judgment whose hidden source blocker made the mapping invalid. Executing the advice was rejected. |
| [Default-limit inspection](../../audit-reports/local-recovery-audit-2026-10-02/recovery/probe_truncated_recovery-default20.json) | The same defect reproduced with 21 judgments through the CLI default limit of 20. |
| [Direct-review pairing](../../audit-reports/local-recovery-audit-2026-10-02/recovery/probe_direct_pairing.json) | A valid response submitted against another packet produced authored-correction advice. Changing only the envelope accepted the identical response. |

## Findings

### A1. P2: Shortened output changes the meaning of recovery advice

In [review.py](../shared/paper_core/review.py), `inspect_response` truncates each category's judgment indexes around line 431 before calling `response_recovery`. That function subtracts blocked indexes from mapping candidates around line 492. Independent truncation can hide a blocker while retaining that judgment in another category.

Consequence: the agent follows advice, receives another deterministic rejection, and may unnecessarily seek more review. Validation still prevents invalid acceptance.

Correction: calculate the action sets from complete diagnostic facts, then shorten only their displayed indexes. Keep useful mapping for genuinely eligible rows when other rows need correction. Whole-response acceptance remains unchanged.

This newly reproduced default-limit case does not explain the older saved failures: the earlier audit found at most 12 judgments in those responses. An explicitly smaller inspection limit can expose it on smaller responses.

### A2. P2: Conflicting packet identities are prematurely blamed on the worker

In [controller.py](../shared/paper_core/controller.py), the packet mismatch at lines 552-554 occurs under `input_part = worker_response`; the generic branch at lines 466-468 consequently requests authored correction. [review.py](../shared/paper_core/review.py) has the same problem: `_worker_diagnostics` records `worker_packet_mismatch` around line 195, and `response_recovery` treats it as a worker-authored fault.

Consequence: a coordinator's envelope mistake can initiate worker contact or reexamination even though the saved response is valid. Both entry points reproduced this with identical accepted worker bytes after envelope correction.

Correction: expose the two identities and direct the coordinator to verify the saved assignment and provenance. A mismatch alone establishes neither which side is wrong nor permission to rewrite either side. Missing/non-object response identity is a distinct authoring problem. Apparent scope or missing-source errors derived from a mismatched packet cannot determine the remedy until pairing is resolved. Preserve the direct path's saved `needs_revision` response and the controller path's rejection semantics.

### A3. P2: Current inspection revives already completed work

In [controller.py](../shared/paper_core/controller.py), `_current` derives present task states for a successful receipt, but its terminal-rejection branch around lines 736-741 copies historical recovery directly. The fresh probe completes the original assigned tasks and still receives an instruction to obtain another authored correction.

Consequence: the required startup inventory of saved attempts can recreate unnecessary work after an interruption.

Correction: assess current obligations for the selected original assignment before deciding what correction remains useful. Preserve the historical result. Missing tasks, incomplete analysis, ambiguous pairing, draft evidence and later scientific changes must remain explicit. Completion of assigned obligations cannot establish that an unparsed historical scientific concern has been resolved.

### A4. P2: Global assignments can omit proof evidence required by their checks

The audit branch of `_LocalClosure.task` in [packets.py](../shared/paper_core/packets.py), around line 1041, supplies statements/setup without all registered proof anchors. Raising the byte cap cannot add records excluded by selection.

The [earlier full audit](../../audit-reports/current-version-audit-2026-10-02/audit.md) documents an actual `WRITE_SCOPE` rejection in the small continuation, and omissions of five relevant RF-HTE GLM anchors and one Distributional-RL anchor at the supported maximum. Those packet observations are retained evidence, not new runs in this audit; the responsible source and core identity remain unchanged.

Correction: enrich the existing primary/global selection with shallow, registered proof-source context within the same scope and bounds. Include boundary-selected anchors, not every passage mentioned by a supporting source review. Avoid traversing every proof group, coverage row or historical examination. Keep direct primary `get`/`apply` as exceptional recovery for already saved work; making that conversion the normal workflow would add format and authorship decisions.

### A5. P2: A correct conditional lemma can be represented as unavailable

[graph-records.md](../stat-proof-check/references/graph-records.md), around lines 118-138, does not clearly state the distinction already explained in [probability-example.md](../stat-proof-check/references/probability-example.md), lines 83-100: a reusable conditional theorem includes its hypotheses in its assertion, while a temporary proof premise restricts availability until appropriately discharged.

The previous small run placed lemma and consumer assumptions in sibling scopes. Its application examinations were valid, but its displayed support remained `scope_unavailable`. Late restructuring can reopen otherwise useful checks.

Correction: promote the distinction into ordinary authoring guidance and verify both a valid conditional application and a genuinely inaccessible temporary premise. This is an instruction/representation correction, not grounds to relax scope validation.

### A6. P3: The work-list continuation is insufficiently explained

[work.py](../shared/paper_core/work.py), `list_work` around line 562, already supplies a snapshot-bound `next_cursor`. [controller-workflow.md](../stat-proof-check/references/controller-workflow.md), around line 70, explains the row limit without explaining continuation.

The previous preserved Claude state had 129 unfinished required tasks, with only 51 visible among the first 100 rows. The other 78 were on later pages. This is a navigation risk, not silent data loss or proof that an agent will stop early.

Correction: document following the cursor with the same audit/focus and restarting current-state listing after writes. Keep database completion assessment authoritative.

## What the harness comparison supports

The source research inspected Pi at `9fba660cf1caca0ade5bea72269352416e595a19` and Hermes Agent at `4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a`.

- Pi converts invalid calls and exceptions into feedback in the existing conversation. This supports local, specific recovery advice. [Execution source](https://github.com/earendil-works/pi/blob/9fba660cf1caca0ade5bea72269352416e595a19/packages/agent/src/agent-loop.ts#L707-L847)
- Hermes distinguishes repeated unproductive calls from useful diagnostic iterations. Proof-check already has `repeated_unchanged_draft` in `work.py` and an unchanged-blocker stopping rule. Fixing the advice the agent follows is the immediate priority. [Hermes guardrails](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/agent/tool_guardrails.py)
- Hermes's optional verification policy tracks fresh evidence after edits; it does not supply universal semantic validation. Proof-check already has stronger domain-specific evidence and freshness requirements that should remain intact. [Verification policy](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/agent/verification_stop.py)

These are design analogies, not evidence that adopting another harness will make our paper audits finish. No generic retry engine, fuzzy scientific-ID repair, new task ledger or extra review stage is justified by these findings.

## Scope of the proposed change

Use four maintained runtime files at most: `review.py`, `controller.py`, `packets.py`, and `cli.py` only if presentation wiring requires it. The principal instruction edits belong in `controller-workflow.md` and `graph-records.md`; other references should receive only necessary links. Existing test modules can cover the changes.

Proof Graphify needs a regenerated compatible shared-core bundle and regression checks. No separate change to its selective overview workflow is supported by this audit.

Two separate agent reviews of the draft handoff identified refinements now incorporated: defer source-extension advice while packet pairing is unresolved; preserve direct-review storage semantics; avoid consuming bounded output as complete decision input; and keep global boundary selection separate from a source review's wider provenance. Required tests also cover consumed-input freshness and scientific concerns retained only in historical bytes.

No runtime source, installed skill, scientific source or remote repository was changed in this audit. New documentation and disposable evidence are the deliverables. The [handoff](proofcheck-local-recovery-handoff.md) defines implementation and validation, including the remaining full-run performance limit.
