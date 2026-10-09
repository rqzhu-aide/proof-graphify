"""Reviewed numbering is optional display evidence, never a mathematical verdict."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck_labels.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_labels", SCRIPT)
labels = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(labels)


def sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


class ReviewedLabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "audit original"
        self.root.mkdir()
        self.pdf = self.root / "audit/00_sources/display-evidence/manuscript.pdf"
        self.pdf.parent.mkdir(parents=True)
        # Header-only fixtures exercise fingerprint handling, not PDF extraction
        # or a claim that a mathematical statement was actually reviewed.
        self.pdf.write_bytes(b"%PDF-1.7\nfixture only\n%%EOF\n")
        quote = "\\begin{theorem}[Tail bound]\\label{thm:main}\nFor each fixed $x$, the bound holds.\n\\end{theorem}"
        self.source = {"id": "source-theorem", "file": "audit/00_sources/project/paper.tex",
                       "start_line": 7, "end_line": 9, "sha256": sha(quote),
                       "quote": quote, "status": "locked"}
        self.sources = [self.source]
        self.result = {"id": "result-exact", "unit_id": "thm:main", "conclusion_id": "C001",
                       "kind": "theorem", "source_environment": "theorem", "printed_label": None,
                       "statement_source_ids": [self.source["id"]],
                       "judgments": {"statement_status": "not_established"}}
        self.results = [self.result]
        self.snapshot = sha("current source snapshot")
        self.entry = {"result_id": self.result["id"], "unit_id": self.result["unit_id"],
                      "conclusion_id": self.result["conclusion_id"],
                      "statement_anchor": {field: self.source[field] for field in labels._ANCHOR_FIELDS},
                      "label": "Theorem 1.2", "pdf_page": 3,
                      "review": {"status": "matched", "note": "Test review assertion: compared the heading and fixed-point statement on PDF page 3 with the locked theorem."}}
        self.mapping = {"version": 1, "source_snapshot_sha256": self.snapshot,
                        "pdf": {"path": self.pdf.relative_to(self.root).as_posix(), "sha256": sha(self.pdf.read_bytes())},
                        "entries": [self.entry]}

    def resolve(self, mapping=None):
        return labels.resolve_labels(self.root, self.mapping if mapping is None else mapping,
                                     self.snapshot, self.results, self.sources)

    def assertFallback(self, output, reason=None):
        self.assertEqual({}, output["labels"])
        self.assertTrue(output["notes"])
        if reason:
            self.assertTrue(any(reason in note for note in output["notes"]), output["notes"])

    def add_conclusion(self, *, unit=None, source=None):
        result = {**copy.deepcopy(self.result), "id": "result-second", "conclusion_id": "C002"}
        if unit:
            result["unit_id"] = unit
        if source:
            self.sources.append(source)
            result["statement_source_ids"] = [source["id"]]
        entry = {**copy.deepcopy(self.entry), "result_id": result["id"],
                 "unit_id": result["unit_id"], "conclusion_id": result["conclusion_id"]}
        if source:
            entry["statement_anchor"] = {field: source[field] for field in labels._ANCHOR_FIELDS}
        self.results.append(result)
        self.mapping["entries"].append(entry)
        return result, entry

    def test_no_mapping_is_quiet_and_does_not_infer_from_tex_label(self):
        before = copy.deepcopy((self.results, self.sources))
        self.assertEqual({"labels": {}, "notes": []},
                         labels.resolve_labels(self.root, None, self.snapshot, self.results, self.sources))
        self.assertEqual(before, (self.results, self.sources))

    def test_pdf_hashing_uses_python_310_api_and_checks_bytes_after_first_chunk(self):
        content = b"%PDF-1.7\n" + b"x" * (2 * 1024 * 1024) + b"\n%%EOF\n"
        self.pdf.write_bytes(content)
        self.mapping["pdf"]["sha256"] = hashlib.sha256(content).hexdigest()
        # API simulation on the shared current interpreter, not a claim that
        # this test was executed by Python 3.10 itself.
        compatible_hashlib = SimpleNamespace(sha256=hashlib.sha256)
        self.assertFalse(hasattr(compatible_hashlib, "file_digest"))
        with patch.object(labels, "hashlib", compatible_hashlib):
            output = self.resolve()
            self.assertEqual([], output["notes"])
            self.assertEqual(self.mapping["pdf"]["sha256"],
                             output["labels"]["result-exact"]["provenance"]["pdf_sha256"])
            self.pdf.write_bytes(content[:-1] + b" ")
            self.assertFallback(self.resolve(), "changed")

    def test_reviewed_pdf_label_has_exact_provenance_without_changing_judgments(self):
        before = copy.deepcopy((self.mapping, self.results, self.sources))
        output = self.resolve()
        self.assertEqual([], output["notes"])
        row = output["labels"]["result-exact"]
        self.assertEqual(("Theorem 1.2", 3), (row["label"], row["pdf_page"]))
        self.assertEqual("reviewed_pdf", row["provenance"]["kind"])
        self.assertEqual(self.entry["statement_anchor"], row["provenance"]["statement_anchor"])
        self.assertEqual(self.entry["review"], row["provenance"]["review"])
        self.assertNotIn("judgments", row)
        self.assertEqual(before, (self.mapping, self.results, self.sources))

    def test_snapshot_pdf_change_missing_pdf_and_bad_header_fall_back(self):
        original = self.pdf.read_bytes()
        for data, digest in ((original + b"changed", self.mapping["pdf"]["sha256"]),
                             (b"not a PDF", sha(b"not a PDF"))):
            with self.subTest(data=data):
                self.pdf.write_bytes(data)
                self.mapping["pdf"]["sha256"] = digest
                self.assertFallback(self.resolve(), "PDF")
        self.pdf.unlink()
        self.assertFallback(self.resolve(), "PDF")
        self.mapping["source_snapshot_sha256"] = sha("old snapshot")
        self.assertFallback(self.resolve(), "snapshot")

    def test_caller_can_withhold_current_digest_when_source_closure_is_stale(self):
        output = labels.resolve_labels(self.root, self.mapping, "", self.results, self.sources)
        self.assertFallback(output, "snapshot")

    def test_relative_pdf_evidence_survives_audit_relocation(self):
        expected = self.resolve()
        relocated = Path(self.tmp.name) / "moved audit"
        shutil.copytree(self.root, relocated)
        shutil.rmtree(self.root)
        self.assertEqual(expected, labels.resolve_labels(relocated, self.mapping, self.snapshot, self.results, self.sources))

    def test_pdf_path_rejects_escape_absolute_drive_and_redirect(self):
        for value in ("../outside.pdf", str(self.pdf.resolve()), "C:/outside.pdf",
                      "C:outside.pdf", "//host/share.pdf", "audit\\outside.pdf",
                      "audit/file.pdf:stream", "audit/../outside.pdf"):
            with self.subTest(path=value):
                self.mapping["pdf"]["path"] = value
                self.assertFallback(self.resolve(), "path")
        self.mapping["pdf"]["path"] = "audit/redirect.pdf"
        outside = Path(self.tmp.name) / "outside.pdf"
        outside.write_bytes(b"%PDF-1.7\n")
        original_resolve = Path.resolve

        def resolved(path, *args, **kwargs):
            return outside if path.name == "redirect.pdf" else original_resolve(path, *args, **kwargs)

        # Models a filesystem symlink target on hosts without symlink privilege.
        with patch.object(Path, "resolve", resolved):
            self.assertFallback(self.resolve(), "redirected")

    def test_result_unit_conclusion_and_statement_hash_are_exact(self):
        for field, bad in (("result_id", "not-a-result"), ("unit_id", "another-unit"),
                           ("conclusion_id", "C002")):
            with self.subTest(field=field):
                mapping = copy.deepcopy(self.mapping)
                mapping["entries"][0][field] = bad
                self.assertFallback(self.resolve(mapping), "binding")
        for field, bad in (("file", "audit/other.tex"), ("start_line", 8),
                           ("end_line", 10), ("sha256", sha("another statement"))):
            with self.subTest(field=field):
                mapping = copy.deepcopy(self.mapping)
                mapping["entries"][0]["statement_anchor"][field] = bad
                self.assertFallback(self.resolve(mapping), "anchor")

    def test_unlocked_changed_or_unbound_source_cannot_authenticate_number(self):
        original = copy.deepcopy(self.source)
        for changes in ({"status": "unavailable"}, {"quote": "changed source"}, {"id": "another-source"}):
            with self.subTest(changes=changes):
                self.source.update(changes)
                self.assertFallback(self.resolve(), "anchor")
                self.source.clear()
                self.source.update(original)

    def test_missing_review_and_malformed_schema_cannot_supply_numbers(self):
        for review in (None, {}, {"status": "matched", "note": "pending"},
                       {"status": "not_checked", "note": "matching filenames"}):
            with self.subTest(review=review):
                self.entry["review"] = review
                self.assertFallback(self.resolve(), "review")
        for mapping in ([], {}, {"version": True}, {"version": 2}):
            self.assertFallback(self.resolve(mapping), "mapping")

    def test_literal_heading_survives_conflict_and_all_mapping_failures(self):
        self.result["printed_label"] = "Theorem 1.2"
        self.assertEqual("Theorem 1.2", self.resolve()["labels"]["result-exact"]["label"])
        self.entry["label"] = "Theorem 4.9"
        self.assertFallback(self.resolve(), "literal heading")
        self.assertEqual("Theorem 1.2", self.result["printed_label"])
        self.mapping["source_snapshot_sha256"] = sha("stale")
        self.assertFallback(self.resolve(), "snapshot")
        self.assertEqual("Theorem 1.2", self.result["printed_label"])

    def test_distinct_conclusions_share_heading_without_merging(self):
        self.add_conclusion()
        output = self.resolve()
        self.assertEqual({"result-exact", "result-second"}, set(output["labels"]))
        self.assertEqual([], output["notes"])
        self.assertEqual(["Theorem 1.2", "Theorem 1.2"], [row["label"] for row in output["labels"].values()])

    def test_observed_parts_are_allowed_but_conflicting_base_numbers_are_not(self):
        _, other = self.add_conclusion()
        self.entry["label"], other["label"] = "Theorem 1.2(a)", "Theorem 1.2(b)"
        self.assertEqual(2, len(self.resolve()["labels"]))
        other["label"] = "Theorem 1.3(b)"
        self.assertFallback(self.resolve(), "conflicting")

    def test_duplicate_result_and_conflicting_pages_discard_all_candidates(self):
        self.mapping["entries"].append(copy.deepcopy(self.entry))
        self.assertFallback(self.resolve(), "duplicate")
        self.mapping["entries"].pop()
        _, other = self.add_conclusion()
        other["pdf_page"] = 8
        self.assertFallback(self.resolve(), "conflicting")

    def test_bad_entry_does_not_discard_an_independently_valid_neighbor(self):
        self.mapping["entries"].extend([None, {"result_id": "missing-result"}])
        output = self.resolve()
        self.assertEqual({"result-exact"}, set(output["labels"]))
        self.assertEqual(2, len(output["notes"]))

    def test_number_cannot_be_shared_by_unrelated_statement_or_existing_literal(self):
        self.add_conclusion(unit="another-unit")
        self.assertFallback(self.resolve(), "conflicting")
        self.mapping["entries"].pop()
        self.results[1]["printed_label"] = "Theorem 1.2"
        self.assertFallback(self.resolve(), "another literal")

    def test_unnumbered_postproof_and_external_results_preserve_fallback(self):
        for changes in ({"kind": "unnumbered theorem"}, {"kind": "conclusion"},
                        {"source_environment": "theorem*"}, {"separate_assertion": True},
                        {"kind": "external result"}):
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.result)
                self.result.update(changes)
                self.assertFallback(self.resolve(), "numbering")
                self.result.clear()
                self.result.update(original)

    def test_labels_and_physical_pages_require_observed_display_shapes(self):
        for label in ("thm:main", "1.2", "Theorem 1.2. Some caption", "Lemma 1.2", "Theorem <script>"):
            with self.subTest(label=label):
                self.entry["label"] = label
                self.assertFallback(self.resolve(), "label")
        for label in ("Theorem A", "Theorem A.2", "Theorem IV", "Theorem 1.2b", "Theorem 1.2 (ii)"):
            self.entry["label"] = label
            self.assertEqual(label, self.resolve()["labels"]["result-exact"]["label"])
        for page in (None, 0, -1, True, "3"):
            self.entry["pdf_page"] = page
            self.assertFallback(self.resolve(), "page")


if __name__ == "__main__":
    unittest.main()
