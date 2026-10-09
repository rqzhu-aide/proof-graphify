"""Compatibility release can recover after the public receipt rename fails."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support import TempCase, edit
from paper_core import assessment, cli, finalization, publish
from paper_core.canonical import sha256_bytes
from paper_core.errors import InvalidRequest, PublicationError


def delivered_report(bundle, *, output, db, receipt_output):
    """Exercise CLI file delivery independently of Node rendering."""
    snapshot, frozen = finalization.load_finalization(bundle)
    html = f"<html>{frozen['snapshot_sha256']}</html>".encode("utf-8")
    Path(output).write_bytes(html)
    publication = {"publication_id": "pub_fixture", "revision": snapshot["revision"], "kind": snapshot["kind"],
        "state": "published", "output_path": str(output), "artifact_sha256": sha256_bytes(html), "receipt": {}}
    Path(receipt_output).write_text(json.dumps({"snapshot_sha256": frozen["snapshot_sha256"],
        "artifact_sha256": publication["artifact_sha256"]}), encoding="utf-8")
    return publication


class ReleaseResumeAdversarialTests(TempCase):
    def test_receipt_replace_failure_resumes_the_same_frozen_revision(self):
        fx = self.fixture().complete()
        output = self.path("delivery")
        args = SimpleNamespace(db=fx.path, audit=fx.audit_id, out=output, checkpoint_out=None, resume=None)
        original_replace = os.replace

        def fail_receipt_replace(source, destination):
            if Path(destination).name == "receipt.json":
                raise OSError("simulated receipt rename failure")
            return original_replace(source, destination)

        with mock.patch.object(publish, "publish_frozen", side_effect=delivered_report):
            with mock.patch.object(cli.os, "replace", side_effect=fail_receipt_replace):
                with self.assertRaises(PublicationError) as failure:
                    cli.cmd_release(args)
            diagnostic = next(row for row in failure.exception.records if row.get("stage") == "receipt")
            preparation = Path(diagnostic["preparation_directory"])
            self.assertTrue((preparation / "report-snapshot.json").is_file())
            self.assertTrue((preparation / "export.json").is_file())
            snapshot_bytes = (preparation / "report-snapshot.json").read_bytes()
            revision = diagnostic["revision"]
            with fx.open() as db:
                item = db.head("items", "itm_lem")
                fx.apply(db, [edit("replace", "items", item.id, dict(item.body, label="Edited after freeze"), item.version)])
                self.assertGreater(db.max_revision(), revision)
            args.resume = str(preparation)
            with mock.patch.object(finalization, "finalize_audit", side_effect=AssertionError("must reuse frozen preparation")), \
                    mock.patch.object(assessment, "derive_full", side_effect=AssertionError("must not reexamine live audit")):
                resumed = cli.cmd_release(args)
            self.assertEqual(revision, resumed["revision"])
            self.assertEqual(["export.json", "receipt.json", "report.html"], sorted(path.name for path in output.iterdir()))
            self.assertEqual(sha256_bytes(snapshot_bytes), resumed["snapshot_sha256"])

    def interrupted_release(self):
        fx = self.fixture().complete()
        output = self.path("delivery")
        args = SimpleNamespace(db=fx.path, audit=fx.audit_id, out=output, checkpoint_out=None, resume=None)
        with mock.patch.object(publish, "publish_frozen", side_effect=delivered_report), \
                mock.patch.object(cli, "_write_json", side_effect=OSError("simulated receipt delivery failure")):
            with self.assertRaises(PublicationError) as failure:
                cli.cmd_release(args)
        diagnostic = next(row for row in failure.exception.records if row.get("stage") == "receipt")
        args.resume = diagnostic["preparation_directory"]
        return fx, args, Path(args.resume)

    def test_preexisting_public_receipt_is_preserved_even_with_matching_snapshot_hash_or_malformed_shape(self):
        fx, args, preparation = self.interrupted_release()
        _, frozen = finalization.load_finalization(preparation)
        output = Path(args.out)
        retained = {path.name: path.read_bytes() for path in preparation.iterdir()}
        for value in ({"snapshot_sha256": frozen["snapshot_sha256"], "revision": -1, "note": "Preserve my receipt"},
                      [], None, "Preserve this text"):
            with self.subTest(value=value):
                receipt = output / "receipt.json"
                receipt.write_text(json.dumps(value), encoding="utf-8")
                public = {path.name: path.read_bytes() for path in output.iterdir()}
                with mock.patch.object(publish, "publish_frozen", side_effect=AssertionError("must refuse existing receipt before delivery")):
                    with self.assertRaises(InvalidRequest):
                        cli.cmd_release(args)
                self.assertEqual(public, {path.name: path.read_bytes() for path in output.iterdir()})
                self.assertEqual(retained, {path.name: path.read_bytes() for path in preparation.iterdir()})

    def test_wrong_audit_database_or_output_refuses_resume_without_changing_any_artifacts(self):
        fx, args, preparation = self.interrupted_release()
        other = self.fixture("other").complete()
        public = {path.name: path.read_bytes() for path in Path(args.out).iterdir()}
        retained = {path.name: path.read_bytes() for path in preparation.iterdir()}
        for field, value in (("audit", "aud_other"), ("db", other.path), ("out", self.path("other_output"))):
            with self.subTest(field=field):
                wrong = SimpleNamespace(**{**vars(args), field: value})
                with mock.patch.object(publish, "publish_frozen", side_effect=AssertionError("must refuse mismatched frozen request")):
                    with self.assertRaises(InvalidRequest):
                        cli.cmd_release(wrong)
                self.assertEqual(public, {path.name: path.read_bytes() for path in Path(args.out).iterdir()})
                self.assertEqual(retained, {path.name: path.read_bytes() for path in preparation.iterdir()})
