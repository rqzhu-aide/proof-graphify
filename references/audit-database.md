# Existing-store compatibility and maintenance

Read this reference for an existing detailed overview or maintenance of a store that already contains audit records. New overview authoring follows the focused [database workflow](database.md). A new proofcheck audit starts from the manuscript in its own `proof-check-<paper-name>/` folder and database; do not create it by continuing, converting, attaching to, or expanding a proof-graphify database. A focused overview is a compatible subset of the native schema, not a new audit format. Its source matches are not proof checks, and its selected inventory is not exhaustive audit coverage.

## Existing detailed overviews

Existing native databases and captured exports retain the full schema-3 reader. New `init` creates a common store; an explicitly requested conversion of an existing native database uses the backed-up compatibility procedure below. Conversion is not required merely to read an existing native database. An export has no focused profile metadata: import with `init --focused` to enforce focused authoring, or without the flag for rich-record compatibility. Incompatible rich content is rejected by focused initialization rather than trimmed. A later user-requested rescoping should use atomic edits in the authoritative database. On a common store, removing an overview item or use deselects it while retaining its shared identity and any existing audit records.

Legacy `equation`, `claim`, and `derivation` records retain their required major-item `owner`. Uses with an intermediate endpoint remain detail annotations under the relevant owner and stay outside major graph layout and cycle detection. An intermediate self-use appears once. Legacy use `group` values retain their `joint` or `cases` annotations and consistent group identities; they do not establish logical sufficiency. New focused work creates none of these objects.

Legacy comparison digests and packets remain unchanged. An owner's context includes its owned rows, uses entering the owner and those rows, prerequisite statements, and evidence. Editing that context stales the owner's comparisons and can prevent reviewed reuse. Do not shorten a legacy packet by dropping this evidence. Source snapshots, old observations, and details remain available in native exports and conditional legacy rendering. The retained exhaustive `scaffold`/`reconcile` utilities apply only to non-focused stores; ordinary overview work uses bounded packets and optional candidates.

## Convert an existing native store when requested

Overview and proofcheck use the same common storage format 4; this compatibility does not make their new work share a database. The retained `migrate-overview` command converts an existing native overview for maintenance when explicitly requested, using the bundled `paper_audit.py` wrapper and its generated `paper_core/` package, without importing a sibling skill. Check the installed bundle before writing:

```text
python <skill>/scripts/paper_audit.py version
```

`bundle.ok` must be `true`. A false or absent value indicates a damaged installation; report it instead of modifying records with that bundle. This check concerns machine-readable compatibility, not the overview's mathematical content.

```text
python <skill>/scripts/paper_audit.py migrate-overview <overview-folder>/data/paper-records.sqlite --backup <overview-folder>/data/paper-records.pre-migration.sqlite
```

The command accepts the overview marker `archify-paper-database-1` with `schema_version: 3`, backs up the file, and converts it transactionally in place to common storage format 4. Close other database clients first. A busy database is refused and the original remains authoritative; conversion never swaps a file underneath an active writer. Keep the verified backup, which retains historical native snapshots and build rows.

The bridge preserves stable item/use/anchor identities, source bytes and root provenance, scope, explicit selected items and connections, main-result selection, authored fields, aliases, issues, regimes, and locators. Legacy owner and group records retain their mappings. A group spanning several conclusions becomes one provisional group per conclusion, disclosed in `limitations`. Every retained comparison keeps its original broad input and chronology; historical comparisons acquire no current credit. The archived native export preserves original provenance, and conversion creates no mathematical reviews.

Anchors must reference captured source files. An excerpt-only overview without registered files cannot migrate. A page alone requires a captured PDF; a supplemental page beside a valid text line or label locator survives as navigation metadata while evidence remains bound to captured text. Unknown items, owners, or endpoints are refused. Correct source bindings in the overview first. The audit store requires the machine-readable feature `overview-bridge/1`; an incompatible bundle refuses it instead of guessing.

After conversion the same database remains authoritative for the existing overview. Continue using overview `get`, `apply`, `compare`, `refresh`, `changes`, `validate`, `candidates`, `render`, `export`, `backup`, and reviewed reuse on its selected view. In an existing store that already contains audit records, unselected audit items remain outside that view until selected explicitly. Full overview upserts preserve exact targets, applications, judgments, and other audit extensions. The retained `scaffold` and `reconcile` utilities keep their non-focused behavior and refuse focused stores. These compatibility operations do not start a new proofcheck audit. Importing a selective graph does not imply that omitted proof steps or results were assessed.

Overview JSON exports contain the selected view. Use the common audit export to inspect all mathematical records and history; use SQLite `backup` for complete recovery. Native snapshots predating conversion are retained in the backup and can be inspected there with the native reader. Registered relative source paths use the saved manuscript root. If the project moves, refresh with an explicit verified `--source-root` and any needed `--file-map`; no similarly named file or current working directory replaces captured evidence.

## Inspect an existing audit store

The following commands apply only when maintaining a store that already contains an audit. Reuse its established audit-report destination, which must be distinct from `overview.html`; do not replace the overview with an audit checkpoint. `<audit-report>` below denotes that destination, and `<snapshot>` and `<backup>` are chosen maintenance output paths in the existing audit workspace.

```text
python <skill>/scripts/paper_audit.py status <db>
python <skill>/scripts/paper_audit.py validate <db>
python <skill>/scripts/paper_audit.py checkpoint <db> --out <audit-report>
python <skill>/scripts/paper_audit.py export <db> --out <snapshot>
python <skill>/scripts/paper_audit.py backup <db> --out <backup>
```

Commands emit JSON receipts. Exit codes distinguish acceptance (`0`), invalid data (`2`), conflict (`3`), incompatibility (`4`), unavailable source (`5`), and rendering/publication failure (`6`). Report the structured error code. An incomplete audit can be a successful status query with `process_complete: false`; it is not a failed command.

`status` distinguishes structural health, source limitations, review coverage, mathematical assessments, and published revision. `validate` checks structure and evidence bindings, not proof correctness. `checkpoint` preserves the previous HTML when rendering fails. `backup` provides full recovery; a mathematical export does not restore an operational controller session. Use proofcheck's continuation guidance when resuming an existing proofcheck audit. Do not edit either store directly with SQLite.

The audit reader keeps major-result graph conventions while exposing its richer recorded evidence separately. Any audit assessment derives from those audit records; the overview's source-comparison colors or counts must not be reinterpreted as proof judgments.
