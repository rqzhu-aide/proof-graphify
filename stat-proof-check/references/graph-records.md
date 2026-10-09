# Coherent graph authoring

Keep exact claims, meaningful prerequisites, routes and local conditions. Routine algebra need not become nodes. Jointly required suppliers belong to one inference; alternative sufficient routes remain distinct. Add explicit cases or nested scopes when their scientific meaning requires them.

The coordinator owns shared records. Phase 1 workers can propose local items and links before database identities exist; consolidate those drafts using [phase1-drafts.md](phase1-drafts.md) before registering them here. A repeated source claim becomes one shared node when its statement and context agree; each consuming use remains distinct.

## Ordinary written proof

stage1 add-unit consumes a JSON object and generates the claim, exact specification, context, argument, final inference, source review/boundary and source comparison together. It generates IDs, pins and paired application records. Example:

~~~json
{
  "key": "theorem_1",
  "kind": "theorem",
  "label": "Theorem 1",
  "statement": "The exact statement including all hypotheses.",
  "statement_anchors": ["anc_statement"],
  "proof_anchors": ["anc_main_proof", "anc_supplement_continuation"],
  "source_matched": true,
  "proof_complete": true,
  "source_note": "The exact statement and setup match the source. The proof continues in the supplement.",
  "aliases": ["Supplement Theorem A"],
  "suppliers": []
}
~~~

Both booleans describe actual source judgments. The coordinator can record its own comparison or a primary worker's saved comparison under that examiner's `reviewer` identity. If the representation is unsettled or a continuation is missing, use false and explain it. This operation saves no proof check and makes no mathematical support claim.

Keep hypotheses and quantifiers in the exact statement, including references such as "Under Assumption A1." Supply A1's captured content as source/setup context and reuse its named-assumption record when needed. A clearly identical restatement can share that record with both source locations retained; materially different conditions stay explicit. No separate equivalence proof or node for each clause is required. An assumption is not a lemma to prove. A formal proof-supplier edge is not required merely to display its reference. Do not add private conditions or proof work just to change a conditional support status.

When the supplied manuscript provides no proof, use `proof_anchors: []`, `proof_complete: true`, and explain the omission in `source_note`. Here true means the supplied material has been accounted for; it does not assert that a proof exists or is valid. This saves the statement without an invented argument. Its primary and independent assessments can record a gap or uncertainty. Do not use this path for a missing supplied continuation.

When the entire referenced proof is unavailable, use `proof_anchors: []`, `proof_complete: false`, and explain what is missing in `source_note`. The helper saves the known statement and an open source issue, without a dummy argument. The missing evidence keeps delivery working; unrelated proofs can proceed. When the material becomes available, capture it, add the actual route to the existing claim through affected-record edits, and resolve the source issue. Do not register a duplicate claim or re-examine unrelated proofs.

The suppliers list is optional. Each supplier entry requires target, reason and needed_form. Register the supplier's claim first, then use its returned item ID at `unit.item` in the add-unit receipt (not `item_id`). For example:

~~~json
{"target":{"collection":"items","id":"itm_lemma_1"},"reason":"The proof applies Lemma 1 at the fixed parameter.","needed_form":{"form":"transcription","text":"The exact consequence needed at this application."}}
~~~

Optional entry fields are substitutions [{symbol,value}], evidence_refs and type. Type is dependency for using a result, definition for definition context, or proof_argument for borrowing an actual argument. Supplying a theorem statement is usually enough for a result application; actual proof borrowing needs its passages. add-unit generates the corresponding application_details; its low-level template requires an existing use and is only needed for advanced edits.

Routine external facts need no separate node. For a non-trivial external use, create an `items` record of kind `external_result` using the existing template/authoring path, then reference it as a supplier. Save the cited result, source location and relevant captured evidence; reuse the node across applications. If retrieval is unavailable, anchor the attributed statement to the supplied manuscript and disclose that its external source was not inspected. The `external_source` assessment can finish as inconclusive. Record this uncertainty in the assessment or findings; `source_issues` is for defects in supplied or captured evidence, not a queue of inaccessible citations. See [external-result-verification.md](external-result-verification.md).

Use an exact `transcription` or `verbatim` statement for that supplier. Its current matched source comparison and supported external-source examination can establish source support without a separate target specification. A synopsis or uninspected citation cannot. Reuse the saved inspection while its source and meaning are unchanged; do not repeat it merely to add bookkeeping.

Use aliases only after comparing the actual statement, hypotheses and context. Different numbering alone neither identifies nor distinguishes results.

A proof may span files and pages. proof_anchors includes every segment. For two proofs sharing a captured page, optional proof_spans contains {anchor_id,start_offset,end_offset} selections using zero-based offsets into the unchanged excerpt. Preserve every continuation. Invalid selections are errors, not permission to silently shrink the evidence.

A repeat of the identical definition reuses the recorded unit. A changed definition with the same key requires an explicit correction to the existing graph, preserving its history.

## Setup and shared intermediate results

Use `stage1 add-record audit.db --input record.json` for an ordinary assumption, definition, intermediate result, equation, claim or derivation. It also accepts the major proof-unit definition above. The returned IDs use the same `unit` member as `add-unit`.

For example, a named assumption needs its source comparison, not a proof-completeness judgment:

~~~json
{
  "key": "assumption_a1",
  "kind": "assumption",
  "label": "Assumption A1",
  "statement": "The exact named assumption.",
  "statement_anchors": ["anc_a1"],
  "source_matched": true,
  "source_note": "Compared the named setup with its captured source."
}
~~~

An intermediate uses its actual kind and `owner_id`. Register the owner first. An item with proof passages alone creates no separate proof assignment and receives no automatic favorable verdict. To represent a derivation actually examined inside the owner, also provide its existing `argument_id`, the selected `proof_anchors`, and any `suppliers` used to derive this result:

~~~json
{
  "key": "equation_12",
  "kind": "equation",
  "label": "Equation (12)",
  "statement": "The exact intermediate equality including its conditions.",
  "statement_anchors": ["anc_eq12"],
  "proof_anchors": ["anc_eq12_derivation"],
  "owner_id": "itm_theorem_1",
  "argument_id": "arg_theorem_1",
  "source_matched": true,
  "source_note": "This passage derives Equation (12) within the written proof of Theorem 1.",
  "suppliers": []
}
~~~

This creates a local inference concluding Equation (12) inside the owner's argument. The selected statement, setup and derivation belong to that ordinary examination; ownership, a shared page or an application alone does not establish the equation. Keep its premises and material conditions accurate. A private `scope_id` remains private when another proof consumes the result. Separate local outcomes can preserve an established intermediate when the owner's final step fails; do not infer that local outcome from the owner's overall label.

Then attach each consuming use, including the owner's own use if needed, through existing record/link edits before preparing the affected examination. The sequence is owner, owned result, consuming link. Another proof reuses the same item and examines its own application. The consolidation helper exposes any deferred links for this sequence.

For a meaningful subsection deliberately selected for its own examination, use `separate_examination: true` with the ordinary proof-unit fields and its required `owner_id`. This creates a separate proof-unit route; select the subsection in the existing audit scope when it needs its own assignment. Omit `argument_id` for that path. Separate assignment is a scope choice, not a consequence of registering an equation.

## Advanced or corrected structure

Use get in author/primary mode, template for the needed collection, and apply a coherent batch. The template command exposes the enforced shape. Do not inspect runtime source to discover fields.

For a live record, `template ... --collection COLLECTION --packet AUTHOR_PACKET --id RECORD_ID --out edit.json` returns `replace`, the full current body and its expected version. Edit the intended fields and submit the `template` member through `apply`. With an ID absent from that collection, the command still prepares a named create. Refresh the author packet if requested; do not mint new IDs or rebuild the database to correct a record.

For an ordinary exact claim created by `add-unit`, use the paired correction helper:

~~~text
AUDIT stage1 correct-claim audit.db --item itm_theorem_1 --expected-version 1 --correction correction.json
~~~

The correction is an object containing `statement` and/or `statement_anchors`, for example `{"statement":"The corrected exact claim including its hypotheses."}`. It updates the item and direct exact specification together, preserving other content. If a generic edit already corrected the item, use `--sync-current` instead of `--correction` to align its direct specification with the saved current statement and statement anchors. Do not reconstruct an old item body. The receipt shows the saved before/after change; a long statement uses a marked excerpt near the first difference.

Neither operation creates a favorable source comparison or proof verdict. An unchanged replay describes the original saved change. Advanced pairings receive a local explanation and use ordinary affected-record edits. Use stage status to identify affected work when needed; do not rebuild or repeat unrelated examinations.

The optional `conditions`, `assumptions` and `binders` fields describe genuinely private assumptions, bound variables or case contexts. Ordinary theorem hypotheses already in the statement need none of these fields. Keep existing meaningful scopes; no migration or separate scope audit is required.

Use existing items/parts, arguments, groups, scopes and uses when an extra route, meaningful subsection, case branch or material local outcome requires them. application_details and target_specs preserve exact usage and target meanings; scripts handle paired fields where available.

A manuscript proof omission is represented as its exact claim without a fabricated argument or dummy evidence. Keep it in requested scope and assess the omission using the statement's generated examination. Unavailable referenced material retains its source limitation until accessed and examined.

A displayed synopsis differs from an exact claim. Do not reuse source fidelity when hypotheses or conditions differ. Checking a valid implication does not establish its supplier. An internal result can remain valid even if its owning theorem's final composition fails.

New routine explanatory detail within an examined unit creates no mandatory microchecks. Changed assertions, conditions, substantive routes or evidence require attention to the affected examination. A proposed mathematical repair is separate from correcting the database's representation and is not required to finish reporting a gap.
