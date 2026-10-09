"""Read-only gate reuse preserves decisions and rejects changing inputs."""
from __future__ import annotations

import os
import unittest
from unittest import mock

import test_proofcheck as fixtures

pc = fixtures.proofcheck


class GateContextCacheTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FinalizationTests()
        self.fixture.setUp()
        self.root = self.fixture.audit

    def tearDown(self):
        self.fixture.tearDown()

    def test_full_gate_matches_uncached_decisions_and_changes_no_files(self):
        self.fixture.make_complete_audit()
        before = pc.audit_state_manifest(self.root)
        expected = None
        with mock.patch.object(pc, "gate_context_snapshot", side_effect=lambda root: pc.gate_digest_snapshot()):
            expected = pc.check_audit_finalization(self.root, check_reports=False)
        actual = pc.check_audit_finalization(self.root, check_reports=False)
        self.assertEqual([], expected[0])
        self.assertEqual(expected, actual)
        self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_reuse_is_local_and_returns_independent_results(self):
        calls = []

        @pc.gate_context_reader
        def source_reader(value):
            calls.append(value)
            return {"values": [value]}

        with pc.gate_context_snapshot(self.root):
            first = source_reader("first")
            first["values"].append("consumer change")
            self.assertEqual({"values": ["first"]}, source_reader("first"))
            self.assertEqual({"values": ["second"]}, source_reader("second"))
        self.assertEqual(["first", "second"], calls)
        source_reader("first")
        with pc.gate_context_snapshot(self.root):
            source_reader("first")
        self.assertEqual(["first", "second", "first", "first"], calls)
        self.assertIsNone(pc._GATE_CONTEXT_CACHE.get())

    def test_cached_gate_retains_incomplete_evidence_failure(self):
        self.fixture.make_complete_audit()
        ledger = next((self.root / "audit/04_local_checks").glob("*.ledger.json"))
        value = fixtures.read_json(ledger)
        value["steps"][0]["status"] = "not_checked"
        fixtures.write_json(ledger, value)
        with mock.patch.object(pc, "gate_context_snapshot", side_effect=lambda root: pc.gate_digest_snapshot()):
            expected = pc.check_audit_finalization(self.root, check_reports=False)
        actual = pc.check_audit_finalization(self.root, check_reports=False)
        self.assertTrue(expected[0])
        self.assertEqual(expected, actual)

    def test_added_removed_and_changed_audit_inputs_fail_the_gate(self):
        target = self.root / "captured-input.json"
        extra = self.root / "concurrent-input.json"
        for operation in ("add", "remove", "change"):
            with self.subTest(operation=operation):
                target.write_text("original", encoding="utf-8")
                def changing_gate(*args, **kwargs):
                    if operation == "add":
                        extra.write_text("unexpected", encoding="utf-8")
                    elif operation == "remove":
                        target.unlink()
                    else:
                        before = target.stat()
                        target.write_text("modified", encoding="utf-8")
                        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
                    return [], {"errors": 0}
                with mock.patch.object(pc, "_check_audit_finalization", side_effect=changing_gate):
                    errors, result = pc.check_audit_finalization(self.root)
                self.assertTrue(any("inputs changed" in error for error in errors), errors)
                self.assertEqual(1, result["errors"])
                if extra.exists():
                    extra.unlink()

    def test_changed_external_source_is_rehashed_after_cached_read(self):
        target = self.fixture.base / "external-source.tex"
        target.write_text("original", encoding="utf-8")
        def changing_gate(*args, **kwargs):
            pc.sha256_file(target)
            before = target.stat()
            target.write_text("modified", encoding="utf-8")
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            return [], {"errors": 0}
        with mock.patch.object(pc, "_check_audit_finalization", side_effect=changing_gate):
            errors, result = pc.check_audit_finalization(self.root)
        self.assertTrue(any("Input changed" in error for error in errors), errors)
        self.assertEqual(1, result["errors"])
        self.assertIsNone(pc._FILE_DIGEST_SNAPSHOT.get())

    def test_failed_gate_clears_reuse_and_preserves_the_error(self):
        with mock.patch.object(pc, "_check_audit_finalization", side_effect=ValueError("unreadable evidence")):
            errors, result = pc.check_audit_finalization(self.root)
        self.assertEqual(["unreadable evidence"], errors)
        self.assertEqual(1, result["errors"])
        self.assertIsNone(pc._GATE_CONTEXT_CACHE.get())
        self.assertIsNone(pc._FILE_DIGEST_SNAPSHOT.get())

    def test_text_reads_preserve_bom_and_newlines_and_guard_external_spans(self):
        target = self.fixture.base / "external-span.tex"
        target.write_bytes(b"\xef\xbb\xbffirst\r\nsecond\rthird\n")
        expected = pc.read_text(target)
        with pc.gate_context_snapshot(self.root):
            self.assertEqual(expected, pc.read_text(target))
        def changing_gate(*args, **kwargs):
            self.assertEqual(expected, pc.read_text(target))
            target.write_text("changed external span", encoding="utf-8")
            return [], {"errors": 0}
        with mock.patch.object(pc, "_check_audit_finalization", side_effect=changing_gate):
            errors, result = pc.check_audit_finalization(self.root)
        self.assertTrue(any("Input changed" in error for error in errors), errors)
        self.assertEqual(1, result["errors"])


if __name__ == "__main__":
    unittest.main()
