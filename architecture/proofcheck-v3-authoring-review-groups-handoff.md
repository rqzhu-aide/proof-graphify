# Proof check handoff for simpler authoring and grouped review

Status: implemented and mechanically validated in `stat-proof-check-v3` version 3.0.3. Ready for a later paper test.

Date: 2026-10-05. Baseline: `stat-proof-check` 3.0.2, protocol `coherent-proof-audit/1`. The canonical skill name remains `stat-proof-check`.

Plan review: checked against the current authoring and assignment code, with separate reviews of both workstreams and an independent final review for workflow burden. The accepted October 5 procedure lets Phase 1 workers independently draft items, connections and examinations, followed by coordinator consolidation into shared graph records. The implementation retains named-assumption reuse and bounded local continuation.

## Purpose and scope

Make the ordinary proof-audit workflow easier to finish: register claims without accidental private conditions, correct existing records without rebuilding the graph, and give a few independent reviewers distinct groups of ready proofs. The coordinator owns database writes, receives the reviews, integrates their saved judgments, and delivers the existing frozen summary and HTML.

This revision implements only priorities **1, simple authoring and correction**, and **2, clear grouped reviewer assignments**, including the Phase 1 ownership needed to prepare that work. It improves execution mechanics without adding mathematical duties. A manuscript gap, uncertainty, or disagreement remains a reportable result. The examiner need not construct a proof, repair the mathematics, or obtain agreement.

Implementation target: `stat-proof-check-v3/` in this repository. Its canonical skill name remains `stat-proof-check`. Modify this package's own `scripts/paper_core`, references, and v3 tests. The older `stat-proof-check/`, shared core, and Proof Graphify are outside scope. This document is an engineering handoff, not another reference that agents must read when auditing a paper.

Keep the three stages and current storage/protocol format. Use existing records, packets, submissions, and completion rules. No scheduler, worker registry, leases, new database collections, mandatory coverage ledger, or additional audit stage is needed. Provider choice, model names, subagent APIs, session commands, concurrency, and timeout settings remain outside the portable skill contract.

## Evidence and design decisions

The motivating run is `stat-proof-check@v3.0.2+kedrl-full__20261005-093136`, under `C:/Users/zrq/projects/skills/_testing-center/results/`.

| Observed friction | Decision for this revision |
| --- | --- |
| The same theorem hypotheses were stored in exact statements and private scopes. Correcting their representation led to 11 renewed independent reviews. | Make the ordinary statement representation clear before dispatch; keep private scope fields out of the ordinary example. |
| An agent tried `update`, received misleading create-oriented feedback, and rebuilt its database although `replace` already existed. | Generate replacement templates from existing records and name valid operations in errors. |
| Correcting a displayed claim can leave its exact specification pinned to the old version. | Provide a bounded claim-correction helper for the ordinary paired representation. Do not make the caller discover storage pins. |
| Repeated generic preparation returned the same pending assignment while the coordinator expected new work. | Select distinct assignments explicitly and provide a small group-preparation helper that handles exclusions. |
| Some runs launched a fresh reviewer session for each proof, usually serially. | Allow one independent reviewer to handle several existing packets in one source-only context. |

Three distinctions are essential:

1. **Preserve hypotheses explicitly or by clear reference to existing assumptions.** A private scope represents a genuinely local assumption or case, not another place to copy every hypothesis.
2. **A reviewer group is a delivery convenience.** It can contain several normal database packets. It is not a new mathematical unit, proof verdict, database task, or all-or-nothing submission.
3. **Workers author local drafts; the coordinator owns shared records.** Workers independently create proposed items, connections and examinations from sources. The coordinator consolidates their returns, merging shared identities while preserving distinct uses and opinions. Missing graph bookkeeping does not itself prevent source-based examination.

The current selector keeps a packet within a compatible argument/owner context. Increasing `--max-units` or listing several task IDs does not guarantee a multi-proof packet. Preserve this useful locality; group existing packets at the delivery level instead.

## 1. Simple authoring and direct correction

### Ordinary authoring

Keep `stage1 add-unit` as the normal entry point. Its ordinary example should contain the exact statement, source passages, proof boundary judgment, and meaningful suppliers. Preserve hypotheses and quantifiers either in the text or through the manuscript's clear references, such as "Under Assumption A1." Include the referenced assumption's source content in the examination context; an unexplained label alone is insufficient. Omit `conditions`, `assumptions`, and `binders` from the ordinary example; their empty defaults already serve this case.

Reuse an existing named-assumption record as source/setup context for the theorems that refer to it. Preserve the theorem's original wording and provide the assumption's captured passage rather than copying its text into every theorem or private scope. A clearly identical restatement may reuse the record with its source location retained. Material differences in domain, quantifiers, or conditions stay explicit. This does not require an equivalence proof, text-matching engine, or paper-wide deduplication pass. Keep assumption records as assumptions; do not turn them into proved lemmas. The theorem examination assesses its reasoning under the assumption, and a consuming argument checks that the assumption applies at its use.

Preserve meaningful existing connections, but do not require a formal proof-supplier edge merely to display a named-assumption reference. In the current support reducer, an assumption used as an ordinary supplier can remain conditional; that is not an instruction to prove it or copy it into a private scope to obtain a favorable status. Existing source passages and the explicit theorem reference are sufficient for the ordinary examination context. This revision adds no edge kind or assumption-support inference rule. A general change to graph treatment of conditional theorems needs its own later design.

Explain private scopes briefly in the advanced subsection of `references/graph-records.md`: use them when a claim is available only inside a genuine temporary assumption or case. Preserve existing support for those situations. Do not reject existing definitions merely because they contain these fields, automatically erase scopes, parse hypothesis prose into new nodes, or require a separate assumption-classification exercise. Keep meaningful existing prerequisite connections; do not require a node for each clause.

This is chiefly a guidance correction. Retain the existing per-unit empty default scopes; `arguments.scope_id` is required by the current schema. There is no need to introduce shared scope identities, change that schema, or migrate previously saved audits. Do not turn this into a scope inference engine.

### Phase 1 dependency discovery and shared-node ownership

Phase 1 includes source preparation, graph construction, and primary examination. Start with the existing paper/supplement result inventory, then let examiners trace the important dependencies of their assigned proofs. This can discover prerequisites backward from a theorem, while registration creates referenced suppliers before their consuming links. There is no compulsory top-down traversal, bottom-up examination sequence, or requirement to finish the entire dependency graph before useful examination begins.

Use this responsibility split:

| Work | Owner |
| --- | --- |
| Draft needed results, equations, assumptions, connections and primary examinations from supplied sources | Examiner of the assigned proof group |
| Decide whether an existing shared record represents it, and create or correct the canonical record and links | Coordinator, as sole database writer |
| Examine a shared result's own supplied derivation | The primary owner of the proof unit containing that derivation, with ordinary independent review later |
| Check each application of the shared result | Examiner of that consuming proof, within its existing assignment |

Workers create local draft items and connections as needed to finish their examinations. Each proposal identifies its source claim, context, document and locator; each consuming connection describes the consequence used. Use local names and supplied anchor IDs where available. The workers need no canonical database IDs, ownership negotiation or coordinator acknowledgement per equation. Readable local drafts are sufficient; an optional structured format supports mechanical consolidation. Do not put invented database IDs into strict packet response fields. A missing node alone is not a mathematical finding.

Coverage and outcome describe the examination actually performed. An otherwise complete source-based examination does not become partial or inconclusive solely because its dependency still needs a database identity.

After the group's returns arrive, the coordinator consolidates them during normal Phase 1 intake, using source identity, claim and context to reuse or create one shared record. Two drafts of the same Equation (12) should lead to one shared node when warranted, with separate consuming connections. Equal equation numbers, a shared paper or a shared page are insufficient. Preserve every returned examination and disagreement; merging a node never adopts a scientific judgment. A delayed worker return remains a local limitation and does not hold up unrelated groups.

The optional `stage1 consolidate-drafts --input worker-a.json --input worker-b.json --out consolidated.json` helper supplies local-to-proposed mappings, exact duplicate consolidation, original examinations, authoring options and a supplier-first authoring order. It does not write the database, prove equivalence, adopt verdicts or grant independent-review credit. The coordinator confirms identities against existing graph records and uses ordinary `add-unit` or template/apply authoring. Locally missing references and source anchors remain explicit alongside usable proposals. No universal graph importer or mandatory draft ledger is introduced.

For initial source-based drafts, the coordinator maps the saved primary reasoning into the consolidated graph's current response scaffold, retaining actual authorship, question, evidence, scope and limitations. Mechanical mapping is coordinator intake, not another examination. Seek only affected continuation when the question or evidence materially differs, or retain the limitation. An initial unbound draft must not be confused with a response to an already issued database packet; the latter retains its existing freshness requirements.

A meaningful shared prerequisite may warrant a node. Routine algebra can remain in source anchors and the containing examination. The shared equation's derivation is examined within its owning proof unit; each consumer need not re-derive it. A genuinely additional in-scope result may need its own existing kind of examination, but a bookkeeping request must not automatically create a new scientific assignment. Preserve unresolved supplier support as a limitation rather than sending every consumer to prove it independently.

| What is missing? | What happens next? |
| --- | --- |
| Only a graph node or connection, with the needed source available | Examiner continues and reports the dependency. Coordinator reconciles the representation during ordinary intake. |
| The relevant source passage or necessary setup | Seek that specific source context or retain a local coverage limitation; other useful work continues. |
| A supplied justification or a convincing inference | Judge the gap or uncertainty in the assigned examination. A new proof or counterexample is not required. |

Handle discoveries at normal return points or when they genuinely block a worker. Do not add a separate discovery-only sweep, require synchronous approval per equation, or enforce a complete-node inventory before dispatch. Organize the group's returned drafts before finalizing its primary records and handing it to independent review; do not repeatedly polish equivalent graph structure during active review.

Missing bookkeeping and durable acceptance are different. Existing intake checks may reject a response after a new connection changes its consumed inputs. Preserve the original reasoning and response. Prepare only the affected current packet and let the same examiner continue from its saved work, confirming the affected use or remaining question. Primary continuation uses `stage1 prepare --focus ...` or `--task ...`; the independent-only `work extend` operation is not a primary extension command. Do not relabel old bytes as an examination of new evidence, bypass freshness checks, or imply that changing a packet ID is enough. If current support cannot be established, retain the specific limitation and continue unrelated work. This is bounded continuation through existing commands, not a new automatic semantic-reuse mechanism.

### Late dependencies in Phase 2

Independent review normally receives the graph and evidence established during Phase 1. A reviewer who discovers a missing dependency reports the source and its consequence using the same ownership rule. The coordinator makes a local addition or correction and provides neutral source context if needed; it does not restart Phase 1 for the whole paper or send the reviewer another examiner's reasoning.

Adding readable evidence to an unchanged independent question can use the existing source-context extension path. That path creates a new packet for the same obligation and a continued response; it does not certify that an earlier response examined the added material. Changed claims, assumptions, or connections require the affected current assignment instead. Use the same independent reviewer for its own continuation when available, preserving its actual exposure. Unaffected packets and completed work remain useful. Detailed integration changes and a general examination-reuse redesign remain outside this revision.

### Existing-record replacement

Extend the existing `template` path rather than introducing a second low-level edit format:

- Without an ID, retain the existing create template.
- With an ID that names a live record in the selected collection, return an uncommitted `replace` entry containing its actual body and current `expected_version`.
- With an ID absent from that collection, retain the named-create behavior needed by same-ID extensions such as `application_details`. Clearly identify the generated operation. A retired record is not a new record to recreate silently.
- Respect the supplied author packet's permissions and versions. If it cannot authorize the current replacement, give the specific author-packet refresh command; do not silently bypass freshness or copy historical contents as current.
- Preserve unknown-to-the-caller optional fields by copying the saved body. The coordinator edits only the intended values and submits the existing batch format.

An invalid edit operation should identify the field and the allowed operations, including `replace`. It must not misleadingly report that every edit must be `create`. Keep validation strict; do not silently translate arbitrary operations or drop fields.

The default correction instructions should lead to this path. They should not tell agents to read runtime source, mint replacement IDs, rebuild the database, or repeatedly try guessed fields.

### Correcting an ordinary exact claim

Generic record replacement is insufficient for an exact-claim correction: a `target_specs.statement_ref` can still select the previous item version. Add one small helper for that paired case.

**Public command:**

```text
AUDIT stage1 correct-claim audit.db --item ITEM_ID --expected-version N --correction correction.json
```

The correction object contains an optional replacement exact `statement` string and optional nonempty `statement_anchors` list of existing captured anchors. At least one is supplied. Omitted fields and the existing exact statement form are preserved. It contains no mathematical verdict, `source_matched`, or `proof_complete` flag. A synopsis requiring a distinct exact specification belongs to the advanced path below.

For an ordinary claim whose exact specification directly refers to that item, the helper:

1. Reads the current item and its direct exact specification, validating the supplied item version.
2. Replaces only the requested statement content or statement passages, preserving proof passages, identity, and other fields.
3. Updates the direct specification to reference the resulting item version and, when requested, its revised statement evidence.
4. Applies these existing versioned edits atomically and returns the changed references through the normal receipt.

Use the existing validator and assessment machinery. Do not generate favorable source comparisons, proof checks, independent reviews, or integrations. Do not silently copy old verification credit onto changed material. A previously attached fidelity reference that no longer applies must not be carried forward as current evidence. Existing stage status exposes affected remaining work; no separate revalidation checklist is created.

Keep the helper bounded. Support the ordinary statement-only and written-proof cases produced by `add-unit`. A deliberately distinct exact specification, ambiguous pairing, or unsupported advanced graph shape receives a local explanation naming the records and the existing author/edit path. There are no partial writes and no recommendation to rebuild. Proof continuations, proof boundaries, supplier changes, and private-scope restructuring remain on the existing graph-edit path in this revision.

An unchanged replay returns the prior result without new edits. A genuine no-op does not create a version or examination. Check replay identity before rejecting the original expected version as stale after a successful first submission. A conflicting later edit produces a local conflict and preserves all accepted work.

This helper synchronizes explicitly requested storage changes. It does not decide mathematical equivalence, rewrite the paper, or force an additional review before allowing a limited delivery.

## 2. Distinct grouped reviewer assignments

### Roles and ordinary execution

One coordinator prepares assignments and writes the database. Primary examiners may be delegated. Independent reviewers receive their source delivery files and write response files; they do not edit the shared database or integrate other reviewers' opinions.

Prefer a few coherent reviewer groups when the material and available context permit. One group may cover related results, a connected argument, or a useful section. This is a coordinator choice, not a mandatory partitioning algorithm or fixed worker count. A single reviewer can process several packets successively; several separate reviewer contexts can run concurrently if available.

An independent reviewer may reuse its own source context across the packets assigned to it. Do not reuse a primary-examination context as independent review. During the initial independent pass, do not send integration decisions, primary opinions, or other reviewers' answers to that worker. Preserve the existing honest limitation path when genuine independent review is unavailable.

Prepare a group's ready units after their source questions and primary examinations are saved. A different group can remain unfinished or source-limited. There is no whole-paper readiness barrier, mandatory pre-dispatch audit, or need to perfect every graph detail first. Avoid discretionary representation cleanup while the affected packets are being reviewed. Correct material errors when found and handle only their affected work under the existing rules.

### Thin preparation helper

Add an optional `stage2 prepare-group` command for independent review. It wraps existing preparation and artifact export; it never launches a model, waits for workers, retries tool calls, submits reviews, or chooses scientific conclusions.

**Public usage:**

```text
AUDIT stage2 prepare-group audit.db --audit AUDIT_ID --max-packets 3 --out work/review-group-a
AUDIT stage2 prepare-group audit.db --audit AUDIT_ID --max-packets 3 --exclude-group work/review-group-a/group-index.json --out work/review-group-b
```

Three is an example capacity, not a required group size. A coordinator can instead repeat the existing `--task TASK_ID` option to select a known coherent set. Retain explicit task exclusions and the existing per-packet size limits. `--max-packets` limits this delivery group; `--max-units` continues to mean compatible units within each packet. Do not reinterpret either as the number of reviewers.

The helper repeatedly calls the normal stage preparation path, accumulating **the task IDs actually assigned** as local exclusions. Excluded group indices resolve their saved packet IDs against the same database and audit, then contribute those packets' assigned task IDs. Exclusion is local to this preparation call, not a reservation or a persistent block on the work.

Explicit task selection is limited to the requested proof units, with their normal within-unit context. It does not add unrelated filler. Report requested work that was satisfied, unavailable, deferred, or not included within the chosen capacity. An explicitly empty selection must never mean selecting the entire audit; omitted selection retains ordinary automatic choice. If a unit exceeds the existing packet limit, report it and skip that unit locally so other ready work can proceed. Do not split an indivisible proof or repeat the same failed selection. Stop when the capacity is reached or no useful unexcluded work remains; do not poll until blocked material becomes ready.

Keep each existing packet and its response scaffold intact. Export them in distinct packet directories. Produce a small coordinator `group-index.json` containing the audit identity, packet IDs, actual assigned task IDs, labels, and file paths, plus any unassigned selection reasons. Record saved packet IDs before exporting their child files, and return those IDs in error feedback if writing the index itself fails. Supply a reviewer delivery list containing only neutral labels, the worker-facing file paths, matching original evidence locations, and expected response paths. The coordinator manifest and guidance remain private.

The index is a generated convenience file, not authoritative task state. It adds no group ID to database records, completion obligation, response schema, or mandatory run artifact. Existing callers can continue using `stage2 prepare`, `--task`, `--exclude-task`, and normal review submission without groups.

### Submission and continuation

The reviewer writes one ordinary response per packet. The coordinator submits each with its actual packet ID, reviewer identity, and exposure through `stage2 review`, then integrates the saved responses using the existing workflow. One failed packet does not prevent accepting another completed response in the group. No combined group verdict or all-or-nothing group submission is added.

The group helper should make these situations straightforward:

| Situation | Expected behavior |
| --- | --- |
| Two groups are prepared before either returns | Their actual assigned task sets are disjoint when the earlier group is excluded. No database writes from workers are required. |
| Generic single preparation returns a reused packet | It remains the same pending assignment. Feedback must not imply that a new folder creates new work. |
| The coordinator is interrupted after preparing a group | Reopen its saved index and response files. Existing packet inspection/export recovers missing delivery files. Do not silently replace membership with today's next tasks. |
| Preparation or export fails partway through | Preserve and report the saved packet IDs and completed exports, with the existing recovery commands. Never infer success merely because an old file exists. |
| A group is too large for the reviewer context | Give smaller groups of existing packets to separate contexts, or process them successively. Do not split ordinary proofs into compulsory edge checks. |
| A reviewer finishes some packets and fails on another | Save the completed responses. Reassign or continue only the unfinished packet when useful, otherwise disclose its limitation. |
| A reviewer returns a usable response with a mechanical envelope problem | Retain the original response and use existing local intake repair. Do not commission another proof examination for formatting. |
| An unrelated unit changes while a group is running | Existing packet freshness rules govern the return. Do not reject a whole group solely because the database revision advanced. |

A saved group path is stable. Reusing it reopens that group or reports a local output conflict if the caller requests different membership; it must not silently append new tasks or overwrite returned responses. Provide explicit re-export through `stage2 prepare-group ... --resume-group SAVED_INDEX --out FRESH_DIRECTORY`. Resume does not accept new task-selection or exclusion options: it re-exports the saved packet IDs, including any saved but previously unexported packets, using existing inspection/export facilities. It does not silently renew stale scientific context. Fresh selection uses a fresh group. Recovery is based on existing packet identities, not a new dispatch-state ledger.

Re-export retains earlier response locations in coordinator-only metadata, including chained recovery. File presence is not acceptance. Inspect saved responses and current remaining tasks before dispatching continuation; re-export itself never requests another examination. Keep prior opinions out of the source-only delivery.

## Implementation map and ownership

| Workstream | Main locations | Boundary |
| --- | --- | --- |
| Authoring and correction | `scripts/paper_core/authoring.py`, `assistance.py`, relevant edit diagnostics in `contract.py`, CLI wiring | Empty ordinary scopes, existing-record templates, bounded paired claim correction. No general graph rewrite or semantic-equivalence engine. |
| Local draft consolidation | `scripts/paper_core/drafts.py`, focused draft tests and `references/phase1-drafts.md` | Optional nonmutating assistance; exact proposal matching and preserved source context, uses and opinions. Canonical intake stays with the coordinator. |
| Group preparation | A small helper alongside `stage1.py` / `stage2.py`, reusing `prepare_stage`, `controller.write_artifacts`, and existing packet inspection | Several existing packets per reviewer delivery; local exclusions and resumable output. No worker launcher or scheduler. |
| Shared integration | `scripts/paper_core/cli.py`, package manifest, references, v3 tests | One integration owner resolves shared-file changes and keeps the ordinary examples executable. |

Useful implementation anchors: `authoring.create_unit` generates the item/specification pair; `authoring.correct_claim` updates the ordinary pair; `assistance.authoring_template` exposes creation or current replacement; `cli.cmd_template` supplies the database and packet; `work.select_assignment` limits compatible contexts; `stage1._reuse_assignment` and `prepare_stage` preserve current packet identities; `controller.write_artifacts` preserves exports and provides recovery commands.

A runtime owner can implement authoring while another implements the group helper. Avoid concurrent patches to `cli.py` or shared instruction files. This allocation concerns implementation work, not a required agent arrangement for users of the skill.

Put the rules into the existing skill instructions at their point of use:

| Location | Focused change |
| --- | --- |
| `SKILL.md`, Phase 1 and ownership paragraphs | State that primary examiners independently draft items, links and examinations while the coordinator consolidates shared identities and owns database writes. |
| `references/database-audit.md` | Clarify inventory first, followed by discovery through assigned proofs; supplier-first registration does not require proving every supplier before examining its consumers. |
| `references/graph-records.md` | Replace the ambiguous hypothesis wording; show one named assumption reused as source context and distinguish it from private scope and a proved supplier. |
| `references/primary-checker.md` | Explain how to report an unregistered dependency by source locator while continuing available work. Separate the supplier's own derivation from its use in this proof. |
| `references/phase1-drafts.md` | Explain local draft intake, preserved primary reasoning and the optional format/helper, with the two-workers/one-equation example. |
| `references/coordinator-protocol.md` | Assign shared-node creation, reuse, and source matching to the coordinator during ordinary Phase 1 intake; no per-equation approval exchange or new registry. |
| `references/controller-workflow.md` | Connect Phase 1 draft intake to the existing authoring and examination commands and give bounded continuation rules. Keep grouped-review commands in Phase 2. |
| `references/independent-checker.md` and generated `assistance.worker_guidance` | Briefly describe source-based dependency reports and neutral context continuation using existing role-specific fields; no invented IDs or new response schema. |

Replace conflicting guidance instead of appending another warning list. The entrypoint needs only the responsibility rule; the optional draft-format example belongs in a focused reference, not another required workflow manual.

## Bounded validation for the programmer

These are development checks, not extra steps in a paper audit. Use the existing synthetic v3 fixtures, ordinary public commands, and user-wide Python/Node installations. Do not alter the original test databases or commission a new large-paper run to finish this patch.

| Scenario | Acceptance result |
| --- | --- |
| Two ordinary theorems with hypotheses, one using the other | Hypotheses remain in exact statements; no accidental private-scope restriction. Existing genuine private-scope behavior still works. |
| Two theorems cite the same named assumption, with one clearly identical restatement | One reusable assumption record and its captured context suffice. No copied private scopes, new proof duty for the assumption, or automatic favorable support is introduced. |
| Two primary workers report the same source equation before its node exists | A bounded workflow example shows the coordinator reusing one record and retaining distinct consuming uses, while workers' available reasoning is preserved. No worker-to-worker negotiation or new mandatory report form. |
| Equal equation labels occur in different sources | Source identity and context distinguish them; no merge based on the label alone. |
| Correct an external record's statement passages through `template --id` | A current `replace` is generated, optional data is preserved, and the existing identity/history remains. Named create for a missing same-ID extension still works. |
| Invalid `update` operation or stale author packet | One accurate local diagnostic identifies the valid operation or refresh command. No partial writes. |
| Correct a claim sign and its statement anchor through the new helper | Item and direct exact specification change together. No stale statement pin, invented source match, or new favorable proof verdict. An unrelated reviewed unit remains unchanged. |
| Replay that correction; submit a conflicting edit; try a custom exact specification | Replay is idempotent; conflict and unsupported pairing preserve the database and give local next steps. |
| Prepare two groups across several distinct proof contexts | Multiple ordinary packets are delivered, actual task sets are disjoint, and explicit selection does not introduce unrelated work. All selected-ready work or exclusions are accounted for. |
| Mix ready, satisfied, unavailable, and oversized requested units; interrupt an export | Later ready work is usable, remaining reasons are visible, and saved packets can be re-exported without duplicate scientific work, changed membership, or overwritten responses. |
| One worker returns multiple packet responses, one malformed or missing | Valid responses are retained independently. Only the remaining packet needs continuation; integration and finalization use existing rules. |
| A dependency is discovered after preparation, including during independent review | Source-only extension is used only where supported. Changed graph inputs receive an affected current assignment and bounded continuation, preserving original bytes and unrelated work. A changed packet ID alone never supplies missing examination. |

Extend the existing `test_v3_contract.py`, completion/delivery fixtures, and focused helper tests where practical. Use one short source-backed walkthrough to validate responsibility instructions; do not create a runtime dependency-discovery framework just to automate that walkthrough. Run affected tests during development, then the combined `test_v3*.py` suite once after integration. Include one small CLI sequence from creation through correction, two reviewer groups, ordinary intake/integration, freeze, and HTML. Synthetic reviewer responses test mechanics; they do not establish actual independent reasoning or faster model execution.

Refresh and verify the candidate's own runtime manifest with `scripts/build_manifest.py`. Record the checks actually performed in `VALIDATION.md`. Reuse the existing release process; do not run the older shared-core bundle builder over this package. A future patch release can keep the canonical installation name. This plan itself does not install, commit, push, or change a version.

### Implementation validation, 2026-10-05

The isolated package is now 3.0.3. All 136 v3 tests passed together in 53.913 seconds, including 25 new tests for draft consolidation, context preservation, ordinary corrections, grouped review/recovery and the public CLI workflow. The CLI exercise consolidated two worker drafts into two shared claims, corrected a claim/specification pair, prepared two disjoint review groups, accepted their separate responses, integrated the saved judgments, froze a completed release and rendered HTML with the existing Node runtime. The gap, four examinations and two original independent responses survived; rendering did not change the database.

Independent implementation review prompted two local corrections before final validation: referenced setup anchors now reach the consuming question without a private scope, and group re-export retains earlier response paths without asking for repeated examination. Source judgments retain their actual examiner identity.

The runtime manifest verifies 54 files with identity `9784b457d41863aa80c062cd545f499bfa0f8c38f260f76be57efc1555e42c42`; skill metadata validation passed. See `../stat-proof-check-v3/VALIDATION.md` and `../tmp/authoring-groups-20261005/v3-suite.txt`. These tests use synthetic judgments and do not establish real-paper speed or mathematical accuracy. Installation, commit and push were not performed as part of this implementation.

## Deferred work and stopping boundary

The previously identified coordinator-opinion leak inside source packets and incorrect integration of saved judgments belong to priority 3 and remain separate targeted work. The new delivery index must not introduce additional private context, but this revision does not claim to repair every existing source-only packet defect. Broad changes to examination reuse or invalidation belong to priority 4 and are also deferred.

Do not add scientific checklists, a second findings audit, automatic repair agents, formal proof duties, per-proof image capability tests, fixed session limits, benchmark time promises, or another review to confirm every correction. Keep existing truthful completion and independent-review requirements.

The implementation is ready for a later paper test when the ordinary command path can correct the motivating records, prepare distinct groups, accept their useful returns, and finish or report a specific remaining limitation without a database rebuild or unrelated repeated examinations. Later real runs should assess speed and scientific quality separately; passing these mechanical checks proves neither universal reliability nor mathematical accuracy.
