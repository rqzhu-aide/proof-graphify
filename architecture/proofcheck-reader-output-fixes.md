# Reader and output fixes, 2026-09-28

Implemented in the maintained repositories without changing the database, audit architecture,
completion rules, or mathematical records. The changes were developed on proof-check 2.3.3, shared core
2.3.3, and graphify 3.1.7, then included in the 2.3.4, 2.3.4, and 3.1.8 version bumps respectively.
At the time of this validation, these source changes had not yet been installed or published.

## What the new runs show

Reviewed the proof-check 2.3.3 and graphify 3.1.5 distributional-RL test sets from September 27.

1. **The HTML exposes too much workflow detail.** Two proof-check reports open with 27 and 32
   list entries, many containing raw record IDs, before reaching the graph. The work queue also
   expands up to 20 entries by default. These are useful recovery details but obstruct reading.
2. **The folder convention is incomplete.** Proof-check explains its output folder after examples
   have already created files. Graphify describes `work/` too narrowly, causing some runs to put
   extraction files and helpers in a second folder. Most of the 103 to 758 proof-check files per
   case are legitimate assignments, responses and recovery artifacts. Harness logs and duplicate
   error reports are separate test evidence.
3. **Nodes exist, but the default camera can hide them.** All ten final pages contain graph nodes:
   14 to 24 for proof-check, 15 to 19 for graphify. Both viewers automatically zoom into one result
   at startup. Proof-check also stacks disconnected components vertically, producing a particularly
   narrow 242 by 2956 canvas in one run. Static geometry and runtime inspection support this
   explanation; live browser appearance was not verified.
4. **Some missing structure is real.** One proof-check report records 18 results and zero connections.
   Changing the display cannot recover dependency analysis that was never recorded. Four proof-check
   reports also contain no authored delimited formulas, so the renderer has no math spans to typeset.
   This is not a missing converter in those reports.

## Changes

- Keep technical completion diagnostics and the work queue behind expandable sections. Keep
  incomplete status, source limitations and independent-review qualifications visible. Use readable
  result and finding labels, retaining exact IDs and navigation in the audit evidence.
- Open both viewers on the full graph. Keep explicit readable-focus controls. Pack disconnected
  audit components into rows, preserving their internal layout and every connection.
- State the recorded node/connection counts. Explicitly distinguish an empty connection set from
  evidence that results are independent.
- Establish one chosen output folder before creating audit files. Put assignments, responses,
  recovery directories, extraction text, images and helpers under its `work/`. Link the report
  and database at delivery. Preserve durable data and registered source locations.
- Require explicit LaTeX delimiters in authored mathematical text, preserving captured source
  excerpts. Render an early checkpoint to compare the recorded map with the declared scope.

The existing six-file assignment package and recovery behavior remain intact. These edits do not
attempt to solve the separate submission, qualification or unfinished mathematical-work failures
reported in the run logs. Instruction changes still need confirmation in a fresh agent test.

## Validation and examples

Regenerated five proof-check reports from their saved projections. All five pass renderer geometry,
representation and independent Python acceptance. Their embedded projections, node/connection
identities and original report files remain unchanged. The generated review copies are working
reports, not new audit decisions or releases.

| Case | Nodes | Connections | Original canvas | Revised canvas |
|---|---:|---:|---|---|
| Claude | 24 | 13 | 792 × 2672 | 1058 × 1688 |
| Codex | 18 | 0 | 242 × 2956 | 774 × 988 |
| DS4 | 14 | 18 | 1342 × 828 | 1342 × 828 |
| GLM | 18 | 14 | 1067 × 1744 | 1067 × 1308 |
| K3 | 24 | 20 | 1342 × 1840 | 1342 × 1512 |

- Publication and reader tests: 60 passed, 33 subtests.
- Packaging and skill structure: 59 passed, 1 skipped, 10 subtests.
- Graph renderer, interactions, layout and packaging: 19 passed, 2 subtests.
- Shared renderer selftest: 14 checks passed; interaction harness: 7 fixtures passed.
- Both skill definitions validate. Both 45-file shared-core bundles match.
- Independent code review found no remaining actionable issue in this scope.

Bundle source identity: `ea8468e5f54fcd542973fc40d0c4e8000422b2224948ec96c4f6314ce35b541d`.

Local evidence, not included in the repository: [cleaned report with the strongest clutter/layout failure](../tmp/reader-cleanup-2026-09-28/previews/codex-gpt-sol6-high/report.html)
and [cleaned report with recorded connections and typeset mathematics](../tmp/reader-cleanup-2026-09-28/previews/claude-opus5.5-xhigh/report.html).
The other three reports and the reproducible comparison scripts are in the same evidence directory;
[comparison receipts](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/reader-cleanup-2026-09-28/report-comparison.json)
include source hashes and preservation checks.

Live visual inspection remains unverified: the browser tool rejected local-file URLs and prohibited
workarounds. The UI guidance search did not return a relevant clutter pattern; the presentation
changes instead follow the concrete report evidence and ordinary disclosure behavior. The original
test results, experimental copies and installed skills were not changed.
