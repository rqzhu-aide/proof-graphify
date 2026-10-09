# Shared core and scientific reader: programmer handoff

Status: implemented in the source checkouts, 9 October 2026. See the [implementation and validation report](shared-core-reader-implementation-20261009.md). Browser verification remains unavailable and installation has not occurred. This document preserves the approved implementation specification and supersedes the exploratory plan in `../../tmp/shared-core-plan-20261009/plan.md`.

## Result and boundaries

Both skills must ship the same maintained core, mathematical display implementation, and common reader components. Graphify presents selected source-backed statements and arguments. Proof Check additionally examines reasoning, commissions independent review when required, and integrates findings. Sharing code never gives an overview proof-review credit.

Keep storage format 4, record contract 4, existing collections, and the current scientific workflows. Preserve source snapshots, immutable history, publication rollback, and the separation between completed work and favorable mathematical outcome. No schema replacement, automatic overview-to-audit promotion, model launcher, new scientific requirement, framework, or runtime import from the sibling skill belongs in this change. A new audit remains an explicit manuscript-based task with its own scope and output database.

The reader foregrounds statements, assumptions, argument ideas, contributions and source passages. Audit mode adds reasoning, findings and coverage. Opaque IDs, worker envelopes and build/task tracking remain in saved data or secondary diagnostics. Missing optional prose creates no new authoring requirement.

## Source baseline and ownership

Paths below use `S` for the `stat-paper-skills` repository and `G` for its sibling `proof-graphify` repository. They currently sit under `C:/Users/zrq/projects/skills/stat-paper-skills/`.

| Input | Baseline |
|---|---|
| S HEAD | `fe2b9d83d3cf7f44dae8574139e4f27170b6a17c` |
| G HEAD | `92fe3cae81b554cb0f24cb28d01fde8facfb0ab8` |
| Formal audit source | `S/stat-proof-check/scripts/paper_core`, core 3.0.11, manifest source identity `ef5baf61c0a7c91a95dbc979f050574d3c0bb7aae0ff06da647dfaee57f90b5e` |
| Current Graphify core | `S/shared/paper_core`, bundled in G as 2.3.10, identity `94a3f0f09d76a5793dd4e3f719c27587c94695f93b30233186aa5d5268ec1f4b` |

Both worktrees contain uncommitted changes. HEAD alone does not contain the current Graphify 3.1.21 improvements. Preserve the actual working-tree inputs, including math adapter 10, mathematical-alphabet handling, source-comparison fixes, staging and publication recovery. Do not reset either checkout or substitute a tagged copy. If these identities have changed, reconcile that specific delta before implementing.

Make `S/shared/paper_core/` the only maintained runtime source. Seed it from the formal 3.0.11 core, then port the specified Graphify math changes and compatibility/reader changes below. Do not transplant the old audit scheduling, calibration or per-record review policy from the legacy shared tree.

Use a new common-core minor release, `CORE_VERSION = 3.1.0`, for the merged implementation. This is independent of database protocol and skill version. Graphify 3.2.0 and Proof Check 3.1.0 are now implemented in the source checkouts; installation remains separate.

Proof Check's `tools/install_proofcheck.py` and `stat-proof-check/tests/test_skill_structure.py` currently require its skill version and README release row to match the core version. Preserve that relationship for this release; Graphify retains its independent skill version. Update the current release documentation and append new validation evidence without rewriting historical `VALIDATION.md` results.

## Work package A: shared bundles

Change `S/tools/build_paper_core_bundles.py` to generate both `S/stat-proof-check/scripts/paper_core/` and `G/scripts/paper_core/` from the canonical source. Default build/check covers both; `--package` continues to select one. Success requires exact source-file and manifest equality, excluding caches as today. Workflow wrappers may differ and must not be part of the identical-core predicate.

Update `S/tools/test_bundle_targets.py`, which currently deliberately rejects Proof Check. Retain `S/stat-proof-check/scripts/build_manifest.py --check` as installed-bundle verification; its mutating invocation must refuse with the canonical builder command. Update its callers and source-ownership claims in S README, `stat-proof-check/IMPLEMENTATION.md`, both architecture documents and the builder docstring. Generated bundles are never hand-maintained. Core equality must not mask a missing product entrypoint: separately require G `paper_database.py`, `proof_overview.py`, `render.mjs`, and Proof Check `paper_audit.py`.

In `paper_core/bundle.py`, retain `protocol_version` as the default audit protocol and add `write_protocols` describing the two scopes from package B: `audit` has only `coherent-proof-audit/1`; `overview` has the three explicit supported protocols. Derive validation and manifest declarations from the same constants, and include this declaration in manifest verification. This is a runtime capability declaration, not an extra database protocol marker.

Keep runtime assets, including shared reader CSS/JS and Archify assets, inside the canonical core so they participate in the manifest. Each skill must operate with only its own installed files. Existing Graphify assets may be removed only after all callers use the bundled common assets; preserve licenses. No source-tree dependency may remain in an installed entrypoint.

Update G `tests/test_cycle_graph.py` and `tests/test_reader_layout.py` to read the template actually consumed from the bundle. If top-level assets remain for compatibility, generate them from the canonical assets rather than maintaining another copy.

Acceptance: both generated cores and manifests match exactly; changing a shared file makes verification fail in either package; both packages work without the sibling checkout or developer `PYTHONPATH`. Distinct wrappers are accepted.

## Work package B: overview operations on the common database

### API and protocol contract

Extend existing APIs, retaining their current audit defaults:

```python
initialize(path, *, source_root, title, allow_missing_source_root=False,
           workflow="audit")
Database(path, *, write=False, write_scope="audit")
```

Valid values are `audit` and `overview`; reject unknown values before filesystem mutation. `workflow="overview"` initializes `protocol_version="paper-overview/1"`; audit initialization keeps `coherent-proof-audit/1`. Use one protocol field, not a second overview-protocol marker. Retain the selection's existing `authoring_profile` as a separate focused/compatibility authoring constraint. Overview initialization must not require `coherent-examinations/1`; the shared runtime still supports that feature for audit stores.

Keep current format, contract, feature, generation and transaction checks. Apply this write matrix:

| Store | Overview writes | Ordinary audit writes |
|---|---|---|
| Format 4, `item-audit/1` | Allowed within the overview boundary | Rejected |
| Format 4, `paper-overview/1` | Allowed within the overview boundary | Rejected |
| Format 4, `coherent-proof-audit/1` | Allowed within the overview boundary | Current v3 policy |
| Unknown protocol, feature or incompatible contract | Rejected | Rejected |
| Common format 2/3 | Existing read-only handling; no new write path | Existing compatibility handling |
| Native `archify-paper-database-1`, schema 3 | Existing native Graphify dispatcher | Not an audit store |

Keep existing read compatibility; common formats 2/3 with contract 3 remain readable but unwritable. This table grants no new legacy audit migration. A stored audit record's historical protocol is distinct from the database metadata protocol. Never rewrite old protocol labels merely to open the store. Recheck compatibility and generation inside `BEGIN IMMEDIATE` and transactional acceptance. A common store without an overview selection does not acquire one merely from read or render.

Targets: `storage._validate_metadata`, `Database`, `initialize`; `G/scripts/paper_database.py` `_init_common` and `_common_dispatch`; `acceptance.accept_in_transaction`; `overview.update` and build-receipt writing.

### Exact overview boundary

Use the current before/after selected overview projection and snapshot checks to derive updates. Changes must concern selected or explicitly newly selected records, their source evidence, selection metadata, and corresponding paper overview fields. Do not expose arbitrary record replacement merely because a collection appears in a whitelist. Check normalized planned edits at transactional acceptance, after application-field normalization, so a normalized `application_details` write cannot evade this boundary.

Reuse `command="overview"` and current structural validation, with this field contract:

| Record | Ordinary overview edits |
|---|---|
| `papers` | Replace the existing paper's `title`, `main_items`, `scope`, `exclusions`; `source_root` only through explicit source refresh, which may persist an explicitly supplied relocated manuscript root. No second paper. |
| `sources` | Create selected captured sources with the existing full contract. Refresh `path`, `media_type`, `blob_sha256`; preserve existing `paper_id`, `capture_method`, `limitation`, old versions and blobs. |
| `anchors` | Create/replace selected source evidence using `source_id`, `source_version`, `locator`, `excerpt`, `excerpt_sha256`, `method`, `limitation`; keep captured-source and version/hash checks. |
| `items` | Selected/newly selected `kind`, `label`, `caption`, `statement`, `passages`, `aliases`, `uncertainty`, `owner_id`, optional `proof_idea`. Omission may remove `proof_idea` as today. |
| `uses` | Selected/newly selected `from`, `to`, `type`, `reason`, `regime`, `uncertainty`, `evidence_refs`. Endpoints remain selected items; preserve separate applications. |
| `overview_selections` | Default selection through `selection_body`, preserving paper identity and authoring profile. Ordinary edits cannot switch `focused` to `compatibility`. |
| `observations` | Create source comparisons only, with overview context, actual selection ID, selected item/use target and existing native input snapshot. Prior observations are immutable. |

Deselecting a record retains its stored identity and history. Preserve legitimate retained `owner_id` and native groups in selection `native_context.groups`; ordinary overview updates do not mutate canonical `groups` or `application_details`. Focused mode keeps its current rejection of newly authored proof-step records and formal groups. Canonical application contradictions still fail existing linked-state validation.

Preserve fields outside that overview ownership, including existing item `origin` and `scope_id`, paper `report_paths`, application details, audit targets and review bindings. New selected source items retain the current defaults: `origin="source"` and `scope_id=null`. Never change checks, findings, responses, reconciliations, audits, qualifications or audit-only extensions through the overview route. Validate field differences at the existing acceptance boundary; no generic permission framework or SQL sandbox is required.

Only immutable `overview_build:<digest>` receipts may be written through a dedicated overview receipt helper. Derive the key from canonical receipt bytes; identical writes are idempotent and different bytes cannot replace an existing receipt. Keep the writer transaction and actual input snapshot/source status. Preserve successful HTML delivery with `build_recorded=false` and an explicit error if that later write fails. Other commands and protocol/feature metadata changes remain unavailable in overview scope. Low-level SQL is not a supported skill interface.

Historical preservation and current support are different assertions. Retain old review rows and binding bytes exactly while the normal acceptance path appends versions, references and facets. Subsequent assessment/publication must withdraw current support after a change to consumed hypotheses, passages or source bytes, using existing `refs.facet_digests`, bindings and `assessment.judgment_freshness`. Preserve existing protocol-specific freshness classifications. Changed target meaning is historical; changed inputs require renewed attention. A coherent examination can become `historical` when its bound whole proof unit changes, while a historical source-only check can become `needs_review`. Both withdraw current support; this integration does not change the audit engine merely to standardize those labels. Presentation-only edits need not reopen mathematical support whose consumed inputs are unchanged. Do not grant historical checks coherent-review credit or invalidate unrelated science. Graphify must not invoke the audit assessor or commission reviewers to make these edits.

### Native overview maintenance

Retain `migrate_overview` in `export_import.py` as an explicit backed-up, transactional operation. Change its temporary initializer and private import writer together: an ordinary audit writer rejects the new overview identity, while an ordinary overview writer correctly rejects `command="import"`.

The private import replaces the initialized paper and creates imported sources, anchors, items, uses, observations and selection. Its extra write set is provenance groups with null argument/scope, native-required draft `application_details`, needed `source_issues`, `identity_maps`, source/legacy-export blobs, and metadata `legacy_overview_format`, `legacy_overview_current_snapshot`, `legacy_overview_snapshot_ids`, `legacy_overview_backup`. Reuse `_overview_edits`, `_finish_import`, ID mapping and existing import validation. These permissions belong only to this operation on its fresh temporary store, not ordinary overview writes. No audit/review credit is created.

Retain the reserved writer lock before backup, explicit backup destination, foreign-key validation, cutover, rollback, busy/WAL handling and repeated-migration refusal. Preserve the current projection, captured bytes, root and comparison chronology subject to existing ID remapping and import limits. Historical native snapshots/build rows remain in the backup; do not imply all are imported. Keep `import_legacy` audit semantics separate.

## Work package C: one math implementation

Canonical API: `paper_core.math_render.render_text(text, diagnostics=None) -> str`. Merge the current Graphify math adapter and move its mathematical-alphabet normalization into that common path. Preserve original TeX annotations, accessible source labels, operators and prose. Apply normalization once. Private converter helpers may remain private; do not create a second rendering policy in a facade.

Callers: G `scripts/overview_math.py`, core `publish.py`, and S `stat-proof-check/scripts/proofcheck_math.py`. The facades delegate while preserving existing call signatures and converter-provenance reporting. For identical input text and configuration, both products must produce identical MathML or literal fallback. This does not require algebraically equivalent but differently written formulas to have identical markup.

Keep the existing field coverage:

- Graphify: statement, proof idea, connection reason, regime, issue, comparison note, and its existing scope-display path.
- Audit: `publish.FRAGMENT_FIELDS`: label, statement, reason, needed_form, rationale, conditions, reasoning, description, proof_idea, regime, uncertainty and impact_reason. Conditions preserve list positions; statement/needed_form preserve their `.text` origin.
- Raw source excerpts, locators, IDs, metadata, and other currently escaped literal fields remain literal. This change does not parse arbitrary record strings as mathematics.

Common diagnostics retain per-expression classification, reason and original excerpt/display mode. Extend `publish.display_fragments` with an optional collector without changing its existing fragment-return shape. Both `render_input` and `frozen_render_input` collect diagnostics with record collection/id/version and field path, and put them in derived display metadata and the publication receipt. Carry this metadata through `render_projection.mjs::validateInput` and its returned model into nonblocking reader display notes. Reuse current Graphify `summarize_math_diagnostics` behavior, counting an expression once per saved field even when it appears in several views. Keep full located facts in the saved build artifact and bounded human-readable notes in the page, with explicit truncation when used. Do not expose record IDs in notices, alter scientific outcome, or write diagnostics into examined records or frozen scientific content. Graphify may omit the internal `kind` in its established message shape; do not lose canonical facts.

Shared escape policy: properly delimited formulas render; unmatched supported openers and paired doubled delimiters keep their exact literal bytes with a recoverable diagnostic. An unpaired doubled opener, ordinary escaped currency and undelimited prose stay literal without becoming formulas. Never silently repair escaping. Common `has_math` means a recognized math candidate, including the diagnosed malformed candidates, not proof of successfully generated MathML. Split the existing Proof Check escaped-prose test so legitimate escapes remain covered and paired doubled delimiters assert literal code-body preservation, no `<math>`, a diagnostic and candidate detection. Do not delete the conflicting test or weaken source-text assertions. Supported mathematical alphabets intentionally gain Graphify's Unicode materialization; unsupported forms such as `\mathcal{\alpha}` keep literal fallback. Preserve original TeX annotations and accessible labels.

There is one demonstrated compatibility exception: legacy `proofcheck_report.py` uses `proofcheck_math.has_math` to select primary claim versus source wording, not just display formulas. Preserve its old source-choice semantics in a small `legacy_reading_has_math` predicate in the facade and change the calls in graph-reading preparation, `_claim_reading`, main conclusion rendering and typeset-source disclosure to that predicate. All actual rendering still delegates to the common implementation. Add paired-doubled source-quote and claim cases to `test_html_report.py`, checking which text is primary and which remains disclosed. This update must not silently change selected scientific text.

## Work package D: common reader, bounded extraction

Keep the two current prepared-input formats and scientific content adapters. Do not introduce a universal scientific projection schema. Retain Graphify's SCC/rank layout and the audit renderer's feedback-edge layout; algorithm replacement is outside this handoff.

Create `paper_core/renderer/scientific_reader.mjs` and `scientific_reader.css`. They own common shell adaptation, graph vocabulary/metrics, typography and section styles, result navigation, source disclosure, scientific search, selection bridge and print lifecycle. Emit the runtime from the module; no UI framework or external asset request. Use the current Archify visual direction.

Use this small display interface, adapting existing data rather than copying scientific records:

```text
KINDS, BOX
adaptScientificReaderTemplate(template)
archifyPage(existing content-slot arguments)
mainResultNavigation({entries, heading, graphAvailable, traceHtml})
readingSection({role, title, bodyHtml, attrs})
sourceDisclosure({title, bodyHtml, attrs})
scientificSearchPanel()
readerRuntime({targets, searchEntries, graphAvailable})

target: {key, articleId, nodeId?, edgeId?}
navigation entry: {key, nodeId, label, caption, kind}
search entry: {key, aliases, label, detail, section, owner, text}
```

Adapters own selected/main IDs, labels, source versions, scientifically meaningful text, and HTML from existing escaped/MathML preparation. The common layer owns visible controls and behavior. Audit `reader_content.mjs` continues to select evidence and retain pinned references; it must not resolve a missing historical version to a newer record. Preserve all existing scientific receipt attributes. Use new `data-reader-*` hooks for common runtime state, avoiding collision with Graphify's intermediate-step `data-proof-detail` attributes.

Change G `scripts/render.mjs`, core `renderer/render_projection.mjs`, and `archify_adapter.mjs` into consumers of those shared components. Extract G `proofCss`/`proofRuntime`, the corresponding audit `PAGE_CSS`/`ADAPTER_CSS`/`RUNTIME_JS`, navigation markup, and common wrappers around G `fullItemHtml`/`fullUseHtml`/`passagesHtml` and audit `readerHtml`/`readerApplication`/`readerSources`. Retain each function's scientific content preparation in its adapter. Remove extracted duplication after callers switch. Use Graphify's current serif statement/proof-idea styles and statement/logic color tokens in one common stylesheet; audit assessment classes add meaningful decoration. Do not recreate two reader typography branches through a mode switch. The final result must share code, not matching copies of CSS.

Required visible behavior:

| Interaction | Shared contract |
|---|---|
| Work-depth label | `Source overview` or `Proof audit`; source-match status remains distinct from support/review verdicts |
| Result/prerequisite/connection selection | Mouse/keyboard activation opens the correct article/section and synchronizes graph selection; repeated activation is idempotent; Close/Escape restores focus to its activator |
| Search | One control/matching behavior over saved scientific text; opens and visibly focuses the exact destination, expanding needed disclosures; Graphify indexes only selected content; opaque aliases never become labels |
| Sources | Same disclosure behavior; exact locator/version, extraction limits and uncertainty retained |
| Theme and appearance | Same controls; selected material stays selected |
| Graph unavailable/index mode | Same reader/search/index behavior with graph-only controls disabled or absent; runtime does not require a visible graph |
| Print | Includes the entire saved page selection, not just the active result; expands sources and audit disclosures with locators, assumptions, restrictions, stale/partial notices, findings and review limits; restores selection, disclosures and show-all state |

Extract already-identical shell pieces first; six fixture outputs should remain byte-identical at that step. Later reader convergence intentionally changes HTML, so use scientific-content, interaction and layout assertions rather than requiring permanent byte equality. Check Graphify focus/metadata adaptations and audit export/theme adaptations before making either shared defaults.

Long formulas scroll within their container rather than widening the page. Keep the only readable source-role or qualification label visible when expanding print disclosures. Graph fit may intentionally restore the full structure; theme and appearance changes preserve scientific selection. Index mode exposes no graph fit/export action.

## Work order and acceptance

1. Capture HEADs, dirty/untracked input identities and old fixture baselines. Assemble a candidate containing both current repositories in their sibling layout. Establish canonical source, builder targets and new identity. Build both isolated packages.
2. Implement B and C against that source; rebuild and test both bundles. Do not edit generated copies. The small shell extraction in D can proceed in parallel; shared source edits need one owner per file.
3. Finish D using preserved prepared-input adapters. Freeze module interfaces before splitting component work among programmers.
4. Run the combined gates below once changes settle. Fix failures locally; do not waive meaningful tests or substitute prototype results.
5. Update ownership/version documentation and prepare both release packages together. Do not install, publish or commit merely to complete this handoff.

| Gate | Required evidence and useful existing tests |
|---|---|
| Bundle authority | Builder build/check, updated `tools/test_bundle_targets.py`, per-package manifest verification and isolated-copy imports |
| Overview compatibility | Fresh overview, old format-4 overview, nonempty mixed fixture, retained rich fixture, native schema-3 reader and backed-up migration; edit/compare/refresh/render/export/backup and failed-operation rollback |
| Write boundary | Exact protocol matrix, unsupported feature/protocol rejection, other-command rejection, selected-record boundary, protected audit fields, receipt behavior; no audit/check/review records created by an ordinary overview |
| Freshness | Changed hypothesis and changed source invalidate affected coherent audit evidence; unrelated change does not; legacy opinions retain historical meaning. Use real bindings and nonempty records, not row preservation alone |
| Audit regression | Normal primary work, synthetic independent return intake, integration, freeze and render under v3; whole/partial, gap, disagreement and original-response preservation retain existing semantics |
| Mathematics | Existing 58 Graphify math tests, revised escaped-prose test, 22-case parity corpus, legacy primary-text selection tests, frozen scientific-content tamper rejection, exact source preservation and diagnostics from live/frozen publisher |
| Reader | DAG, cycle, index, long math, multiple prerequisites, missing pinned evidence; scientific field/graph preservation and interaction simulation in both modes |
| Browser | Paired result/prerequisite selection, search, sources, long math, theme, index and print. If unavailable, record this gate as unverified; static tests are not a browser pass |

Existing lanes import different cores. `S/tests/new_format/support.py` loads `S/shared`; `S/stat-proof-check/tests/support.py` loads that installed package's `scripts`; G tests load G `scripts`. Run each lane in a fresh process and record imported core paths and manifest identity. Preserve legacy-specific tests as historical expectations where appropriate; do not make the old per-record audit policy the specification for new coherent audits. Promote relevant legacy overview/storage fixtures into the common integration lane instead of disabling their assertions.

In particular reuse `test_sql_overview.py` for retained owners/groups, application preservation and contradictory endpoints, proof-idea omission, unselected content, captures/refresh, comparisons and receipts. Reuse `test_overview_bridge.py` and selected `test_export_migration.py` cases for native migration; record pre-change results because some historical expectations differ from v3. Keep these tests in the repository lane or explicitly fix their roots: the formal support module's retained `OVERVIEW` constant currently points inside S rather than to sibling G. Replace packetless historical fixture setup with valid coherent setup or preserved historical input, never by widening normal overview permissions.

Use existing shared Python and Node. Example commands, from the workspace containing S and G:

```powershell
$py = 'C:/Users/zrq/AppData/Local/Python/pythoncore-3.14-64/python.exe'
$node = 'C:/Program Files/nodejs/node.exe'
& $py -B stat-paper-skills/tools/build_paper_core_bundles.py
& $py -B stat-paper-skills/tools/build_paper_core_bundles.py --check
& $py -B -m unittest discover -s stat-paper-skills/tools -p 'test_bundle_targets.py' -v
& $py -B -m unittest discover -s proof-graphify/tests -p 'test_*.py' -v
& $py -B -m unittest discover -s stat-paper-skills/stat-proof-check/tests -p 'test_v3*.py' -v
& $py -B -m unittest discover -s stat-paper-skills/stat-proof-check/tests -p 'test_report_math.py' -v
& $py -B -m unittest discover -s stat-paper-skills/stat-proof-check/tests -p 'test_html_report.py' -v
& $py -B -m unittest discover -s stat-paper-skills/stat-proof-check/tests -p 'test_skill_structure.py' -v
& $node stat-paper-skills/stat-proof-check/scripts/paper_core/renderer/selftest.mjs
& $node stat-paper-skills/stat-proof-check/scripts/paper_core/renderer/interaction_test.mjs
& $node stat-paper-skills/stat-proof-check/scripts/paper_core/renderer/reader_content_test.mjs
```

Direct temporary fixtures to a verified workspace-owned scratch folder if the restricted terminal cannot reopen its default temporary directory. Do not install local environments or bypass a browser policy denial. Inspect every test's imported path; an old-source pass does not validate the candidate.

## Evidence and delivery limits

Prior isolated experiments generated matching 63-file cores; 22 formula cases matched; 58 Graphify math tests passed; 21/22 Proof Check math/publication tests passed, with the documented delimiter-policy conflict. The shared shell extraction preserved six HTML outputs exactly. A real mixed fixture preserved three historical audit/check/scope rows through overview edits and rendering. Fresh review derived that fixture's historical check as current at revisions 4-6 and `needs_review` after source change at revision 7. This does not establish coherent or changed-hypothesis freshness. Five additional focused math probes passed. The prototype's overview protocol bypass admits unknown protocols and must be replaced by the explicit table above. These prototypes were separate and are not the combined implementation.

Detailed planning evidence is under `../../tmp/shared-core-plan-20261009/`, including `report.md`, each experiment's report and JSON results, and the fresh reviews under `revalidation/`. These artifacts explain feasibility and known failures, not patches to apply wholesale. The [implementation report](shared-core-reader-implementation-20261009.md) records subsequent native migration, combined audit lifecycle, common-core and reader validation. Actual browser usability remains unverified.
