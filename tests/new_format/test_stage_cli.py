"""The stage workflow and release continuation as exercised by an operator."""
import json
from pathlib import Path
from unittest.mock import patch

from support import CLI_ENV, R, TempCase, edit, node_available, run_cli
from paper_core import cli, publish
from paper_core.canonical import sha256_bytes
from paper_core.errors import PublicationError


class StageCliTests(TempCase):
    def test_default_review_waits_for_full_primary_but_explicit_subset_can_run(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            unfinished = fixture.check_edit("chk_draft", R("groups", "grp_thm"), "derivation", state="draft",
                outcome=None, supersedes=fixture.pin(db, "checks", "chk_der_thm"))
            unfinished["body"]["next_action"] = "Examine the remaining step."
            fixture.apply(db, [unfinished], *fixture.ITEMS, mode="primary")
        arguments = ("stage2", "prepare", fixture.path, "--audit", "aud_1", "--mode", "independent",
                     "--focus", "items:itm_lem", "--out", self.work / "packet")
        blocked, _ = run_cli(*arguments)
        self.assertFalse(blocked["prepared"])
        self.assertEqual("stage1_not_ready", blocked["preparation"]["reason"])
        ready, _ = run_cli(*arguments, "--ready-subset")
        self.assertTrue(ready["prepared"])
        self.assertTrue(ready["scope_limited"])
        status, _ = run_cli("status", fixture.path, "--audit", "aud_1")
        self.assertFalse(status["stages"]["stage1"]["ready"])

    def test_global_size_retry_keeps_stage_and_runs(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        with fixture.open() as db:
            audit = db.head("audits", "aud_1")
            tasks = [dict(row) for row in audit.body["global_tasks"]]
            tasks[0].update(applicability="required", reason="Cross-result consistency needs examination.")
            fixture.apply(db, [edit("replace", "audits", "aud_1", dict(audit.body, global_tasks=tasks), audit.version)],
                          *fixture.ITEMS, mode="primary")
        result, _ = run_cli("stage2", "prepare", fixture.path, "--audit", "aud_1", "--mode", "global",
                            "--max-bytes", 1, "--out", self.work / "global")
        self.assertFalse(result["prepared"])
        command = result["preparation"]["size_action"]["command"]
        self.assertEqual(["stage2", "prepare"], command[1:3])
        self.assertEqual("global", command[command.index("--mode") + 1])
        retried, _ = run_cli(*command[1:])
        self.assertTrue(retried["prepared"])

    def test_finalize_does_not_need_node_and_build_does_not_need_database(self):
        if not node_available():
            self.skipTest("Node required for delivery")
        fixture = self.fixture().complete()
        bundle = self.work / "frozen"
        result, _ = run_cli("stage2", "finalize", fixture.path, "--audit", "aud_1", "--out", bundle,
                            env=dict(CLI_ENV, PATH=""))
        self.assertEqual({"report-snapshot.json", "finalization.json"}, {p.name for p in bundle.iterdir()})
        fixture.path.rename(fixture.path.with_suffix(".offline"))
        page = self.work / "report.html"
        built, _ = run_cli("stage3", "build", bundle, "--out", page)
        self.assertEqual(result["revision"], built["revision"])
        self.assertEqual("release", built["kind"])
        self.assertEqual(sha256_bytes(page.read_bytes()), built["artifact_sha256"])
        repeated, _ = run_cli("stage3", "build", bundle, "--out", page)
        self.assertTrue(repeated["reused"])


class ReleaseResumeTests(TempCase):
    def setUp(self):
        super().setUp()
        if not node_available():
            self.skipTest("Node required for delivery")

    def test_resume_after_render_failure_delivers_old_revision_after_live_edit(self):
        fixture = self.fixture().complete()
        output = self.work / "release"
        failed, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", output,
                             expect=6, env=dict(CLI_ENV, PATH=""))
        failure = next(row for row in failed["error"]["records"] if "resume_command" in row)
        bundle = Path(failure["preparation_directory"])
        frozen_export = (bundle / "export.json").read_bytes()
        run_cli("attach", fixture.path, "--report", "another-report.html")
        current, _ = run_cli("status", fixture.path, "--audit", "aud_1")
        self.assertGreater(current["revision"], failure["revision"])
        delivered, _ = run_cli(*failure["resume_command"][1:])
        self.assertEqual(failure["revision"], delivered["revision"])
        self.assertEqual(frozen_export, (output / "export.json").read_bytes())
        self.assertEqual({"report.html", "export.json", "receipt.json"}, {p.name for p in output.iterdir()})
        self.assertFalse(bundle.exists())
        after, _ = run_cli("status", fixture.path, "--audit", "aud_1")
        self.assertEqual(current["revision"], after["revision"])

    def test_receipt_failure_resumes_without_rerendering_or_new_publication(self):
        fixture = self.fixture().complete()
        output = self.work / "release"
        args = cli.build_parser().parse_args(["release", str(fixture.path), "--audit", "aud_1", "--out", str(output)])
        with patch.object(cli, "_write_json", side_effect=OSError("simulated full disk")):
            with self.assertRaises(PublicationError) as caught:
                cli.cmd_release(args)
        failure = next(row for row in caught.exception.records if "resume_command" in row)
        first = (output / "report.html").read_bytes()
        args = cli.build_parser().parse_args(failure["resume_command"][1:])
        with patch.object(publish, "render_payload", side_effect=AssertionError("must reuse delivered HTML")):
            delivered = cli.cmd_release(args)
        self.assertEqual(first, (output / "report.html").read_bytes())
        with fixture.open(write=False) as db:
            self.assertEqual(1, len(db.publications()))
        self.assertEqual(delivered["snapshot_sha256"], json.loads((output / "receipt.json").read_text())["snapshot_sha256"])
