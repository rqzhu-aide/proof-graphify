---
name: proof-graphify
description: Build a selective, source-backed interactive map of a paper's main results, important prerequisites, and their connections, from TeX or PDF sources to a standalone HTML page. Use for a theorem or lemma dependency graph, to understand argument structure, and to navigate results, not to reconstruct detailed proof steps or verify proofs.
metadata:
  version: "3.1.9"
---

# Proof Graphify

Deliver a standalone HTML graph explaining the structure of the paper's written argument. Select its main results, the important assumptions, definitions, and supporting results that explain them, and sourced connections between those statements. Preserve essential qualifications in concise summaries. Detailed derivations and mathematical validity checks belong to the separate `stat-proof-check` skill (called proofcheck in the references), which runs only when the user invokes it.

## Select and build

1. **Orient and select.** Read the introduction, main results, and relevant source context. Start from the central contributions or the results the user names; follow important prerequisite chains as far as needed to explain them. State the selected scope and material omissions. Ask about scope only when an unresolved choice would materially change the requested overview. A declaration scan aids discovery, not an obligation to represent every declaration.
2. **Record statements.** Read [authoring.md](references/authoring.md) and [database.md](references/database.md), including the [PDF-only recipe](references/authoring.md#pdf-only-input) for PDF input. Initialize with `init --focused`, explicit `main_items`, and the supplied source files. Preserve essential conditions from the statement and applicable surrounding setup. Give main results a concise, source-backed `proof_idea` explaining how their important inputs work together when the written argument is available; do not reconstruct a missing proof. Use one identity per selected statement and its manuscript declaration type. All selected statements remain visible; main-result selection highlights roles without filtering the graph. Do not author intermediate proof-step records, owners, or formal use groups.
3. **Record connections.** Explain what the prerequisite supplies and where the target uses it, with any essential restriction. Distinguish a stated condition or conclusion, a definition, and a reused proof argument. A citation alone is not a dependency. Do not collapse omitted derivations into an unsupported direct arrow. Explain joint requirements, alternative routes, and relevant cycles briefly in the connection reasons or scope.
4. **Compare and refine.** Compare the saved summaries, proof ideas, incoming premises, and connection reasons with their sources and applicable setup in bounded groups, reusing unchanged context. Check omitted conditions and unsupported contributions as described in [authoring.md](references/authoring.md#compare-and-display); correct review notes cannot repair inaccurate records. Correct affected explanations together. Record only comparisons supported by the evidence actually inspected; retain specific unresolved questions when needed PDF vision is unavailable. Use `candidates` when a connection needs investigation; exhaustive coverage and zero scanner warnings are not completion requirements.
5. **Render and deliver.** When math or labels need a display check, render the current draft before bulk comparisons, repair affected records through `apply`, then finish comparisons and render the final database. Keep specific unresolved interpretations visible. A cycle can remain with an explanation; do not invent intermediate nodes or change genuine directions to remove it.

## Durable output and continuation

For a new overview, default to this folder beside the manuscript, unless the user chooses another destination:

```text
proof-graphify-<short-paper-name>/
  overview.html
  data/paper-records.sqlite
  work/                       batches, extraction, images and helpers
  exports/                    optional portable snapshots
```

Keep supporting files and useful query snapshots in this same `work/`; relative `work/` examples mean `<overview-folder>/work/`. Link `overview.html` and the database when delivering; retain working data for continuation. Do not delete durable records or relocate registered sources to tidy the folder. The database and exports hold complete source copies; name the output folder so the user can exclude it from manuscript version control or cloud sync.

Register the actual manuscript directory with `--source-root`. Scripts and viewer assets stay in the shared skill installation. After initialization the database is authoritative; seeds and exports are not parallel masters. Reuse the database, stable identities, and output folder for revisions, following [revisions.md](references/revisions.md). For a separate new overview, use the first unused suffix such as `proof-graphify-<short-paper-name>-2/` if the proposed folder is occupied.

The usual command sequence, where `<db>` is `<overview-folder>/data/paper-records.sqlite`; [database.md](references/database.md) gives each command's input:

```text
python <skill>/scripts/paper_database.py init <db> <overview-folder>/work/seed.json --focused --source-root <manuscript-dir>
python <skill>/scripts/paper_database.py list <db>
python <skill>/scripts/paper_database.py get <db> <item-id>
python <skill>/scripts/paper_database.py apply <db> <overview-folder>/work/edits.json
python <skill>/scripts/paper_database.py compare <db> <overview-folder>/work/comparisons.json
python <skill>/scripts/paper_database.py render <db> <overview-folder>/overview.html
```

Rendering checks integrity, source status, comparisons, record preservation, and geometry. An unchanged successful render needs no extra `validate`. Regenerate a retained JSON export after final comparisons, because observations can change without changing the mathematical snapshot ID.

Completion means the selected statements and connections are represented, source comparisons are current or explicitly unresolved, and the HTML faithfully displays them. Unreviewed or stale selected records still need attention; a reviewed `needs_attention` record can be delivered as unresolved. Source comparison does not establish proof correctness. Foreground the overview, selected scope, actual inspection, and material limitations in the delivery message; routine counts remain available in the artifact and receipts.

When a browser is available, inspect a long statement, several prerequisites, search/selection, and any cycle explanation using [browser-check.md](references/browser-check.md). With no browser tool, use the render receipt, disclose interactions as untested, and stop that check. Do not build a driver or install a framework for a paper. Static checks and screenshots alone do not establish interaction correctness.

Existing detailed databases remain readable and retain their records and history. Do not auto-convert or prune them. Read [audit-database.md](references/audit-database.md) only for existing-store compatibility and maintenance. A new `stat-proof-check` audit starts independently from the manuscript in `proof-check-<paper-name>/`, with its own database and report; it does not continue, convert, or expand this overview's database or reuse its output folder. A selective overview does not establish exhaustive audit coverage.

Use shared Python, `latex2mathml`, Node.js, and `pypdf` when PDF input needs text extraction; page images need an available viewing tool or renderer as described in the PDF recipe. Identify missing shared dependencies rather than creating a project-local environment. Keep paper reasoning in records and JSON batches; an optional serializer can safely write those batches without becoming a custom bookkeeping system. The bundled representer-theorem example illustrates the format, never evidence about the user's paper.
