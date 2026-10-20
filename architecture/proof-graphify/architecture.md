# Current Proof Graphify architecture

## Purpose and boundary

Proof Graphify builds a selective, source-backed map of a paper's main results, important prerequisites, and their connections. It records statements, source locations, proof ideas where the paper supplies them, and reasons for each connection. It does not reconstruct every proof step or verify mathematical correctness. The [skill](../../proof-graphify/SKILL.md) defines selection and comparison rules.

## Data flow

```text
Paper and relevant source context
  -> select main results and prerequisite chains
  -> save statements, connections, and source evidence in SQLite
  -> compare selected records with the paper
  -> validate and render a standalone overview.html
```

The SQLite database is authoritative. JSON seeds and edit batches are inputs; exports and HTML are derived. A source comparison records agreement, an unresolved question, or staleness for the material actually inspected. It is not a proof verdict. The overview selection highlights main results without deleting other selected statements or existing detailed audit records. A new `stat-proof-check` audit starts independently from the manuscript in its own folder and database; existing stores containing both overview and audit records remain supported for compatibility.

[`scripts/paper_database.py`](../../proof-graphify/scripts/paper_database.py) provides the database commands. The bundled `scripts/paper_core/` supplies storage, validation, source handling, projection, and publication. Overview-specific records and revision logic live in the package's `scripts/` directory. The renderer produces an offline HTML reader with a selectable graph, source evidence, mathematical display, and expanded result cards. Failed validation or rendering preserves the previous deliverable.

## Shared core and repository ownership

The maintained source for this bundled backend lives in [`shared/paper_core/`](../../shared/paper_core) in this repository. The [canonical builder](../../tools/build_paper_core_bundles.py) generates byte-identical cores and manifests into `proof-graphify/` and `stat-proof-check/`. Each installed package imports only its shipped runtime. This checkout bundles core `3.3.4`, storage format `4`, and record contract `4`. Overview writes are limited to selected source-backed content and build receipts; sharing the audit runtime adds no proof-checking obligation. Both readers consume the common scientific reader and math implementation, with product adapters retaining their scientific content and graph layouts.

This repository owns both independently installable skills, their shared source, product-specific code and tests, examples, and architecture. Bundled-core changes are made at the maintained source, built into both skills, and validated against the source tests and product integration tests before publication. The `v3.1.4` tag records the historical Graphify release with shared core `2.3.1`.
