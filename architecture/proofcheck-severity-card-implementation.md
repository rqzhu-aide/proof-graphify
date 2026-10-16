# Proof Check severity and issue-card implementation

Implemented 2026-10-13. No version bump, installation, commit or push was performed. Existing unrelated working-tree changes were preserved.

## Delivered behavior

Proof Check now records optional research severity separately from its mathematical outcome, exact-target support and review coverage. Severe issues are red, moderate orange, minor yellow and positively checked mathematics green. Unresolved, unassessed, unrated and historical material stays neutral, with its actual limitation stated. Graphify remains a source-backed map without proof grades.

The canonical rubric distinguishes harmless exposition from an actual incorrect derivation. An obvious typo or wrong attribution can be minor. A substantive derivation with an already apparent result-preserving correction is moderate. Material failure of an important claim or its intended regime is severe. Inherited assumptions are not missing assumptions; familiar conditions are judged by their actual consequence for the stated model. An accurately disclosed gap between theoretical and practical tuning need not create a finding. Uncertainty does not establish a defect.

Each issue card reuses the saved finding: severity and affected result, a short issue description with decisive mathematics where useful, one impact sentence and existing evidence links. Full examinations and older long findings remain accessible in details. No extra card record, word-count gate or rewriting pass was introduced.

The instructions explicitly bound examination to LLM mathematical understanding of supplied material and reliably known mathematics. A short exact witness or immediate correction can be stated directly. Numerical or symbolic truth checks, mandatory counterexample or repair searches, compulsory external-source retrieval and another severity reviewer are excluded from the default workflow. Ordinary extraction, database and rendering tools remain available.

## Scope of implementation

- `stat-proof-check/SKILL.md` and its existing judgment, external-result, mathematical-checking, role, graph-record and delivery references contain the policy. The severity table has one authoritative owner in `references/evidence-and-verdicts.md`.
- Shared `contract.py`, `controller.py` and `assistance.py` accept and preserve optional severity through existing intake and edit paths. Templates do not supply a default rating.
- `refs.py` excludes only severity from mathematical finding freshness. Full stored bodies, revision history and frozen hashes retain the rating. Mathematical edits keep their existing consequences.
- `review_display.py`, `assessment.py` and `projection.py` derive applicable display states without altering logical outcomes. Explicit target, owner and affected-use relationships determine scope; supplier severity does not automatically spread through the graph.
- The shared renderer and `publish.py` reuse the existing MathML and publication acceptance paths. Audit-scoped CSS supplies light/dark severity colors, accessible text and export-compatible SVG selectors. Historical projections without display metadata stay neutral and preserve their saved logical text.
- Both packaged cores are generated from the maintained shared source through the existing bundle builder.

## Independent validation and corrections

Sol 6.1 xhigh subagents examined scientific judgment, saved-record behavior and HTML output in jobs bounded to ten minutes or less.

The fresh judgment exercise used ten synthetic cases and the actual revised instructions, without the handoff's expected classifications. One response initially called a wrong probability derivation minor because reallocating the failure probability was easy. A short rubric clarification now distinguishes an actual derivation correction from an isolated typo. A second five-case exercise classified the former as moderate while retaining minor for the latter. The trials used written mathematical reasoning, without computational proof validation or external retrieval.

Saved-record probes confirmed that an unresolved disputed finding stays neutral, an independently established issue retains its rating alongside separate uncertainty, a valid alternative proof route can preserve support, and severity-only edits do not repeat completed mathematical examination. They exposed an application-group issue missing from its connection's severity; the projection now includes the exact represented group and traced intermediate material without importing the owning theorem's unrelated finding.

A follow-up exposed a triage summary incorrectly retaining a checked display after the existing logical assessment was demoted. Summary and grouped-connection displays now derive after that adjustment. A saved established finding retains its rating in triage. Graphify's no-audit projection remains free of severity metadata.

The six-result HTML fixture covers severe, moderate, minor, checked, unresolved and legacy unrated cases, including the tuning formula and full older prose. Publication passes its JavaScript representation receipt and Python acceptance. Altering severity, removing a summary card or removing MathML now fails the existing acceptance path. The missing-card control exposed and corrected a narrow omission in that path. Historical display fallback and SVG export selector retention also pass.

The final CSS inspection found insufficient small-text contrast for neutral badges in both themes and severe badges in the dark theme. Audit-only text-color overrides correct these pairs without changing Graphify or graph ring hues. Exact neutral status labels are retained in the graph descriptions, static index and related-result links.

## Verification evidence

Validation artifacts are under `../../tmp/proofcheck-severity-implementation/` relative to the repository root's architecture directory.

| Check | Result |
| --- | --- |
| Coherent reader, copied notes, integration, correction, severity and external-source regression selection | 41 passed |
| Shared reader JavaScript tests | 14 passed |
| Graphify layout, interaction, renderer identity and mathematics selection | 60 passed |
| Packaged severity intake and rendering tests | 9 passed |
| Historical rendering and export selector checks | Passed within the rendering test module |
| Small badge text contrast from actual CSS | All ten light/dark pairs exceed 4.5:1 |
| Real independent-review, alternate-route and freshness probes | Passed; see `runtime-validation.md` |
| Display aggregation, triage and no-audit regressions | 12 passed; 28 associated coherent engine/intake tests also passed |
| Package identity | Both generated cores match the canonical source |

Some older `tests/new_format` publication fixtures still request the obsolete `item-audit/1` protocol and fail before exercising these changes. They were not weakened or treated as evidence of this revision. Focused current-protocol fixtures were used instead. The legacy fixture limitation remains outside this revision.

Useful artifacts: `judgment-validation.md`, `runtime-validation.md`, `ui/v2/report.html`, and `ui/v2/ui-evidence.json` in the validation directory. The latter records status mappings, the actual artifact hash, MathML count, acceptance results and the exact browser-tool denial.

## Remaining visual limitation and workload

Actual desktop/narrow browser appearance, light/dark screenshots, touch behavior and browser export were not observed. The browser tool rejected local `file:` navigation and explicitly prohibited alternate-surface workarounds. Static HTML, MathML, CSS and export-selection checks passed, but those checks are not a substitute for visual inspection.

For an application of the skill, the additional authored datum is one optional severity choice during existing examination or integration. Description and impact replace the previous finding prose, rather than duplicate it. There is no new examination, reviewer, required artifact, repair round or delivery gate for missing severity. Display computation and the narrow publication checks are ordinary deterministic software work. No measured end-to-end time saving is claimed.
