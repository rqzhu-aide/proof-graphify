"""Common-store operation results survive disposable projection cleanup errors."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import paper_database as database
import overview_staging


class ProjectionCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "paper.tex"
        self.source.write_text("\\begin{theorem}\\label{thm:constant}\n"
                               "A constant has variance zero.\n\\end{theorem}\n", encoding="utf-8")
        self.seed = self.base / "seed.json"
        self.seed.write_text(json.dumps({
            "schema_version": 3, "title": "Constant variance", "scope": "One synthetic theorem.",
            "source": {"title": "Synthetic paper", "file": "paper.tex"},
            "main_items": ["constant"], "uses": [],
            "items": [{"id": "constant", "kind": "theorem", "label": "Theorem 1",
                       "caption": "Constant variance", "statement": {
                           "text": "A constant has variance zero.", "form": "synopsis"},
                       "source": {"start_line": 1, "end_line": 3, "label": "thm:constant"}}],
        }), encoding="utf-8")
        self.db = self.base / "data" / "paper.sqlite"
        database.init_database(self.db, self.seed, focused=True)
        self.before = database.export_snapshot(self.db)

    def cleanup_failure(self):
        original = overview_staging.cleanup_directory

        def fail(directory):
            original(directory)
            if Path(directory).name.startswith("overview-projection-"):
                raise PermissionError("injected projection cleanup failure")

        return patch.object(overview_staging, "cleanup_directory", fail)

    def assert_cleanup_warning(self, receipt):
        self.assertIn("operation completed", " ".join(receipt["warnings"]))
        self.assertIn("injected projection cleanup failure", " ".join(receipt["warnings"]))

    def scope_edit(self):
        return {"expected_snapshot": self.before["snapshot_id"],
                "set": {"scope": "Updated synthetic scope."}, "edits": []}

    def test_committed_apply_returns_receipt_and_saved_edit(self):
        with self.cleanup_failure():
            receipt = database.apply_edits(self.db, self.scope_edit())
        self.assert_cleanup_warning(receipt)
        after = database.export_snapshot(self.db)
        self.assertEqual(after["scope"], "Updated synthetic scope.")
        self.assertEqual(receipt["snapshot_id"], after["snapshot_id"])
        self.assertNotEqual(after["snapshot_id"], self.before["snapshot_id"])

    def test_comparison_is_saved_even_when_snapshot_is_unchanged(self):
        with self.cleanup_failure():
            receipt = database.compare_records(self.db, {
                "expected_snapshot": self.before["snapshot_id"],
                "targets": [{"collection": "items", "id": "constant"}],
                "reviewer": "Synthetic source reader", "result": "matched",
                "note": "Compared the synopsis with the located synthetic theorem.",
            })
        self.assert_cleanup_warning(receipt)
        after = database.export_snapshot(self.db)
        self.assertEqual(after["snapshot_id"], self.before["snapshot_id"])
        self.assertEqual(receipt["recorded"], 1)
        self.assertEqual(len(after["observations"]), len(self.before["observations"]) + 1)
        self.assertEqual(database.get_packet(self.db, "constant")["target_fidelity"], "matched")

    def test_committed_refresh_returns_receipt_and_captured_source(self):
        self.source.write_text("\\begin{theorem}\\label{thm:constant}\n"
                               "Any constant has variance zero.\n\\end{theorem}\n", encoding="utf-8")
        with self.cleanup_failure():
            receipt = database.refresh_database(self.db, self.before["snapshot_id"])
        self.assert_cleanup_warning(receipt)
        after = database.export_snapshot(self.db)
        self.assertEqual(receipt["snapshot_id"], after["snapshot_id"])
        self.assertNotEqual(after["snapshot_id"], self.before["snapshot_id"])
        self.assertTrue(any("Any constant" in anchor["excerpt"] for anchor in after["anchors"]))

    def test_successful_reads_return_results_without_changing_authority(self):
        before_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()
        calls = [
            (database.list_records, (), "expected_snapshot"),
            (database.get_packet, ("constant",), "expected_snapshot"),
            (database.validate_database, (), "snapshot_id"),
        ]
        for function, args, snapshot_key in calls:
            with self.subTest(operation=function.__name__), self.cleanup_failure():
                receipt = function(self.db, *args)
            self.assert_cleanup_warning(receipt)
            self.assertEqual(receipt[snapshot_key], self.before["snapshot_id"])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before_hash)

    def test_snapshot_export_logs_warning_without_changing_payload(self):
        with self.assertLogs(database.__name__, level="WARNING") as logs, self.cleanup_failure():
            snapshot = database.export_snapshot(self.db)
        self.assertIn("injected projection cleanup failure", " ".join(logs.output))
        self.assertEqual(snapshot, self.before)
        self.assertNotIn("warnings", snapshot)
        self.assertEqual(database.records.validate_records(snapshot), snapshot)

    def test_file_export_keeps_canonical_json_and_receipt(self):
        output = self.base / "exports" / "paper.json"
        with self.cleanup_failure():
            receipt = database.export_database(self.db, output)
        self.assert_cleanup_warning(receipt)
        exported = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exported, self.before)
        self.assertNotIn("warnings", exported)
        self.assertEqual(database.records.validate_records(exported), exported)
        self.assertEqual(receipt["snapshot_id"], exported["snapshot_id"])
        self.assertEqual(receipt["observations"], len(exported["observations"]))

    def test_failed_commit_preserves_error_and_rolls_back_with_cleanup_failure(self):
        _, Database, _, _ = database._common_core()
        with self.cleanup_failure(), patch.object(
                Database, "commit", side_effect=sqlite3.OperationalError("injected commit failure")):
            with self.assertRaisesRegex(sqlite3.OperationalError, "injected commit failure") as caught:
                database.apply_edits(self.db, self.scope_edit())
        self.assertIn("injected projection cleanup failure", " ".join(caught.exception.__notes__))
        self.assertEqual(database.export_snapshot(self.db), self.before)

    def test_invalid_edit_preserves_validation_error_and_authority(self):
        with self.cleanup_failure():
            with self.assertRaisesRegex(ValueError, "main_items") as caught:
                database.apply_edits(self.db, {
                    "expected_snapshot": self.before["snapshot_id"],
                    "set": {"main_items": []}, "edits": [],
                })
        self.assertIn("injected projection cleanup failure", " ".join(caught.exception.__notes__))
        self.assertEqual(database.export_snapshot(self.db), self.before)


if __name__ == "__main__":
    unittest.main()
