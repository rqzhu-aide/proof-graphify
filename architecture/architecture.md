# Historical v2 proof-check architecture

This document retains the shared-backend design before the v3 rebuild. The ownership section reflects the common core restored in 3.1.0 and its 3.2.0 relocation into the Proof Graphify repository. Current scientific workflow is defined in the formal package's [implementation boundary](../stat-proof-check/IMPLEMENTATION.md) and [skill instructions](../stat-proof-check/SKILL.md); historical v2 review requirements below do not override them.

## Purpose and scope

`stat-proof-check` audits a paper's written mathematical argument. It records exact claims, source passages, dependencies, substantive proof steps, independent review, and unresolved limits. It is a non-formal audit: a valid database or rendered report does not certify a theorem.

The skill supports triage, focused audits, and full audits. A focused audit examines its declared targets and the internal prerequisites their arguments need. A full audit reconciles the proof-required inventory with the manuscript and supplements. The [skill instructions](../stat-proof-check/SKILL.md) and [database workflow](../stat-proof-check/references/database-audit.md) define these modes and their scientific standard.

## Repository and package boundary

The maintained backend is [`shared/paper_core`](../shared/paper_core). [`tools/build_paper_core_bundles.py`](../tools/build_paper_core_bundles.py) copies it into `stat-proof-check/scripts/paper_core/` and `proof-graphify/scripts/paper_core/` in this repository. These bundles must be byte-identical. Each installed skill runs its own bundle and does not import from a neighboring package or download runtime code.

The common core now reports version `3.2.8`, SQLite storage format `4`, and record contract `4`. [`schema.sql`](../shared/paper_core/schema.sql), [`contract.py`](../shared/paper_core/contract.py), and the acceptance and validation modules define the executable data contract. Overview writes have a bounded scope; ordinary audit writes require `coherent-proof-audit/1`. Historical audit records remain historical and are not automatically recertified.

## From manuscript to assessment

```text
Manuscript and supplements
  -> source capture and exact statement registration
  -> versioned SQLite records and dependency structure
  -> scoped mathematical checks and independent responses
  -> reconciliation and current assessment
  -> HTML reader and bounded report
```

The SQLite database is the authority. JSON batches are proposed edits or exports; HTML and Markdown are derived views. The source layer records file identity and passages. The acceptance layer validates records, references, permissions, and atomic changes. The controller prepares bounded work and saves progress, while the coordinator and checkers interpret the mathematics. Software checks record shape and provenance; mathematical validity requires an actual derivation and justified use of its premises.

The normal workflow has three stages: prepare evidence and primary examination; review, reconcile and finalize; then produce HTML. The current modules are [`stage1.py`](../shared/paper_core/stage1.py), [`stage2.py`](../shared/paper_core/stage2.py), and [`stage3.py`](../shared/paper_core/stage3.py). The earlier v2 scheduler is not included in the common runtime. [`finalization.py`](../shared/paper_core/finalization.py) freezes one consistent report snapshot. [`publish.py`](../shared/paper_core/publish.py) builds that snapshot without reopening scientific examination. See the [workflow instructions](../stat-proof-check/references/controller-workflow.md).

The initial independent reviewer receives source material without the coordinator's private assessment. Its original response is preserved before reconciliation. Local argument validity, availability of upstream support, statement status, and completion of the declared audit remain separate judgments. A proof gap does not establish that the theorem is false, and a proposed repair does not silently replace the manuscript's written proof.

The reader projects major results and their connections from a consistent database snapshot. It exposes exact statements, strategy, contextual premises, detailed checks, and unresolved issues through the graph and report. Rendering failure must preserve the previous published output. Browser interaction is a separate acceptance question from database, projection, and static renderer checks.

## Development and release

Proof Graphify, Stat Proof Check, and their maintained backend belong to this repository. The other three `stat-` skills remain in the separate stat-paper-skills repository. To change shared behavior, edit `shared/paper_core`, rebuild both bundles with the builder, and validate the packages before publishing. Do not edit a generated bundle by hand.

The relevant checks are the skill structure tests, `tests/new_format`, the proof-check installer tests, and the Proof Graphify suite. A passing mechanical suite supports software behavior within its tested cases; it does not substitute for mathematical evaluation of an audit or a live browser review. Dated release receipts and earlier plans are local historical records under `archived/`.

`tests/fixtures/reference-audit/` is a repository-only historical v1.5 regression fixture, excluded from skill delivery. Its recorded validator hash is stale, so current delivery checks correctly reject it as a finalized audit. Its original evidence remains intact; renewal would require an actual review under the current protocol.
