# Graphify edit-template implementation

Implemented 2026-10-12 against the current working tree and [validated handoff](graphify-edit-template-handoff.md). The optional command is available in the canonical source package. No release, installation or remote publication was performed. Versions remain Graphify 3.2.5, Proof Check 3.2.4 and shared core 3.2.4.

## Result

`edit-template` copies explicitly named saved items and connections into one complete, editable native `apply` batch. It obtains one current semantic snapshot, preserves optional fields and evidence links, and produces no database change or comparison. The agent edits the generated file and submits it through the existing writer. Existing files are never replaced.

```text
python <skill>/scripts/paper_database.py edit-template data/paper-records.sqlite --item ITEM_ID --use USE_ID --output work/correction.json
# Edit the intended fields while retaining other saved content.
python <skill>/scripts/paper_database.py apply data/paper-records.sqlite work/correction.json
```

Both target flags are repeatable and either may be used alone. Only explicitly selected records are included. Repeated target IDs are deduplicated within each collection. The receipt contains `output`, `expected_snapshot` and `targets`.

Generation remains optional when complete current records and their snapshot are already available. The existing full-record upsert, affected-context comparison and recovery rules remain in force. Relevant semantic changes reject stale corrections; compatible comparison-only and audit-only updates do not introduce unnecessary conflicts.

## Change ownership

| File | Change |
|---|---|
| `proof-graphify/scripts/paper_database.py` | One outer helper and CLI wiring. Calls the existing public export once; uses exclusive file creation; protects the database and captured sources, including missing registered sources; serializes before creating output; cleans up an owned partial output after failure. |
| `proof-graphify/references/database.md` | Replaces custom Python extraction/envelope code with optional template/edit/apply instructions. Explicitly retains direct batching and reuses available context. Names the template as a source of `expected_snapshot`. |
| `proof-graphify/tests/test_paper_database.py` | Eleven focused tests for native records, CLI behavior, freshness, selection, output protection and failure cleanup. |
| `tests/new_format/test_sql_overview.py` | Four focused tests for complete shared records, audit extensions, history, unselected content and semantic freshness. |

The helper is deliberately outside `_adapt_common`: its existing public reader already supports both storage formats, while output protection refers to the authoritative database. No core operation, schema migration, dependency, proof-check change, routine review stage or additional per-paper validation pass was introduced. `SKILL.md`'s ordinary sequence is unchanged.

## Validation

Three `gpt-6.1-sol` agents with `xhigh` reasoning completed bounded jobs within eight minutes. Two independently authored and ran focused native/common tests; the third reviewed the production implementation and performed a fresh real CLI correction trial. No concrete implementation defect remained.

The focused additions cover exact full-record copying, UTF-8 mathematical text, canonical evidence, database/source immutability during generation, preserved history, stale correction rejection, compatible comparison/audit updates, selected-record boundaries, duplicate IDs, item-only/use-only selection, compact receipts, JSON errors, existing drafts, protected sources and injected write failures. Existing common endpoint/application consistency tests also passed.

Integration exercised 83 distinct test cases across the two existing database suites: 82 passed and one symlink case was skipped. The native suite initially encountered the known restricted-terminal Python startup warning in three pre-existing CLI tests; all three passed when rerun unchanged under normal access. The shared suite passed all 25 tests after moving its temporary fixture location to the writable task directory. Its first attempt failed during fixture setup because the sandbox's default temporary directory was not writable. These environmental attempts and their outputs were retained; no production workaround or weakening of existing tests was added.

Commands used the shared global Python installation with `-E -X utf8 -B`:

```text
python -E -X utf8 -B -m unittest discover -s proof-graphify/tests -p test_paper_database.py -v
python -E -X utf8 -B -m unittest discover -s tests/new_format -p test_sql_overview.py -v
```

The skill structural validator, CLI help and whitespace checks passed. The independent fresh common-store trial executed initialization, template generation, a coherent statement/proof-idea/connection correction, apply, and an explicit synthetic `needs_attention` comparison. It also confirmed draft preservation, missing-source protection and cleanup after a partial write. It did not claim a scientific match.

## Evidence and limits

Evidence is under `C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-implementation-20261012`:

- [Native tests and interventions](C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-implementation-20261012/native/REPORT.md)
- [Common-store tests](C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-implementation-20261012/common/REPORT.md)
- [Independent CLI review](C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-implementation-20261012/review/REPORT.md)
- [Final source identities and scope check](C:/Users/zrq/projects/skills/stat-paper-skills/tmp/edit-template-implementation-20261012/scope-after.json)

The scope check compared 720 pre-existing repository files against their starting hashes. Only the four intended files changed; the pre-existing dirty work, shared core, Proof Check, version declarations and repository HEAD were preserved. This report is an additional new artifact. HEAD remains `e11bc293cd111e9f3d4f9c52af51a945956f0694`; the final CLI SHA-256 is `9d5dff94be2f5b5b8c4bb980a9362bb8351030a4ede8c430748ed5f306ba0716`.

Windows denied symlink creation with error 1314, so alias-specific execution remains untested on this host. No full-paper scientific audit, installed-mirror campaign or measured end-to-end speed comparison was performed. The supported benefit is less custom copying and batch construction, with no new mandatory step.
