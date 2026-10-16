# External result verification

Use this reference when a proof makes a non-trivial use of a result outside the supplied papers. Assess the needed statement and application from supplied passages and reliably known mathematics. External-source retrieval is not required in the default LLM audit. Routine facts and simple applications need no separate lookup or external node.

This work checks the relevant external statement and its application. It does not create an audit of the external paper or its references. Read external proof passages only when the manuscript actually borrows that reasoning.

## Establish the needed statement and its basis

Read an already supplied external statement and relevant setup when available.
Otherwise state whether the needed result and conditions are reliably known from
mathematical knowledge. Distinguish this basis from inspection of its publication.
Do not fabricate precise source attribution, theorem numbers or inspected passages.
Metadata or a search-result page identifies a paper; it does not establish theorem
content. Capture passages actually used with source anchors or PDF page locators.

Assess the theorem's conclusion and conditions relevant to this application.
For supplied passages, read enough surrounding setup to establish their meaning.
Check consequential distinctions such as
pointwise versus uniform scope, dependence, regime and constant dependencies.

If the needed statement or conditions cannot be recalled reliably and are not
supplied, identify the specific uncertainty and use an inconclusive judgment where
it prevents assessment. Lack of retrieval alone does not make a familiar mathematical
fact inconclusive. Keep publication provenance unverified when it was not inspected;
do not infer hypotheses from a title or informal citation. A source/literature
verification task is separate when explicitly requested. Record a bibliography
defect as an attribution issue when the result and application are otherwise established.

## Record one supplier and each actual use

Create one `external_result` node for the non-trivial external result and reuse it
across its applications. When the source was not inspected, retain the manuscript's
citation and exact attributed statement with that provenance limitation, and state
the mathematical basis separately. A locally stated lemma keeps its own identity and can be connected
to the external result. Source identity and each application are distinct scientific
questions within a coherent examination; they do not require separate worker assignments.

For a non-trivial use, explain which conclusion supplies the needed form and whether
the manuscript satisfies its relevant hypotheses, substitutions and scope. A source
match cannot replace this application judgment.

Save these facts in the assigned response. The coordinator records the exact target,
application, and scope using [graph-records.md](graph-records.md). Keep external
hypothesis evidence distinct from manuscript evidence satisfying it.

Reuse a current source inspection or reliably known statement across uses when its
meaning is unchanged, preserving which basis was used. Batch related applications when their complete context fits, while
retaining distinct outcomes. A theorem may apply correctly at one use and fail at
another. Examine a materially changed application before claiming support for it;
unchanged evidence does not require another lookup.
If an earlier source limitation has been resolved by that inspection, update the
affected conclusion and recorded limitation using the saved evidence. Retrieval
provenance alone does not mean the evidence is still unavailable.

## Check contribution and applicability

A citation may refer to a shared assumption without applying the cited theorem.
Locate the actual premise. Distinguish using a theorem's conclusion from borrowing
a separable argument inside its proof. For the latter, identify that subargument
and its own inputs and restrictions. Its owner's full theorem is neither an
automatic premise nor automatic support for the borrowed step.

For example, a fixed-\(t\) theorem saying
\[
\Pr\{|Z_t|>r(\delta)\}\le\delta
\]
does not alone provide
\[
\Pr\{\sup_{t\in T}|Z_t|>r(\delta)\}\le\delta.
\]
If \(T\) is finite, a justified union bound can instead use failure allocation
\(\delta/|T|\), giving threshold \(r(\delta/|T|)\). An infinite or data-dependent
set needs its own argument and hypotheses. The supplier may be correct while
the manuscript application has a gap.

Do not silently add an external theorem's hypotheses to the manuscript or discard
an inconvenient requirement because a similar theorem might exist. If the claimed
reformulation cannot be justified, record the uncertainty or gap. Searching for a
replacement theorem or constructing a repair is not required. Preserve the original
defect if an alternative argument is noted.

For a manuscript result that merely restates an external theorem, check the
restatement against the exact supplier, its setup, and the actual transformation.
The manuscript conclusion cannot act as its own premise.

## Save the conclusion at the correct level

When recording separate local checks, use `external_source` for the supplier-statement assessment and `application` for an exact use. State whether the supplier judgment uses inspected source or mathematical knowledge. An uncertain needed statement can have a completed inconclusive assessment; it does not establish the attributed theorem or grant unconditional premise support. Reliable knowledge can support the assessed mathematical statement without certifying its citation or inventing a source match.
Follow the assigned packet/scaffold and generated role guidance for targets and response shape.
Independent workers use source targets for hidden canonical inferences, as in
[independent-checker.md](independent-checker.md). Distinguish joint reasoning and final composition
within the coherent examination. Explain missing prerequisites or incompatibilities using
[evidence-and-verdicts.md](evidence-and-verdicts.md).

A source match cannot replace application checking. A failed application does not
refute the external theorem. Preserve source limitations, per-use findings, and
the actual conditional support when the needed statement or assumptions remain uncertain.
