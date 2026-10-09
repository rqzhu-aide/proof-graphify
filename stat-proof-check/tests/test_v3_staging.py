"""Delivery staging preserves scientific input, prior output and the first error."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

from support import TempCase, node_available
from paper_core import finalization, publish, staging
from paper_core.errors import InvalidRequest, PublicationError


class V3StagingTests(TempCase):
    def frozen_fixture(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        bundle = self.path("frozen")
        with fixture.open(write=False) as db:
            finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
        return fixture, bundle

    def test_actual_staging_can_write_read_and_clean_its_sibling(self):
        with staging.staging_directory(self.work, ".paper-probe-") as path:
            self.assertEqual(self.work, path.parent)
            self.assertRegex(path.name, r"^\.paper-probe-[0-9a-f]{32}$")
            (path / "probe").write_bytes(b"local staging")
            self.assertEqual(b"local staging", (path / "probe").read_bytes())
        self.assertFalse(path.exists())

    def test_platform_mkdir_modes_mock_only_the_branch(self):
        # These are argument checks, not a claim to have run on a POSIX host.
        for platform, mode in (("nt", None), ("posix", 0o700)):
            with self.subTest(platform=platform), mock.patch.object(staging, "_mkdir") as mkdir:
                path = staging._create(self.work, ".paper-mode-", platform=platform)
                if mode is None:
                    mkdir.assert_called_once_with(path)
                else:
                    mkdir.assert_called_once_with(path, mode)

    def test_random_name_collision_refuses_once_and_keeps_existing_contents(self):
        existing = self.path(".paper-collision-" + "0" * 32)
        existing.mkdir()
        sentinel = existing / "keep"
        sentinel.write_bytes(b"existing contents")
        with mock.patch.object(staging, "_token_hex", return_value="0" * 32), \
                mock.patch.object(staging, "_mkdir", wraps=staging._mkdir) as mkdir, \
                mock.patch.object(staging, "_rmtree") as cleanup:
            with self.assertRaises(FileExistsError):
                with staging.staging_directory(self.work, ".paper-collision-"):
                    self.fail("collision entered the operation")
        self.assertEqual(1, mkdir.call_count)
        cleanup.assert_not_called()
        self.assertEqual(b"existing contents", sentinel.read_bytes())

    def test_permission_denial_propagates_without_retry_or_cleanup(self):
        denied = PermissionError("staging access denied")
        with mock.patch.object(staging, "_mkdir", side_effect=denied) as mkdir, \
                mock.patch.object(staging, "_rmtree") as cleanup:
            with self.assertRaises(PermissionError) as caught:
                with staging.staging_directory(self.work, ".paper-denied-"):
                    self.fail("denied creation entered the operation")
        self.assertIs(denied, caught.exception)
        self.assertEqual(1, mkdir.call_count)
        cleanup.assert_not_called()

    def test_freeze_uses_one_sibling_replace_and_skips_cleanup_after_move(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        destination = self.path("frozen")
        real_replace = finalization.os.replace

        def replace(source, output):
            self.assertEqual(destination.parent, source.parent)
            self.assertEqual(destination, output)
            self.assertEqual(source.stat().st_dev, output.parent.stat().st_dev)
            return real_replace(source, output)

        with fixture.open(write=False) as db, \
                mock.patch.object(finalization, "os", SimpleNamespace(replace=mock.Mock(side_effect=replace))) as operations, \
                mock.patch.object(staging, "_rmtree") as cleanup, \
                mock.patch.object(finalization, "derive_full", wraps=finalization.derive_full) as derive:
            result = finalization.finalize_audit(db, audit_id="aud_1", output=destination, include_export=True)
            repeated = finalization.finalize_audit(db, audit_id="aud_1", output=destination, include_export=True)
        self.assertEqual("release", result["kind"])
        self.assertTrue(repeated["reused"])
        self.assertEqual(1, derive.call_count)
        self.assertEqual(1, operations.replace.call_count)
        cleanup.assert_not_called()
        finalization.load_finalization(destination)
        self.assertTrue((destination / finalization.EXPORT_NAME).is_file())

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_actual_small_freeze_and_node_render_leave_science_unchanged(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        before_db = fixture.path.read_bytes()
        before_source = (fixture.source_root / "paper.tex").read_bytes()
        bundle, output = self.path("frozen"), self.path("report.html")
        with fixture.open(write=False) as db:
            revision = db.max_revision()
            frozen = finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
            self.assertEqual(revision, db.max_revision())
        saved = {path.name: path.read_bytes() for path in bundle.iterdir()}
        with mock.patch.object(finalization, "derive_full", side_effect=AssertionError("scientific reassessment")), \
                mock.patch.object(staging, "_create", wraps=staging._create) as create:
            result = publish.publish_frozen(bundle, output=output)
        create.assert_called_once_with(output.parent, ".paper-report-")
        self.assertEqual("published", result["state"])
        self.assertEqual(frozen["snapshot_sha256"], result["snapshot_sha256"])
        self.assertEqual("pass", result["receipt"]["renderer"]["python_acceptance"]["status"])
        self.assertEqual(result["receipt"], json.loads(Path(result["build_receipt_path"]).read_text(encoding="utf-8")))
        self.assertIn("Test paper", output.read_text(encoding="utf-8"))
        self.assertEqual(saved, {path.name: path.read_bytes() for path in bundle.iterdir()})
        self.assertEqual(before_db, fixture.path.read_bytes())
        self.assertEqual(before_source, (fixture.source_root / "paper.tex").read_bytes())
        self.assertFalse(list(self.work.glob(".paper-report-*")))

    def test_freeze_refuses_nonempty_destination_before_staging_or_assessment(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        destination = self.path("existing")
        destination.mkdir()
        sentinel = destination / "keep"
        sentinel.write_bytes(b"prior output")
        with fixture.open(write=False) as db, mock.patch.object(staging, "_create") as create, \
                mock.patch.object(finalization, "derive_full") as derive:
            with self.assertRaises(InvalidRequest):
                finalization.finalize_audit(db, audit_id="aud_1", output=destination)
        create.assert_not_called()
        derive.assert_not_called()
        self.assertEqual(b"prior output", sentinel.read_bytes())

    def test_protected_output_collisions_refuse_before_render_or_staging(self):
        fixture, bundle = self.frozen_fixture()
        protected = (fixture.path, fixture.source_root / "paper.tex", bundle / finalization.SNAPSHOT_NAME)
        before = {path: path.read_bytes() for path in protected}
        for output in protected:
            with self.subTest(output=output), mock.patch.object(staging, "_create") as create, \
                    mock.patch.object(publish, "render_payload") as render:
                with self.assertRaises(InvalidRequest) as caught:
                    publish.publish_frozen(bundle, output=output)
            self.assertEqual("OUTPUT_CONFLICT", caught.exception.code)
            create.assert_not_called()
            render.assert_not_called()
        self.assertEqual(before, {path: path.read_bytes() for path in protected})

    def test_freeze_write_error_survives_cleanup_error(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        before = fixture.path.read_bytes()
        destination = self.path("failed-freeze")
        primary = PermissionError("primary snapshot write failure")
        real_write = Path.write_bytes

        def write(path, data):
            if path.name == finalization.SNAPSHOT_NAME and path.parent.name.startswith(".paper-freeze-"):
                raise primary
            return real_write(path, data)

        with fixture.open(write=False) as db, mock.patch.object(Path, "write_bytes", autospec=True, side_effect=write), \
                mock.patch.object(staging, "_create", wraps=staging._create) as create, \
                mock.patch.object(staging, "_rmtree", side_effect=PermissionError("secondary cleanup failure")) as cleanup, \
                mock.patch.object(finalization, "derive_full", wraps=finalization.derive_full) as derive:
            with self.assertRaises(PermissionError) as caught:
                finalization.finalize_audit(db, audit_id="aud_1", output=destination)
        self.assertIs(primary, caught.exception)
        self.assertIn("secondary cleanup failure", " ".join(primary.__notes__))
        self.assertEqual(1, create.call_count)
        self.assertEqual(1, cleanup.call_count)
        self.assertEqual(1, derive.call_count)
        self.assertFalse(destination.exists())
        self.assertEqual(before, fixture.path.read_bytes())

    def test_frozen_render_preserves_primary_and_cleanup_details(self):
        fixture, bundle = self.frozen_fixture()
        output = self.path("report.html")
        receipt = output.with_name(output.name + ".receipt.json")
        output.write_bytes(b"previous report")
        receipt.write_bytes(b"previous receipt")
        science = {path.name: path.read_bytes() for path in bundle.iterdir()}
        for primary in (PermissionError("primary render write failure"), PublicationError("primary renderer failure")):
            with self.subTest(error=type(primary).__name__), \
                    mock.patch.object(publish, "render_payload", side_effect=primary) as render, \
                    mock.patch.object(staging, "_create", wraps=staging._create) as create, \
                    mock.patch.object(staging, "_rmtree", side_effect=PermissionError("secondary cleanup failure")) as cleanup:
                with self.assertRaises(PublicationError) as caught:
                    publish.publish_frozen(bundle, output=output)
            self.assertIn(str(primary), str(caught.exception))
            self.assertIn("secondary cleanup failure", " ".join(caught.exception.__notes__))
            self.assertIn("secondary cleanup failure", json.dumps(caught.exception.to_json()))
            if isinstance(primary, PublicationError):
                self.assertIs(primary, caught.exception)
            self.assertEqual(1, render.call_count)
            self.assertEqual(1, create.call_count)
            self.assertEqual(1, cleanup.call_count)
            self.assertTrue(caught.exception.records[-1]["prior_output_retained"])
            self.assertTrue(caught.exception.records[-1]["prior_receipt_retained"])
            self.assertEqual(b"previous report", output.read_bytes())
            self.assertEqual(b"previous receipt", receipt.read_bytes())
        self.assertEqual(science, {path.name: path.read_bytes() for path in bundle.iterdir()})

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_receipt_replace_failure_restores_prior_valid_output(self):
        fixture, bundle = self.frozen_fixture()
        output = self.path("report.html")
        receipt = self.path("receipts", "build.json")
        published = publish.publish_frozen(bundle, output=output, receipt_output=receipt)
        before_html, before_receipt = output.read_bytes(), receipt.read_bytes()
        real_replace = publish._replace_file
        replacements = []

        def replace(staged, destination):
            self.assertEqual(staged.stat().st_dev, destination.parent.stat().st_dev)
            replacements.append(destination)
            if destination == receipt:
                self.assertEqual(b"replacement HTML", output.read_bytes())
                raise PermissionError("receipt replacement failure")
            return real_replace(staged, destination)

        with mock.patch.object(publish, "render_payload", return_value=(b"replacement HTML", published["receipt"]["renderer"])) as render, \
                mock.patch.object(publish, "_replace_file", side_effect=replace):
            with self.assertRaisesRegex(PublicationError, "receipt replacement failure"):
                publish.publish_frozen(bundle, output=output, receipt_output=receipt)
        render.assert_called_once()
        self.assertEqual([output, receipt], replacements)
        self.assertEqual(before_html, output.read_bytes())
        self.assertEqual(before_receipt, receipt.read_bytes())
        self.assertFalse(list(receipt.parent.glob(".paper-build-*")))
        self.assertFalse(list(self.work.glob(".paper-report-*")))


if __name__ == "__main__":
    unittest.main()
