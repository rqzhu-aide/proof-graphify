# Targeted local recovery revision: implementation and validation

Date: October 2, 2026. The six targeted repairs and their bounded validation are complete in the working tree. Full RF-HTE completion and speed remain unverified.

## Implemented behavior

The [handoff](proofcheck-local-recovery-handoff.md) is implemented on top of the existing unreleased workflow revision. Pre-existing changes were preserved in the [baseline patch and file copies](../../audit-reports/local-recovery-implementation-2026-10-02/). No new workflow state, retry engine, dispatcher, storage migration or model-specific rule was added.

| Repair | Result |
| --- | --- |
| R1: Complete recovery facts | Mapping eligibility uses the full overlapping diagnostics before display limits are applied. Recovery actions report total counts and truncation. Bounded data passed back to the helper produces inspection advice rather than guessed eligibility. |
| R2: Conflicting packet identities | Controller and direct-review inspection name both identities and ask for the actual assignment to be established. Packet-dependent extension or renewal advice waits for that resolution. Missing or malformed identity still gets shape guidance. |
| R3: Historical rejection | Current inspection derives the original assignment's current obligations at one database revision. It exposes applicable evidence, outcomes, freshness and blockers. Completed adverse examinations remain completed work; drafts, disputes, stale evidence, changed scope and unusable independence remain explicit. Historical bytes and receipts are unchanged. |
| R4: Global proof context | Primary global assignments include selected registered proof passages, argument evidence and boundary-selected continuations. They do not collect every anchor in a supporting source review or expand the full inference history. Incompatible historical pins and oversize context produce explicit diagnostics. |
| R5: Conditional results | Normal scope guidance distinguishes a reusable conditional lemma from a fact local to a temporary proof premise, with paired examples. |
| R6: Navigation and recovery | Existing workflow guidance explains cursor snapshots, current obligations before historical repair, and the exceptional direct-primary route for a saved response missing context. It retains truthful authorship and the unchanged-blocker stopping rule. |

A final targeted review caught two additional branches within R2 and R3. An independent rebase validation failure could precede the pairing diagnostic; it now retains its original rejection semantics while giving neutral pairing advice. A write between inspection and assessment could mix revisions; the rejected-attempt view now reads both audit scope and derived work at its advertised revision. Regressions exercise both cases, including successful submission of the unchanged worker bytes after correcting only the envelope.

## Candidate and checks

The final maintained-core identity is `d9e892be6227c324ec00b004dd268ddf0f7d0f24c75949c7714de3c459b81f94`. Both generated packages contain the same 46 core files. Their manifest hash is `76a672696d2706b432bef9142a4de28ca61a2700742fad5721865bc0a961eb39`. [The candidate manifest](../../audit-reports/local-recovery-implementation-2026-10-02/candidate-final.json) records repository baselines, dirty files and runtime details.

Version labels remain proof-check/core 2.3.7 and Graphify 3.1.14. Commands, storage, record, packet and projection contracts remain unchanged. This is an implementation record, not a versioned release, installation, commit or push. Installed copies are not the candidate tested here.

All checks used the existing user-wide Python 3.14.7 and Node 24.20.0. Logs are in [the validation directory](../../audit-reports/local-recovery-implementation-2026-10-02/).

| Check | Result |
| --- | --- |
| Complete shared-core suite | 1,513 tests successful; one optional browser skip |
| Proof-check package suite | 1,071 tests successful; one optional browser skip |
| Graphify package suite | 381 tests successful; one optional browser skip |
| Installer suite on disposable targets | 22 passed |
| Final controller/adversarial regressions | 55 passed |
| Final independent context-extension regressions | 24 passed |
| Final package integrity and isolated execution | 54 tests successful; one optional browser skip |
| Final stitched recovery integration | 1 passed |
| Final bundle parity, skill frontmatter and whitespace checks | Passed |

The full suites began before the last two controller corrections. Only the affected controller, extension, packaging and stitched recovery checks were repeated after rebuilding the final candidate. The Graphify wrapper and overview behavior were not changed. Test counts above include repeated checks and are not a count of unique tests.

Expected negative-path diagnostics printed by the passing proof-check package suite are assertions of rejection behavior, not failed test cases.

New regressions exercise actual advertised mappings at `limit=1` and at 21 judgments, overlapping wrong-kind/scope/source blockers, a still-mappable judgment beside a blocked one, both mismatch directions and disjoint source context. Additional cases cover current adverse completion, partial/draft successors, input drift, disputes, independence, incomplete analysis, more than 100 work rows, and fresh listing after a write. Packet tests check selected supplementary anchors, exclusion of unrelated reviewed anchors, source/route changes, label-only edits, historical pins and unchanged independent privacy. The conditional-result regression tests application support and a genuinely inaccessible temporary premise separately.

## Preserved global cases

Five cases with unfinished global work were replayed on disposable database copies. Every revised packet included all selected boundary anchors checked by the replay and fitted the existing 1,048,576-byte maximum. All five original databases remained unchanged. [Saved replay results](../../audit-reports/local-recovery-implementation-2026-10-02/global-replay.json) contain hashes, preparation diagnostics, source sizes and selected evidence.

| Preserved case | Before repair, bytes | Revised bytes | Boundary anchors supplied |
| --- | ---: | ---: | ---: |
| Distributional RL 2.3.5, Codex | 104,863 | 188,805 | 2/2 |
| Distributional RL 2.3.5, GLM | 186,606 | 194,908 | 4/4 |
| RF-HTE 2.3.6, Claude | 776,885 | 803,055 | 25/25 |
| RF-HTE 2.3.6, GLM | 212,160 | 238,262 | 22/22 |
| RF-HTE 2.3.7, Claude | 507,987 | 530,093 | 23/23 |

All revised preparations explicitly exceeded the default 131,072-byte cap. The distributional-RL/Codex case previously fitted that cap; including the missing proof context adds 65,817 bytes of source excerpts. The existing `--max-bytes 1048576` retry actually succeeds for that case, so the repair has a demonstrated bounded recovery route without increasing the supported maximum or splitting its evidence. A default-cap failure's measured bytes are a lower bound, not a final packet size.

These replays establish preparation and evidence inclusion, not that an agent examined every passage or completed the mathematics. Old packets often omitted boundary records themselves, so their empty missing-boundary arrays are not evidence of old completeness.

## Bounded agent exercise and remaining limits

A fresh agent received only the shipped skill, the earlier small manuscript and a disposable copy of its saved audit. The assignment was to resume primary work, check the conditional-lemma application and displayed support, preserve scientific findings, and stop at a primary checkpoint. It did not receive this plan's expected answers. Independent review was explicitly outside this exercise.

The exercise began with core identity `1730e679fc4f9c9c8afd1d2493830a667f472b5057dfaf3636f9645a0ef79ead`. The agent was told when the final controller-only corrections changed the bundle to the final identity above. This disclosed transition means the exercise is not an uninterrupted fixed-candidate performance benchmark.

The agent identified the reusable lemma's erroneous placement inside a sibling hypothesis scope. At revision 27 it corrected the target's shared setup, retained the hypotheses in a local scope and explicitly discharged that scope. Revisions 28 and 29 recorded its source comparisons and renewed affected primary examinations with explicit predecessor pins. It preserved earlier authorship, the saved responses, coverage and all three original findings: the covariance gap, theorem refutation and literal `mu` notation defect.

At the revision-29 checkpoint, the lemma's application changed from `premise unavailable` to `available`. Structural validation and report rendering passed, with 23 of 29 current obligations satisfied. Six reopened obligations remain: global consistency, adversarial examination, two independent compositions and two reconciliations. The exercise intentionally stopped at this local primary checkpoint. It did not claim audit completion or treat the earlier independent reviews as current after a scientific representation change.

The [exercise report](../../audit-reports/local-recovery-implementation-2026-10-02/behavior/primary-continuation-report.md) records commands, receipts, source reasoning and the bundle transition. Its saved-output inventory verifies that all 15 known authored response/envelope pairs match retained intake hashes. The [continuation note](../../audit-reports/local-recovery-implementation-2026-10-02/behavior/proof-check-paper/CONTINUATION.md) identifies the six remaining obligations. One initial `--version` usage mistake was corrected to the documented `version` command without scientific redispatch.

Separate coordinator calls through the final packaged CLI confirmed revision 29, structural validity and `process_complete: false`; their outputs are saved as [status](../../audit-reports/local-recovery-implementation-2026-10-02/behavior-status-verified.json) and [validation](../../audit-reports/local-recovery-implementation-2026-10-02/behavior-validation-verified.json). [Hash verification](../../audit-reports/local-recovery-implementation-2026-10-02/behavior-verification.json) confirms the report matches its renderer receipt. The original saved audit remains unchanged at SHA-256 `a217d5b3ad37e9de5b5650fa634d43b48af6071df89ba680bb67775365a20c7f`. The manuscript remains unchanged at `430b688146345731f3e79b97baef2a2d1f1dabaa0cd65fd2a4db948664a0a356`. Browser policy blocked opening the local report, so renderer success and saved support data are verified, but visual browser inspection is not claimed.

A matched full RF-HTE run remains necessary to establish whole-paper completion or runtime improvement. No external Claude run was launched for this revision.
