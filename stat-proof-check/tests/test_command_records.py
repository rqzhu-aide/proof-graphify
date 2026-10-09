from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck_usage.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_command_records", SCRIPT)
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)


class CommandRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.root = self.workspace / "audit with spaces"
        (self.root / "audit").mkdir(parents=True)
        (self.root / "AUDIT_MANIFEST.json").write_text("{}", encoding="utf-8")
        self.records = self.workspace / "work" / "command records"
        self.scripts = self.workspace / "scripts"
        self.scripts.mkdir()
        (self.scripts / "proofcheck.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'errors': 1, 'status': 'not_ready', "
            "'large_detail': 'x'*20000, 'argument': sys.argv[1:]}))\n"
            "sys.stderr.buffer.write('Exact diagnostic: β ≤ 1\\n'.encode('utf-8'))\n"
            "sys.exit(7)\n",
            encoding="utf-8",
        )
        patch = mock.patch.object(usage, "__file__", str(self.scripts / "usage.py"))
        patch.start()
        self.addCleanup(patch.stop)

    def args(self, records=None):
        return usage.build_parser().parse_args([
            "run", "--root", str(self.root), "--records", str(records or self.records),
            "--stage", "primary", "--", "ledger-check", "a file with spaces.json",
        ])

    def test_failed_command_keeps_complete_output_and_returns_failure(self):
        before = (self.root / "AUDIT_MANIFEST.json").read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = usage.cmd_run(self.args())
        summary = json.loads(output.getvalue())
        directory = Path(summary["record_directory"])
        start = json.loads((directory / "start.json").read_text())
        end = json.loads((directory / "end.json").read_text())
        full_output = json.loads((directory / "stdout.txt").read_text())
        self.assertEqual(7, code)
        self.assertEqual(7, summary["exit_code"])
        self.assertEqual({"errors": 1, "status": "not_ready"}, summary["reported_summary"])
        self.assertEqual(20000, len(full_output["large_detail"]))
        self.assertEqual(["ledger-check", "a file with spaces.json"], full_output["argument"])
        self.assertEqual("Exact diagnostic: β ≤ 1\n", (directory / "stderr.txt").read_text(encoding="utf-8"))
        self.assertEqual(start["started_utc"], end["started_utc"])
        self.assertEqual(64, len(start["core_script_sha256"]))
        self.assertNotIn("validator_sha256", start)
        self.assertGreaterEqual(end["ended_utc"], start["started_utc"])
        self.assertGreaterEqual(end["elapsed_seconds"], 0)
        self.assertNotIn("large_detail", summary)
        self.assertEqual(before, (self.root / "AUDIT_MANIFEST.json").read_bytes())
        self.assertEqual([], list((self.root / "audit").iterdir()))

    def test_each_parallel_run_retains_its_own_receipts(self):
        with contextlib.redirect_stdout(io.StringIO()), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: usage.cmd_run(self.args()), range(2)))
        self.assertEqual([7, 7], results)
        folders = list(self.records.iterdir())
        self.assertEqual(2, len(folders))
        snapshots = {f.name: (f / "start.json").read_bytes() for f in folders}
        with contextlib.redirect_stdout(io.StringIO()):
            usage.cmd_run(self.args())
        self.assertEqual(3, len(list(self.records.iterdir())))
        for folder in folders:
            self.assertEqual(snapshots[folder.name], (folder / "start.json").read_bytes())
            self.assertTrue((folder / "end.json").is_file())

    def test_launch_failure_has_a_durable_end_record(self):
        with mock.patch.object(usage.subprocess, "run", side_effect=OSError("launch failed")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(2, usage.cmd_run(self.args()))
        end = json.loads(next(self.records.glob("*/end.json")).read_text())
        self.assertIsNone(end["exit_code"])
        self.assertIn("launch failed", end["failure"])
        self.assertTrue(next(self.records.glob("*/start.json")).is_file())

    def test_receipts_cannot_modify_the_audit_tree(self):
        with self.assertRaisesRegex(ValueError, "outside the audit root"):
            usage.cmd_run(self.args(records=self.root / "audit" / "records"))
        self.assertEqual([], list((self.root / "audit").iterdir()))

    def test_different_child_root_is_rejected_before_records_are_created(self):
        other = self.workspace / "other audit"
        (other / "audit").mkdir(parents=True)
        (other / "AUDIT_MANIFEST.json").write_text("{}", encoding="utf-8")
        for values in (["--root", str(other)], ["--root=" + str(other)],
                       ["--root", str(self.root), "--root", str(other)]):
            with self.subTest(values=values):
                args = self.args()
                args.proofcheck_args = ["--", "status", *values]
                with self.assertRaisesRegex(ValueError, "must match"):
                    usage.cmd_run(args)
                self.assertFalse(self.records.exists())
        args.proofcheck_args = ["--", "status", "--root=" + str(self.root)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(7, usage.cmd_run(args))

    def test_non_json_and_non_utf8_output_is_not_misreported(self):
        path = self.workspace / "raw output"
        path.write_bytes(b"\xff ERROR: cannot parse\n")
        self.assertEqual({}, usage.command_output_summary(path))
        path.write_text('["not a status object"]', encoding="utf-8")
        self.assertEqual({}, usage.command_output_summary(path))


if __name__ == "__main__":
    unittest.main()
