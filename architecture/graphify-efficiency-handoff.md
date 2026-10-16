# Graphify efficiency revision handoff

Status: ready for implementation after independent validation, 2026-10-12. This is a revision plan, not an implemented release. Three Sol 6.1 xhigh reviewers independently assessed the draft, tested isolated prototypes, and confirmed the affected revisions in bounded follow-ups.

## Objective and scope

Remove demonstrated repeated transcription, unnecessary retrieval and repeated mechanical processing while preserving the current scientific comparison standard. Graphify continues to present selected results and their connections, not verify detailed proofs. No new review stage, per-paper checklist, fixed result quota, storage format, database authority, or model-specific instruction is introduced.

Implement five bounded skill changes (S1-S5) and one separately owned test-harness change (H1). H1 belongs to `_testing-center`; S1-S4 belong to Graphify; S5 belongs to the shared math renderer and ships in both skills. Proof Check's scientific workflow and source-only independent review must remain unchanged. Host timeout changes, general actor-behavior changes and historical-query redesign are outside this handoff.

The canonical repository is `C:/Users/zrq/projects/skills/stat-paper-skills/proof-graphify`. Paths below are relative to that root unless explicitly absolute. Graphify is currently 3.2.5; Proof Check and shared core are 3.2.4. HEAD is `e11bc293cd111e9f3d4f9c52af51a945956f0694`, with pre-existing uncommitted work. Preserve that work. No bump, installation, commit, push, live-run mutation or full-paper benchmark is authorized by this planning task.

Evidence and baseline are in [the audit](../../tmp/graphify-waste-audit-20261012/AUDIT.md). Completed examples: RF-HTE 3.2.3 and Fast-SDE 3.2.4. The current-version example is a frozen partial Fast-SDE 3.2.5 trace at 2026-10-13 01:27:12 UTC; its later completion and active work time were not established. Equal version labels do not establish equal bytes; record the actual candidate identity during implementation.

## Required invariants

- One authoritative database; stable item/use/anchor identities; full-record edits preserve intended fields and unselected detailed-audit content.
- Exact saved scientific wording still receives source comparison. Preserve complete formula reading, essential setup/quantifiers/conditions, correct consumers, and legitimate unresolved interpretations.
- Retain expected-snapshot rejection, transaction boundaries, history, observation-only revisions, source-byte validation, affected-comparison semantics and reviewed reuse rules.
- No scientific-record mutation solely to accommodate the two supported display-spacing forms. Unsupported notation remains visible with its existing limitation; mechanical display success never constitutes scientific approval.
- Existing completion receipts remain authoritative. No automatic rerun of successful writes, no extra validate after an unchanged successful render, and no static HTML scan presented as a browser test.

## H1. Make the testing launcher respect Graphify's review contract

**Owner:** `C:/Users/zrq/projects/skills/_testing-center/run-test.sh`, `write_reviewer_recipe` around lines 302-337 and `cmd_launch` around lines 368-433. This change is separately reviewable from the skill patch.

**Trigger and consequence:** ordinary Graphify launches currently receive a user-level instruction to run a fresh source-only reviewer using generated scaffolds. The recipe repeats this assignment. Recent agents construct a second independent map and custom scaffold machinery, then reconcile that map with the database. The latest trace read Graphify's optional-review guidance and still followed the injected assignment.

**Proposed edit:** keep same-model fresh-process transport, role prompt input, separate stdout/stderr and all existing CLI/provider isolation. Select a Graphify-specific prompt/recipe contract using the first skill token in this run's `test-id`, which main already writes before recipe creation. Both main and followup phases must use that run identity, not a mutable globally current skill. Branch only for recorded `proof-graphify`; preserve the present Proof Check and other skills' legacy contract. A valid older Graphify test-id selects the new Graphify contract for a newly generated followup; do not overwrite earlier prompts or recipes. Missing/empty/unparseable first skill token retains legacy behavior with a concise identity-limitation message, never a guess from `.current-skill`. The tested selector reads with `read -r recorded_skill _` and checks the complete first token against `^[A-Za-z][A-Za-z0-9_-]*$`; it does not add validation of the remaining version/slug/hash fields. An LF row containing only the exact token `proof-graphify` therefore selects Graphify. A CRLF single-token row retains a trailing carriage return and follows the stated legacy fallback; ordinary four-field CRLF rows keep their first token intact, and the current writer uses LF. A different well-formed skill token retains the legacy contract without inventing a skill registry. Do not infer an intentional source-only benchmark from an older automatically injected recipe.

For ordinary Graphify, the parent addition must say that the recipe is an available transport if the skill/user assignment calls for a reviewer; it must not create a new mandatory review stage. Keep the existing four-argument calling shape. Graphify usage/errors describe a clean working directory, role prompt file, bounded assignment file and new stdout path; the assignment file may be plain text, with no new schema. Replace its source-only/scaffold prompt injection with neutral path metadata: `printf -v prompt "%s\n\nBounded assignment file: %s\n" "$prompt" "$delivery"`. Merely reading the role file would accidentally drop argument 3. A single bounded Graphify assignment identifies saved targets, exact current records or packet, source root/resolved paths, native comparison format, response path and return channel. It does not hide the current record from its reviewer. The scientific assignment lives in the user assignment and skill/role prompt; the harness supplies execution capability.

The parent guidance should be short: “Optional same-model fresh reviewer launcher: PATH. If assigning a reviewer, pass a clean working directory, role prompt, bounded assignment file, and new stdout transcript path. Follow the user's assignment and the invoked skill's applicable review contract and response format. Preserve assigned snapshot identities. This launcher adds no review requirement. Original stdout and stderr are retained separately.” Include the argument meaning in recipe usage comments. No new Graphify review schema or general harness mode framework is needed.

If an explicitly requested benchmark requires independent source-only reconstruction, retain that instruction in its benchmark prompt and account for it as additional workload. Do not silently redefine such a benchmark as ordinary Graphify usage.

**Acceptance:** inspect/capture generated parent prompts and recipes for Graphify main and followup, Proof Check main and followup, and one unrelated skill. Use fake CLI executables in an isolated copied harness, with zero paid model calls. Confirm exact model/effort arguments still propagate; reviewer recipes always use fresh `build_args agent main` and never resume/share parent sessions; existing parent followup continuation stays unchanged. Parent DSH followup remains unsupported as today. Both output streams and exit codes remain; Graphify is optional and permits saved-record comparison; Proof Check behavior is unchanged. Simulate changed `.current-skill`, valid old test-id, missing/empty/malformed identity, and another recorded skill. Explicit source-only benchmark text must survive verbatim, without appended instructions negating that assignment. Preserve invalid/missing-input and duplicate-phase rejection. Do not launch/prep/harvest an active testing-center run.

## S1. Remove mandatory re-fetch during a local correction

**Owner:** `proof-graphify/references/authoring.md`, paragraph after the serializer example, around line 43.

Replace the paragraph's unconditional get instruction with:

> After initialization, correct the decoded field in the affected current full record and apply the edit as described in [database.md](database.md#apply-a-bounded-batch). Reuse exact current records and their expected snapshot already available; use the optional edit-template helper for editable records or get when current argument/source context is missing. Preserve all intended record fields and the inspected expected snapshot. Do not rebuild the database from an older seed to repair display text. Direct file-tool authoring remains valid. Diagnostics catch specific corruption patterns, not every escaping mistake; correct reported errors from the source without guessing the missing command.

Keep the detailed edit-template/get contract in database.md, not copied into SKILL.md. An old or incomplete packet is not an exact current full record. This permits reuse, not blind edits or automatic approval of affected incoming connections.

**Acceptance:** a short independent decision trial considers (a) an exact current full record already available, (b) missing source/argument context, and (c) an intervening scientific edit. Case (a) should not acquire another get solely as ritual; case (b) retrieves necessary context; case (c) preserves stale-input refusal and obtains the actual current record. Reuse existing edit-template stale/round-trip tests; do not add wording-match tests.

## S2. Obtain the revision baseline without a diagnostic report

**Owner:** `proof-graphify/references/revisions.md`, opening paragraph and command block, around lines 7-12.

Replace “First read ... using validate” with: “Record the known current database snapshot as OLD. If it is not available, obtain expected_snapshot from list. Then capture the revised manuscript and compare the two retained snapshots.” Show the list command separately and mark it conditional, followed by the unchanged refresh/changes commands. Do not display a mandatory list command in the main sequence when OLD is already known.

Keep validation for diagnosis and preserve later source-diff inspection, changes outside anchor ranges, source drift handling, unchanged-PDF cautions and explicit reviewed reuse. No change to snapshot calculation or refresh conflict enforcement.

**Acceptance:** decision trial with OLD in context versus absent; one refresh integration verifies a stale OLD is rejected without modifying the database. Inspect that list returns expected_snapshot for native and common databases. No performance claim beyond avoiding at most one unnecessary report call on revision entry. The completed initial-authoring runs did not expose this path.

## S3. Project and stage the current graph once

**Owner:** `proof-graphify/scripts/paper_database.py`, `_materialize_common` around lines 289-318.

Retain the initial current projection and selection used to identify profile/source root. For `history=False`, skip the revision loop, stage that current object once, and set current_snapshot from that store result. For `history=True`, traverse prior revisions in the same order as today, retaining selection checks, and stage the already projected current object exactly once as the final revision. Capture the maximum revision within the already-open transaction; do not drop earlier revisions because they have equal mathematical snapshot IDs. Keep snapshot serialization, observation accumulation, source blobs, metadata and transaction/cleanup behavior unchanged.

The minimal algorithm is: current projection; when history is requested, materialize qualifying revisions strictly before the captured maximum; then stage current once and write the pointer. This avoids a second projection of the maximum revision and its second staging. If maximum revision only changes observations or unrelated audit content, preserve the same current projection and all historical observations.

**Acceptance:** with current-mode list/get on a common store, instrument project/store calls and assert one current projection/staging while comparing semantic outputs to baseline. Add a history fixture with at least two observation-only revisions sharing a mathematical snapshot plus a later actual record/source edit. Compare current and old packets, observation IDs/order/status, historical selection and changes/reuse results to baseline. Verify reads leave source DB bytes/logical contents unchanged, and existing rollback/cleanup/stale-write tests still pass. Count assertions test the measured duplicated work; output/history equivalence is the correctness criterion.

Use existing `tests/new_format/test_sql_overview.py` and relevant `proof-graphify/tests/test_paper_database.py` coverage. Replay the audit's `database/probe.py` against its disposable completed Fast-SDE copy for corroboration, not a timing threshold. Broader changes-history filtering and `overview.update` conflict-check optimization are deferred.

## S4. Share PDF decoding within anchor construction

**Owners:** `proof-graphify/scripts/paper_database.py::_edit_data`, around line 676; `proof-graphify/scripts/paper_records.py::make_anchor`, around line 1378. Existing `_binding` already accepts a source cache.

Create one `_SourceContent` for each `_edit_data` batch and pass it through a backward-compatible, keyword-only optional internal `sources` parameter on make_anchor to _binding. Keep default standalone calls working. Do not cache across commands, source captures, transactions or mutable live files. Do not widen the patch to change update_inventory or skip final validation: the initial bounded implementation should reduce five construction readers plus validation from six to two for a one-PDF batch.

Source content is the captured manifest, never an unverified reread of the live file. Preserve the existing cache key `(sha256, content_base64)` and its hash verification on first decode; equal claimed digests with different bytes cannot borrow a prior successful check. Identical verified content may share decoding even when file IDs differ, while each anchor retains its own file binding. Non-anchor edits and malformed anchors must retain their existing behavior.

**Acceptance:** five anchor additions on distinct pages of one PDF cause one reader for construction plus the existing independent validation reader, producing identical anchors/excerpts/hashes/verification and normalized result. Add a two-PDF case with matching physical page numbers and different contents to expose cache cross-contamination; use multiple anchors per file if asserting a count reduction. Warm the cache before tampering with encoded bytes while retaining the old claimed hash. Invalid base64/hash, unknown file, invalid page and malformed locator retain their baseline outcomes and write atomicity. PDF parser failures are different: _binding can retain an unverified anchor and explicit inspection limitation, while full validation may reject previously checked anchors that no longer reproduce. Compare each specified fixture with baseline rather than imposing a new blanket failure rule for undecodable PDFs. Standalone make_anchor remains compatible. Replay the completed Fast-SDE five-page example in memory, without touching its retained or live database. Place relevant behavioral tests with existing paper-record/database source tests, avoiding a new test framework.

## S5. Keep harmless spacing repairs inside the renderer

**Owner:** maintained `shared/paper_core/math_render.py`, `_convert` and converter-only adapters around lines 413-450. Do not hand-edit either shipped paper_core copy.

Add a narrow converter-input normalization for exactly one negative thin-space token between the evidenced operators and their opening delimiters: unescaped `\Pr\!\left\{` and bare-token `O\!\left(`. Use a small scan of complete control-sequence tokens and individual bare characters. Permit only whitespace between the four matching tokens and remove only that single `\!` token. Avoid longer control names, escaped commands and an O immediately adjoining an identifier character. Protect the immediate argument of text-family, mbox/hbox and operatorname commands, including their optional star, nested braced argument or unbraced single token. Leave comment-bearing and uncertain syntax unchanged. This is bounded local recognition, not macro expansion or a general TeX parser.

Protect those arguments locally; do not skip the whole formula merely because it contains operatorname. The actual RF-HTE probability formula contains `\operatorname{diam}` inside the event, while the spacing to fix occurs outside that argument. A whole-formula bailout failed this retained example. A pure MathML-sibling normalization also loses some source-context distinctions and is not the proposed implementation. Do not globally strip `\!` or relax _safe_mathml's rejection of unsupported negative widths. Keep the existing independence-symbol adapter and HTML/MathML sanitization.

Only converter input changes. Original TeX remains the canonical record and MathML annotation. Statements, snapshot IDs, evidence, scientific comparisons and historical records must remain byte/semantically unchanged after rendering. Faithful unsupported overlap constructions must retain their explicit fallback. Ordinary operator spacing can be less tightly typeset, but must remain legible and mathematically equivalent.

**Acceptance:** positive inline/block cases from both exact full RF-HTE formulas extracted from the statements and retained in [retained-rf-hte-probes.json](../../tmp/graphify-efficiency-handoff-20261012/math/retained-rf-hte-probes.json), not only the shortened audit examples; whitespace variants; mixed supported and unsupported negative-spacing formulas; existing independence cases; escaped/text/control-name boundary cases; and a negative case where overlap builds a symbol. Assert original annotation and database snapshots/comparison states preserved. Existing escaping, malicious markup, script grouping, delimiter and unsupported-command regressions must continue passing. Build a small paired Graphify/Proof Check display fixture and visually inspect probability, big-O and independence notation plus labels and fallback. Structural MathML success alone is insufficient to claim browser display correctness. If browser access fails, record visual acceptance as outstanding rather than retrying unrelated tools or calling it passed.

Increment the internal `CONFIGURATION['adapter_version']` from 12 to 13 as part of the behavior change. This is renderer provenance, not a displayed skill/core release bump. Native Proof Check and Graphify producer identities already include the relevant adapter bytes, but legacy `stat-proof-check/scripts/proofcheck_release.py::renderer_identity` depends on facade files plus `proofcheck_math.renderer_info()`. That info would miss an adapter-bytes-only change. Extend the existing report-math tests to assert the legacy identity changes with the adapter configuration; retain native producer-identity and Graphify renderer-identity regressions. Do not add a new identity scheme or expose a private helper through a facade merely to test it.

Regenerate both bundles with `python tools/build_paper_core_bundles.py`, then verify `--check`. Run relevant `proof-graphify/tests/test_math_display.py`, `test_math_variants.py`, `stat-proof-check/tests/test_common_math_publication.py`, `test_report_math.py`, and bundle parity/packaging coverage once after the final renderer candidate. Both skills receive the same shared-renderer behavior; Proof Check instructions/controller/review remain unchanged. Preserve existing displayed version numbers during development; a later release decision must acknowledge changed core bytes rather than representing this as a Graphify-only code release.

## Implementation order and completion evidence

1. Record baseline identity and preserve pre-existing changes. Prepare scratch copies of completed artifacts; leave live tests, installations and results untouched.
2. H1 as its separate harness patch, and S1/S2 as two paragraph/example corrections. Validate the generated contracts and bounded decision cases.
3. S3/S4 as Graphify code changes, with observable-output equivalence and narrow performance-mechanism probes.
4. S5 as a separate shared-renderer patch, both generated bundles and its visual/semantic tests.
5. Review the integrated diff and run relevant existing suites once. Re-run only affected checks after a repair. Do not make full-paper model trials a release ritual for these small mechanisms.

The intended maintained-source diff is one harness file, two Graphify reference files, two Graphify Python files and one shared Python file, plus focused tests at their existing owners. Generated math-renderer copies and bundle manifests in both skills follow from the builder. Do not rewrite READMEs, entrypoint workflow instructions, database schema, revision engine, Proof Check controller or review protocol. The handoff itself and developer validation reports are maintenance artifacts, not paper-delivery requirements.

Run commands from the repository root with the existing global Python (here `C:/Users/zrq/AppData/Local/Python/pythoncore-3.14-64/python.exe`), `-E -X utf8 -B`, and temporary outputs under owned workspace scratch. Never create a project-local environment. Run different test lanes in separate processes so their `support` and bundled-core imports do not contaminate each other. The focused implementation check set is:

| Changed boundary | Existing test entry points to extend/run |
|---|---|
| Current projection, chronology and current/history equality | `python -B -m unittest discover -s tests/new_format -p test_sql_overview.py` |
| Full-record correction, source-cache batching and write failure behavior | `python -B -m unittest discover -s proof-graphify/tests -p test_paper_database.py`; the same command with `-p test_source_reuse.py` |
| Historical refresh/reuse touched by S3 | `python -B -m unittest discover -s proof-graphify/tests -p test_revision_workflow.py` |
| Shared formula conversion and Graphify identity | `python -B -m unittest discover -s proof-graphify/tests -p test_math_display.py`; separately `test_math_variants.py` and `test_renderer_identity.py` |
| Proof Check native and legacy math/publication identity | `python -B -m unittest discover -s stat-proof-check/tests -p test_common_math_publication.py`; separately `test_report_math.py` |
| Final two-bundle identity and standalone packages | `python -B tools/build_paper_core_bundles.py --check`; relevant `ShippedBundleTests` and `InstalledPackageTests` from `tests/new_format/test_packaging.py` |
| Harness review contract and transport | Adapt the retained scratch fake-CLI fixture to the final actual function bodies; invoke only copied harness state and fake executables. No real provider call, prep, live followup or harvest is required. |

Do not run all unrelated Proof Check audit suites just because the shared bundle was regenerated. Do not run a wording-matching test for S1/S2; use the accepted decision cases and existing storage tests. If an environment prevents access to a globally installed runtime, verify that runtime through approved normal access before reporting it missing. Preserve failures and limitations rather than converting skipped checks into passes.

Required handoff receipts after implementation: changed-file list; exact baseline/candidate identity; focused command outcomes; generated harness prompt/recipe samples; preservation results for historical observations, stale writes and source evidence; paired rendering artifact and actual visual-check status; one short account of remaining limitations. These are developer validation outputs, not requirements for every paper application.

Expected runtime burden: no additional model-facing step, record, source comparison, required retrieval or repeated render. H1 removes accidental second-map work when optional review is used. S1/S2 remove unnecessary calls; S3/S4 reduce mechanical processing; S5 can eliminate spacing-only corrections. Existing timings are not controlled before/after measurements and do not support a promised percentage or total minutes saved.

## Deferred and explicitly rejected changes

- Do not rename `#proof-selection`; the reader creates it dynamically.
- Do not add static-hook scans, an extra final validate, fixed reviewer deadlines, another proof audit, or a new completion certificate.
- Do not auto-approve unchanged-looking source context, strip all negative spacing, reinitialize repaired databases, deduplicate observation-only history, or skip writer conflict checks.
- Do not optimize every historical query, redesign the temporary compatibility bridge, change storage format, or rewrite proof-check orchestration as part of this patch.
- Host/tool timeouts, active-time telemetry and actors ignoring existing stopping guidance have separate owners. No credible saved-time estimate is available for them here.

## Independent validation record

Each reviewer read the full plan, with independent ownership of one technical area. Initial jobs were assigned a ten-minute limit; follow-ups were limited to five or six minutes. Reviewers used existing global runtimes and isolated scratch prototypes. No production source, installed skill, retained test run or running test was changed. The initial plan is preserved as [draft-1.md](../../tmp/graphify-efficiency-handoff-20261012/draft-1.md).

| Reviewer | Independent evidence | Revision and final disposition |
|---|---|---|
| `efficiency_handoff_contracts`, gpt-6.1-sol / xhigh | 131 fake-CLI assertions, nine legacy-contract/source-preservation checks, eight existing record tests, native/common stale-refresh trials; then 38 additional edge assertions | Clarified assignment-path transport, recorded first-token selection, unknown identity compatibility, explicit benchmark precedence and reviewer freshness versus parent continuation. H1/S1/S2 approved. [Initial review](../../tmp/graphify-efficiency-handoff-20261012/contracts/review.md), [final recheck](../../tmp/graphify-efficiency-handoff-20261012/contracts/final-recheck.md). |
| `efficiency_handoff_database`, gpt-6.1-sol / xhigh | Baseline/candidate current and historical equality on retained Fast-SDE and public-API fixtures; list/get projection/store counts 2 to 1; six PDF readers to two; seven selected SQL regressions; repaired affected probe has 17 passing checks | Clarified immutable cache key and parser limitations versus corrupt captures. Final two-PDF repeated-anchor probe changes readers 8 to 4 with exact records/bindings. Warm-cache tampering still fails. S3/S4 approved. [Initial review](../../tmp/graphify-efficiency-handoff-20261012/database/review.md), [final recheck](../../tmp/graphify-efficiency-handoff-20261012/database/final-recheck.md). |
| `efficiency_handoff_math`, gpt-6.1-sol / xhigh | 60 paired inline/block cases, both exact failing RF-HTE formulas, four sanitizer probes, 45 selected Graphify regressions and 20 Proof Check math regressions; then two added boundary probes | Rejected whole-formula operatorname exclusion and pure MathML-sibling repair; specified local protected arguments and internal adapter-version increment. Original formulas, records and comparison state preserved in synthetic fixture. S5 approved; final editorial clarification names formulas rather than whole prose statements. [Initial review](../../tmp/graphify-efficiency-handoff-20261012/math/review.md), [final recheck](../../tmp/graphify-efficiency-handoff-20261012/math/final-recheck.md). |

The database review's initial extended probe stopped on a baseline-invalid PDF fixture. That failed evidence is retained; the affected fixture was repaired in a separate follow-up and completed successfully. The harness follow-up corrected a scratch-only Bash quoting error before its 38-check successful run. These were prototype-fixture issues, not production defects. Do not sum overlapping existing tests into a claimed unique whole-system coverage count.

The plan is ready to hand off, with no unresolved design blocker in the reviewed scope. Prototype feasibility is not implementation acceptance. The final production candidate still needs the specified transaction/publication/cleanup checks, generated bundle identity verification, and actual paired browser display inspection. No whole-paper model timing trial or measured total-runtime reduction was performed. Keep those limits explicit instead of turning this plan's approval into a claim that future code is already validated.

The source-protection check compared 721 pre-existing repository files against the audit baseline and verified unchanged HEAD, with no changed existing files. See [scope-after.json](../../tmp/graphify-efficiency-handoff-20261012/scope-after.json). The only new maintained-repository artifact from this task is this handoff document; prototype code and validation reports remain in workspace scratch.
