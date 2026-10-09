> Historical v2 reference retained from the baseline. Its workflow and completion requirements do not govern v3. Use [the v3 workflow](controller-workflow.md) and [graph authoring](graph-records.md).

# Release evaluation

Use `evals/release_eval.py` to compare actual proof-checking behavior across skill releases or against a direct expert-style review. This is an offline, standard-library harness. It does not call a model, assign mathematical rationale scores, purchase anything, or estimate financial cost.

Run this maintenance workflow from the development repository. The ordinary
installed skill omits `evals/` and `tests/`; neither is needed for a paper audit.

This workflow is separate from the [reviewer qualification](database-qualification.md) required during an ordinary database audit. Legacy v1.5 folders use the [balanced two-canary smoke test](checker-calibration.md). Do not run the whole release pilot for every paper. Passing qualification or a canary smoke test does not establish research-level competence.

## Pilot and review status

The initial corpus has eight correct/flawed matched pairs and two short theorem chains, with twenty conclusions in eighteen problems. The historical v1 catalog assigns nine problems to each split. New preparations use `evals/prospective-allocation-v2.json`: q-52fd moves prospectively to development because the direct-review smoke exposed it, leaving ten development and eight candidate held-out problems. The historical catalog, keys, runs, and scores stay unchanged. Entire correct/flawed pairs stay together.

The exposure file records known exposure, including the already-development chain q-ab60. It is not proof that every unlisted case is untouched. Record later checking/tuning exposures before another prospective allocation is frozen. A prepared packet alone does not prove model exposure; completed responses and the actual workflow supply that evidence. Replace the exposed held-out chain with unseen, independently reviewed material before a confirmatory comparison. This release supplies no replacement expert-reviewed corpus or measured performance claim.

The pairs cover maxima and uniformity, expectation convergence, adaptive concentration, boundary transformations, matrix invertibility, joint rate regimes, admissibility of lower-bound alternatives, and routine algebra versus missing joint assumptions. The chains distinguish a correct lemma used outside its assumptions from an invalid submitted proof whose conclusion is nevertheless true.

Every shipped key is **provisional, pending independent statistical-theory expert review**. The implementation assistant authored and self-reviewed the candidate arguments; no human expert adjudication has occurred. The harness reports this limitation even when labels and independently supplied rationale scores agree. Do not describe the pilot as validated expert ground truth until a real expert has reviewed the keys and recorded that review.

`evals/catalog.json`, `evals/keys/`, the rubric files, and prospective allocation are evaluator-only. The source problems use opaque IDs. Prepared checker packets omit case identities, pair membership, variants, splits, candidate judgments, and grading rationales. Their filenames are opaque hashes. Supply only the selected packet to a fresh checking context. A context that has read keys or another configuration's responses is not a blind checker.

## Prepare a configuration

Create a configuration JSON outside the skill directory. Record what will actually run, including model and reasoning settings when applicable. Identifiers are declarations, not automatic runtime identity verification.

```json
{
  "role": "revised",
  "configuration_id": "revised-pilot-001",
  "checker_id": "actual-fresh-checker-context-id",
  "description": "Actual model, reasoning setting, and workflow used for this run",
  "model": "actual model name",
  "reasoning_effort": "actual setting",
  "implementation_path": "absolute path to the evaluated stat-proof-check directory"
}
```

Roles are `baseline`, `current`, `revised`, and `plain_expert`. For a skill run, supply `implementation_path` so preparation fingerprints `SKILL.md`, all role references and scripts, templates, canaries, and agent configuration. Record any additional instructions, example records, or scripts actually supplied in configuration `supplied_files`, a list of file paths. For a direct review, use `plain_expert`, set `implementation_path` to `null`, and supply the actual prompt file through `supplied_files`. Empty lists are incomplete provenance, not evidence that versions match. The hashes identify available and supplied bytes; they do not prove that the checker followed them. New records reject changes to prepared implementation, supplied files, or evaluator/rubric bytes.

Prepare from the repository root, using the shared Python installation:

```text
python stat-proof-check/evals/release_eval.py prepare --configuration configuration.json --split development --seed 20260904 --run-dir evaluation-runs/revised-001
```

Use a new run directory each time. `--case-id` may be repeated for a bounded subset, but each selected case must belong to the chosen split. Preserve the seed and case selection for comparisons. The seed controls deterministic packet order and identifiers, not model randomness. If the model exposes a seed, record its actual value separately in the configuration.

The run directory contains a coordinator `run.json` and checker-visible `packets/`. Share individual packet files, not the coordinator manifest or evaluation source tree. Use the evaluated skill's ordinary workflow for skill configurations, including any required audit work; return the requested evaluation response after that work. For a direct-review comparison, use the stated expert-style prompt. The harness alone does not execute or prove compliance with either workflow.

Each response supplies one record per listed conclusion: argument status, statement status, root defect lines, justification, and optional counterexample and repair. `established` means established by the submitted derivation. A newly invented replacement proof cannot turn an invalid submitted proof into a successful audited argument. Routine explicitly invoked algebra may be reconstructed with its conditions. Scorer v2 separately reports false establishment of a candidate-known false statement, even if the submitted argument is labeled `gap`, and acceptance of a defective written proof. An `established` statement with any argument status other than `valid` is an inconsistent establishment; the evaluator retains and reports this mistaken combination instead of dropping the response.

The original rationale rubric and candidate keys remain unchanged. `evals/rubric-v2.json` records the new scoring dimensions and pending conditional-versus-gap and root-versus-use-site conventions. Obtain independent statistical-theory adjudication before interpreting those conventions as checker errors. Records without a scorer version retain v1 scores; the unmeasured new serious-error fields are `null`. Mixed scorer versions cannot be compared as equivalent measures. Preserve historical records and prepare new runs for a revised comparison.

## Independently assess and record the response

Fix the checker response before revealing keys to an assessor. Then generate a bound assessment draft:

```text
python stat-proof-check/evals/release_eval.py assessment-template --response response.json --output assessment.json
```

Give a separately declared assessor the problem, fixed response, candidate key, and evaluator rubric. The assessor completes every rationale score and explains it. Record `fresh_context_same_model`, `different_model`, or `independent_human`, using the strongest honest description of the actual arrangement. A second identifier alone does not establish genuine independence.

Rationale scores are:

- **0:** incorrect, unrelated, or based on a false mathematical principle, even if the final labels happen to be right.
- **1:** identifies the right concern but omits decisive justification or a necessary side condition.
- **2:** provides a sound source-backed argument for the judgment under the exact assumptions.

Counterexample and repair scores use the separate rubric when assessed; leave them `null` when not assessed. A valid counterexample must satisfy the hypotheses and violate the conclusion. A valid repair must state any stronger assumption, narrower regime, changed guarantee, and downstream recheck. If the assessor disputes the candidate key, preserve the disagreement, obtain expert review, revise the key explicitly, and prepare a new run. Do not silently change ground truth underneath an existing record.

The assessor's `response_sha256` binds the exact response file bytes. Correct labels with the explanation that pointwise convergence controls every growing maximum must receive rationale score zero. This is the explicit regression against label-only calibration.

```text
python stat-proof-check/evals/release_eval.py record --run-dir evaluation-runs/revised-001 --response response.json --assessment assessment.json
```

Recording requires a separate declared assessor, completed rationale scores, and matching response and packet identities. It copies the submitted judgments and assessments into a no-overwrite record. Use repeatable `--workflow-evidence-file` arguments for preserved operation logs, audit finalization records, or other evidence of the workflow actually executed. Their paths and hashes are recorded, and absent attachments remain explicit. Preserve those files with the run. Attachments and declared identities do not attest workflow compliance or establish that the assessor's mathematics is correct.

## Usage and comparison

When actual usage observations are available, add `--usage-file` for the corresponding `RUN_USAGE.json` from `proofcheck_usage.py`. Multiple files may be linked. Add `--wall-seconds` only for an actually measured case duration, including the same workflow stages across configurations. Do not substitute the harness's fast JSON-processing time for proof-checking time.

New records preserve the usage file path, exact UTF-8 source content, hash, and validated events. Summaries verify the captured content and reject edited events or conflicting copies of an event. Identical source files count once even at different paths. Cumulative log snapshots contribute the union of their events, so an earlier call is counted once. Event IDs must uniquely identify calls within the evaluation run, for example `audit-run-id:call-id`, and remain stable across snapshots. Separate genuine calls need separate identities. An old record without captured content is counted only when its original source can still be verified; otherwise it is listed as unverifiable and excluded from totals.

Token sources retain `measured`, `reported`, and `unavailable`. Keep input, cached input, output, and reasoning counters separate and describe the provider semantics in the event notes: cached input may be included in input, and reasoning may be included in output, so do not add all four into a total. Each event records that call's counters, not a repeated cumulative provider counter. Missing fields remain `null`, and partial sums report how many events had values. Summed case durations may overlap under concurrency and are not total elapsed run time. No dollar cost is inferred.

```text
python stat-proof-check/evals/release_eval.py summary --run-dir evaluation-runs/revised-001 --output revised-summary.json
python stat-proof-check/evals/release_eval.py compare --run-dir evaluation-runs/baseline-001 --run-dir evaluation-runs/revised-001 --output comparison.json
```

Summaries retain counts and denominators for labels, supported labels, supported defect detection, false alarms, and independently assigned rationale scores. Root-line localization reports true-positive, predicted, and candidate defect-line counts, so flagging every line is visible. Serious false verifications, false refutations, and correct labels with unsupported rationales remain individually listed. Unrecorded packets are explicit and are not silently counted as successes or failures.

Comparison reports the overlap in prepared and completed cases and preserves each configuration's denominators. Matched cases must use identical problem and candidate-key bytes. Use the same case selection, split, settings, and execution conditions for an interpretable comparison. The tool does not declare a winner, infer significance, or treat this small pilot as a soundness guarantee.

Run `python -m unittest discover -s stat-proof-check/tests -p test_release_evals.py` to verify the harness. These tests exercise scoring and record behavior with synthetic responses; their success is not a measurement of a live checker's mathematical performance.
