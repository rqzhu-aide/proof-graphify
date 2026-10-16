# Targeted Graphify runtime revision plan

2026-10-13. S1/S2 and H1/H2 are implemented and independently validated. See the [implementation report](graphify-runtime-implementation.md) for actual changes, tested identities and results. Deferred work below remains deferred.

The objective is to remove repeated construction, transcription and recovery work while retaining the existing source-comparison standard. The completed Fast-SDE evidence supports a small workflow patch first. It does not support a universal 15-minute target or attributing the entire elapsed time to the skill.

Canonical repository: `C:/Users/zrq/projects/skills/stat-paper-skills/proof-graphify`. Repository-relative paths below start there. Separate harness owner: `C:/Users/zrq/projects/skills/_testing-center/run-test.sh`. Baseline HEAD: `e11bc293cd111e9f3d4f9c52af51a945956f0694`, with substantial pre-existing edits preserved. Graphify is 3.2.5; Proof Check and the shared core are 3.2.4. The authorized implementation covers the immediate skill and harness changes. Releases, installation, commits and live test runs remain outside this implementation.

This is the immediate priority plan after the completed-run investigation. It refines the instruction and harness parts of [the earlier efficiency handoff](graphify-efficiency-handoff.md). Its projection/cache/renderer optimizations remain separately scoped proposals, with the qualifications in the [cost reassessment](../../tmp/graphify-efficiency-handoff-20261012/burden/assessment.md); they are not prerequisites for this patch.

## Skill changes

### S1. Demonstrate a saved-record correction instead of a seed rebuild

**Owner:** `proof-graphify/references/authoring.md`, escaping/serializer example and the paragraph immediately after it. `database.md` already owns full-record semantics and the optional edit-template helper; do not duplicate that tutorial.

**Evidence:** DSH reinitialized six databases. It explicitly reasoned that rebuilding was acceptable before any comparison existed. Current instructions already make SQLite authoritative, but the foreground repair example edits `work/seed.json`; the following paragraph also unnecessarily requires `get` when exact current records are already available.

**Edit:** retain the JSON escaping explanation, raw-string caveat and source-supported repair requirement. Replace the example with serialization of an already prepared canonical correction batch. Explain that the first edit in this example is the affected item:

```python
import json
from pathlib import Path
path = Path("work/correction.json")
batch = json.loads(path.read_text(encoding="utf-8"))
batch["edits"][0]["record"]["statement"]["text"] = r"Under Assumption 1, \(\lVert f\rVert \leq M\)."
path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
```

This is an optional serializer for an existing batch, not a new preparation stage or instruction to create a helper script. Direct file-tool editing remains valid. Preserve `expected_snapshot` and every other intended field. Keep one sentence that before initialization the same serialization technique can repair the seed's decoded fields.

Replace the post-example repair paragraph with the following substance:

> After initialization, correct the affected current full record through `apply`, following the database editing guidance. Reuse exact current records and their expected snapshot already available; retrieve only missing current record or source context. Keep the initialized database and its identities even before its first comparison. Seeds and exports are inputs or snapshots, not correction masters. Preserve unaffected fields and evidence links. Diagnostics identify specific corruption patterns, not every escaping mistake; use source evidence to resolve the repair.

Keep existing rules for explicit new overviews and captured imports. Keep affected scientific comparisons after edits. Do not add an obligatory edit-template call, record-fetch check, database backup, review gate or repair ledger.

**Developer acceptance:** pre-init seed correction; post-init correction before the first comparison; post-review correction retaining unaffected records and comparisons; exact current context already available; missing context. Validate that the example serializes a full existing batch without dropping optional fields or changing its snapshot. These are development cases, not a new paper checklist.

### S2. Make direct native returns and bounded stale-return handling explicit

**Owners:** the optional-review block of `proof-graphify/references/authoring.md` and two unconditional retrieval clauses in `proof-graphify/references/database.md`. Keep the native format, receipt-led recovery, observed-state semantics and transaction rules unchanged.

**Evidence:** Codex reconciled a second independently reconstructed map before native comparison recording. Claude used one subprocess per target. DSH replayed 73 exact judgments and substituted newer snapshot identifiers in old reviewer responses. Existing native batches, grouping and recovery already support the intended path; another response schema or review stage is unnecessary.

**Edit:** retain the current concise assignment with exact target records, source paths, response path and return channel. Make its output explicitly a ready-to-submit native comparison batch. Ask for one batch per coherent set of targets sharing an accurate result and note, with separate batches for substantively different findings. A unique note for every matched record is not required. Keep the source reading and the specificity of real concerns; grouping is never permission to mark unnamed or unexamined targets.

Replace the paragraph after the assignment with the following substance:

> Return the native comparison format directly. Preserve the expected snapshot of the inspected records. Use a shared result and note only where accurate for every named target; keep distinct findings separate. A pending return whose snapshot is stale stays unchanged. The coordinator can compare the affected current records and applicable source context using retained reading and the returned findings, recording its own current judgment under its own reviewer identity. If independent judgment is needed, ask about only the affected current targets. A coordinator judgment does not satisfy an explicit requirement for independent review of changed input. Do not relabel an old return to make it current. Already current comparisons remain saved; adding observations alone does not change the mathematical snapshot.

This is the existing comparison when input has changed, not an extra pass. Reuse exact current context where available and fetch missing context only. A changed source manifest or premise can matter even when displayed statement text is identical. For manuscript changes, follow existing refresh/change-review rules; do not equate unchanged text with unchanged meaning. A pending unrecorded return is not an eligible recorded historical comparison merely because it once inspected the target.

Retain completion-aware collection and the distinction between a completed save and a file merely existing. Preserve the existing `database.md` rule that known successful writes are not replayed and uncertain outcomes trigger inspection before retry. An error without a receipt does not by itself prove rollback; an isolated fault probe saved an observation before reporting failure. This is an uncertain outcome under the existing rule, not a new normal-write inspection. Do not add a check before normal writes or a new journal. Do not delete duplicate historical observations. Retain `needs_attention` as a valid completed inspection with an unresolved interpretation.

Remove two contradictory retrieval requirements in `database.md`: replace “Retrieve a fresh packet when the expected snapshot is stale” in Resume with “For a stale snapshot, use exact current records and relevant context already available; retrieve only missing current context before revising the batch.” In the Apply paragraph, replace “retrieve and review intervening changes” with “review intervening changes using current context already available, retrieving missing context as needed.” Reviewing intervening changes remains necessary; a redundant fetch does not. Leave the existing rule for an uncertain write intact, because a missing success receipt may require inspecting current saved state.

**Developer acceptance:** a native reviewer assignment produces directly usable batches; coherent shared notes versus distinct findings; a stale return following an editorial change versus a changed prerequisite/source setup; current comparison history survives unrelated changes; an uncertain write versus a known successful write; unresolved delivery. Confirm coordinator judgments are not falsely attributed to the earlier independent reviewer. No mandatory fresh reviewer or whole-map re-review is introduced.

### S3. Defer multi-file submission

Do not add `compare DB FILE [FILE ...]` in this patch. An isolated candidate reused the current writer sequentially. On disposable copies of the retained Claude database, eight separate CLI calls took 16.96/17.41 seconds; the same eight calls in one process took 12.91/14.41 seconds. One accurate shared-note batch for those eight targets took 2.11/2.49 seconds. These are two local trials with synthetic comparison notes, not whole-paper savings or a scientific review of the eight statements.

The candidate saves some startup/import cost but retains repeated projection/transaction work and adds a partial-success output contract. A simulated error after a successful commit also showed why “failed input” cannot always mean “rejected with no write.” Existing accurate grouping is the simpler immediate improvement. Distinct findings still remain separate; do not discard notes just to achieve the grouped timing. Reconsider a multi-file interface only if meaningful residual need persists after the simpler contract changes. No new request IDs, retry journal, transaction model or automatic deduplication is proposed.

### No additional presentation checks

Do not change browser selectors, add static HTML scans or introduce byte-size/URL checks. Existing guidance already uses the render receipt and actual browser interactions where available, with honest untested disclosure otherwise. DSH's character/byte mismatch was caused by its custom helper, not by the renderer. Do not add another rule for each observed agent mistake.

## Testing-harness changes

### H1. Remove the imposed second reconstruction for ordinary Graphify

**Owner:** `run-test.sh::write_reviewer_recipe` and the parent prompt construction in `cmd_launch`. This is separately owned and reviewed from the skill patch.

Branch only for the recorded `proof-graphify` run identity. Read the first skill token in that run's `test-id` for both main and followup. Retain the previously validated compatibility behavior for missing/invalid identity and other skill names; do not use a mutable `.current-skill` to classify followup. The detailed selector and compatibility cases in the earlier H1 remain applicable.

For ordinary Graphify, the launcher is optional transport. Replace the source-only/scaffold paragraph in both parent prompt and generated recipe. Keep the existing four arguments: clean working directory, role-prompt file, bounded-assignment file and new stdout path. The assignment can be ordinary text and identifies exact saved records/packet and source locations. The recipe reads the role and appends the assignment path, for example:

```bash
printf -v prompt "%s\n\nBounded assignment file: %s\n" "$prompt" "$delivery"
```

Do not drop argument 3. Remove the Graphify-specific exclusions that hide saved primary records or require generated question-ID scaffolds. Preserve configured model, effort, provider/profile, fresh session, separate stdout/stderr, response delivery and exit code. Preserve parent followup/resume behavior; reviewers still use the fresh route.

An explicit user benchmark requesting source-only reconstruction keeps that requirement in its assignment. Proof Check retains its existing independent-review contract and recipe text. Optional independent review never removes Graphify's ordinary source comparison.

### H2. Stop unavailable-transport detours at the harness boundary

**Owner:** the same Graphify-specific parent guidance introduced by H1. This is a conditional instruction, not a new preflight or tool call.

The combined parent guidance should say:

> Optional same-model fresh reviewer launcher: PATH. If assigning a reviewer, pass a clean working directory, role prompt, bounded assignment file and new stdout path. Follow the user's assignment and the skill's review contract. This launcher adds no review requirement. Preserve assigned snapshot identities. If the route is unavailable because of confinement or permissions, report that limitation instead of reconstructing the launcher. Another already available authorized route may be used only if it preserves the configured provider, model, effort and fresh context. An unavailable optional reviewer does not prevent the author's source comparison. Review required by the user or skill remains unfulfilled if no permitted route can perform it. Original stdout and stderr are retained separately.

Retain routine correction of an ordinary path typo. The unfulfilled-review rule includes required saved-record independent review, not only source-only benchmarks. Do not require per-paper runtime checks, install dependencies, rebuild profiles or bootstrap another CLI. Do not add model-specific scientific instructions. The observed module-path error came from an agent-built PowerShell route; it does not establish a defect in the supplied Bash quoting. Repair a transport implementation only after reproducing its own defect, separately from this prompt change.

**Developer acceptance for H1/H2:** use an isolated copy and fake CLIs, never live launch/prep/followup/harvest. Cover Graphify main and followup, Proof Check unchanged behavior, an unrelated skill, absent/invalid run identity, explicit source-only benchmark, model/effort/freshness and argument-path preservation, no overwriting existing captures, and nonzero exit propagation. Include an unavailable route: optional review may be omitted honestly; required independent review must not be silently replaced by author review.

### Separate host issue: post-delivery process lifetime

Codex had at least 24 minutes after delivery before process termination. This is outside the skill patch. The precise shutdown cause is unproven. A separate host/harness task should reproduce the existing `run_agent` exit/stdio behavior with normal completion, final-looking text followed by more work, and a descendant retaining output handles. Inspect defined structured terminal events only if actually available.

The isolated validation already supplied a counterexample to a simple inherited-pipe explanation: the unchanged wrapper, which redirects output to a regular log file, returned in about 0.15 seconds while a descendant retained stdio; a direct pipe control waited about 2.1 seconds. This does not reproduce the actual Codex failure. Follow the actual CLI/host process ownership in a separate diagnosis rather than treating pipe closure as an established fix.

Do not kill a process because prose says “done,” an HTML file exists or output is quiet. Do not impose a new scientific-review deadline. Keep `timing.tsv` as process wall time and active time unknown where unmeasured. Existing operator-reported manual termination remains distinct from directly proven process events. Host diagnosis is not a skill-release blocker or an extra paper task.

Use existing archived provider/model/effort and assignments when interpreting version comparisons. The DSH configuration changed. No new telemetry system is part of this plan.

## Workload, implementation order and completion

| Change | New required paper operations | Work removed or replaced | Scientific requirement retained |
|---|---:|---|---|
| S1 | 0 | Seed/database/packet rebuilding and redundant retrieval during a local correction | Exact current full-record edit and affected source comparison |
| S2 | 0 | Custom response conversion, needlessly individual notes, whole-review restarts and replay of known successes | All named scientific claims compared; distinct findings, current context and honest reviewer attribution |
| H1 | 0 | Automatically imposed second map and reconciliation | Ordinary Graphify comparison; explicitly required independent review |
| H2 | 0 | Building/debugging another launcher inside a paper task | Configured reviewer identity and honest disclosure of unmet requirements |

Implement H1/H2 as one harness patch and S1/S2 as one small skill-documentation patch. They are independently reviewable. The immediate plan changes two skill reference files and one separately owned harness file. It requires no change to the shared core, Proof Check, database CLI, storage format or browser validation. The multi-file candidate is deferred.

Run the affected developer probes once on the final candidate and rerun only affected failures. Preserve source evidence, prior observations and pre-existing repository work. No new recurring model audit or full-paper benchmark is required by the delivered skill. A later controlled application can measure adoption and elapsed savings, holding effective configuration and assignment fixed; this planning task does not measure that outcome.

Expected benefit is conditional: the harness change removes an extra assignment in testing-center use; local-edit and direct-return guidance help when an agent otherwise reconstructs or replays work. Scientific reading, legitimate correction, provider latency and the host tail remain. The evidence does not justify a promised total or percentage saving.

## Independent validation

Three new `gpt-6.1-sol` / `xhigh` jobs independently validated the plan and each finished within its ten-minute limit. All prototypes and reports are isolated under `../../tmp/graphify-runtime-plan-20261013/`.

| Job | Evidence | Integrated result |
|---|---|---|
| Skill, scientific rigor and workload | Eight bounded storage/recovery probes passed; source-manifest, prerequisite, stale-return, optional-field and unresolved-result cases; independent workflow decisions | Replaced the foreground seed example with a canonical edit-batch example. Removed unconditional retrieval clauses. Added correctly attributed coordinator comparison of current affected input, preserving any requirement for independent review. Approved integrated S1/S2. [Report](../../tmp/graphify-runtime-plan-20261013/skill/report.md). |
| Comparison submission and recovery | Eight selected existing native/common regressions passed; two retained-database timing trials; partial-success, lost-receipt and commit-then-error probes | Approved existing receipt-led recovery. Deferred S3 because its small measured benefit adds an avoidable output/recovery contract. A failed command with no receipt remains uncertain rather than automatically rolled back. [Report](../../tmp/graphify-runtime-plan-20261013/batches/report.md). |
| Harness contract and process ownership | Final isolated fake-CLI matrix: 87/87 assertions; exact configured identities, fresh reviewers/resumed parent, streams, exit codes, run-local identity, unchanged legacy contracts; regular-file versus pipe probes | Required review includes saved-record review as well as source-only reconstruction; alternate routes retain configured provider/model/effort. Approved H1/H2. Host lifetime stays a separate diagnosis. [Report](../../tmp/graphify-runtime-plan-20261013/harness/review.md). |

The harness prototype initially passed 86/87 assertions: its fallback text covered required benchmarks but omitted required saved-record review. The wording was corrected and the affected fake-CLI matrix passed. This was a prototype contract defect, not a production edit. Test counts are separate evidence sets, not a claimed aggregate coverage percentage.

The final plan adds no required paper operation, recurring review, receipt artifact, or normal-write validation. It still requires meaningful source comparison and affected-context work when scientific content changes. The validators approved that distinction, not a guarantee of future agent adherence. No paid model paper run or measured end-to-end runtime reduction was performed.

Evidence: [completed-run investigation](../../tmp/graphify-325-completed-runtime-20261012/report.md), [initial plan](../../tmp/graphify-runtime-plan-20261013/draft-1.md), [baseline file hashes](../../tmp/graphify-runtime-plan-20261013/baseline-files.json) and [source protection check](../../tmp/graphify-runtime-plan-20261013/scope-check.json). The eight sampled owning/protected files remained byte-identical; the retained Claude database also remained unchanged. Only this plan and scratch validation artifacts were created. Development probes validate contracts and feasibility, not whole-paper scientific quality or measured end-to-end speedup.
