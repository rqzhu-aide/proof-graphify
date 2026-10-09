# Proof-check baseline rebuild: revision handoff

Status: planned, not implemented. Date: October 4, 2026.

## Purpose and authority

Build a new revision from the working 2.3.5 baseline, with improved multiple-source handling and three simple stages. The product is an evidence-backed graph database, examinations of its important connections and combined reasoning, a summary of findings, and an Archify HTML report.

The governing requirement is **reliable completion of a finite, declared audit**. Routine record maintenance must not generate further scientific assignments. A proof gap is a finding to report, not an instruction to invent a repaired proof. Missing evidence or unavailable review must lead to an honest limited delivery when they cannot be resolved within the task.

This handoff replaces the implementation prescriptions in the earlier workflow, local-recovery, three-stage and v2.3.8 reliability handoffs for this rebuild. Those documents remain historical evidence. In particular, do not reinstate their whole-scope readiness gates, mandatory calibration, character-coverage certificates or per-record reconciliation requirements by following an older reference. This document is an engineering handoff, not additional material that ordinary paper-audit agents must read.

The requested work at this point is this plan. Implementation, installation and release have not been performed.

## 1. Starting point and boundaries

| Component | Starting point | Treatment |
|---|---|---|
| Proof-check and maintained shared core | `ad40833c687932a06337188f1312f3b5492dca15`, version 2.3.5 | Create an isolated candidate from this commit. Apply the changes below. |
| Current proof-check release | `fca6c5cae7eef34384157e8b12749e9d83dc4d15`, version 2.3.9 | Preserve as a comparison, compatible historical reader and source of selected fixes. |
| Graphify | `92fe3cae81b554cb0f24cb28d01fde8facfb0ab8`, version 3.1.16 | Preserve its product behavior. Adapt and test its shared-core bundle without adding proof-check obligations. |

Recheck actual repository state before implementation. Preserve unrelated changes, saved audit databases, original worker outputs and installed releases. Do not reset a shared checkout or install 2.3.5 over the current skills as the first experiment. Copy this handoff into the isolated candidate because the baseline commit predates it.

Use fresh candidate audit databases. Do not open 2.3.9 stores with the stock 2.3.5 writer. Unsupported feature checks are meaningful even though their SQL schemas are alike.

Edit `shared/paper_core` in the maintained repository, then generate the packaged cores with `tools/build_paper_core_bundles.py`. The builder also writes the sibling Graphify package. Give the candidate an isolated sibling checkout or explicit isolated package destinations before running it; a worktree alone does not isolate the builder's sibling output.

Keep the physical database initially. Both versions have 12 tables, 8 views and 27 logical collections. The main burden is the required authoring and task policy, not newly added SQL tables. Do not combine this revision with a database replacement, general scheduler, tool installation, manuscript editing or redesign of the Archify interface.

## 2. Decisions to implement

| Keep | Simplify or remove from ordinary execution |
|---|---|
| Exact claims, hypotheses, source identity and full captured passages | Duplicate source comparisons when the displayed statement and exact target truly share the same text, setup and source |
| Important prerequisite connections, jointly required premises, alternative routes and local assumptions | Mandatory graph decomposition of routine algebra or every displayed equation |
| Mathematical examination of applications, cases, discharge and the combined conclusion | Automatically creating a separate compulsory task for every group, use, case or discharge record |
| Located proof passages, continuation inspection and explicit omissions | Compulsory character-by-character coverage closure and filler rows |
| Actual independent examination for modes that promise it; original response and exposure history | Mandatory calibration during ordinary paper runs; preserve existing calibration evidence only when actually available |
| Integration of primary and independent reasoning; visible disagreements | Mandatory agreement rows for every detail and repeated review until agreement |
| Integrity checks, immutable evidence and material-change freshness | Whole-scope perfection gates, administrative edits reopening science, and agent-authored hashes/pins |
| Saved scientific results and the existing Archify renderer | A live database dependency or new scientific assessment in Stage 3 |

Calibration removal changes the assurance policy. Do not describe an uncalibrated reviewer as qualified or reuse an old qualification label without its evidence. This does not remove independence, which concerns the actual context, source access and exposure of the reviewer.

Preserve the current explicit-invocation policy and the scientific restrictions on proof examination. This rebuild does not authorize simulations or empirical experiments as substitutes for mathematical reasoning. Triage still makes no completed proof-audit claim. Focused and Full retain their declared scientific scope and actual independent-review requirement.

## 3. One coherent examination contract

### The unit of work

Use an existing written proof route, or a meaningful source-located subsection when the proof is too large, as the normal unit. The audit's declared targets and written-route inventory determine required work. Registering explanatory graph detail does not itself enlarge that inventory.

A subsection must have an exact local question and enclosing conditions. Splitting a proof does not eliminate the need to examine how those subsections establish its conclusion. Perform that composition within the owning proof's examination or integration, without turning every subsection into a fresh whole-proof review. Distinct written routes and distinct material outcomes remain distinguishable.

The coordinator may discover a genuinely missing in-scope claim or route. Add that work and record why. Do not silently narrow Full scope to the graph that happened to be entered, or treat a new ID for already examined reasoning as a new scientific requirement.

For an uncomplicated route, scripts can generate one argument, its context and a coherent final inference with the meaningful supplier uses. Add internal nodes, branches and nested scopes when they express a reusable conclusion, a material difference or reasoning that cannot faithfully fit that simple structure. Routine equations need not become individually registered claims. Replace inventory logic that treats every stored item or registered child argument as a new required unit; in particular, audit `scope_statements` along with task derivation.

### Minimum information, not a new record family

Reuse the existing claims, arguments, checks, findings, responses and integration records. The normal authoring interface exposes evidence, claims, routes/connections, examinations and findings. The following information must be expressible without a separate certificate for every edge:

| Information | Responsibility |
|---|---|
| Exact unit and question, with source passages and conditions | Agent chooses the scientific scope; scripts preserve identity and source versions. |
| Scope actually examined, relevant route/context, and omissions | Agent states what was examined. The assignment supplies the ordinary whole-unit scope; explicit exceptions identify narrower coverage. |
| Outcome and reasoning about important applications and their combined implication | Agent performs the mathematics. A favorable label alone is insufficient. |
| Material local differences, affected claims/connections and limitations | Agent names the meaningful exceptions. Uniform routine detail needs no individual verdict rows. |
| Independent response, exposure, and integration decision when required | Preserve what was actually returned; generate routine record associations. |
| IDs, pins, hashes, paired records, revision bindings and history | Scripts generate and validate these. They are not scientific writing assignments. |

Use an existing `composition` check for the ordinary unit examination, retaining its role, outcome, reasoning, conditions and evidence. Add a narrowly versioned examination extent, `whole_unit` or `partial`, and an omission note. The assignment supplies the exact unit and passage inventory; scripts bind the scientific inputs. `whole_unit` is an affirmative claim about the examination actually performed, not a conclusion inferred from an empty omission field. Local checks remain optional for materially different or reusable conclusions and may be saved with the same examination without commissioning another job.

Before parallel implementation, the integration owner records the exact API mapping and one mixed-outcome example for this contract. Do not introduce a parallel examination/task database, a mandatory nested outcome for every edge, or synthetic per-edge checks produced from a broad verdict. All workers consume this one contract.

### Support and completion must use the same contract

Change task derivation, local support, coverage, freshness, review eligibility, integration and report completion together. Use one shared resolver for the new policy's local examination basis so these consumers cannot invent different coverage rules. Altering only the task list is not acceptable. Legacy checks receive no new-policy scope credit merely because their old outcome was favorable.

An examination may supply the local reasoning basis for the connections explicitly within its scope. This is not unconditional support for every owned node. Premise availability, exact applicability, scope and alternative-route semantics still apply. An omitted or newly introduced substantive connection receives no examination credit. A material local defect takes precedence over an encompassing favorable summary.

Under the new protocol, a current `whole_unit` supported primary examination supplies the local-validity basis for substantive inferences and applications within that examined unit. It asserts that their reasoning and applicability were examined, not that their suppliers are established. A gap, refuted or inconclusive unit supplies no default positive basis for its members. An optional local result can support a particular internal inference even when the owning proof's final composition fails. Missing suppliers keep dependent support conditional. Material local findings and integrated independent outcomes remain effective; ownership or a favorable primary summary cannot override them. No list of individually accepted routine edges is required.

Apply the same source-comparison basis to faithfully represented internal detail that was actually examined within the fixed source/setup. Update `exact_target_current` and related source-fidelity consumers so they do not recreate a separate exact-specification/comparison job for every explanatory node. This is reuse of an examined basis, not automatic source approval for new assertions, altered restrictions or material outside that examination.

For example, a review can find both applications of probability bounds valid while their joint inference incorrectly promises failure probability at most \(\delta\) instead of \(2\delta\). Preserve those different facts without requiring a separate job for every valid application. Likewise, a valid alternative proof does not erase a gap in the written route being audited. Circular dependencies acquire no support merely through ownership or a favorable route label.

The examined scope is fixed to the actual scientific input. Adding equivalent explanatory detail can reuse the recorded basis; changed hypotheses, new source evidence or a genuinely new route cannot inherit it automatically. Update bindings that currently consume coverage-row membership and individual check identities so routine detail does not make a completed examination stale. Do not use whole-database revision changes as a reason to repeat all examinations. Do not attempt a general automatic theorem-equivalence checker: uncertain correspondence stays limited to the affected unit and must be explained.

Retain distinct meanings in the derived report:

- **Examination outcome:** supported within stated conditions, gap, refutation, inconclusive or a preserved disagreement, as applicable.
- **Required work performed:** whether the promised primary examination, independent examination and integration actually occurred on the relevant input.
- **Declared scope accounted for:** examined work plus explicit exclusions, unavailable sources and unfinished work, without disguising omissions as coverage.
- **Delivery:** frozen result available, and HTML produced or failed.

These are report distinctions, not four new ledgers. A gap or an honestly inconclusive examination can finish an assigned examination. An integrated but unresolved disagreement does not require repeated attempts to obtain agreement and cannot produce unqualified support. Missing promised review, unexamined required material or unresolved transcription cannot be counted as completed Full work. A limited artifact is useful delivery, not evidence that the intended full run succeeded.

## 4. Multiple-source and packet changes

2.3.5 already supports multiple captured sources, local TeX includes and multiple anchors. Extend that implementation rather than rebuilding source discovery.

1. **One exact scientific object can have several passages and labels.** Link main paper and supplement using the actual statement, hypotheses and cross-references. Preserve file/page/line locations and observed aliases. Never infer correspondence from a numbering offset alone. If identity is ambiguous, retain that limitation.
2. **Keep complete proofs and continuations.** Support precise selections for proofs sharing a page and for disjoint passages, while preserving complete captured excerpts. Carry the span contract, selection validation, source/version bindings and consumers together. Explicit invalid selections cannot silently shrink, widen or drop a continuation. The selection locates evidence; it does not create a character-accounting requirement.
3. **Repair prerequisite selection through intermediate records.** Traverse the relevant hidden intermediate dependencies until the necessary source statements and setup are reached, with cycle/visited bounds. Supply a supplier's proof only when the assignment actually depends on that proof. Do not attach every upstream proof or begin an unrestricted literature audit.
4. **Give reviewers the exact neutral question.** Repair local-target selection and packet construction together. A local bound assignment must not repeatedly become the owning theorem while its answer is recorded against a hidden smaller task. Withhold primary judgments and proposed solutions, not the question and its conditions. Keep the question, selected passages, private task correspondence, input binding, response scaffold and intake mapping aligned. The owning theorem supplies enclosing context, not a replacement conclusion. Permit a narrowly source-only assignment description in the blinding rules without exposing the private manifest. If an exact neutral local question cannot be grounded, use an honestly broader unit and preserve that actual scope.
5. **Match global/integration context to freshness.** Deliver the selected proof passages, including supplements, needed for the actual question. Bind the examination to the same selected evidence. Do not deliver one scope and invalidate according to a different scope.
6. **Keep useful reader fixes contained.** Reuse file/page/version labels and safe formula display fallback. PDF extraction diagnostics may identify damaged evidence, but do not certify fidelity. Consequential unreadable mathematics remains a source limitation; an HTML conversion problem with readable source remains a presentation issue.

Retain existing packet size and traversal bounds. Keep meaningful scientific units intact. If the required context cannot fit or be obtained, split at a coherent source boundary or disclose what remains unexamined; do not silently trim a hypothesis or continuation. Additional supplied context cannot retroactively enlarge the scope of an earlier response.

Relevant source areas are `sources.py`, `proof_spans.py`, `packets.py`, `bindings.py`, `contract.py`, `acceptance.py`, `validation.py`, `__init__.py`, the source-scope consumer in `assessment.py`, and `renderer/render_projection.mjs`. Persisted span semantics must declare the appropriate supported feature through acceptance so older readers cannot silently misinterpret them. In particular, `_source_target`, `_assignment_packet` and `prepare_assignment` must agree about local assignments; a packet passing blinding checks does not prove that it contains the right question. The later span implementation is a dependency reference, not a whole-release cherry-pick. Do not import the later per-record grounding gate or consumed-evidence maintenance framework unless a demonstrated candidate failure needs a narrow part of it.

## 5. Three stages with finite transitions

| Stage | Work | Durable result and transition |
|---|---|---|
| **1. Prepare and examine** | Establish declared scope and source inventory; capture evidence; build meaningful claims and connections while examining proofs; repair material representation errors; save primary reasoning. | Each planned unit has primary work or a named limitation/unexamined status. Source-sufficient examined units can proceed; an unavailable unit does not hold unrelated work hostage. |
| **2. Review and integrate** | Obtain actual independent examinations; integrate saved work; resolve mechanical mapping locally; reconcile material scientific differences; examine cross-proof consistency; summarize coverage and findings. | Save a consistent scientific snapshot. If promised work remains unavailable or unperformed, save a clearly limited result with the affected conclusions identified. |
| **3. Present** | Render the saved snapshot through the existing Archify adapter; verify report navigation and displayed findings. | Deliver HTML, database and summary with matching scientific identity. If rendering fails, retain the snapshot and deliver the database/summary with the HTML failure stated. |

Three stages describe responsibilities and normal order. There is no additional all-records-perfect barrier or special ready-subset policy to negotiate. An affected unit needs accurate enough source and question to be reviewed; unresolved representation problems in that unit must remain explicit. Finishing Stage 1 with limitations does not turn those limitations into examination evidence.

Cross-proof consistency, shared assumptions and any material method/proof interface belong in Stage 2 integration. Retain their scientific content in the applicable examination and summary; do not require three separate global jobs or empty not-applicable records on every paper. A genuine cross-proof question can be a targeted assignment. It must not automatically repeat every local proof.

Keep the existing CLI wrapper. Provide three thin entry-point groups and separate implementation modules for Stage 1 preparation, Stage 2 review/integration/finalization, and Stage 3 frozen rendering. Share storage and scientific assessment functions. The implementation may retain the existing `stage1`, `stage2` and `stage3` command names; it must not retain their old gates merely to preserve a name. Stage 3 must be invocable with only its frozen bundle and output destination.

Stage selection must be explicit. In the baseline, an empty task-ID list can mean automatic selection, and a primary role can include global work. An empty stage therefore returns its accounted-for status rather than accidentally selecting all remaining work. Repeating preparation with unchanged inputs should return the current assignment or lack of useful work, not manufacture more packets.

### Bounded recovery

Use the same short rule in all hosts: diagnose the failing operation, correct the smallest relevant cause, verify that correction, and resume affected work. Do not reissue the same operation on unchanged inputs expecting progress.

| Situation | Required behavior |
|---|---|
| Wrong function argument or malformed envelope | Return the exact local correction; preserve scientific content and original worker bytes. Correct mechanics before considering another scientific review. |
| Valid response plus peripheral malformed or out-of-scope row | Accept separable valid content and retain the remainder for local disposition. A provenance failure affecting the whole response is not separable. Never discard an adverse concern to obtain clean acceptance. |
| Material adverse concern | Attach it to the relevant unit or retain an explicit unresolved mapping/impact. Do not count the affected integration as clean while hiding the concern. |
| Missing source or prerequisite context | Use already captured evidence first; make a targeted source/context correction. If still unavailable, identify affected conclusions and finish with that limitation. |
| Independent route unavailable | Check actual available capabilities before asserting unavailability. Do not fabricate a reviewer, invent a model requirement or retry a known unavailable route. Deliver the unmet review requirement explicitly. |
| Scientific disagreement or gap | Compare reasoning once within normal integration. Pursue a further examination only for a concrete unresolved question that can change the finding; otherwise retain the disagreement/gap. |
| Repeated mechanical failure after a targeted correction | Preserve the last valid records and failed input, report the failed operation, and use the limited-delivery path. Do not restart the audit or enter another unchanged repair cycle. |
| Late material source/claim correction | Reopen affected examinations and their dependent conclusions. Preserve unrelated evidence and prior responses. |
| Renderer failure | Retry rendering against the same frozen input. Never regenerate science to repair presentation. |

This rule does not impose a time limit on mathematical thought or hide unperformed work. It prevents repeated administrative operations from masquerading as progress. Use existing history and statuses; do not add a general retry-policy engine.

## 6. Frozen delivery and compatibility

Stage 2 freezes one assessed database revision: exact claims/scope, selected source evidence, examinations, integrated findings, limitations, and the projected report input. Preserve the scientific producer/protocol identity and a content hash. The summary and HTML must describe that same revision.

Reuse the useful pieces of the later finalization/publisher implementation without importing the full stage engine. The baseline projection can accept an already computed assessment. Validate the selected snapshot once as part of freezing; avoid recursive re-projection. Do not turn the later representation-readiness helper into another whole-scope completion gate for limited output.

Use the existing `working` and `release` output kinds. Under the new protocol, performed primary examination, independent examination and integration may produce a release containing gaps, inconclusive conclusions or unresolved scientific disagreement. These limit mathematical support; they do not themselves mean promised work was unperformed. Missing required examination, source or review, or unresolved transcription, produces working output. Update frozen validation and report labels accordingly; do not retain the later automatic disagreement blocker.

Stage 3 reads the frozen bundle, checks its integrity and invokes the renderer. It must not call live scientific derivation, fetch missing scientific content or update checks. Retrying a build must leave scientific bytes unchanged. Publication metadata may record a new build attempt separately. Preserve prior reports on a failed build and prevent output paths from overwriting the database, evidence or frozen input.

If integrity damage makes a valid freeze impossible, deliver the last valid saved artifacts and a plain failure summary. Do not construct a purportedly valid scientific snapshot from corrupted records. Mark that delivery as failed/incomplete rather than a completed audit.

Use a new protocol identity as well as a new release version. Enforce compatibility where stores, packets, responses and evidence are consumed. Do not simply relabel the current history or reinterpret old pending counts using the reduced obligation rules.

For the first release, new-protocol audits start fresh. Before replacing installed packages, preserve the complete compatible historical skill bundles, including the packaged core and renderer, in a user-wide versioned archive outside automatic skill discovery, and record their invocation paths. Include the 2.3.9 reader needed for unfinished saved audits and the 2.3.5 comparison runtime. A Git revision alone is not an executable historical reader. A new writer should refuse unsupported legacy workflow mutations clearly. An optional read-only legacy view must preserve historical labels. Migration or resuming an old audit under changed semantics is a separate project, not a release requirement here. Graphify's supported overview path remains usable and must not be rejected simply because it has no proof-audit protocol.

## 7. Implementation assignments and order

The implementation lead owns integration and acceptance. Independent workers may implement the following packages in parallel **after** the small common examination contract is fixed. They should not each invent their own completion policy.

| Assignment | Owned work | Boundaries and acceptance evidence |
|---|---|---|
| **A. Scientific contract and engine** | `contract.py`, scientific semantics, `assessment.py`, `support_semantics.py`, protocol handling and the compatible scope/binding interfaces | Removes automatic administrative task growth while retaining honest local support, material differences and completion labels. Owns shared contract changes requested by other workers. |
| **B. Evidence and review packets** | Source selection/capture consumers, neutral packet construction, independent response/intake handling, source-location rendering and their focused tests | Implements Section 4 and separable intake using A's contract. Does not edit task/completion policy or add source gates. Requests changes to shared schema/bindings through A. |
| **C. Stages and delivery** | Thin stage modules, CLI routing, finalization, frozen publishing and delivery tests | Uses A's assessment and B's packets. Does not duplicate scientific derivation or impose additional readiness requirements. Requests projection changes through the designated integration owner. |
| **Integration lead** | Shared-file integration, normal-path documentation, Graphify compatibility, bundle generation, matched execution and release | Audits the actual product, observes runs, and fixes conflicts. Does not make a test pass by authoring missing scientific work during the observed candidate run. |

Set precise file ownership before starting workers. In particular, `contract.py`, `bindings.py`, `validation.py`, `projection.py` and CLI interfaces cross packages; each has one editor at a time. Workers provide narrow patches or interface requests to that owner instead of concurrently modifying shared definitions. No worker runs the bundle builder, installer or release process independently.

Implementation sequence:

1. Preserve releases/evidence, establish isolated paths, confirm the baseline and record the common examination contract with one mixed-outcome example.
2. Implement the contract/engine change and the source/packet change. Use a small real-source slice to expose mismatches between saved scope, packet scope and support before implementing all delivery behavior.
3. Complete the three entry points and frozen renderer. Consolidate the ordinary skill instructions around them. Remove obsolete obligations from every reference reachable by the normal path, including worker prompts and generated scaffolds.
4. Run focused semantic, packet, recovery, compatibility and packaging checks. Review changed tests: replace assertions tied to deliberately removed obligations, while preserving their scientific counterexamples. Do not delete failing scientific cases to obtain a green suite.
5. Run the matched paper comparisons and cross-host exercise below. Address observed material failures; do not expand the design for hypothetical variants.
6. Produce a release only after the behavioral evidence meets the acceptance criteria. Update the common core and both packaged skills consistently, then validate the actual installed entry points.

Keep this handoff outside ordinary skill loading. The coordinator should have one concise normal workflow; workers receive the actual assignment, evidence and response shape. Detailed compatibility or failure references are read only when applicable. Do not move the removed obligations into a long recovery appendix.

## 8. Validation focused on the user's outcome

### Focused checks

Use small cases to test changed boundaries, not a new exhaustive safeguard matrix:

| Case | Observable acceptance result |
|---|---|
| Routine graph detail added after a proof was examined | No new compulsory examination or individual verdict fabrication. A changed condition/new substantive route does create affected work. |
| Mixed outcomes and joint reasoning | Valid applications stay distinguishable from a bad joint conclusion. AND premises are not alternatives; genuine alternative routes remain separate. |
| Missing case, local assumption leak, fixed-parameter result used at a data-dependent optimizer, circular support | The defect remains representable and affects the proper conclusion after microtask removal. Test these as scientific cases, not required runtime job kinds. |
| Exact target loses a hypothesis while its synopsis remains accurate | It cannot reuse the synopsis's source match or inherit the original supported conclusion. |
| Main/supplement aliases; two proofs on one page; multi-page continuation | One correct identity and complete located scope. Ambiguous identity stays explicit; a dropped continuation or changed source bytes invalidates the affected evidence. |
| Hidden intermediate suppliers, including multiple hops and a cycle; three different local questions within one theorem | Necessary supplier statements arrive; actual proof borrowing also delivers the needed proof passages. Ordinary dependencies do not automatically expand into supplier-proof audits. Each assignment exposes its actual neutral question; the same whole-theorem answer is not silently accepted as three local examinations. Question, condition and passage changes affect freshness; cosmetic label changes do not. |
| Review with extra detail, malformed peripheral row, or adverse concern | Valid separable evidence survives; defects and relevant concerns remain visible. No whole-proof rerun solely for envelope or peripheral-row repair. |
| Missing source, unavailable review, inconclusive examination, unresolved disagreement | Terminal artifacts describe the actual limitation. Missing promised work never earns completed Full status; unresolved truth is not retried merely to become favorable. |
| Freeze revision R, then change live database to R+1 | Rendering R uses only R. Render retry preserves scientific hash and checks; failure preserves prior artifacts. |
| Old saved audit and Graphify overview | Historical evidence/completion are unchanged. Graphify still builds and displays its selective source-backed map without proof validation duties. |

### Matched paper execution

Use the original Distributional-RL case and RF-HTE with the relevant supplement. For each comparison, hold source files, declared scope, agent/harness configuration, tools, independent-review route and execution allowance constant between baseline and candidate. Record content identities, not only version labels. If the old successful case cannot be reproduced under the current harness, report that separately; its historic success is not a controlled runtime benchmark.

Locate the original inputs and run configuration from these preserved result folders. Read their manifests and captured sources; do not resume or mutate their databases as candidate tests:

- `C:/Users/zrq/projects/skills/_testing-center/results/stat-proof-check@v2.3.5+distributional-rl-main__20260929-195600`
- `C:/Users/zrq/projects/skills/_testing-center/results/stat-proof-check@v2.3.9+rf-hte__20261003-134829`

Minimum evidence is one matched baseline/candidate pair for each paper, plus a focused end-to-end exercise on a second available host/reviewer route to detect host-specific assumptions. This is not a requirement to replay every historical case on every model. If the necessary hosts or papers are unavailable, focused tests can proceed, but improved end-to-end completion remains unverified and the candidate must not be promoted on that claim.

The old completed Claude and DS4 runs are relevant evidence, but the 2.3.5 and 2.3.9 saved runs used different papers and conditions. Neither those comparisons nor the prior small fixtures demonstrate universal completion. In particular, repeated packet creation is not the same as repeated scientific review; measure the actual work.

During observed candidate runs, the supervising developer may observe and collect diagnostics. Do not author missing judgment records, choose exact reconciliation pins, silently repair input contracts or supply an undisclosed reviewer route. Configure the available tools/review route before both matched runs. If intervention becomes necessary, preserve it as a failed/unassisted-run result, fix the product and rerun the affected acceptance case.

Record a small comparison table covering: delivered artifacts and scope; required review actually performed; material findings retained; elapsed and active work where available; normal examination, justified scientific reexamination and mechanical retry; additional task creation from routine graph edits; and any developer intervention. Save the original logs rather than building a new telemetry system.

Acceptance means the candidate follows the planned path, accounts for the requested scope, preserves material findings and reaches useful honest delivery without recurring administrative loops. A limited-delivery failure case passes its fallback test, but cannot substitute for completing the available-source/reviewer paper cases. Lower task counts, exit code zero, fewer findings or a large passing unit suite do not establish that result. The report remains a rigorous non-formal audit, not a mathematical correctness guarantee.

## 9. Release and final handoff checklist

Before promotion, the implementation lead should be able to demonstrate all of the following:

- The ordinary run no longer needs per-record check rows, a character ledger, mandatory calibration or repeated clean-agreement repairs to finish its declared scientific work.
- Source, packet, scientific support and completion consumers agree on the same examination scope. A returned finding cannot disappear during mapping or integration.
- Stage 3 succeeds without the live database, and presentation failure does not reopen mathematics.
- The matched runs and focused negative cases have recorded results, with limitations and interventions disclosed.
- The old releases and saved databases remain available under compatible readers, and Graphify still performs its selective overview task.
- Both generated bundles match the maintained shared core and the installed entry points match the tested release identities.

Choose the next unused versions at implementation time; never relabel the rebuild as 2.3.5 or silently replace 2.3.9 content under its old identity. The new protocol communicates the changed completion/assurance contract independently of package numbering. Bump Graphify only as needed for its changed package/bundle, without claiming new proof-check features for it.

After validation, install both packages to the requested user-wide `.agents/skills` and `.claude/skills` locations using the existing supported installer path, verify installed identities and run a small installed-entry smoke test. Use existing shared runtimes and packages. Then commit and push the intended repository changes under the user's release instruction, recording both repository revisions. Do not include test databases, private source papers or run logs in release commits by default.

The implementer's final delivery should link the changes, the compact behavioral comparison and the exact deployed identities. State any remaining limitation directly. If real runs still require repeated repair, retain the candidate for diagnosis rather than declaring success from mechanical test results.

## Evidence and detailed extraction notes

- [Approved rebuild proposal](../../audit-reports/v239-rf-hte-2026-10-04/baseline-rebuild-plan.md)
- [Minimum source package and dependencies](../../audit-reports/v239-rf-hte-2026-10-04/baseline-rebuild-sources.md)
- [Three-stage and frozen-delivery extraction](../../audit-reports/v239-rf-hte-2026-10-04/baseline-rebuild-stages.md)
- [Complete simplification evaluation](../../audit-reports/v239-rf-hte-2026-10-04/simplification-evaluation.md)
- [Database evaluation](../../audit-reports/v239-rf-hte-2026-10-04/simplification-database.md)
- [Packet exposure evidence](../../audit-reports/v239-rf-hte-2026-10-04/packet-exposure.md)
- [2.3.9 RF-HTE audit](../../audit-reports/v239-rf-hte-2026-10-04/audit.md)

These notes justify the selected changes. They do not override the smaller execution contract in this handoff or become mandatory reading during ordinary paper audits.
