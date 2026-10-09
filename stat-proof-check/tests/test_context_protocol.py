from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("context_protocol_fixture", HERE / "test_proofcheck.py")
fixture_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_module)
pc = fixture_module.proofcheck
read = fixture_module.read_json
write = fixture_module.write_json


class ContextProtocolTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.FinalizationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.audit
        self.manifest_path = self.root / "AUDIT_MANIFEST.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.ledger_path = self.fixture.make_complete_audit()
        self.original_identity = pc.protocol_identity()
        self.new_identity = dict(self.original_identity, validator_sha256="1" * 64)

    def revalidate(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            result = pc.cmd_revalidate_protocol(argparse.Namespace(root=self.root))
        return result, json.loads(output.getvalue())

    def current_challenge(self):
        manifest = read(self.manifest_path)
        manifest["protocol"]["challenge_contract_version"] = 3
        write(self.manifest_path, manifest)
        packet = pc.build_context_packet(self.root, "lem:main", "challenge")
        line = next(row["line"] for row in packet["source"]["proof"]["lines"] if "reflexivity" in row["text"])
        response = {
            "response_schema_version": 2, "unit_id": "lem:main",
            "independence_level": "fresh_context_same_model", "challenger_verdict": "verified",
            "conclusions": [{"conclusion_id": "C001", "verdict": "verified",
                "argument_status": "valid", "statement_status": "established",
                "decisive_reason": "The proof invokes reflexivity to establish x=x for the arbitrary real x in the statement.",
                "source_refs": [{"packet_pointer": "/source/proof", "start_line": line, "end_line": line}]}],
            "issue_assessments": [],
        }
        packet_path = self.fixture.base / "challenge-packet.json"
        response_path = self.fixture.base / "response.json"
        write(packet_path, packet)
        write(response_path, response)
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_record_challenge(argparse.Namespace(root=self.root, unit_id="lem:main", packet=packet_path, response=response_path))
            pc.cmd_bind_challenge(argparse.Namespace(root=self.root, unit_id="lem:main"))
            self.fixture.refresh_report_views()
        check = read(self.ledger_path)["independent_check"]
        return self.root / check["initial_response"]["artifact"]

    def test_two_code_upgrades_preserve_reviews_and_exact_origin_and_pass_current_gate(self):
        initial = self.current_challenge()
        ledger_bytes, initial_bytes = self.ledger_path.read_bytes(), initial.read_bytes()
        manifest = read(self.manifest_path)
        # Preserve the actual source bytes, including a UTF-8 BOM and CRLF.
        original_bytes = b"\xef\xbb\xbf" + (json.dumps(manifest, indent=2) + "\n").replace("\n", "\r\n").encode("utf-8")
        self.manifest_path.write_bytes(original_bytes)
        anchor = None
        for newer in (self.new_identity, dict(self.new_identity, skill_version="next-release", validator_sha256="2" * 64)):
            with self.subTest(identity=newer), mock.patch.object(pc, "protocol_identity", return_value=newer):
                result, receipt = self.revalidate()
                self.assertEqual(0, result, receipt)
                current = read(self.manifest_path)
                self.assertEqual(newer, {k: v for k, v in current["protocol"].items() if k != "challenge_contract_version"})
                self.assertEqual(self.original_identity, current["context_protocol"]["protocol"])
                if anchor is not None:
                    self.assertEqual(anchor, current["context_protocol"])
                anchor = current["context_protocol"]
                self.assertEqual(hashlib.sha256(original_bytes).hexdigest(), anchor["original_manifest_sha256"])
                self.assertEqual(original_bytes, (self.root / anchor["original_manifest_file"]).read_bytes())
                self.assertEqual(ledger_bytes, self.ledger_path.read_bytes())
                self.assertEqual(initial_bytes, initial.read_bytes())
                self.assertEqual([], pc.check_audit_finalization(self.root)[0])
                self.assertEqual("already_current", self.revalidate()[1]["status"])

    def test_contract_change_is_refused_without_writes(self):
        before = pc.audit_state_manifest(self.root)
        incompatible = dict(self.new_identity, evidence_contract_version=self.new_identity["evidence_contract_version"] + 1)
        with mock.patch.object(pc, "protocol_identity", return_value=incompatible):
            result, receipt = self.revalidate()
        self.assertEqual(1, result)
        self.assertIn("protocol.evidence_contract_version is not compatible", " ".join(receipt["errors"]))
        self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_source_change_still_invalidates_after_retention(self):
        with mock.patch.object(pc, "protocol_identity", return_value=self.new_identity):
            self.assertEqual(0, self.revalidate()[0])
            self.fixture.paper.write_text(self.fixture.paper.read_text(encoding="utf-8") + "% changed source\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source drift in included file"):
                pc.build_context_packet(self.root, "lem:main", "challenge")
            self.assertTrue(pc.check_audit_finalization(self.root)[0])

    def test_semantic_obligation_change_still_invalidates_after_retention(self):
        with mock.patch.object(pc, "protocol_identity", return_value=self.new_identity):
            self.assertEqual(0, self.revalidate()[0])
            ledger = read(self.ledger_path)
            ledger["obligation"]["hypotheses"] = ["x is nonnegative"]
            write(self.ledger_path, ledger)
            with self.assertRaisesRegex(ValueError, "The normalized obligation is incomplete or stale"):
                pc.build_context_packet(self.root, "lem:main", "challenge")
            self.assertTrue(pc.check_audit_finalization(self.root)[0])

    def test_corrupt_or_missing_origin_is_rejected_and_never_replaced(self):
        with mock.patch.object(pc, "protocol_identity", return_value=self.new_identity):
            self.assertEqual(0, self.revalidate()[0])
            manifest = read(self.manifest_path)
            origin = self.root / manifest["context_protocol"]["original_manifest_file"]
            origin.write_bytes(origin.read_bytes() + b" ")
            before = pc.audit_state_manifest(self.root)
            self.assertEqual(1, self.revalidate()[0])
            self.assertEqual(before, pc.audit_state_manifest(self.root))
            self.assertTrue(pc.load_audit_manifest(self.root)[2])
            origin.unlink()
            with self.assertRaisesRegex(ValueError, "missing, redirected, or changed"):
                pc.context_protocol_identity(self.root, manifest)

    def test_null_unknown_or_forged_retained_identity_is_rejected(self):
        with mock.patch.object(pc, "protocol_identity", return_value=self.new_identity):
            self.assertEqual(0, self.revalidate()[0])
            original = read(self.manifest_path)
            for mutate in (
                lambda m: m.update(context_protocol=None),
                lambda m: m["context_protocol"].update(unrecognized=True),
                lambda m: m["context_protocol"]["protocol"].update(validator_sha256="3" * 64),
            ):
                with self.subTest(mutate=mutate):
                    altered = json.loads(json.dumps(original))
                    mutate(altered)
                    write(self.manifest_path, altered)
                    before = pc.audit_state_manifest(self.root)
                    result, receipt = self.revalidate()
                    self.assertEqual(1, result, receipt)
                    self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_unknown_or_wrong_type_recorded_contract_cannot_publish_bad_anchor(self):
        original = read(self.manifest_path)
        with mock.patch.object(pc, "protocol_identity", return_value=self.new_identity):
            for mutate in (
                lambda m: m["protocol"].update(unrecognized=True),
                lambda m: m["protocol"].update(closure_contract_version=True),
            ):
                altered = json.loads(json.dumps(original))
                mutate(altered)
                write(self.manifest_path, altered)
                before = pc.audit_state_manifest(self.root)
                self.assertEqual(1, self.revalidate()[0])
                self.assertEqual(before, pc.audit_state_manifest(self.root))


if __name__ == "__main__":
    unittest.main()
