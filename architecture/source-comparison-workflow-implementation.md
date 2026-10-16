# Source-comparison workflow: implementation and validation

Implemented 2026-10-12. The three Graphify instruction files match the approved [handoff](source-comparison-workflow-handoff.md) and [patch](source-comparison-workflow.patch) exactly. The change adds 79 words net. All three independent Sol 6.1 xhigh validation jobs completed within the user's ten-minute limit, with no necessary follow-up edits.

## What changed

- `proof-graphify/SKILL.md` now organizes existing authoring and comparison duties around coherent argument groups. Known relevant prerequisites and connections are assembled before the group's comparisons. Unrelated branches can continue independently. Draft display checks remain conditional and precede the affected comparisons.
- `proof-graphify/references/authoring.md` explicitly compares current saved scientific content while the source evidence remains available. Earlier source reading or a successful write does not establish a match.
- `proof-graphify/references/database.md` preserves actual success receipts and names misleading wrapper output as an example of uncertain recovery. Current state is inspected before repeating an uncertain write, not after every successful command.

The existing current-record correction and comparison examples remain intact. There is no new stage, required read-back, per-record check, whole-paper readiness gate or final sweep of unchanged comparisons. Proof Check, the shared core, runtime, schema, renderer and installed skills were unchanged by this implementation. Versions remain unchanged.

## Validation

The root applied the exact approved patch after checking applicability. Comparison against the saved baseline and validated candidate confirmed only the four intended instruction edits. Skill Creator's `quick_validate.py` returned `Skill is valid!`; the changed instruction files passed `git diff --check`.

Three fresh `gpt-6.1-sol` agents used `xhigh` reasoning. Each assignment was bounded to eight minutes and completed within four minutes:

| Job | Result |
| --- | --- |
| Implementation audit | Approved. The actual patch is byte-identical to the approved patch, and all three resulting documents match the validated candidate. Conditional preview, unresolved states, current-record corrections and evidence freshness remain intact. |
| Workflow exercise | Followed the revised skill through four continuation scenarios without reading the handoff, patch or earlier reviews. Finished only the affected group, retained completed work, accepted a clear receipt without repeating comparisons, inspected saved state after an ambiguous wrapper result, and kept an output-path failure in presentation. No new compulsory check was inferred. |
| Scientific rigor and scope | Approved. Saved records remain the comparison target; changed prerequisites, connections and source context still require affected review. Old seeds and receipts remain distinct from current scientific authority. Independent Proof Check examination remains required within its existing scope. |

The workflow exercise was a dry run of operational decisions, not an executed manuscript audit. Its commands were planned, not run. It noted that the instructions do not define every receipt field, but correctly handled the supplied receipt and inferred no additional checking duty. No further wording was added for that observation.

Hash checks covered 718 pre-existing repository files. Only the three intended instruction files and the handoff's implementation-status text changed. All pre-existing unrelated work was preserved. Separately, 225 runtime files matched their hashes from the prior public-CLI probe. That probe had already demonstrated unreviewed initialization, explicit comparisons, complete-record preservation, affected staleness and usable receipts. It was not repeated for unchanged runtime code, and no proof audit or renderer suite was rerun.

## Evidence and limits

Applied patch SHA-256: `503b3c81e5929225e10712b8ed51f84929631a103bb7a991365eb151d9aec0f7`.

This implementation's evidence is retained under `C:/Users/zrq/projects/skills/stat-paper-skills/tmp/source-comparison-implementation-20261012`:

- `before.json`, `before/`, `implementation.patch` and `verification.json` identify the baseline, exact changes and protected-file checks.
- `implementation-audit/REPORT.md`, `workflow-trial/REPORT.md` and `rigor-scope/REPORT.md` retain the independent reviews and scenario actions.

These checks establish faithful implementation and support the intended workflow interpretation. They do not measure an end-to-end time saving, certify a paper's mathematics or validate a separate visual migration. No installation, version bump, commit or push was performed.
