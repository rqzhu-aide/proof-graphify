# Three-stage execution

Use the script in this package. Do not mix v2 commands, schemas or qualification instructions into a v3 audit.

Preparation selects a batch of useful work, which may cover only part of the declared scope. The coordinator records returned work and uses the saved responses and status to select remaining assignments. A reused packet is the same pending assignment, not a request to examine the proof again. No separate stage checklist is needed.

Use a fresh output directory for each new batch, such as primary-01 followed by primary-02. Reuse an already exported pending assignment when its files are available. If an export reports OUTPUT_CONFLICT, export the saved packet to a fresh directory; no examination needs repeating. Another directory does not supply a missing response.

## Stage 1: prepare and examine

Capture evidence and examine coherent primary groups serially. During ordinary source reading, include meaningful footnote and remark claims by their mathematical role, within a coherent examination or as explicitly selected results. Routine graph children need no separate examination. A primary worker can draft needed items, connections and examinations from its sources without canonical IDs. After the group's return, the coordinator consolidates shared identities and registers meaningful proof units. See [phase1-drafts.md](phase1-drafts.md) for the procedure and optional consolidation helper. Direct authoring is also available when one examiner is doing the work.

Use stage1 add-unit for a written proof, or stage1 add-record for ordinary setup and shared intermediate results, following [graph-records.md](graph-records.md). These helpers generate the paired records and save source judgments under the actual examiner's identity; they do not manufacture mathematical verdicts. A selected intermediate derivation can belong to the owner's ordinary examination without another assignment. Finish its known consuming links before preparing that examination. If the supplied manuscript omits a proof, record and examine that omission without inventing a proof route.

The consuming proof owns examination of its important connections. If B uses A, B's examination checks whether A supplies what B needs; A's examination assesses A's own reasoning. Include known questions about shared assumptions, joint probability, limits or method interfaces in these assignments and their ordinary independent review. Use a separate cross-proof inspection only for a substantive question that does not fit an existing unit; its primary examination belongs in Stage 1. Record its actual review coverage rather than implying it received independent review through the standalone assignment.

~~~text
AUDIT stage1 add-unit audit.db --input unit.json
AUDIT stage1 status audit.db --audit AUDIT_ID
AUDIT stage1 prepare audit.db --audit AUDIT_ID --out work/primary-01
~~~

Read the returned packet and fill the generated response scaffold by row type: source_fidelity records the source comparison; check records mathematical reasoning and outcome. Keep each generated task_id and row type unchanged. The coordinator may map saved draft examinations into these rows when the consolidated question and evidence match what the worker examined. Preserve its reasoning, scope, limitations and actual reviewer identity; this is intake, not a second proof examination. A materially changed question needs only affected continuation or an explicit limitation. Leave optional coverage and advanced bookkeeping alone unless needed. For a composition, extent is whole_unit only when the whole assigned source question was examined, including an assessed manuscript omission; otherwise use partial and name unexamined material. No character ledger or one-result-per-edge certificate is needed.

Submit through the stage command using the actual packet, reviewer and response. Scripts generate the administrative envelope and a stable request ID; corrected response bytes get a new ID. An unchanged replay is a historical receipt, performs no new work, and may contain an old remaining-task list. When deciding what still needs doing after a replay, use current stage status or preparation. Manual envelopes are for recovery or advanced use.

~~~text
AUDIT stage1 examine audit.db --packet PACKET_ID --reviewer REVIEWER --response work/primary-01/response.json
~~~

After a coherent primary group's accepted work is current and satisfied with its assigned scope covered, select its corresponding independent task IDs for [Stage 2](#stage-2-review-and-integrate). Use the saved group result and current stage status when needed at this boundary, not after every record edit. An independent task's `ready` state does not require primary completion; `analysis_complete` means status derivation succeeded. Neither flag alone establishes this dispatch condition. Supply the exact source question, applicable setup and known proof passages, and defer an affected group while a known material edit to its consumed inputs remains pending.

When background review is supported, dispatch that stable group before continuing the next primary group serially; unrelated primary work need not finish first. Whole-unit `gap` or `refuted` outcomes can finish an examination. A source mismatch requires correcting the affected representation or disclosing the limitation. Finalize known shared identities in the assigned scope where practical, without a whole-graph stability pass. Later material changes renew only affected work under existing freshness rules. A blocking host can use sequential review.

To include a later meaningful registered claim in the same Full audit, use the current `audit.version` from `status`, not the database revision:

~~~text
AUDIT status audit.db --audit AUDIT_ID
AUDIT stage1 add-targets audit.db --audit AUDIT_ID --expected-version AUDIT_VERSION --target items:ITEM_ID
~~~

Repeat `--target` for other deliberately selected items. Read `ineffective_targets` for excluded claims; the command preserves exclusions and records no examination. Prepare the added question with its item focus. Unchanged local assignments remain usable; materially changed questions retain their normal freshness rules. A claim without a separate argument keeps its statement examination, including a possible gap or uncertainty. If several exact proof routes are available, select the intended argument or task. This operation adds scope without restarting the audit or waiting for unrelated reviewers.

## Stage 2: review and integrate

Commission independent review with the coordinator's effective provider and model in a separate source-only context. Native delegation may use established model inheritance without the primary conversation. For a fresh subprocess, use the host's same-model launch recipe from the actual root configuration, including overrides and configured reasoning settings when available. A different provider or model requires explicit user authorization. Preparation exports work and submission records returns; neither launches reviewers.

Trusted launch configuration or established native inheritance is sufficient; unavailable backend identity or optional effort metadata creates no new verification task. Record the configured and any returned identity in existing reviewer/run evidence. If returned metadata contradicts the intended model, preserve the actual identity and response without counting it as the required same-model review. Establish the known route once and reuse it while its configuration and capability are unchanged. Correct a concrete local launch error if possible; if that route is unavailable, retain the missing-review limitation and finish working output. Do not search unrelated CLIs or substitute the primary context to obtain completion.

Continue unfinished work in the same identified source-only reviewer context where supported. Otherwise use a fresh same-model context with that reviewer's source-only saved work. A replacement packet does not restore independence to a context that already read a primary opinion; report that exposure or use a fresh context without the exposed material. A generic most-recent-session flag does not establish that it resumes the reviewer rather than the coordinator.

~~~text
AUDIT stage2 prepare audit.db --audit AUDIT_ID --mode independent --out work/review-01
~~~

For several ready proofs, prefer a few disjoint reviewer groups running concurrently when the host permits. Roughly balance planned groups using known proof scope and length while keeping coherent units intact; sequential execution remains valid when concurrency is unavailable or unsuitable. Each group contains normal packets; no combined response is required:

~~~text
AUDIT stage2 prepare-group audit.db --audit AUDIT_ID --task REVIEW_TASK_A --task REVIEW_TASK_B --max-packets 3 --out work/reviewer-a
AUDIT stage2 prepare-group audit.db --audit AUDIT_ID --task REVIEW_TASK_C --exclude-group work/reviewer-a/group-index.json --out work/reviewer-b
~~~

If the user or host supplies a review time budget, include a return deadline in the launch brief, chosen from the assigned coherent proof units and known source scope, leaving time for intake and integration. Ask reviewers to save completed responses as they finish and, at the next available interaction near the deadline, return assessed work with actual coverage, named omissions and all concerns. A fully examined gap can finish without proof repair. The host manages the clock and any interruption; a prompt cannot guarantee a return during a long generation. At expiry, retain saved returns; continue only unexamined or changed assigned material within the remaining stage budget, otherwise disclose missing review and finish working output.

Give each reviewer its `reviewer-delivery.json` and the public worker files named there. Keep `group-index.json` and manifests private. Select only unfinished packet IDs using existing receipts/current status: a re-export retains historical membership and is not a new assignment. Use this brief with those IDs and the actual delivery path:

~~~text
Examine only packets PACKET_IDS in DELIVERY/reviewer-delivery.json. Follow its instructions and relevant role references. Fill those packets' generated response scaffolds using their worker guidance, and save each response at its assigned response_path. Announce each completed packet return as it is saved.
~~~

Add only needed execution context such as source access, return channel and an existing time budget; do not rewrite response fields or add a second scientific checklist. One reviewer can reuse its source context across packets. Without write access, return each filled scaffold through stdout or its individual return channel; the coordinator/host captures that original before aggregate formatting or clipping. A combined status message is only a notification, not the sole copy of completed work.

Provide relevant role references and matching original source passages or source-only images. Use the existing proof records and source navigation to supply the exact statement, applicable setup and known proof segments, including supplied continuations, from their actual files. Match differently numbered results by their statements and hypotheses, following [graph-records.md](graph-records.md). Preparation includes `source-navigation.json`, an optional index of public packet anchors with source identity and version, including prerequisites and continuations; no manual index preparation or validation is required. Keep primary judgments and suggested solutions out of source-only delivery. Reuse readable TeX/text and existing renders; for ambiguous consequential PDF symbols, provide the relevant original passage/image or retain that local limitation. No page sweep, PDF merging or per-proof image preparation or capability test is required.

Retain individual reviewer handles and collect each announced completed packet return through ordinary intake while other work continues. A worker can report one response saved while its process continues another packet; process exit is not required. File existence alone is not a completed-save signal. Partial, malformed or still-being-written returns supply no completion credit; preserve them and keep uncovered work pending. Prefer completion notifications or completion-aware waits. When polling is necessary, use bounded host status waits that permit prompt collection, not a guessed total-duration sleep. A quiet log or unchanged database does not establish a stalled reviewer or justify a replacement. If only blocking execution is supported, use it and retain that timing limitation.

For an individually announced saved response while other files may still be written, submit only that return:

~~~text
AUDIT stage2 review audit.db --packet PACKET_ID --reviewer REVIEWER --exposure source_only --response RESPONSE_PATH
~~~

Use `submit-group` when the group's existing response files are known completed saves. It attempts every member's path; missing files remain pending. Submit the saved group in a finite pass with the actual common reviewer and exposure:

~~~text
AUDIT stage2 submit-group audit.db --audit AUDIT_ID --group-index work/reviewer-a/group-index.json --reviewer REVIEWER --exposure source_only
~~~

This command records each usable return separately and continues past local missing or malformed files. It reuses saved outcomes after interruption, reports current remaining work and stops; it does not launch reviewers, repeat pending examinations or mark the audit complete. Use `--response PACKET_ID RESPONSE_PATH` for an explicitly chosen repaired or prior return; otherwise it uses the group's recorded response_path. `stage2 review` remains available for one response, and integration corrections use their existing commands. Preparation does not reserve tasks: exclude all already assigned groups (repeat `--exclude-group`) or task IDs. Repeated generic preparation can return an existing pending packet and must not trigger duplicate dispatch.

Use repeated `--task TASK_ID` to select the independent tasks corresponding to the completed primary scope. Single-packet `stage2 prepare` also accepts `--focus items:ITEM_ID`. Use a fresh output directory for each new group and exclude every already assigned group/task. Packet and byte limits bound preparation, not scientific obligations. Read `unassigned` reasons and remaining work; dispatch only returned nonempty assignments, leaving blocked or oversized work explicit. The helper does not retry scientific work automatically.

To re-export saved membership after an interrupted delivery, use a fresh output directory:

~~~text
AUDIT stage2 prepare-group audit.db --audit AUDIT_ID --resume-group work/reviewer-a/group-index.json --out work/reviewer-a-recovered
~~~

Omit selection and capacity options with `--resume-group`. Completed responses stay accepted; re-export is not a request to repeat them. A stale packet needs only its affected current assignment. Saved group membership does not silently change when new work becomes ready.

Report the actual reviewer and exposure, using the returned model identity when available rather than assuming it matches the coordinator. No calibration is required. Follow [evidence-and-verdicts.md](evidence-and-verdicts.md) for registered citations and newly needed evidence. Preserve the original returned bytes and submit through stage2 review. The neutral question and returned question_id identify the actual assignment; do not map a whole-theorem answer onto a hidden local task.

For a review actually performed in a separate source-only context:

~~~text
AUDIT stage2 review audit.db --packet PACKET_ID --reviewer REVIEWER --exposure source_only --response work/review-01/response.json
~~~

A saved response may still leave work unfinished. Read the receipt's reason and next action. A compromised review requires a fresh independent context, not another same-session examination. Ordinary preparation defers that attempt; after arranging a fresh reviewer, select the named task with stage2 prepare --mode independent --task TASK_ID. Other useful work can continue.

~~~text
AUDIT stage2 prepare audit.db --audit AUDIT_ID --mode integration --out work/integration-01
~~~

Integrate saved responses that are ready before asking for replacements. For each scaffold `task_id`, use the existing `reconciliation_candidates` bundle whose `integration_task_ids` contains that ID in `coordinator-guidance.json`. Compare its saved reasoning and conditions, preserving adverse concerns; do not infer another mapping from labels or item/argument prefixes. Scripts choose current pins; scientific decisions belong to the coordinator. Return only rows actually integrated, omitting undecided scaffold rows. A genuine `unresolved` disagreement needs an authored rationale; an untouched default or placeholder is not an integration. Submit with `stage2 integrate audit.db --packet PACKET_ID --reviewer REVIEWER --response RESPONSE_PATH`. Adopting a reviewer's finding is integration, not a new examination.

`ASSISTANCE_MAPPING` names a packet, task and exact target with no unique opinion bundle. Retain the saved packet and returns. If consumed inputs changed, prepare the affected current integration; otherwise report the local association limitation and continue unrelated work without unchanged inspection/preparation retries. This error supplies no scientific verdict. Export changed guidance to a fresh directory under the existing `OUTPUT_CONFLICT` rule.

For a new finding, use the optional finding example in worker-guidance.json and the response's top-level `findings` array. Keep its assigned target and related task IDs; write the concern, evidence and consequence. Integration supplies the current check references and returns `finding_refs`. Leave findings empty when there is nothing new. When integration changes the disposition of an existing finding, update that identified record as described in [reconciler.md](reconciler.md); a rationale alone does not change its status. A restriction on applicability does not by itself refute the conditional theorem.

If an otherwise usable response contains malformed or extra rows, the integration scaffold lists those preserved rows for local disposition. Explain how their concerns are incorporated, why they are outside scope, or why they add no scientific claim. Retain substantive unresolved concerns in the integration decision and findings. This does not create an independent verdict for an unperformed examination, and the original response remains unchanged.

The ordinary proof review includes its assigned cross-proof questions. Integrate those responses and any separately recorded inspections with their actual review coverage; there is no compulsory new sweep or fixed set of global jobs. A concern discovered during integration may finish as a finding or stated uncertainty, with its consequences reflected in the affected conclusions. It does not automatically reopen completed examinations. If a scientific correction changes the claim, conditions or evidence, examine the affected question before claiming support for the corrected version, or leave that support unresolved.

To revise a completed integration of unchanged, current examinations, use its coordinator task ID from `stage2 status audit.db --audit AUDIT_ID`:

~~~text
AUDIT stage2 prepare audit.db --audit AUDIT_ID --mode integration --correct --task TASK_ID --out work/integration-correction-01
~~~

Submit the corrected comparison through stage2 integrate as usual. Preparation supplies the current predecessor and preserves earlier decisions. For several requested corrections, handle the returned assigned_task_ids and deferred selections; an empty remaining_task_ids describes ordinary audit completion, not whether every requested correction was returned. After a concurrent correction, prepare the affected task again before submitting a different decision. Ordinary preparation leaves completed work alone.

~~~text
AUDIT stage2 finalize audit.db --audit AUDIT_ID --out frozen
~~~

Finalize when the planned examinations and integration are done, or remaining limitations prevent useful progress. Finalization creates a consistent snapshot and summary. Completed promised work can produce a release containing gaps or inconclusive/disputed conclusions, including assessed proof omissions or unavailable external sources. Missing promised examinations, review or supplied material produces working output. Counts cover registered work; if known meaningful in-scope review was never registered or performed, explain it in the existing scope notes and use `stage2 finalize ... --partial` to retain a working label. This does not require a second manuscript sweep. Never claim a working result is a completed Full audit.

## Stage 3: present

~~~text
AUDIT stage3 build frozen --out report.html
~~~

This command uses only the frozen bundle. Present the paper's statements, source passages and dependency uses separately from examination reasoning, findings and limitations. Administrative tracking stays in the saved audit artifacts. Use existing explanations; omit empty optional sections without requesting another summary or examination. Check displayed claims, source navigation, findings and limitations. A formula-display failure may fall back to readable literal source. Use existing diagnostics to distinguish faithful unsupported notation from a corrupted saved formula, such as a control character or unmatched brace. When captured evidence supports correcting the saved formula, use the existing affected-record correction path; an HTML-only patch does not correct the saved record. Preserve uncertain meaning as a limitation. A presentation-only compatibility fix uses the same frozen result and does not reopen unchanged proof judgments. Keep cosmetic prose polish in the presentation without changing scientific meaning; do not rewrite examined database records merely to improve wording. A scientific correction returns only affected work to the live audit and produces a new snapshot. A presentation retry uses the same scientific snapshot. If you start a temporary preview server solely for this delivery, retain its process or session handle and stop that specific server after verification, including a failed or denied check; leave pre-existing or user-managed services running.

## Stop and recover

After interruption or aggregate truncation, recover individual originals from their assigned paths or retained returns before selecting more work. Keep unchanged completed work; continue only missing, unexamined or materially changed questions under the normal freshness rules. A saved file, successful process or parseable response does not establish completion: use existing coverage and current remaining-work status. If no complete original survives, retain the affected limitation or continue only that missing work; do not reconstruct discarded reasoning or relaunch unrelated groups.

Read the first concrete error and correct only the affected field or response. Preserve the original returned bytes before making a corrected response. Usable primary rows can be submitted as a subset with their existing task IDs, row types and actual judgments; omit unanswered scaffold rows rather than filling defaults. For an already authored native primary response with separable malformed rows, optional `stage1 intake-response audit.db --packet PACKET_ID --response ORIGINAL --out CANDIDATE` writes a candidate subset and reports deferred originals with their JSON paths. It keeps the original file and database unchanged, supplies no scientific defaults, and leaves final acceptance to `stage1 examine`. Retain omitted adverse rows and findings linked to them for local intake repair or an explicit unresolved limitation. Accepting a subset does not integrate those deferred concerns. Keep separate reviewers' returns separate.

For example, `exposure` belongs in `stage2 review --exposure source_only`, not as an extra response field; the generated response has its own `exposure_report`. Correct that envelope mistake locally without removing adverse concerns, guessing outcomes or moving a finding to another target. An empty extra field may be removed in the corrected copy; preserve a nonempty concern in the supported reasoning/coverage fields and account for it during integration. Ordinary v3 review uses null qualification when no calibration exists; do not manufacture calibration or clear a genuine failed claim to obtain acceptance. A malformed return does not require resubmitting the batch.

If no new response or local correction is available, retain the pending assignment and exclude its task IDs with repeated --exclude-task while selecting other ready work. An unchanged replay ends that repeated submission, not all work. Read current status after replay; its saved remaining-task list may be historical. A reused packet can still accept a changed response answering its remaining question. Neither reuse nor an unrelated database revision is evidence of progress. When no useful work remains, finalize with the actual limitations.

For an accepted partial examination, the judgment is recorded but examination coverage remains partial. `omissions` names assigned supplied material still unexamined. Distinguish an actual unread or consequentially unreadable passage from a misclassified proof defect before continuing or correcting coverage. Continue the remaining material from the saved reasoning. If all assigned material was examined, preserve the assessed defect and mathematical outcome in reasoning/findings and explicitly correct coverage to `whole_unit` with empty `omissions` in the corrected response. Wording such as "None material" does not establish that correction. For independent review, submit the actual continuation or correction through `stage2 review` on the current prepared packet; a reused pending packet needs no invented supersession fields. For primary work, prepare the affected pending coherent composition and use its current partial predecessor in `renewal_candidates` to author a successor with explicit `supersedes`. This continuation preserves the task and source question; draft-only replacement does not replace a completed partial judgment.

When retrying a primary submission, distinguish an accepted prior submission from one rejected atomically. After acceptance, obtain committed finding IDs from `receipt.changed` entries with `collection == "findings"`, or inspect their current records. `record_map` maps tasks to checks/observations, not findings; an old packet without finding records does not establish their absence. For unchanged concerns, retain the records, cite their IDs in supported narrative and leave the new `findings` array empty. Finding IDs do not belong in `existing_check_refs`. A genuinely distinct concern may create a new finding. After atomic rejection, no findings were committed; retain the substantive adverse findings in the corrected submission. Preserve the original response in either case. Successful or explicit no-defect observations belong in examination reasoning, not new open findings. A changed finding disposition requires updating that identified record through the existing route in [reconciler.md](reconciler.md); a supported check or integration rationale alone does not resolve it.

Use `template --id` for a current record replacement and `stage1 correct-claim` for an ordinary claim with a direct exact specification, as described in [graph-records.md](graph-records.md). A graph correction during active review may change consumed inputs. Preserve the old return and prepare only the affected current question; changing its packet ID does not establish that new material was examined. `work extend` is for additional neutral source context on an unchanged independent question, not a general graph repair or primary extension command. Deliver the extended packet and obtain a response naming it. Reuse current reasoning and already examined passages; examine only material still unexamined or materially changed. Retain unresolved support when that examination cannot be done.

If the saved item is already corrected and only its direct specification is stale:

~~~text
AUDIT stage1 correct-claim audit.db --item itm_theorem_1 --expected-version CURRENT_VERSION --sync-current
~~~

If a targeted correction still cannot make the operation work, deliver the last valid database and findings with the failed operation stated. Do not keep retrying the same input. A failed HTML build leaves the database and frozen summary available.

Use --help rather than guessing flags. Additional detail in the database does not itself create more required science.
