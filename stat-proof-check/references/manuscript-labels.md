# Legacy v1.5: Reviewed manuscript labels

Result numbering is optional presentation metadata in the audit manifest's
`report_context.manuscript_labels`. Use it when a printed PDF supplies the
number that ordinary TeX source does not contain. A literal, unambiguous numbered
heading in locked source takes precedence. Without either source of numbering,
the report keeps the result kind, title or description, and physical source
location. TeX labels, `.aux` hints, extraction order, and inventory counters
never authenticate a manuscript number.

During the existing source review, actually compare the statement and heading
context in the PDF with the locked source. Record the observed label, physical
PDF page, and a short note identifying what matched. Comparing filenames or
hashes alone is insufficient. Do not claim this comparison occurred unless it
did. The renderer validates the recorded review's binding and freshness; it
cannot establish whether its author's observation is correct. This is display
evidence and creates no mathematical verdict or new review requirement.

Preserve the reviewed companion PDF at an audit-relative path, for example
`audit/00_sources/display-evidence/manuscript.pdf`, outside the copied TeX project.
Do not add it to the TeX source snapshot or discovery closure. Its byte hash is
recorded separately. Include this relative path when moving or delivering the
audit; paths escaping the audit, including redirected symlinks, are rejected.
No TeX execution, PDF text extraction, or package installation is needed for
report rendering.

The complete version 1 structure is below. Replace the placeholder IDs, hashes,
coordinates, label, page, and review note with the actual reviewed evidence.
The source snapshot hash comes from the manifest. Exact result IDs and locked
statement anchors are available in the report projection or its technical
records. Anchor paths are relative to the audit root, with forward slashes.

```json
{
  "report_context": {
    "manuscript_labels": {
      "version": 1,
      "source_snapshot_sha256": "<current manifest source_snapshot.sha256>",
      "pdf": {
        "path": "audit/00_sources/display-evidence/manuscript.pdf",
        "sha256": "<SHA-256 of the PDF bytes>"
      },
      "entries": [
        {
          "result_id": "<exact report result id>",
          "unit_id": "thm:main",
          "conclusion_id": "C001",
          "statement_anchor": {
            "file": "audit/00_sources/project/paper.tex",
            "start_line": 70,
            "end_line": 82,
            "sha256": "<locked statement span SHA-256>"
          },
          "label": "Theorem 1.2",
          "pdf_page": 4,
          "review": {
            "status": "matched",
            "note": "Compared the PDF page 4 heading and its fixed-point tail bound with the locked theorem at paper.tex lines 70 to 82; the statement and heading context match."
          }
        }
      ]
    }
  }
}
```

Every entry binds one existing result, unit, and conclusion to an exact locked
span in that result's `statement_source_ids`. Copy the stored span hash; it is
the SHA-256 of its UTF-8 quote, without a trailing newline added by the mapping.
`pdf_page` is a positive, one-based physical PDF page, not the printed journal
page. Its correctness is part of the authored comparison. The byte/header check
does not count PDF pages or inspect the heading.

Use the full mathematical kind and the observed identifier, such as `Lemma 2.1`,
`Theorem A.2`, or `Corollary B`. Omit the heading's terminal sentence punctuation.
A parenthesized part is allowed only if printed in the paper, for example
`Theorem 1.2(a)`. Never generate part letters to distinguish audit conclusions.
Several conclusions may use the same label and PDF page, provided they bind to
the same unit and exact statement anchor. Keep their individual result IDs and
descriptions. Parts of that statement may carry their own observed labels and
pages under the same base number. Unnumbered environments, separate post-proof
assertions, and external-result records cannot receive a formal manuscript
number through this object. Their existing presentation remains available.

Missing or stale source/PDF evidence discards the mapping. An invalid entry,
duplicate result entry, conflicting source binding, inconsistent page, or a
conflict with a literal heading discards the affected entries. The report shows
a display-resolution note and retains independently authenticated headings.
These notes are not mathematical defects. The reserved mapping is handled as
structured display metadata, rather than miscellaneous authored prose.

After a source or PDF change, repeat the actual correspondence check before
updating its hashes. Preserve sealed reports and make presentation changes in
the working audit copy. Use the existing report and finalization workflow;
the generated projection binds the current display evidence, so stale labels
cannot silently preserve a released report's presentation identity.
