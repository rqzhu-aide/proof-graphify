# Proof check workflow revision handoff

Status: planned, not implemented. Prepared on 2026-10-01 for the next implementation agent and the researcher maintaining these skills.

Revise the existing proof-check workflow so that mathematical examinations survive unrelated bookkeeping changes, independent reviews remain coherent, and PDF coverage follows the actual proof boundary. Preserve the useful recent rendering, source inspection, supplement matching, and recovery improvements. Completion must still mean that the required mathematical work, independent review, coverage, and reconciliation have actually been performed.

Implementation status, October 1: the targeted revision is implemented in proof-check/core 2.3.7 and Graphify 3.1.14. See [implementation and validation](proofcheck-workflow-revision-validation.md) for completed checks, installation evidence, and the live-test limitation. The fresh RF-HTE run was blocked by Claude's session limit before audit work began. This handoff remains the rationale and implementation scope; it is not evidence of end-to-end completion.

## Start here

1. Confirm the two repository heads and working trees. The baseline is `stat-proof-check` 2.3.6 at `b53a491` and Proof Graphify 3.1.13 at `2b855b0`, both using shared core 2.3.6. Preserve any subsequent user changes.
2. Read the confirmed causes and invariants below. Implement the freshness corrections before changing reviewer guidance or PDF boundary semantics, so failures remain attributable.
3. Reuse the supplied reproductions to expose the failures, then turn them into small maintained tests. Keep the harvested paper audits immutable and use disposable copies for recovery checks.
4. Complete each work package and its acceptance tests. Rebuild both generated bundles from maintained source. Finish with a real audit of the same paper and supplement before describing the full workflow as validated.

This is the proposed scope for the current request. The September 27 [targeted fixes handoff](proofcheck-targeted-fixes-handoff.md) and its validation record describe implemented baseline behavior; do not reapply that old patch. The [automatic workflow handoff](proofcheck-automatic-workflow-handoff.md) is a separate unimplemented proposal. Its wrapper, managed run layout, task store, and dispatch machinery are not dependencies of this revision.

## Workspace and ownership

| Location | Responsibility |
| --- | --- |
| `C:/Users/zrq/projects/skills/stat-paper-skills` | Outer workspace, not the maintained skills Git root |
| `C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills` | Maintained proof-check repository and shared core |
| `C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/shared/paper_core` | Edit database and workflow implementation here |
| `C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/stat-proof-check` | Proof-check instructions and generated skill package |
| `C:/Users/zrq/projects/skills/stat-paper-skills/proof-graphify` | Separate companion repository and Git history |
| `C:/Users/zrq/projects/skills/_testing-center` | Test harness and original run evidence, outside the maintained repositories |
| `C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports` | Local investigation artifacts, outside the maintained repositories |

Edit `shared/paper_core`, then generate both bundled copies. Never patch `stat-proof-check/scripts/paper_core` or `proof-graphify/scripts/paper_core` independently. Keep proof-check audit requirements out of graphify's selective source-map workflow.

Use existing machine-wide or user-wide runtimes and packages. The investigation used user-wide Python 3.14.7, with `python -X utf8 -B`; its resolved executable was `C:/Users/zrq/AppData/Local/Python/pythoncore-3.14-64/python.exe`. Node.js must be available through the shared PATH for renderer checks. Do not create a project environment or download a private tool copy. If a restricted terminal cannot access an existing installation, verify it through normal approved access before treating it as missing. Keep documentation concise and avoid long dash punctuation.

## Confirmed causes and limits of the evidence

The problematic run is [proof-check 2.3.6 on rf-hte](C:/Users/zrq/projects/skills/_testing-center/results/stat-proof-check@v2.3.6+rf-hte__20260930-200930). The supplied [issues summary](C:/Users/zrq/projects/skills/_testing-center/summary/issues-20261001-proofcheck-v2.3.6-rf-hte.md) is useful evidence of symptoms, but several of its causal claims were incorrect.

The latest successful Claude baseline is [proof-check 2.3.5 on distributional RL](C:/Users/zrq/projects/skills/_testing-center/results/stat-proof-check@v2.3.5+distributional-rl-main__20260929-195600). It has a release at revision 149 and 239 of 239 required obligations current. The current Claude database reached revision 144 with 321 of 365 current, but its working HTML remained at revision 7. None of the four harvested current-run databases contains a release. GLM's current run has 74 of 118 obligations current; the summary's claim of a complete audit is inaccurate.

| Claude measure | Previous 2.3.5 run | Current 2.3.6 run |
| --- | ---: | ---: |
| Captured source files | 1 | 2 |
| Item and part statements | 43 | 89 |
| Required obligations | 239 | 365 |
| Qualification records | 1 | 3 |
| Independent response records | 20 | 33 |
| Judgments within those responses | 20 | 170 |
| Accepted current response records | 20 | 16 |
| Coverage records | 29 | 142 |

The older responses contained one composition judgment each, with detailed mathematics in the reasoning. The current responses contain 35 composition, 89 derivation, and 46 application judgments. These are saved-record counts, not measures of mathematical correctness or active model time. Seventeen current response records still need revision. Initial submission receipts remain historical even when later mapping accepts a response.

The previous run excluded unavailable supplementary material and constructed substitute arguments for some missing proofs. The current run examined supplied supplement proofs. Both runs mapped independent reviews before later coverage authoring; do not explain the older success as coverage-first scheduling. The older run reached reconciliation, while the newer run did not. Different papers, available sources, and coordinator dispatch choices prevent a controlled performance attribution from these two runs alone.

Three defects are confirmed:

1. A qualification-only audit update rejects already prepared local primary source comparisons even when none of their mathematical inputs changed. Claude had four saved failures of this kind and 32 subsequently accepted replacement assignments. Do not report 32 failed submissions.
2. Adding coordinator coverage makes a mapped source-only independent composition stale even when its delivered source and setup are unchanged. The narrow reproduction changes only `coverage_in_argument`.
3. PDF anchors contain whole pages, and coverage requires the full anchor excerpt. A short proof can therefore require accounting for neighboring material, which agents sometimes misclassify as structural.

The two freshness failures reproduce in 2.3.5, 2.3.4, 2.3.1, and 2.0. Whole-page coverage also predates 2.3.6. The September 30 release did not change the relevant review, assessment, packet, or binding rules. New guidance may have influenced agent choices, but the evidence does not establish that it caused the increased fragmentation. Address the demonstrated mechanisms without discarding the useful updates.

Do not implement fixes for unconfirmed allegations. Qualification documentation already uses `record`; `--judgment` belongs to `review mapping-template`; pagination already returns `next_cursor`. K3's helper omitted coverage and findings before submission, rather than the core silently dropping them. The oversized timeout error came from the host shell tool. Ambiguous null-field wording and incomplete `get` help are real, small usability defects.

## Invariants to preserve

SQLite remains authoritative. Saved response bytes, initial opinions, source versions, and historical bindings remain unchanged. A software correction can change how current eligibility is assessed, but it must not rewrite an old examination or pretend that new material was reviewed.

Retain exact targets, actual hypotheses, source-only isolation, genuine calibration, source-grounded mapping, and exact-target reconciliation. Keep adverse findings, counterexamples, conditions, and disagreements visible through corrections. A completed negative audit is valid; missing work cannot be closed by changing its description or silently narrowing scope.

Changes to mathematical statements, applicable setup, source passages, required dependencies, or written routes must still reopen affected work. Coverage completeness remains a separate completion requirement even when a saved independent opinion remains current. A review of one route cannot certify another route that it did not examine.

Keep the current math rendering improvements, including sized norms and scripted fences, raw mathematical annotations, offline reports, source diagnostics, and supplement identity matching. The renderer must not repair scientific statements or create proof credit.

## Work package 1 Preserve examinations through bookkeeping changes

### Qualification changes and primary submissions

In `shared/paper_core/controller.py`, revise `_freshness` so that a qualification-only audit change is neutral for primary submissions whose task inputs do not consume that qualification. Cover local source comparisons, ordinary primary checks, and coverage or findings submissions with no result rows. The current exemption only covers certain global primary tasks.

Preserve task authorization, protocol and scope comparison, source freshness, `task_binding_changes`, auxiliary evidence validation, and immutable input provenance. Independent and reconciliation submissions retain their qualification requirements. Historical tasks explicitly bound to the full audit remain conservative unless their original provenance establishes that the changed field was irrelevant.

Recovery uses retained, unchanged worker output with a fresh submission request ID and any still-required current authorization. Reusing a failed request ID returns its historical failure. A rebase does not supply unexamined source material.

### Coverage changes and independent judgments

For an eligible source-only independent work response, omit coordinator `coverage` records, the `coverage_in_argument` relation, and its corresponding semantic membership from the saved judgment's mathematical freshness dependencies. Determine eligibility from the accepted response, actual exposure, immutable original work packet, and validated source/setup provenance. Preserve every other mathematical and mapping dependency.

Keep primary and supplied-route review behavior unchanged. Do not replace the whole independent binding with its neutral source binding: that could lose mapped dependency or route guards. Keep graph-structure changes conservative in this revision.

The implementation must filter by the `coverage` collection and `coverage_in_argument` relation, not by the facet name `coverage`. Proof-boundary certificates also use that facet and must remain protected. Preserve original source/anchor pins, exact statements, scopes, assumptions, group/use dependencies, proof boundaries, and original neutral-context checks.

Historical recovery needs the same narrow interpretation for old eligible checks. Do not rewrite stored bindings. Use one record-aware effective comparison consistently in `assessment.judgment_freshness`, `queries.validate_snapshot`, and `queries.changes`, with equivalent results in work planning and reports. Keep generic `binding_changes` strict for transaction and reuse validation. Do not trust a saved `neutral_setup_validated` marker alone, or relax records with missing original provenance.

Existing `review.map_response` rejects mapping a judgment to the same target again, and reuse validation rejects changed membership. Neither is an existing general recovery solution for this defect. The compatibility interpretation must recover coverage-only staleness without issuing replacement mathematical opinions.

### Acceptance tests

Use `test_neutral_audit_metadata.py`, `test_neutral_freshness.py`, `test_work_origin_bindings.py`, and the existing reconciliation tests. Add tests around behavior, not generated wording.

| Scenario | Required result |
| --- | --- |
| Only reviewer qualification changes before an unrelated primary submission | Saved mathematical output remains usable with valid current authorization |
| Protocol, scope, source, or consumed assumptions change | Affected submission is rejected or requires reexamination |
| Coverage is added, edited, or retired after eligible source-only mapping | Independent examination remains current |
| Required coverage is missing or invalid | Audit completion remains blocked |
| Statement, source passage, assumption, use, group conclusion, final group, proof boundary, or required route changes | Relevant existing freshness and completion guards remain effective |
| Supplied-route, compromised, unqualified, partially mapped, or unsupported historical review | No new eligibility is granted by this fix |
| Historical eligible check has only coverage drift | Status, validation, changes, planning, and report agree; stored history is unchanged |

Intentionally revise `test_work_origin_mapping_stales_when_coverage_span_changes` and `test_work_origin_mapping_stales_when_coverage_claim_changes`. They currently encode the undesirable behavior. Pair the revised expectation with assertions that invalid coverage still blocks completion. Preserve the tests for changed proof excerpts, mapping transaction conflicts, omitted historical setup, new written routes, and pending-response credit.

## Work package 2 Keep independent reviews coherent

Update the existing `references/independent-checker.md` and generated `_response_guidance` in `shared/paper_core/assistance.py` together. Adjust coordinator and mapping guidance only where needed to make the same rule clear.

A composition judgment should explain every substantive application, intermediate inference, case, scope transition, and final integration needed by its written route. Those steps need not each become an independent judgment record. Separate records remain appropriate for distinct conclusions or routes and for local outcomes that need independent treatment. Impose no numeric cap and never collapse different outcomes merely to reduce record counts.

This matches the current obligation model: independent composition is required for registered proof routes, while primary checking separately covers the required applications, derivations, cases, and scopes. Extra independent opinions create real mapping and reconciliation work. A coordinator must privately check that all required routes were actually reviewed; do not expose the primary graph or judgments to make source-only mapping easier.

Keep the existing mapping and correction mechanisms, with a short decision rule:

| Problem | Appropriate action |
| --- | --- |
| A genuine correspondence between reviewed source and an existing record | Map with a precise source-grounded rationale |
| Missing neutral source needed by the reviewer | Extend the assignment, then obtain the reviewer's examination of that material |
| Wrong judgment kind, incompatible combined targets, or a judgment outside actual assigned scope | Obtain a reviewer-authored correction with original bytes and actual continuity preserved |
| Correctly identified inference absent from the graph | Refine the graph from source, retaining the mathematical discovery |
| Concern outside the assigned conclusion | Record it in the coverage note; if it undermines the assigned conclusion, reflect that in its reasoning and outcome too |

Do not invent graph nodes solely to accept a response, remove a legitimate refinement to restore freshness, or discard a troublesome counterexample. A corrected response must preserve unresolved substantive concerns in its reasoning and the saved finding or unresolved issue. Relevant accepted extra opinions still require reconciliation.

Keep the current whole-response acceptance policy for this revision. One pending extra can block that response, so prevention and the existing correction path both matter. Adding partial-acceptance states or automatic dismissal of judgments is outside this plan.

Validate with a meaningful multi-step route, multiple required routes, a distinct local defect, and an incorrectly targeted extra judgment. The model must produce full reasoning without obligatory row-per-step fragmentation, and correction must not erase adverse mathematics. Do not use a lower row count alone as evidence of a better audit.

## Work package 3 Make PDF coverage follow a reviewed proof boundary

Keep full PDF page anchors, source bytes, surrounding context, and visual formula inspection. Add an optional selection of actual proof spans, measured in half-open character offsets `[start_offset, end_offset)` against the stored anchor excerpt. These are character offsets, not byte offsets or PDF coordinates. Permit multiple spans where the source reading order requires them.

The preferred minimal extension places these selections in immutable accepted `source_reviews` evidence for `purpose: proof_boundary`; `proof_boundaries` already pins that review. Associate each selection unambiguously with the relevant argument and pinned anchor version. If the final design stores selectors on `proof_boundaries` instead, the immutable source review must certify those exact selectors. A review that merely pins a full page cannot certify a later edited selection.

Resolve coverage requirements through those certified spans. `assessment.py` also creates requirements from argument evidence and item proof passages, so changing the boundary record alone is insufficient. These sources must resolve through the same reviewed selection. Calculate uncovered intervals within the required union, retaining argument ownership and all responsible primary-check requirements. Neighboring unrelated text outside that union needs no artificial structural row.

Missing, unresolved, or stale boundaries still block complete coverage. Never infer the proof boundary from the intervals already checked. Visually confirm the complete written proof, including continuations and disjoint passages. Ambiguous extraction remains a stated source limitation, not a reason to certify a convenient subset.

Omitted selectors retain the current whole-anchor meaning. Do not rewrite historical boundaries or source reviews. Validate nonempty, in-range selections against their pinned source evidence and ensure every required boundary anchor is represented. A changed selection requires new review evidence. Include selection semantics in relevant source/setup and boundary freshness checks, packet delivery where needed, and diagnostics.

Use the existing required-feature compatibility mechanism on the first span-aware write, so an older core rejects unsupported semantics rather than silently ignoring them. Decide the smallest necessary contract/feature changes during implementation and document them. A storage-format migration is not assumed; if one is necessary, add explicit tested migration and backup handling before using the new semantics.

Tests must include two unrelated proofs on one page, a proof continuing onto another page, disjoint spans, invalid offsets, a missing continuation, changed source versions, altered selectors with an old review, and unchanged legacy records. Preserve the regression that checking only a prefix cannot certify the full reviewed proof. Verify that graphify can still display full page evidence and preserve audit extensions during supported overview edits.

## Work package 4 Clarify existing dispatch and recovery guidance

Surface reviewer configuration planning before dispatch: qualify the actual available profile once and reuse that calibration across fresh contexts while model, effort, tools, and isolation remain unchanged. A genuine configuration change still requires a new calibration. Preserve verified isolation and honest exposure declarations. Do not mandate one provider-specific isolation technique or repeatedly change profiles merely to satisfy a cosmetic preference.

Retain the early working report, meaningful checkpoint, and unfinished-work handoff rules. On resume, inspect authoritative database state and preserved worker outputs before redispatch. At a stopping boundary, render a current checkpoint when possible; if rendering fails, identify retained HTML as old and link the saved work. Do not introduce rendering after every record or a new checkpoint scheduler.

Make the primary/reconcile envelope error state that `qualification_id` and `exposure` **must be null**. Make `get` help explicit about supported packet-root collections and obtaining an owning item or part for other records. Clarify that `--judgment` selects rows for `review mapping-template`. Preserve working pagination and generated schemas rather than adding aliases for guessed commands.

Use the existing commands and generated artifacts. A new workflow wrapper, autonomous dispatcher, generic recovery state machine, extra calibration framework, or provider quota manager would expand this revision beyond the demonstrated need.

## Validation and completion of the revision

### Deterministic checks

First reproduce the two current failures and verify their paired preservation and invalidation tests after each change. Use synthetic fixtures in maintained tests; local real-paper artifacts are diagnostic evidence, not portable test dependencies or genuine calibration evidence.

Replay relevant saved operations on disposable copies of the rf-hte database, especially qualification-only rejection and coverage-only stale independent checks. Compare current judgments, findings, provenance, and remaining work. Real changes in mathematics must remain unresolved. A mechanical replay cannot count as a fresh mathematical audit.

Use the completed 2.3.5 database for backward-compatibility checks, preserving its recorded scope and limitations. Its release is not evidence that supplied rf-hte supplement proofs were examined. Hash original harvested databases before and after investigation and keep them unchanged.

Rebuild both generated bundles before packaging-sensitive integration tests, using the commands under Packaging and eventual release. The supported test lanes below run from the nested maintained repository and use the existing shared Python installation:

```powershell
Set-Location 'C:\Users\zrq\projects\skills\stat-paper-skills\stat-paper-skills'
python -X utf8 -B -m unittest discover -s tests/new_format
python -X utf8 -B -m unittest discover -s tools -p test_install_proofcheck.py
python -X utf8 -B -m unittest discover -s ../proof-graphify/tests
```

The separate legacy lane is `python -X utf8 -B -m unittest discover -s stat-proof-check/tests`; select it when legacy entrypoints or shared behavior affecting them changes. It is not an automatic prerequisite for a documentation-only correction. Run relevant focused tests during development, then the necessary broader lanes after integration. Distinguish completed tests, skips, failures, and interrupted suites. An unavailable-renderer skip is not browser validation. The previous large test pass did not establish real-paper completion. Avoid repeating unchanged suites without a new reason.

### Trustworthy live evidence

Before a new live comparison, make a separate, narrow harness change in `_testing-center`: preserve the participant inventory across follow-ups and harvests, and give each phase its own logs and exit record. Report elapsed time separately from measured active execution time, leaving active time unknown where it cannot be recovered. The current continuation logs overwrite earlier phases, so their elapsed intervals cannot be treated as model working time.

Verify this with a fixture that launches several slots, continues one, and then harvests every original slot exactly once with all phase logs preserved. Status and waiting must refer to the appropriate active phase rather than stale process identifiers. Harmless fixture processes are sufficient for this harness check; it does not require another model audit.

Use the existing runner and an actual fresh audit of the same rf-hte paper and supplement with the same scope and recorded reviewer configuration. Keep the full written-proof task. Do not remove difficult targets, omit the supplied supplement, replace written proofs with invented successful routes, or relax independence to obtain a completed result. Use explicit separate targets/routes for legitimate proposed repairs.

Inspect the actual responses and final state. Record qualification changes, redispatch reasons, mapping corrections, required/current obligations, accepted/pending responses, coverage, reconciliation, and report revision. Counts support diagnosis; no arbitrary judgment-count or duration threshold proves success.

The demonstrated bookkeeping cases should cause zero unnecessary mathematical redispatches. A complete run must reach actual process completion with the required scope, independent review, coverage, and reconciliation, while preserving gaps or refutations. Also exercise one interruption/resume case: saved work must be reused and the handoff must identify the current report or its absence. A quota stop is an incomplete observation, not a passed completion test.

Inspect the produced HTML in a browser for mathematics, source links, navigation, current revision, and honest incomplete/completed status. Exercise graphify's source-map creation, edit, render, and export paths with the regenerated core.

## Packaging and eventual release

Build both bundled cores from the maintained repository, then check the result:

```powershell
Set-Location 'C:\Users\zrq\projects\skills\stat-paper-skills\stat-paper-skills'
python -X utf8 -B tools/build_paper_core_bundles.py
python -X utf8 -B tools/build_paper_core_bundles.py --check
```

After the implementation and validation are complete, choose consistent next package/core versions and update maintained metadata and generated manifests through the established process. Keep each repository's changes and history separate. Record any validation that remains incomplete instead of describing the workflow as fully verified.

For a later authorized installation, the maintained proof-check upgrade command is:

```powershell
python -X utf8 -B tools/install_proofcheck.py --source stat-proof-check --user-root C:/Users/zrq --upgrade --target agents --target claude
```

This command writes user-wide installations and is not part of writing this handoff. Preserve existing Claude configuration and the proof-check explicit-invocation policy. Verify both installed targets in fresh processes.

Proof Graphify has no maintained installer equivalent. The local September 30 `install_graphify_release.py` is a one-off script pinned to graphify 3.1.13, core 2.3.6, and that release's file inventory. Do not rerun it as a future-version installer. Inspect the actual next package, preserve a recoverable backup, copy the intended runtime package to the user-wide `.agents` and `.claude` skill roots, and independently verify identities and create/render/export behavior. Avoid introducing a general installer project merely for this revision.

Installation, commits, and pushes follow the user's applicable instructions for the implementation task. The earlier September 30 installation and pushes are already complete and must not be mistaken for publication of this proposed revision.

## Evidence for the next agent

These local artifacts are outside the Git repositories. Keep necessary portable regression tests self-contained. If the handoff is moved to another machine, transfer relevant diagnostic artifacts explicitly rather than assuming their paths exist.

| Evidence | Purpose |
| --- | --- |
| [Run change attribution](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/run-change-attribution.json) | Version comparison, recorded counts, dispatch differences, and causal limits |
| [Current freshness reproduction](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/neutral-freshness-repro.json) | Both demonstrated failures in 2.3.6 |
| [Reproduction script](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/repro_neutral_freshness.py) | Existing synthetic fixture operations to adapt into tests |
| [Historical replay results](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/freshness-history-replays.json) | Same failures reproduced in earlier releases |
| [Historical causal timeline](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/freshness-coverage-history.md) | Commit attribution and whole-page coverage history |
| [Claude final database assessment](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/claude-final-state.json) | Revision 144, 321/365 obligations, current response states, and unchanged database hash |
| [Claude workflow excerpts](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/claude-workflow-excerpts.json) | Qualification changes, repeated preparation, and independent redispatch |
| [CLI and workflow classifications](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/diagnosis-2026-10-01/workflow-cli-findings.json) | Confirmed usability problems and corrected allegations |
| [Baseline database comparisons](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/validation-2026-10-01/proofcheck-baselines.json) | Earlier outcomes, recorded scope, and publication state |
| [Claude review sequencing](C:/Users/zrq/projects/skills/stat-paper-skills/audit-reports/validation-2026-10-01/proofcheck-claude-review-sequencing.json) | Judgment granularity and ordering in both runs |

Useful implementation entrypoints are `controller._freshness`, `bindings.compute_bindings`, `_Builder.argument`, `assessment.judgment_freshness`, coverage and boundary assessment, `queries.validate_snapshot`, `queries.changes`, `assistance._response_guidance`, record validation, and packet source/setup selection. Inspect their current callers before editing. Extend existing focused tests rather than introducing a parallel test framework.

## What the implementer should hand back

Provide the focused changes and why they remove repeated work, evidence that true mathematical changes still reopen review, compatibility results on both captured audits, and actual live-run completion or its precise blocker. Include package/core identities, bundle checks, browser verification, and any later installation or publication receipts. Distinguish implemented behavior, tested behavior, and remaining uncertainty. Do not close this revision solely on passing unit tests or on a model's narrative claim that its audit finished.
