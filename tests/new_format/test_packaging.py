"""Packaging and module boundary (implementation-handoff 8).

One maintained source lives at ``shared/paper_core``. ``tools/build_paper_core_bundles.py`` generates a
``scripts/paper_core/`` bundle inside each skill package; both core bundles must be byte-identical, workflow wrappers may differ, and an installed package must prove itself intact and run with no repository on the
import path. These tests pin the manifest contents, the identity algorithm, every way verification can
fail, and the isolated execution of each installed package.

Nothing here ever rebuilds the shipped bundles: the builder is only ever invoked with ``--check`` or
through ``check``/``main`` over temporary packages, and every mutation happens on a copy in a temporary
directory.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import CORE, OVERVIEW, PROOFCHECK, REPO, TOOLS, TempCase, rmtree_force, run_wrapper, sha

from paper_core import (CONTRACT_NAME, CONTRACT_VERSION, CORE_VERSION, LEGACY_OVERVIEW_FORMAT, PACKET_VERSION,
                        PROJECTION_VERSION, PROTOCOL_VERSION, STORAGE_FORMATS_READABLE, STORAGE_FORMATS_WRITABLE,
                        SUPPORTED_FEATURES, WRITE_PROTOCOLS, bundle)

# -- known-good release state ----------------------------------------------------------------------
PACKAGES = {"stat-proof-check": PROOFCHECK, "proof-graphify": OVERVIEW}
BUILDER = TOOLS / "build_paper_core_bundles.py"
MANIFEST_KEYS = {"bundle", "contract", "contract_version", "core_version", "file_count", "files",
                 "legacy_overview_format", "packet_version", "projection_version", "protocol_version",
                 "source_identity", "storage_formats_readable", "storage_formats_writable", "supported_features", "write_protocols"}
VERIFY_KEYS = {"present", "ok", "source_identity", "file_count", "missing", "unexpected", "changed",
               "constants_match"}
#: The compatibility facts a manifest publishes, with the live core value each one must carry.
RELEASE_CONSTANTS = {
    "bundle": "paper_core",
    "core_version": CORE_VERSION,
    "storage_formats_readable": list(STORAGE_FORMATS_READABLE),
    "storage_formats_writable": list(STORAGE_FORMATS_WRITABLE),
    "contract_version": CONTRACT_VERSION,
    "contract": CONTRACT_NAME,
    "packet_version": PACKET_VERSION,
    "projection_version": PROJECTION_VERSION,
    "protocol_version": PROTOCOL_VERSION,
    "write_protocols": {scope: list(values) for scope, values in WRITE_PROTOCOLS.items()},
    "supported_features": list(SUPPORTED_FEATURES),
    "legacy_overview_format": LEGACY_OVERVIEW_FORMAT,
}
#: Directories an installed skill package does not ship (handoff 8: release tests copy each package).
INSTALL_SKIP = ("tests", "evals", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git")

SOURCE_FILES = bundle.bundle_files(CORE)
BUNDLE_FILE_COUNT = len(SOURCE_FILES)
SOURCE_IDENTITY = bundle.content_identity(SOURCE_FILES)


# -- helpers ----------------------------------------------------------------------------------------
def shipped(package_root: Path) -> Path:
    return Path(package_root) / "scripts" / "paper_core"


def wrapper_path(package_root: Path) -> Path:
    return Path(package_root) / "scripts" / "paper_audit.py"


def copy_shipped_bundle(target: Path, package_root: Path = PROOFCHECK) -> Path:
    """Copy one shipped bundle so a test may mutate it without touching the repository."""
    shutil.copytree(shipped(package_root), target)
    return target


def install_package(package_root: Path, target: Path) -> Path:
    """Copy a skill package into a standalone install root, without tests, evals or caches."""
    shutil.copytree(package_root, target, ignore=shutil.ignore_patterns(*INSTALL_SKIP))
    return target


def clean_env() -> dict:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_builder(*args, expect=0):
    """Run the release builder in a subprocess; assert the exit code and return the completed process."""
    command = [sys.executable, "-B", str(BUILDER), *[str(a) for a in args]]
    proc = subprocess.run(command, cwd=str(REPO), env=clean_env(), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect} for {args}\n"
                             f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc


def builder_module():
    """Import the release builder as a fresh module so its ``check`` can run over temporary packages."""
    spec = importlib.util.spec_from_file_location("paper_core_bundle_builder_under_test", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_symlink(target: Path, link: Path) -> bool:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True


def bundle_state(root: Path) -> tuple:
    """Everything about a bundle that a read-only command must leave untouched."""
    manifest = root / bundle.MANIFEST_NAME
    return (bundle.bundle_files(root), manifest.read_bytes() if manifest.is_file() else None)


# -- which files belong to a bundle -------------------------------------------------------------------
class BundleFileSelectionTests(TempCase):
    """``bundle_files`` decides what the release identity covers."""

    def test_bundle_files_hashes_the_bytes_of_every_source_file(self):
        """Every entry is the sha256 of that file's bytes, keyed by its posix-relative path."""
        self.assertEqual(len(SOURCE_FILES), BUNDLE_FILE_COUNT)
        for relative, digest in SOURCE_FILES.items():
            self.assertEqual(digest, sha((CORE / relative).read_bytes()), relative)
            self.assertNotIn("\\", relative)  # posix separators even when the bundle is built on Windows
        for required in ("__init__.py", "cli.py", "schema.sql", "renderer/render_projection.mjs",
                         "renderer/assets/archify/template.html"):
            self.assertIn(required, SOURCE_FILES)

    def test_bundle_files_excludes_caches_byte_compiled_files_and_the_manifest(self):
        """Caches, .pyc/.pyo and the bundle's own manifest never enter the identity, at any depth."""
        root = self.path("tree")
        root.mkdir()
        for relative in ("a.py", "pkg/b.py", "pkg/data/c.json"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("keep\n", encoding="utf-8", newline="\n")
        for relative in ("__pycache__/a.cpython-314.pyc", "pkg/__pycache__/b.cpython-314.pyc",
                         "__pycache__/not_even_compiled.json", ".pytest_cache/v/cache/lastfailed",
                         ".mypy_cache/x.json", ".ruff_cache/y.bin", ".git/config", "stale.pyc",
                         "pkg/stale.pyo", bundle.MANIFEST_NAME):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("drop\n", encoding="utf-8", newline="\n")
        self.assertEqual(bundle.bundle_files(root),
                         {"a.py": sha(b"keep\n"), "pkg/b.py": sha(b"keep\n"), "pkg/data/c.json": sha(b"keep\n")})

    def test_bundle_files_excludes_only_the_bundles_own_manifest(self):
        """Only the top-level ``bundle-manifest.json`` is the bundle's own; a nested one is shipped data."""
        root = self.path("tree")
        (root / "renderer").mkdir(parents=True)
        (root / bundle.MANIFEST_NAME).write_text("{}\n", encoding="utf-8", newline="\n")
        nested = root / "renderer" / bundle.MANIFEST_NAME
        nested.write_text("{\"fixture\": true}\n", encoding="utf-8", newline="\n")
        files = bundle.bundle_files(root)
        self.assertEqual(files, {f"renderer/{bundle.MANIFEST_NAME}": sha(nested.read_bytes())})

    def test_bundle_files_ignores_directories_and_keeps_only_regular_files(self):
        """An empty directory contributes nothing: the identity is over files, not tree shape."""
        root = self.path("tree")
        (root / "empty" / "deeper").mkdir(parents=True)
        (root / "only.py").write_text("x\n", encoding="utf-8", newline="\n")
        self.assertEqual(bundle.bundle_files(root), {"only.py": sha(b"x\n")})

    def test_bundle_files_refuses_a_symlink(self):
        """A bundle may not contain links; the hash of a link target would not travel with the package."""
        root = self.path("tree")
        root.mkdir()
        real = root / "real.py"
        real.write_text("x\n", encoding="utf-8", newline="\n")
        if not make_symlink(real, root / "link.py"):
            self.skipTest("this platform/account cannot create symlinks (Windows needs SeCreateSymbolicLink)")
        with self.assertRaises(ValueError) as caught:
            bundle.bundle_files(root)
        self.assertIn("bundle links are not supported", str(caught.exception))
        self.assertIn("link.py", str(caught.exception))

    def test_bundle_files_refuses_a_link_the_os_reports_on_any_host(self):
        """The link rule is pinned even where the account cannot create one: only the OS answer is faked.

        ``bundle_files`` itself is the real function, so removing its ``is_symlink`` guard fails this
        test - and so does moving the guard inside the ``is_file`` filter, where a linked directory
        would slip through.
        """
        root = self.path("tree")
        (root / "pkg").mkdir(parents=True)
        (root / "linked_dir").mkdir()
        (root / "a.py").write_text("x\n", encoding="utf-8", newline="\n")
        (root / "pkg" / "link.py").write_text("y\n", encoding="utf-8", newline="\n")
        for name in ("link.py", "linked_dir"):
            with self.subTest(link=name):
                with mock.patch.object(Path, "is_symlink", lambda self, linked=name: self.name == linked):
                    with self.assertRaises(ValueError) as caught:
                        bundle.bundle_files(root)
                self.assertIn("bundle links are not supported", str(caught.exception))
                self.assertIn(name, str(caught.exception))
        self.assertEqual(bundle.bundle_files(root), {"a.py": sha(b"x\n"), "pkg/link.py": sha(b"y\n")})


# -- the content identity -----------------------------------------------------------------------------
class ContentIdentityTests(unittest.TestCase):
    """``content_identity`` is the release fingerprint of a file set."""

    def test_content_identity_is_order_independent(self):
        """Insertion order of the mapping cannot change the fingerprint."""
        forward = dict(sorted(SOURCE_FILES.items()))
        backward = dict(sorted(SOURCE_FILES.items(), reverse=True))
        self.assertNotEqual(list(forward), list(backward))
        self.assertEqual(bundle.content_identity(forward), SOURCE_IDENTITY)
        self.assertEqual(bundle.content_identity(backward), SOURCE_IDENTITY)

    def test_content_identity_changes_when_a_file_changes(self):
        """One different file hash gives a different fingerprint."""
        changed = dict(SOURCE_FILES)
        changed["cli.py"] = sha(b"tampered")
        self.assertNotEqual(bundle.content_identity(changed), SOURCE_IDENTITY)

    def test_content_identity_changes_when_a_file_is_renamed(self):
        """Paths are part of the fingerprint, so moving identical content still changes it."""
        renamed = dict(SOURCE_FILES)
        renamed["renamed_cli.py"] = renamed.pop("cli.py")
        self.assertEqual(sorted(renamed.values()), sorted(SOURCE_FILES.values()))
        self.assertNotEqual(bundle.content_identity(renamed), SOURCE_IDENTITY)

    def test_content_identity_changes_when_a_file_is_added_or_removed(self):
        """Adding or dropping a file changes the fingerprint even when nothing else moves."""
        added = dict(SOURCE_FILES, extra_module=sha(b""))
        removed = {name: digest for name, digest in SOURCE_FILES.items() if name != "ids.py"}
        self.assertNotEqual(bundle.content_identity(added), SOURCE_IDENTITY)
        self.assertNotEqual(bundle.content_identity(removed), SOURCE_IDENTITY)
        self.assertNotEqual(bundle.content_identity(added), bundle.content_identity(removed))

    def test_content_identity_separates_a_path_from_its_hash(self):
        """Two file sets whose bare path+hash concatenations collide must still fingerprint apart.

        ``"ab" + h`` and ``"a" + ("b" + h)`` are the same characters, so a digest fed the path and the
        hash with no separator between them would report these two different bundles as identical.
        """
        one = {"ab": "c" * 64}
        two = {"a": "b" + "c" * 64}
        self.assertEqual("ab" + one["ab"], "a" + two["a"])  # the collision the separator must break
        self.assertNotEqual(bundle.content_identity(one), bundle.content_identity(two))

    def test_content_identity_terminates_every_entry(self):
        """Entries are terminated, so one entry cannot impersonate two by embedding the separator.

        Without the per-entry terminator, ``{"a": "1", "b": "2"}`` and ``{"a": "1b\\0" "2"}`` feed the
        digest the same bytes.
        """
        two_entries = {"a": "1", "b": "2"}
        one_entry = {"a": "1b\x002"}
        self.assertEqual("a\x00" + "1" + "b\x00" + "2", "a\x00" + one_entry["a"])
        self.assertNotEqual(bundle.content_identity(two_entries), bundle.content_identity(one_entry))


# -- the manifest -------------------------------------------------------------------------------------
class ManifestTests(unittest.TestCase):
    """``build_manifest``/``manifest_text`` must be deterministic and carry the compatibility facts."""

    def test_build_manifest_is_deterministic_and_carries_no_timestamp(self):
        """Two builds over the same files give byte-identical text; the key set admits no clock field."""
        first = bundle.build_manifest(dict(sorted(SOURCE_FILES.items())))
        second = bundle.build_manifest(dict(sorted(SOURCE_FILES.items(), reverse=True)))
        self.assertEqual(set(first), MANIFEST_KEYS)
        self.assertEqual(first, second)
        self.assertEqual(bundle.manifest_text(first), bundle.manifest_text(second))
        self.assertEqual(list(first["files"]), sorted(SOURCE_FILES))

    def test_build_manifest_records_the_release_constants(self):
        """The manifest publishes the exact versions an installed package checks compatibility against."""
        manifest = bundle.build_manifest(SOURCE_FILES)
        self.assertEqual({key: manifest[key] for key in RELEASE_CONSTANTS}, {
            "bundle": "paper_core",
            "core_version": "3.2.8",
            "storage_formats_readable": [2, 3, 4],
            "storage_formats_writable": [4],
            "contract_version": 4,
            "contract": "proofcheck-records/4",
            "packet_version": 2,
            "projection_version": 2,
            "protocol_version": "coherent-proof-audit/1",
            "write_protocols": {"audit": ["coherent-proof-audit/1"], "overview": ["item-audit/1", "paper-overview/1", "coherent-proof-audit/1"]},
            "supported_features": ["records/3", "packets/1", "packets/2", "work-submissions/1", "audits/1", "independent-review/1", "projection/1", "projection/2", "overview-bridge/1", "sql-superset/1", "records/4", "route-review/1", "coherent-examinations/1", "work-context-extension/1", "audit-scope-binding/1", "reviewed-proof-spans/1"],
            "legacy_overview_format": "archify-paper-database-1",
        })

    def test_manifest_values_survive_a_json_round_trip_unchanged(self):
        """Every value is JSON-native, so a stored manifest can compare equal to a freshly built one.

        The core keeps its format and feature lists as tuples. ``build_manifest`` must copy them into
        lists: a tuple would serialize as a JSON array and then compare unequal on reload, which is
        exactly what ``verify_bundle`` does - ``constants_match`` would be False for every shipped
        bundle.
        """
        manifest = bundle.build_manifest(SOURCE_FILES)
        parsed = json.loads(bundle.manifest_text(manifest))
        self.assertEqual(parsed, manifest)
        for key in ("storage_formats_readable", "storage_formats_writable", "supported_features"):
            self.assertEqual(parsed[key], manifest[key], key)  # a tuple here would compare unequal

    def test_build_manifest_records_the_file_set_and_its_identity(self):
        """file_count, files and source_identity describe exactly the mapping handed in."""
        files = {"b.py": sha(b"b"), "a.py": sha(b"a")}
        manifest = bundle.build_manifest(files)
        self.assertEqual(manifest["file_count"], 2)
        self.assertEqual(list(manifest["files"]), ["a.py", "b.py"])
        self.assertEqual(manifest["files"], files)
        self.assertEqual(manifest["source_identity"], bundle.content_identity(files))

    def test_build_manifest_copies_the_file_mapping_it_was_given(self):
        """The caller's mapping is snapshotted: later edits to it cannot rewrite a built manifest."""
        files = {"a.py": sha(b"a")}
        manifest = bundle.build_manifest(files)
        files["b.py"] = sha(b"b")
        del files["a.py"]
        self.assertEqual(manifest["files"], {"a.py": sha(b"a")})
        self.assertEqual(manifest["file_count"], 1)

    def test_manifest_text_is_sorted_indented_json_with_a_trailing_newline(self):
        """The serialized form is stable so two packages can hold byte-identical manifests."""
        manifest = bundle.build_manifest({"a.py": sha(b"a")})
        text = bundle.manifest_text(manifest)
        self.assertTrue(text.endswith("}\n"))
        self.assertNotIn("\r", text)
        self.assertEqual(json.loads(text), manifest)
        top_level = [line.split('"')[1] for line in text.splitlines() if line.startswith(' "')]
        self.assertEqual(top_level, sorted(MANIFEST_KEYS))
        self.assertEqual(text.splitlines()[1], ' "bundle": "paper_core",')  # indent=1, not the json default

    def test_manifest_text_keeps_non_ascii_paths_literal(self):
        """ensure_ascii is off, so the same file set serializes to the same bytes on every host."""
        text = bundle.manifest_text(bundle.build_manifest({"résumé.tex": sha(b"x")}))
        self.assertIn("résumé.tex", text)
        self.assertNotIn("\\u00e9", text)
        self.assertEqual(list(json.loads(text)["files"]), ["résumé.tex"])


# -- the shipped bundles ------------------------------------------------------------------------------
class ShippedBundleTests(unittest.TestCase):
    """The two generated bundles and the two wrappers are the coordinated release."""

    def test_repository_source_tree_has_no_manifest(self):
        """shared/paper_core is the maintained source, not a bundle: present False and ok None."""
        self.assertIsNone(bundle.load_manifest(CORE))
        self.assertIsNone(bundle.load_manifest())  # the default root is the imported package directory
        verification = bundle.verify_bundle(CORE)
        self.assertEqual(set(verification), VERIFY_KEYS)
        self.assertIs(verification["present"], False)
        self.assertIsNone(verification["ok"])
        self.assertIsNone(verification["source_identity"])
        self.assertIsNone(verification["file_count"])
        self.assertIsNone(verification["constants_match"])
        self.assertEqual([verification["missing"], verification["unexpected"], verification["changed"]],
                         [[], [], []])

    def test_each_shipped_bundle_verifies_clean(self):
        """Both packages ship the expected files and a manifest matching the maintained source."""
        for name, package in PACKAGES.items():
            with self.subTest(package=name):
                root = shipped(package)
                self.assertTrue((root / bundle.MANIFEST_NAME).is_file())
                files = bundle.bundle_files(root)
                self.assertEqual(len(files), BUNDLE_FILE_COUNT)
                self.assertEqual(files, SOURCE_FILES)
                verification = bundle.verify_bundle(root)
                self.assertIs(verification["present"], True)
                self.assertIs(verification["ok"], True)
                self.assertIs(verification["constants_match"], True)
                self.assertEqual(verification["file_count"], BUNDLE_FILE_COUNT)
                self.assertEqual(verification["source_identity"], SOURCE_IDENTITY)
                self.assertEqual([verification["missing"], verification["unexpected"], verification["changed"]],
                                 [[], [], []])

    def test_the_two_bundles_are_byte_identical(self):
        """A coordinated release means both packages carry the same bytes, manifest included."""
        proofcheck, overview = shipped(PROOFCHECK), shipped(OVERVIEW)
        self.assertEqual(bundle.bundle_files(proofcheck), bundle.bundle_files(overview))
        manifest_bytes = (proofcheck / bundle.MANIFEST_NAME).read_bytes()
        self.assertEqual(manifest_bytes, (overview / bundle.MANIFEST_NAME).read_bytes())
        self.assertNotIn(b"\r\n", manifest_bytes)
        for relative in sorted(SOURCE_FILES):
            self.assertEqual((proofcheck / relative).read_bytes(), (overview / relative).read_bytes(), relative)

    def test_shipped_manifest_equals_a_fresh_build_of_the_source(self):
        """The shipped manifests are exactly what the builder would write again from shared/paper_core."""
        expected = bundle.manifest_text(bundle.build_manifest(SOURCE_FILES)).encode("utf-8")
        for name, package in PACKAGES.items():
            with self.subTest(package=name):
                self.assertEqual((shipped(package) / bundle.MANIFEST_NAME).read_bytes(), expected)

    def test_shipped_manifests_record_the_live_core_constants(self):
        """Bumping a constant in shared/paper_core without rebuilding leaves the shipped manifests stale."""
        for name, package in PACKAGES.items():
            with self.subTest(package=name):
                stored = json.loads((shipped(package) / bundle.MANIFEST_NAME).read_text(encoding="utf-8"))
                self.assertEqual({key: stored[key] for key in RELEASE_CONSTANTS}, RELEASE_CONSTANTS)
                self.assertEqual(stored["source_identity"], SOURCE_IDENTITY)
                self.assertEqual(stored["file_count"], BUNDLE_FILE_COUNT)
                self.assertEqual(stored["files"], SOURCE_FILES)

    def test_wrappers_load_only_their_adjacent_core(self):
        """Workflow wrappers may differ; both load their adjacent bundle."""
        first = wrapper_path(PROOFCHECK).read_bytes()
        second = wrapper_path(OVERVIEW).read_bytes()
        self.assertIn(b"from paper_core.cli import main", second)
        text = first.decode("utf-8")
        self.assertNotIn("\r\n", text)
        code = text.split('"""')[2]  # everything after the module docstring
        self.assertIn("HERE = os.path.dirname(os.path.abspath(__file__))", code)
        self.assertIn("sys.path.insert(0, HERE)", code)
        self.assertIn("from paper_core.cli import main", code)
        for forbidden in ("import proofcheck", "os.pardir", "parents[", "..", "shared", "PYTHONPATH"):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertLess(len(code.strip().splitlines()), 15)


# -- verification failure paths -------------------------------------------------------------------------
class BundleVerificationTests(TempCase):
    """``verify_bundle`` must name every way an installed bundle can stop matching its manifest."""

    def test_verify_bundle_reports_a_missing_file(self):
        """Deleting a bundled file reports it as missing and drops ok to False."""
        root = copy_shipped_bundle(self.path("copy"))
        (root / "renderer" / "fixtures" / "dag_small.json").unlink()
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], False)
        self.assertEqual(verification["missing"], ["renderer/fixtures/dag_small.json"])
        self.assertEqual([verification["unexpected"], verification["changed"]], [[], []])
        self.assertIs(verification["constants_match"], True)
        self.assertEqual(verification["file_count"], BUNDLE_FILE_COUNT)

    def test_verify_bundle_reports_an_unexpected_file(self):
        """A hand-added file inside a generated bundle is unexpected: bundles are never edited by hand."""
        root = copy_shipped_bundle(self.path("copy"))
        (root / "sneaky.py").write_text("# hand edit\n", encoding="utf-8", newline="\n")
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], False)
        self.assertEqual(verification["unexpected"], ["sneaky.py"])
        self.assertEqual([verification["missing"], verification["changed"]], [[], []])
        self.assertIs(verification["constants_match"], True)
        self.assertEqual(verification["file_count"], BUNDLE_FILE_COUNT)

    def test_verify_bundle_reports_a_changed_file(self):
        """Editing a bundled file is detected by hash even though the path set is unchanged."""
        root = copy_shipped_bundle(self.path("copy"))
        victim = root / "ids.py"
        victim.write_bytes(victim.read_bytes() + b"# tampered\n")
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], False)
        self.assertEqual(verification["changed"], ["ids.py"])
        self.assertEqual([verification["missing"], verification["unexpected"]], [[], []])
        self.assertEqual(verification["source_identity"], SOURCE_IDENTITY)

    def test_verify_bundle_reports_every_fault_it_finds_at_once(self):
        """One report names all three categories; the first fault does not hide the others."""
        root = copy_shipped_bundle(self.path("copy"))
        (root / "renderer" / "fixtures" / "dag_small.json").unlink()
        (root / "sneaky.py").write_text("# hand edit\n", encoding="utf-8", newline="\n")
        victim = root / "ids.py"
        victim.write_bytes(victim.read_bytes() + b"# tampered\n")
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], False)
        self.assertEqual(verification["missing"], ["renderer/fixtures/dag_small.json"])
        self.assertEqual(verification["unexpected"], ["sneaky.py"])
        self.assertEqual(verification["changed"], ["ids.py"])

    def test_verify_bundle_reports_stale_manifest_constants(self):
        """A manifest whose versions no longer match the bundled core fails with constants_match False."""
        root = copy_shipped_bundle(self.path("copy"))
        manifest = json.loads((root / bundle.MANIFEST_NAME).read_text(encoding="utf-8"))
        manifest["core_version"] = "1.0.0"
        (root / bundle.MANIFEST_NAME).write_text(bundle.manifest_text(manifest), encoding="utf-8", newline="\n")
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], False)
        self.assertIs(verification["constants_match"], False)
        self.assertEqual([verification["missing"], verification["unexpected"], verification["changed"]],
                         [[], [], []])

    def test_verify_bundle_reports_a_dropped_manifest_constant(self):
        """A manifest that simply omits a compatibility fact is stale too, not silently acceptable."""
        root = copy_shipped_bundle(self.path("copy"))
        manifest = json.loads((root / bundle.MANIFEST_NAME).read_text(encoding="utf-8"))
        del manifest["supported_features"]
        (root / bundle.MANIFEST_NAME).write_text(bundle.manifest_text(manifest), encoding="utf-8", newline="\n")
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], False)
        self.assertIs(verification["constants_match"], False)

    def test_verify_bundle_reports_a_manifest_whose_identity_disagrees_with_its_own_file_list(self):
        """source_identity is re-derived from the recorded hashes, so a forged identity cannot pass."""
        root = copy_shipped_bundle(self.path("copy"))
        manifest = json.loads((root / bundle.MANIFEST_NAME).read_text(encoding="utf-8"))
        manifest["source_identity"] = sha(b"forged")
        (root / bundle.MANIFEST_NAME).write_text(bundle.manifest_text(manifest), encoding="utf-8", newline="\n")
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], False)
        self.assertIs(verification["constants_match"], True)
        self.assertEqual([verification["missing"], verification["unexpected"], verification["changed"]],
                         [[], [], []])
        self.assertEqual(verification["source_identity"], sha(b"forged"))

    def test_verify_bundle_tolerates_byte_compiled_caches_beside_an_installed_bundle(self):
        """Running an installed package writes caches; they must not make it look tampered with."""
        root = copy_shipped_bundle(self.path("copy"))
        (root / "__pycache__").mkdir(exist_ok=True)
        (root / "__pycache__" / "ids.cpython-314.pyc").write_bytes(b"\x00\x01")
        (root / "stale.pyc").write_bytes(b"\x00")
        verification = bundle.verify_bundle(root)
        self.assertIs(verification["ok"], True)
        self.assertEqual(verification["unexpected"], [])
        self.assertEqual(verification["source_identity"], SOURCE_IDENTITY)

    def test_verify_bundle_does_not_touch_the_bundle_it_reads(self):
        """Verification is read-only: an intact bundle is byte-for-byte unchanged afterwards."""
        root = copy_shipped_bundle(self.path("copy"))
        before = bundle_state(root)
        self.assertIs(bundle.verify_bundle(root)["ok"], True)
        self.assertEqual(bundle_state(root), before)

    def test_load_manifest_returns_none_when_there_is_no_manifest(self):
        """A tree with no manifest yields None rather than raising, so callers can report present False."""
        empty = self.path("empty")
        empty.mkdir()
        self.assertIsNone(bundle.load_manifest(empty))
        self.assertIsNone(bundle.load_manifest(empty / "missing"))
        verification = bundle.verify_bundle(empty)
        self.assertIs(verification["present"], False)
        self.assertIsNone(verification["ok"])

    def test_load_manifest_returns_the_stored_mapping_when_there_is_one(self):
        """A shipped manifest is read back as parsed JSON, not as bytes or a default."""
        root = copy_shipped_bundle(self.path("copy"))
        manifest = bundle.load_manifest(root)
        self.assertEqual(manifest, bundle.build_manifest(SOURCE_FILES))
        self.assertEqual(manifest["files"]["cli.py"], SOURCE_FILES["cli.py"])


# -- installed packages run isolated --------------------------------------------------------------------
class InstalledPackageTests(TempCase):
    """Each package is copied to its own install root and run with ``-I`` and no repository import path."""

    @classmethod
    def setUpClass(cls):
        cls.install_home = Path(tempfile.mkdtemp(prefix="paper_core_install_"))
        cls.addClassCleanup(rmtree_force, cls.install_home)
        cls.roots = {name: install_package(package, cls.install_home / f"{name}-only" / name)
                     for name, package in PACKAGES.items()}

    def mutable_install(self, name="stat-proof-check") -> Path:
        target = self.path("install") / name
        shutil.copytree(self.roots[name], target)
        return target

    def assert_healthy_report(self, payload):
        self.assertEqual(payload["command"], "version")
        self.assertEqual(payload["core_version"], "3.2.8")
        self.assertEqual(payload["storage_format"], 4)
        self.assertEqual(payload["contract_version"], 4)
        self.assertEqual(payload["contract"], "proofcheck-records/4")
        self.assertEqual(payload["packet_version"], 2)
        self.assertEqual(payload["projection_version"], 2)
        report = payload["bundle"]
        self.assertIs(report["present"], True)
        self.assertIs(report["ok"], True)
        self.assertIs(report["constants_match"], True)
        self.assertEqual(report["file_count"], BUNDLE_FILE_COUNT)
        self.assertEqual(report["source_identity"], SOURCE_IDENTITY)
        self.assertEqual([report["missing"], report["unexpected"], report["changed"]], [[], [], []])

    def test_proofcheck_package_runs_from_its_own_install_root(self):
        """The audit skill's installed wrapper reports the current core and an intact bundle."""
        self.assertFalse((self.roots["stat-proof-check"] / "assets" / "reference-audit").exists())
        self.assertTrue((REPO / "tests" / "fixtures" / "reference-audit" / "proofcheck-audit").is_dir())
        payload, stderr = run_wrapper(self.roots["stat-proof-check"], "version")
        self.assertEqual(stderr, "")
        self.assert_healthy_report(payload)

    def test_overview_package_runs_from_its_own_install_root(self):
        """The overview skill's installed wrapper reports the same core and bundle, independently."""
        payload, stderr = run_wrapper(self.roots["proof-graphify"], "version")
        self.assertEqual(stderr, "")
        self.assert_healthy_report(payload)

    def test_both_installed_packages_report_the_same_source_identity(self):
        """A coordinated release: the two installs are indistinguishable at the core boundary."""
        first, _ = run_wrapper(self.roots["stat-proof-check"], "version")
        second, _ = run_wrapper(self.roots["proof-graphify"], "version")
        self.assertEqual(first["bundle"], second["bundle"])
        self.assertEqual(first["bundle"]["source_identity"], SOURCE_IDENTITY)
        self.assertEqual({key: first[key] for key in ("core_version", "storage_format", "contract")},
                         {key: second[key] for key in ("core_version", "storage_format", "contract")})

    def test_installed_wrapper_imports_the_core_beside_it_not_the_repository_one(self):
        """The core the wrapper runs is the adjacent copy: its constants, not shared/paper_core's.

        Only the install copy's ``__init__.py`` is edited. The repository still says 3.2.8, so a
        wrapper that reached back into the repository - or into a sibling skill - could not report
        9.9.9 here.
        """
        root = self.mutable_install()
        init = shipped(root) / "__init__.py"
        source = init.read_text(encoding="utf-8")
        self.assertIn('CORE_VERSION = "3.2.8"', source)
        init.write_text(source.replace('CORE_VERSION = "3.2.8"', 'CORE_VERSION = "9.9.9"'),
                        encoding="utf-8", newline="\n")
        payload, _ = run_wrapper(root, "version")
        self.assertEqual(payload["core_version"], "9.9.9")
        self.assertEqual(payload["bundle"]["changed"], ["__init__.py"])
        self.assertIs(payload["bundle"]["constants_match"], False)
        self.assertEqual(CORE_VERSION, "3.2.8")  # the repository source is untouched
        self.assertIs(bundle.verify_bundle(shipped(PROOFCHECK))["ok"], True)

    def test_installed_wrapper_verifies_the_copy_it_imported_not_the_repository(self):
        """Breaking only the install copy changes what the wrapper reports; the repository stays intact."""
        root = self.mutable_install()
        (shipped(root) / "renderer" / "fixtures" / "dag_small.json").unlink()
        payload, _ = run_wrapper(root, "version")
        self.assertIs(payload["bundle"]["ok"], False)
        self.assertEqual(payload["bundle"]["missing"], ["renderer/fixtures/dag_small.json"])
        self.assertIs(bundle.verify_bundle(shipped(PROOFCHECK))["ok"], True)
        pristine, _ = run_wrapper(self.roots["stat-proof-check"], "version")
        self.assertIs(pristine["bundle"]["ok"], True)

    def test_installed_wrapper_has_no_repository_or_sibling_fallback(self):
        """With its adjacent bundle removed the wrapper fails outright rather than importing elsewhere."""
        root = self.mutable_install()
        rmtree_force(shipped(root))
        payload, stderr = run_wrapper(root, "version", expect=1)
        self.assertIsNone(payload)
        self.assertIn("No module named 'paper_core'", stderr)

    def test_installed_wrapper_ignores_the_legacy_monolith_beside_it(self):
        """The audit skill installs legacy scripts in the same directory; the new core never imports them."""
        root = self.mutable_install()
        legacy = root / "scripts" / "proofcheck.py"
        self.assertTrue(legacy.is_file())  # the wrapper's own directory is on sys.path
        legacy.write_text("raise SystemExit('the legacy monolith must never be imported')\n",
                          encoding="utf-8", newline="\n")
        payload, stderr = run_wrapper(root, "version")
        self.assertEqual(stderr, "")
        self.assertEqual(payload["core_version"], "3.2.8")
        self.assertIs(payload["bundle"]["ok"], True)

    def test_installed_package_ships_the_wrapper_and_bundle_it_needs(self):
        """The install root carries the entry point and an intact bundle, and no development folders."""
        for name, root in self.roots.items():
            with self.subTest(package=name):
                self.assertEqual([path.name for path in root.parent.iterdir()], [name])
                self.assertEqual(wrapper_path(root).read_bytes(), wrapper_path(PACKAGES[name]).read_bytes())
                self.assertEqual(bundle.bundle_files(shipped(root)), SOURCE_FILES)
                self.assertIs(bundle.verify_bundle(shipped(root))["ok"], True)
                excluded = [skip for skip in INSTALL_SKIP if (PACKAGES[name] / skip).exists()]
                self.assertTrue(excluded, "the source package has nothing this test could prove excluded")
                for skip in excluded:
                    self.assertFalse((root / skip).exists(), f"{name}/{skip} leaked into the install root")


# -- the release builder --------------------------------------------------------------------------------
class BuilderTests(TempCase):
    """``tools/build_paper_core_bundles.py --check`` is the release gate; it must never write."""

    def temp_package(self, name, *, wrapper=True, bundle_dir=True) -> Path:
        root = self.path("packages") / name
        (root / "scripts").mkdir(parents=True)
        if bundle_dir:
            copy_shipped_bundle(root / "scripts" / "paper_core")
        if wrapper:
            shutil.copyfile(wrapper_path(PROOFCHECK), root / "scripts" / "paper_audit.py")
        return root

    def test_check_passes_for_the_shipped_release(self):
        """--check requires identical cores and present product entrypoints, and writes nothing."""
        before = {name: bundle_state(shipped(package)) for name, package in PACKAGES.items()}
        proc = run_builder("--check")
        result = json.loads(proc.stdout)
        self.assertEqual(result["command"], "check")
        self.assertIs(result["ok"], True)
        self.assertIs(result["bundles_identical"], True)
        self.assertTrue(result["entrypoints_present"])
        self.assertEqual(result["source_identity"], SOURCE_IDENTITY)
        self.assertEqual(sorted(result["bundles"]), sorted(PACKAGES))
        for name in PACKAGES:
            entry = result["bundles"][name]
            self.assertIs(entry["exists"], True, name)
            self.assertIs(entry["ok"], True, name)
            self.assertIs(entry["matches_source"], True, name)
            self.assertEqual(entry["file_count"], BUNDLE_FILE_COUNT, name)
            self.assertEqual(entry["source_identity"], SOURCE_IDENTITY, name)
            self.assertEqual([entry["missing"], entry["unexpected"], entry["changed"]], [[], [], []], name)
        self.assertEqual(len({result["bundles"][name]["manifest_bytes"] for name in PACKAGES}), 1)
        self.assertTrue(result["entrypoints_present"])
        for name, package in PACKAGES.items():
            self.assertEqual(result["wrappers"][name], sha(wrapper_path(package).read_bytes()))
        after = {name: bundle_state(shipped(package)) for name, package in PACKAGES.items()}
        self.assertEqual(after, before)

    def test_check_can_be_limited_to_one_package(self):
        """--package narrows the report to that package without touching the other."""
        proc = run_builder("--check", "--package", "proof-graphify")
        result = json.loads(proc.stdout)
        self.assertEqual(sorted(result["bundles"]), ["proof-graphify"])
        self.assertEqual(sorted(result["wrappers"]), ["proof-graphify"])
        self.assertIs(result["ok"], True)
        self.assertIs(result["bundles"]["proof-graphify"]["matches_source"], True)
        self.assertEqual(result["source_identity"], SOURCE_IDENTITY)

    def test_check_rejects_an_unknown_package_name(self):
        """An unknown --package is an argparse error (exit 2) and prints no JSON report."""
        proc = run_builder("--check", "--package", "not-a-skill", expect=2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("invalid choice", proc.stderr)

    def test_check_fails_when_a_bundle_is_missing(self):
        """A package with no generated bundle is not a release: exists False and ok False."""
        module = builder_module()
        packages = {"good": self.temp_package("good"), "bare": self.temp_package("bare", bundle_dir=False)}
        result = module.check(packages)
        self.assertIs(result["ok"], False)
        self.assertIs(result["bundles_identical"], False)
        self.assertIs(result["bundles"]["bare"]["exists"], False)
        self.assertIs(result["bundles"]["bare"]["ok"], False)
        self.assertIs(result["bundles"]["good"]["ok"], True)

    def test_check_fails_when_the_two_bundles_differ(self):
        """Editing one package's bundle breaks matches_source and bundles_identical."""
        module = builder_module()
        packages = {"good": self.temp_package("good"), "edited": self.temp_package("edited")}
        victim = packages["edited"] / "scripts" / "paper_core" / "ids.py"
        victim.write_bytes(victim.read_bytes() + b"# hand edit\n")
        result = module.check(packages)
        self.assertIs(result["ok"], False)
        self.assertIs(result["bundles_identical"], False)
        self.assertIs(result["bundles"]["edited"]["matches_source"], False)
        self.assertEqual(result["bundles"]["edited"]["changed"], ["ids.py"])
        self.assertIs(result["bundles"]["good"]["ok"], True)
        self.assertIs(result["wrappers_identical"], True)

    def test_check_fails_when_a_bundle_matches_its_own_stale_manifest(self):
        """A self-consistent bundle built from a different source is still not this release."""
        module = builder_module()
        packages = {"good": self.temp_package("good"), "stale": self.temp_package("stale")}
        target = packages["stale"] / "scripts" / "paper_core"
        victim = target / "ids.py"
        victim.write_bytes(victim.read_bytes() + b"# an older revision\n")
        (target / bundle.MANIFEST_NAME).write_text(
            bundle.manifest_text(bundle.build_manifest(bundle.bundle_files(target))),
            encoding="utf-8", newline="\n")
        result = module.check(packages)
        self.assertIs(result["bundles"]["stale"]["ok"], False)
        self.assertIs(result["bundles"]["stale"]["matches_source"], False)
        self.assertIs(result["bundles"]["stale"]["constants_match"], True)  # self-consistent, wrong source
        self.assertEqual(result["bundles"]["stale"]["changed"], [])
        self.assertNotEqual(result["bundles"]["stale"]["source_identity"], SOURCE_IDENTITY)
        self.assertIs(result["ok"], False)

    def test_check_accepts_different_workflow_wrappers(self):
        """A valid product wrapper may differ while both core bundles verify."""
        module = builder_module()
        packages = {"good": self.temp_package("good"), "drifted": self.temp_package("drifted")}
        drifted = packages["drifted"] / "scripts" / "paper_audit.py"
        drifted.write_bytes(drifted.read_bytes() + b"# drift\n")
        result = module.check(packages)
        self.assertIs(result["ok"], True)
        self.assertIs(result["wrappers_identical"], False)
        self.assertIs(result["bundles_identical"], True)
        self.assertNotEqual(result["wrappers"]["good"], result["wrappers"]["drifted"])

    def test_check_fails_when_a_wrapper_is_absent(self):
        """A package without its entry point reports a null wrapper hash and fails the gate."""
        module = builder_module()
        packages = {"good": self.temp_package("good"), "headless": self.temp_package("headless", wrapper=False)}
        result = module.check(packages)
        self.assertIs(result["ok"], False)
        self.assertIs(result["wrappers_identical"], False)
        self.assertIsNone(result["wrappers"]["headless"])

    def test_check_exits_one_and_writes_nothing_when_the_gate_fails(self):
        """The gate's failure is an exit code, not just a report; --check never repairs what it found.

        ``main`` runs over temporary packages here (``PACKAGES`` is patched on a freshly imported
        module) so the repository's own bundles are never a subject of a failing run.
        """
        module = builder_module()
        packages = {"good": self.temp_package("good"), "bare": self.temp_package("bare", bundle_dir=False)}
        module.PACKAGES = packages
        before = bundle_state(packages["good"] / "scripts" / "paper_core")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(["--check"])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["command"], "check")
        self.assertFalse((packages["bare"] / "scripts" / "paper_core").exists())
        self.assertEqual(bundle_state(packages["good"] / "scripts" / "paper_core"), before)

    def test_check_exits_zero_when_the_gate_passes(self):
        """The same entry point returns 0 for a consistent pair, so the exit code tracks ``ok``."""
        module = builder_module()
        module.PACKAGES = {"one": self.temp_package("one"), "two": self.temp_package("two")}
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(["--check"])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertIs(result["ok"], True)
        self.assertIs(result["bundles_identical"], True)
        self.assertIs(result["wrappers_identical"], True)


if __name__ == "__main__":
    unittest.main()
