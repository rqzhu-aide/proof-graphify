# Graphify current-record edit template: implementation handoff

Prepared 2026-10-12. This is a revision plan, not an implemented command. Baseline: Proof Graphify 3.2.5, Proof Check 3.2.4, shared core 3.2.4.

## Purpose and bounded benefit

Provide an optional command that packages explicitly selected current records into a ready-to-edit native batch. It replaces the agent's custom extraction and batch-construction code. The agent still reads the current wording, makes the scientific correction, submits through `apply`, and compares affected content through the existing workflow.

The command is useful when an edit batch needs preparing. When complete current records and their snapshot are already available, direct batch authoring remains valid and may be shorter. Do not insert template generation into every authoring, retrieval, comparison or delivery operation. It does not inherently reduce command count, remove mathematical reading or establish a measured whole-run speedup.

## Public contract

Add one command to `proof-graphify/scripts/paper_database.py`:

```text
python <skill>/scripts/paper_database.py edit-template <db> --item ITEM_ID --use USE_ID --output work/correction.json
```

Both `--item` and `--use` are repeatable; at least one target is required. Support existing selected items and uses only. Do not add anchors, creates, removals, automatic neighboring records, historical snapshots or a new merge/patch operation. Users can still prepare other supported edits through the existing batch interface.

Resolve all targets from one current call to the existing public `export_snapshot`. Preserve the full canonical record exactly, including optional fields and evidence references. Generate one ordinary `apply` batch:

```json
{
  "expected_snapshot": "SNAPSHOT_RETURNED_BY_THE_EXISTING_READER",
  "edits": [
    {"collection": "items", "op": "upsert", "id": "ITEM_ID", "record": {"...": "complete saved item"}},
    {"collection": "uses", "op": "upsert", "id": "USE_ID", "record": {"...": "complete saved use"}}
  ]
}
```

The abbreviated record objects above illustrate the envelope only. Actual output contains complete saved records, with no placeholders, newly drafted scientific wording, source comparisons or status defaults. Include only named targets. Deduplicate repeated IDs within each collection, preserving first occurrence; emit items first, then uses. An item and use with the same textual ID remain distinct targets. Reject empty selection or any unknown/unselected target before creating output. Do not look up hidden common-store records as a fallback.

Return a compact JSON receipt containing exactly `output`, `expected_snapshot`, and `targets` (a list of `{collection, id}`). It reports a generated edit input, not a scientific change or complete database export. Keep the current JSON error/exit conventions.

## Implementation ownership

Implement `edit_template(db_path, output_path, *, item_ids=(), use_ids=())` as an ordinary outer helper in `paper_database.py`. It calls the already adapted public reader and constructs the batch. **Do not register the helper in `_adapt_common`.** That adapter substitutes a temporary projection path for a common database; output protection and publication must refer to the original database. Use the existing schema-3 and common-store reading paths without raw SQL or a new core operation.

Validate selection, build the full batch and serialize it before publishing the output. Use UTF-8, `ensure_ascii=False`, `allow_nan=False`, indentation and a terminal newline. The command may create the requested parent directory. It must leave the authoritative database, records, versions, comparisons, sources and build history unchanged.

Require a `.json` output path. Refuse the database path and captured source paths; derive source paths from the returned source manifest and the existing `_source_root` metadata helper, without reading manuscript contents again. Refuse any existing destination, including an in-progress draft. No overwrite flag is needed for the first version.

Create the output exclusively, using the original absolute pathname for the exclusive open. Use resolved paths for database/source collision checks, but do not resolve a dangling output symlink into a different path before opening it. Ordinary exclusive creation protects an existing directory entry. Keep error cleanup limited to a new file this operation actually created; retain unrelated files and drafts. No locks, staging database, retry loop or publication service is added.

Do not call `_write_export` unchanged: it replaces existing files and labels its receipt as `export_snapshot`. Its existing export behavior stays unchanged.

Add parser help, the repeatable target options, required `--output`, and a dispatch branch. `get`, `apply`, comparison handling, renderer, shared core and Proof Check remain unchanged. The existing public projection may create and remove a temporary SQLite file beside a common database; the new command inherits that already documented writable-directory requirement.

## Correction and freshness behavior

The generated file describes current saved records. The agent edits intended fields while retaining other content, then calls the existing `apply` once for the coherent batch. It also corrects affected proof ideas, qualifications and connection explanations where needed. The file is an input; the saved database remains authoritative after submission.

Existing `apply` checks the selected semantic `expected_snapshot`. Intervening relevant content changes reject the old batch. A comparison observation or an unrelated audit-only change need not change that snapshot. Do not introduce a requirement to reject every newer common database revision.

Generating a new template does not authorize transplanting an old replacement or judgment onto its newer snapshot. If its current contents differ from the context previously inspected, reconcile the relevant changes using existing guidance. Do not change an old batch's snapshot solely to force acceptance. This is conditional handling of changed context, not another obligatory retrieval or comparison pass.

Template generation supplies no source evidence beyond the canonical references already in the records. Use source/context already available; retrieve missing evidence with existing `get` only when needed. Scientific comparison and affected continuation remain exactly as before. Generating or applying a template never creates a favorable judgment automatically.

## Instruction edit

In `proof-graphify/references/database.md`, under `Apply a bounded batch`, replace the paragraph beginning "`get` returns complete canonical records" through the sentence "For a connection, copy its complete entry ... collection `uses`" with the following. Retain the preceding full-record-upsert warning and the following native JSON example for anchor and metadata work.

````markdown
`get` returns complete canonical records in `item`, `prerequisite_items`, and `incoming_uses`, including optional fields. When the exact current records and `expected_snapshot` are already in context, copy them directly into one edit batch; no template command or repeated retrieval is required.

To avoid manual record extraction and envelope construction for existing selected records, optionally generate one native batch for the named items and connections:

```text
python <skill>/scripts/paper_database.py edit-template data/paper-records.sqlite --item projection-lemma --use COPY_EXISTING_PROJECTION_USE_ID --output work/correction.json
# Edit intended fields in work/correction.json, retaining other saved content.
python <skill>/scripts/paper_database.py apply data/paper-records.sqlite work/correction.json
```

Use existing IDs. Repeat `--item` and `--use` for other records you intend to edit in the same batch; omit `--use` for an item-only correction. The helper copies their complete current records and one `expected_snapshot` into a new `.json` file, preserving any existing output file. It supplies edit inputs, not source context or a scientific comparison. Reuse available context; use `get` only when current argument or evidence context is needed.

Change the intended fields and retain unaffected fields and evidence links. When correcting a mathematical fact, also correct its affected occurrences in `proof_idea`, `issue`, and related connection reasons or regimes before comparing the edited content.

If the generated snapshot differs from the context used to develop the correction, inspect its saved wording and consider intervening changes before carrying over old replacements or judgments. A stale apply batch follows [Resume and recover](#resume-and-recover); changing only its expected snapshot does not reconcile those changes.
````

Keep `SKILL.md`'s ordinary command sequence unchanged. It already directs authors to `database.md`; inserting `edit-template` into that sequence could turn an optional convenience into a routine extra operation. No new example in Proof Check or separate correction workflow is needed.

## Focused implementation acceptance

Add behavior tests in the existing `proof-graphify/tests/test_paper_database.py` and `tests/new_format/test_sql_overview.py` as appropriate. Reuse small native/common fixtures. The programmer should cover these contracts without introducing a new test framework:

1. A selected item-and-use template contains exact complete records and one consistent current snapshot. Optional scientific fields, canonical anchors and evidence survive a one-field local correction submitted through existing `apply`.
2. Template generation alone changes no database content/history or source comparison. Applying a scientific correction preserves past judgments and leaves current comparison decisions to the existing freshness rules.
3. A stale template is rejected after a relevant saved change, without modifying the newer records. Existing comparison-only and compatible audit-only writes do not become automatic conflicts merely because a common revision advanced.
4. Common-store corrections preserve audit-owned extensions and unselected records. Existing endpoint/application consistency rules still reject contradictory edits.
5. Empty, unknown or unselected targets produce a useful error without output. Repeated target flags yield one edit per collection/ID. No unnamed neighbors appear.
6. Existing draft, database and captured-source destinations retain their bytes, and a registered missing source path cannot be created as a batch. New output is valid UTF-8 JSON, including mathematical backslashes and non-ASCII text. Exercise an injected write failure to verify cleanup removes only output created by that call. Add alias tests where the host supports them; document unsupported link creation rather than bypassing the host restriction.
7. Exercise the new CLI parser, receipt and one generated-file-to-`apply` round trip. No test should depend only on instruction wording or headings.

Run the targeted tests and the existing relevant database suites once after implementation. Run the skill's structural validator after the documentation change. No full-paper proof audits, repeated renderer campaign or new routine per-paper check follows from this feature.

## Release and scope

The implementation should touch one Graphify CLI file, one Graphify reference, and the focused existing test files. A new output-writing helper, if useful, stays local to that CLI module. No database migration, core rebuild, dependency, source-writing permission, Proof Check edit or version change is part of this planning task. Any later release should advance only the affected Graphify skill; core and Proof Check versions remain independent.

Use the current working tree, preserving its existing unrelated edits. The baseline repository HEAD is `e11bc293cd111e9f3d4f9c52af51a945956f0694`; HEAD alone does not identify all pending work. Validation evidence and input hashes are retained under `C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-plan-20261012`.

## Independent validation and resulting revisions

Three independent `gpt-6.1-sol` reviewers with `xhigh` reasoning assessed the proposal in jobs bounded to eight minutes. They reviewed the command contract, exercised a disposable prototype, and traced the workflow cost. All supported the optional helper with the refinements above.

The executable prototype passed in native schema 3, common storage 4 under the overview workflow, and a common audit store. It copied exact selected records from one public export, preserved optional scientific fields and evidence through an edited apply, left generation read-only, rejected stale batches, and demonstrated atomic rejection of an invalid paired item/use batch. Audit-owned scope extensions and unselected audit content survived. Separate probes confirmed that comparison-only writes and a compatible audit-only scope write preserved semantic snapshot validity and intervening history.

The contract reviewer demonstrated that the existing export writer replaces an in-progress file and labels an edit-shaped object as an export. That is existing export behavior, not a new regression. It makes a separate, small exclusive-create writer necessary for this proposed command. The workflow reviewer found that requiring template generation would add a command when complete current records are already in context. Therefore the final plan retains direct batching and leaves the ordinary `SKILL.md` sequence unchanged.

The plan incorporates four precise refinements from review: optional use, no common-adapter registration, explicit selected targets only, and preservation of existing output files. It retains existing semantic freshness rather than adding a whole-database revision lock. It also distinguishes a new template's current snapshot from the older context used to develop a correction, without mandating another retrieval.

The prototype establishes mechanical feasibility, not completion of this handoff. Production parser wiring and the final writer contract remain to be implemented and tested. In particular, the prototype resolves the output path before opening, does not protect registered missing manuscript paths, and serializes while the file is open; the final implementation must follow the stronger, small writer contract above instead of copying the prototype verbatim. Host permissions prevented alias construction, so alias-specific behavior was not executed. Broader audit-extension combinations, legacy grouped uses, intermediate owner fields, relocation cases, and model behavior were not exhaustively tested. No elapsed-time improvement or full-paper scientific validation is claimed.

Reviewer reports and executable evidence:

- [Command and failure contract](C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-plan-20261012/contract/REPORT.md)
- [Three-format mechanism experiment](C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-plan-20261012/mechanism/REPORT.md)
- [Workflow action traces and instruction review](C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-plan-20261012/workflow/REPORT.md)

The first mechanism fixture used a formal group in a focused profile and was rejected by existing rules. A later probe initially requested a scope through an unsupported packet target. The reviewer corrected only these disposable fixtures and retained the failed outputs. These failures do not establish defects in the current skill or in the proposed helper.
