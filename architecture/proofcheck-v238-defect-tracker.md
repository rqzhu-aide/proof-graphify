# Proof-check workflow defect tracker

Date: October 3, 2026. Status: WF-01 through WF-07 implemented and validated for this release. See the [implementation validation](proofcheck-v239-reliability-validation.md).

This is the maintained tracker for the workflow failures exposed by the RF-HTE 2.3.8 test. The [revision handoff](proofcheck-v238-reliability-handoff.md) defines implementation and closure tests. The specification is independent of agent, model, provider and host. Run names below identify evidence only.

Baseline: proof-check/core 2.3.8, maintained commit `73bd788544c927c70e3e616ee1a884032e650920`, core identity `f4fb59880bf943807e3cd37b0899b4e96ae60fdab47f3b8415b73ceb930adf27`. Graphify 3.1.15 is at `f619473b1d876c093474ea86ad1fa92ac8e315d0`. Capture the actual checkout and installed identities again before implementation; preserve intervening work.

## Evidence and attribution

The [programmer's summary](C:/Users/zrq/projects/skills/_testing-center/summary/issues-20261002-proofcheck-v2.3.8-rf-hte.md) and [harvested run](C:/Users/zrq/projects/skills/_testing-center/results/stat-proof-check@v2.3.8+rf-hte__20261002-212425) are original evidence. Read-only investigations are recorded in the [GLM audit](../../audit-reports/v238-rf-hte-2026-10-03/glm.md), [DS4 audit](../../audit-reports/v238-rf-hte-2026-10-03/ds4.md), [K3 audit](../../audit-reports/v238-rf-hte-2026-10-03/k3.md), [database facts](../../audit-reports/v238-rf-hte-2026-10-03/round-facts.json), and [delivery verification](../../audit-reports/v238-rf-hte-2026-10-03/delivery-facts.json). These local artifacts are not shipped with either skill. Regression fixtures must also run without those local paths.

All three frozen bundles validate and their HTML hashes match. None is a completed audit. The reports establish workflow behavior, not the correctness of the paper findings or a measured allocation of elapsed time. This round contains no Claude execution, and the Codex slot failed before audit startup.

Stage 1 did pass before each of DS4's three independent rounds. At the final revision it was blocked again. Five response records became accepted through mapping, although their historical submission receipts remain `needs_revision`; all 22 resulting independent checks were noncurrent at the end. Do not mistake historical intake state for current response state.

## Active defects

P1 means required for this reliability revision. P2 is a bounded instruction/interface correction included after the core changes. Every WF row is **validated** for its stated scope. The [validation record](proofcheck-v239-reliability-validation.md) contains final test counts, preserved cases, behavioral evidence, integration corrections and remaining limits.

| ID | Priority, state and defect | Confirmed consequence and attribution | Planned owner and closure evidence |
| --- | --- | --- | --- |
| WF-01 | P1, validated: readiness omits source-correspondence prerequisites | A ready graph had 55 uses with empty source references. Later mapping required grounding edits. This is a mismatch between Stage 1 readiness and the existing mapping contract. | `stages.py`, shared source resolution, `review.py`; handoff A. Missing grounding blocks routine dispatch with exact targets; correctly grounded routes pass without preassigning independent judgments. |
| WF-02 | P1, validated: source-link maintenance can invalidate too much evidence | Additions to `evidence_refs` changed proof/application/inference fingerprints, reopening earlier work without changes to the recorded formulas or conditions. Some invalidation is necessary; blanket reuse would be unsafe. | `bindings.py`, `proof_spans.py`, assessment and freshness tests; handoff B. A narrowly defined forward binding preserves already consumed evidence, while changed source, scope, route and unknown cases remain stale. Historical bindings retain their original meaning. |
| WF-03 | P1, validated: a stale explicit boundary becomes apparent whole-page work | Initial final-group registration invalidated all 13 earlier boundary selections. Coverage then requested text preceding a proof. Boundary uncertainty and missing examination are being conflated. | `proof_spans.py`, `assessment.py`, `work.py`; handoff A. Stale explicit selection produces boundary recovery, with no fabricated neighboring-text tasks and no coverage credit. |
| WF-04 | P1, validated: untouched scaffolds become accepted records and repeated work | All 62 draft checks in one run were blank. The helper ignored existing no-progress instructions, but intake accepted those rows and recommended preparing remaining work. | `controller.py`, generated assistance, tests; handoff C. Placeholder-only returns preserve intake without scientific writes; useful partial returns remain supported; receipts distinguish saved drafts from satisfied obligations. |
| WF-05 | P1, validated: successor writes can repeatedly renew historical ancestry | Bulk batches created 279 successors to already superseded predecessors. Normal renewal guidance already excludes these predecessors; broader write paths did not enforce that distinction. | New-write checks in `acceptance.py`/controller validation; handoff D. New ancestor branches are rejected with current candidates, legitimate draft completion works, and old branches remain readable. |
| WF-06 | P2, validated: compatibility preparation can silently bypass stage ordering | Global checks were prepared through the ordinary-looking old command before local review. Normal stage gates worked. The exception is described in prose but absent from the command contract. | `cli.py`, controller and stages; handoff D. Ordinary preparation shares stage policy; exceptional investigations explicitly record their bounded purpose and limitations. Saving and recovering old work stays available. |
| WF-07 | P2, validated: reviewer capability discovery is underspecified | A run inferred no independent context from no native subagent tool. The instructions mention separate sessions, but give no observable discovery procedure. This is an unsupported agent inference made easier by a definition gap. | `controller-workflow.md`, qualification guidance; handoff E. A host-neutral capability check distinguishes available, unavailable and unknown routes without requiring a particular tool or provider. |

## Contributing mistakes and secondary observations

| ID | Classification | Disposition |
| --- | --- | --- |
| C-01 | Mapping by rotating group order or the first matching supplier word violates the current exact-correspondence rule. One helper also mixed an old response ID with later-round judgments. | Cover in A/D recovery tests and concise generated guidance. Assistance may expose source-compatible candidates; it must not choose a mathematical correspondence automatically. |
| C-02 | Ten saved returns were normalized from anchor-reference objects to strings without a demonstrated reviewer correction trail. Verdicts and reasoning were unchanged. | Preserve original bytes and require an authored corrected response, with truthful continuity and a fresh request where required. Do not silently rewrite historical responses or add a general automatic response-repair engine. |
| O-01 | Formula diagnostics remain despite successful static acceptance: 35 occurrences in one report, including damaged escapes. These are occurrences, not 35 distinct defects. | Open secondary product issue. Include existing JSON-escaping/formula checks in behavioral acceptance and record remaining defects separately. Do not enlarge this revision into renderer replacement. |
| O-02 | One test slot failed provider/account model selection before running the skill. | Harness configuration issue, outside this skill revision. Future evaluation must verify its executable configuration before attributing results to the workflow. |

The rules against repeated unchanged work, guessed mapping and unnecessary redispatch already exist. Correcting their tool support should replace conflicting guidance, not add another warning document to every worker's reading load.

## Tracking and closure

Update each defect with implementation commit, focused tests, behavioral evidence and remaining limits. Use `open`, `implemented awaiting validation`, `validated`, or `deferred with reason`. Keep mitigations separate from full fixes, especially conservative recovery of old bindings under WF-02.

Close a P1 only after its positive and negative cases pass on the same frozen candidate. A lower record count, clean exit, accepted submission, passing renderer, or patch version is not closure evidence by itself. Retain immutable original artifacts; run continuations and repairs on disposable copies. Do not reopen completed unaffected mathematics merely to produce a new release receipt.
