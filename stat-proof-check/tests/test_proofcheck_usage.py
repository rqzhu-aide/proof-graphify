from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck_usage.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_usage", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
proofcheck_usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proofcheck_usage)


class ProofcheckUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "portable audit"
        (self.root / "audit").mkdir(parents=True)
        (self.root / "AUDIT_MANIFEST.json").write_text(
            '{"schema_version": 5}\n', encoding="utf-8", newline="\n"
        )
        self.usage_file = self.root / proofcheck_usage.USAGE_RELATIVE_PATH
        self.finalization_patch = mock.patch.object(
            proofcheck_usage, "current_usable_finalization", return_value=False
        )
        self.finalization_patch.start()

    def tearDown(self) -> None:
        self.finalization_patch.stop()
        self.temporary.cleanup()

    def args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "root": self.root,
            "event_id": "E001",
            "stage": "unit_primary",
            "work_packets": 1,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "token_source": "unavailable",
            "cache_outcome": "not_used",
            "unit_id": [],
            "notes": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def record(self, **overrides: object) -> dict:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck_usage.cmd_record(self.args(**overrides))
        self.assertEqual(0, status)
        return json.loads(output.getvalue())

    def summary(self, output_format: str = "json") -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck_usage.cmd_summary(
                argparse.Namespace(root=self.root, format=output_format)
            )
        return status, output.getvalue()

    def test_records_portable_data_and_preserves_null_distinct_from_zero(self) -> None:
        self.record(
            event_id="E001",
            work_packets=2,
            unit_id=["lem:a", "lem:a"],
            cache_outcome="miss",
            notes="Primary proof pass.",
        )
        self.record(
            event_id="E002",
            stage="challenger",
            work_packets=1,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=5,
            token_source="measured",
            cache_outcome="hit",
            unit_id=["lem:a"],
        )

        stored = json.loads(self.usage_file.read_text(encoding="utf-8"))
        self.assertTrue(stored["observational_only"])
        self.assertEqual(["lem:a"], stored["events"][0]["unit_ids"])
        self.assertIsNone(stored["events"][0]["tokens"]["input"])
        self.assertEqual(0, stored["events"][1]["tokens"]["input"])
        self.assertNotIn(str(self.root), self.usage_file.read_text(encoding="utf-8"))

        status, output = self.summary()
        summary = json.loads(output)
        self.assertEqual(0, status)
        self.assertEqual("present", summary["status"])
        self.assertEqual(2, summary["events"])
        self.assertEqual(3, summary["work_packets"])
        self.assertEqual(0, summary["tokens"]["input"]["total"])
        self.assertEqual(1, summary["tokens"]["input"]["events_with_value"])
        self.assertEqual(1, summary["tokens"]["input"]["events_without_value"])
        self.assertIsNone(summary["tokens"]["reasoning"]["total"])
        self.assertEqual(1, summary["cache_outcomes"]["hit"])
        self.assertEqual(1, summary["cache_outcomes"]["miss"])

    def test_duplicate_event_id_is_rejected_without_changing_file(self) -> None:
        self.record(event_id="E001")
        before = self.usage_file.read_bytes()

        with self.assertRaisesRegex(ValueError, "Duplicate telemetry event ID"):
            proofcheck_usage.cmd_record(self.args(event_id="E001"))

        self.assertEqual(before, self.usage_file.read_bytes())

    def test_unavailable_source_rejects_even_zero_token_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires every token field to be null"):
            proofcheck_usage.cmd_record(
                self.args(token_source="unavailable", input_tokens=0)
            )
        self.assertFalse(self.usage_file.exists())

    def test_measured_source_requires_at_least_one_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires at least one token count"):
            proofcheck_usage.cmd_record(self.args(token_source="measured"))
        self.assertFalse(self.usage_file.exists())

    def test_negative_direct_value_is_rejected_before_writing(self) -> None:
        with self.assertRaisesRegex(ValueError, "work-packets must be a nonnegative"):
            proofcheck_usage.cmd_record(self.args(work_packets=-1))
        self.assertFalse(self.usage_file.exists())

        parser = proofcheck_usage.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "record",
                    "--root",
                    str(self.root),
                    "--event-id",
                    "E001",
                    "--stage",
                    "unit_primary",
                    "--work-packets",
                    "-1",
                ]
            )

    def test_atomic_replace_failure_preserves_previous_record(self) -> None:
        self.record(event_id="E001")
        before = self.usage_file.read_bytes()

        with mock.patch.object(
            proofcheck_usage.os, "replace", side_effect=OSError("interrupted")
        ):
            with self.assertRaisesRegex(OSError, "interrupted"):
                proofcheck_usage.cmd_record(self.args(event_id="E002"))

        self.assertEqual(before, self.usage_file.read_bytes())
        temporary_files = list(
            self.usage_file.parent.glob(".RUN_USAGE.json.*.proofcheck.tmp")
        )
        self.assertEqual([], temporary_files)

    def test_current_usable_finalization_refuses_mutation(self) -> None:
        self.finalization_patch.stop()
        try:
            with mock.patch.object(
                proofcheck_usage,
                "current_usable_finalization",
                return_value=True,
            ):
                with self.assertRaisesRegex(ValueError, "current usable FINALIZATION"):
                    proofcheck_usage.cmd_record(self.args())
        finally:
            self.finalization_patch.start()
        self.assertFalse(self.usage_file.exists())

    def test_absent_summary_is_read_only_and_keeps_unknown_totals_null(self) -> None:
        before = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
        )
        status, output = self.summary()
        after = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
        )
        summary = json.loads(output)

        self.assertEqual(0, status)
        self.assertEqual("absent", summary["status"])
        self.assertTrue(summary["observational_only"])
        self.assertEqual(0, summary["events"])
        self.assertEqual(0, summary["work_packets"])
        self.assertIsNone(summary["tokens"]["input"]["total"])
        self.assertEqual(before, after)

    def test_markdown_summary_renders_zero_and_unavailable_separately(self) -> None:
        self.record(
            token_source="reported",
            input_tokens=0,
            output_tokens=0,
        )
        status, output = self.summary("markdown")

        self.assertEqual(0, status)
        self.assertIn("| input | 0 |", output)
        self.assertIn("| reasoning | unavailable |", output)

    def test_markdown_summary_escapes_stage_table_delimiters(self) -> None:
        self.record(stage="primary|batch")

        status, output = self.summary("markdown")

        self.assertEqual(0, status)
        self.assertIn("| primary\\|batch | 1 | 1 |", output)


if __name__ == "__main__":
    unittest.main()
