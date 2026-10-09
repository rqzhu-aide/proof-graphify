# Detailed mathematical checking

Use the assigned packet, role brief, and relevant [domain checks](domain-risk-checks.md).
Examine the full assigned unit, recording decisive reasoning and material exceptions. Routine lines need no separate node.

Assess the supplied argument using the provided material and mathematical knowledge. Short calculations and routine reasoning may clarify a judgment; constructing a missing proof, repairing the argument or finding a counterexample is not required. When substantive assessment cannot resolve a step, record what needs further verification and continue.

## Mathematical text and JSON

Use `$...$`/`\(...\)` inline or `$$...$$`/`\[...\]` display.
Undelimited math stays plain; preserve source excerpts. JSON requires doubled backslashes,
including dollar-delimited commands: `"$\\theta$"`. Prefer a JSON serializer with Python raw strings.

## Establish the source and exact target

Read the complete statement, applicable setup, definitions, proof, continuations,
supplement, and relevant macros. For PDF material, verify consequential symbols,
subscripts, powers, signs, inverses, and domains visually. An available PyMuPDF
`page.get_pixmap()` can render a page for inspection. State inaccessible or ambiguous
material before claiming source fidelity or complete coverage.

Normalize the assertion without strengthening or weakening it. Preserve:

- Objects, types, domains, ordered quantifiers, and which quantities are fixed or random.
- Explicit and inherited hypotheses, including numerical caps and conjunctions.
- Probability space, sampling law, conditioning, dependence, and equality notion.
- Exact conclusion parts, normalization, regime, and convergence mode.
- Pointwise or uniform scope and each permitted dependency of hidden constants.

For example, \(\mathbb E|X|^q\le M\) is stronger than finite \(q\)-th moment
when a bound must be uniform in the specified \(M\). Likewise,
\[
\forall\theta\;\exists C_\theta\;\forall n:\quad
|R_n(\theta)|\le C_\theta n^{-1}
\]
does not supply a single constant uniform over \(\theta\).
Retain the exact target separately from a short overview synopsis. Compare the
actual saved target and its setup with source; an accurate review note cannot
repair an inaccurate assertion.

## Assess decisive transitions

For
\[
\Gamma,A_1,\ldots,A_m\Longrightarrow C,
\]
examine the decisive written transition using actual inputs, substitutions, scope,
operation, rule, side conditions, and source location. Explain the basis for the judgment, with a calculation or logical derivation where useful;
a familiar final formula or “standard algebra” does not justify an invalid transition.

Separate a consequential change of premise, operation, event, measure, quantifier,
regime or scope when it needs a distinct judgment. Record useful intermediate bounds
or disputed assertions within the examination. Keep routine consecutive algebra together.

For example, with \(a,b>0\),
\[
\frac{u}{a}-\frac{v}{b}
=\frac{b(u-v)+v(b-a)}{ab},
\qquad
\left|\frac{u}{a}-\frac{v}{b}\right|
\le\frac{|u-v|}{a}+\frac{|v|\,|b-a|}{ab}.
\]
This explains the bound and exposes the positive-denominator requirements. A later
claim of a uniform constant also needs uniform lower bounds on the denominators
and the stated control of \(v\). Record those requirements at the step that uses them.

Distinguish three questions, even when one response answers all three:

| Examination | Mathematical question |
|---|---|
| Application | Does this supplier give the exact form needed after substitution, under this scope? |
| Derivation | Do the inputs jointly imply this next assertion, with its side conditions? |
| Composition | Does the entire route establish the exact target and every required part, with legitimate scope exit? |

Two valid applications do not imply a valid joint inference. If
\(\Pr(E_i^c)\le\delta\) for \(i=1,2\), then
\[
\Pr(E_1\cap E_2)\ge1-\Pr(E_1^c)-\Pr(E_2^c)\ge1-2\delta.
\]
A claim of \(1-\delta\) requires a different allocation or further reasoning.
Distinguish the correct applications from the defective combination in the examination's reasoning. Separate local check records are optional when that distinction needs its own displayed outcome.

## Premises, definitions, and witnesses

A theorem's asserted conclusion is not its own premise. Use its hypotheses,
meaning-determining definitions, authorized setup, or actually available earlier
results. Ordinary algebraic and logical rules belong in the justification and need no
separate source investigation. For a non-trivial use of an external result, follow
[external-result-verification.md](external-result-verification.md).

Definitions introduce notation, not unproved mathematical properties. Defining
\(\hat\theta\in\arg\min_{\theta\in\Theta}f(\theta)\) does not establish nonempty
argmin, uniqueness, or measurability. If a later step needs one of these properties,
examine why it holds or identify the missing premise within the current examination.
For example, \(\inf_{x>0}x=0\) has no minimizer in its stated domain.

Respect witness dependence. From \(\forall x\,\exists y:P(x,y)\), a witness
may depend on \(x\); the statement does not imply \(\exists y\,\forall x:P(x,y)\).
Track which earlier variables a witness may depend on and whether it can be
chosen measurably or independently of later randomness when those properties
are used. Fixing a sample-dependent optimizer after a fixed-parameter probability
bound requires further justification.

Check variable freshness for universal introduction and capture-free substitution.
An arbitrary \(x\) must remain arbitrary when generalized. An existential witness
cannot escape into the conclusion or another open assumption where the elimination
rule forbids it.

## Local scope, cases, and induction

Keep a temporary hypothesis attached to its branch. Under \(x\ge0\), the claim
\(x=|x|\) is available; it is not thereby available for \(x<0\) or unconditionally.
At a use, check the supplier's hypotheses, substitutions, and the actual implication
between its scope and the consumer's scope. A kind such as assumption or an
owner relationship cannot authorize the transfer.

For a proof of \(A\Rightarrow B\), retain the local assumption \(A\) until the
implication-introduction step discharges it. For contradiction, use the exact
negation of the target and identify the contradiction actually reached.
Do not add a needed restriction only to free-text check conditions and then claim
the original unconditional target.

Exhaustive cases require all branches under their respective assumptions and an
argument that the branches cover the target domain. Do not conjoin incompatible
branch assumptions into a global premise. Alternative proofs are different:
one complete admissible route can establish a statement while another remains
defective and reportable.

For induction, check the domain and well-founded order, the base cases, the
quantified conditional step, and the induction rule assembling the result.
The induction hypothesis is not an unconditional fact. A cycle of dependencies
without an independent foundation supplies no proof.

## Constants, rates, probability, and limits

Check consequential algebra and asymptotic comparisons under the exact regime. Identify
constants depending on dimension, distribution, confidence, or tuning parameters.
If a theorem lets \(p=p_n\) grow, a fixed-\(p\) bound does not automatically remain
valid. Divide by a vanishing normalization only with a corresponding bound on
the numerator and an admissible nonzero denominator.

Distinguish exact, almost-sure, distributional, and asymptotic equality.
In particular, \(O_p(1)\) does not mean \(o_p(1)\), and pointwise convergence
does not give uniform convergence. State the norm and convergence mode at the
step that changes them.

Track accumulated probability losses and the actual events on which all inputs
hold together. Check conditioning, independence, filtration, random indexing,
and data-dependent choices. When exchanging limits, integrals, expectations,
derivatives, suprema, or infima, name the applicable justification and verify
its needed regularity in this problem.

Within the same examination, note direct, material restrictions that consequential assumptions impose on the claimed application. Distinguish a valid conditional theorem from an unsupported application. Routine reasoning may clarify a restriction or a common event; do not require a predetermined gap verdict, a proof reconstruction, or a separate nonvacuity investigation for every assumption.

## Origins, completion, and repairs

Distinguish the written argument, reconstruction of routine details, and proposed
repairs. Do not silently substitute corrected expressions for printed ones. A borrowed
internal bound can survive a false owner theorem; examine its own inputs.

Assess whether the written route reaches its final target, considering conjunctions,
cases, quantifiers and discharged scopes. Inspect all in-scope written material,
including unused defective routes. Do not call the audit complete just because
one route establishes the target or every registered excerpt has coverage.

If the manuscript omits the argument, assess what is actually supplied and record the omission or uncertainty. Do not invent a route to fill it. This is different from leaving an available proof unread.

Use [evidence-and-verdicts.md](evidence-and-verdicts.md) for outcome and
counterexample standards when a refutation is actually claimed. Repairs are optional; preserve defects when supplying one. A new route
for the unchanged statement has its own provenance; a restricted statement has
its own target. A candidate repair remains provisional until the claimed
mathematics and required independent review are completed.

Record these mathematical distinctions within the coherent proof examination. Use graph-records.md for v3 authoring; the older probability fixture is historical.
