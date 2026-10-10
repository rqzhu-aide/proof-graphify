# Compatibility

This package is stat-proof-check version 3.2.3. Its coherent audit workflow retains the 3.0.11 semantics.

New audits use coherent-proof-audit/1 and the coherent-examinations/1 feature. The physical database format remains 4. A shared SQL format does not imply compatible audit semantics.

Start a fresh database for this protocol. The v3 writer refuses legacy protocol mutations. Use the original compatible v2 runtime for saved v2 audits. Do not relabel an incomplete historical audit as complete under the smaller v3 task policy.

Both skills ship paper_core version 3.2.3, maintained in `shared/paper_core` in the Proof Graphify repository. Both skill versions are 3.2.3 for this release; skill and core versions can advance independently. Its `tools/build_paper_core_bundles.py` generates both self-contained bundles and manifests. The installed `scripts/build_manifest.py --check` verifies its bundle without rewriting it. Install this package under the existing stat-proof-check skill name; it needs neither the Graphify installation nor the maintained source directory at runtime.

New Graphify stores use `paper-overview/1`. Bounded overview edits can also continue supported historical or mixed stores without changing audit-only fields or promoting source comparisons into proof-review credit. New audit work still starts explicitly from the manuscript in its own database.
