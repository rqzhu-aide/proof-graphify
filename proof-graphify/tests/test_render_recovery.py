"""Publication recovery checks for file renders and common-store renders."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import paper_database as database
import proof_overview as overview
import overview_staging
import paper_records as records


@unittest.skipUnless(shutil.which("node"), "HTML rendering requires shared Node.js.")
class RenderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "paper.tex"
        self.source.write_text("\\begin{theorem}\\label{thm:constant}\n"
                               "A constant has variance zero.\n\\end{theorem}\n", encoding="utf-8")
        self.seed = self.base / "overview.json"
        self.seed.write_text(json.dumps({
            "schema_version": 3, "title": "Constant variance", "scope": "One synthetic theorem.",
            "source": {"title": "Synthetic paper", "file": "paper.tex"},
            "main_items": ["constant"],
            "items": [{"id": "constant", "kind": "theorem", "label": "Theorem 1",
                       "caption": "Constant variance", "statement": {
                           "text": "A constant has variance zero.", "form": "synopsis"},
                       "source": {"start_line": 1, "end_line": 3, "label": "thm:constant"}}],
            "uses": [],
        }), encoding="utf-8")
        self.output = self.base / "overview.html"
        self.output.write_text("Previous valid overview", encoding="utf-8")
        self.previous = self.output.read_bytes()

    def cleanup_failure(self, prefix):
        original = overview_staging.cleanup_directory

        def fail(directory):
            original(directory)
            if Path(directory).name.startswith(prefix):
                raise PermissionError("injected temporary cleanup failure")
        return patch.object(overview_staging, "cleanup_directory", fail)

    def assert_published(self, receipt):
        html = self.output.read_bytes()
        self.assertNotEqual(html, self.previous)
        self.assertEqual(receipt["sha256"], hashlib.sha256(html).hexdigest())
        self.assertEqual(receipt["bytes"], len(html))
        self.assertEqual(receipt["graph_preservation"]["status"], "pass")

    def common_database(self):
        db = self.base / "paper.sqlite"
        database.init_database(db, self.seed, focused=True)
        snapshot = database.export_snapshot(db)
        database.compare_records(db, {"basis": "tex", "expected_snapshot": snapshot["snapshot_id"],
            "targets": [{"collection": "items", "id": "constant"}],
            "reviewer": "Synthetic source reader",
            "note": "Compared the bounded theorem passage with the displayed synopsis."})
        return db, database.export_snapshot(db)

    def assert_retry_recovers(self, db, before):
        with closing(sqlite3.connect(db)) as connection:
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM metadata WHERE key LIKE 'overview_build:%'").fetchone()[0], 0)
        receipt = database.render_database(db, self.output)
        self.assert_published(receipt)
        self.assertTrue(receipt["build_recorded"])
        self.assertNotIn("build_record_error", receipt)
        self.assertEqual(database.export_snapshot(db), before)

    def test_render_cleanup_after_publication_returns_valid_receipt_with_warning(self):
        with self.cleanup_failure("proof-overview-"):
            receipt = overview.render_file(self.seed, self.output)
        self.assert_published(receipt)
        self.assertIn("cleanup", " ".join(receipt["warnings"]))

    def test_delivery_brief_reuses_source_comparison_without_changing_prepared_data(self):
        canonical = records.normalize(overview.load_data(self.seed), self.base)
        prepare = records._prepare_records_validated
        accept = overview._accept_artifact
        for result, status in ((None, "incomplete"), ("matched", "complete"),
                               ("needs_attention", "complete_with_limits")):
            with self.subTest(result=result):
                data = deepcopy(canonical)
                if result:
                    data["observations"].extend(records.make_observations(
                        data, [{"collection": "items", "id": "constant"}],
                        reviewer="Synthetic source reader", result=result,
                        note="Saved source comparison."))
                captured = {}

                def capture(*args):
                    prepared = prepare(*args)
                    captured["prepared"] = prepared
                    captured["brief"] = deepcopy(prepared["delivery_brief"])
                    return prepared

                def capture_accepted(prepared, *args):
                    captured["accepted"] = deepcopy(prepared)
                    return accept(prepared, *args)

                with patch.object(records, "_prepare_records_validated", side_effect=capture), patch.object(
                        records, "comparison_status", wraps=records.comparison_status) as comparison, patch.object(
                        overview, "_accept_artifact", side_effect=capture_accepted):
                    receipt = overview._render_validated_dataset(data, self.base, self.output)
                comparison.assert_called_once()
                prepared = captured["prepared"]
                brief = receipt["delivery_brief"]
                self.assertIsNot(brief, prepared["delivery_brief"])
                self.assertEqual(prepared["delivery_brief"], captured["brief"])
                self.assertEqual(prepared, captured["accepted"])
                self.assertIs(brief["source_comparison"], prepared["build_context"]["source_comparison"])
                self.assertEqual(brief["source_comparison"], receipt["source_comparison"])
                self.assertEqual(brief["source_comparison"]["status"], status)
                self.assertEqual(brief["browser_review"], receipt["browser_review"])
                self.assertEqual(brief["browser_review"], "not_performed")
                parser = overview._ArtifactReader()
                html = self.output.read_text(encoding="utf-8")
                parser.feed(html)
                self.assertEqual(json.loads("".join(parser.metadata))["build_context"], prepared["build_context"])
                self.assertIn(f'data-proof-fidelity="{result or "unreviewed"}"', html)
                if result == "needs_attention":
                    self.assertTrue("All 1 records reviewed; 1 have unresolved source questions." in html)

    def test_render_failure_and_cleanup_failure_preserve_first_error_and_previous_html(self):
        failed = subprocess.CompletedProcess([], 1, "", "injected renderer failure")
        with self.cleanup_failure("proof-overview-"), patch.object(overview.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(overview.OverviewError, "injected renderer failure") as caught:
                overview.render_file(self.seed, self.output)
        self.assertEqual(self.output.read_bytes(), self.previous)
        if hasattr(caught.exception, "add_note"):
            self.assertIn("cleanup", " ".join(getattr(caught.exception, "__notes__", [])))

    def test_output_parent_file_is_an_actionable_overview_error(self):
        parent = self.base / "occupied"
        parent.write_text("keep this file", encoding="utf-8")
        with patch.object(overview.subprocess, "run") as render:
            with self.assertRaisesRegex(overview.OverviewError, "output path"):
                overview.render_file(self.seed, parent / "overview.html")
        render.assert_not_called()
        self.assertEqual(parent.read_text(encoding="utf-8"), "keep this file")
        run = subprocess.run([sys.executable, "-B", str(SKILL / "scripts" / "proof_overview.py"),
                              "render", str(self.seed), str(parent / "overview.html")],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 2)
        self.assertIn("output path", json.loads(run.stderr)["error"])

    def test_common_build_record_failure_returns_publication_receipt(self):
        db, before = self.common_database()
        common_overview, _, _, _ = database._common_core()
        with patch.object(common_overview, "record_build_receipt",
                          side_effect=sqlite3.OperationalError("injected common build record failure")):
            receipt = database.render_database(db, self.output)
        self.assert_published(receipt)
        self.assertFalse(receipt["build_recorded"])
        self.assertIn("build record failure", receipt["build_record_error"])
        self.assertEqual(database.export_snapshot(db), before)
        self.assert_retry_recovers(db, before)

    def test_common_build_commit_failure_returns_publication_receipt(self):
        db, before = self.common_database()
        _, Database, _, _ = database._common_core()
        with patch.object(Database, "commit", side_effect=sqlite3.OperationalError("injected build commit failure")):
            receipt = database.render_database(db, self.output)
        self.assert_published(receipt)
        self.assertFalse(receipt["build_recorded"])
        self.assertIn("commit failure", receipt["build_record_error"])
        self.assertEqual(database.export_snapshot(db), before)
        self.assert_retry_recovers(db, before)

    def test_common_projection_cleanup_after_publication_returns_receipt(self):
        db, before = self.common_database()
        with self.cleanup_failure("overview-projection-"):
            receipt = database.render_database(db, self.output)
        self.assert_published(receipt)
        self.assertTrue(receipt["build_recorded"])
        self.assertIn("cleanup", " ".join(receipt["warnings"]))
        self.assertEqual(database.export_snapshot(db), before)

    def test_common_projection_cleanup_does_not_mask_failed_render(self):
        db, before = self.common_database()
        with self.cleanup_failure("overview-projection-"), patch.object(
                overview, "_render_validated_dataset", side_effect=overview.OverviewError("injected renderer failure")):
            with self.assertRaisesRegex(overview.OverviewError, "injected renderer failure") as caught:
                database.render_database(db, self.output)
        self.assertEqual(self.output.read_bytes(), self.previous)
        if hasattr(caught.exception, "add_note"):
            self.assertIn("cleanup", " ".join(getattr(caught.exception, "__notes__", [])))
        self.assertEqual(database.export_snapshot(db), before)
        self.assert_retry_recovers(db, before)


if __name__ == "__main__":
    unittest.main()
