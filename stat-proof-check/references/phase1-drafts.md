# Local Phase 1 work and shared graph intake

The coordinator gives each primary examiner a coherent group of proofs and stable source material. The worker can create local proposed items and connections as needed to examine those proofs. It returns these together with its reasoning, outcomes and any source limits. Local names are enough; workers do not write the shared database or wait for another worker to create an equation.

Name an original-return location with each assignment. A writable worker saves its draft there and returns a concise path/status; otherwise the coordinator/host captures the full individual return before combined-message formatting or clipping. Freeform drafts remain valid. After an interruption, retrieve saved originals and continue only missing or unfinished work, following [recovery guidance](controller-workflow.md#stop-and-recover); a clipped aggregate does not require repeating completed groups.

After the group's returns, the coordinator organizes them into the shared graph:

1. Match proposed items by their source claim and context. The same Equation (12) in the same document and conditions normally becomes one node. Equal labels or a shared page alone are insufficient. Keep different claims, conditions and source versions distinct. Routine algebra can stay in the containing examination.
2. Reuse an existing shared record or register one canonical item. Keep each consuming proof's actual use and needed consequence. A shared result's own derivation belongs to its owning proof unit; consumers check its applicability without each reconstructing that derivation.
3. Save the returned primary examinations against the consolidated questions, preserving their authors, reasoning, limitations and disagreements. Formatting and identity mapping belong to the coordinator. The same unchanged question does not need another mathematical examination.
4. Send the ready group to ordinary independent review in Stage 2. A missing worker return remains a local coverage limitation and does not block other groups.

For example, two workers examining Theorems A and B may both propose Equation (12). The coordinator creates one equation node and two consuming connections, one for A and one for B. Their different judgments about its uses stay separate. If they disagree about the equation itself, merging the identity does not erase either judgment.

Initial local drafts are source-based work, not responses claiming to have inspected an already issued database packet. Once the graph is organized, use `stage1 prepare` and map the saved work into its generated response rows. Only copy judgments whose actual question, conditions and evidence agree. Save the original draft alongside that response and submit with the actual primary examiner identity. Mechanical mapping needs no worker round trip. An uncovered or materially changed use receives only the affected continuation, or stays an explicit limitation. Do not turn a partial examination into a whole-unit verdict during intake.

If a worker was already given a database packet, preserve that response and respect its freshness checks. A later graph change may require `stage1 prepare --focus ...` or `--task ...` and continuation from the saved reasoning. For primary continuation, give the examiner its saved response and the specific remaining question alongside the assignment; a regenerated blank scaffold is not a request to restart. Changing an old response's packet ID does not establish examination of changed material.

## Optional structured consolidation

Readable local drafts are sufficient. When structured returns are convenient, the following small format lets the script match exact proposals and prepare ordinary authoring inputs. It creates no database records, proof verdicts or independent-review credit.

~~~json
{
  "namespace": "section-a",
  "reviewer": "actual primary examiner",
  "items": [
    {
      "local_id": "lemma1",
      "kind": "lemma",
      "label": "Lemma 1",
      "statement": "The exact statement, including hypotheses or named assumption references.",
      "source": {"document": "paper.tex", "locator": "Lemma 1, lines 5-7"},
      "unit": {
        "statement_anchors": ["anc_lemma1"],
        "proof_anchors": ["anc_lemma1_proof"],
        "source_matched": true,
        "proof_complete": true,
        "source_note": "The examiner compared these captured statement and proof passages.",
        "proof_idea": "The source first bounds the sequence by induction. Together with monotonicity, this bound gives convergence."
      }
    }
  ],
  "connections": [],
  "examinations": [
    {
      "target": "lemma1",
      "outcome": "inconclusive",
      "extent": "whole_unit",
      "reasoning": "The actual examination and the specific unresolved inference."
    }
  ]
}
~~~

`unit` is optional. Without captured anchors, return source locators and let the coordinator capture the needed passages. Its fields, when supplied, follow the [ordinary record or proof-unit definition](graph-records.md); booleans describe actual source judgments. Setup records need no proof-completeness answer. `context` may record a material source case or local condition so it is not lost during matching. Keep all hypotheses explicit in the statement or its named references as well. Intermediate equations or claims name their owning proof item with `owner`. When their derivation was selected inside that proof, `derivation_in` names the local owning item; the helper maps it to the proposed argument. For an existing argument, use its actual `unit.argument_id`. See graph-records for the distinction between grouped derivation, ownership and a separate proof-unit route.

Optional `unit.proof_idea` follows the [source-argument explanation contract](graph-records.md#ordinary-written-proof); do not add a draft-level explanation field. Different explanations stay with their originating authoring options and do not change claim identity or become one merged summary.

A connection runs from supplier to consuming claim. For items in the same draft:

~~~json
{"from":"lemma1","to":"theorem2","reason":"The proof applies Lemma 1 at the fixed parameter.","needed_form":{"form":"transcription","text":"The exact consequence used here."}}
~~~

References can also be `{"namespace":"section-b","local_id":"equation12"}` or an existing `{"collection":"items","id":"itm_known"}`. Workers need not coordinate names across drafts: identical source-backed items with different local names can still merge. A missing referenced return remains an unresolved reference alongside the usable work.

~~~text
AUDIT stage1 consolidate-drafts --input worker-a.json --input worker-b.json --out consolidated.json
~~~

The output contains the local-to-proposed mapping, items, connections, original examinations, unchanged source drafts and authoring options. Matching is exact, not a mathematical equivalence judgment. Different wording or locators may require the coordinator's ordinary source comparison; the script does not request an equivalence proof. Repeating identical input is harmless. For a later return, consolidate the available drafts to a fresh output path and reuse already registered identities.

Choose one authoring option per shared item after checking existing records. Different source-boundary judgments remain alternatives, not automatically adopted answers. For ready `add-unit` or `add-record` options, save the chosen `definition` to a file and run the named command. `authoring_order` puts required records first, including an owner before its owned result. `authoring_shape_ready` describes input shape, not scientific approval. Both helpers save `definition.suppliers`; do not register those links again.

When an owner consumes its own intermediate, its chosen option includes `deferred_connections`: create the owner and intermediate, then submit those use edits through the existing author-packet/apply path before preparing the examination. Select the deferred edits from the same authoring options you used, not every alternative in the output. This resolves the ordinary owner/prerequisite ordering without a worker round trip. For `template` options, obtain an author packet and an item template. Use the chosen option's body for new items; for existing items obtain the current replacement template and edit only intended fields. Omission of optional prose in a draft does not instruct erasing saved prose. Author remaining links separately. Generated IDs are proposed identities only: when reusing an existing node, use its actual IDs in the affected definitions, deferred links and response mappings.

A named assumption stays an assumption and source/setup context. The helper keeps its context connections separate from proof-supplier links, and includes available captured setup anchors with the consuming claim's statement evidence. `context` here is a draft classification, not a new database edge type. Keep the named reference in the exact statement and supply any missing setup passage to the examinations. For source-stated hypotheses of the consuming claim, use the existing `assumptions` field with the actual shared item IDs during ordinary authoring. A draft context connection alone does not establish a target hypothesis; preserve genuine local conditions or cases in their own context, and create no proof duties for assumptions.

Resolve only listed local authoring issues, such as a missing captured anchor or unresolved supplier. `cyclic_items` need existing record/link authoring, not repeated `add-unit` calls. None of these diagnostics asks a worker to re-prove the paper. This consolidated file contains primary opinions and is coordinator material; it is not an independent-review delivery file.

## Late discoveries

Finish known meaningful shared identities before dispatching the affected independent review where practical. Do not polish equivalent graph details while a reviewer is working. If Stage 2 exposes another dependency, the reviewer reports its source and consequence; the coordinator handles the local addition. Use `work extend` only for additional neutral source context on an unchanged independent question. Refresh the affected assignment when its freshness rules require it. Scientific continuation is needed only for materially changed or previously unexamined content; administrative mapping and equivalent explanatory detail belong to coordinator intake. Preserve original responses and all unaffected work. A refreshed packet does not by itself establish examination of new material.
