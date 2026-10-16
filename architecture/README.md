# Shared paper-core and proof-check architecture

This folder describes the common backend and current `stat-proof-check` architecture, and retains labeled change records and proposals. `proof-graphify` is version `3.2.9`; `stat-proof-check` and `paper_core` are version `3.2.8`. Their versions can advance independently in this repository. The audit skill's [entry point](../stat-proof-check/SKILL.md) and references define its agent workflow; the [Graphify architecture](proof-graphify/README.md) describes the selective overview. This folder explains code ownership and package boundaries.

| Source | Responsibility |
|---|---|
| [V3 implementation](../stat-proof-check/IMPLEMENTATION.md) | Current ownership, workflow contract and revision history |
| [V3 validation](../stat-proof-check/VALIDATION.md) | Tested behavior and release limitations |
| [`shared/paper_core`](../shared/paper_core) | Maintained common database, audit controller, math and scientific reader |
| [`stat-proof-check/scripts/paper_core`](../stat-proof-check/scripts/paper_core), [`proof-graphify/scripts/paper_core`](../proof-graphify/scripts/paper_core) | Generated identical cores in two independently installable skills |
| [`stat-proof-check/tests`](../stat-proof-check/tests) | V3 behavior and package checks |
| [V2 architecture](architecture.md), [`tests/new_format`](../tests/new_format) | Historical design and retained storage/overview compatibility tests |
| [`tools`](../tools) | Canonical builder for both core bundles and the Proof Check installer |
| [Shared core and reader handoff](shared-core-reader-handoff-20261009.md) | Common implementation with bounded overview and coherent audit workflows |
| [Shared core and reader validation](shared-core-reader-implementation-20261009.md) | Implemented 3.1.0 common core, tests, independent reviews and browser limitation |
| [3.2.0 repository consolidation](repository-consolidation-3.2.0.md) | Both skill packages and their shared source moved into this repository; versions and validation aligned |

The [Proof Graphify repository](https://github.com/rqzhu-aide/proof-graphify) now owns both skill packages, the shared core, builder, installer, and compatibility tests. The [stat-paper-skills repository](https://github.com/rqzhu-aide/stat-paper-skills) retains manuscript writing, paper review, and proof writing. Each installed mathematical-paper skill uses only its own bundled runtime. Dated records below preserve the original release versions and repository paths; those historical paths do not define current ownership.

## Proof-check change records and proposals

These notes preserve decisions and evidence. Current workflow instructions remain in the skill and its references.

| Note | Status |
|---|---|
| [V3 baseline rebuild](proofcheck-baseline-rebuild-handoff.md) | Implemented baseline rebuild, now promoted into the formal package |
| [3.0.11 reviewer and recovery handoff](proofcheck-v310-reviewer-recovery-handoff.md) | Implemented same-model commissioning and saved-return recovery |
| [2.3.8 workflow defect tracker](proofcheck-v238-defect-tracker.md) | Historical v2 defects, implementation status, contributing mistakes and closure evidence |
| [Workflow reliability revision handoff](proofcheck-v238-reliability-handoff.md) | Implemented agent/model-neutral corrections within the existing three stages |
| [2.3.9 reliability validation](proofcheck-v239-reliability-validation.md) | Integration corrections, preserved cases, behavioral evidence and release validation |
| [Three stage revision handoff](proofcheck-three-stage-handoff.md) | Implemented October 2 revision: stage-specific preparation, fixed audit snapshots, and separate Archify HTML delivery |
| [Three stage implementation validation](proofcheck-three-stage-validation.md) | Integration tests, preserved-case comparisons, continuation evidence and release status |
| [Three stage plan validation](proofcheck-three-stage-plan-audit.md) | Historical pre-implementation review and disposable probes that informed the final design |
| [Local recovery audit](proofcheck-local-recovery-audit.md) | October 2 focused recheck, fresh reproductions, and remaining context/navigation findings |
| [Targeted local recovery handoff](proofcheck-local-recovery-handoff.md) | Six targeted repairs implemented in the working tree; release remains separate |
| [Targeted local recovery validation](proofcheck-local-recovery-validation.md) | October 2 regression evidence, preserved-case preparation replay and bounded continuation exercise |
| [Agent-independent workflow revision handoff](proofcheck-agent-workflow-revision-handoff.md) | Implemented in the working tree: portable ownership, ordered examination and specific recovery |
| [Agent-independent workflow validation](proofcheck-agent-workflow-revision-validation.md) | October 2 implementation evidence, behavioral checks and remaining full-run validation limit |
| [Proof audit workflow design](proofcheck-proof-workflow-design.md) | Design rationale for the implemented workflow revision |
| [Workflow revision handoff](proofcheck-workflow-revision-handoff.md) | Implemented scope for preserving examinations, coherent independent reviews, and precise PDF coverage |
| [Workflow revision validation](proofcheck-workflow-revision-validation.md) | October 1 implementation, compatibility, installation, and live-test limitation |
| [Targeted reliability fixes](proofcheck-targeted-fixes-handoff.md) | Implemented; retained scope of the September 27 fixes |
| [Targeted fixes validation](proofcheck-targeted-fixes-validation.md) | Implementation, verification, and subsequent installation record |
| [Reader and output fixes](proofcheck-reader-output-fixes.md) | Implemented in maintained sources; records validation and remaining live-browser/test-run limitations |
| [Automatic-workflow handoff](proofcheck-automatic-workflow-handoff.md) | Unimplemented proposal for a new wrapper and managed-run design; not current workflow instructions |

Additional completed plans, audits, and old architecture versions are retained in the local `archived/` folder, outside skill discovery and Git. They are historical evidence, not current implementation instructions.
