# Shared core and scientific reader implementation

Implemented on 9 October 2026 from the [approved handoff](shared-core-reader-handoff-20261009.md). Graphify is now 3.2.0 and Stat Proof Check is 3.1.0. Both packages ship common core 3.1.0, maintained only in `shared/paper_core`. Installation, commits and publication were not performed.

The two skills now share storage, mathematical display and reader components while retaining their scientific depth. Graphify presents selected statements, source passages, proof ideas and connections. Proof Check retains its coherent examinations, independent review, integration and frozen publication. The mathematical assessment engine remains identical to the formal 3.0.11 baseline. Sharing the core adds no proof-review credit to an overview.

## What changed

- The canonical builder generates and verifies both self-contained bundles. Distinct product entrypoints are supported and required. Installed manifest commands verify only. The final bundles contain the same 67 files and identical manifests, with source identity `cd8fd24ca689eb31df925fa5fd9bc3e2b27efa889f371b40724da04529f7d3b5`. The obsolete v2 scheduler is excluded.
- New overviews use `paper-overview/1`. The overview writer can continue supported format-4 historical and mixed stores, but can change only selected overview fields. Ordinary audit writers require `coherent-proof-audit/1`. Native conversion remains explicit, transactional and backed up. Existing scientific records, observations, audit extensions and immutable build receipts are preserved.
- Both products render mathematics through adapter 11. Mathematical alphabets, literal fallback, original TeX and accessible labels are shared. Located display diagnostics remain separate from scientific judgments. The legacy report retains its previous choice between claim wording and source wording.
- Both products use one scientific reader for the shell, navigation, search, disclosures, selection, themes and print lifecycle. Graphify retains its layout algorithm and scientific adapter; Proof Check retains its own layout and pinned evidence adapter. Graph and index views use the same shell. Sources, restrictions and qualifications remain visible when printing the full selection. Graphify pointer and keyboard previews are retained.

## Defects found and repaired during validation

Independent reviews found that selection metadata could shadow a stored source concern and that archive-only comparisons could disappear after native migration. Normalized acceptance now protects original comparison bytes and history, canonical observations take precedence, and deselection/reselection retains archive-only originals without promoting them into audit evidence. All six independent storage probes pass after repair.

Review also caught missing Graphify hover previews and a manifest count that could be incorrect while verification succeeded. Both were repaired and independently retested. Integration fixed duplicate node activation, source-search destinations inside nested disclosures, print labels, and false staleness caused by reclassifying an unchanged source anchor during a caption edit.

Older compatibility tests were adapted to the coherent fixture, overview rendering entrypoint and dedicated receipt helper. Their binding, source-preservation, error-recovery and artifact-hash assertions were retained. Historical per-record audit policy fixtures remain separate; ordinary overview permissions were not widened to make them pass.

## Validation

Three fresh `gpt-6.1-sol` reviewers at `xhigh`, each bounded to ten minutes, independently examined storage/scientific preservation, math/delivery, and reader behavior. Their local reports and reproductions are under [independent-storage](../../tmp/shared-core-implementation-20261009/independent-storage/REPORT.md), [independent-math-delivery](../../tmp/shared-core-implementation-20261009/independent-math-delivery/REPORT.md), and [independent-reader](../../tmp/shared-core-implementation-20261009/independent-reader/report.md). The storage report records the original archive-retention finding; the subsequent parent rerun of its unchanged six-probe script is green.

| Check | Result |
|---|---|
| Full Graphify suite | 435 tests, successful; one Windows symlink privilege skip |
| Full Proof Check v3 suite | 277 tests, successful; one Windows symlink subtest skip |
| Math, legacy HTML and skill structure | 67 tests passed |
| Storage, overview boundaries, rich/native migration and packaging | 213 tests, successful; one Windows symlink privilege skip |
| Final builder and installer fixture tests | 29 tests passed; no real installation |
| Final audit lifecycle, overview preservation, publication and skill smoke | 15 tests passed |
| Final Graphify interaction, recovery and math smoke | 69 tests passed |
| Shared reader/content tests | 13 tests passed; audit interaction simulation and renderer selftest also passed |

The full workflow suites ran against the frozen scientific runtime. The final packaging-only cleanup removed the unused v2 scheduler and preserved the manifest verifier's existing diagnostic fields while rejecting incorrect counts. The compatibility, delivery and smoke checks were rerun against the final 67-file identity above. Each Python lane ran in a separate process; JSON results record its actual imported core path and identity. The existing user-wide Python and Node were used, with no project-local environment or downloads.

A copied retained KEDRL overview rendered with four statements, one connection, all five source comparisons preserved and zero math diagnostics. Geometry, graph preservation and the output hash passed. Its ten non-administrative authority/history tables and exported snapshot remained unchanged; the original database, HTML and PDF hashes also remained unchanged. This confirms retained-data presentation, not a new mathematical audit. Evidence is in [retained-kedrl/verification.json](../../tmp/shared-core-implementation-20261009/retained-kedrl/verification.json).

The baseline and final source identities, failed intermediate runs, final results and release manifest are retained under [the implementation evidence directory](../../tmp/shared-core-implementation-20261009). Unrelated pre-existing dirty files were preserved. Re-run the canonical builder with `--check` to verify both source checkouts; `scripts/build_manifest.py --check` verifies an isolated Proof Check package.

Actual browser layout, pointer hit testing and print pagination remain unverified because browser access was unavailable under the existing policy restriction. No browser pass, fresh whole-paper accuracy improvement or installation is claimed. DOM simulations and static preservation checks are not substitutes for that visual gate.
