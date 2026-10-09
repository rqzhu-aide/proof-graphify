> Historical v2 reference retained from the baseline. Its workflow and completion requirements do not govern v3. Use [the v3 workflow](controller-workflow.md) and [graph authoring](graph-records.md).

# Legacy v1.5: Workspace and Resume

Canonical rules for portable setup, source state, checkpoints, resumption, and blocked work. See [issues-and-repairs.md](issues-and-repairs.md) for repair and [reporting-and-release.md](reporting-and-release.md) for release.

## Audit workspace

Use `proofcheck.py scaffold` to create a project outside the skill directory:

```text
proofcheck-audit/
  AUDIT_MANIFEST.json
  proofcheck-report.html        default reader-facing report
  CHECK_PLAN.md                 generated projection
  EXECUTION_ORDER.md            generated projection
  PROGRESS.json
  audit/
    01_index/
      theorem_inventory.json
      cross_reference_audit.json
    02_ledgers/
    03_dependencies/
      DEPENDENCY_REGISTRY.json
      METHOD_INTERFACE_REGISTRY.json
    04_local_checks/
    05_adversarial/
    06_reports/
      ISSUE_LOG.json
      ISSUE_SUMMARY.md
      FINALIZATION.json
    07_runtime/
      CALIBRATION.json          canonical checker-calibration evidence
      calibration-history/     byte-exact hash-addressed superseded records
```

The report belongs beside the audit manifest, not beside the manuscript.
Existing audits retain their declared report path until explicit
`migrate-report --top-level`; see [reporting-and-release.md](reporting-and-release.md).
Do not store paper-specific work inside the installed skill.

`AUDIT_MANIFEST.json`, `PROGRESS.json`, ledgers, registries, `ISSUE_LOG.json`, and
`CALIBRATION.json` are canonical; superseded calibration records are immutable
history. Regenerate the deterministic views `CHECK_PLAN.md`, `EXECUTION_ORDER.md`,
and `audit/03_dependencies/dependency_graph.md` rather than editing them:

```bash
python "<skill-root>/scripts/proofcheck.py" sync-views --root "<audit-root>"
```

`finalize` refreshes and seals the required current views; use `sync-views`
earlier as needed. Views cannot supply missing scope, dependencies, statuses,
or judgments. Keep packets and compact annotations outside the audit root as
context, not final deliverables. Submission requires the exact primary packet;
skeletons and ledgers belong in `audit/04_local_checks`. Author through files
and stop dependent commands on unexpected nonzero exits. The
[authoring example](../assets/templates/AUTHORING_AND_RENEWAL.md) covers
argument-array execution and supported renewal. After delivery-check returns
FINAL, keep the sealed audit immutable. External temporary files are ordinary
workspace material outside finalization. Never delete or move nearby directories
as a release step.

For a long audit, the existing usage helper can retain each command's full
output while returning a compact result:

```text
python "<skill-root>/scripts/proofcheck_usage.py" run --root "<audit-root>" --records "<workbench>/commands" --stage primary -- issues --root "<audit-root>" --before-challenge
```

Each invocation creates a new receipt folder containing start/end times, exit
status, arguments, and full stdout/stderr. Keep it outside the canonical audit.
The child exit status is preserved; inspect saved diagnostics and stop dependent
commands on failure. Both root arguments identify the same audit. Receipts measure
work; they supply neither a proof judgment nor a completion gate.
Token usage remains unknown unless supplied by actual model usage records;
cached input is part of input and reasoning output is part of output.

Keep complete packets and evidence on disk; return bounded diagnostics and read
implicated sources or records as needed. Do not repeatedly load the full
validator or unrelated ledgers for local authoring errors. Group routine
deterministic work without truncating units or relevant prerequisite evidence.

## Portable setup and environment boundary

Invoke `proofcheck.py` through the directory containing the loaded
`SKILL.md`, not through a path relative to the caller's current directory. Run
`doctor` before scaffold or resume when the source, output directory, working
directory, or platform has changed:

```bash
python "<skill-root>/scripts/proofcheck.py" doctor --mode new --paper "<source>" --output "<audit-root>" --input-kind latex --portable-sources
```

Use `--mode new` before scaffold and `--mode resume` for an existing audit.
Pass identical quoted `--project-root`, `--additional-source`, and `--fls`
values to doctor, the read-only `proofcheck_source_check.py`, and scaffold.
Check new or changed LaTeX source before calibration or mathematical checking;
resolve its `review_required` items through
[source-layout-diagnostics.md](source-layout-diagnostics.md).
New mode rejects any existing destination. Resume mode requires a readable
audit manifest and a supplied paper whose hash matches the recorded
authoritative paper. `doctor` leaves no probe residue. It checks that
Python 3.10 or later is running, the source is a supported regular file, its
required provenance is available, and the destination can be safely created
or written. A process-start failure
occurs before the skill can create a diagnostic record. Whether the failure is
reported by `doctor` or by the surrounding execution environment, stop and
label the requested audit output `NONFINAL` with reason
`environment_blocked`. Do not continue through an ad hoc review and present it
as a completed proofcheck run.

Use `--portable-sources` when the audit may move between folders or systems. It
copies the authoritative source closure into `audit/00_sources/`, locks the
copied bytes, and makes those bundled files authoritative. Original absolute
locations remain nonauthoritative provenance only. Portable LaTeX sources must
use relative local references, and `--project-root` must contain every file in
the authoritative source closure. If a relative include escapes that boundary,
scaffold fails without committing an audit; rerun with a broader common root.
Do not rewrite `\input`, `\include`, class, package, or bibliography paths to
make the bundle appear self-contained. Move the whole audit root,
not selected state files. After moving it, run `status` and `delivery-check`;
their hash and closure checks determine whether the bundle remains usable.

Canonical paths stored inside JSON use `/`, including on Windows, and relative
paths resolve from the audit root or the record-specific documented base.
Readers normalize legacy relative paths containing `\`. They reject a foreign
absolute path rather than interpreting it as a relative path or silently
rebinding it. Re-scaffold with `--portable-sources` when a legacy audit depends
on unavailable absolute locations.

State-changing replacements commit complete files atomically. No-overwrite
publication uses a hard link or an exclusive rename when supported, with a
hash-verified exclusive-copy fallback on other filesystems. It never replaces
an existing path. If interruption leaves an incomplete newly created fallback
file, later validation rejects it; keep the audit `NONFINAL` and report the
exact malformed artifact. Recovery and issue archives are byte copies with
hashes and never depend on shared inode identity.

`AUDIT_MANIFEST.json` is the machine-readable scope and completion contract. Before finalization, set its reviewed depth, overall assessment, targets, in-scope units, optional priority-only `critical_units`, in-scope method interfaces, explicit exclusions with reasons, source or parser limits, inventory overrides, and completion evidence. Every in-scope unit requires an independent check. The obsolete `verified_challenge_sample_rate` field is rejected. For Focused depth, `target_units` must be nonempty and `in_scope_units` must equal the targets plus their exact transitive internal dependency closure. An inventory override may add a parser-missed manual unit, correct or reject a proof location, confirm, replace, or reject a proof association, or designate an exact external restatement only when it records the required source-bound evidence. Follow the source-bound override contracts in [proof-system-audit.md](proof-system-audit.md#1-build-the-inventory). Source-lock and rescan every changed proof span or statement-only restatement, then reconcile its exact reference occurrences, dependencies, and citations. Do not edit the source snapshot to make drift disappear. Re-scaffold or deliberately update and recheck affected work after a source change.

Literal `\newtheorem` roles persist: Assumption, Definition, and Remark are
context; Theorem, Lemma, Proposition, and Corollary require proofs. For an
ambiguous role, an `environment_classification` override records `unit_id`,
exact `environment_declaration` and `statement_sha256`,
`parser_proof_required`, `parser_semantic_kind`, `reviewed_proof_required`,
`reviewed_semantic_kind`, and substantive `reason` and `evidence`. Update the
inventory role and dependency review. Explicit theorems cannot be demoted;
stale bindings fail.

Literal `\newenvironment` aliases of `\begin{proof}` / `\end{proof}` require
complete boundaries; optional titles work. Arbitrary wrappers are unsupported.
Literal `restatable` preserves the original kind, title, and command. Command
copies link to the original and its adjacent appendix proof, without duplicate
obligations. Generic `Proofs` headings are not targeted proofs. Review remaining
source-located parser limitations.

The manifest records the skill version, artifact schemas, closure contract
version, validator hash, and source snapshot identifier. When only the
release identity changes, meaning the validator implementation hash or the
skill version, and all schema and contract versions remain current, status
reports `validator_revalidation_required`. Run:

```text
python "<skill-root>/scripts/proofcheck.py" revalidate-protocol --root "<audit-root>"
```

The command checks source freshness and record readability, stamps the current
protocol, and invalidates prior finalization. It preserves the original manifest
bytes in history and retains that compatible `context_protocol` for input binding,
so code-only upgrades do not require rewriting unchanged reviews. Current validators
still reconstruct every source and semantic input and run all gates; changed
contracts, sources, or reviewed meaning require the normal migration or recheck.
Resolve current gate errors and finalize again. Sealed resolution archives retain
their historical identity bound to their original manifest and seal. Validator
hashing normalizes CRLF and CR to LF across equivalent checkouts. Keep proof,
dependency and method-interface contracts distinct.

For an audit predating calibration schema 2, first finish reported contract
migrations, or run `revalidate-protocol` when only the validator changed. Then
run balanced `canary-grade` with reviewed checker-profile, configuration, and
context IDs. It hash-archives prior bytes in
`audit/07_runtime/calibration-history/` and records existing ledger hashes.
Those hashes are historical provenance, not a requirement to change sound
ledger bytes. Recheck existing work only when its checker profile or
configuration differs from the calibrated binding, or when ordinary semantic
freshness checks require it. A changed qualification receipt still requires
fresh annotation scaffolds and full review through the
[supported renewal sequence](../assets/templates/AUTHORING_AND_RENEWAL.md#renew-an-existing-ledger).
Keep the old ledger until its replacement compiles;
rebind cannot cross a calibration receipt.

The current release finalizes `5/5/4`. Evidence contract 5 adds anchored step
evidence, failure computations, and severe-issue repair searches; contract-4
ledgers remain inspection-only. A reviewed closure-4 registry binds the exact
source snapshot, inventory hash, ordered scope, and substantive evidence;
rebind it after any source, inventory, or scope change.

Reusable unit work is bound to its locked statement and proof, normalized
obligation, actual prerequisite contracts and evidence, calibration receipt,
and protocol. Whole-file hashes and the full source snapshot remain provenance
and release checks. Shared prose outside freshly indexed statement/proof
regions, local configuration files, and TeX commands with uncertain effects
also enter a conservative shared-context identity. Only demonstrably plain
unrelated regions can be omitted; indirect and unknown macros retain their
whole region, including multi-line arguments. Thus changing an unrelated plain
proof can preserve an unaffected unit's complete or partial judgments after an
explicit source rescan and dependency-review reconciliation. Changing a shared
assumption, mathematical macro, required conclusion, or locked unit span
invalidates affected work. Unclassified context and moved source lines can
still require additional review; this is not a full TeX effect analysis.

Source drift always blocks packet generation until that reconciliation is
complete, and every source edit invalidates the old release. Never rewrite
snapshot hashes alone to claim currency. A still-equivalent primary packet
may compile with its original annotation binding while current operational
provenance is recorded. The preserved initial challenge can be reused when
its mathematical inputs are unchanged, but the final challenge still binds
the global snapshot and must be explicitly rebound before resealing. Reuse
does not by itself claim a current FINAL result.

For schema-5/evidence-4 state, run `migrate-evidence --root "<audit-root>"`.
It validates source, closure, versions, and only direct live ledgers and
skeletons in `audit/04_local_checks`; hash-named byte-exact backups go in its
`history/` directory. It then failure-atomically restamps live files and the
manifest and invalidates finalization. Add and recheck the new failure, repair,
and anchored-step evidence. At evidence 5, the same checks precede
`already_current`; a prior closure points to `migrate-closure`. Fatal ledger
errors remain `malformed_or_stale`.

For `5/5/3`, `migrate-closure` byte-backs up the registry and atomically updates
registry and manifest to closure 4, clears carried citation bindings, marks
review pending, and invalidates finalization. Complete and recheck the bindings.
It refuses evidence-contract-4 state and points to `migrate-evidence`.

Both commands hold `.proofcheck-migration.lock` through preflight, backup, and
commit. If failure leaves it, inspect the lock, audit state, and reported
recovery files; restore coherent state, remove the lock only when no migration
is running, then rerun.

Artifacts using schema `4`, evidence contract `3`, or closure contract `2`
are inspection-only. Their prior status is historical evidence under the older
contract, not a current finalization. Re-scaffold or explicitly migrate every
affected record, recheck its source, inference, dependency, issue, challenge,
and reporting evidence, and rerun the current gates before making a
current-protocol claim.

To create a schema-5 skeleton from one legacy schema-4 ledger, run:

```text
python "<skill-root>/scripts/proofcheck.py" migrate-ledger "<legacy.ledger.json>" --output "<schema5.ledger.json>"
```

The command never overwrites the legacy ledger. It creates a nonfinal
source-unit skeleton and resets the review verdicts, independent challenge, and
steps rather than transferring prior mathematical judgments. Final mode
remains blocked until a full manual atomic recheck reconstructs the ledger and
sets `migration.status` to `rechecked` with substantive
`migration.recheck_evidence` and a valid UTC `migration.rechecked_utc`.

Report-directory integrity, deliverable declarations, and the transition from
the nonfinal report scaffold are defined in
[reporting-and-release.md](reporting-and-release.md).

The `source_discovery` record distinguishes recursively discovered LaTeX inputs, local class and package files, explicitly declared sources, and supplemental project-local `.fls` inputs. An outside-project recorder input remains excluded until it is explicitly promoted as an additional source with a reason and evidence. Treat an `.fls` trace as evidence from one compilation path, not as a completeness certificate.

`parser_warning_reviews` must be a one-to-one review of the exact current warning set. Use `confirmed_non_load_bearing` only with concrete evidence, `scope_limitation` when the unresolved reach is bounded and declared, and `unresolved` otherwise. Use `external_restatement` only for the missing-associated-proof warning of the same explicitly overridden unit, with `affected_units` containing exactly that unit and substantive evidence. An unresolved warning, or a limitation that may affect in-scope units, cannot support `no_defect_found`.

Manifest `cross_reference_reviews` must be a one-to-one review of the exact
current broken-reference and duplicate-label records. Orphan labels do not
require rows. Each record contains `kind`, `key`, exact `locations`, `status`,
substantive `evidence`, `affected_units`, and `issue_ids`. Use only `passed`,
`defect`, or `inconclusive`. The affected units and issues must agree with the
scope, canonical issue log, global source-resolution row, and final report.

## Checkpoint contract

After validating every completed ledger, at the end of every session, and
before a handoff, write `PROGRESS.json` through the checkpoint command. Choose
exactly one active-unit option and supply a specific next action:

```bash
python "<skill-root>/scripts/proofcheck.py" checkpoint --root "<audit-root>" --active-unit <unit-id> --next-action "<specific action>"
python "<skill-root>/scripts/proofcheck.py" checkpoint --root "<audit-root>" --clear-active-unit --next-action "<specific action>"
```

The command derives `current_pass`, the completed, in-progress, and not-started
unit sets, and the conditional subset from canonical scope and ledger state. It
keeps the active unit and next action explicit and preserves only validated
blockers and source or parser limits. Do not hand-edit derived progress fields.

Use these exact `current_pass` milestones:

| Pass | Milestone |
|---|---|
| 0 | Reserved for pre-work or legacy bootstrap; a normal scaffold starts at pass 1. |
| 1 | Establishing scope and source is underway. |
| 2 | Scope and source are reviewed; proof-system mapping is incomplete. |
| 3 | Proof-system mapping is reviewed, but at least one scoped obligation is not fully source-locked and normalized. |
| 4 | All scoped obligations are normalized; local atomic checking is incomplete. |
| 5 | All local ledgers are complete; dependency, method-interface, global, or adversarial checks are incomplete. |
| 6 | Dependency, method-interface, global, and adversarial checks are complete; at least one in-scope independent check is incomplete. |
| 7 | Every in-scope independent check is reconciled; the final report is not declared ready. |
| 8 | The final report is declared ready; the strict candidate finalization gate alone controls `complete` versus `in_progress`. |

On a current finalized audit, `report`, `checkpoint`, and repeated `finalize`
return the current deliverable or state without rewriting durable files.
Checkpoint arguments do not reopen that delivered snapshot. Use a working copy
for deliberate repairs, including the portable source bundle or independent
copies of every external source that will be edited. Verify the copy with
`delivery-check` before changing it; retain the original delivered audit.

For ongoing work, checkpoint refuses source-snapshot or include-closure drift rather than
rewriting progress against stale source. On a successful checkpoint, it
migrates a legacy progress record that lacks `in_progress_units` by writing the
derived field. It rejects an active unit already present in the derived
`completed_units` set. At pass 8, it places the newly supplied `next_action`
into the candidate progress record
before running the strict gate, so that gate validates the new value. If the
gate fails, checkpoint records `status: in_progress`, never `complete`.

Keep the explicit state factual. Do not mark a unit complete merely because a
draft ledger exists. At finalization, require `completed_units` to equal the
in-scope set exactly, `conditional_units` to equal the exact set of ledgers
with `unit_status: conditionally_verified`, `blocked_units` to be an empty
object, `in_progress_units` and `not_started_units` to be empty, and
`open_high_priority_issues` to equal the sorted set of open or deferred S0 and
S1 issue IDs. Reject duplicates, unknown IDs, missing IDs, and stale snapshot
bindings.

Pass-7 readiness requires a current reconciled independent check for every ID
in `audit_scope.in_scope_units`, as defined in
[challenge-protocol.md](challenge-protocol.md).

## Resume contract

On resumption:

1. Run `proofcheck.py status --root "<audit-root>"` before loading substantive
   audit content.
2. Inspect the reported source and protocol freshness, active unit, bounded
   gate errors, and exact next action.
3. For an active or next unit, generate a current primary packet with
   `packet --root "<audit-root>" --unit-id <unit-id> --mode primary --output
   "<packet.json>"` outside the audit root and load that packet rather than the
   whole workspace. If its obligation is absent, normalize the fresh extracted
   skeleton or ledger before semantic checking and regenerate the packet.
4. Inspect `resume.wip.included`. Reuse partial semantic work only when it is
   true; otherwise recheck the affected work rather than reconstructing it
   from conversation or prose notes.
5. Load separately only external evidence or canonical issue records named by
   that packet and needed for the next action.
6. Continue from the recorded next action without rereading completed ledgers,
   report artifacts, or unrelated source.
7. If status reports source, obligation, dependency, external-evidence, or
   protocol drift, identify and recheck the bounded affected set before
   trusting its prior semantic judgments. Do not reuse a verdict across a
   changed binding merely because the unit ID or prose appears unchanged.

`status` distinguishes incomplete, stale, malformed, and finalizable work. Use
`status --verbose` for all errors; both modes apply the same gates.

If only the cross-reference records are stale, regenerate their canonical JSON
and Markdown view together from the unchanged locked source closure:

```bash
python "<skill-root>/scripts/proofcheck.py" crossref --root "<audit-root>"
```

This supports portable audits and supplemental sources. It preserves source
locks and reviewed inventory/dependency decisions. Source drift requires the
normal source repair below; regeneration cannot approve changed manuscripts.
Recheck final delivery after changing a finalized audit.

Packets are optional for manual ledgers and mandatory for compile-annotations;
they do not replace status. The compiler rebuilds canonical state, verifies both
bindings, and requires an identical dependency-closed semantic projection.
Use a fresh .skeleton.json with the intended obligation; keep packet and
annotations outside the audit root, bound by context_binding_sha256.

The semantic binding covers protocol, source snapshot, exact unit source,
normalized obligation, unit inventory and candidate paths, direct dependency
contracts and external evidence, relevant issue triggers, dependency alignment,
and all risk aspects. A separate operational_binding records raw manifest,
inventory, registry, issue-log, progress, and semantic-artifact file hashes plus
readiness and resume state. Operational drift remains traceable but does not
by itself invalidate a mathematical judgment.

For resumable partial ledgers, copy work_context_sha256 from the primary packet.
A new packet includes WIP only if nonfinal local validation passes and its
dependency-closed context matches. resume.wip carries the ledger hash and full
reusable source_units, steps, and review. Relevant semantic drift requires
rechecking; progress, next action, or unrelated metadata changes do not.

A zero exit from bare `status` means coherent resumable state, not completion.
Read `audit_complete`, `delivery_status`, and `finalization_gate_error_count`.
The nested progress gate count covers only a pass-8 completion candidate.
`status --require-finalized` requires current usable finalization;
use `delivery-check` for release.

If source drift affects a checked unit, mark that unit stale and re-extract it. Preserve unaffected audit records. If the paper's theorem statement changes, re-evaluate downstream dependencies even when proof text is unchanged.

Because finalization locks the full include closure, any included-file change
invalidates the audit-wide source snapshot. Determine the affected units,
refresh the snapshot transparently, recheck all context and dependencies whose
meaning could have changed, and then renew the registry review binding.

External `source_evidence` files are locked independently by file hash. A
changed or missing evidence file makes its external record and every associated
use stale even when the manuscript snapshot is unchanged.

Method-interface records independently lock manuscript, pseudocode, code, and configuration spans. A code snapshot can support a code-to-target or code-to-documentation judgment without being part of the LaTeX include closure. If the inspected revision, configuration, preprocessing, or caller inputs are not tied to reported experiments, execution provenance remains not checked.

## Optional usage telemetry

Usage telemetry is observational only. It is not proof evidence and does not
affect any mathematical or completion judgment. When the user requests it,
record exactly one event for each actual model call. Set `work_packets` to the
number of complete unit or external-result packet contexts processed in that
call. Record a retry, correction call, or challenger call as a separate event;
do not record deterministic `proofcheck.py` commands as model calls.

For example:

```bash
python "<skill-root>/scripts/proofcheck_usage.py" record --root "<audit-root>" --event-id call-001 --stage primary --work-packets 1 --unit-id <unit-id> --input-tokens 12000 --cached-input-tokens 8000 --output-tokens 3000 --reasoning-tokens 1500 --token-source measured --cache-outcome hit
python "<skill-root>/scripts/proofcheck_usage.py" summary --root "<audit-root>" --format markdown
```

Event IDs must be unique. Use `--token-source measured` for tool-reported
counts, `reported` for another stated count, and `unavailable` when no token
count exists. A measured or reported event needs at least one numeric token
field; an unavailable event must omit all token counts. Record
`--cache-outcome` as `hit`, `miss`, or `not_used` without inferring a hit from
a lower token count.

The helper writes `audit/07_runtime/RUN_USAGE.json`. Record events only before
a current usable finalization. When present, the file is sealed in the audit
artifact manifest. After usable finalization, run only the read-only `summary`
command. Absence of telemetry neither weakens nor strengthens the audit.


## Blocked and conditional work

When a dependency or source is missing, record what is needed and propagate the
missing input into every affected verdict. Still inspect every in-scope
dependent line by line, but do not mark it verified or fill missing material
from memory.

When user judgment is needed, isolate the smallest concrete choice and explain how each option changes the audit. Keep already established facts stable.
