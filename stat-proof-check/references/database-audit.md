# Start a v3 audit

Use the bundled scripts/paper_audit.py with an existing user-wide Python runtime. Never use the old proofcheck.py ledger program for a new v3 audit. This package is independent of installed v2 and Graphify.

## Choose the work folder

Use a dedicated proof-check-PAPER folder with audit.db, work/ and report.html. Keep manuscript files separate. Do not overwrite an existing audit or report belonging to another run. Resume a v3 database through these commands; use the original compatible reader for a v2 database.

The commands below abbreviate the existing Python invocation and the full path to this package's scripts/paper_audit.py as AUDIT. On Windows, use `python -X utf8` for mathematical text and explicit UTF-8 file/subprocess encoding. This avoids terminal encoding failures; ambiguous PDF glyphs still need the original page.

~~~text
AUDIT init audit.db --source-root SOURCE_DIRECTORY --title "Paper title"
AUDIT source capture audit.db --files source-files.json
~~~

Here source-files.json contains the JSON array ["paper.tex","supplement.tex"], relative to SOURCE_DIRECTORY. The --files argument is the path to this JSON file. Use --help on the needed subcommand for its precise arguments. Discover actual local TeX includes and supplied PDFs. Capture the relevant sources, then create source anchors using source anchor and the generated schema. Source capture preserves bytes; source anchors preserve exact locators and excerpts. Do not invent hashes or reconstruct excerpts from memory. To obtain a general authoring packet, use get with --mode author and --target papers:PAPER_ID, using the paper ID returned by init.

Use the main/supplement result inventory as navigation during initial reading, not as proof of Full coverage. Include meaningful in-scope unnumbered derivations and method justifications encountered during source reading; they may share a proof unit only when its actual examination and independent review cover them. Routine algebra needs no separate unit, and proof scope does not imply reproducing experiments. A named main PDF identifies the target paper: inspect relevant supplied companion files in the indicated input locations before declaring a referenced proof omitted or unavailable. Honor explicit source restrictions; unrelated accessible files do not enter scope. Full accounts for the related supplied manuscript and supplements, while retrieving a needed continuation does not itself add every other result in the retrieved document to scope.

If the manuscript actually omits a proof, keep the result in scope and assess the omission without fabricating a route. A referenced continuation that could not be accessed or examined remains a coverage limitation. Captured, inspected evidence matched to the target paper is available even if retrieved rather than originally attached. Preserve its provenance; resolve an earlier missing-source issue when its cause is removed, without repeating the lookup. Record these decisions in existing source notes and scope, not a separate inventory.

For TeX anchors, save this request shape to anchors.json, replacing the example IDs and inclusive one-based line range with actual values. Use a fresh request_id, the author packet's packet_id, and the source_id returned by capture. The script reads the excerpt and computes hashes.

~~~json
{
  "contract_version": 4,
  "request_id": "req_source_anchors_1",
  "packet_id": "pkt_RETURNED_BY_GET",
  "anchors": [
    {"id":"anc_theorem_1", "expected_version":null,
     "source_id":"src_RETURNED_BY_CAPTURE",
     "locator":{"start_line":10,"end_line":20,"page":null,"label":null}}
  ]
}
~~~

~~~text
AUDIT source anchor audit.db --request anchors.json
~~~

Create separate anchors for distinct statements, setup and proof segments. Include all continuation segments when registering the proof unit. For PDF material use a locator such as {"start_line":null,"end_line":null,"page":3,"label":null}, where page is the physical one-based PDF page. Inspect consequential symbols visually and keep every relevant page from its actual source file.

For delegated Phase 1 work, give each examiner a coherent group of proofs and the matching source passages. Let them draft needed items, connections and examinations independently, then consolidate their returns as described in [phase1-drafts.md](phase1-drafts.md). A missing graph node does not block examination of available source material. The coordinator alone registers the consolidated records using [graph-records.md](graph-records.md). Direct authoring remains useful when working alone or continuing an existing graph. Once the intended scope is represented:

~~~text
AUDIT stage1 scope audit.db --mode full
AUDIT stage1 scope audit.db --mode focused --target items:itm_theorem_1
~~~

These are alternatives. Record the returned audit ID and use it for subsequent stages. Triage uses --mode triage. A change of declared scope is explicit, not a repair shortcut.

SQLite holds the evidence and scientific history. A frozen result describes one revision; later live changes do not alter a previously built report.
