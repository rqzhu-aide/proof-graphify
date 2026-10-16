# Proof Check: research severity and concise mathematical issue cards

Status: implemented, 2026-10-13. See [implementation and validation](proofcheck-severity-card-implementation.md). Actual browser appearance remains unverified because the browser tool blocked local-file navigation.

## Intended result

Proof Check should report how consequential an issue is for a statistics paper, while preserving its separate judgment of the written mathematics. A minor correctable issue should look minor; uncertainty must not look like either a severe defect or a successful check. Each issue should have one concise card containing the decisive mathematical reason and its consequence.

This implements the user's preferred research-review calibration. It is not presented as a universal grading standard across journals or statistical subfields. The examination remains an LLM assessment of supplied mathematics using mathematical knowledge, not formal verification or a computational validation service.

## 1. Judgment policy

Keep `supported`, `gap`, `refuted`, and `inconclusive`, exact-target availability, source provenance, and review coverage. Add a separate optional finding field `severity`, with values `minor`, `moderate`, and `severe`. Omission means not rated, not minor. Do not infer severity from finding category, logical outcome, color, or confidence alone.

| Severity | Decision rule | Typical example |
| --- | --- | --- |
| Minor | An obvious local correction or justification leaves the mathematical claim and intended application intact. | Harmless notation or prose error; wrong citation or justification with a directly identified valid replacement under the same premises. |
| Moderate | A substantive local derivation needs correction, but the already available reasoning identifies how to preserve the result under the stated assumptions; or a bounded qualification/loss of an ancillary claim leaves the main contribution and intended regime intact. | A missing term repaired without materially changing the principal claim; an erroneous unused auxiliary claim whose removal does not affect the main results. |
| Severe | The evidence identifies a material failure of the claimed conclusion or intended scope, such as a genuinely restrictive missing assumption, changed principal rate, or false important statement. | An essential moment assumption is absent and the stated class includes distributions for which the conclusion fails. |

Apply these distinctions during the existing examination and finding integration:

- Judge the actual consequence, location, and repair scope together. A wrong justification is minor only when its valid replacement is apparent. A merely plausible rescue does not establish easy repair.
- No new assumption is not by itself evidence that a difficult missing proof is a moderate issue. Conversely, a condition already in inherited setup is not an added assumption.
- A routine omitted regularity qualification that changes no intended model or conclusion can be minor; a standard condition that excludes intended distributions or regimes can be severe. An assumption already inherited from the stated setup is not a defect at all. Familiarity in the literature informs judgment but never substitutes for examining its consequence in this paper. No literature search is required to establish familiarity.
- Describe what a known correction would change, without constructing it as a new proof route. Say that repairability is uncertain when it is uncertain. Failure to discover a repair is not proof that none exists.
- Practical tuning outside a theoretical guarantee is ordinarily a minor applicability qualification when theory and practice are distinguished. Existing numerical evidence can provide context for that choice, but does not extend the theorem. If the paper explicitly promises the guarantee for that implemented rule, judge the resulting claim failure at its actual impact.
- Do not manufacture a minor issue merely because practice uses a different tuning rule. If the paper accurately discloses that boundary, the theoretical claim can simply remain checked. Record a qualification only when it adds a consequential clarification.
- A false incidental formula with an obvious intended correction is not automatically severe. Likewise, a genuine defect in one auxiliary result does not automatically invalidate the paper's main result. Name the affected claim.
- A presentation-only concern outside the established proof inference must not make a supported mathematical composition into `gap`. Record the concern separately. When the assigned inference itself fails, retain its logical gap even if its research severity is minor.
- Inconclusive examination, missing access, and lack of model knowledge are limitations. They receive no inferred defect severity. A clearly identified defect may coexist with a separate unresolved question.

Authoritative owner: `stat-proof-check/references/evidence-and-verdicts.md`. Update the existing findings section and add this short rubric there. Replace conflicting statements rather than append a competing policy. Primary and independent role references point to this owner; do not duplicate the table in every role file. Do not revive the legacy S0-S3 scale or its repair-search ledger.

## 2. Bounded LLM examination

Retain the existing primary examination and independent review. Classification and concise reporting happen within their existing work and the coordinator's existing integration. There is no new severity reviewer, calibration round, repair search, card-writing worker, or publication-time scientific assessment.

- Read supplied statements, proofs, assumptions, and available cited passages. Use mathematical knowledge and short written deductions to judge them.
- A direct short analytical counterexample is allowed when apparent. It is not a required deliverable or a search task.
- An immediate one-line correction can explain a minor or moderate rating inside the same examination. It is not an authored replacement proof and must not trigger the existing separate-route/repair-review machinery. Preserve that machinery only for an actually requested or supplied replacement route, without promoting an unexamined proposal to established mathematics.
- Do not invoke simulations, numerical solvers, optimization searches, interval validation, computer algebra, proof assistants, or code execution to establish mathematical truth. Hand-written algebra and a short exact mathematical witness remain appropriate.
- Source extraction, PDF inspection, storage, schema validation, rendering, and software regression tests remain ordinary tools. These are not proof evidence.
- Remove mandatory external-source retrieval from the default audit. An accurately known mathematical result may be assessed from LLM knowledge, with that basis stated honestly. Reading an already supplied external statement remains useful. Do not claim an external publication was inspected when it was not.
- If the needed external statement or its conditions cannot be recalled reliably and are not supplied, state the specific uncertainty and continue. Do not force inconclusive merely because a familiar fact has not been fetched, and do not fabricate precise source attribution.
- A separately requested literature/source-verification task is outside this default workflow. No replacement-theorem hunt or recursive reference audit is introduced.
- Remove the existing invitation to numerical follow-up from the default unresolved-examination instructions. The requested mathematical assessment should finish with the precise unresolved statement, not generate additional validation work.

Align the actual instruction owners: `stat-proof-check/SKILL.md`, `references/evidence-and-verdicts.md`, `references/external-result-verification.md`, `references/graph-records.md`, and the brief links/wording in `primary-checker.md`, `independent-checker.md`, `reconciler.md`, and `mathematical-checking.md`. In particular, clarify the repair boundary at evidence-and-verdicts lines 90-91/146-148 and mathematical-checking lines 169-172. Keep existing external-result/application records and provenance; do not redesign storage or silently grant unconditional support when assumptions are uncertain. Put delivery/card guidance in the existing `reporting-and-release.md`, with a link to the rubric rather than another copy.

## 3. One concise issue card from one saved finding

Add only `severity` to the stored finding. Reuse the existing scientific fields instead of adding title, evidence-summary, repair-cost, or parallel card records.

Fixed visible shape:

1. Header generated from severity and the affected theorem, step, or application, for example `Minor · Theorem 3.3`.
2. `description`: one short issue sentence followed, when useful, by one decisive display equation, inequality, implication, or short counterexample. An exact named missing condition or textual correction suffices where a formula would be artificial.
3. `impact_reason`: one short sentence saying what remains valid and what changes. Include an already apparent correction only when useful; do not require a repair proposal.
4. Source locator/link from existing evidence references. Existing examination reasoning, assumptions, review limits, and historical resolutions remain accessible under details.

Aim for two or three short sentences plus the mathematical block. This is an authoring guideline, not a word-count validator or a reason to commission a rewrite. Use enough notation to identify the failed claim and the decisive discrepancy; define any unfamiliar symbol locally. Do not require a second derivation to satisfy the card shape.

Example:

**Minor · Theorem 3.3**

The sentence reverses the direction of the tuning relationship.

\[
\lambda_n(\tau)=n^{-1/[2(\tau+2)]},\qquad
\frac{\partial}{\partial\tau}\log\lambda_n(\tau)
=\frac{\log n}{2(\tau+2)^2}>0\quad(n>1,\ 0<\tau\le1).
\]

Within the stated source-exponent range, larger \(\tau\) gives larger \(\lambda_n\); correcting the sentence leaves the displayed bound unchanged.

Source: page 22. Details expose the saved examination, not a newly generated explanation.

Implement one card component reused by the issue summary and selected-result view. Reuse the current `readerField`/MathML path for `description` and `impact_reason`; these fields already support math. Do not parse severity out of prose or truncate LaTeX to obtain a preview. Old long findings retain their complete saved text in details; no bulk rewriting or mandatory card backfill.

## 4. Color and aggregation contract

| Visible color | Label | Meaning |
| --- | --- | --- |
| Red | Severe | At least one current applicable severe issue. |
| Orange | Moderate | Highest current applicable rated issue is moderate. |
| Yellow | Minor | Highest current applicable rated issue is minor. |
| Green | Checked | The existing current examination supports the scoped mathematics and no applicable open issue or unresolved support blocks this status. The recorded review level remains explicit. |
| Neutral gray | Not assessed / Unable to assess / Severity not rated / Depends on unresolved result | State the actual limitation. It is neither a defect grade nor a successful check. |

Color is an issue-severity/status signal, not the finding category or a proof certificate. Display the scientific outcome and exact-target support as short text separate from the color. Use one report-level explanation that all checks are LLM mathematical assessments.

Rules:

- Derive an optional `review_display` once from the frozen current assessment and applicable current findings in the core projection. Preserve existing logical assessment values. The renderer consumes the derived display state consistently instead of inventing a second judgment policy. Include the display status, applicable finding references, and unrated count; derive labels/colors from that single enum, not from prose.
- A node or grouped edge takes the highest severity among applicable current findings within its represented scope. Count each finding ID once. Include an ungraded-issue or unresolved-work note when such items coexist; a minor color must not claim all concerns are minor.
- Resolved, superseded, stale, and historical findings do not determine current severity. Their history remains available. Use the existing finding lifecycle, freshness, and current-target rules; findings are not generally bound like proof checks. An old linked check reference alone must not make an otherwise current open finding stale. Do not add a new finding-staleness system or commission reassessment just to compute a color.
- A finding classified `inconclusive` stays a neutral limitation even if a contradictory severity field was supplied. Preserve its text and surface the uncertainty; do not invent confirmed severity from it.
- Do not propagate severity mechanically along every dependency. Explicit affected uses and existing target/owner relationships determine where an issue applies. An unresolved prerequisite retains a dependency/support notice and link to the original issue, without creating duplicate findings or declaring every descendant severe.
- Green requires positive current examination evidence, not merely an empty findings list or a successful build. Preserve current initial-review eligibility and the independent-review indicator; do not add a new review-completion gate just to color a node. Label initial-only work accordingly. Unexamined assumptions/definitions remain premises, not newly checked theorems.
- A finding whose mathematical validity remains disputed is neutral rather than an established rated defect. If a separate applicable rated defect is established at the saved review level, retain its severity color and show the unrelated unresolved question alongside it. Use neutral gray when no established applicable rated issue remains and the examination is unresolved. Established means supported by the existing saved reasoning/integration, not a new confirmation field or review gate. The coordinator settles a severity-label disagreement from the existing reasoning; it does not commission another referee merely to choose a color.
- A sufficient alternative route can preserve exact-target support while an examined defective route remains visible at its severity. Global audit findings stay in the audit summary unless an explicit affected target/use establishes their local applicability.
- Current gray/amber operational states must not be relabeled as mathematical minor/moderate issues. Pending review and process messages use neutral text/markers; severe red is not reused for an administrative warning in the proof-report semantic layer.
- Keep textual labels and accessible descriptions alongside color. Distinguish orange and yellow in both light and dark themes, including badge backgrounds, borders, node rings, edge arrows, static index, and print/export. Do not replace scientific item-kind colors or graph structure.
- The current Archify SVG exporter copies only selected CSS selector families. Prefix new SVG severity rules with `svg` so standalone SVG and raster export retain them. No new severity filter is needed for this revision.
- Apply this audit display only to Proof Check. Graphify's source-backed map does not acquire correctness grades. Shared math rendering and visual components remain shared.

Update `shared/paper_core/assessment.py` and `projection.py` to expose the derived display, and `renderer/render_projection.mjs`, `reader_content.mjs`, and `scientific_reader.css` to consume it. Check the native reader adapter in `scientific_reader.mjs` only where it consumes those statuses. Cover graph nodes, grouped edges, legends, summary cards, result detail, static index, obligation cards, accessible descriptions, and existing export/HTML receipt validation together. `publish.py` and `render_projection.mjs`'s representation receipt must validate the derived display instead of demanding the old logical-state color. Extend the existing rendering acceptance path, without adding another publication stage. Preserve the meaning of old assessment states in persisted scientific history.

## 5. Narrow data and compatibility changes

- Add optional `severity` to `BODY_SCHEMAS['findings']` and `WORK_FINDING` in `shared/paper_core/contract.py`. Omitted severity must remain valid for older records and incoming usable responses.
- Update `controller.py`'s separate `INTEGRATION_FINDING` optional-field declaration and both explicit finding-copy paths. An accepted severity must survive primary and reconciliation submissions rather than be silently dropped.
- Use the existing generated template/example/scaffold path in `assistance.py` and relevant authoring helpers. Provide the concise-card convention alongside the finding example. Independent source-only response shapes need no new mandatory severity opinion; the coordinator already creates formal findings.
- Leave severity unset in generic finding examples/templates until a finding is actually classified. Do not seed a default minor/moderate/severe value that can become an accidental judgment. New established findings should normally receive their rating in the existing integration; an omitted rating is neutral and does not block delivery.
- Ensure record retrieve/edit/save round trips preserve severity and existing IDs, source links, check links, and untouched fields.
- A classification-only update must update the visible report without invalidating unchanged mathematical examination. In `refs.py`, exclude only `severity` from the finding `full` facet used for mathematical freshness. No-severity legacy finding facets remain byte-for-byte equivalent to their previous calculation. Keep `storage.py`'s canonical `digest(body)`, version history, and frozen-report hash sensitive to severity, so reports remain attributable to the actual saved rating. Changes to category, target, evidence, description, impact, or resolution keep their existing consequential behavior. Do not exempt mathematical rewrites as presentation changes.
- Existing optimistic-concurrency version checks may still require refreshing a local edit template after another edit. Preserve those protections; refreshing a template is not repeating a mathematical examination.
- Do not rewrite old stores or frozen snapshots. Old records without severity are unrated; never guess a severity from `gap`, `refuted`, `presentation`, or the old red/amber color. A frozen projection lacking `review_display` uses a neutral historical-display fallback and preserves its saved logical assessments in text. Do not infer the assessment policy from the renderer's current `build.core_version`; `build.scientific_producer` retains the original producer. Historical v2 readers retain their historical meaning.
- The shared core requires an additive change, even though the policy belongs to Proof Check. Regenerate the two packaged core mirrors through the established bundling script after implementation; do not hand-edit three copies. Graphify must pass its unchanged-scope rendering regressions.
- No testing-harness change is needed. No installation, version bump, commit, or push is part of this planning request.

## 6. Focused implementation acceptance tests

These are development tests, not extra stages or checks performed during each paper audit.

1. **Scientific calibration:** replay the historical reversed-tuning sentence, plus a wrong justification with a known valid replacement, substantive same-assumption repair, genuinely restrictive missing assumption, practical tuning qualification, and explicit unsupported coverage claim. Confirm the rubric distinguishes their consequence without demanding repair construction or numerical work. Include unknown repairability and inherited-assumption controls.
2. **Contract and integration:** old finding accepted; severity retained through primary/reconciliation submission and record round trip; generated templates agree with accepted schemas; a severity-only edit changes display but leaves unchanged examination freshness intact; a mathematical evidence/target change still affects normal freshness.
3. **Status and aggregation:** current versus stale/resolved issues under existing freshness rules; mixed graded/ungraded issues; multiple findings on one node; an established rated issue plus a separate unresolved disagreement; a finding whose own validity is disputed; an inconclusive finding carrying a supplied severity; unaffected alternate route; dependency-only uncertainty; initial review with pending independent review; incomplete/no findings; Graphify has no audit-severity leakage. Missing ratings do not become a delivery blocker.
4. **Cards and math:** generate one fixture report with all five visual states, the tuning formula, a short analytical witness, a textual citation issue, a long older finding, and an unavailable source. Exercise summary-to-result-to-evidence links and the existing math coverage/receipt checks. No second authored card representation.
5. **Actual rendered UI:** one batched browser inspection at wide and narrow widths in light and dark themes, plus existing print/export checks. Verify clear orange/yellow distinction, readable contrast, labels without color dependence, keyboard details, and long formula containment. Fix observed defects once and confirm affected cases. Passing schema/unit tests alone is not a claim that rendering was visually verified.

## 7. Expected workload

Per finding, the extra authored datum is one severity choice. The short explanation and mathematical reason replace the current free-form finding prose; they do not duplicate the full examination. Classification uses reasoning already produced. The renderer handles layout, labels, color, and links deterministically. Routine work should be comparable or smaller, particularly when removing mandatory external-source hunts and publication-time prose reconstruction. No measured runtime saving is claimed.

Do not add a hard word-count gate, completeness gate for severity, per-assumption ledger, repair-attempt record, external-reference queue, numerical validation task, or repeated independent review. A difficult uncertainty can finish as an explicit limitation within the existing scope.

## Validation record

Three independent Sol 6.1 xhigh agents reviewed scientific calibration, data/workload compatibility, and UI/display behavior, with a 10-minute limit per job. Their initial findings changed the plan in the following ways:

- Eight synthetic scientific cases exposed the difference between an assumed easy repair and an immediate valid correction, a conventional versus genuinely restrictive moment assumption, a harmless tuning qualification versus a false adaptive guarantee, and local falsity versus paper-level consequence.
- The data reviewer ran an isolated real intake probe with an in-memory optional severity schema. Submission succeeded and added zero checks, but the current builder silently dropped severity. The plan explicitly fixes both intake whitelists and the copied integration schema.
- Existing mathematical finding freshness hashes include all fields. The plan excludes only severity from that facet while retaining full stored/frozen content identity, and leaves ordinary edit-concurrency protections intact.
- The UI review confirmed existing math-capable finding fields suffice, identified old logical-color receipt assumptions, and found the standalone SVG export selector restriction. These are included in the implementation scope.
- Alternative valid routes, ungraded older findings, inconclusive concerns, and review/coverage badges now have explicit display rules. No new filter or extra review gate is included.

The same three agents then independently reread this written handoff in jobs limited to five minutes. Their required narrow corrections were incorporated: preserve the admissible parameter range in the sample formula; state precedence when an established issue and an unrelated uncertainty coexist; use existing finding freshness rules without creating a new reassessment mechanism; and leave severity unset in generic examples/templates. The parent verified these corrections against the reported concerns.

The record above describes the original plan validation: eight scenario classifications, source/code-path inspection, and one real isolated intake probe. The subsequent implementation and its bounded validation are recorded separately. Neither record establishes measured runtime savings or actual browser appearance.
