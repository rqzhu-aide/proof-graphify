"""Relative paths keep the same source, database and delivery destinations."""
from __future__ import annotations

from contextlib import chdir
import json
import subprocess
import sys
import unittest
from pathlib import Path

from support import CLI_ENV, PAPER_TEX, REPO, TempCase, run_cli, write_json
from paper_core import finalization, publish, sources, storage
from paper_core.errors import InvalidRequest


class V3PathTests(TempCase):
    def test_relative_roots_initialize_capture_and_reopen(self):
        for root_argument in (".", "../source space λ"):
            with self.subTest(source_root=root_argument):
                case = self.work / ("current" if root_argument == "." else "sibling")
                caller = case / "caller"
                caller.mkdir(parents=True)
                source_root = caller if root_argument == "." else case / "source space λ"
                source_root.mkdir(exist_ok=True)
                (source_root / "paper.tex").write_bytes(PAPER_TEX.encode("utf-8"))
                listing = write_json(caller / "files.json", ["paper.tex"])
                initialized, _ = run_cli("init", "../paper.db", "--source-root", root_argument,
                                         "--title", "Relative paths", cwd=caller)
                captured, _ = run_cli("source", "capture", "../paper.db", "--files", listing.name,
                                      cwd=caller)
                self.assertTrue(captured["changed"])
                self.assertEqual(["paper.tex"], [row["path"] for row in captured["sources"]])
                self.assertTrue((case / "paper.db").is_file())
                with chdir(caller), storage.Database("../paper.db") as db:
                    paper = storage.paper_record(db)
                    self.assertEqual(initialized["paper_id"], paper.id)
                    self.assertEqual(source_root.resolve().as_posix(), paper.body["source_root"])
                    source = db.heads("sources")[0]
                    self.assertEqual(PAPER_TEX.encode("utf-8"), db.get_blob(source.body["blob_sha256"]))
                    discovered, _ = sources.discover(root_argument, ["paper.tex"])
                    self.assertEqual(["paper.tex"], [row["path"] for row in discovered])
                    self.assertEqual(PAPER_TEX.encode("utf-8"), discovered[0]["bytes"])

    def test_missing_relative_root_does_not_create_a_database(self):
        caller = self.work / "caller"
        caller.mkdir()
        result, _ = run_cli("init", "../paper.db", "--source-root", "../missing",
                            "--title", "Missing source", expect=5, cwd=caller)
        self.assertEqual("SOURCE_UNAVAILABLE", result["error"]["code"])
        self.assertEqual(["caller"], sorted(path.name for path in self.work.iterdir()))

    def test_existing_relative_destinations_are_never_replaced(self):
        caller = self.work / "caller"
        caller.mkdir()
        existing = self.work / "existing.db"
        existing.write_bytes(b"existing destination")
        result, _ = run_cli("init", "../existing.db", "--source-root", ".",
                            "--title", "Existing destination", expect=2, cwd=caller)
        self.assertIn("refusing to overwrite", result["error"]["message"])
        self.assertEqual(b"existing destination", existing.read_bytes())
        with self.subTest(destination="dangling symlink"):
            link, target = self.work / "linked.db", self.work / "missing-target.db"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            result, _ = run_cli("init", "../linked.db", "--source-root", ".",
                                "--title", "Linked destination", expect=2, cwd=caller)
            self.assertIn("refusing to overwrite", result["error"]["message"])
            self.assertTrue(link.is_symlink())
            self.assertFalse(target.exists())

    def test_relative_output_aliases_preserve_protected_files(self):
        fixture = self.fixture("audit").audit(independent_required=False).primary()
        caller = self.work / "caller"
        caller.mkdir()
        bundle = self.work / "frozen"
        with fixture.open(write=False) as db:
            finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
        protected = (fixture.path, fixture.source_root / "paper.tex", bundle / finalization.SNAPSHOT_NAME)
        before = {path: path.read_bytes() for path in protected}
        with chdir(caller):
            for path in protected:
                relative = Path("..") / path.relative_to(self.work)
                with self.subTest(output=str(relative)):
                    with self.assertRaises(InvalidRequest) as caught:
                        publish.publish_frozen("../frozen", output=relative)
                    self.assertEqual("OUTPUT_CONFLICT", caught.exception.code)
        self.assertEqual(before, {path: path.read_bytes() for path in protected})

    def test_public_workflow_uses_relative_sibling_destinations(self):
        caller = self.work / "caller"
        caller.mkdir()
        process = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(REPO / "tests" / "test_v3_workflow_cli.py"),
             "../workflow space λ"],
            cwd=caller, env=CLI_ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, process.returncode, f"{process.stdout}\n{process.stderr}")
        result = json.loads(process.stdout)
        self.assertEqual("release", result["kind"])
        self.assertTrue(result["process_complete"])
        destination = self.work / "workflow space λ"
        self.assertTrue((destination / "frozen" / finalization.SNAPSHOT_NAME).is_file())
        self.assertTrue((destination / "group-a" / "group-index.json").is_file())
        self.assertTrue((destination / "primary-lemma" / "response-scaffold.json").is_file())
        if result["rendered"]:
            self.assertTrue((destination / "report.html").is_file())


if __name__ == "__main__":
    unittest.main()
