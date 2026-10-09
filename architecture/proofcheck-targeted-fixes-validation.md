# Targeted proof-check fixes: implementation and validation

Implemented locally on 2026-09-27 from the [targeted handoff](proofcheck-targeted-fixes-handoff.md), against stat-paper-skills `14186a1` and Proof Graphify `8783e3f`. Automated verification is complete; live browser inspection remains unverified for the reason below. The maintained source and both generated shared-core bundles are updated. Patch versions were subsequently installed at the user's request, as recorded below. No commit or remote publication was performed during that implementation and installation step.

## What changed for users

1. **Earlier judgments remain available during continuation.** Renewal guidance includes the exact pinned outcome, reasoning, conditions, evidence and changed-input context. Reconciliation exposes both eligible opinions and distinguishes historical opinions. Presence of both reviewer roles does not supply an agreement decision. New scientific decisions remain unauthored.
2. **Prepared work is easier to submit and recover.** Each assignment has a stable initial request ID and a coordinator-only submission envelope template. Receipts list the files to give the worker. Saved packets and raw submissions can be recovered through inspection after an output or intake interruption, without preparing another assignment or rewriting the response. Changed attempts still require a fresh request ID.
3. **Accepted source requests replay their historical results.** Exact anchor and source-review retries return the accepted receipt even after later source changes. New requests still undergo the live checks, and current freshness remains a separate question. Source capture is unchanged.
4. **Incomplete audits produce a clearer handoff.** Status exposes existing coverage diagnostics. Empty preparation explains the existing blocker and points to status/work commands. Checkpoint receipts include the report's factual scope summary. Incomplete release stays refused, with a checkpoint action; failed multi-file delivery names the artifacts that exist without claiming delivery succeeded.
5. **The useful experimental maintenance fixes are retained.** Empty graphs render, distinctive damaged math escapes remain visible, legal whitespace in little-o notation renders, common-store backup/change export works, and blank-line source ranges survive refresh. Automatic TeX discovery stays within its documented roots, with explicitly registered external sources supported.

The independent-review instructions now show qualification, attachment, unchanged response submission, mapping and authored reconciliation in one continuation path. The existing incomplete probability example retains its limited status.

## What stayed intact

SQLite remains authoritative. The record schema, storage format, assessment and completion rules, reviewer qualification, source freshness, independent isolation, focused/full/triage meanings, legacy runtime and shared-core boundary are unchanged. There is no new wrapper, scheduler, manifest or automatic adjudicator.

The walkthrough used existing templates and explicit output paths successfully. The plan's conditional continuation-draft helper and default checkpoint path were therefore not added. These fixes reduce opportunities for administrative mistakes; they do not automatically detect every contradiction between an authored verdict and its reasoning.

## Automated verification

All Python commands used the existing user-wide Python 3.14 installation and shared packages. Node came from the existing machine-wide installation. No project environment or private runtime was created.

| Check | Result |
|---|---|
| Current core, excluding the separately exercised new lifecycle module | Initial broad run: 1,379 passed, 1 skipped, 532 subtests passed. Two older output assertions were updated for the intended additive fields/files; all 8 tests in their two focused classes then passed. No remaining failure. |
| New lifecycle regression | Passed; also executed once with durable output and 38 command receipts |
| Legacy proof-check and skill structure | 1,070 passed, 1 skipped, 976 subtests passed |
| Proof Graphify companion | 354 passed, 1 skipped, 176 subtests passed |
| Installer/package tests | 22 passed, 6 subtests passed |
| Both skill frontmatter validators | Passed |
| Shared-core bundle consistency | Passed: both 45-file bundles and wrappers match |
| Git whitespace/error checks | Passed in both repositories |

The full-suite logs preserve the initial results, including the two assertion failures; the final focused run is recorded separately below. The assertions now check the exact six delivered files, private envelope separation, retained publication diagnostics and incomplete-delivery details. Only tests changed after that broad core run. Initial failing cases were established for the repaired maintenance, little-o, source replay, continuation/recovery and CLI behavior before applying the relevant fixes. Existing completion and reviewer-isolation regressions remain part of the broad suite.

Final focused command, from `tests/new_format`, using the same global Python: `python -m unittest test_revision_interfaces.RevisionInterfacesTests test_publication.MissingRendererTests`. Result: `Ran 8 tests in 5.080s`, `OK`, exit 0. This result was captured in the agent's tool output; no separate log file was saved.

Logs and detailed receipts are under [the local evidence directory](../tmp/targeted-fixes-2026-09-27/). Before the subsequent patch-version bump, the bundle source identity was `eddbfd7878b87c28663d9a43fc322c9b663d7a2ea42804e801fc772077a05023`.

## Workflow and scientific checks

**Small complete workflow.** The [lifecycle summary](../tmp/targeted-fixes-2026-09-27/lifecycle/summary.json) records source intake, graph authoring, primary work, synthetic qualification, independent response intake, source-target mapping, explicit reconciliation, checkpoint and release. It exercises a real artifact-output failure and an injected processing interruption after durable submission intake. Recovery uses saved IDs and bytes. Three negative `gap` judgments survive the completed focused audit. The theorem remains explicitly excluded. The [incomplete report](../tmp/targeted-fixes-2026-09-27/lifecycle/incomplete.html) preserves unfinished review and refuses release. Qualification here is a software fixture, not evidence that a real reviewer qualified.

**Five harvested runs.** The [before/after comparison](../tmp/targeted-fixes-2026-09-27/harvested-comparison.md) used copies of the original databases. All 2,000 record versions, including 23 negative or conditioned check versions and their reasoning, were preserved. Existing status fields and all five projections were exactly equal; only the three newly exposed coverage fields were added to status. Case A stayed complete within its recorded scope; B through E stayed incomplete. Ten baseline/edited reports passed mechanical rendering checks. Original and copied database hashes were unchanged. This is compatibility evidence, not a new scientific audit of those papers.

**Fresh mathematical examination.** A fresh evaluator received the current scientific references and neutral source passages, without expected answers or implementation history. It identified a false written equality despite the true final result, accepted a correct control, and kept an unavailable cited theorem separate from a refuted theorem. Once given the cited proof, it checked the argument and resolved the mathematical source limitation. [First responses and evaluation](../tmp/targeted-fixes-2026-09-27/behavioral/evaluation.md) are preserved. The source arrived through a conversation continuation; the native database context-extension protocol was tested separately by regression tests. This bounded exercise does not establish an accuracy rate or count as a full paper audit.

**Browser limit.** Live inspection of the generated local HTML was blocked by the browser tool's file-URL policy. No alternate serving path was used to bypass that restriction. Renderer, geometry and interaction-related automated checks passed, but human-style browser inspection remains unverified.

## Follow-up: repository isolation and portable skill definitions

The maintained repositories were checked independently of the experimental copies. Their runtime wrappers, core loaders, bundle builder and installer have no path or fallback into the experimental folder. Both bundles still match the maintained shared source. A scan of 618 maintained files found no junctions, symbolic links or multiple hardlinks; 614 text files had no experimental-folder reference outside the historical handoff and validation notes. Archives, temporary test evidence, Git internals and caches were outside this runtime/package audit. The deliberately retained maintenance fixes are independent maintained changes, not dependencies on the experimental copies.

All five current skills and their instructional references were checked for named agents, models and host APIs. Proof-check invocation instructions now state the portable explicit-invocation policy, and legacy checking guidance assigns mathematical judgments to the calibrated checker rather than a named model tier. Graph image/browser guidance depends on the actual available tool and its permitted capabilities. The other three skill definitions already needed no changes. Host integration metadata and installer target settings remain outside the portable instructions; generic qualification and reviewer-configuration fields still record real provenance.

These follow-up changes affect instructions and one existing test assertion, not runtime behavior or schemas. All six skill-structure tests and all five skill validators passed; bundle consistency and both repository whitespace checks passed. No installation was changed.

## Patch versions and user-wide installation

At the user's request, `stat-proof-check` and shared core were bumped from `2.3.1` to `2.3.2`; Proof Graphify was bumped from `3.1.4` to `3.1.5`. Both core bundles were rebuilt from maintained source, with source identity `08381c8ecde443d4114dd6a40a593467e264d8f7b11d3d807d72c4ac051f2301`. Contract and storage versions are unchanged. Current version declarations and tests were updated; historical release statements remain historical.

The affected CLI, export, packaging, skill-structure and installer checks passed: 218 tests, 1 skipped, and 94 subtests. Proof Graphify's standalone-package checks passed: 3 tests and 2 subtests. Both skill validators passed.

Both updated skills were installed into `C:/Users/zrq/.agents/skills/` and `C:/Users/zrq/.claude/skills/`. Each previous installation was preserved under the corresponding `.agents/skill-backups/` or `.claude/skill-backups/` folder. The existing proof-check installer validated its staged and installed files; graph's one-time installation helper copied an explicit runtime payload and verified its hashes and bundled runtime before and after replacement. Its initial native-CLI probe used an unsupported isolated invocation and stopped before any graph replacement; the probe was corrected to the documented invocation, without changing runtime code.

Installations use the maintained repositories only. Development tests, temporary evidence, archives and Git data are excluded. Existing explicit-invocation settings were retained. Installation receipts and the independent final verification are saved in the local evidence directory.
