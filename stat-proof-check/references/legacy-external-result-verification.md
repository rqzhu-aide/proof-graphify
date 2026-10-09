# Legacy v1.5: External Result Verification

Use this workflow whenever an external theorem, lemma, inequality, or technical
fact is load-bearing, whether or not the manuscript supplies an inline citation
command.

Store each external result once in
`audit/03_dependencies/DEPENDENCY_REGISTRY.json`. Use
`closure_contract_version: 4`. Lock the source record once, then record each
manuscript use separately. Ledger rows and direct-dependency records refer to
the external result's unique ID and to the exact `Dxxx` use ID.

Audit granularity and model-call granularity are separate here as well. Inspect
one unique current external theorem contract once, and assess all of its
current manuscript uses in one compact work packet when their complete
evidence fits. This saves repeated source reading but never merges per-use
applicability judgments.

## 1. Identify the exact result and every use

Record the exact fact needed at each manuscript line, the cited source, theorem
or equation number, edition or version, and whether the paper uses the result
directly or through a reformulation. Do not merge several uses merely because
they cite the same source. Different uses may require different prerequisites
or conclusion forms.

The uses may share one verification call, but the output must retain one exact
`Dxxx` row, prerequisite map, compatibility matrix, invoking-step set, status,
and issue set for each use. If the complete source contract or any use context
does not fit, split at use boundaries rather than omitting evidence.

Do not search only by topic. Retrieve the actual publication or authoritative
source containing the cited result.

## 2. Verify publication identity and lock the evidence

Resolve a DOI, arXiv identifier and version, official proceedings record, book
edition, or publisher record. Confirm title, authors, date, venue, and version
chronology when the theorem changed across versions.

For every inspected theorem statement, definition, prerequisite, correction, or
erratum, add a `source_evidence` row containing:

- `file`: the local evidence artifact;
- `sha256`: the current file hash;
- `locator`: the exact theorem, equation, section, and page location;
- `role`: the role supplied by that artifact.

A verified, conditional, gap, or incorrect external record requires current
source evidence. Hash the actual PDF, text, or authoritative downloaded
artifact, not a search-result page. Metadata verifies identity, not theorem
content. If the required full source is unavailable, use `status: unchecked`
and record a substantive `reason`.

Reuse the locked source inspection only while its evidence file hash, source
identity, version, theorem locator, and normalized theorem contract remain
current. A changed source or contract requires renewed inspection. Similar
wording, a stable citation key, or an unchanged result ID does not authorize
cross-revision reuse.

## 3. Record the external result contract

For each `external_results` record, provide `id`, `status`, `source_identity`,
`version`, `theorem_location`, `exact_statement`, `source_evidence`,
`issue_ids`, and `uses`. Add `reason` when the status is `unchecked`. When any
use has a load-bearing citation key, also provide `citation_bindings` and
`citation_binding_review`.

Read the exact theorem statement, definitions, assumptions, surrounding
conventions, and any corrections or errata. Normalize, without strengthening:

- mathematical objects, quantifiers, and domains;
- probability model and dependence structure;
- explicit and inherited hypotheses;
- meaning-determining definitions;
- finite-sample or asymptotic regime;
- pointwise or uniform scope;
- constants and normalization;
- regularity, measurability, compactness, or moment conditions;
- conclusion in the exact form stated.

Treat this normalized source record as the external dependency contract. Bind
each use to its exact conclusion and current contract hash. Source drift or a
contract-hash mismatch makes every dependent use stale.

### Bind bibliography identity separately

The union of `citation_bindings[].key` must equal the union of load-bearing
`uses[].citation_keys` exactly. Sort bindings by key and use one row per key.
Each binding contains `key`, `source_kind`, `file`, `start_line`, `end_line`,
span `sha256`, `role: bibliography_identity`, a substantive `locator`, the
parent `external_result_id`, and the current `external_identity_sha256`.

Use `source_kind: bibtex_entry` for one complete unique BibTeX entry,
`bibitem` for one complete unique `.bbl` or inline `thebibliography` item, and
`rendered_reference` only for an exact locked text transcription of the
rendered reference when the snapshot contains no machine-readable bibliography
entry for the key. The validator parses encoded BibTeX and only `bibitem`
commands inside a complete `thebibliography` environment. Any read or parse
error blocks validation. It rejects missing keys and duplicates within or
across the authoritative source snapshot, requires the locked span to equal
the complete entry, and requires every non-rendered binding to equal the
snapshot's unique authoritative location exactly: the same resolved file,
source kind, and span.

A rendered binding additionally contains `rendered_provenance` with
`authority: source_snapshot`, the current `source_snapshot_sha256`, the
rendered file's whole-file `source_file_sha256`, and a locked `key_mapping`
span with `role: rendered_reference_key_mapping`. Both the rendered file and
mapping file must be authoritative snapshot members. The mapping span contains
exactly one JSON object of this form:

```json
{
  "schema_version": 1,
  "citation_key": "smith2026",
  "rendered_reference": {
    "file": "audit/00_sources/project/rendered-references.txt",
    "start_line": 40,
    "end_line": 41,
    "sha256": "sha256-of-the-exact-rendered-reference-span"
  }
}
```

The validator mechanically requires the mapping's key, resolved file, complete
line span, and span hash to equal the binding. A free-text assertion or an
unrelated snapshot span is insufficient. A non-rendered binding with no unique
machine-readable entry is rejected. When none exists, rendered fallback is
accepted only with the authoritative snapshot key mapping above. A binding
that locks a copy of an entry outside the snapshot is rejected.
Every binding remains hash-locked to the exact external result identity. Add
`citation_binding_review` with `status: reviewed`, the exact sorted
`required_keys`, and substantive evidence after this check.
For a portable audit, pass every load-bearing `.bib` or `.bbl` file as the same
quoted `--additional-source` to doctor and scaffold so the binding targets the
locked audit copy.

Bibliography identity establishes attribution only. Keep it separate from the
external theorem statement, prerequisite map, compatibility matrix, and use
status. A bibliography defect can be `presentation_only`; it must not be used
as evidence that the theorem is mathematically inapplicable.

## 4. Map the source to each manuscript use

Each external `uses` row contains the internal-use fields
`dependent_unit`, `use_id`, `dependency_id`, `step_ids`, `needed_form`,
`dependency_conclusion`, `dependency_contract_sha256`, `compatibility_check`,
`compatibility_checks`, `status`, and `issue_ids`, plus `citation_keys` and
`prerequisite_map`.

Require `use_id` to equal the invoking ledger's `Dxxx` result use and
`dependency_id` to equal the parent external record ID. Require
`step_ids`, `needed_form`, `compatibility_check`, status, and issues to match the
invoking ledgers exactly. Require `citation_keys` to equal the load-bearing
citation dispositions whose `dependency_use_id` resolves to this use.

An exact named result may be load-bearing even when its statement has no
citation command. In that case, verify its source contract and application in
the same way and record `citation_keys: []`. If citation commands are present,
every load-bearing statement citation must map to the designated use and the
key set must match exactly. Missing or imprecise attribution alone is a
bibliographic or `presentation_only` issue. It is not a mathematical proof gap
when the exact external contract and its applicability have been verified.

For a proof-required manuscript result that only restates an external result,
use the explicit `external_restatement` workflow in
[proof-system-audit.md](proof-system-audit.md). The manuscript statement is
the object being checked, not a premise for itself. Its conclusion is supported
by the one designated external `Dxxx` use.

For every external prerequisite, add one `prerequisite_map` row with:

- `prerequisite`: the exact source requirement;
- `manuscript_evidence`: the exact manuscript fact claimed to satisfy it;
- `status`: `satisfied`, `not_satisfied`, `partial`, or `unclear`;
- `evidence_spans`: source-locked manuscript spans supporting the mapping;
- `source_evidence_spans`: locked spans of the actual external hypothesis,
  resolving into that result's current `source_evidence` files;
- `issue_ids`: every canonical issue raised by the mapping.

Do not use an empty map. If the theorem has no substantive prerequisites,
include an explicit domain and no-prerequisites row. A `satisfied` row requires
current evidence spans. Link every `not_satisfied`, `partial`, or `unclear` row
to the issues required by its effect.

For new challenge-contract-3 audits with text theorem evidence, a satisfied
mapping requires `source_evidence_spans`. Keep the external hypothesis and the
manuscript evidence distinct. Source-bound text is an authenticity check, not
a completeness check: inspect the actual theorem and its inherited conditions
before deciding the map covers everything. The challenge packet exposes the
actual text alongside the authored transcription. PDF evidence continues to
use its locked file hash and exact locator; inspect that document directly
instead of inventing textual line numbers. If essential theorem text is
unavailable, keep the source unchecked and its applications unresolved.

Within a batched check, share only the locked external contract and common
definitions. Test every manuscript use against its own source spans, needed
form, probability model, hypotheses, transformation, and downstream role.
Record a separate failure even when another use of the same theorem passes.

Also complete `compatibility_checks` with exactly one row for each of:

1. `quantifiers_and_domains`
2. `probability_model`
3. `hypotheses`
4. `definitions`
5. `conclusion`
6. `uniformity`
7. `regime`
8. `constant_dependencies`

Each compatibility row contains `aspect`, `status`, substantive `evidence`, and
`issue_ids`. Use only `passed`, `not_applicable`, `conditional`, `gap`,
`incorrect`, `unclear`, or `unchecked`. Check notation changes, rescaling,
conditioning, version changes, and every transformation from the external
statement to `needed_form`. A theorem can be correctly identified but
misapplied.

## 5. Derive and propagate status

Keep source availability separate from per-use applicability. A source record
may support one use exactly and fail to support another.

- Use `verified` only when the exact result and current source evidence were
  inspected.
- Use `unchecked` with a reason when the exact theorem or authoritative source
  was not inspected.
- Use `conditional`, `gap`, `incorrect`, or `unclear` only with the evidence and
  canonical issues that establish that state.

Let the complete prerequisite map, compatibility matrix, and source-record
status determine each use status. A verified use requires a verified source
record, satisfied prerequisites, and only passed or specifically
not-applicable compatibility rows. A missing prerequisite supports a gap. A
definite incompatibility supports incorrect. Partial support remains
conditional, ambiguity remains unclear, and unavailable source verification
remains unchecked.

Reconcile external uses one-to-one with all ledger direct external dependencies.
Reject missing, duplicate, unused, or stale uses; wrong invoking steps or
citation keys; mismatched needed forms; stale evidence hashes; and status or
issue disagreements. Propagate every nonverified use through the internal
dependency graph before assigning downstream unit and manuscript assessments.

## 6. Migrate closure-3 audit state

For a schema-5 audit reported as `closure_upgrade_required`, run:

```text
python "<skill-root>/scripts/proofcheck.py" migrate-closure --root "<audit-root>"
```

The command preserves a byte-exact closure-3 registry backup, advances only the
closure protocol, clears current citation bindings, marks required binding
reviews `pending`, marks the dependency registry unreviewed, and invalidates
prior finalization. Any experimental rows remain only in the legacy backup, so
the migration does not transfer a bibliography judgment. Complete and review
the bindings manually, refresh affected external contract hashes, and rerun the
normal closure and finalization gates.
