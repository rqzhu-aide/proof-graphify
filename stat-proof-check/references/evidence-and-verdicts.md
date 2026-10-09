# Evidence and outcomes

This reference governs current database audits.
Read [mathematical-checking.md](mathematical-checking.md) for how to examine an inference.

## What the evidence establishes

Separate material observed in the manuscript or an inspected external source,
reviewer reasoning reconstructed from it, and claims not established by available
evidence. Cite exact source anchors, statement parts, equations, or external result
locations. Explain the particular premises, operation, and success or failure;
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
A restricted repair needs a separate target. A new proof of the unchanged statement
needs a separate route and provenance; keep the original proof's judgment.

## Omitted arguments, unavailable sources and restrictions

A supplied exact theorem statement permits checking its application under that premise even when
its proof is outside this assignment. If the manuscript omits an argument, assess the supplied material and record the omission as a gap when justified, or as inconclusive when its significance is uncertain. Do not construct a proof route merely to register or finish that finding.

A proof or passage that is present in the supplied material but unavailable to the examiner remains a coverage limitation. An inaccessible external citation is different: use available tools for non-trivial applications, then record what was established and any unresolved source limitation. Follow [external-result-verification.md](external-result-verification.md); routine facts need no separate lookup. Never describe an unavailable source as inspected.

Call a manuscript gap only when an actual missing or invalid manuscript inference is identified. Coverage follows the examination rule above, independently of this outcome.

Adding \(\pi_n\to0\) does not establish a source theorem allowing fixed positive \(\pi_n\).
Correct the saved assertion or identify a restricted target; an accurate prose note cannot repair it.
An inspected external statement, a self-contained derivation, a remembered theorem, and numerical
consistency are distinct evidence. Detailed source requirements load with external-source work.

## Analytical refutations and unresolved examinations

A failed written proof does not show a false theorem. Finding a counterexample is not required to finish an examination. If a statement refutation is claimed,
state the exact assertion and explain the decisive contradiction under its hypotheses.
When a counterexample is the basis, its witness must satisfy **all** hypotheses and
show the actual violation in the claimed regime. Record the refutation as
a `statement_refutation` finding, linked to the supporting examination and evidence.

For example, to refute “for every sequence \(p_n\ge1\), \(p_n/n\to0\),”
choose the admissible sequence \(p_n=n\) and compute \(p_n/n=1\) for every \(n\).
A test with a fixed \(p\) cannot refute or verify that universal growing-sequence claim.

Use written derivations, symbolic equations and exact arithmetic to check
proposed witnesses. Do not run simulations, numerical validation, parameter
sweeps, random searches or empirical experiments, including small pilots.
Computational searches, numerical solvers and interval-validation runs are not
fallbacks for missing derivations. Supplied experimental results are context,
not proof credit. Source extraction, PDF inspection, database arithmetic, hashes,
rendering and software regression tests remain ordinary tooling.

For an unresolved examination, name the inference, what was attempted and why
it remains unresolved. If useful, suggest one follow-up in existing reasoning
or findings. Label any numerical suggestion unperformed and outside the audit;
it supplies no proof credit and creates no required task. Continue other useful
proof work instead of retrying without new evidence.

## Findings, disagreements, and repairs

Separate the finding's mathematical content, consequence, and evidential confidence.
State whether it affects one application, a written route, the exact statement,
or a later use. Use an evidence-backed impact explanation; current database findings
do not require the legacy severity, repair-search, or per-line risk ledgers.

Ambiguity is not a proved mismatch. When two readings imply different targets,
record the readings and what source evidence could distinguish them. Likewise,
separate an estimator's relation to a theorem's target, implementation consistency
with that estimator, and evidence linking the inspected code to reported experiments.
A missing execution link does not refute an abstract theorem assuming an oracle.

A plausible repair stays provisional. Record whether its sufficiency was actually
examined and independently reviewed. Checked sufficiency does not mean the
manuscript was edited or its original defect resolved.

Preserve independent response bytes and original outcomes. Reconcile conflicting
judgments on the same exact question with explicit reasons, retaining unresolved disagreement when appropriate.
A statement refutation and a conditional application are different questions;
do not change the latter's outcome merely to display the former.
