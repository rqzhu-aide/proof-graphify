"""Continue common overviews when the system temporary folder is unavailable."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import paper_database as database
import proof_overview as overview
import overview_staging


class OverviewStagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_platform_creation_uses_inherited_windows_acl_and_private_posix_mode(self):
        token = "ab" * 16
        expected = self.base / ("overview-projection-" + token)
        for platform in ("nt", "posix"):
            filesystem = SimpleNamespace(name=platform, mkdir=Mock())
            with self.subTest(platform=platform), patch.object(overview_staging, "os", filesystem), patch.object(
                    overview_staging.secrets, "token_hex", return_value=token) as random_name:
                actual = overview_staging.create_directory(self.base, prefix="overview-projection-")
            self.assertEqual(actual, expected)
            random_name.assert_called_once_with(16)
            if platform == "nt":
                filesystem.mkdir.assert_called_once_with(expected)
            else:
                filesystem.mkdir.assert_called_once_with(expected, 0o700)

    def test_collision_preserves_existing_directory_or_file(self):
        token = "cd" * 16
        occupied = self.base / ("overview-projection-" + token)
        for kind in ("directory", "file"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    occupied.mkdir()
                    marker = occupied / "keep.txt"
                else:
                    marker = occupied
                marker.write_text("keep collided contents", encoding="utf-8")
                with patch.object(overview_staging.secrets, "token_hex", return_value=token), patch.object(
                        overview_staging, "cleanup_directory") as cleanup:
                    with self.assertRaises(FileExistsError):
                        overview_staging.create_directory(self.base, prefix="overview-projection-")
                cleanup.assert_not_called()
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep collided contents")
                marker.unlink()
                if kind == "directory":
                    occupied.rmdir()

    def test_native_directory_supports_sqlite_and_explicit_cleanup(self):
        staging = overview_staging.create_directory(self.base, prefix="overview-projection-")
        self.assertEqual(staging.parent, self.base)
        self.assertRegex(staging.name, r"^overview-projection-[0-9a-f]{32}$")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(staging.stat().st_mode), 0o700)
        with sqlite3.connect(staging / "projection.sqlite") as connection:
            connection.execute("CREATE TABLE evidence(value TEXT)")
            connection.execute("INSERT INTO evidence VALUES ('usable staging')")
            self.assertEqual(connection.execute("SELECT value FROM evidence").fetchone()[0], "usable staging")
        connection.close()
        overview_staging.cleanup_directory(staging)
        self.assertFalse(staging.exists())

    def test_cleanup_reports_failure_and_retains_contents(self):
        staging = overview_staging.create_directory(self.base, prefix="overview-projection-")
        marker = staging / "keep.txt"
        marker.write_text("owned staging", encoding="utf-8")
        with patch.object(overview_staging.shutil, "rmtree", side_effect=PermissionError("denied cleanup")):
            with self.assertRaisesRegex(PermissionError, "denied cleanup"):
                overview_staging.cleanup_directory(staging)
        self.assertEqual(marker.read_text(encoding="utf-8"), "owned staging")
        overview_staging.cleanup_directory(staging)

    @unittest.skipUnless(os.name == "nt", "Read-only file deletion policy is Windows specific.")
    def test_windows_readonly_cleanup_reports_warning_without_permission_repair(self):
        warnings = []
        staging = marker = None
        try:
            with overview._render_directory(prefix="proof-overview-", dir=self.base, warnings=warnings) as name:
                staging = Path(name)
                marker = staging / "readonly.txt"
                marker.write_text("retained after denied cleanup", encoding="utf-8")
                os.chmod(marker, stat.S_IREAD)
            self.assertIn("published", " ".join(warnings))
            self.assertIn("cleanup failed", " ".join(warnings))
            self.assertTrue(marker.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "retained after denied cleanup")
        finally:
            if marker is not None and marker.exists():
                os.chmod(marker, stat.S_IWRITE)
            if staging is not None and staging.exists():
                overview_staging.cleanup_directory(staging)


class ProjectionStagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "paper.tex"
        self.source.write_text("\\begin{theorem}\\label{thm:constant}\n"
                               "A constant has variance zero.\n\\end{theorem}\n", encoding="utf-8")
        self.seed = self.base / "seed.json"
        self.seed.write_text(json.dumps({
            "schema_version": 3, "title": "Constant variance", "scope": "One synthetic statement.",
            "source": {"title": "Synthetic source", "file": "paper.tex"},
            "main_items": ["constant"], "uses": [],
            "items": [{"id": "constant", "kind": "theorem", "label": "Theorem 1",
                       "caption": "Constant variance", "statement": {
                           "text": "A constant has variance zero.", "form": "synopsis"},
                       "source": {"start_line": 1, "end_line": 3, "label": "thm:constant"}}],
        }), encoding="utf-8")
        self.db = self.base / "data" / "paper.sqlite"
        self.output = self.base / "overview.html"

    @contextmanager
    def unavailable_system_temp(self):
        with patch.object(tempfile, "TemporaryDirectory", side_effect=PermissionError(
                "TemporaryDirectory is unavailable; use local overview staging.")):
            yield

    def compare_constant(self, snapshot):
        return database.compare_records(self.db, {"basis": "tex",
            "expected_snapshot": snapshot,
            "targets": [{"collection": "items", "id": "constant"}],
            "reviewer": "Synthetic source reader", "result": "matched",
            "note": "Compared the saved synopsis with the bounded synthetic statement.",
        })

    @unittest.skipUnless(shutil.which("node"), "Rendering requires shared Node.js.")
    def test_resume_and_render_recovery_without_system_temp(self):
        source_bytes = self.source.read_bytes()
        with self.unavailable_system_temp():
            initial = database.init_database(self.db, self.seed, focused=True)
            listing = database.list_records(self.db)
            self.assertEqual(listing["expected_snapshot"], initial["snapshot_id"])
            packet = database.get_packet(self.db, "constant")
            self.compare_constant(packet["expected_snapshot"])
            reviewed = database.export_snapshot(self.db)
            packet = database.get_packet(self.db, "constant")
            record = packet["item"]
            record["caption"] = "Variance of a constant"
            edited = database.apply_edits(self.db, {
                "expected_snapshot": packet["expected_snapshot"], "edits": [
                    {"collection": "items", "op": "upsert", "id": "constant", "record": record}],
            })
            self.assertEqual(database.get_packet(self.db, "constant")["target_fidelity"], "stale")
            self.compare_constant(edited["snapshot_id"])
            before = database.export_snapshot(self.db)
            exported = self.base / "exports" / "paper.json"
            database.export_database(self.db, exported)
            self.assertEqual(json.loads(exported.read_text(encoding="utf-8")), before)
            self.output.write_text("Previous overview", encoding="utf-8")
            previous_html = self.output.read_bytes()
            with patch.object(overview, "_render_validated_dataset", side_effect=overview.OverviewError("Display failed")):
                with self.assertRaisesRegex(overview.OverviewError, "Display failed"):
                    database.render_database(self.db, self.output)
            self.assertEqual(self.output.read_bytes(), previous_html)
            self.assertEqual(database.export_snapshot(self.db), before)
            receipt = database.render_database(self.db, self.output)
            self.assertTrue(receipt["build_recorded"])
            self.assertEqual(receipt["source_comparison"]["matched"], 1)
            resumed = database.get_packet(self.db, "constant")
            self.assertEqual(resumed["expected_snapshot"], edited["snapshot_id"])
            self.assertEqual(resumed["target_fidelity"], "matched")
            self.assertEqual(database.export_snapshot(self.db), before)
            historical = database.export_snapshot(self.db, reviewed["snapshot_id"])
            self.assertEqual({k: v for k, v in historical.items() if k != "observations"},
                             {k: v for k, v in reviewed.items() if k != "observations"})
            self.assertTrue(all(row in historical["observations"] for row in reviewed["observations"]))
        self.assertEqual(self.source.read_bytes(), source_bytes)
        self.assertEqual(list(self.db.parent.glob("overview-projection-*")), [])
        self.assertEqual(list(self.base.glob("proof-overview-*")), [])

    @unittest.skipUnless(shutil.which("node"), "Rendering requires shared Node.js.")
    def test_denied_staging_creation_preserves_authority_and_previous_output(self):
        database.init_database(self.db, self.seed, focused=True)
        before_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.output.write_text("Previous valid overview", encoding="utf-8")
        previous_html = self.output.read_bytes()
        original = os.mkdir

        def denied(path, *args, **kwargs):
            if Path(path).name.startswith(("overview-projection-", "proof-overview-")):
                raise PermissionError("injected staging creation denial")
            return original(path, *args, **kwargs)

        with patch.object(overview_staging.os, "mkdir", denied), patch.object(
                overview_staging, "cleanup_directory") as cleanup:
            with self.assertRaisesRegex(PermissionError, "staging creation denial"):
                database.list_records(self.db)
            with self.assertRaisesRegex(overview.OverviewError, "staging creation denial"):
                overview.render_file(self.seed, self.output)
        cleanup.assert_not_called()
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before_hash)
        self.assertEqual(self.output.read_bytes(), previous_html)
        self.assertEqual(list(self.db.parent.glob("overview-projection-*")), [])
        self.assertEqual(list(self.base.glob("proof-overview-*")), [])

    def test_readonly_authority_in_writable_folder_can_still_be_read(self):
        initial = database.init_database(self.db, self.seed, focused=True)
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        previous_mode = self.db.stat().st_mode
        os.chmod(self.db, stat.S_IREAD)
        try:
            with self.unavailable_system_temp():
                self.assertEqual(database.list_records(self.db)["expected_snapshot"], initial["snapshot_id"])
                self.assertEqual(database.get_packet(self.db, "constant")["item"]["id"], "constant")
                self.assertTrue(database.validate_database(self.db)["valid"])
                self.assertEqual(database.export_snapshot(self.db)["snapshot_id"], initial["snapshot_id"])
        finally:
            os.chmod(self.db, previous_mode)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        self.assertEqual(list(self.db.parent.glob("overview-projection-*")), [])


if __name__ == "__main__":
    unittest.main()
