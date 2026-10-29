# Evidence and outcomes

This reference governs current database audits.
Read [mathematical-checking.md](mathematical-checking.md) for how to examine an inference.

## What the evidence establishes

Separate material observed in the manuscript or an inspected external source,
reasoning and mathematical knowledge used by the examiner, and claims not established
by available evidence. Cite exact source anchors, statement parts, equations, or inspected
external result locations. Do not imply a remembered result's publication was inspected.
Explain the particular premises, operation, and success or failure;
repeating a verdict or a generic checklist is not evidence.

Source comparison asks whether the saved statement or connection agrees with its
source and applicable setup. It does not establish mathematical correctness.
Compare the actual saved wording. Missing conditions in that wording cannot be
excused by an accurate note or source excerpt.

Mechanical validation checks the consistency and currentness of recorded evidence.
It does not discover an omitted premise, confirm complete proof boundaries, or
prove the mathematics. This audit has no formal proof-kernel guarantee.

## Examination coverage

`extent` and `omissions` describe examination coverage, not the mathematical outcome.
Use `whole_unit` when the assigned supplied material has been examined, including
assessment of a manuscript's omission of proof. An assessed unavailable external
citation can also finish with a limitation. Put assessed defects and uncertainty
in reasoning or findings, preserving registered conditions. Assigned supplied
material still unexamined, including unreadable passages needed to assess the
question, leaves that part unfinished: use `partial` and name it in `omissions`.
Never clear omissions or upgrade partial coverage solely to obtain acceptance.
Unrelated discoveries do not create required assignments.

## Reviewer source navigation and citations

The packet fixes the assigned question and registered citation IDs. The generated
`source-navigation.json` is an optional index of all its source anchors, including
prerequisites and continuations. Identify pages by source and version. Matching
originals remain usable; an index entry does not mean a passage was inspected.

Use only packet-registered IDs in `evidence_refs`. Other inspected material may be
identified by traceable locators in reasoning or coverage notes, retaining its
limitations; prose citations do not bind evidence or establish support. Repair
harmless citation formatting without repeating examination. When support relies
on newly consumed evidence, the coordinator captures it and prepares the affected
assignment. For an unchanged independent question, use the existing context
extension and return an honest response naming that packet. Reuse current reasoning
and already examined passages; examine only material still unexamined or materially
changed, or leave support unresolved.

## Local outcomes and statement availability

A completed examination uses one of these outcomes:

| Outcome | Meaning |
|---|---|
| `supported` | This exact local obligation follows under its represented premises and scope. |
| `gap` | The supplied argument does not establish its obligation; identify the missing or invalid inference. |
| `refuted` | Exact evidence contradicts the assertion being examined under its claimed hypotheses. |
| `inconclusive` | Substantive examination cannot resolve this obligation with the available evidence. |

Report a substantive unresolved examination as **Unable to verify**, with
`state: complete`, `outcome: inconclusive`. A saved completed examination may be
partial; its named omissions still leave the unit unfinished. Use a draft when
the returned examination itself is unfinished. Inability to verify alone
establishes no manuscript defect.

Keep four facts separate: what was examined, its local outcome, whether the exact
statement is available in the consumer's premise context, and whether the audit's
required work and review are complete. A locally supported implication can depend
on an unproved supplier. If a required supplier is refuted, that route does not
establish its conclusion, although the implication itself may remain valid.
Describe that known failure explicitly rather than calling it merely pending.

All required inputs of one inference must hold together. Different complete
routes to the same exact target can provide alternative support. A defect in one
written route remains reportable even when another establishes the statement.
A self-supporting cycle supplies no foundation. Checking selected parts cannot
establish unexamined parts or the whole theorem.

`checks.conditions` explains restrictions already represented in the exact target
and scope. It cannot add an assumption while retaining unconditional support.
Each entry must exactly match an entry in the applicable `scopes.conditions`,
including inherited scopes. The store does not infer equivalence between prose
paraphrases. Explain binder domains and target hypotheses in `reasoning`; leave
`checks.conditions` empty when no separately listed scope condition is invoked.
An unmatched condition keeps availability conditional even when the local check
is complete. A real extra restriction requires a separately scoped target or route.

## Omitted arguments, unavailable sources and restrictions

A supplied exact theorem statement permits checking its application under that premise even when
its proof is outside this assignment. If the manuscript omits an argument, assess the supplied material and record the omission as a gap when justified, or as inconclusive when its significance is uncertain. Do not construct a proof route merely to register or finish that finding.

A proof or passage that is present in the supplied material but unavailable to the examiner remains a coverage limitation. An uninspected external citation is different: assess its needed statement and application from supplied material and reliably known mathematics, stating the basis and any uncertainty. External retrieval is not a default duty. Follow [external-result-verification.md](external-result-verification.md); routine facts need no separate lookup. Never describe an uninspected source as inspected.

Call a manuscript gap only when an actual missing or invalid manuscript inference is identified. Coverage follows the examination rule above, independently of this outcome.

Adding \(\pi_n\to0\) does not establish a source theorem allowing fixed positive \(\pi_n\).
Correct the saved assertion or identify a restricted target; an accurate prose note cannot repair it.
An inspected external statement, a short hand-written deduction and a remembered
theorem are distinct bases for an LLM assessment. Numerical consistency supplies no proof credit.

## Analytical refutations and unresolved examinations

A failed written proof does not show a false theorem. Finding a counterexample is not required to finish an examination. If a statement refutation is claimed,
state the exact assertion and explain the decisive contradiction under its hypotheses.
When a counterexample is the basis, its witness must satisfy **all** hypotheses and
show the actual violation in the claimed regime. Record the refutation as
a `statement_refutation` finding, linked to the supporting examination and evidence.

For example, to refute “for every sequence \(p_n\ge1\), \(p_n/n\to0\),”
choose the admissible sequence \(p_n=n\) and compute \(p_n/n=1\) for every \(n\).
A test with a fixed \(p\) cannot refute or verify that universal growing-sequence claim.

Use short hand-written deductions and exact equations to explain an immediately
apparent witness. Do not turn refutation into a counterexample search. Do not run
simulations, numerical validation, symbolic verification, parameter sweeps, optimization or random searches,
empirical experiments, numerical solvers, interval validation, computer algebra or
proof assistants to establish mathematical truth. Supplied experimental results are context,
not proof credit. Source extraction, PDF inspection, database arithmetic, hashes,
rendering and software regression tests remain ordinary tooling.

For an unresolved examination, name the exact inference and why the available
reasoning cannot resolve it. Finish with that specific limitation and continue
other useful proof work; do not generate numerical follow-up or retry unchanged work.

## Findings, disagreements, and repairs

Separate the finding's mathematical content, consequence, evidential confidence and
research severity. State whether it affects one application, a written route, the
exact statement or a later use. Use an evidence-backed impact explanation and the
rubric below; no legacy severity, repair-search or per-line risk ledger is required.

Ambiguity is not a proved mismatch. For encountered competing readings or differing
source formulations, identify them and their source passages, and state the source
basis of any formulation saved or assessed; retain unresolved ambiguity. Likewise,
separate an estimator's relation to a theorem's target, implementation consistency
with that estimator, and evidence linking the inspected code to reported experiments.
A missing execution link does not refute an abstract theorem assuming an oracle.

A plausible repair stays provisional; failure to discover a repair does not show none exists.
Describe an already apparent correction without constructing a new proof route.
An obvious one-line correction or routine justification inside the examination is not
a replacement proof and needs no separate route or reviewer. An actually authored
replacement proof of the unchanged statement needs a separate route, provenance and
actual examination and independent review; a restricted replacement statement needs
its own target. Its sufficiency remains provisional until that mathematics and its
required review are completed. Do not construct a replacement proof merely to choose
severity. Keep the original proof's judgment. Checked sufficiency does not mean the
manuscript was edited or its original defect resolved.

Preserve independent response bytes and original outcomes. Reconcile conflicting
judgments on the same exact question with explicit reasons, retaining unresolved disagreement when appropriate.
A statement refutation and a conditional application are different questions;
do not change the latter's outcome merely to display the former.

## Research severity

The optional finding field `severity` is `minor`, `moderate` or `severe`. Omission
means not rated. Judge consequence, location and known repair scope together within
the existing examination and coordinator integration. Do not infer severity from
category, logical outcome, confidence or color. This is the user's research-review
calibration, not a universal journal grading standard.

| Severity | Decision rule | Typical example |
|---|---|---|
| `minor` | An obvious local correction or justification preserves the claim and intended application. | Harmless notation; a wrong justification with an immediately identified valid replacement under the same premises. |
| `moderate` | A substantive local derivation needs correction and available reasoning identifies how the result is preserved under stated assumptions; or a bounded qualification or loss of an ancillary claim leaves the main contribution and intended regime intact. | A missing term with a known local correction; removal of an erroneous unused auxiliary claim. |
| `severe` | Evidence identifies material failure of an important conclusion or intended scope. | A genuinely restrictive missing assumption, changed principal rate or false important statement. |

- A merely plausible rescue does not establish easy repair. Merely avoiding a new
  assumption does not make a difficult missing proof moderate. State uncertain repairability.
- Distinguish correcting exposition or a justification from correcting an actual
  derivation. An easy repair of a wrong intermediate bound is still moderate:
  combining two events of probability at least \(1-\delta\) gives only
  \(1-2\delta\); reallocating \(\delta/2\) to preserve the intended guarantee
  corrects that derivation. An isolated typo surrounded by the correct calculation,
  or a wrong theorem name with the exact inequality already justified, is minor.
- Check inherited setup first. A condition already inherited is not an added
  assumption or defect. Judge a hypothesis correction by its known effect on the
  exact stated claim and intended applications, not the size of the textual edit;
  explain that effect briefly in the existing finding reasoning. A routine omitted
  qualification that changes no intended model or conclusion can be minor; a
  familiar condition excluding important intended distributions or regimes can be
  severe. Mathematical familiarity informs this judgment without requiring a
  literature search.
- Separate conditional theorem validity from a material limitation of its important
  intended regime; retain that limitation and explain its consequence. If supplied
  setup contradicts a premise needed for a claim that the result applies, attach
  the finding to that application; finite fitted values do not remove the
  contradiction. An accurately
  disclosed benchmark restriction need create no defect, and conditional validity
  alone neither establishes severity nor dismisses the limitation. Practical tuning
  outside a theoretical guarantee ordinarily warrants at most a minor qualification
  when the boundary needs clarification. Numerical evidence gives context, not an
  extension of the theorem. If the paper promises the guarantee for the implemented
  rule, assess that promise at its actual impact.
- A false incidental formula is not automatically severe. A positive factor independent of the candidate preserves an objective's optimizer, but need not preserve its value, rate or uncertainty formula. An obvious normalization correction with unchanged intended choice and guarantee can be minor. Otherwise assess the affected claim at its established impact or retain uncertainty. An auxiliary defect does not automatically invalidate the main result.
- A presentation concern outside the assigned inference must not turn a supported
  composition into `gap`. If that inference fails, retain `gap` even when severity
  is minor. A sufficient alternative route can preserve exact-target support while
  the defective route and its severity remain visible.
- Inconclusive assessment, missing access, uncertain assumptions and lack of model
  knowledge are neutral limitations with no inferred defect severity. A disputed
  finding's validity stays neutral. A separate established rated issue can coexist
  with that uncertainty and retains its rating. An `inconclusive` finding cannot
  become an established defect through a supplied severity value.
- Rate new established findings during ordinary integration when the reasoning
  permits. An omitted rating does not block delivery. The coordinator resolves a
  label disagreement from saved reasoning, without another referee or calibration pass.

For concise cards and severity colors, use [reporting-and-release.md](reporting-and-release.md).
