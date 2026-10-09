from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_canaries", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
proofcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proofcheck)

CANARIES = SCRIPT.parents[1] / "assets" / "canaries"


def response(
    canary_id: str,
    argument_status: str,
    statement_status: str,
    defect_lines: list[int],
) -> dict:
    return {
        "canary_id": canary_id,
        "argument_status": argument_status,
        "statement_status": statement_status,
        "defect_lines": defect_lines,
        "justification": (
            "The judgment follows from re-deriving the displayed inequality "
            "against the exact stated hypotheses of this canary lemma."
        ),
    }


class CanaryAssetTests(unittest.TestCase):
    def test_index_and_keys_are_complete_and_consistent(self) -> None:
        rows = proofcheck.load_canary_index()
        self.assertGreaterEqual(len(rows), 5)
        flawed = 0
        correct = 0
        for row in rows:
            with self.subTest(canary=row["id"]):
                source = CANARIES / row["source"]
                self.assertTrue(source.is_file())
                key = proofcheck.load_canary_key(row["id"])
                self.assertEqual(row["id"], key["canary_id"])
                expected = key["expected"]
                self.assertTrue(
                    set(expected["argument_status"]).issubset(
                        proofcheck.CANARY_ARGUMENT_STATUSES
                    )
                )
                self.assertTrue(
                    set(expected["statement_status"]).issubset(
                        proofcheck.CANARY_STATEMENT_STATUSES
                    )
                )
                line_count = len(source.read_text(encoding="utf-8").splitlines())
                for span in expected["defect_line_ranges"]:
                    self.assertEqual(2, len(span))
                    self.assertLessEqual(1, span[0])
                    self.assertLessEqual(span[0], span[1])
                    self.assertLessEqual(span[1], line_count)
                if expected["defect_line_ranges"]:
                    flawed += 1
                    self.assertNotIn("established", expected["statement_status"])
                    self.assertNotIn("valid", expected["argument_status"])
                else:
                    correct += 1
                    self.assertEqual(["valid"], expected["argument_status"])
                    self.assertEqual(
                        ["established"], expected["statement_status"]
                    )
        self.assertGreaterEqual(flawed, 3)
        self.assertGreaterEqual(correct, 2)

    def test_packet_is_blinded_and_refuses_audit_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            packet_path = Path(temp) / "canary.packet.json"
            with contextlib.redirect_stdout(io.StringIO()):
                status = proofcheck.cmd_canary_packet(
                    argparse.Namespace(
                        canary_id="continuous-mapping", output=packet_path
                    )
                )
            self.assertEqual(0, status)
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            serialized = json.dumps(packet)
            self.assertNotIn("expected", serialized)
            self.assertNotIn("rationale", serialized)
            self.assertNotIn("defect_line_ranges", serialized)
            self.assertEqual("continuous-mapping", packet["canary_id"])
            source_text = "\n".join(row["text"] for row in packet["source"])
            self.assertIn("uniformly continuous", source_text)

            fake_root = Path(temp) / "audit-root"
            (fake_root / "audit").mkdir(parents=True)
            (fake_root / "AUDIT_MANIFEST.json").write_text(
                "{}", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "outside any audit root"):
                proofcheck.cmd_canary_packet(
                    argparse.Namespace(
                        canary_id="chebyshev",
                        output=fake_root / "inside.packet.json",
                    )
                )


class CanaryGradingTests(unittest.TestCase):
    def grade(self, canary_id: str, row: dict) -> tuple[bool, list[str]]:
        key = proofcheck.load_canary_key(canary_id)
        passed, reasons, _ = proofcheck.grade_canary_response(row, key)
        return passed, reasons

    def test_flawed_canaries_accept_detection_and_reject_sleep(self) -> None:
        passed, _ = self.grade(
            "bounded-drift",
            response("bounded-drift", "invalid", "refuted", [15]),
        )
        self.assertTrue(passed)
        passed, reasons = self.grade(
            "bounded-drift",
            response("bounded-drift", "valid", "established", []),
        )
        self.assertFalse(passed)
        self.assertTrue(any("argument_status" in reason for reason in reasons))
        passed, reasons = self.grade(
            "bounded-drift",
            response("bounded-drift", "invalid", "refuted", [12]),
        )
        self.assertFalse(passed)
        self.assertTrue(
            any("do not locate" in reason for reason in reasons), reasons
        )
        passed, _ = self.grade(
            "signed-markov",
            response("signed-markov", "invalid", "not_established", [12]),
        )
        self.assertTrue(passed)

    def test_true_statement_canary_rejects_fabricated_refutation(self) -> None:
        passed, _ = self.grade(
            "continuous-mapping",
            response("continuous-mapping", "invalid", "not_established", [12, 13]),
        )
        self.assertTrue(passed)
        passed, reasons = self.grade(
            "continuous-mapping",
            response("continuous-mapping", "invalid", "refuted", [12]),
        )
        self.assertFalse(passed)
        self.assertTrue(
            any("statement_status" in reason for reason in reasons), reasons
        )
        passed, _ = self.grade(
            "continuous-mapping",
            response("continuous-mapping", "gap", "established", [12]),
        )
        self.assertFalse(passed)

    def test_correct_canaries_reject_overflagging_and_shotguns(self) -> None:
        passed, _ = self.grade(
            "finite-max", response("finite-max", "valid", "established", [])
        )
        self.assertTrue(passed)
        passed, reasons = self.grade(
            "finite-max",
            response("finite-max", "valid", "established", [15]),
        )
        self.assertFalse(passed)
        self.assertTrue(
            any("none exists" in reason for reason in reasons), reasons
        )
        passed, reasons = self.grade(
            "bounded-drift",
            response(
                "bounded-drift",
                "invalid",
                "refuted",
                [11, 12, 13, 14, 15, 16, 17],
            ),
        )
        self.assertFalse(passed)
        self.assertTrue(
            any("too many lines" in reason for reason in reasons), reasons
        )

    def test_malformed_responses_fail_closed(self) -> None:
        row = response("chebyshev", "valid", "established", [])
        row["justification"] = "TBD"
        passed, reasons = self.grade("chebyshev", row)
        self.assertFalse(passed)
        self.assertTrue(
            any("justification" in reason for reason in reasons), reasons
        )
        row = response("chebyshev", "valid", "established", [])
        row["confidence"] = "high"
        passed, reasons = self.grade("chebyshev", row)
        self.assertFalse(passed)
        self.assertTrue(
            any("unknown fields" in reason for reason in reasons), reasons
        )


class CalibrationRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "audit-root"
        (self.root / "audit" / "07_runtime").mkdir(parents=True)
        (self.root / "AUDIT_MANIFEST.json").write_text(
            json.dumps(
                {
                    "protocol": proofcheck.protocol_identity(),
                    "source_snapshot": {"sha256": "a" * 64},
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.responses = Path(self.temp.name) / "responses"
        self.responses.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_response(self, name: str, row: dict) -> Path:
        path = self.responses / name
        path.write_text(
            json.dumps(row, ensure_ascii=False, indent=1),
            encoding="utf-8",
            newline="\n",
        )
        return path

    def grade_session(
        self,
        session_id: str,
        rows: list[dict],
        checker_context_id: str | None = None,
        checker_configuration_id: str = "proofcheck-test-config",
    ) -> int:
        paths = [
            self.write_response(f"{session_id}-{index}.json", row)
            for index, row in enumerate(rows, 1)
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            return proofcheck.cmd_canary_grade(
                argparse.Namespace(
                    response=paths,
                    session_id=session_id,
                    root=self.root,
                    checker_profile_id="checker-test-profile",
                    checker_configuration_id=checker_configuration_id,
                    checker_context_id=(
                        checker_context_id or f"fresh-context-{session_id}"
                    ),
                    reviewed_binding=True,
                )
            )

    def test_source_and_validator_drift_do_not_stale_calibration(self) -> None:
        """Calibration attests the checker, not the paper: a snapshot refresh
        or validator release must not invalidate a recorded session, while a
        changed canary bundle still must."""
        status = self.grade_session(
            "cal-001",
            [
                response("bounded-drift", "invalid", "refuted", [14, 15, 16]),
                response("finite-max", "valid", "established", []),
            ],
        )
        self.assertEqual(0, status)
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

        manifest_path = self.root / "AUDIT_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_snapshot"]["sha256"] = "b" * 64
        manifest_path.write_text(
            json.dumps(manifest), encoding="utf-8", newline="\n"
        )
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        session = calibration["sessions"][0]
        session["audit_binding"]["source_snapshot_sha256"] = "c" * 64
        session["audit_binding"]["validator_sha256"] = "d" * 64
        calibration_path.write_text(
            json.dumps(calibration), encoding="utf-8", newline="\n"
        )
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

        session["audit_binding"]["validator_sha256"] = "not-a-digest"
        calibration_path.write_text(
            json.dumps(calibration), encoding="utf-8", newline="\n"
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("must be a SHA-256 digest" in error for error in errors),
            errors,
        )

        session["audit_binding"]["validator_sha256"] = "d" * 64
        calibration["canary_bundle"]["files"][0]["sha256"] = "0" * 64
        calibration_path.write_text(
            json.dumps(calibration), encoding="utf-8", newline="\n"
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any(
                "canary_bundle does not match the sealed bundle" in error
                for error in errors
            ),
            errors,
        )

    def result_receipt(self, row: dict) -> dict:
        key = proofcheck.load_canary_key(row["canary_id"])
        passed, reasons, got = proofcheck.grade_canary_response(row, key)
        return {
            "canary_id": row["canary_id"],
            "passed": passed,
            "reasons": reasons,
            "got": got,
            "response_sha256": proofcheck.canonical_sha256(got),
        }

    def session_receipt(self, session_id: str, rows: list[dict]) -> dict:
        results = [self.result_receipt(row) for row in rows]
        return {
            "session_id": session_id,
            "graded_utc": "2026-08-09T00:00:00+00:00",
            "checker_binding": {
                "checker_profile_id": "checker-test-profile",
                "checker_configuration_id": "proofcheck-test-config",
                "checker_context_id": f"fresh-context-{session_id}",
                "reviewed": True,
                "scope": proofcheck.CHECKER_BINDING_SCOPE,
                "automatic_identity_verification": False,
                "limitation": proofcheck.CHECKER_BINDING_LIMITATION,
            },
            "audit_binding": proofcheck.calibration_audit_binding(self.root),
            "results": results,
            "passed": all(result["passed"] for result in results),
        }

    def calibration_record(self, sessions: list[dict]) -> dict:
        return {
            "calibration_schema_version": proofcheck.CALIBRATION_SCHEMA_VERSION,
            "canary_bundle": proofcheck.canary_bundle_identity(),
            "sessions": sessions,
        }

    def test_sessions_are_recorded_and_gate_finalization(self) -> None:
        status = self.grade_session(
            "cal-001",
            [
                response("bounded-drift", "invalid", "refuted", [14, 15, 16]),
                response("finite-max", "invalid", "not_established", [15]),
            ],
        )
        self.assertEqual(1, status)
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("checker calibration failed" in error for error in errors),
            errors,
        )

        status = self.grade_session(
            "cal-002",
            [
                response("finite-max", "valid", "established", []),
                response("bounded-drift", "invalid", "refuted", [14, 15, 16]),
            ],
        )
        self.assertEqual(0, status)
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        self.assertEqual(2, len(calibration["sessions"]))
        self.assertEqual(2, calibration["calibration_schema_version"])
        self.assertEqual(
            proofcheck.canary_bundle_identity(), calibration["canary_bundle"]
        )
        serialized = json.dumps(calibration)
        self.assertNotIn("expected", serialized)
        self.assertNotIn("defect_line_ranges", serialized)
        self.assertIn("justification", serialized)

        with self.assertRaisesRegex(ValueError, "already exists"):
            self.grade_session(
                "cal-002",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("chebyshev", "valid", "established", []),
                ],
            )
        with self.assertRaisesRegex(ValueError, "reused across sessions"):
            self.grade_session(
                "cal-003",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("chebyshev", "valid", "established", []),
                ],
                checker_context_id="fresh-context-cal-001",
            )
        self.assertEqual(
            2,
            len(json.loads(calibration_path.read_text(encoding="utf-8"))["sessions"]),
        )

    def test_unbalanced_sessions_are_refused_before_recording(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "one flawed-style and one correct-style"
        ):
            self.grade_session(
                "cal-solo",
                [response("chebyshev", "valid", "established", [])],
            )
        with self.assertRaisesRegex(
            ValueError, "one flawed-style and one correct-style"
        ):
            self.grade_session(
                "cal-two-flawed",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("signed-markov", "invalid", "refuted", [12]),
                ],
            )
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        self.assertFalse(calibration_path.is_file())

        recorded = self.calibration_record(
            [
                self.session_receipt(
                    "cal-hand",
                    [response("chebyshev", "valid", "established", [])],
                )
            ]
        )
        calibration_path.parent.mkdir(parents=True, exist_ok=True)
        calibration_path.write_text(
            json.dumps(recorded), encoding="utf-8", newline="\n"
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any(
                "one flawed-style and one correct-style" in error
                for error in errors
            ),
            errors,
        )

        older = self.session_receipt(
            "cal-unbalanced-old",
            [response("chebyshev", "valid", "established", [])],
        )
        latest = self.session_receipt(
            "cal-balanced-latest",
            [
                response("bounded-drift", "invalid", "refuted", [15]),
                response("finite-max", "valid", "established", []),
            ],
        )
        older["graded_utc"] = "2026-08-09T00:00:00.000001+00:00"
        latest["graded_utc"] = "2026-08-09T00:00:00.000002+00:00"
        calibration_path.write_text(
            json.dumps(self.calibration_record([older, latest])),
            encoding="utf-8",
            newline="\n",
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any(
                "sessions[1]" in error
                and "one flawed-style and one correct-style" in error
                for error in errors
            ),
            errors,
        )

    def test_absent_record_blocks_and_malformed_record_is_an_error(self) -> None:
        bare = Path(self.temp.name) / "bare-root"
        bare.mkdir()
        errors = proofcheck.checker_calibration_errors(bare)
        self.assertTrue(
            any("checker calibration required" in error for error in errors),
            errors,
        )
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        malformed = self.calibration_record([{}])
        calibration_path.write_text(
            json.dumps(malformed), encoding="utf-8", newline="\n"
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("exact fields" in error for error in errors), errors
        )

    def test_receipts_are_regraded_and_duplicates_are_rejected(self) -> None:
        self.assertEqual(
            0,
            self.grade_session(
                "cal-001",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("finite-max", "valid", "established", []),
                ],
            ),
        )
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        result = calibration["sessions"][-1]["results"][0]
        result["got"] = {}
        result["response_sha256"] = proofcheck.canonical_sha256({})
        calibration_path.write_text(
            json.dumps(calibration), encoding="utf-8", newline="\n"
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("disagrees with re-grading" in error for error in errors), errors
        )

        calibration["sessions"][-1]["results"][0] = self.result_receipt(
            response("bounded-drift", "invalid", "refuted", [15])
        )
        calibration["sessions"][-1]["results"].append(
            dict(calibration["sessions"][-1]["results"][0])
        )
        calibration_path.write_text(
            json.dumps(calibration), encoding="utf-8", newline="\n"
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(any("duplicated" in error for error in errors), errors)

    def test_calibration_currency_is_profile_and_configuration(self) -> None:
        passing = [
            response("bounded-drift", "invalid", "refuted", [15]),
            response("finite-max", "valid", "established", []),
        ]
        self.assertEqual(0, self.grade_session("cal-context-1", passing))
        first = proofcheck.current_calibration_receipt(self.root)

        self.assertEqual(0, self.grade_session("cal-context-2", passing))
        second = proofcheck.current_calibration_receipt(self.root)
        self.assertEqual(first, second)

        self.assertEqual(
            0,
            self.grade_session(
                "cal-configuration-2",
                passing,
                checker_configuration_id="proofcheck-test-config-2",
            ),
        )
        third = proofcheck.current_calibration_receipt(self.root)
        self.assertNotEqual(second["sha256"], third["sha256"])

    def test_bundle_identity_and_preexisting_artifacts_are_provenance(
        self,
    ) -> None:
        ledger = (
            self.root
            / "audit"
            / "04_local_checks"
            / "lem-existing.ledger.json"
        )
        ledger.parent.mkdir(parents=True)
        ledger.write_text('{"state":"before"}', encoding="utf-8", newline="\n")
        self.assertEqual(
            0,
            self.grade_session(
                "cal-posthoc",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("finite-max", "valid", "established", []),
                ],
            ),
        )
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [
                {
                    "file": "audit/04_local_checks/lem-existing.ledger.json",
                    "sha256": proofcheck.sha256_file(ledger),
                }
            ],
            calibration["sessions"][-1]["audit_binding"][
                "preexisting_proof_artifacts"
            ],
        )
        ledger.write_text('{"state":"recompiled"}', encoding="utf-8", newline="\n")
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

        calibration["canary_bundle"]["sha256"] = "0" * 64
        calibration_path.write_text(
            json.dumps(calibration), encoding="utf-8", newline="\n"
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(any("sealed bundle" in e for e in errors), errors)

    def test_only_live_ledgers_are_snapshotted_and_sessions_are_chronological(
        self,
    ) -> None:
        history_ledger = (
            self.root
            / "audit"
            / "04_local_checks"
            / "history"
            / "old.ledger.json"
        )
        history_ledger.parent.mkdir(parents=True)
        history_ledger.write_text("{}", encoding="utf-8", newline="\n")
        self.assertEqual([], proofcheck.calibration_proof_artifacts(self.root))

        later = self.session_receipt(
            "cal-later",
            [
                response("bounded-drift", "invalid", "refuted", [15]),
                response("finite-max", "valid", "established", []),
            ],
        )
        earlier = self.session_receipt(
            "cal-earlier",
            [
                response("bounded-drift", "invalid", "refuted", [15]),
                response("finite-max", "valid", "established", []),
            ],
        )
        later["graded_utc"] = "2026-08-09T01:00:00+00:00"
        earlier["graded_utc"] = later["graded_utc"]
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration_path.write_text(
            json.dumps(self.calibration_record([later, earlier])),
            encoding="utf-8",
            newline="\n",
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(any("not strictly later" in error for error in errors), errors)

        earlier["graded_utc"] = "2026-08-09T01:00:00.000001+00:00"
        earlier["checker_binding"]["checker_context_id"] = later[
            "checker_binding"
        ]["checker_context_id"]
        calibration_path.write_text(
            json.dumps(self.calibration_record([later, earlier])),
            encoding="utf-8",
            newline="\n",
        )
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("checker_context_id is reused" in error for error in errors),
            errors,
        )

    def test_stale_record_is_archived_byte_exact_before_fresh_session(self) -> None:
        self.assertEqual(
            0,
            self.grade_session(
                "cal-old",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("finite-max", "valid", "established", []),
                ],
            ),
        )
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        stale = json.loads(calibration_path.read_text(encoding="utf-8"))
        stale["canary_bundle"]["sha256"] = "0" * 64
        stale_bytes = b"\xef\xbb\xbf" + json.dumps(
            stale, separators=(",", ":")
        ).encode("utf-8")
        calibration_path.write_bytes(stale_bytes)
        digest = proofcheck.sha256_file(calibration_path)

        self.assertEqual(
            0,
            self.grade_session(
                "cal-fresh",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("finite-max", "valid", "established", []),
                ],
            ),
        )
        archive = (
            calibration_path.parent
            / "calibration-history"
            / f"CALIBRATION.{digest}.json"
        )
        self.assertEqual(stale_bytes, archive.read_bytes())
        current = json.loads(calibration_path.read_text(encoding="utf-8"))
        self.assertEqual(["cal-fresh"], [s["session_id"] for s in current["sessions"]])
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

        with self.assertRaisesRegex(ValueError, "reused across sessions"):
            self.grade_session(
                "cal-reused",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("finite-max", "valid", "established", []),
                ],
                checker_context_id="fresh-context-cal-old",
            )
        current = json.loads(calibration_path.read_text(encoding="utf-8"))
        self.assertEqual(["cal-fresh"], [s["session_id"] for s in current["sessions"]])

        archive.write_bytes(stale_bytes + b"\n")
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("history entry hash is stale" in error for error in errors),
            errors,
        )

    def test_malformed_record_is_archived_byte_exact_before_recovery(self) -> None:
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        malformed_bytes = b'{"calibration_schema_version":2,"sessions":['
        calibration_path.write_bytes(malformed_bytes)
        digest = proofcheck.sha256_file(calibration_path)

        self.assertEqual(
            0,
            self.grade_session(
                "cal-recovered",
                [
                    response("bounded-drift", "invalid", "refuted", [15]),
                    response("finite-max", "valid", "established", []),
                ],
            ),
        )
        archive = (
            calibration_path.parent
            / "calibration-history"
            / f"CALIBRATION.{digest}.json"
        )
        self.assertEqual(malformed_bytes, archive.read_bytes())
        current = json.loads(calibration_path.read_text(encoding="utf-8"))
        self.assertEqual(
            ["cal-recovered"],
            [session["session_id"] for session in current["sessions"]],
        )

    def test_redirected_calibration_record_is_refused_without_archival(self) -> None:
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        original_bytes = b'{"redirected":"sentinel"}'
        calibration_path.write_bytes(original_bytes)
        real_detector = proofcheck.path_redirect_kind

        def redirect_calibration_only(path: Path) -> str | None:
            if Path(path) == calibration_path:
                return "symlink"
            return real_detector(Path(path))

        with mock.patch.object(
            proofcheck,
            "path_redirect_kind",
            side_effect=redirect_calibration_only,
        ):
            with self.assertRaisesRegex(ValueError, "traverses a symlink"):
                self.grade_session(
                    "cal-refused",
                    [
                        response("bounded-drift", "invalid", "refuted", [15]),
                        response("finite-max", "valid", "established", []),
                    ],
                )
        self.assertEqual(original_bytes, calibration_path.read_bytes())
        self.assertFalse(
            (calibration_path.parent / "calibration-history").exists()
        )

    def test_calibration_history_rejects_redirected_and_nonregular_paths(
        self,
    ) -> None:
        passing = [
            response("bounded-drift", "invalid", "refuted", [15]),
            response("finite-max", "valid", "established", []),
        ]
        self.assertEqual(0, self.grade_session("cal-current", passing))
        history = (
            self.root
            / "audit"
            / "07_runtime"
            / "calibration-history"
        )
        history.mkdir()
        nonregular = history / f"CALIBRATION.{'0' * 64}.json"
        nonregular.mkdir()
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("history entry is not a regular file" in error for error in errors),
            errors,
        )
        nonregular.rmdir()

        noncanonical = history / "CALIBRATION.old.json"
        noncanonical.write_text("{}", encoding="utf-8", newline="\n")
        errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("history entry has a noncanonical name" in error for error in errors),
            errors,
        )
        noncanonical.unlink()

        real_detector = proofcheck.path_redirect_kind

        def redirect_history_only(path: Path) -> str | None:
            if Path(path) == history:
                return "symlink"
            return real_detector(Path(path))

        with mock.patch.object(
            proofcheck,
            "path_redirect_kind",
            side_effect=redirect_history_only,
        ):
            errors = proofcheck.checker_calibration_errors(self.root)
        self.assertTrue(
            any("calibration history is redirected" in error for error in errors),
            errors,
        )

    def test_concurrent_grade_cannot_overwrite_locked_session(self) -> None:
        passing = [
            response("bounded-drift", "invalid", "refuted", [15]),
            response("finite-max", "valid", "established", []),
        ]
        self.assertEqual(0, self.grade_session("cal-base", passing))
        calibration_path = (
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        real_atomic_write = proofcheck.atomic_write_json
        interleaved = False

        def force_interleaving(path: Path, value: dict) -> None:
            nonlocal interleaved
            if Path(path) == calibration_path and not interleaved:
                interleaved = True
                with self.assertRaisesRegex(
                    ValueError, "in progress or a stale lock remains"
                ):
                    self.grade_session("cal-loser", passing)
                self.assertTrue(
                    any(
                        "update is in progress" in error
                        for error in proofcheck.checker_calibration_errors(
                            self.root
                        )
                    )
                )
                with self.assertRaisesRegex(
                    ValueError, "calibration is locked"
                ):
                    proofcheck.current_calibration_receipt(self.root)
            real_atomic_write(Path(path), value)

        with mock.patch.object(
            proofcheck,
            "atomic_write_json",
            side_effect=force_interleaving,
        ):
            self.assertEqual(0, self.grade_session("cal-winner", passing))
        self.assertTrue(interleaved)
        calibration = json.loads(
            calibration_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            ["cal-base", "cal-winner"],
            [session["session_id"] for session in calibration["sessions"]],
        )
        self.assertFalse(proofcheck.calibration_update_lock_path(self.root).exists())
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

    def test_parser_registers_canary_commands(self) -> None:
        parser = proofcheck.build_parser()
        args = parser.parse_args(["canary-list"])
        self.assertIs(args.func, proofcheck.cmd_canary_list)
        args = parser.parse_args(
            ["canary-packet", "--canary-id", "chebyshev", "--output", "p.json"]
        )
        self.assertIs(args.func, proofcheck.cmd_canary_packet)
        args = parser.parse_args(
            [
                "canary-grade",
                "--response",
                "a.json",
                "--response",
                "b.json",
                "--session-id",
                "cal-001",
                "--root",
                "audit-root",
                "--checker-profile-id",
                "checker-test-profile",
                "--checker-configuration-id",
                "proofcheck-test-config",
                "--checker-context-id",
                "fresh-context-cal-001",
                "--reviewed-binding",
            ]
        )
        self.assertIs(args.func, proofcheck.cmd_canary_grade)
        self.assertEqual(Path("audit-root"), args.root)


if __name__ == "__main__":
    unittest.main()
