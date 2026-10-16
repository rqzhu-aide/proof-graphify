# Graphify runtime revision implementation

Implemented and independently validated on 2026-10-13. This implements S1/S2 and H1/H2 from the [targeted revision plan](graphify-runtime-revision-plan.md). No additional paper check, review stage, database API or bookkeeping artifact was introduced.

## Changes

The two skill-reference changes are in [authoring.md](../proof-graphify/references/authoring.md) and [database.md](../proof-graphify/references/database.md):

- The escaping-repair example now edits an existing canonical full-record correction batch. It preserves the initialized database even before its first comparison and reuses exact current records/context when available. The serializer remains optional, and pre-initialization seed repair remains supported.
- Reviewers return directly usable native comparison batches. A shared note can cover targets for which it is accurate, while different findings stay separate. Stale pending responses stay unchanged; any new coordinator judgment applies to current affected context and carries the coordinator's identity. Required independent review remains required.
- Known successful writes are retained. A missing receipt or error can leave the outcome uncertain, so existing saved-state inspection applies before retrying that write. Normal successful writes gain no extra check. Two unconditional retrieval clauses now retrieve only missing current context.

The separately owned harness change is in [run-test.sh](C:/Users/zrq/projects/skills/_testing-center/run-test.sh), limited to `write_reviewer_recipe` and `cmd_launch`:

- Graphify main and followup use the run-local `test-id` to select optional fresh reviewer transport with a neutral bounded assignment. The harness no longer imposes a second source-only reconstruction or generated question scaffolds on ordinary Graphify.
- Unavailable launcher guidance discourages rebuilding shells/profiles inside a paper task. An available alternate route must preserve configured provider/model/effort and freshness. Optional unavailability is disclosed; review required by the user or skill remains unfulfilled without a permitted route. Ordinary path correction remains allowed.
- Legacy Proof Check and other-skill contracts, configured arguments, fresh reviewers, parent continuation, capture guards, separate streams and exit behavior remain intact. Existing generated recipes and retained run artifacts were not rewritten.

## Independent validation

Three `gpt-6.1-sol` / `xhigh` jobs reviewed the actual implementation, each finishing within ten minutes.

| Area | Evidence | Result |
|---|---|---|
| Harness | 223 isolated fake-CLI assertions, plus three explicit-permission-denial capture cases | Passed. Includes main/followup identity, explicit required-review precedence, provider/model/effort, fresh sessions, unchanged legacy output, paths with spaces, captures and nonzero exits. [Report](../../tmp/graphify-runtime-implementation-20261013/harness/review.md). |
| Skill instructions and storage contract | Eight focused probes plus three additional examples | Passed. Executed the exact serializer from the edited reference; preserved optional fields/snapshot/history; submitted grouped and distinct native findings; recovered from simulated receipt loss without replay. [Report](../../tmp/graphify-runtime-implementation-20261013/skill/review.md). |
| Integrated scope and burden | Compared 723 maintained baseline files and reviewed the actual contracts | Approved. Exactly the two intended reference files changed; the other 721 were unchanged before adding this maintenance report and updating the plan status. No missing maintained files. Production harness independently matched the tested candidate. [Report](../../tmp/graphify-runtime-implementation-20261013/scope/report.md). |

Initial harness inspection found a leftover wrong-argument message describing a source-only directory. It was corrected before the full actual-candidate matrix. The final matrix and published file share the same hash; unchanged checks were not rerun on the identical published copy. The reference diff also passes `git diff --check`.

Baseline bytes and incremental patches are retained under `../../tmp/graphify-runtime-implementation-20261013/`. They distinguish these edits from the substantial pre-existing work at repository HEAD `e11bc293cd111e9f3d4f9c52af51a945956f0694`.

Final SHA-256 identities:

| File | SHA-256 |
|---|---|
| authoring.md | `33b0592d4e70b0502a1ff306e7778a8454e5f872dfd8a67529c41a6d59d45089` |
| database.md | `f6d647f95ea0877ce9a9937cb4a5bd5109fbac9eec0de6920a4075905c1902b1` |
| run-test.sh | `4eb45bc7336ca3c2a8915fcfa571d08f3ea0d079269320cb7b0def648180cd6a` |

The harness was published through a guarded copy: its original hash had to match `0aadd7b45dc854b5af4fbd572cdb9ab9d23ed991fed310f2387cef9cca476645`, and the copied bytes had to match the validated candidate.

## Scope and limits

The two references grew by 143 words combined, replacing existing examples and paragraphs. That clarification adds no required operation. Harness code grew by 25 lines to keep Graphify and legacy contracts separate. The shared core, database CLI, renderer, Proof Check behavior and package manifests remain unchanged. Graphify stays 3.2.5; Proof Check/core stay 3.2.4. Installed copies were not synchronized, and no commit or push was made.

The multi-file comparison command, earlier low-level optimizations and post-delivery host-lifetime investigation remain deferred. No timeout, regex-based process termination, automatic snapshot rebinding, history deduplication or additional visual check was added.

All executable validation used disposable fixtures or fake CLIs with existing shared runtimes. No live paper/model run or testing-center prep/followup/harvest was performed. These checks support the implementation's contracts and preserved behavior; they do not establish future agent adherence, whole-paper scientific quality or measured end-to-end time savings.
