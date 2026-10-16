# Source-comparison workflow: implementation handoff

Status: implemented 2026-10-12. See [implementation and validation](source-comparison-workflow-implementation.md). The companion patch records the exact applied instruction changes.

## Outcome and scope

Make Graphify's existing source comparison easier to complete while the relevant source passages are still in context. Assemble a coherent group's known statements, prerequisites and connections, save them, then explicitly compare their current saved scientific content with the source. Continue from the authoritative SQLite records when a correction is needed.

This changes three Graphify instruction files, adding 79 words net. SQLite already supplies the required tracking. Python remains an optional way to prepare inputs, and the existing current-record correction example remains intact. No new command, schema, tracking object, review pass or runtime dependency is needed.

Proof Check requires no edit for this issue. Its current instructions already cover source judgments during registration, preservation of primary reasoning, affected continuation, independent review and frozen presentation. Archify visual migration and the deferred continuation-assessment change are separate work.

## Exact implementation

Paths below are relative to the `proof-graphify` repository. Apply [source-comparison-workflow.patch](source-comparison-workflow.patch), or make the four edits below exactly. Preserve all surrounding instructions.

### 1. `proof-graphify/SKILL.md`: group the existing duties

Immediately after `## Select and build`, insert:

> Work in coherent argument groups, keeping their source passages and setup in context. Assemble each group's known relevant prerequisites and connections before recording comparisons; unrelated branches can proceed independently.

This is a working order, not a new database group, fixed batch size or whole-paper readiness gate. Keep the five existing responsibilities. Do not instruct the agent to repeat numbered steps 2 through 4, because step 2 includes initialization.

In step 5, replace only:

```text
before bulk comparisons
```

with:

```text
before recording the affected group's comparisons
```

Keep `When math or labels need a display check, render the current draft` and the rest of the step unchanged. Preview stays conditional and uses the existing render command. This introduces neither a subset-render feature nor a new finalization stage.

### 2. `proof-graphify/references/authoring.md`: compare the saved group explicitly

Under `## Compare and display`, replace only the first sentence with these two sentences:

> After the group's known shared setup and relevant incoming connections are assembled, compare every scientific claim in the current saved `statement.text`, any `proof_idea`, `reason`, `issue`, and `regime` with its supporting passages and applicable setup, using the bounded packet or exact current records already in context. Save the comparison while that evidence is available; successful authoring or earlier source reading alone does not establish a match.

Keep the following conditions, formula checks, PDF inspection, assumption-to-arrow checks and correction guidance unchanged. The comparison concerns the actual saved record and its relevant context. Earlier source reading alone cannot preapprove a future record.

### 3. `proof-graphify/references/database.md`: keep useful receipts

Under `## Resume and recover`, replace only the first sentence with:

> Keep the command's actual success receipt. After an interruption or uncertain command result, including one hidden or ambiguously summarized by a wrapper, retain the authoritative database and inspect current records and comparison states before repeating a write.

Keep the remaining recovery instructions and both existing correction/comparison examples unchanged. A successful command needs no additional read-back. This addresses the observed loss of useful receipt fields in a custom wrapper without adding a new receipt format or recovery system.

## Behavior that must remain intact

- Initialize once and extend or correct the existing database through public commands. Newly initialized records remain unreviewed. A comparison explicitly identifies its item and connection targets and records the actual judgment.
- Reuse current records and source evidence already in context. Fetch missing or uncertain current state when needed. Keep serializers, sensible batches and the existing full-record correction example; an `upsert` preserves only the fields supplied.
- Finish known relevant shared setup and incoming links before comparing their consumers. Later discoveries still receive affected comparison. Relevant prerequisites, connections or selected source changes can invalidate a comparison even if its own statement is unchanged. Existing freshness and reviewed-reuse rules determine the affected work.
- Keep unresolved interpretations visible. Source agreement is distinct from proof correctness. An item's comparison does not silently compare its incoming connections.
- Final delivery does not require another source sweep of unchanged current comparisons. Presentation repairs reuse saved scientific input; a discovered scientific defect receives affected correction and examination.

For Proof Check, preserve independent review and integration. See `stat-proof-check/references/graph-records.md`, especially the source-judgment explanation and `correct-claim`/`--sync-current` guidance; `phase1-drafts.md` for matching saved reasoning to consolidated questions; and `reporting-and-release.md` for the frozen presentation boundary. These existing instructions are sufficient, so adding another example would repeat them.

## Validation and implementation acceptance

Three independent GPT-6.1 Sol reviewers using xhigh reasoning checked wording, exercised the public database workflow and challenged the unchanged Proof Check scope. Each assignment had an eight-minute limit. The reviews removed ambiguous repeat-initialization wording, a possible extra finalization step, an implied subset-render capability and a redundant database paragraph. The original broad recovery trigger was retained.

A fresh isolated public-CLI probe used the bundled Graphify runtime and the existing representer-theorem example. It confirmed:

1. Initialization left three items unreviewed. Adding two connections left all five targets unreviewed.
2. Explicit comparison returned `recorded`, `reused`, `snapshot_id` and `common_revision`. The CLI receipt omits the Python API's full observation payload. The comparison did not change the mathematical snapshot, so that snapshot alone cannot show whether a comparison write occurred.
3. Corrections copied from current records retained `proof_idea`, passages, regimes and evidence references. The affected comparisons became stale.
4. A later prerequisite qualification invalidated its direct consuming context while the fixture's unaffected distant context remained current. This is a fixture result, not a guarantee that every edit has only local effects.
5. Exactly ten observations were written for batches of five, two and three targets, without duplicate writes. Every observation was labelled `needs_attention` with a mechanical-test note; none claimed a new scientific match. This shows a viable sequence, not automatic duplicate suppression. The probe's inspection calls are test assertions, not added per-paper duties.

Before applying, check the patch against the current working tree. After applying, inspect the three-file diff and confirm the anchors and surrounding scientific requirements are preserved. If implementation matches this validated patch and runtime files are unchanged, do not repeat full proof audits or renderer suites. Re-run the bounded probe only if implementation changes a demonstrated contract or the runtime has changed since this validation. Do not add tests that merely assert instruction wording.

Earlier historical replays provide complementary regression evidence: Graphify 3.2.0 KEDRL, 3.2.3 RF-HTE and 3.2.4 Fast-SDE; Proof Check 3.2.2 and 3.2.3 RF-HTE and 3.2.4 Fast-SDE. They verified correction preservation, context-sensitive freshness, accepted-work reuse and scientific-change rejection. Two frozen Proof Check results also rendered without opening a live database. This handoff changes no rendering code, and neither validation round establishes browser appearance after an Archify migration.

The expected benefit is less reconstruction and fewer avoidable repeated comparisons. A same-source, same-model paired application is necessary before claiming improved model behavior or a measured time saving. That experiment is neither a release blocker for these wording changes nor a recurring requirement for ordinary papers.

## Baseline, handoff and release boundaries

Canonical repository: `C:/Users/zrq/projects/skills/stat-paper-skills/proof-graphify`.

The patch is based on the current working tree, not clean HEAD alone. HEAD was `e11bc293cd111e9f3d4f9c52af51a945956f0694`, with substantial pre-existing edits. Preserve them. If the patch does not apply, inspect changed anchors and adapt only the four specified edits; do not replace whole files or reset the repository.

| File | Baseline SHA-256 |
| --- | --- |
| `proof-graphify/SKILL.md` | `7cfaa39b4a77c70499b622907ea1f058bae7de2b6d1cb5117ed9aa6a8e835451` |
| `proof-graphify/references/authoring.md` | `2203a6357b76d4a3e09ad38ab7461d38ca2a436e7858730576153300cc26c502` |
| `proof-graphify/references/database.md` | `d7b6d2102bef20e1b486dc1bb7b4800b489dccb021166bab8f3a0c75a678a38e` |

The current canonical and installed cores both carry version 3.2.4 but contain different bytes from other pending work. Do not synchronize or attribute behavior from version labels alone. This handoff requires no core or Proof Check version change. Versioning, installation, commit and push are separate release actions, outside this plan.

Validation artifacts are retained under `C:/Users/zrq/projects/skills/stat-paper-skills/tmp/source-first-handoff-validation-20261012`: `candidate.patch`, `baseline.json`, `candidate-validation.json`, three reviewer reports and the executable `contract/probe.py` with its receipts. The prior historical investigation is under the sibling `source-first-validation-20261012` directory. These are development evidence, not new artifacts required during ordinary skill use.

During plan validation, the patch passed `git apply --check`, and hash checks covered 716 pre-existing repository files without changes. That round added only handoff artifacts. Subsequent implementation and its validation are recorded in the linked implementation report.
