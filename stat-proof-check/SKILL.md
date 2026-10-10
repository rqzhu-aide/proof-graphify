---
name: stat-proof-check
metadata:
  version: "3.2.1"
description: Rigorous, non-formal proof audits from manuscript and supplement sources to a graph database, findings and an Archify HTML report. Use only when explicitly invoked as $stat-proof-check.
---

# Statistical proof check, version 3

Run when the user explicitly invokes $stat-proof-check. Continue an active audit within its declared scope.

Build the evidence-backed graph, examine important connections and their combined reasoning, correct material database errors, then deliver findings and the report. Assess supplied reasoning using the available evidence and mathematical knowledge. A manuscript gap or unresolved question is a finding; constructing a missing proof, repairing the mathematics or finding a counterexample is not required.

## Choose the scope

- Triage maps arguments, suspected defects and unavailable evidence. It makes no completed proof-audit claim.
- Focused examines the selected exact results and necessary prerequisites, with actual independent review.
- Full accounts for the manuscript and supplied supplements. Independently review the in-scope proof examinations, including their important connections to other results. Report any additional cross-proof inspection at its actual review level.

Record omissions and source limits. Prioritizing results does not silently narrow Full scope. This is a non-formal examination, not a theorem-certification service.

## Three stages

1. Prepare evidence and examine. Assign coherent proof groups with stable source evidence. Workers may independently draft the needed items, connections and primary examinations. The coordinator consolidates their returns into shared graph records and saves the examinations, including important uses of other results.
2. Review and integrate. Obtain independent examinations of that work, compare reasoning, retain material disagreements, correct the affected database records, summarize coverage and findings, and freeze the results.
3. Present. Build the Archify HTML from that frozen result, showing the paper's mathematics separately from examination reasoning, findings and limitations. Keep administrative tracking in the saved audit artifacts; missing optional explanatory prose creates no new examination or writing task.

The coordinator maintains the shared database and carries the audit through delivery; it can also do the primary examination or delegate it. Independent reviewers return judgments from a separate review context. Integration belongs to the coordinator and does not require another reviewer.

Local Phase 1 drafts need no shared database IDs. After a group's returns arrive, the coordinator merges the same source claim in the same context, keeps separate consuming uses and returned opinions, and registers the shared records. Workers need not negotiate who creates a shared equation. Unavailable returns remain explicit limitations; they do not hold up unrelated groups. See [phase1-drafts.md](references/phase1-drafts.md).

Use [database-audit.md](references/database-audit.md) to start and [controller-workflow.md](references/controller-workflow.md) for the commands. A ready proof can proceed while an unrelated source is unavailable. No perfect whole-database gate is required.

Use [coordinator-protocol.md](references/coordinator-protocol.md) for assignment ownership, [reconciler.md](references/reconciler.md) for integration and [reporting-and-release.md](references/reporting-and-release.md) for delivery.

The ordinary examination is a written proof or meaningful subsection. It includes important applications, joint inference, cases, local conditions and composition. Routine graph detail creates no new compulsory examination. Save separate local outcomes only when they matter.

Examination coverage and mathematical outcome are separate. Whole-unit scope reflects the assigned material actually examined; partial examinations name unexamined material. An assessed proof omission, inconclusive conclusion or integrated disagreement can finish an examination without establishing the theorem. Unexamined supplied material remains unfinished. See [evidence-and-verdicts.md](references/evidence-and-verdicts.md) for these decision boundaries.

## Scientific work

Read exact statements, applicable setup, full proofs, continuations, supplements and relevant macros. Check consequential PDF symbols visually. Preserve source excerpts and file/page locations. Match differently numbered results by their actual claims and hypotheses.

Show decisive mathematical reasoning, hypotheses and limitations. Preserve AND premises, alternative proof routes and local assumptions. A valid supplier application does not by itself validate the joint inference. A failed written proof does not refute its theorem, and an alternative proof does not erase its defect.

A theorem's hypotheses belong in its statement, including clear references to named assumptions whose passages are supplied as context. Reuse those assumptions; ordinary hypotheses need no duplicate private scope. Private scopes are for genuine local assumptions or cases.

For a non-trivial use of an external result, use available tools to identify and inspect its source, record an external-result node, and check applicability. Routine facts need no separate lookup or node. An unavailable source can finish as an inconclusive limitation; do not expand the work into auditing the external paper. See [external-result-verification.md](references/external-result-verification.md).

Do not use simulations, numerical searches or empirical experiments as proof evidence. Source extraction, database checks and software tests are ordinary tooling.

Use [mathematical-checking.md](references/mathematical-checking.md) and [evidence-and-verdicts.md](references/evidence-and-verdicts.md) for scientific standards. Load only relevant portions of [domain-risk-checks.md](references/domain-risk-checks.md).

## Assignment and recovery

Checkers receive the exact source-backed question, its conditions and sufficient passages. For ordinary written-proof review, independent checkers do not receive primary judgments or suggested solutions. Use [primary-checker.md](references/primary-checker.md) or [independent-checker.md](references/independent-checker.md) with the generated assignment.

Scripts generate bookkeeping fields and preserve original responses. The coordinator submits usable returned work and handles local field or mapping corrections, keeping omitted work and adverse concerns explicit. Use generated assignment identities rather than inferred record names. Do not commission another proof examination solely to fix its envelope.

For several ready proofs, the coordinator may prepare a few distinct reviewer groups. Each reviewer can handle several source-only packets and return each separately. Exclude work already assigned to another group; a reused packet is the same assignment. Continue unfinished required work from saved reasoning; changed questions or needed evidence renew only affected examination. Unrelated discoveries do not expand the assignment.

Diagnose a failed operation, correct its smallest relevant cause, and retry affected work. If no new response or local correction is available, defer that assignment and continue other ready work. If the same mechanical failure remains, preserve the last valid result and disclose the limitation. Do not repeat unchanged calls or restart the paper. Further scientific review needs a concrete question or changed evidence.

Deliver the database, frozen summary and HTML links with the actual review level and limitations. A rendering failure stays in Stage 3. Historical v2 stores use their compatible readers; do not relabel them as completed v3 audits.
