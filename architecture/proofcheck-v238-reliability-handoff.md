# Proof-check reliability revision handoff

Date: October 3, 2026. Status: implemented; see the [validation and release record](proofcheck-v239-reliability-validation.md).

The [defect tracker](proofcheck-v238-defect-tracker.md) owns defect status, baseline identities and evidence. This handoff defines the universal behavior to implement. It applies to any agent, model, provider or host capable of the relevant operations. Test-run names are evidence labels, never execution requirements.

## Objective and scope

Keep the existing three stages:

1. Prepare evidence, graph and primary examination.
2. Independently review, integrate, reconcile, finish the audit and freeze its results.
3. Produce the Archify HTML from those results.

Make their handoffs reliable and keep recovery proportional to the actual change. This revision adds no fourth stage, database stage lock, second task ledger, model executor, automatic reviewer dispatch, retry daemon or paper-specific heuristic. SQLite and the existing scientific assessment remain authoritative. Negative mathematical outcomes can still complete examinations; useful partial work can still be saved.

The shared core is maintained in `shared/paper_core`. Regenerate both shipped bundles with the existing builder. Graphify remains a selective overview skill using its existing workflow; it does not acquire proof-check stage requirements. Preserve invocation policy, original reviewer authorship, source-only independence, exact scope, unchanged returned bytes and completed-audit criteria.

## A. Settle records before review integration: WF-01 and WF-03

### One practical order within Stage 1

For each coherent proof, establish its source, statement/setup, argument and final-group structure, and source links on its actual applications and inference groups. Then certify the final written-proof spans, examine the argument, and save reasoning and coverage. These are steps inside Stage 1, not additional stages or a requirement to build every proof in the paper first. Existing same-batch cross-references can avoid creating a knowingly provisional argument followed immediately by a registration edit that invalidates its certificate.

Substantive discoveries may still refine the graph later. They reopen affected work with a specific reason. There is no blanket graph freeze and no requirement to predict every independent finding.

### Structural source correspondence at the boundary

Extend the existing primary-readiness derivation over the declared required written-proof closure. For its current uses, groups and arguments, verify usable source grounding through the same target-source resolution rules used by mapping. The written argument must agree with its current reviewed proof spans. Uses and groups require their own applicable source associations, which may be elsewhere in the manuscript: argument membership alone does not locate a supporting derivation. Report exact missing targets and the grounding operation needed.

Keep this check bounded in meaning: it verifies that known canonical records can be related to their sources. It does not premap unseen judgments, demand every target overlap every proof page, require all optional graph records, or certify semantic correspondence. A required reconstructed inference retains its honest origin and source-backed premises and can use the existing supplied-route review path; it does not need a fictitious manuscript location for the new inference itself. Its inclusion cannot exempt the actual written route from grounding or examination. A source link must describe the record's actual content, not merely a convenient nearby page.

Use one shared resolver rather than different definitions in readiness and `review map`. Prefer extending existing modules/functions over adding another subsystem. The whole-scope and explicit ready-subset paths use the same rule over their real prerequisite closures. Derive decisions before truncating displayed diagnostics. Unknown or incomplete analysis cannot establish readiness.

### Preserve the distinction between absent and stale selectors

`reviewed_spans()` and its callers must distinguish:

- A historical review that intentionally omits explicit selectors: retain its existing whole-anchor interpretation.
- A present, valid explicit selector: use its exact intervals.
- A present selector that is stale, incomplete or invalid: keep a boundary-recovery blocker and grant no coverage credit for the affected argument.

In the third case, suppress derived whole-page missing-coverage requests for that argument. Do not silently widen the proof to unrelated page material, silently drop a continuation, or clear the blocker. Process other arguments sharing the same page with their own selections. Global packets, projection, work scheduling and readiness must agree about the unresolved boundary.

### Saved-response mapping

Keep mapping anchored to the stored response ID, immutable bytes and zero-based judgment indexes. Generate help from that stored response, with packet A and current coordinator packet B clearly distinguished. Show the source target and eligible canonical context together. Never zip rows from a different response file or pick targets by list position or keyword alone.

An unchanged response needing correspondence receives a mapping next action, not a new-review recommendation. If correspondence is ambiguous, explain which judgment and target are unresolved. If source or mathematics truly changed, preserve the original and identify the affected examination. Existing partial-mapping and whole-response pending rules remain authoritative.

## B. Narrow source-link maintenance without rewriting history: WF-02

The first remedy is early correct grounding under A. Residual harmless additions need a narrowly defined comparison rule, not a global relaxation of freshness.

Keep existing `facet_digests()` outputs and historical binding rows unchanged. For newly captured evidence bindings only, use a versioned private comparison projection, following the existing per-binding comparison-marker patterns. Retain the recognized ordinary facet digest and original pins alongside the new marker so an older reader ignoring that marker remains conservative. It may treat an additive source link as administrative only when every condition below is established from pinned records:

1. The changed body differs only by adding `evidence_refs`; nothing was removed, replaced, reordered into a different meaning or rebound to different source bytes.
2. Every added anchor is within the exact source bytes and selected span already delivered **and consumed** by that examination. Presence somewhere in a packet, the same file/page, or unchanged source-context digest alone is insufficient.
3. Statement, target, hypotheses, scope, supplier relationships, application conditions, final group, route and relevant membership remain unchanged.
4. All original anchor/source guards and independent qualification, exposure and actual-response evidence still hold.

Otherwise retain current strict invalidation and identify the affected current work. A newly read page, expanded proof extent, changed source text, changed assumption, changed final group or ambiguous comparison requires actual examination. Do not automatically reinterpret evidence additions as harmless or give credit for newly supplied evidence.

Apply this distinction consistently to mathematical bindings and newly certified source-span comparisons where their contracts justify it. Capture the source-selection comparison policy in the existing private binding metadata of a newly saved source review. Both `reviewed_spans()` and `boundary_selection_digest()` must consult that policy; changing only check freshness would leave boundary invalidation unresolved. Unmarked reviews retain the full pinned argument-proof comparison. Source-span certification and mathematical examination are different decisions: preserving a known physical span must not establish mathematical correctness. Changes to initial final-group registration are prevented by authoring order in A, not broadly exempted here.

Old unmarked bindings and source reviews retain strict behavior. Do not backfill markers, rewrite old snapshots or recalculate stored historical digests. When old evidence cannot establish the narrow exception, use existing diagnostics to identify one affected terminal examination or boundary renewal. Preserve its reasoning and authorship; do not bulk-renew ancestry. The tracker should describe this as conservative legacy recovery, not automatic repair of every historical cascade.

Existing `reuse_decisions` do not already solve this problem: they permit reviewed source relocation, reject mathematical-facet/membership changes, and cannot override target changes classified as historical. Do not silently broaden that contract. An unknown marker version must fail conservatively. Document compatibility of the new private marker and test export/import and older unmarked databases before shipping; no SQL migration or new record collection is intended.

## C. Save useful work and report its effect: WF-04

Keep original submission bytes in the existing intake store. Interpret only recognizable untouched scaffold rows as omitted work, not new scientific records. Match the assigned task and type and the actual generated defaults: a draft check has empty reasoning/evidence/conditions and null outcome, next action, replacement and predecessor fields; a default source-comparison row has `needs_attention` with empty note and evidence. A changed outcome, linkage, task identity or other authored field is not an untouched placeholder. Validate it normally and diagnose malformed content instead of silently omitting it.

For a mixed response, omit only untouched placeholders and atomically save its valid authored work. Report the exact omitted task IDs. If coverage or findings reference an omitted placeholder as a supporting check, return a precise authoring diagnostic; do not fabricate a check, silently discard that authored row, or save broken links. Preserve the whole return for correction.

A placeholder-only response is stored with terminal `needs_revision` and a specific `NO_AUTHORED_WORK` diagnostic, without a scientific record revision. Its next action is to author the identified work or choose another useful task. Replaying identical bytes with the same request returns the same receipt. A changed response requires the existing fresh-request procedure. Changing only the request ID cannot manufacture scientific progress.

Useful partial work remains valid even if no obligation becomes satisfied. Require actual reasoning and a concrete remaining question/next action for a draft; evidence may be absent when the authored investigation explains a missing source. Findings and coverage can also be useful without an increase in completed-obligation count. Do not impose a word quota or require a favorable outcome.

For an explicit same-reviewer draft continuation whose content and consumed-input guards are unchanged, preserve the existing draft and report no change rather than allocating another scientific version. Compare identity, content and binding applicability within the authorized task; identical prose after changed mathematical inputs is not an unchanged continuation and must receive the applicable recovery diagnostic. Do not silently rebind it or merge different reviewers, opinions, targets or substantive reasoning. An otherwise valid request containing only such unchanged continuations returns stored `needs_revision`, `no_change: true`, exit 0, `UNCHANGED_DRAFT`, null `committed_revision`/commit receipt and the existing check references, with no scientific revision. The draft still needs work; the guidance names its saved continuation rather than requesting an identical retry. This implementation adjustment preserves the current SQLite rule that `accepted` requires a scientific commit, avoiding a storage migration solely for a no-op label. An untouched blank scaffold instead reports `NO_AUTHORED_WORK`. Existing historical blank drafts remain readable. General finding deduplication is outside scope; placeholder-dependent repeated findings are addressed by the supporting-check rule above.

Extend receipts additively with omitted task IDs, saved complete-check references, saved draft-check references and current satisfied assigned-task IDs, alongside the existing remaining IDs. Distinguish unchanged existing references from newly saved references. `accepted` means the authoring request was accepted, not that new work or a satisfied obligation resulted. A completed check row is not automatically a newly satisfied obligation. Only report a true before/after progress delta when derived from the same transaction; do not add another persisted progress ledger or require extra status polling. Exact replay of an old terminal receipt keeps its original shape, even when the new fields are absent.

Direct ordinary writes must not provide an easy alternate route to new empty drafts/comparisons. Put the new authored-work checks at write-time boundaries while preserving historical reads, exact terminal receipt replay and compatible imports. Avoid making whole-store validation reject old blank rows merely because the new authoring rule is stricter.

## D. Recover current work through consistent entry points: WF-05 and WF-06

### Successor authorization

Retain the existing current renewal candidates, which already exclude superseded checks. Enforce the corresponding rule for newly authored successors through both controller submissions and ordinary direct writes. Reject a new branch that supersedes an already superseded predecessor, and reject two new successors to the same predecessor in one prospective batch. Return the actual current candidate(s), target and next operation, never an instruction to renew every old check.

Do not enforce this by invalidating historical stored branches, rejecting compatible historical imports or replaying old receipts under new rules. Exempt an authorized same-reviewer draft replacement that preserves its inherited predecessor pin; completing that draft must not be mistaken for another branch. Resolve transactional races against the current write state.

This is not a newest-opinion-wins rule. Distinct current opinions may coexist and require reconciliation. Preserve their authorship and adverse findings. A genuinely new examination can be recorded under existing opinion rules, but relabeling old reasoning is not a new examination or a way to avoid successor authorization.

### Preparation policy

Route ordinary `work prepare` through the same stage policy as the explicit stage commands. Primary local work uses Stage 1, independent/reconciliation work uses Stage 2, and explicitly selected audit-level global work uses Stage 2 global gating. Mixed local/global requests return a precise split instruction; never silently schedule a global task early or select unrelated work when a filtered set is empty.

Keep a single explicit option for other exceptional investigations, with a nonempty purpose and bounded limitations recorded in the existing private packet manifest/receipt. Existing `--route` is itself an explicit supplied-route investigation selection: preserve its preparation path, record the named route as its purpose and the existing supplied-route limitations, and do not add a normal written-route Stage 1 prerequisite to it. For other exceptions the implementer may choose flag spelling, but behavior is fixed: the exception is opt-in, visible and cannot waive source availability, write authorization, independence, actual examination or final completion criteria. Supplied-route review retains its source/exposure rules. No extra ledger or copying of private purpose text into source-only worker packets is required.

Stage ordering governs new preparation. It must not block saving an already returned response, inspecting historical intake, mapping valid saved evidence, extending neutral source, authorized correction, or continuing an old valid assignment solely because scheduling policy changed. Existing negative outcomes and valid earlier reviews keep their established scientific meaning.

## E. Discover available reviewer routes: WF-07

At setup or resume, briefly establish which execution routes the host actually offers: a native isolated worker, a clean separate session/process through an already available supported tool, or an externally supplied reviewer return. Use exposed tools/help and existing host information. Do not infer unavailability from a missing tool name or assume a particular CLI/provider exists.

Record available, unavailable-with-evidence, or unknown in the existing run note or handoff. State the selected route and limitations before committing to independent dispatch. This is a short capability check, not a new calibration suite. Qualify an actual chosen configuration using the current scientific protocol and reuse it while its relevant properties remain unchanged.

Reuse an already verified route while its relevant configuration remains unchanged. Otherwise perform at most one bounded check of an available plausible route before declaring it unavailable; retain the observed result, or state unknown if a check cannot be made. The check can use an already configured and task-authorized clean reviewer session. Do not repeat unchanged probes or turn discovery into a provider search.

Respect the host's permissions and the user's authorization. Do not install runtimes, establish new accounts/services/billing, solicit another person, or use an unauthorized route merely to discover capability. If no verifiable route exists, continue useful primary work and retain an explicit reviewer handoff. Independence remains unfinished. No provider/model names or host-specific shell command belong in the universal algorithm.

## Implementation ownership and order

| Work package | Main maintained files | Completion target |
| --- | --- | --- |
| 1. Reproductions and no-op intake | `controller.py`, `contract.py` as needed, write-time acceptance, `assistance.py`; controller/partial-save tests | WF-04 including mixed returns, idempotency and useful drafts |
| 2. Grounding and boundaries | `stages.py`, shared target-source resolution, `review.py`, `proof_spans.py`, `assessment.py`, `work.py` | WF-01/WF-03; known mapping prerequisites and specific boundary recovery |
| 3. Narrow forward freshness | `bindings.py`, source-span comparison and assessment; neutral/evidence freshness tests | WF-02 positive/negative matrix and strict historical compatibility |
| 4. Current recovery and command policy | `acceptance.py`, new-write validation, controller, `cli.py`, stage policy | WF-05/WF-06; current successors, explicit exceptions, preserved old intake |
| 5. Instructions and integration | `SKILL.md`, controller/graph/primary/mapping/qualification references, generated guidance | WF-07 and one consistent documented sequence |

Start with portable reproductions from the observed state transitions. Packages 1 and 2 can be implemented independently with explicit interface ownership. Integrate package 3 against their final boundary semantics, then package 4. One coordinator reviews the interfaces and freezes one candidate before behavioral validation. Avoid having parallel implementers edit the same controller or validation section without agreement.

Update existing guidance in place. Keep the top-level skill short, put canonical rules in their existing references, and remove superseded statements. Do not increase the instruction-reading budget or require every worker to read the defect tracker. The coordinator owns capability, record preparation and recovery; checkers receive coherent mathematical assignments.

## Required validation and stopping conditions

| Scenario | Required result |
| --- | --- |
| Repeated untouched scaffolds, including blank comparisons | Intake is preserved; no check/observation/finding proliferation; exact missing authored work is identified. |
| Useful incomplete derivation or missing-source investigation | Reasoning and next action survive; unfinished work remains explicit; no completion is invented. |
| Mixed completed/draft/placeholder rows | Valid content is saved atomically when links are valid; omitted IDs are explicit; invalid placeholder links get one precise diagnostic. |
| Fresh request continuing an identical draft; same prose after changed inputs | Unchanged authorized content and guards create no new version and return existing references; changed inputs require specific recovery without silent rebinding. |
| Crash after intake but before scientific commit; replay of old terminal intake | Received intake resumes once without duplicate records; terminal receipts replay unchanged, including older receipts without new fields. |
| Empty direct-authoring rows versus historical import | New empty drafts/comparisons are rejected; compatible old records remain readable and importable. |
| Ready primary graph with missing dependency grounding | Routine review preparation names missing canonical grounding; valid grounding permits it; ready-subset includes real prerequisites. |
| Required reconstructed inference with source-backed premises | Honest supplied-route review remains available without a fabricated manuscript passage or exemption of the written proof. |
| Stale explicit proof selection on a shared PDF page | Boundary recovery is required without creating coverage tasks for neighboring text; other proof selections survive. |
| Absent legacy selectors; a newly marked source certificate after permitted grounding | Legacy absence retains whole-anchor coverage; the new certificate preserves only unchanged certified spans. Expanded extent or a dropped continuation remains blocking. |
| New marked binding plus provably consumed additive source link | Qualified existing work remains applicable without a new review; unchanged mathematics is not inferred from packet presence alone. |
| New source bytes, new passage outside consumed extent, changed conditions/route/supplier/final group, removed evidence, unknown marker | Affected work becomes stale or blocked; unrelated work remains current; no silent reuse. |
| Old unmarked bindings, historical branches and old blank drafts | No retrospective relabeling, digest rewrite or whole-store rejection; explicit local continuation remains possible. |
| Export/import and historical assessment across comparison-policy versions | Original pins/digests, new markers and old successor branches survive the round trip; old snapshots gain no retroactive credit; readers ignoring new markers stay conservative. |
| Successor to an already superseded ancestor, duplicate successors in one batch, and concurrent writers | New invalid branch is rejected with current recovery; authorized draft completion and independent opinions still work. |
| Retained response needs mapping, including partial mapping and stale historical receipt | Original bytes and judgments remain unchanged; current response guidance is authoritative; no automatic redispatch. |
| Malformed reviewer response and an authorized correction | Original return stays intact; a corrected return retains truthful author/continuity evidence; coordinator normalization cannot impersonate a reviewer correction. |
| Ordinary legacy preparation versus explicit stage preparation | Same stage eligibility; explicit exceptional investigation records purpose/limitations without waiving scientific rules. |
| Native workers absent, clean session available; all routes unavailable; route unknown | Capability is established from observable host evidence; useful work and truthful handoff are preserved in every case. |
| Stage 3 fails, then resumes | Frozen scientific snapshot and previous HTML remain intact; no scientific task is reopened. |

Use the existing controller, stages, reviewed-proof-spans, evidence/neutral-freshness, review-recovery, CLI, packaging and finalization suites. Add targeted transition tests where coverage is missing; do not write tests that only match revised prose. Run the full shared-core and both affected package suites once the candidate is frozen, plus relevant installer checks. Generated bundles must match the maintained source.

Replay the 15 prior preserved audits and the three new databases read-only, checking original hashes. Document expected changes to readiness and diagnostics separately from scientific outcomes. Historical bindings must not silently gain completion credit. Reproduce repairs only on copies. For the old renewal-heavy database, demonstrate recovery of affected terminal work without renewing its ancestors; do not claim the entire unfinished paper has been completed by mechanical replay.

Then run a bounded fresh behavioral exercise from raw manuscript/artifact inputs with an independent coordinator context. Include a fresh graph, one useful partial save, one completed proof unit, an independent returned judgment requiring exact mapping, one justified record correction, interruption/resume, reconciliation and HTML production. Do not supply the diagnosis, intended mathematical answer or the fixes' preferred choices to that evaluator. Examine its actual artifacts and identity trail afterward. Existing available execution configurations are sufficient; no particular model is a gate.

Measure saved substantive work, omitted placeholders, repeated unchanged attempts, current versus historical renewals, mapping recoveries, reviewer calls, reopened affected/unaffected tasks, and wall time where genuinely available. Raw record count is not mathematical productivity. If the same unresolved diagnostic repeats without a changed input or new evidence, retain the state and continue an independent useful task or hand off that blocker; do not prescribe another full audit pass. A genuine new issue gets a bounded investigation, not an automatic repair loop.

## Closure and release

Record each WF row's focused tests and behavioral evidence in the tracker. Zero blank-record proliferation, no ancestor-renewal amplification, no gratuitous rereview for mapping alone, and no lost unrelated completion are required. All source/condition/route-change negative tests must still block unsafe credit. A merely lower runtime or successful render is insufficient.

Freeze and identify the exact source/bundles used by every final validation. Report any candidate changes and rerun the affected checks before claiming closure. A full-paper performance claim additionally requires a comparable full-paper test with recorded scope and execution conditions; the bounded exercise cannot establish it. Keep formula presentation and harness-startup observations visible under their separate tracker rows.

When implementation is requested and validated, select an unused patch release, rebuild both shared bundles, run both skills' installation checks, install to the requested user-wide surfaces with backups, and commit/push the two repositories under the existing release workflow. Graphify receives the tested shared-core update, not a new audit workflow. The original planning task made no runtime, version, installation or publication change; implementation and release results are recorded separately in the validation note.

Planning review on October 3 checked the proposal against the maintained code and two independent focused reviews. Corrections covered reconstructed-route eligibility, source-review comparison metadata, conservative old-reader behavior, exact scaffold matching, unchanged-draft bindings, historical imports, supplied-route preparation and bounded capability checks. The validation scenarios above remain implementation requirements, not tests already passed by this proposal.
