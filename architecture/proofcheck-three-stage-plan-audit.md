# Three stage plan validation

October 2, 2026. The [revision handoff](proofcheck-three-stage-handoff.md) has been rechecked against the current code and revised. The three-stage design remains appropriate, but its original specification had concrete gaps in readiness, task selection, and delivery recovery. Those gaps are now addressed in the plan. The stage implementation does not exist yet.

This was a code and design audit with disposable fixture probes. Three separate review passes examined readiness, selection, and frozen publication, followed by a narrower consistency check of the amendments. Runtime source, existing skill instructions, tests and generated bundles were preserved.

## Main corrections

### Recorded source comparison is not necessarily settled representation

The most consequential finding was a misleading readiness shortcut. In the current assessment engine, a source comparison with result `needs_attention` can be complete/current and satisfy its examination obligation. It does not necessarily appear in the existing blocker list.

In two completed fixtures, one with an item comparison and one with an exact-target comparison, recording a known transcription mismatch left all 9 required local primary tasks satisfied. Both still reported `process_complete: true`, with no assessment problems or source limits. That is sufficient evidence that the original plan's generic task-completion condition did not enforce its intended representation boundary.

The revised plan explicitly requires current required source comparisons to be `matched` for normal independent dispatch and completed release. It preserves canonical counts and uses one shared representation-readiness decision. A working report can retain the unresolved comparison, but must prominently explain that delivery has not been finalized. Recovery identifies the affected comparison rather than repeatedly asking the scheduler for a task it already counts satisfied.

This distinction does not require favorable mathematics. A completed gap still counts as examined. See [readiness results](../../audit-reports/three-stage-plan-audit-2026-10-02/readiness/results.json) and the [public-interface probe](../../audit-reports/three-stage-plan-audit-2026-10-02/readiness/probe.py).

### Task requests cannot serve as a stage filter

The plan originally proposed passing eligible task identities into the current controller. However, its `task_ids` parameter identifies requested starting tasks, and an empty list requests ordinary automatic selection.

A real fixture with all local primary work completed and global consistency still pending prepared that global task when given the empty list of eligible Stage 1 work. A second probe confirmed that an explicit composition request correctly selects its needed source-fidelity prerequisite outside the requested IDs.

The revised plan uses a distinct internal stage filter over complete units, preserves requested-task semantics, and handles an empty stage selection explicitly. It also reuses one assessed revision for the boundary and packet selection, retaining the existing revision conflict checks. Complete readiness facts must come from the derivation, not already-truncated diagnostic lists.

The current preparation helper also generates retry advice using `work prepare`. Reusing it unchanged could bypass the new boundary or emit invalid `--mode global`. The plan now requires retries to preserve the stage command and its relevant options. See [selection results](../../audit-reports/three-stage-plan-audit-2026-10-02/selection/results.json) and [code findings](../../audit-reports/three-stage-plan-audit-2026-10-02/selection/selection-audit.md).

### Finalization and presentation need precise recovery contracts

The separation remains small: one frozen report snapshot, one finalization receipt, and the existing renderer. The recheck clarified four details:

- Partial delivery uses the existing `working` kind, not a new `partial` enum that the renderer rejects.
- Publication changes projection metadata without changing the scientific revision. Repeated finalization should reuse the existing valid bundle rather than regenerate it and mistake this change for a conflict.
- A failed compatibility release retains its private frozen preparation and export until delivery succeeds, with an explicit resume operation. It must not reconstruct a newer audit while claiming to retry the old one.
- Missing math conversion retains the existing labeled literal-TeX fallback. Missing Node remains a rendering failure. Neither condition requires scientific reexamination.

Three executable checks passed: a completed fixture rendered and passed mechanical acceptance; the renderer accepted `working` and rejected `partial`; simulated converter absence retained the formula with a nonblocking diagnostic. Publication left revision 16 unchanged while changing only `summary.published_revision` in the projection. See [snapshot results](../../audit-reports/three-stage-plan-audit-2026-10-02/snapshot/results.json) and [publication findings](../../audit-reports/three-stage-plan-audit-2026-10-02/snapshot/findings.md).

## Behaviors that were confirmed

No independence cycle was found in the examined primary workflow. Removing qualification from a completed primary fixture left 9 of 9 local primary obligations satisfied; independent review correctly remained unfinished. A completed primary gap also retained 9 of 9 satisfied local obligations while mathematical support became unavailable. Readiness can therefore distinguish examined work from established results without introducing a new dependency system.

Existing primary prerequisite traversal, coherent work units, packet revision checks, and the bundled Archify renderer provide the needed building blocks. The revised plan adds stage selection and a delivery boundary rather than duplicating those mechanisms. The six previously reproduced runtime defects remain separate required fixes; writing this plan has not repaired them.

## Validation limits and preservation

The new stage commands, candidate filter, finalization fields, failure-resume option, and HTML disclosure are specifications, not tested implementations. The probes establish existing behavior and expose integration hazards. They do not prove full-paper completion, mathematical reliability, or reduced runtime on RF-HTE. No fresh full-paper run or broad suite was presented as validation of unimplemented commands.

Hash comparison confirmed that 346 watched source, script, reference, test and tool files were unchanged, with no added runtime files. See [preservation evidence](../../audit-reports/three-stage-plan-audit-2026-10-02/preservation.json). The pre-audit plan is retained as [plan-before.md](../../audit-reports/three-stage-plan-audit-2026-10-02/plan-before.md).

The plan is ready to implement with its listed regression cases. The next validation should exercise the implemented transitions and a bounded realistic continuation, rather than repeat this design audit without new evidence.
