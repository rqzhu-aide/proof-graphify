"""Both products share generated core files while retaining their own entrypoints."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_paper_core_bundles as builder


class BundleTargetTests(unittest.TestCase):
    def test_cli_selects_both_or_one_product(self):
        expected = {"proof-graphify": builder.ROOT / "proof-graphify",
                    "stat-proof-check": builder.ROOT / "stat-proof-check"}
        self.assertEqual(builder.PACKAGES, expected)
        self.assertEqual(builder.REPOSITORIES, {"proof-graphify": builder.ROOT})
        for name in (None, *expected):
            for checking in (False, True):
                arguments = (["--check"] if checking else []) + (["--package", name] if name else [])
                selected = {name: expected[name]} if name else expected
                with self.subTest(arguments=arguments), \
                        patch.object(builder, "build", return_value={"ok": True}) as build, \
                        patch.object(builder, "check", return_value={"ok": True}) as check, \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(builder.main(arguments), 0)
                (check if checking else build).assert_called_once_with(selected)
                (build if checking else check).assert_not_called()

    def test_unknown_target_fails_before_mutation(self):
        with patch.object(builder, "build") as build, contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            builder.main(["--package", "not-a-skill"])
        self.assertEqual(raised.exception.code, 2)
        build.assert_not_called()

    def fixture(self, root):
        source = root / "source"
        for relative in ("cli.py", "schema.sql", "renderer/render_projection.mjs", "ids.py"):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture content\n", encoding="utf-8")
        packages = {name: root / name for name in builder.PACKAGES}
        for name, package in packages.items():
            for relative in builder.REQUIRED_ENTRYPOINTS[name]:
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name + " entrypoint\n", encoding="utf-8")
        return source, packages

    def test_different_workflow_entrypoints_and_identical_core_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            source, packages = self.fixture(Path(directory))
            with patch.object(builder, "SOURCE", source):
                built = builder.build(packages)
                checked = builder.check(packages)
                self.assertTrue(checked["ok"])
                self.assertTrue(checked["bundles_identical"])
                self.assertTrue(checked["entrypoints_present"])
                self.assertFalse(checked["wrappers_identical"])
                self.assertEqual(built["source_identity"], checked["source_identity"])
                manifests = [(p / builder.BUNDLE_DIR / builder.bundle.MANIFEST_NAME).read_bytes()
                             for p in packages.values()]
                self.assertEqual(manifests[0], manifests[1])
                self.assertEqual(json.loads(manifests[0])["write_protocols"],
                                 {"audit": ["coherent-proof-audit/1"],
                                  "overview": ["item-audit/1", "paper-overview/1", "coherent-proof-audit/1"]})

    def test_missing_product_entrypoint_fails_even_when_core_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            source, packages = self.fixture(Path(directory))
            with patch.object(builder, "SOURCE", source):
                builder.build(packages)
                (packages["proof-graphify"] / "scripts/proof_overview.py").unlink()
                checked = builder.check(packages)
                self.assertFalse(checked["ok"])
                self.assertTrue(checked["bundles_identical"])
                self.assertFalse(checked["entrypoints_present"])

    def test_matching_manifests_with_incorrect_file_count_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, packages = self.fixture(Path(directory))
            with patch.object(builder, "SOURCE", source):
                builder.build(packages)
                for package in packages.values():
                    target = package / builder.BUNDLE_DIR
                    manifest = builder.bundle.load_manifest(target)
                    manifest["file_count"] = 999
                    (target / builder.bundle.MANIFEST_NAME).write_text(
                        builder.bundle.manifest_text(manifest), encoding="utf-8")
                    self.assertFalse(builder.bundle.verify_bundle(target)["ok"])
                self.assertFalse(builder.check(packages)["ok"])

    def test_drift_cannot_be_blessed_by_a_self_consistent_local_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source, packages = self.fixture(Path(directory))
            with patch.object(builder, "SOURCE", source):
                builder.build(packages)
                target = packages["stat-proof-check"] / builder.BUNDLE_DIR
                (target / "ids.py").write_text("# destination edit\n", encoding="utf-8")
                self.assertFalse(builder.check(packages)["ok"])
                (target / builder.bundle.MANIFEST_NAME).write_text(
                    builder.bundle.manifest_text(builder.bundle.build_manifest(builder.bundle.bundle_files(target))),
                    encoding="utf-8")
                checked = builder.check(packages)
                self.assertFalse(checked["ok"])
                self.assertFalse(checked["bundles"]["stat-proof-check"]["matches_source"])

    def test_installed_manifest_command_cannot_bless_destination_edits(self):
        script = builder.ROOT / "stat-proof-check/scripts/build_manifest.py"
        manifest = script.parent / "paper_core" / builder.bundle.MANIFEST_NAME
        before = manifest.read_bytes()
        run = subprocess.run([sys.executable, "-B", str(script)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("tools/build_paper_core_bundles.py", run.stderr)
        self.assertEqual(manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
