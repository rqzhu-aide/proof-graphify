> Historical v2 reference retained from the baseline. Its workflow and completion requirements do not govern v3. Use [the v3 workflow](controller-workflow.md) and [graph authoring](graph-records.md).

# Legacy v1.5: Proof-System Audit

## 1. Build the inventory

Index every formal statement, definition, assumption, named event, important equation, proof range, label, and external theorem citation. Record exact locations and parser limitations. Snapshot every file in the static LaTeX include closure. Reconcile the generated inventory against custom theorem environments, macros, generated content, and the rendered document before marking it reviewed.

Inspect `proofcheck_source_check.py` items before bulk ledger extraction.
For association or boundary failures, follow
[source-layout-diagnostics.md](source-layout-diagnostics.md); source inspection
must distinguish an absent argument from an unsupported layout.

Keep reviewed depth, targets, scope, critical units, exclusions, parser limits,
and the few genuinely judgmental planning notes in canonical JSON. Do not
rewrite those facts into a separate authored plan. Generate the concise plan,
execution order, and dependency view after relevant canonical state changes:

```bash
python "<skill-root>/scripts/proofcheck.py" sync-views --root "<audit-root>"
```

`CHECK_PLAN.md`, `EXECUTION_ORDER.md`, and
`audit/03_dependencies/dependency_graph.md` are reviewed projections, not
alternate evidence sources. A blank scaffold or stale projection cannot
support completion.

Review proof associations in the parser's precedence order: explicit named
proof headers, strict navigation-only forwarding proofs, then physical
adjacency. Treat a forwarding association marked `review_required` as
unconfirmed until its target and bounded proof region agree with the rendered
source. Record a `proof_association` override for that confirmation. Use a
`proof_location` override only for a genuine parser miss, reviewed replacement,
or explicit rejection. A manual unit binds its reviewed inventory record with
`reviewed_unit_sha256`. To reject a parser proof candidate, set the reviewed
proof to null and the reviewed association to status `rejected`, method
`reviewed_rejection`, the same target, and an empty evidence-occurrence list.
Source-lock and rescan any changed span, reject overlaps, and reconcile its
exact reference occurrences, dependencies, and citations. Do not carry parser
evidence over from the old span.

A proof-required result may use external-restatement verification only through
one manifest `audit_scope.inventory_overrides` row with
`kind: external_restatement`, exact `unit_id`,
`external_dependency_use_id`, `statement_sha256` equal to the hash of the exact
reviewed formal statement span, substantive `reason`, and substantive
`evidence`. Keep `proof_required: true`, keep the unit in scope,
and require its reviewed proof to be null. The ledger source must use
`coverage_mode: external_restatement`, repeat the same
`external_dependency_use_id`, and cover exactly the locked statement span,
with no local proof lines. The designated `Dxxx` use must be one external
direct dependency of that unit and have exactly one matching registry use.
Every established or conditional conclusion must include it in its support
closure. The statement
does not serve as its own premise; the verified external use supplies the
conclusion. An absent override retains the ordinary local-proof rule.

Statement citation commands, when present, must all be exposed by statement
evidence and disposed to that designated external use. The registry
`citation_keys` must equal those keys exactly. When the statement has no
citation command, the exact set is empty. The source-locked override plus the
verified external contract and applicability supplies the audit evidence; an
empty citation-key list is not itself a proof gap.

The missing-associated-proof parser warning remains visible. Give its matching
`parser_warning_reviews` row disposition `external_restatement` only when it
names the same explicitly overridden unit, `affected_units` contains exactly
that unit, and the row provides substantive source-review evidence. No other
warning may use this disposition.

Treat the analyzer's proof region as canonical. Every automatic or reviewed
proof span must equal either a complete proof environment or one uniquely
targeted named-heading region with a recognized boundary. A replacement uses
the existing hash-bound `reviewed_manual` path and must preserve explicit
target and boundary review evidence. An arbitrary excerpt, convenient stopping
point, or unbounded appendix remainder is not a proof region.

Treat parser-generated internal-dependency candidates as advisory evidence that
must be reconciled, not as declared dependency uses. Candidates may come from
owned proof references, references in the formal statement, or a reference to a
uniquely labeled display-math block in a safely bounded unowned proof
derivation. For the last case, trace the bounded cross-reference path in the
source. Do not promote a reference across a heading, formal statement, owned
proof, duplicate label, ambiguous label, cycle, or unbounded source region.

Reconcile `cross_reference_reviews` one-to-one with the current broken-reference
and duplicate-label records. Orphan labels do not require review rows. Copy each
anomaly's `kind`, `key`, and exact `locations`; then record `status` as
`passed`, `defect`, or `inconclusive`, with substantive `evidence`, valid
`affected_units`, and canonical `issue_ids`. Do not retain a row for an anomaly
that no longer exists or omit a newly detected anomaly.

For each formal result, record:

- statement and scope;
- explicit and inherited assumptions;
- direct dependencies;
- downstream use sites;
- constants, rates, domains, and probability level;
- local-check status.

Also review the method-interface trigger. Inventory each load-bearing estimated object only when it meets the trigger in [legacy workflow step 4](legacy-workflow.md#4-close-dependencies-and-issues). Do not turn every oracle nuisance or routine computation into a software audit.

For `depth: full`, put every inventory unit with `proof_required: true` in
`audit_scope.in_scope_units`. Do not exclude a proof-required result because its
proof is absent or defective. Audit it and record the resulting gap, incorrect,
or unclear status. Source-layout rejection alone establishes none of these.
Continue to classify every non-proof-required unit as either
in scope or explicitly excluded.

For `depth: focused`, set a nonempty ordered `audit_scope.target_units` list.
Set `in_scope_units` to exactly those targets plus every transitive internal
prerequisite reached from their result-use records. A focused scope is invalid
if it omits a reachable prerequisite or includes an unrelated result.

## 2. Build the canonical dependency record

Use ledger `direct_dependencies` plus
`audit/03_dependencies/DEPENDENCY_REGISTRY.json` as the machine-readable
canonical record. Use `closure_contract_version: 4`. Treat the Markdown table
and graph as reviewed views, not alternate records.

Let deterministic tooling build repeated mirror fields, graph edges,
topological layers, and Markdown rows from canonical IDs and hashes. Human or
model review still supplies each needed form, dependency conclusion choice,
compatibility judgment and evidence, use status, and issue link. Generation
must fail or retain an unchecked state when any of those semantic inputs is
absent.

Build this record in two explicit stages. First normalize every in-scope unit
and create a reviewed scheduling map from source references and exact Cxxx
contracts. Before a dependent has a final primary ledger, its registry row may
have an empty `step_ids` list and `unchecked` status. This schedules work but
does not establish closure. Once the checker fixes the dependent's atomic step
plan, replace those temporary fields with the exact invoking steps, ledger
mirrors, status, and issue links. Regenerate the primary packet before final
compilation. Compilation and finalization require the complete binding.

Set the registry `review` object only after reviewing the complete current
assembly. Record:

- `status: reviewed`;
- `source_snapshot_sha256` equal to the manifest source snapshot;
- `inventory_sha256` equal to the current theorem inventory file hash;
- `in_scope_units` equal to the manifest list exactly;
- substantive `evidence` describing the review.

Any mismatch makes the registry stale. Rebind and recheck it after the source
snapshot, inventory, or scope changes.

Record every direct internal dependency exactly once in `internal_uses`. Use one
row per `(dependent_unit, use_id)` pair, with a `Dxxx` use ID that will match
the dependent ledger. In the final binding, each row must contain:

- `dependent_unit`, `use_id`, and `dependency_id`;
- the exact `dependency_conclusion_id` naming a `Cxxx` conclusion in the
  referenced ledger;
- `step_ids` equal to the exact invoking ledger-step set;
- `needed_form` equal to the ledger direct-dependency value;
- `dependency_conclusion` equal to that conclusion record's exact claim;
- `dependency_contract_sha256` equal to the hash of that conclusion's locked
  contract payload, including its applicability pointers;
- the same substantive `compatibility_check` used by the ledger;
- `compatibility_checks`, with exactly one row for each required aspect;
- the mechanically derived `status` and all canonical `issue_ids`.

Make every `Dxxx` identifier audit-globally unique across all internal and
external uses. Historical-current closure, issue reports, and resolution
archives carry bare use IDs and therefore cannot disambiguate a reused ID by
unit.

Use these eight compatibility aspects exactly:

1. `quantifiers_and_domains`
2. `probability_model`
3. `hypotheses`
4. `definitions`
5. `conclusion`
6. `uniformity`
7. `regime`
8. `constant_dependencies`

For each row, record `aspect`, `status`, substantive `evidence`, and
`issue_ids`. Use only `passed`, `not_applicable`, `conditional`, `gap`,
`incorrect`, `unclear`, or `unchecked`. Use `not_applicable` only with an exact
paper-specific reason. Link every nonclean finding to the issue records required
by its status. The use status must be the status derived from the referenced
result's availability and this complete matrix, and it must match the direct
ledger record.

Derive internal availability from the named conclusion's own contract fidelity,
argument status, statement status, and dependency closure. Do not borrow a
stronger status from another conclusion, and do not let the unit-level weakest
summary downgrade an independent conclusion. An established conclusion supplies
`verified` only when its contract, argument, and dependency closure are each
verified; any conditional component supplies at most `conditional`. A refuted
conclusion supplies `incorrect`. A `not_established` conclusion supplies `gap`,
including when the written argument is invalid but the conclusion is not
refuted. An unclear or unassessed conclusion supplies `unclear` or `unchecked`,
respectively. Never turn an invalid proof into a claim that the conclusion is
false.

Store each external theorem once in `external_results`, lock the inspected
source evidence, and record every manuscript use separately. Apply the exact
per-use rules in
[legacy-external-result-verification.md](legacy-external-result-verification.md). Reconcile
all internal and external use rows one-to-one with ledger direct dependencies,
invoking steps, citation dispositions, needed forms, statuses, and issues.
Reject unused or stale registry rows.

Inspect one current external theorem contract once and batch its current uses
in the same verification packet when complete evidence for all uses fits. The
output still contains a separate prerequisite map, compatibility matrix,
needed form, invoking-step set, status, and issue set for each `Dxxx` use.
Source-evidence or contract drift invalidates the shared inspection and every
affected use; do not transfer the old applicability judgments across revisions.

Build the internal graph from the reviewed use rows. Draw arrows from each
prerequisite to its dependent result. Reject unknown IDs, namespace collisions,
self-dependencies, duplicate uses, cycles, stale conclusion contract hashes,
and status mismatches. Propagate every nonverified dependency status and every
open or deferred load-bearing issue through the dependent closure. A downstream
result cannot remain verified after a load-bearing prerequisite becomes
conditional, gap, incorrect, unclear, or unchecked.

Perform this propagation for the exact affected `Cxxx` conclusion and its
transitive dependents. Reuse the root issue ID in the canonical dependency and
global records that represent the same finding; do not create a second issue
for a downstream consequence. If the dependency makes its invoking downstream
step conditional or failed, reuse the root ID only on that exact step recorded
by the canonical `Dxxx` edge. Do not attach it to an unrelated or otherwise
valid downstream step. Record the full effect in `affected_results`, conclusion
status, and dependency closure.

Reconcile the parser's proof-level reference occurrences and citation lists
against the registry and each ledger. Every reference occurrence has one exact
disposition keyed by its parser `occurrence_id`, target, and command.
Load-bearing formal-result occurrences must resolve through label ownership to
an internal `Dxxx` use, including equation labels owned by another result. Load-bearing
citations must resolve to external uses. Self-identification, navigation,
local-step, obligation-context, and non-load-bearing occurrences require their
specific evidence and links. Do not allow omission from a ledger or registry
to erase a source-declared dependency, and do not create a self-edge from a
header or navigation occurrence.

Also reconcile every parser candidate internal dependency through its exact
packet provenance paths. Each `candidate_dependency_paths` row has one stable
`CPxxx` ID and preserves the statement-only or transitive label-reference
chain that made the foreign result a candidate. Cover every candidate ID and
all of its path IDs exactly once in
`review.candidate_dependency_dispositions`. A load-bearing candidate must map
to its exact internal `Dxxx` registry use. A candidate without a registry edge
may be only `navigation` or `non_load_bearing`, with specific evidence that is
valid for every named path. Reject omitted, extra, or stale candidate paths and
ledger-only internal dependencies.

## 3. Maintain cross-cutting ledgers

Maintain only ledgers that the paper needs:

- **Assumptions:** statement, scope, use sites, strength needed, sufficiency.
- **Notation:** symbol, type, domain, first definition, later uses, drift.
- **Constants and rates:** allowed dependencies, fixed or changing, propagation.
- **Events:** definition, probability, conditioning, intersections, use sites.
- **External results:** exact theorem, source version, assumptions, mapped use.
- **Method interfaces:** population target, fitting laws, marginal relationships, evaluation sites, downstream uses, and separately scoped implementation evidence.

Update ledgers during local checking. Do not build exhaustive tables that never affect verification.

## 4. Check in dependency order

Trace target results backward to identify their exact prerequisite closure, then
check forward from base assumptions and prerequisite lemmas to their
dependents. A dependent unit is ready only after its internal prerequisites
have current ledgers and their exact conclusion contracts are known.

Generate the current dependency layers and execution order with `sync-views`.
Use one complete primary packet per ordinary unit. Short adjacent units in the
same ready layer may share one model call only when each unit's full statement,
proof, assumptions, and dependency contracts fit and the output keeps their
records separate. Every audit still checks every scoped unit. A priority label
may break ties between units in the same ready layer, but it never changes
coverage or moves a dependent ahead of an unchecked prerequisite.

Follow [challenge-protocol.md](challenge-protocol.md) for every in-scope unit.
Prioritization and batching cannot omit an independent check.

If a prerequisite fails, propagate that failure into every dependent's inputs
and verdict, but continue checking every in-scope dependent line by line. A
failed prerequisite prevents an unsupported verified verdict; it does not
remove the dependent from coverage or prevent discovery of independent flaws.

## 5. Run the global consistency pass

After local checks, complete `completion.global_consistency_pass.checks` with
exactly these eight aspects:

1. `source_resolution`
2. `assumption_and_definition_propagation`
3. `notation_domain_and_dimension`
4. `constants_and_rates`
5. `probability_events_and_conditioning`
6. `quantifiers_uniformity_and_regime`
7. `use_site_sufficiency`
8. `issue_propagation`

Each row has `aspect`, `status`, substantive `evidence`, `affected_units`, and
`issue_ids`. `affected_units` means defect impact: use `[]` for both lists on
`passed` or `not_applicable` rows; describe checked scope in `evidence`.
`defect` and `inconclusive` rows require affected in-scope units and canonical
issues. These are the only four statuses; aspects cannot repeat.
`not_applicable` requires evidence of absence from scope. `no_defect_found`
requires every row to be `passed` or specifically `not_applicable`.

Use the matrix to test statement versus proof conclusion, proof conclusion
versus later use, assumption propagation, notation and measure stability,
event intersections, failure-probability accumulation, hidden constants, rate
composition, quantifier order, uniformity, finite-sample versus asymptotic
scope, and issue propagation through the main chain. Keep method-interface
consistency in its canonical registry while reflecting any load-bearing result
impact in the relevant global rows.

When non-vacuity is not immediate, use the assumption-propagation and regime
rows to verify that all assumptions, domains, and regimes are jointly
realizable by an admissible model, parameter choice, sequence, or verified
existence result. Impossibility is a defect; unresolved realizability is
inconclusive. Keep proof validity separate from applicability.

Local validity does not imply global sufficiency.

## 6. Run the adversarial and independent passes

Try boundary and degenerate cases, including zero variance, singular matrices, smallest sample size, dimension one, boundary parameters, nonunique optimizers, heavy tails, empty events, equality cases, and failed regularity.

Remove or weaken each assumption and identify the first proof step that fails. Search for the smallest counterexample that distinguishes the claimed statement from the proved statement.

Use [domain-risk-checks.md](domain-risk-checks.md) only for domains actually present.


For every in-scope unit, follow [challenge-protocol.md](challenge-protocol.md).
That file is the sole authority for blinding, issue assessments, freshness,
reconciliation, and artifact binding. This system audit verifies that every
required independent check exists and passes its current gate.
## 7. Apply completion gates

A full audit is complete only when:

- every proof-required inventory unit is in scope and has one current,
  source-locked ledger, using a complete local proof or the exact
  `external_restatement` contract above;
- every physical line is covered exactly once;
- the closure registry is reviewed against the exact source snapshot, inventory
  hash, and in-scope unit set;
- every internal and external dependency use has one exact registry row, a
  complete compatibility record, a derived status, and current evidence;
- every internal use binds one exact dependency conclusion and current
  per-conclusion contract hash;
- every conclusion has one exact support closure and dependency-use set;
- cycles, stale contract hashes, unused records, and status mismatches are
  absent;
- the exact global consistency matrix is complete;
- every open or deferred load-bearing issue is propagated to the exact affected
  result set;
- every resolved issue preserves a validated historical archive and clean
  current resolution, and its historical-current unit, dependency-use,
  challenge, and deliverable closure is fully rechecked;
- every in-scope unit has a reconciled, issue-complete, fresh independent
  checker record;
- canonical issue and method-interface consistency passes;
- `PROGRESS.json` exactly matches the source snapshot, scope, unit statuses, and
  open S0 and S1 issue set;
- the canonical final report and every manifest-declared user-facing report
  exactly reconcile canonical unit, dependency, issue, scope, protocol, and
  overall-verdict fields;
- checked and unchecked scope is explicit.
- every generated plan, execution-order, and dependency Markdown view is a
  current deterministic projection of the canonical records.

Run `proofcheck.py finalize --root "<audit-root>"` after completing the final report and progress state. A passing result means the declared non-formal audit records passed the mechanical closure checks. It does not certify kernel-checked mathematical truth.
