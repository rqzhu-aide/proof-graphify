# Stat Proof Check

[![Version v3.4.10](https://img.shields.io/badge/version-v3.4.10-0ea5e9)](SKILL.md)

Version `3.4.10` audits a paper's written mathematical arguments. It records exact claims, source evidence, consequential inferences, independent review, findings, and unresolved limits, then delivers an interactive HTML report. This is a scoped, non-formal examination; a successful database check or report build does not certify a theorem.

## Use

Install this `stat-proof-check/` directory under its existing skill name in a user-wide skill root. From the [repository root](https://github.com/rqzhu-aide/proof-graphify/blob/main/README.md), the validated installer can install it into the Agents and Claude skill directories:

```powershell
python -B tools/install_proofcheck.py --source stat-proof-check --target agents --target claude
```

Use `--upgrade` for an existing installation. Preserve `allow_implicit_invocation: false` and the Claude `"stat-proof-check": "user-invocable-only"` override. Invoke the skill explicitly:

```text
Use $stat-proof-check to audit this theorem and its prerequisite arguments.
```

Choose Triage for mapping suspected issues, Focused for selected results and their necessary prerequisites, or Full for the manuscript and supplied supplements. The [skill instructions](SKILL.md) define scope and the scientific standard. The workflow prepares source evidence and primary examinations, obtains independent review and integrates findings, then renders a frozen result. Proof omissions and unresolved disagreements remain findings; the skill does not silently repair the manuscript's mathematics.

## Outputs and continuation

```text
proof-check-<paper-name>/
  audit.db
  work/
  frozen/summary.json
  report.html
```

Keep the database and frozen artifacts for continuation. Report what was examined and independently reviewed, together with material omissions and source limits. New audits start independently from the manuscript in their own folder and database, including when a Graphify overview already exists. Start with the [database workflow](references/database-audit.md), and use the [controller workflow](references/controller-workflow.md) for continuation commands.

## Runtime and compatibility

This package bundles `paper_core` version `3.3.15` and runs independently of Graphify and the source checkout. Shared Python 3.10+ runs the helpers; Node.js produces the HTML report. Optional offline LaTeX conversion uses shared `latex2mathml`. Install missing dependencies globally or user-wide.

Version 3.4.10 bundles paper core 3.3.15, typesets saved resolution equations and places Source evidence at the end of the report. Final delivery stays within saved facts. Accepted corrections carry into already known affected current assessments using existing saved examinations, without a new review pass or final sweep.

Version 3.4.9 retains paper core 3.3.14 and clarifies formula serialization, inherited setup, application coverage, external premises, rate comparisons and normalization severity. Existing finding updates and delivery reuse saved reasoning and qualifications. No review pass, required retrieval or repair search is added.

Version 3.4.8 bundles paper core 3.3.14, renders math in explanatory fields and simple terminal equation tags, and exposes saved source-capture notes and links to source-review evidence. The delivery brief preserves those notes. Surgical writing and integration clarifications add no review pass or repeated scientific check.

Version 3.4.7 bundles paper core 3.3.13, fixes integral-spacing and sized-floor display, and clarifies mathematical delimiters and independent response fields. Delivery preserves saved finding statuses and aggregate counts without guessing omitted entries. No review pass, source comparison or retrieval task is added.

Version 3.4.6 bundles paper core 3.3.12, renders bounded triple-bar norm spacing, and clarifies saving already-established findings during normal integration. Delivery preserves frozen outcomes, severity and reviewer qualifications without adding judgments, review passes or retrieval.

Version 3.4.5 bundles paper core 3.3.11, corrects linked finding badges and mathematical-spacing display, improves prerequisite placement, and includes saved external-source qualifications in delivery. Clarifications distinguish neutral metadata from opinion exposure, preserve returned claim identities and bundled scope, and identify glyph extraction as extraction. They add no review pass or forced splitting.

Version 3.4.4 bundles paper core 3.3.10, corrects immutable-source recovery guidance, clarifies Full-audit scope, and separates local finding counts from examination outcomes. Delivery reuses saved scope notes, and the source-response reminder preserves the existing inspection standard without adding review work.

Version 3.4.3 bundles paper core 3.3.9, corrects completed-examination recovery guidance, and reports current reconciled outcomes with compact saved reviewer context. Source and delivery clarifications preserve unresolved limitations without adding a review pass or backfill work.

Version 3.4.2 bundles paper core 3.3.8, supplies a frozen delivery brief, and clarifies source declarations when consequential PDF mathematics has not received the required inspection. Final messages reuse saved facts and qualifications; no review stage, source pass or proof check is added.

Version 3.4.1 bundles paper core 3.3.7, keeps local findings from blocking unaffected conclusions, and recognizes already-checked public theorem applications across named setup differences. It clarifies finding targets and application mappings while preserving private scopes, genuine defects and existing review work.

Version 3.4.0 adds concrete mathematical-scope examples to the existing reconciliation guidance, distinguishes source transcription errors from established source defects, and reuses adequate evidence and unaffected completed work. It retains paper core 3.3.6 and adds no review stage or checklist.

Version 3.3.10 bundles paper core 3.3.6 and clarifies correcting already-known source-record errors before dependent work, reusing applicable reasoning after local corrections, and continuing source-only review without treating it as a new independent vote. It preserves current-record binding, reviewer exposure and coverage requirements without adding review stages or repeated checks.

Version 3.3.9 clarifies supplier roles at authoring, complete mathematical statement selection, and how a contradicted premise affects a claimed application. It consolidates existing guidance without adding examinations, review stages or repair searches. The shared core remains 3.3.5.

Version 3.3.8 narrows application guidance to assessing the supplied inference, preserving explicit assumptions as premises, and assessing available justification for separately asserted properties. It retains same-claim/context reuse and required independent review without adding a review stage or proof-construction duty. The shared core remains 3.3.5.

Version 3.3.7 clarifies formula grouping during existing source reading, the mathematical consequence of hypothesis corrections, and coverage of substantive applications while reusing examinations that already address the same claim and context. It adds no examination or review stage and retains paper core 3.3.5.

Version 3.3.6 bundles paper core 3.3.5, fixes bounded multiline math conversion, and reduces repeated source excerpts in the HTML search payload while preserving search results and navigation. It clarifies where adopted source corrections belong and how to treat supplements already inside the supplied PDF. No examination or review stage is added.

Version 3.3.5 bundles paper core 3.3.4. It corrects support propagation for definitions used as notation context without granting their mathematical properties proof credit, fixes narrow-screen review-card layout, and consolidates repeated examiner instructions. Scientific standards and assigned work are unchanged.

Version 3.3.4 clarifies how to retain conflicting source formulations and unresolved mathematical notation during the existing examination. It adds no review stage or repair work and retains paper core 3.3.3.

Version 3.3.2 combines assessments, current issues and limitations in one Review card, followed by an optional saved proof idea and compact prerequisites. Exact conditions and evidence remain available. Optional explanations are written during existing source reading; this release adds no backfill, examination or review stage.

Version 3.3.1 corrects sized norm bars, prioritizes exact labels and aliases in search, and routes current result matches to their own cards while preserving historical evidence destinations. These renderer changes add no examination or review work.

Version 3.3.0 displays recorded hypotheses as neutral connections to their consuming results and improves reader navigation, graph framing and mathematical display. Hypothesis connections reuse saved target scopes and add no proof duties, review pass or duplicate authoring.

Version 3.2.8 corrects the recovery command for editing audit records and clarifies response coverage fields, inherited premises, unresolved interpretations and Full coverage of unnumbered arguments. These changes act within the existing workflow and add no review pass or retry loop.

Version 3.2.7 emphasizes decisive mathematical structure, clarifies the response conditions field, and places concise LaTeX issue-card guidance at the point of authoring. It adds no examination, review round or publication-time rewriting. It also fixes findings whose unresolved status depended on the order of linked examinations. It retains the Archify 3.0.1 reader, export colors, detail links and shared-owner assessments introduced in 3.2.6.

New audits use `coherent-proof-audit/1`, the `coherent-examinations/1` feature, storage format `4`, and record contract `4`. Historical v2 audits retain their original protocol and compatible runtime. See [database compatibility](references/database-compatibility.md), the [implementation boundary](IMPLEMENTATION.md), and the retained [validation record](VALIDATION.md).

The 3.2.4 source-fidelity correction renews affected pending statement-only review packets that copied examiner notes into source context. It does not rewrite completed reviews or frozen reports. Historical `source_only` labels on those affected reviews were recorded before this correction and are not retroactively certified; a reviewer who already read the note needs a fresh context for a new blind examination. Original notes and legitimate source caveats remain preserved.

[MIT license](LICENSE)
