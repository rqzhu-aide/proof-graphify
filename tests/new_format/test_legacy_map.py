"""``legacy-map.json`` is checked against the proofcheck suite it classifies.

Section 9 asks for one mapping file whose entries are ``{old_test, treatment, new_test, reason}`` with
``treatment`` in ``legacy_only``, ``ported`` or ``shared``, and for tests affected by a changed shared
component to be classified exhaustively. A hand-written map rots silently: a legacy test gets added or
renamed, a new-format module gets renamed, and the map still parses. These tests make that a failure.

Nothing here asserts that a port is *good*; that is the job of the module the entry points at. This
asserts only that the classification is complete, unambiguous, and made of live references.
"""
from __future__ import annotations

import io
import json
import unittest

from support import PROOFCHECK, REPO

MAP_PATH = REPO / "tests" / "new_format" / "legacy-map.json"
PROOFCHECK_TESTS = PROOFCHECK / "tests"
TREATMENTS = ("legacy_only", "ported", "shared")
ENTRY_KEYS = {"old_test", "treatment", "new_test", "reason"}

#: The four ports handoff section 9 names explicitly, and the behaviour each one carries over.
NAMED_PORTS = {
    "stat-proof-check/tests/test_challenge_evidence.py": "blinding and original responses",
    "stat-proof-check/tests/test_statement_support.py": "restricted repairs",
    "stat-proof-check/tests/test_semantic_reuse.py": "changed prerequisites",
    "stat-proof-check/tests/test_transaction_publication.py": "failed publication",
}
#: The two files handoff section 9 names as legacy-only representation.
NAMED_LEGACY_ONLY = (
    "stat-proof-check/tests/test_proofcheck.py",
    "stat-proof-check/tests/test_primary_renewal.py",
)


def _load() -> dict:
    with io.open(MAP_PATH, encoding="utf-8") as stream:
        return json.load(stream)


def _suite_paths() -> set:
    """Every legacy proofcheck test module, as a repository-relative POSIX path."""
    found = set()
    for folder in (PROOFCHECK_TESTS,):
        for path in folder.glob("test_*.py"):
            found.add(path.relative_to(REPO).as_posix())
    return found


class FileShape(unittest.TestCase):
    """The map is one JSON object with the keys section 9 asks for, stored with LF newlines."""

    def test_the_map_is_stored_as_utf8_with_lf_newlines(self):
        """.gitattributes normalizes the repository to LF; a map written on Windows must match."""
        with io.open(MAP_PATH, "rb") as stream:
            raw = stream.read()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        raw.decode("utf-8")  # raises on any non-UTF-8 byte

    def test_every_entry_has_exactly_the_four_documented_keys(self):
        """Section 9 fixes the entry shape; an extra key would be an undocumented field."""
        for entry in _load()["entries"]:
            self.assertEqual(set(entry), ENTRY_KEYS, entry.get("old_test"))

    def test_every_treatment_is_one_of_the_three_documented_values(self):
        for entry in _load()["entries"]:
            self.assertIn(entry["treatment"], TREATMENTS, entry["old_test"])

    def test_every_treatment_is_defined_in_the_files_own_legend(self):
        """The legend is the reader's contract; a value it does not define is not classified."""
        data = _load()
        self.assertEqual(sorted(data["treatments"]), sorted(TREATMENTS))
        for value in data["treatments"].values():
            self.assertTrue(value.strip())

    def test_every_reason_is_a_real_sentence(self):
        """A one-word reason records nothing. Each entry explains what moved, or why nothing did."""
        for entry in _load()["entries"]:
            self.assertGreater(len(entry["reason"]), 80, entry["old_test"])
            self.assertTrue(entry["reason"].rstrip().endswith("."), entry["old_test"])


class Coverage(unittest.TestCase):
    """The classification covers proofcheck exactly once, with no invented or missing file."""

    def test_every_legacy_test_module_is_classified(self):
        """Exhaustive classification: a newly added legacy test must be classified before it lands."""
        classified = {e["old_test"] for e in _load()["entries"]}
        missing = sorted(_suite_paths() - classified)
        self.assertEqual(missing, [], f"unclassified legacy tests: {missing}")

    def test_no_entry_names_a_file_that_does_not_exist(self):
        """A renamed or deleted legacy test must not leave a stale row behind."""
        classified = {e["old_test"] for e in _load()["entries"]}
        stale = sorted(classified - _suite_paths())
        self.assertEqual(stale, [], f"entries for absent legacy tests: {stale}")

    def test_no_legacy_test_is_classified_twice(self):
        """Two rows for one file would make the treatment ambiguous."""
        seen = [e["old_test"] for e in _load()["entries"]]
        duplicates = sorted({name for name in seen if seen.count(name) > 1})
        self.assertEqual(duplicates, [])

    def test_the_legacy_suites_are_not_empty(self):
        """Guards the coverage assertions above: an empty glob would make them vacuous."""
        paths = _suite_paths()
        self.assertGreater(len([p for p in paths if p.startswith("stat-proof-check/")]), 30)


class References(unittest.TestCase):
    """Every ``new_test`` points at a module that exists, and the treatments agree with it."""

    def test_every_named_new_test_exists(self):
        for entry in _load()["entries"]:
            if entry["new_test"] is not None:
                self.assertTrue((REPO / entry["new_test"]).is_file(), entry["new_test"])

    def test_a_ported_entry_names_the_module_that_replaces_it(self):
        """``ported`` is the claim that a new-format test asserts the behaviour; it needs a target."""
        for entry in _load()["entries"]:
            if entry["treatment"] == "ported":
                self.assertIsNotNone(entry["new_test"], entry["old_test"])

    def test_a_legacy_only_entry_names_no_replacement(self):
        """``legacy_only`` is the claim that nothing was carried forward, so a target would contradict it."""
        for entry in _load()["entries"]:
            if entry["treatment"] == "legacy_only":
                self.assertIsNone(entry["new_test"], entry["old_test"])

    def test_every_new_format_module_is_accounted_for(self):
        """A module that no entry reaches is either an unrecorded port or dead weight."""
        data = _load()
        reached = {e["new_test"] for e in data["entries"] if e["new_test"]}
        reached |= {row["new_test"] for row in data["new_without_legacy_predecessor"]}
        modules = {p.relative_to(REPO).as_posix()
                   for p in (REPO / "tests" / "new_format").glob("test_*.py")
                   if p.name != "test_legacy_map.py"}
        self.assertEqual(sorted(modules - reached), [])

    def test_the_new_only_list_names_existing_modules_that_no_entry_claims(self):
        """The two lists must not overlap: a module cannot both replace something and replace nothing."""
        data = _load()
        reached = {e["new_test"] for e in data["entries"] if e["new_test"]}
        for row in data["new_without_legacy_predecessor"]:
            self.assertTrue((REPO / row["new_test"]).is_file(), row["new_test"])
            self.assertNotIn(row["new_test"], reached)
            self.assertGreater(len(row["reason"]), 80, row["new_test"])


class HandoffNamedCases(unittest.TestCase):
    """The six files handoff section 9 classifies by name are classified that way here."""

    def test_the_four_named_behavioural_ports_are_ported(self):
        entries = {e["old_test"]: e for e in _load()["entries"]}
        for old_test in NAMED_PORTS:
            self.assertIn(old_test, entries)
            self.assertEqual(entries[old_test]["treatment"], "ported", old_test)
            self.assertIsNotNone(entries[old_test]["new_test"], old_test)

    def test_the_two_named_legacy_only_files_are_legacy_only(self):
        entries = {e["old_test"]: e for e in _load()["entries"]}
        for old_test in NAMED_LEGACY_ONLY:
            self.assertIn(old_test, entries)
            self.assertEqual(entries[old_test]["treatment"], "legacy_only", old_test)

    def test_the_named_ports_reach_four_distinct_behaviours(self):
        """Section 9 names four separate behaviours; collapsing them into one row would lose three."""
        entries = {e["old_test"]: e for e in _load()["entries"]}
        targets = {entries[old]["new_test"] for old in NAMED_PORTS}
        self.assertGreaterEqual(len(targets), 3)


class NoRetirement(unittest.TestCase):
    """Section 9: legacy retirement needs a separate declared end of old-format support."""

    def test_the_map_deletes_no_legacy_test(self):
        """Every classified file is still on disk, whatever its treatment."""
        for entry in _load()["entries"]:
            self.assertTrue((REPO / entry["old_test"]).is_file(), entry["old_test"])

    def test_the_map_states_that_it_retires_nothing(self):
        self.assertIn("retire", _load()["purpose"])


if __name__ == "__main__":
    unittest.main()
