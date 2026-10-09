"""Focused maintainer checks; real reference delivery is exercised separately."""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import install_proofcheck as installer


class RuntimeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="proofcheck-runtime-install-test-")
        self.addCleanup(self.workspace.cleanup)
        self.package = Path(self.workspace.name)
        source = Path(__file__).resolve().parents[1] / "stat-proof-check"
        shutil.copy2(source / "SKILL.md", self.package / "SKILL.md")
        (self.package / "scripts").mkdir()
        shutil.copy2(source / "scripts/paper_audit.py", self.package / "scripts/paper_audit.py")
        shutil.copytree(source / "scripts/paper_core", self.package / "scripts/paper_core")

    def test_current_runtime_verifies_without_recertifying_a_legacy_audit(self):
        receipt = installer.delivery(self.package)
        self.assertEqual(receipt["command"], "version")
        self.assertTrue(receipt["bundle"]["ok"])
        self.assertFalse((self.package / "assets/reference-audit").exists())

    def test_changed_bundle_is_rejected_even_when_the_cli_can_start(self):
        path = self.package / "scripts/paper_core/schema.sql"
        path.write_bytes(path.read_bytes() + b"\n-- changed after validation\n")
        with self.assertRaisesRegex(ValueError, "runtime or skill version is inconsistent"):
            installer.delivery(self.package)

    def test_skill_version_mismatch_is_rejected(self):
        path = self.package / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        text = installer.re.sub(r'^  version:.*$', '  version: "0.0.0"', text, flags=installer.re.MULTILINE)
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "runtime or skill version is inconsistent"):
            installer.delivery(self.package)

    def test_missing_database_entry_does_not_fall_back_to_legacy(self):
        (self.package / "scripts/paper_audit.py").unlink()
        with self.assertRaisesRegex(ValueError, "Database runtime failed"):
            installer.delivery(self.package)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="proofcheck-installer-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).resolve()
        self.source = self.root / "package"
        self.user_root = self.root / "user"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "SKILL.md").write_text("tested package", encoding="utf-8")
        (self.source / "scripts/proofcheck.py").write_text("# fixture", encoding="utf-8")
        self.target = self.user_root / ".agents/skills/stat-proof-check"
        self.delivery = patch.object(installer, "delivery", return_value={
            "delivery_status": "FINAL", "usable_finalization": True,
            "freshness": "current"}).start()
        self.addCleanup(patch.stopall)

    def test_copy_excludes_caches_and_preserves_required_bytes(self):
        for relative in ("scripts/__pycache__/module.pyc", ".pytest_cache/state",
                         "scripts/stray.pyo"):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"cache")
        receipt = installer.install(self.source, self.user_root)
        self.assertTrue(receipt["runtime_files_match"])
        self.assertEqual(installer.files(self.source), installer.files(self.target))
        self.assertFalse(any(installer.excluded(p.relative_to(self.target))
                             for p in self.target.rglob("*")))
        self.assertEqual(self.delivery.call_count, 3)

    def test_development_roots_are_excluded_but_runtime_resources_remain(self):
        development = ("tests/test_audit.py", "evals/release_gate.py")
        runtime = ("assets/canaries/calibration.json", "assets/templates/review.json",
                   "references/reporting-and-release.md", "assets/tests/example.txt")
        for relative in development + runtime:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode("utf-8"))
        before = installer.files(self.source)
        receipt = installer.install(self.source, self.user_root)
        self.assertEqual(before, installer.files(self.source))
        self.assertEqual(receipt["excluded_top_level_directories"], ["evals", "tests"])
        self.assertEqual(receipt["source_non_bytecode_file_count"], len(before))
        self.assertEqual(receipt["files"], installer.files(self.target))
        for relative in development:
            self.assertFalse((self.target / relative).exists())
        for relative in runtime:
            self.assertEqual((self.target / relative).read_bytes(),
                             (self.source / relative).read_bytes())
        self.assertEqual(self.delivery.call_count, 3)

    def test_legacy_codex_copy_rejects_without_install(self):
        duplicate = self.user_root / ".codex/skills/stat-paper-proofcheck"
        duplicate.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "Other discoverable copies"):
            installer.install(self.source, self.user_root)
        self.assertTrue(duplicate.is_dir())
        self.assertFalse(self.target.exists())
        self.delivery.assert_not_called()

    def test_upgrade_preserves_old_tree_outside_discovery(self):
        installer.install(self.source, self.user_root)
        old_bytes = (self.target / "SKILL.md").read_bytes()
        (self.target / "obsolete.txt").write_bytes(b"old release")
        for directory in ("tests", "evals"):
            (self.target / directory).mkdir()
            (self.target / directory / "old.py").write_bytes(b"previous developer material")
        (self.source / "SKILL.md").write_bytes(b"new release")
        receipt = installer.install(self.source, self.user_root, upgrade=True)
        backup = Path(receipt["backup"])
        self.assertTrue(backup.is_relative_to(self.user_root / ".agents/skill-backups"))
        self.assertEqual((backup / "SKILL.md").read_bytes(), old_bytes)
        self.assertTrue((backup / "obsolete.txt").exists())
        self.assertFalse((self.target / "obsolete.txt").exists())
        for directory in ("tests", "evals"):
            self.assertEqual((backup / directory / "old.py").read_bytes(),
                             b"previous developer material")
            self.assertFalse((self.target / directory).exists())
        self.assertEqual((self.target / "SKILL.md").read_bytes(), b"new release")

    def test_existing_install_requires_explicit_upgrade(self):
        installer.install(self.source, self.user_root)
        before = installer.files(self.target)
        with self.assertRaisesRegex(ValueError, "use --upgrade"):
            installer.install(self.source, self.user_root)
        self.assertEqual(before, installer.files(self.target))

    def test_explicit_claude_and_agents_copies_match_and_upgrade_independently(self):
        for surface in ("claude", "agents"):
            installer.install(self.source, self.user_root, surface=surface)
        before = (self.source / "SKILL.md").read_bytes()
        (self.source / "SKILL.md").write_bytes(b"new shared revision")
        for surface in ("claude", "agents"):
            receipt = installer.install(self.source, self.user_root, upgrade=True,
                                        surface=surface)
            target = self.user_root / f".{surface}/skills/stat-proof-check"
            backup = Path(receipt["backup"])
            self.assertTrue(backup.is_relative_to(self.user_root / f".{surface}/skill-backups"))
            self.assertEqual((backup / "SKILL.md").read_bytes(), before)
            self.assertEqual(installer.files(target), installer.files(self.source))
        self.assertFalse((self.user_root / ".codex").exists())

    def test_cli_defaults_to_agents_and_claude(self):
        with patch.object(installer.sys, "argv", ["install_proofcheck.py", "--source",
                          str(self.source), "--user-root", str(self.user_root)]), \
                patch("builtins.print"):
            self.assertEqual(installer.main(), 0)
        for surface in ("agents", "claude"):
            target = self.user_root / f".{surface}/skills/stat-proof-check"
            self.assertEqual(installer.files(target), installer.files(self.source))
        self.assertFalse((self.user_root / ".codex").exists())

    def test_cli_explicit_single_target_only_installs_that_target(self):
        for surface in ("agents", "claude"):
            with self.subTest(surface=surface):
                user_root = self.user_root / surface
                with patch.object(installer.sys, "argv", ["install_proofcheck.py", "--source",
                                  str(self.source), "--user-root", str(user_root),
                                  "--target", surface]), patch("builtins.print"):
                    self.assertEqual(installer.main(), 0)
                self.assertEqual({path.name for path in user_root.iterdir()}, {f".{surface}"})
                target = user_root / f".{surface}/skills/stat-proof-check"
                self.assertEqual(installer.files(target), installer.files(self.source))

    def test_codex_is_not_an_installation_target(self):
        with self.assertRaisesRegex(ValueError, "Unknown installation surface"):
            installer.install(self.source, self.user_root, surface="codex")
        with patch.object(installer.sys, "argv", ["install_proofcheck.py", "--source",
                          str(self.source), "--user-root", str(self.user_root),
                          "--target", "codex"]), patch.object(installer.sys, "stderr"), \
                self.assertRaises(SystemExit) as error:
            installer.main()
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.user_root.exists())
        self.delivery.assert_not_called()

    def test_unknown_surface_rejects_before_writes(self):
        with self.assertRaisesRegex(ValueError, "Unknown installation surface"):
            installer.install(self.source, self.user_root, surface="../outside")
        self.assertFalse(self.user_root.exists())
        self.delivery.assert_not_called()

    def test_invalid_source_is_rejected_before_mutation(self):
        installer.install(self.source, self.user_root)
        before = installer.files(self.target)
        self.delivery.side_effect = ValueError("reference rejected")
        with self.assertRaisesRegex(ValueError, "reference rejected"):
            installer.install(self.source, self.user_root, upgrade=True)
        self.assertEqual(before, installer.files(self.target))

    def test_installed_delivery_failure_restores_previous_package(self):
        installer.install(self.source, self.user_root)
        before = installer.files(self.target)
        self.delivery.side_effect = [{}, {}, ValueError("installed check failed")]
        (self.source / "SKILL.md").write_bytes(b"new release")
        with self.assertRaisesRegex(ValueError, "installed check failed"):
            installer.install(self.source, self.user_root, upgrade=True)
        self.assertEqual(before, installer.files(self.target))
        candidates = list((self.user_root / ".agents").glob("proofcheck-install-*/stat-proof-check"))
        self.assertEqual(len(candidates), 1)
        self.assertEqual((candidates[0] / "SKILL.md").read_bytes(), b"new release")

    def test_concurrent_install_is_not_replaced(self):
        def delivery(package):
            if "proofcheck-install-" in str(package):
                self.target.mkdir(parents=True)
                (self.target / "owner.txt").write_bytes(b"concurrent package")
            return {}
        self.delivery.side_effect = delivery
        with self.assertRaisesRegex(ValueError, "appeared during preparation"):
            installer.install(self.source, self.user_root, upgrade=True)
        self.assertEqual((self.target / "owner.txt").read_bytes(), b"concurrent package")

    def test_source_mutation_during_validation_rejects_even_for_excluded_files(self):
        installer.install(self.source, self.user_root)
        before = installer.files(self.target)
        for relative in ("SKILL.md", "tests/test_audit.py"):
            with self.subTest(relative=relative):
                def delivery(package):
                    if "proofcheck-install-" in str(package):
                        path = self.source / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"concurrent edit")
                    return {}
                self.delivery.side_effect = delivery
                with self.assertRaisesRegex(ValueError, "changed during validation"):
                    installer.install(self.source, self.user_root, upgrade=True)
                self.assertEqual(before, installer.files(self.target))

    def test_previous_development_file_mutation_blocks_upgrade(self):
        installer.install(self.source, self.user_root)
        old_test = self.target / "tests/old.py"
        old_test.parent.mkdir()
        old_test.write_bytes(b"previous test")
        def delivery(package):
            if "proofcheck-install-" in str(package):
                old_test.write_bytes(b"concurrent edit")
            return {}
        self.delivery.side_effect = delivery
        with self.assertRaisesRegex(ValueError, "Installation changed during preparation"):
            installer.install(self.source, self.user_root, upgrade=True)
        self.assertEqual(old_test.read_bytes(), b"concurrent edit")
        self.assertFalse((self.user_root / ".agents/skill-backups").exists())

    def test_stage_rejects_unexpected_development_files(self):
        installer.install(self.source, self.user_root)
        before = installer.files(self.target)
        def delivery(package):
            if "proofcheck-install-" in str(package):
                path = package / "tests/unexpected.py"
                path.parent.mkdir()
                path.write_bytes(b"unexpected staged file")
            return {}
        self.delivery.side_effect = delivery
        with self.assertRaisesRegex(ValueError, "changed during validation"):
            installer.install(self.source, self.user_root, upgrade=True)
        self.assertEqual(before, installer.files(self.target))

    def test_failed_backup_move_preserves_original_error_and_installation(self):
        installer.install(self.source, self.user_root)
        before = installer.files(self.target)
        with patch.object(Path, "rename", side_effect=PermissionError("backup move denied")):
            with self.assertRaisesRegex(PermissionError, "backup move denied"):
                installer.install(self.source, self.user_root, upgrade=True)
        self.assertEqual(before, installer.files(self.target))

    def test_user_root_inside_source_rejects_before_writes(self):
        before = installer.files(self.source)
        for user_root in (self.source, self.source / "nested-user"):
            with self.subTest(user_root=user_root):
                with self.assertRaisesRegex(ValueError, "outside the source package"):
                    installer.install(self.source, user_root)
                self.assertFalse((user_root / ".agents").exists())
                self.assertEqual(before, installer.files(self.source))
        self.delivery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
