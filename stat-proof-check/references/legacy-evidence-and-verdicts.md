# Legacy v1.5: Evidence and Verdicts

This file is the canonical contract for evidence strength and proof-audit judgments. Issue lifecycle rules are in [issues-and-repairs.md](issues-and-repairs.md), and independent challenger rules are in [challenge-protocol.md](challenge-protocol.md).

## Evidence classes

Keep three classes separate:

1. **Observed:** explicitly present in the manuscript or verified external source.
2. **Inferred:** a reviewer reconstruction supported by observed material.
3. **Not established:** missing, ambiguous, externally unchecked, or dependent on unresolved work.

Every strong judgment must cite exact manuscript lines, theorem or equation labels, pages, or verified external theorem locations.

## Evidence specificity

Evidence must identify the paper-specific claim, objects, premises, operation,
source anchor, and observed success or failure relevant to that record. It
cannot merely restate a status or generic checklist.

Under evidence contract 5, final validation treats exact normalized wording
repeated across at least four distinct, unrelated substantive steps as nonspecific when it
appears in `checks.literal`, `checks.atomicity.evidence`, a move
`justification`, or `checks.adversarial`. It also treats the same risk
evidence reused across at least three distinct aspects within one step, or
across at least four unrelated applicable-risk steps, as nonspecific. A
paper-specific `not_applicable` row is excluded from the cross-step
applicable-risk count, but not from the within-step cross-aspect check.
Repetition below these thresholds is not positive evidence of specificity, and
cosmetic wording changes do not make generic evidence adequate.

Evidence contract 5 also anchors evidence to the source. For every derivation
or reuse step whose locked source unit contains an extractable mathematical
object name (a subscripted identifier such as `X_{n,j}` or `m_n`, or a plain
identifier inside a math segment; TeX control-sequence names excluded), the
union of that step's authored evidence, including atomicity, adversarial, justification,
failure, and risk evidence, excluding the literal transcription and the
restatement, must name at least one such object. A unit with no extractable
token is exempt. Anchoring is a floor: naming an object does not make
otherwise generic evidence adequate.

`annotation-check` additionally reports advisory `near_duplicate_evidence`
warnings for authored evidence strings from different steps that are at least
90 percent similar. Warnings never fail the check; treat them as a prompt to
replace shared boilerplate before compilation.

## Assurance boundary

This protocol is non-formal. It can provide high assurance through exact source coverage, independent reconstruction, dependency closure, adversarial search, and a fresh independent check of every in-scope unit. It cannot provide the soundness guarantee of a small proof-assistant kernel.

Mechanical validation establishes that source hashes, normalized-field
dispositions, premise origins and active reference anchors, exact
reference-occurrence dispositions, `Dxxx` dependency-use mirrors, atomic move
links and reachability, source-unit coverage and hashes, one-move inferential
steps and their support roles, structured failure and status links, risk
dispositions, joint side-condition discharge, and per-conclusion support
closures are present and internally consistent. Audit-wide validation also
establishes that the reviewed closure registry matches the current source
snapshot, inventory, and scope; every direct dependency has one exact use
record; obligation and external-evidence hashes are current; compatibility and
global-consistency matrices are complete; statuses and issues propagate; and
progress and report claims reconcile. It does not establish that the
mathematics written in those fields is true.

The local active-anchor check is conservative and static. It rejects commented
labels and labels inside disabled or unresolved conditional branches, but it
also masks common command and environment definition bodies, inline `\verb`,
and common verbatim-like environments. It still does not expand macro
invocations or execute TeX. Unrecognized or dynamically generated definitions,
verbatim constructs, and labels can evade static masking. Inspect them during
manual source-resolution review, and do not rely on the local active-label
result alone.

Mechanical validation also rejects unresolved placeholders throughout the
normalized obligation and substantive proof or evidence fields. Exact `unclear`
is allowed in normalized fields only with a matching `unclear` disposition. A
status such as `not_applicable` does not replace paper-specific evidence
explaining why the aspect is absent. Record the mathematical content, the
observed failure, or an appropriate nonverified status.

## Unit verdicts

Use one verdict per proof unit:

- `verified`: all source lines and substantive steps checked; every premise is
  anchored, every declared dependency is verified, every risk is passed or
  specifically not applicable, and every side condition is discharged.
- `conditionally_verified`: each unresolved cause is explicit and maps exactly
  to an open side condition, conditional or unchecked dependency, or open risk.
- `gap`: a necessary claim is not established.
- `incorrect`: a definite invalidity or counterexample is established.
- `unclear`: ambiguity blocks a defensible conclusion.
- `not_checked`: detailed checking is incomplete.

Do not average step statuses. The weakest load-bearing step controls the unit verdict.

A verified step cannot inherit an open, failed, unclear, unchecked, or
conditional load-bearing input. A conditional step cannot hide a failed or
unclear dependency or risk. The structured condition list must be an exact
bijection with its unresolved causes. The unit verdict remains the weakest
substantive step verdict; component judgments can impose additional gates but
cannot upgrade that verdict.
Keep these judgments separate:

- `contract_fidelity`: whether the normalized obligation faithfully matches the stated result;
- `argument_status`: valid, conditional, gap, invalid, unclear, or not checked;
- `statement_status`: established, conditional, refuted, not established, unclear, or not assessed;
- `dependency_closure`: whether every load-bearing dependency resolves with compatible assumptions and conclusions;
- `use_site_sufficiency`: the audit-wide projection of whether the established
  result is sufficient where later used. It is derived from outgoing internal
  dependency edges after closure and is never checker-authored.

Derive dependency availability from the named conclusion's contract,
argument, statement and closure; other conclusions and unit summaries cannot
cap it. An established conclusion normally supplies `verified` when its
contract, argument, and closure are verified; any conditional component
supplies at most `conditional`. A refuted conclusion supplies `incorrect`. A
`not_established` conclusion supplies `gap` even after an invalid argument.
Unclear or unassessed conclusions supply `unclear` or `unchecked`; an invalid
proof alone does not refute its statement. The optional
[checked supplement](statement-support.md) preserves written defects and
supports a statement or restricted use only with current immutable reviewer
acceptance. Primary readiness is provisional.

Each `Cxxx` conclusion has one `review.conclusion_results` row supported by an
exact checked move. Its component judgments, obligation-pointer use,
dependency-use closure, and issues are conclusion-specific. For `established`
or `conditional`, that move must reach the exact conclusion claim. For
`refuted`, `not_established`, or `unclear`, it must preserve the actual failure
or mismatch. Without a separate supplement, its step status must agree with
the conclusion judgment. Use
`review.conclusion_step_id` only as the single-conclusion support-step alias;
leave it empty for a multi-conclusion result. The unit-level `statement_status`
is the weakest conclusion judgment.

An `established` or `refuted` statement requires `contract_fidelity: verified`.
A `conditional` statement requires `contract_fidelity: verified` or
`conditionally_verified`. Strong judgments require a faithful normalized target.

An invalid argument establishes a defect in the proof, not the falsity of the
theorem. Use `refuted` only when an exact counterexample or contradiction
establishes that one recorded conclusion itself is false. Its support move must
record the matching `counterexample` or `contradiction` failure kind, issue
link, and evidence, with `failure.target` exactly equal to that conclusion's
claim.

## Method-interface judgments

For a triggered estimated interface, keep the proof-unit judgments above unchanged and record these additional relations in `METHOD_INTERFACE_REGISTRY.json`:

- `interface_specification_status`: `clear`, `ambiguous`, `incomplete`, or `not_checked`;
- `derivation_status`: the status of the mathematical derivation, kept separate from prose clarity;
- `target_relation.verdict`: `match`, `conditional_match`, `mismatch`, `not_assessable`, or `not_checked`;
- `implementation_relation.inspection_status`: `inspected`, `available_not_checked`, `unavailable`, `out_of_scope`, or `not_applicable`;
- separate code comparisons to `documented_estimator` and `required_target`, each with verdict `consistent`, `inconsistent`, `not_assessable`, `not_checked`, or `not_applicable`;
- `implementation_relation.execution_provenance.status`: `matched`, `not_matched`, `not_checked`, or `not_applicable`.

`conditional_match` requires an explicit named condition supported by the source. Do not use it for an unspecified manuscript meaning. If two plausible readings select different targets and the source does not choose between them, use `not_assessable` and record both interpretations.

Ambiguity can be load-bearing and severe. It does not, by itself, establish which target or implementation is wrong. A `mismatch` requires authoritative evidence that fixes both compared objects. Static code inspection can establish only what the inspected snapshot computes. It does not establish that the same code, run configuration, preprocessing, inputs, and output linkage produced reported experiments.

Keep the two code comparisons separate. Code can be consistent with the documented estimator while inconsistent with the theorem-required target because the documented estimator itself is wrong. Classify that as `estimator_target_mismatch`, not a coding defect. Use `implementation_mismatch` when the code is inconsistent with the documented estimator.

When the documented estimator itself remains ambiguous, code may still be compared directly with the required target, but the code-to-documentation verdict is ordinarily `not_assessable`. Do not let code silently choose the manuscript's intended meaning.

Execution provenance affects the proof assessment only when execution linkage is required for the declared claim. A missing link is then inconclusive, while an established required non-match is a defect. Neither state invalidates an abstract theorem that explicitly assumes an oracle nuisance condition and does not claim that the implementation establishes it.

## Severity

- **S0 Fatal:** the main theorem or central claim does not follow in the stated form, with no local repair established.
- **S1 Major:** a load-bearing assumption, dependency, or inference is missing or wrong, but a plausible repair may exist.
- **S2 Moderate:** a local gap, ambiguity, scope mismatch, or incomplete justification affects confidence but may not change the main result.
- **S3 Minor:** a typo, label, notation, or exposition defect does not change the mathematical argument.

Severity measures consequence, not certainty or repair difficulty.

The S0/S1 boundary is an evidence-backed judgment, not an assertion: every S0
or S1 issue carries the `repair_search` record defined in
[issues-and-repairs.md](issues-and-repairs.md), documenting the bounded repair
strategies actually attempted and where each fails. Assign S0 only after the
recorded strategies fail; assign S1 only with a recorded strategy that
survives local inspection.

S0 and S1 issues are load-bearing by definition. Any open or deferred S0 or S1 issue, and any lower-severity issue explicitly marked load-bearing, prevents a `no_defect_found` assessment.

Independent-check coverage is exactly the in-scope unit set defined in
[challenge-protocol.md](challenge-protocol.md). Severity determines which
neutral issue targets a checker must assess; it never changes unit coverage.

## Confidence

- **high:** exact evidence plus reconstructed reasoning or a concrete counterexample.
- **medium:** strong evidence remains dependent on interpretation or an unchecked fact.
- **low:** a plausible concern requiring further analysis.

High severity with low confidence is a priority for checking, not a proven failure.


## Verification burden

"Verified" requires positive support. The following are insufficient:

- the step is familiar;
- a similar theorem is standard;
- the manuscript compiles;
- symbolic software returns the expected expression on examples;
- no counterexample was found;
- the authors cite a relevant-looking paper;
- a downstream theorem would be true if the step held.

When evidence is incomplete, downgrade the status rather than filling the gap from mathematical taste.

## Proof-only checking and historical computation

The current [proof-only boundary](evidence-and-verdicts.md#analytical-refutations-and-unresolved-examinations)
also applies to resumed audits: use mathematical derivations, not new numerical
experiments. Preserve historical computational evidence without rerunning it;
supplied experimental results cannot replace a mathematical argument.

The legacy `failure.computation` contract and finalization gate remain intact;
see [line-by-line-protocol.md](line-by-line-protocol.md). Do not invent a script
or result, or use `not_instantiable` merely because execution is outside scope.
If that gate requires an experiment for a new analytical finding, preserve the
derivation in an unfinalized finding/handoff and explain the compatibility limit.
The user may choose the existing explicit import into the current database
workflow. Do not migrate automatically or reinterpret legacy outcomes.
