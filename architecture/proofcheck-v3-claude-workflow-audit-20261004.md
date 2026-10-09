# Claude review of v3 workflow and responsibilities

Date: 2026-10-04.

Requested and reported model: `claude-opus-5-5`. Requested effort: `xhigh`.
Harness: installed Claude Code CLI, fresh nonpersistent session, read-only Read/Glob/Grep tools, no file-writing or command tools. The review was restricted to ordinary workflow and role instructions; detailed code/schema review and new tests were excluded.

Result: successful completion. No skill changes were made for this review. The suggestions below are Claude's recommendations, not approved implementation requirements. Changes to omitted-proof completion policy or review of late scientific concerns would need to preserve honest scope and actual examination; they should not be treated as merely cosmetic wording changes.

Original prompt and response metadata are preserved under `../tmp/claude-opus55-workflow-audit-20261004/`.

## Returned audit

I'm finished reading the eight references and checked one section of evidence-and-verdicts.md to settle a conflict. Here is the audit.

## Overall judgment

The workflow is mostly smooth and the roles are clear. The coordinator keeps the database, does the integration and makes the delivery. Checkers send back judgments. The skill says plainly that gaps, inconclusive results and unresolved disagreements can still finish an audit. The rules for retrying and recovering have a clear end point. Three wording problems are likely to cause rework or a misleading finish in practical tests. Nothing else needs to change before testing.

## Finding 1. A proof the paper leaves out can block a completed audit

**Where:** `references/database-audit.md:18` says a missing proof "remains visible as a source limitation, not an exclusion chosen to obtain completion." `references/controller-workflow.md:47` and `references/reporting-and-release.md:7` say missing required evidence produces working output. `references/evidence-and-verdicts.md:66` adds that an absent statement or passage "needs a source request." This conflicts with `SKILL.md:18`, which defines Full in terms of "written proofs," and `SKILL.md:12`, which says a manuscript gap is a finding.

**Consequence:** Statistics papers often say "proof omitted" or "similar to Lemma 2." A coordinator could treat each case as missing evidence. Then a Full audit can never be released, or the coordinator starts asking the user for sources or rebuilding proofs to clear the block. Both work against getting a finite, useful delivery.

**Smallest change:** Replace the second sentence of `database-audit.md:18` with: "A proof the manuscript does not provide is reported as a finding and does not by itself make the audit working. A source the manuscript relies on but that was not supplied is missing evidence."

## Finding 2. Cross-proof checking comes after review, with no clear owner or review path

**Where:** `references/controller-workflow.md:41` puts "Inspect interactions across the requested proofs" in Stage 2, after independent review and integration. Results go "with the relevant unit or an explicitly selected global examination." But `SKILL.md:18` says Full covers cross-proof questions "with actual independent review," and the stage summary at `SKILL.md:24-25` leaves them out of both stages.

**Consequence:** Suppose the coordinator notices a cross-proof concern while integrating. It can be read in two ways, and both loop:
- as a change to a unit that is already integrated, which reopens it under `graph-records.md:52`;
- as a new global examination, which needs its own primary, independent and integration round, and then another pass over interactions.

That is the late loop of repeated review you want to avoid.

**Smallest change:** Move that paragraph into Stage 1 and start it with "While planning primary work, inspect interactions...". Then add one sentence: "A cross-proof concern noticed later is recorded as a finding in the current integration and need not reopen integrated units."

## Finding 3. The integration guidance is hard to find, and one sentence invites re-examination

**Where (finding the guidance):** `SKILL.md` does not link `reconciler.md`, `coordinator-protocol.md` or `reporting-and-release.md`. The only links to them are in `probability-example.md:41`, `legacy-workflow.md:20` and `workspace-and-resume.md`, which the v3 path never loads. `controller-workflow.md:3` warns against mixing in v2 material, so a coordinator who finds these files through the legacy pages is in exactly that position. The file name "reconciler" also suggests a separate role, while `SKILL.md:28` gives integration to the coordinator.

**Where (the wording):** `reconciler.md:5` allows "a supported revision" and then says "Genuine changes to mathematics or conditions need the corresponding examination." A coordinator who adopts the independent reviewer's gap could read that as needing a new examination. Also, `controller-workflow.md:37` says "scientific decisions remain the author's," and `controller-workflow.md:9` uses "the author's" the same way. In a paper audit, "author" reads as the paper's author.

**Consequence:** A disagreement that is already settled can turn into a new assignment. The coordinator may also miss the guidance that unresolved disagreement is an acceptable outcome.

**Smallest change:**
- At `SKILL.md:28`, add: "See coordinator-protocol.md, reconciler.md and reporting-and-release.md."
- Replace the last sentence of `reconciler.md:5` with: "Choosing or revising a conclusion from saved reasoning is integration. Only a corrected claim, condition or evidence record needs its examination redone."
- In `controller-workflow.md:9` and `:37`, change "the author's" to "the coordinator's".

## What should stay unchanged

- The three-stage split, and integration by the coordinator without a further reviewer.
- "A manuscript gap is a finding; repairing its mathematics is not a new required task."
- Unresolved disagreement as a valid integrated finding, and keeping adverse concerns.
- Fixing envelopes, fields and mappings locally, with no repeated proof examination.
- Stopping after the same mechanical failure: keep the last valid result and disclose the limitation.
- A reused packet counting as the same pending assignment.
- No calibration, no per-edge or character ledgers, no fixed global jobs.
- Optional supplier, alias, proof_spans and advanced-structure fields that are clearly marked optional.
- Stage 3 working only from the frozen bundle, with rendering failures kept inside Stage 3.

I did not read `mathematical-checking.md`. I read only the "Missing source and restrictions" section of `evidence-and-verdicts.md`, to check Finding 1.
