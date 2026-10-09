> Historical v2 reference retained from the baseline. Its workflow and completion requirements do not govern v3. Use [the v3 workflow](controller-workflow.md) and [graph authoring](graph-records.md).

# Minimal transitivity interface example


The linked [graph-example-batch.json](graph-example-batch.json) creates three source-linked items,
one shared scope, exact target specifications, one registered route, one joint group, its two uses
and application extensions, a reviewed proof-boundary link, and a focused audit.
It contains no checks or findings. This example's audit is primary-only to demonstrate authoring;
that setting is not a substitute for the independent review required by a formal audit.

If running this optional teaching example, keep its source, database, batches and assignments under
`work/authoring/transitivity-example-1/` in the chosen proof-check folder. Use a fresh example folder
for another run; its database is separate from the actual paper's `audit.db`.
First create `source/paper.txt` inside the example folder containing these exact five lines:

```text
Let u, v, w be real numbers.
Assumption A: u <= v.
Assumption B: v <= w.
Theorem T: u <= w.
Proof. By transitivity, u <= v and v <= w imply u <= w.
```

Initialize a new example database using that example's `source/` directory as its source root and capture
`["paper.txt"]`. Copy the returned paper/source IDs and obtain an author packet. Create these
anchors in a single request, replacing `req_anchors_example`, `pkt_author_example`, and every
`src_example` with actual fresh IDs/packet identity:

```json
{
  "contract_version": 4,
  "request_id": "req_anchors_example",
  "packet_id": "pkt_author_example",
  "anchors": [
    {"id": "anc_scope", "expected_version": null, "source_id": "src_example", "locator": {"start_line": 1, "end_line": 1, "page": null, "label": null}},
    {"id": "anc_A", "expected_version": null, "source_id": "src_example", "locator": {"start_line": 2, "end_line": 2, "page": null, "label": null}},
    {"id": "anc_B", "expected_version": null, "source_id": "src_example", "locator": {"start_line": 3, "end_line": 3, "page": null, "label": null}},
    {"id": "anc_T_statement", "expected_version": null, "source_id": "src_example", "locator": {"start_line": 4, "end_line": 4, "page": null, "label": null}},
    {"id": "anc_T_proof", "expected_version": null, "source_id": "src_example", "locator": {"start_line": 5, "end_line": 5, "page": null, "label": null}}
  ]
}
```

Read the five-line source and confirm that line 5 contains the complete proof with no continuation.
Get an author packet and submit a boundary review as described above. For this new example, use
`id: "srv_boundary_example"`, pin the returned source and `anc_T_proof` at their current versions,
and set the decision to `accepted` with a reason identifying that complete fifth line.
The graph example refers to version 1 of that review and its newly created anchors; use the
returned versions if adapting existing records.

Then get a fresh author packet, copy the graph example, and replace its top-level `request_id`,
`packet_id`, and audit body's `paper_id`. The other example IDs are valid in this new empty graph;
use fresh generated IDs when adapting to an existing paper. Apply the batch once. Its scope and
two premise uses record the intended joint inference; whether that source-linked reasoning is
actually valid remains work for the checker. Run `work list DB --audit aud_example --focus
items:itm_T`, then prepare the next coherent assignment. Assumption and scope source-fidelity work
is initially unexamined, so do not expect the first assignment to close the whole theorem.
