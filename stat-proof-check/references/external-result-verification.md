# External result verification

Use this reference when a proof makes a non-trivial use of a result outside the supplied papers. Routine mathematical facts and simple applications can be assessed using mathematical knowledge, without a separate lookup or external node. A specialized result whose assumptions determine whether the step works warrants source inspection when tools are available.

This work checks the relevant external statement and its application. It does not create an audit of the external paper or its references. Read external proof passages only when the manuscript actually borrows that reasoning.

## Identify and inspect the exact source

Use available tools to identify and retrieve the actual publication or authoritative
source containing the result. Confirm the relevant statement, assumptions and location.
Metadata or a search-result page identifies a paper; it does not establish theorem content.
Capture the evidence used with source anchors or PDF page locators.

Read enough surrounding setup to understand the theorem's conclusion and the
conditions relevant to this application. Check consequential distinctions such as
pointwise versus uniform scope, dependence, regime and constant dependencies.

If the source cannot be obtained with the available tools, or the application remains
uncertain, record the attempted inspection or tool limitation and an inconclusive
judgment. That assessment can finish without resolving the dependency. Do not repeat
unchanged retrieval attempts or infer hypotheses from a title or informal citation.
Record a bibliography defect as an attribution issue when the exact result and its
use have otherwise been verified.

## Record one supplier and each actual use

Create one `external_result` node for the non-trivial external result and reuse it
across its applications. When the source is unavailable, retain the manuscript's
citation and attributed statement with that limitation; do not fabricate an inspected
source. A locally stated lemma keeps its own manuscript identity and can be connected
to the external result. Source identity and each application are distinct scientific
questions within a coherent examination; they do not require separate worker assignments.

For a non-trivial use, explain which conclusion supplies the needed form and whether
the manuscript satisfies its relevant hypotheses, substitutions and scope. A source
match cannot replace this application judgment.

Save these facts in the assigned response. The coordinator records the exact target,
application, and scope using [graph-records.md](graph-records.md). Keep external
hypothesis evidence distinct from manuscript evidence satisfying it.

Share a current source inspection across uses when its consumed source and meaning
are unchanged. Batch related applications when their complete context fits, while
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

When recording separate local checks, use `external_source` for the supplier-source assessment and `application` for an exact use. An unavailable source can have a completed inconclusive source assessment; that does not establish its attributed theorem or grant it premise support.
Follow the assigned packet/scaffold and generated role guidance for targets and response shape.
Independent workers use source targets for hidden canonical inferences, as in
[independent-checker.md](independent-checker.md). Distinguish joint reasoning and final composition
within the coherent examination. Explain missing prerequisites or incompatibilities using
[evidence-and-verdicts.md](evidence-and-verdicts.md).

A source match cannot replace application checking. A failed application does not
refute the external theorem. Preserve source limitations, per-use findings, and
the actual conditional support when the exact external evidence remains unavailable.
