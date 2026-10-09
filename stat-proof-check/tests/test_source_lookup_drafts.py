"""Read-only draft selection must not require completed mathematical judgments."""
from __future__ import annotations

import contextlib
import copy
import io
import sys
import unittest
from unittest import mock

import test_unit_submission as support

proofcheck = support.proofcheck
authoring = support.authoring
read_json = support.read_json
write_json = support.write_json


class SourceLookupDraftTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.fixture_support.CompileAnnotationsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.draft = self.fixture.base / "unfinished.annotations.json"

    def files(self):
        return {p.relative_to(self.fixture.base): p.read_bytes()
                for p in self.fixture.base.rglob("*") if p.is_file()}

    def lookup(self, annotations, key="conclusion"):
        write_json(self.draft, annotations)
        before = self.files()
        try:
            return authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger,
                                           annotations_path=self.draft, step_key=key)
        finally:
            self.assertEqual(before, self.files(), "Source lookup must not write audit or draft records")

    def test_fresh_scaffold_can_be_read_but_cannot_be_compiled(self):
        ledger, packet = read_json(self.fixture.ledger), read_json(self.fixture.packet)
        draft = proofcheck.annotation_scaffold_data(ledger, packet)
        key = next(row["key"] for row in draft["steps"] if row["lines"] == [5, 5])
        result = self.lookup(draft, key)
        self.assertEqual("S005", result["step_id"])
        self.assertEqual([5, 5], result["coverage_positions"])
        self.assertEqual(5, result["lines"][0]["source"]["start_line"])
        self.assertIn("reflexivity", result["lines"][0]["text"])
        with self.assertRaises(ValueError):
            proofcheck.compile_annotation_data(ledger, draft, self.fixture.ledger, packet)

    def test_unfinished_requested_and_unrelated_review_fields_do_not_block_lookup(self):
        for field in ("mode", "goal", "risks", "inputs", "status", "adversarial"):
            with self.subTest(field=field):
                draft = self.fixture.annotations()
                for step in draft["steps"]:
                    step[field] = None
                self.assertEqual("S003", self.lookup(draft)["step_id"])

    def test_only_structural_step_fields_are_needed_for_lookup_but_not_submission(self):
        draft = self.fixture.annotations()
        draft["steps"] = [{"key": step["key"], "lines": step["lines"]} for step in draft["steps"]]
        self.assertEqual("S003", self.lookup(draft)["step_id"])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            authoring.submit_unit(proofcheck, ledger_path=self.fixture.ledger,
                                  annotations_path=self.draft, packet_path=self.fixture.packet)
        self.assertFalse(self.fixture.output.exists())

    def test_draft_may_omit_other_steps_without_changing_source_unit_identity(self):
        draft = self.fixture.annotations()
        draft["steps"] = [draft["steps"][1]]
        self.assertEqual("S003", self.lookup(draft)["step_id"])
        with self.assertRaisesRegex(ValueError, "omit substantive source units"):
            proofcheck.compile_annotation_data(read_json(self.fixture.ledger), draft,
                                               self.fixture.ledger, read_json(self.fixture.packet))

    def test_complete_and_split_step_ids_match_compiler_order(self):
        complete = self.fixture.dependency_annotations()
        ledger, packet = read_json(self.fixture.ledger), read_json(self.fixture.packet)
        compiled = proofcheck.compile_annotation_data(ledger, complete, self.fixture.ledger, packet)
        units, ranges = proofcheck.build_compiled_source_units(ledger, complete["source_groups"])
        for shuffled in (False, True):
            draft = copy.deepcopy(complete)
            if shuffled:
                draft["steps"] = draft["steps"][1:] + draft["steps"][:1]
            _, expected = proofcheck.prepare_compact_step_plans(draft["steps"], units, ranges)
            for step in draft["steps"]:
                key = step["key"]
                step["goal"] = None
                result = self.lookup(draft, key)
                self.assertEqual(expected[key], result["step_id"])
                self.assertIn(result["step_id"], {row["id"] for row in compiled["steps"]})
        self.assertIn("S003.1", expected.values())

    def test_missing_structure_returns_controlled_input_errors(self):
        for field in ("source_groups", "steps"):
            with self.subTest(field=field):
                draft = self.fixture.annotations()
                del draft[field]
                with self.assertRaisesRegex(ValueError, f"{field} must be a list"):
                    self.lookup(draft)
        for field in ("key", "lines"):
            with self.subTest(field=field):
                draft = self.fixture.annotations()
                del draft["steps"][0][field]
                with self.assertRaisesRegex(ValueError, field):
                    self.lookup(draft)
        draft = self.fixture.annotations()
        draft["steps"][0] = None
        with self.assertRaisesRegex(ValueError, "must be an object"):
            self.lookup(draft)

    def test_duplicate_and_unknown_keys_are_refused(self):
        draft = self.fixture.annotations()
        draft["steps"].append(copy.deepcopy(draft["steps"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate compact step key"):
            self.lookup(draft)
        with self.assertRaisesRegex(ValueError, "Unknown draft step key"):
            self.lookup(self.fixture.annotations(), "missing")

    def test_malformed_outside_partial_and_non_substantive_ranges_are_refused(self):
        for lines in (None, [5], [True, 5], [5, "5"], [0, 5], [5, 4], [5, 9], [2, 3], [4, 4]):
            with self.subTest(lines=lines):
                draft = self.fixture.annotations()
                draft["steps"][0]["lines"] = lines
                with self.assertRaises(ValueError):
                    self.lookup(draft)

    def test_source_groups_keep_exact_range_and_order_validation(self):
        base = self.fixture.annotations()
        invalid = (None, [None], [{"lines": [1, 3]}],
                   [{**base["source_groups"][0], "kind": []}],
                   [base["source_groups"][0], base["source_groups"][0]],
                   [{**base["source_groups"][0], "lines": [5, 6]}, base["source_groups"][0]],
                   [{**base["source_groups"][0], "lines": [1, 9]}])
        for groups in invalid:
            with self.subTest(groups=groups):
                draft = copy.deepcopy(base)
                draft["source_groups"] = groups
                with self.assertRaises(ValueError):
                    self.lookup(draft)

    def test_source_and_obligation_bindings_cannot_be_missing_or_stale(self):
        for field in ("unit_id", "source_unit_sha256", "obligation_sha256"):
            for value in (None, "different"):
                with self.subTest(field=field, value=value):
                    draft = self.fixture.annotations()
                    draft[field] = value
                    with self.assertRaisesRegex(ValueError, "do not bind"):
                        self.lookup(draft)
        draft = self.fixture.annotations()
        ledger = read_json(self.fixture.ledger)
        del ledger["obligation"]
        write_json(self.fixture.ledger, ledger)
        with self.assertRaisesRegex(ValueError, "source-locked obligation"):
            self.lookup(draft)

    def test_cli_missing_source_groups_reports_input_error_without_traceback(self):
        draft = self.fixture.annotations()
        del draft["source_groups"]
        write_json(self.draft, draft)
        before = self.files()
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["proofcheck.py", "source-lookup", str(self.fixture.ledger),
                                            "--annotations", str(self.draft), "--step-key", "conclusion"]):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(2, proofcheck.main())
        self.assertIn("source_groups must be a list", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertEqual(before, self.files())


if __name__ == "__main__":
    unittest.main()
