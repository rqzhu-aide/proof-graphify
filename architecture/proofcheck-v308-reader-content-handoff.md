# Phase 3 scientific reader content handoff

Date: 2026-10-07, America/Chicago. Status: implemented and validated in the isolated v3.0.8 candidate. Canonical skill name: `stat-proof-check`. See [candidate validation](../stat-proof-check-v3/VALIDATION.md#scientific-reader-presentation-308) for results and limits. Installation and publication remain separate.

## Objective and boundary

Make the HTML useful for understanding the paper's mathematics, the proof structure, and the examination's reasoning and issues. Keep the current visual design, graph layout, mathematical rendering, themes, controls and exports. Shorter content can shorten panels; preserving appearance does not require preserving empty rows or panel heights.

This is a Phase 3 presentation change. Its input is the existing Phase 2 frozen report snapshot. Phases 1 and 2 keep their current responsibilities, database schema, scientific judgments, completion rules and saved artifacts. The renderer selects and labels existing material. It does not commission new reviews, generate proofs, require another summary for each result, retrieve new sources, or return missing optional prose for repair.

Implement in `stat-proof-check-v3`, including its packaged `scripts/paper_core`. Leave the historical `stat-proof-check`, `shared/paper_core` and proof-graphify packages alone. Use the candidate's existing manifest builder. Installation and publication are separate from this handoff.

## Evidence and remaining uncertainty

Three bounded sol-6.1-xhigh experiments tested evidence content, summary content, and search/printing:

- [Evidence experiment](../tmp/v307-reader-experiments-20261007/evidence/REPORT.md): five real reports, with paper statements, source passages, examination reasoning and reconciliation rationale retained in selected record views. CSS, graph SVG, runtime scripts, mathematical displays and existing result overviews were unchanged.
- [Summary experiment](../tmp/v307-reader-experiments-20261007/summary/REPORT.md): three real reports and six controls, with 34 static checks. It separated scientific support from process completion and retained partial, stale, disputed and unavailable-source limitations.
- [Search and print experiment](../tmp/v307-reader-experiments-20261007/search/REPORT.md): two real reports, scientific queries, preserved evidence destinations and adversarial mathematical-literal controls. A separate print filter was rejected as a production approach.
- [Parent validation](../tmp/v307-reader-experiments-20261007/parent/validation.json): 47 checks passed, including preservation of 1,766 scientific text values. All 253 source files and the ten original report/database artifacts were unchanged.

These are presentation experiments, not new scientific reviews. Browser and actual print-preview validation were unavailable. The full-report simulated print traversal was too slow; only individual real details were exercised in that simulation. Do not claim full browser acceptance from these results.

The prototypes are not implementation patches to copy wholesale. Their limitations are material: the evidence selection omitted valid record types, the summary hid important qualifications in a closed disclosure, and the original search prototype attempted unsafe prose scrubbing. Current validators also intentionally reject removal of the old record dumps or counters. Resolve these points within the presentation change.

Two further sol-6.1-xhigh reviewers checked this handoff for scientific preservation and workflow burden. Their corrections are incorporated: actual-schema coverage for less-used records, current versus historical opinion context, consequential review-exposure explanations, examined-span meaning, and validation through the isolated production renderer/publisher rather than legacy report tests alone.

## Reader-facing content contract

Readers should be able to answer three questions through the existing graph and panels:

1. What does the paper state, under which assumptions, and where is the supporting passage?
2. Which result or equation is used, how is it applied, and what conditions matter?
3. What did the examination conclude, why, and what remains uncertain or disputed?

Keep the paper's text and the examiner's analysis distinct. Short headings such as "Statement from the paper", "Source passage", "Initial assessment", "Independent assessment" and "Combined assessment" can label existing content. An examiner's reasoning must not become an attributed proof strategy from the paper. Preserve the distinction between a source argument, an examiner's observation and a proposed repair.

Use the existing scientific text and mathematical display fragments. Preserve quantifiers, conditions, substitutions, adverse conclusions and qualifications. Do not shorten a mathematical statement by dropping hypotheses. When no proof-strategy summary was saved, use the available source passages and reasoning; omit that optional empty heading. A missing optional named scope does not establish missing theorem hypotheses or unexamined mathematics.

Scientific uncertainty remains visible. A completed examination may find a gap or remain inconclusive. An incomplete or stale examination may have a saved opinion without establishing that all current material was examined. Missing sources, unexamined supplied material, review limitations and exclusions remain distinguishable. Do not derive a stronger conclusion from the absence of an administrative record.

## 1. Use one small scientific content adapter

Replace generic display of every body field with selection based on the current record type and schema. Use one shared selection/labeling implementation for evidence rendering and search. A small renderer-local module is appropriate if it reduces duplication; it is not a new persistent projection format, database layer or public protocol.

Retain hidden record identities, pinned versions and navigation attributes where needed for exact links and validation. Display useful names: theorem/equation labels, source filenames or titles, page/line locators and the names of connected results. Do not print database collections, record IDs, hashes or protocol versions as evidence headings. Existing data embedded for navigation is not itself reader-visible content.

Selection must follow `contract.py`, `projection.py` and actual saved shapes, including current shapes absent from the five KEDRL samples:

| Material | Scientific content to retain |
| --- | --- |
| Items, proof parts and exact targets | The saved exact statement or explicitly identified synopsis, ownership/context, origin, uncertainty and source passages. Resolve a `statement_ref` to its pinned statement. Include `parts`, not only `items`. |
| Assumptions and applications | Named assumptions, binder domains and quantifiers, conditions, how a supplier is used, the required mathematical form, substitutions, restrictions and uncertainty. Preserve joint and case context and discharged local assumptions. |
| Proof structure and refinements | Argument context, group rationale and connections between a summary link and its detailed applications. `connection_refinements` uses `summary_use_id`, `argument_id`, `use_ids`, `state`, and `note`; do not copy the prototype's nonexistent field names. |
| Source evidence | Passages, locators, source-comparison notes, source-review rationale, unresolved source issues and evidence-quality limitations. Coverage/proof-boundary information should explain the exact examined span and its claim context. Keep substantive versus structural coverage meaning even when `coverage.note` is empty: displaying structural source text does not imply its mathematics was examined. Numeric offsets and check identifiers may remain hidden while the relevant passage/locator and assessment links retain their meaning. |
| Examinations | Actual outcome, reasoning, conditions, omissions and affected statement/application. Preserve distinct initial and independent views and their completeness/currentness. A recorded next action can contain a scientific limitation or proposed clarification; do not drop its substance merely because of its field name. |
| Findings and repairs | Finding description, affected material, impact and meaningful resolution. Retain repair descriptions, supported restricted forms and added conditions. Clearly identify a proposal; its existence does not establish that the original claim is repaired. |
| Review integration | Reconciliation rationale and the views it combines, including successor assessments and consequential `reuse_decisions.rationale`. Include `response_dispositions[].rationale` with its response/target context. Preserve coverage notes and review limitations that affect confidence. `pending_judgments` contains integer indexes, not judgment prose; report unresolved returned material without fabricating its contents. |
| Scope and confidence | Stated scope, exclusions and their consequences, actual independent-review level, and material qualification or source-access limitations. Technical qualification exercises and session-isolation logs do not become the reader's report. |

Do not treat a field allowlist as proof that all scientific content was preserved. Complete the mapping for current supported records and test representative nonempty values, including structured values. This is an implementation responsibility, not a checklist added to every agent run.

For a valid older or less-used shape, reuse compatible existing scientific fields and expose a concise display limitation if needed. Retain its full source record in the frozen artifact. Do not silently replace substantive material with an empty panel, render an unrestricted database dump as fallback, or trigger a scientific rerun. Truly incompatible or invalid inputs continue to use the existing compatibility/error route.

Mixed prose is an explicit boundary. Administrative fields can be omitted by type, but scientific `reasoning`, `resolution`, `coverage_note` or source notes may mention internal details. Preserve a mixed note when dropping it would lose a condition or concern. Do not remove identifier-like strings, hexadecimal literals or phrases using regular expressions. Resolve structured references to human labels; arbitrary authored prose stays faithful. This revision cannot promise that every internal-looking token disappears from legacy prose.

## 2. Replace the raw evidence interface in the existing panels

Primary seams: `renderer/render_projection.mjs`, especially `recordHtml`, record/value/reference helpers, `detailHtml`, `sectionHtml`, `assessmentBlock`, reader overview methods and the index fallback.

Render the adapter's scientific fields in the existing evidence disclosure. Remove the visible technical record index, obligation-ID cards, collection/version headers and empty administrative rows. Replace `sectionHtml`'s visible collection/ID placeholders with reader labels before hydration as well. Keep the scientific assessment and supporting reasoning currently reached through those locations. Preserve usable evidence destinations when a removed technical wrapper previously owned an anchor.

Give paper statements/passages and examiner explanations clear headings. Retain initial/independent distinctions where they explain disagreement; model names, request identities and execution-session notes are not needed to understand the argument. Historical or superseded scientific opinions must be identifiable as earlier views when shown, so they are not confused with the current conclusion. Use existing lifecycle/currentness information without displaying a revision ledger.

Keep the pinned statement associated with a displayed examination. If it is unavailable, disclose that local limitation instead of substituting a newer synopsis as the examined claim. Show the scientific meaning of recorded review exposure and qualification: a review that does not qualify as independent must not acquire that label through presentation cleanup. Preserve any consequential exposure explanation in the evidence, subject to the mixed-prose rule above, while omitting routine session logs and identity fields.

Replace storage vocabulary in ordinary result and connection views where it has no scientific value. Omit empty optional synopsis/strategy/scope sections. Preserve real missing-evidence notices and the exact assessment meaning. In index-mode reports and connection labels, use result names rather than connection hashes. Keep existing graph colors and their meaning.

Source links must continue to open the relevant passage, and links to findings must reach their explanations. Removing technical sections must not leave navigation leading to blank content or make scientific text available only inside embedded JSON.

## 3. Show scientific findings, scope and review limits

Primary seams: `summaryHtml`, `factualHtml`, `readerReportState`, `buildLine`, and the remaining-work section in `page`.

Retain a brief truthful report state, main findings, support conditions, actual review level, scope/exclusions and source limitations. Keep material source-access and independent-review limitations visible in the existing area near the graph. Do not adopt the prototype's move of all such qualifications into a closed summary.

Remove the build/version/hash line, obligation totals, draft and historical-check counts, revision/publication bookkeeping and the coordinator's work queue. Useful scientific totals may remain if they aid navigation; counts must not imply a percentage of manuscript correctness or completeness. Full explanations can remain in existing disclosures rather than requiring freshly authored executive summaries.

Use the saved work facts only to state consequences for the reader: which material lacks current examination, which judgments are conditional, and where review is incomplete. Suppress scheduling dependencies, recovery instructions and coordinator actions. A task with a saved outcome that is partial or stale still needs an explicit current-review limitation; do not label its entire material examined merely because an outcome exists.

Preserve disagreements and adverse findings even in a completed release. Preserve unresolved limitations from existing summary prose when their scientific consequence cannot be recovered safely from structured facts. Administrative ambiguity is not a reason to ask for new proof work or quietly erase a qualification.

## 4. Reuse the same content for search and print

Primary seams: the search index and result snippets in `RUNTIME_JS`, plus existing disclosure/print handling.

Index the selected statements, equations, source passages, assumptions, explanations and findings. Search result titles identify the theorem, application or source passage. Keep navigation keys internal. Existing identifier lookup may remain a hidden alias if easy to preserve, but IDs and hashes should not supply ordinary snippets. Do not append generic raw record text or task instructions after creating a clean index.

Resolve explicitly typed assumption/source references to their scientific labels as needed. Preserve independent and conflicting judgments rather than merging distinct opinions as duplicates. Where the same record is repeated at several locations, reuse the existing location choices or remove exact duplicates without changing meaning. Do not expand this patch into semantic search, formula equivalence or a ranking project. Keep an honest indication that a limited result list is not the complete audit.

Print the same scientific content using the existing print/export appearance. Once raw administrative panels are removed, there is no need for a second DOM blacklist or another scientific-content filter. Keep mathematical children and complete condition/limitation text when disclosures expand. Preserve normal page state after printing. Do not pursue the slow full-report mock-DOM traversal as a new runtime feature or a compulsory agent check.

## 5. Adjust presentation validation with the content contract

Update both JavaScript and Python checks; changing only visible HTML leaves the public Stage 3 command rejecting the result.

- `renderer/render_projection.mjs`: replace generic `canonical_record_templates` equality and obsolete count/work-panel expectations with checks for the selected scientific text, correct destinations and mathematical fragments. Update scope/assessment checks where labels or field presentation change.
- `publish.py`: update `_Scan`, `_visible_failures`, `_reader_failures` and `mechanical_acceptance` only where the reader contract changes. Remove requirements for visible tracking counters and raw completion diagnostics while retaining their scientific consequences. Keep frozen-input integrity, mathematical fidelity, output protection and read-only publication behavior.
- Update `renderer/selftest.mjs`, `renderer/interaction_test.mjs`, `tests/test_v3_delivery.py` and the current core publisher fixtures. Verify which implementation a test exercises: legacy `proofcheck_report.py` tests alone do not validate this renderer. Preserve independent expected scientific values in tests; a candidate's renderer comparing itself with itself cannot establish preservation. Include a small adverse control that removes a consequential condition or changes an assessment and verify rejection, alongside normal successful delivery.

Retain existing graph integrity/geometry checks, source and finding links, safe mathematical rendering/fallbacks, and truthfulness of outcomes, scope and review limitations. Do not bypass production acceptance because an old raw-display expectation failed. Replace that expectation and prove the intended reader behavior through the normal Stage 3 build path.

## 6. Small instruction update and finite implementation sequence

Update the existing Phase 3 paragraph in `SKILL.md` and `references/controller-workflow.md`, plus `references/reporting-and-release.md`. Keep this guidance in those locations instead of adding another agent checklist. Suggested content:

> Build the reader-facing HTML from the frozen result. Show the paper's statements, source passages and dependency uses separately from examination reasoning, findings and limitations. Keep administrative tracking in the saved audit artifacts. Use existing content; missing optional explanatory prose does not commission another review. A display repair uses the same frozen input.

Clarify that database/frozen-summary delivery retains internal tracking, while the HTML presents its scientific meaning. Keep the current rules for incomplete review and honest final reporting. No new required records, prose summaries, phase gates, agent roles or approval steps are added.

Implementation can be divided into three bounded workstreams:

1. Establish the shared scientific selection and evidence view against actual current schemas. Agree its small interface before another worker consumes it.
2. Update summary/limitations and connect search/printing to that selection. Preserve appearance and current source/assessment meaning.
3. Update affected acceptance checks and run the reader-preservation/public-build tests; coordinate shared-file edits rather than merging competing full renderer rewrites.

After focused checks pass, update the source patch version and documentation, rebuild the isolated runtime manifest, and verify it. Do not automatically install, commit or push as part of this planning task.

## Validation and completion

Use a compact implementation regression set. These checks belong to development of the renderer, not to each future proof-audit run.

| Case | Observable result |
| --- | --- |
| Five saved KEDRL reports | Statements, mathematical fragments, source passages, examination reasoning, findings and reconciliation rationale survive. Compare identified scientific fields against the inputs. Tracking fields are absent from ordinary visible content. |
| Less-used current structures | Nonempty proof parts, repair proposals, connection refinement notes, response-disposition/reuse rationale, binders and substitutions remain accessible with correct context. Include structural coverage with an empty note and substantive coverage linked to its actual examined span/claims; neither displaying a source passage nor omitting numeric offsets changes what was examined. Use existing fixtures or small contract-shaped controls. |
| Conditional, gap, disputed and inconclusive results | Correct scientific meaning and both relevant viewpoints remain; process completion never becomes proof correctness. |
| Unexamined, partial or stale material | Meaningful current-review limits remain visible; an older saved opinion does not imply complete current examination. Missing optional scope/strategy metadata adds no false scientific warning. |
| Mixed prose and literal collisions | Scientific conditions and conclusions remain exact even when prose contains an ID-like symbol or a long hexadecimal literal. No blanket prose scrub is used. |
| Reader navigation and search | Graph selections, source/finding links and representative scientific searches reach useful explanations with human labels. No dead destinations after technical panels are removed. |
| Print and compatibility | Scientific text and formula children remain available when expanded; display state restores. A compatible older snapshot renders without a Phase 2 rerun. |
| Public Stage 3 delivery | `AUDIT stage3 build FROZEN --out NEW_REPORT` passes both production acceptance layers against an existing frozen bundle; database/frozen bytes and existing output-protection behavior are preserved. |

Run the affected renderer and Python report tests first, then the existing v3 regression suite once after the source settles. Do not keep rerunning unrelated suites without a new change or failure. Build representative candidate pages from the existing frozen reports; no full-paper proof-check rerun is needed to validate this display revision.

Verify unchanged style assets and graph geometry for the same inputs. Compare scientific MathML/LaTeX fragments by their associated content, allowing removal of duplicate administrative views. Browser and print checks, when an allowed preview route is available, should cover representative result, connection, evidence, search and print paths. If that environment is unavailable, record the untested boundary rather than bypassing browser restrictions or claiming visual acceptance.

Stop when the selected scientific content is preserved, ordinary reader paths work, internal tracking panels are removed, public Stage 3 rendering passes, and Phases 1 and 2 remain unchanged. Scientific calibration, new explanations, database simplification, renderer redesign and new agent work are outside this revision.
