# Deliver the recorded result

Stage 2 finalization freezes one assessed revision and saves its scope, findings, limitations, source identity, producer identity and content hash. Stage 3 consumes that snapshot without accessing live scientific state.

Deliver audit.db, the frozen summary and report.html. The database and frozen summary retain administrative tracking; the HTML presents the paper's mathematics, examination reasoning, findings and scientific limitations. Take completion and actual review scope from the frozen result. Registered assignment counts do not measure manuscript coverage and need not appear in the reader's report. A saved response or successful command does not by itself fulfill its required work. State what was actually examined and independently reviewed, including known exclusions or coordinator-only inspection. Use the existing `--partial` finalization option for known unfinished promised review that the registered counts do not represent. Prefer "no load-bearing defect found within the stated non-formal scope" to an unqualified correctness claim.

Use saved statements, passages and explanations without requiring new authoring. Keep the paper's argument distinct from examiner judgments and proposed repairs. Preserve consequential conditions, disagreements, source limitations and partial or historical review qualifications. Missing optional summaries or scope metadata do not by themselves establish missing mathematics. Omit empty optional sections; a presentation repair uses the same frozen result.

## Concise issue cards

Author one finding during examination or integration using the existing fields;
the renderer reuses it in the issue summary and selected-result view. Apply the
[research-severity rubric](evidence-and-verdicts.md#research-severity), without a
separate card-writing or publication-time scientific pass.

1. Header: rated severity and the affected theorem, step or application, such as
   **Minor · Theorem 3.3**. Missing severity displays **Severity not rated**.
2. `description`: one short issue sentence, with one decisive display equation,
   inequality, implication or short exact witness when useful. A named missing
   condition or textual correction suffices when a formula would be artificial.
3. `impact_reason`: one short sentence saying what remains valid and what changes.
   Include an already apparent correction only when useful; no repair is required.
4. Source locator or link from existing evidence references. Details retain saved
   examination reasoning, assumptions, limitations and historical resolutions.

Aim for two or three short sentences plus one decisive mathematical block when
useful, drawn from already recorded reasoning. Keep derivations, further examples
and speculative repairs in examination details. This is an authoring guideline,
not a word-count gate. Define unfamiliar symbols locally;
do not require a second derivation, parse severity from prose, truncate LaTeX or
create parallel card records. Preserve complete older findings in details without
bulk rewriting or mandatory backfill.

For example:

**Minor · Theorem 3.3**

The sentence reverses the direction of the tuning relationship.

\[
\lambda_n(\tau)=n^{-1/[2(\tau+2)]},\qquad
\frac{\partial}{\partial\tau}\log\lambda_n(\tau)
=\frac{\log n}{2(\tau+2)^2}>0\quad(n>1,\ 0<\tau\le1).
\]

Within the stated range, larger \(\tau\) gives larger \(\lambda_n\); correcting
the sentence leaves the displayed bound unchanged. Source: page 22.

## Display meaning

Use the frozen derived display consistently: red **Severe**, orange **Moderate**,
yellow **Minor**, green **Checked**, and neutral gray for the specific limitation
such as **Not assessed**, **Unable to assess**, **Severity not rated** or
**Depends on unresolved result**. These colors describe current applicable issue
severity or assessment status. Show the logical outcome, exact-target support and
actual review level separately in text. Explain once per report that checks are
LLM mathematical assessments.

Use the highest applicable established current severity within the represented
scope, counting each finding once. Resolved, superseded, stale and historical
findings remain accessible but do not grade current work. A disputed or
`inconclusive` finding stays neutral even if it carries a severity value; a separate
established rated issue retains its color with any unrelated uncertainty shown.
Mixed rated and unrated concerns must expose the unrated count. Use existing
target, owner and explicit affected-use relationships, without mechanically
propagating severity through dependencies or creating duplicate findings.

Green requires positive current examination and no applicable open issue or
unresolved support blocking that status. Preserve initial-review eligibility and
label the independent-review status; no additional review gate is required.
Unexamined assumptions and definitions stay premises. Alternative valid routes
may preserve exact-target support while a defective route remains visible.
Global findings stay global unless their recorded scope establishes local impact.
Administrative warnings and pending work use neutral text. Labels and accessible
descriptions accompany colors in the report and export. Historical snapshots
without derived severity display use a neutral fallback and retain saved logical
assessment text. This grading applies only to Proof Check, not Graphify.

## Release integrity

A published report with a temporary-cleanup warning is delivered; cleanup alone does not require rebuilding it. A working report does not establish completion of the promised audit scope, even when its registered examinations are complete.

Gaps, refutations, inconclusive conclusions and integrated disagreements may occur in a completed release. This includes an assessed omission of proof or an unavailable external source, without claiming the missing mathematics was verified. Missing promised examinations, review or supplied material produces working output. Reporting a limitation does not make unperformed work complete.

A rendering error leaves the database and frozen results valid. Correct presentation against the same input; preserve prior reports on failure. A material scientific correction produces a new snapshot after affected examination.

Do not overwrite source files, the database or frozen input with a report. Historical v2 stores keep their original completion meaning and require their compatible reader.
