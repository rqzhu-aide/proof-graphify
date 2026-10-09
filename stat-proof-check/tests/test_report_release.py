from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_proofcheck as fixtures

pc = fixtures.proofcheck


class ReportReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FinalizationTests()
        self.fixture.setUp()
        self.root = self.fixture.audit

    def tearDown(self):
        self.fixture.tearDown()

    def migrate_complete(self):
        self.fixture.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_migrate_report(argparse.Namespace(root=self.root, markdown=False))

    def finalize(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = pc.cmd_finalize(argparse.Namespace(root=self.root))
        if result:
            errors, _ = pc.check_audit_finalization(self.root, check_reports=False)
            self.fail(f"HTML finalization failed; mathematical errors={errors}")

    def test_new_scaffold_is_html_and_honestly_nonfinal(self):
        output = self.fixture.base / "new-html-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_scaffold(argparse.Namespace(paper=self.fixture.paper, output=output))
        manifest = fixtures.read_json(output / "AUDIT_MANIFEST.json")
        self.assertEqual(2, manifest["report_contract"]["version"])
        self.assertEqual(3, manifest["protocol"]["challenge_contract_version"])
        report = output / "proofcheck-report.html"
        self.assertEqual("proofcheck-report.html", manifest["report_contract"]["primary"])
        self.assertTrue(report.is_file())
        self.assertIn("NONFINAL", report.read_text(encoding="utf-8"))
        self.assertFalse((output / "audit/06_reports/FINAL_REPORT.md").exists())
        self.assertFalse(pc.check_finalization_freshness(output)["usable_finalization"])

    def test_migration_preserves_original_bytes_and_mathematical_records(self):
        self.fixture.make_complete_audit()
        report = self.root / "audit/06_reports/FINAL_REPORT.md"
        # Exercise byte preservation, including CRLF and a UTF-8 BOM.
        report.write_bytes(b"\xef\xbb\xbf" + report.read_bytes().replace(b"\n", b"\r\n"))
        prior_bytes = report.read_bytes()
        ledger = next((self.root / "audit/04_local_checks").glob("*.ledger.json"))
        ledger_bytes = ledger.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_migrate_report(argparse.Namespace(root=self.root, markdown=False))
        archived = list((self.root / "audit/06_reports/history").glob("report-v1-*/FINAL_REPORT.md"))
        self.assertEqual(1, len(archived))
        self.assertEqual(prior_bytes, archived[0].read_bytes())
        self.assertEqual(ledger_bytes, ledger.read_bytes())
        self.assertIn("NONFINAL", (self.root / "proofcheck-report.html").read_text(encoding="utf-8"))

    def test_html_finalization_and_readonly_delivery(self):
        self.migrate_complete()
        self.finalize()
        before = pc.audit_state_manifest(self.root)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            status = pc.cmd_delivery_check(argparse.Namespace(root=self.root))
        self.assertEqual(0, status)
        value = json.loads(stream.getvalue())
        self.assertEqual("FINAL", value["delivery_status"])
        self.assertTrue(value["report"].endswith("proofcheck-report.html"))
        self.assertEqual(before, pc.audit_state_manifest(self.root))
        errors, _ = pc.check_audit_finalization(self.root)
        self.assertEqual([], errors)

    def test_failed_migration_leaves_original_state(self):
        self.fixture.make_complete_audit()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with mock.patch.object(pc.report_renderer(), "render_report", side_effect=ValueError("injected render failure")):
            with self.assertRaisesRegex(ValueError, "injected"):
                pc.report_module("proofcheck_release").migrate(pc, self.root)
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_migration_keeps_multiline_authored_context(self):
        self.fixture.make_complete_audit()
        report = self.root / "audit/06_reports/FINAL_REPORT.md"
        report.write_text(re.sub(r"^- (?:Final confidence|Tooling, extraction, or rendering limitations):.*$", "", report.read_text(encoding="utf-8"), flags=re.MULTILINE), encoding="utf-8")
        with report.open("a", encoding="utf-8") as handle:
            handle.write("\n## Authored context\n\n- Description of checked scope: Exact theorem scope.\n  Includes its prerequisite.\n- Final confidence: Limited by source review.\n- Tooling, extraction, or rendering limitations: Equations are preserved as TeX.\n")
        pc.report_module("proofcheck_release").migrate(pc, self.root)
        context = fixtures.read_json(self.root / "AUDIT_MANIFEST.json")["report_context"]
        self.assertIn("Includes its prerequisite.", context["Description of checked scope"])
        self.assertEqual("Limited by source review.", context["Final confidence"])
        self.assertIn("preserved as TeX", context["Tooling, extraction, or rendering limitations"])

    def test_one_render_refreshes_changed_declaration_metadata(self):
        self.migrate_complete()
        path = self.root / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(path)
        manifest["report_deliverables"][0]["issue_ids"] = ["outdated-id"]
        fixtures.write_json(path, manifest)
        pc.report_module("proofcheck_release").render_working(pc, self.root)
        manifest = fixtures.read_json(path)
        self.assertEqual([], pc.report_module("proofcheck_release").validate(pc, self.root, manifest, final=False))
        self.assertEqual({"R001"}, {row["id"] for row in manifest["report_deliverables"]})

    def test_malformed_release_and_source_snapshot_return_nonfinal(self):
        self.migrate_complete()
        path = self.root / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(path)
        manifest["report_release"] = []
        self.assertIn("report_release must be an object", pc.report_module("proofcheck_release").validate(pc, self.root, manifest))
        manifest["source_snapshot"] = {"files": [{}]}
        fixtures.write_json(path, manifest)
        errors, result = pc.report_module("proofcheck_release").finalize(pc, self.root)
        self.assertTrue(errors)
        self.assertEqual("NONFINAL", result["delivery_status"])

    def test_changed_visible_html_cannot_be_resealed_by_restamping_hash(self):
        self.migrate_complete()
        self.finalize()
        report = self.root / "proofcheck-report.html"
        report.write_text(report.read_text(encoding="utf-8").replace("</body>", "<p>The result is false.</p></body>"), encoding="utf-8")
        path = self.root / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(path)
        manifest["report_deliverables"][0]["sha256"] = pc.sha256_file(report)
        fixtures.write_json(path, manifest)
        errors, _ = pc.check_audit_finalization(self.root)
        self.assertTrue(any("canonical rendered report" in error for error in errors), errors)
        self.assertFalse(pc.check_finalization_freshness(self.root)["usable_finalization"])

    def legacy_complete(self):
        self.migrate_complete()
        path = self.root / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(path)
        manifest["report_contract"]["primary"] = "audit/06_reports/FINAL_REPORT.html"
        fixtures.write_json(path, manifest)
        pc.report_module("proofcheck_release").render_working(pc, self.root)
        (self.root / "proofcheck-report.html").unlink()
        self.finalize()

    def test_legacy_location_remains_supported_until_explicit_relocation(self):
        self.legacy_complete()
        manifest = fixtures.read_json(self.root / "AUDIT_MANIFEST.json")
        self.assertEqual("audit/06_reports/FINAL_REPORT.html", pc.preferred_report_path(manifest))
        self.assertFalse((self.root / "proofcheck-report.html").exists())
        self.assertTrue(pc.check_finalization_freshness(self.root)["usable_finalization"])

    def test_relocation_preserves_original_seal_and_has_one_active_report(self):
        self.legacy_complete()
        originals = {name: (self.root / name).read_bytes() for name in (
            "AUDIT_MANIFEST.json", "audit/06_reports/FINAL_REPORT.html",
            "audit/06_reports/FINALIZATION.json")}
        ledgers = {path: path.read_bytes() for path in (self.root / "audit/04_local_checks").glob("*") if path.is_file()}
        api = pc.report_module("proofcheck_release")
        result = api.migrate(pc, self.root, top_level=True)
        self.assertEqual("NONFINAL", result["delivery_status"])
        self.assertEqual(str(self.root / "proofcheck-report.html"), result["report"])
        for relative, original in originals.items():
            self.assertEqual(original, (Path(result["history"]) / Path(relative).name).read_bytes())
        self.assertFalse((self.root / "audit/06_reports/FINAL_REPORT.html").exists())
        self.assertFalse((self.root / "audit/06_reports/FINALIZATION.json").exists())
        self.assertEqual(ledgers, {path: path.read_bytes() for path in ledgers})
        self.assertFalse(pc.check_finalization_freshness(self.root)["usable_finalization"])
        history_before = list((self.root / "audit/06_reports/history").glob("report-location-*"))
        api.migrate(pc, self.root, top_level=True)
        self.assertEqual(history_before, list((self.root / "audit/06_reports/history").glob("report-location-*")))
        self.finalize()
        self.assertTrue(pc.check_finalization_freshness(self.root)["usable_finalization"])
        progress = fixtures.read_json(self.root / "PROGRESS.json")
        self.assertIn("Audit finalized.", progress["next_action"])
        self.assertIn("proofcheck-report.html", progress["next_action"])

    def test_failed_relocation_restores_original_report_and_seal(self):
        self.legacy_complete()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        original = Path.unlink
        old_report = self.root / "audit/06_reports/FINAL_REPORT.html"
        def fail_remove(path, *args, **kwargs):
            if path == old_report:
                raise OSError("injected old report removal failure")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", fail_remove):
            with self.assertRaisesRegex(OSError, "injected"):
                pc.report_module("proofcheck_release").migrate(pc, self.root, top_level=True)
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_renderer_only_note_requires_unchanged_evidence_and_sources(self):
        self.migrate_complete()
        self.finalize()
        api = pc.report_module("proofcheck_release")
        with mock.patch.object(api, "renderer_identity", return_value="f" * 64):
            freshness = pc.check_finalization_freshness(self.root)
            self.assertFalse(freshness["usable_finalization"])
            self.assertIsNotNone(api.presentation_refresh_note(pc, self.root, freshness))
            source = pc.resolve_stored_path(fixtures.read_json(self.root / "AUDIT_MANIFEST.json")["paper_file"], self.root)
            source.write_text(source.read_text(encoding="utf-8") + "\nChanged source.\n", encoding="utf-8")
            self.assertIsNone(api.presentation_refresh_note(pc, self.root, freshness))

    def test_failed_finalization_preserves_recorded_active_work(self):
        self.migrate_complete()
        path = self.root / "PROGRESS.json"
        progress = fixtures.read_json(path)
        progress.update(active_unit="lem:main", next_action="Resolve the active mathematical review before finalization.")
        fixtures.write_json(path, progress)
        before = path.read_bytes()
        errors, result = pc.report_module("proofcheck_release").finalize(pc, self.root)
        self.assertTrue(errors)
        self.assertEqual("NONFINAL", result["delivery_status"])
        self.assertEqual(before, path.read_bytes())

    def test_unsupported_report_location_does_not_write_outside_audit(self):
        self.migrate_complete()
        path = self.root / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(path)
        manifest["report_contract"]["primary"] = "../outside.html"
        fixtures.write_json(path, manifest)
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        api = pc.report_module("proofcheck_release")
        self.assertTrue(api.validate(pc, self.root, manifest, final=False))
        with self.assertRaisesRegex(ValueError, "report_contract.primary"):
            api.render_working(pc, self.root)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertFalse((self.root.parent / "outside.html").exists())

    def test_interrupted_publication_restores_working_report(self):
        self.migrate_complete()
        pc.sync_workflow_views(self.root)
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        original = pc.os.replace
        destination = self.root / "audit/06_reports/FINALIZATION.json"
        def fail_commit(source, target):
            if Path(target) == destination:
                raise OSError("injected finalization publication failure")
            return original(source, target)
        with mock.patch.object(pc.os, "replace", side_effect=fail_commit):
            with self.assertRaisesRegex(OSError, "injected"):
                with contextlib.redirect_stdout(io.StringIO()):
                    pc.cmd_finalize(argparse.Namespace(root=self.root))
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        self.assertFalse(pc.check_finalization_freshness(self.root)["usable_finalization"])


if __name__ == "__main__":
    unittest.main()
