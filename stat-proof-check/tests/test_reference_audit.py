from __future__ import annotations

import argparse
import contextlib
import importlib.util
import html
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_reference", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
proofcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proofcheck)

REFERENCE = SCRIPT.parents[2] / "tests" / "fixtures" / "reference-audit"
REFRESH_SCRIPT = REFERENCE / "refresh_reference_audit.py"
REFRESH_SPEC = importlib.util.spec_from_file_location(
    "reference_refresh", REFRESH_SCRIPT
)
if REFRESH_SPEC is None or REFRESH_SPEC.loader is None:
    raise RuntimeError(f"Cannot load {REFRESH_SCRIPT}")
reference_refresh = importlib.util.module_from_spec(REFRESH_SPEC)
REFRESH_SPEC.loader.exec_module(reference_refresh)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ReferenceAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "proofcheck-audit"
        shutil.copytree(REFERENCE / "proofcheck-audit", self.root)
        self.report_path = self.root / proofcheck.preferred_report_path(
            read_json(self.root / "AUDIT_MANIFEST.json"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_shipped_manifest_records_historical_contracts(self) -> None:
        shipped = read_json(REFERENCE / "proofcheck-audit" / "AUDIT_MANIFEST.json")
        self.assertFalse(proofcheck.protocol_matches_current(shipped["protocol"]))
        self.assertEqual(3, proofcheck.challenge_contract_version(shipped))
        self.assertTrue(proofcheck.uses_html_report(shipped))

    def test_shipped_audit_refuses_current_finalization(self) -> None:
        errors, result = proofcheck.check_audit_finalization(self.root)
        self.assertTrue(any("validator_sha256" in error for error in errors))
        self.assertGreater(result["errors"], 0)

    def test_shipped_audit_cannot_be_redelivered_without_review(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_finalize(argparse.Namespace(root=self.root))
        self.assertNotEqual(0, status)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            delivery = proofcheck.cmd_delivery_check(
                argparse.Namespace(root=self.root)
            )
        self.assertNotEqual(0, delivery)
        result = json.loads(stdout.getvalue())
        self.assertEqual("NONFINAL", result["delivery_status"])
        self.assertFalse(result["usable_finalization"])
        self.assertEqual("stale", result["freshness"])

    def test_shipped_audit_exercises_the_new_evidence_gates(self) -> None:
        lem = read_json(
            self.root / "audit" / "04_local_checks" / "lem-growing-max.ledger.json"
        )
        failures = [
            move["failure"]
            for step in lem["steps"]
            for move in (step.get("inference") or {}).get("moves", [])
            if isinstance(move, dict) and isinstance(move.get("failure"), dict)
        ]
        counterexamples = [
            failure
            for failure in failures
            if failure.get("kind") == "counterexample"
        ]
        self.assertTrue(counterexamples)
        for failure in counterexamples:
            computation = failure["computation"]
            self.assertEqual("instantiated", computation["status"])
            script = (
                self.root / "audit" / "04_local_checks" / computation["script_file"]
            ).resolve()
            self.assertTrue(script.is_file())
            self.assertEqual(
                proofcheck.sha256_file(script), computation["script_sha256"]
            )

        issues = read_json(
            self.root / "audit" / "06_reports" / "ISSUE_LOG.json"
        )["issues"]
        self.assertEqual(1, len(issues))
        issue = issues[0]
        self.assertEqual("S1", issue["severity"])
        repair_search = issue["repair_search"]
        self.assertEqual("candidate_repair_exists", repair_search["conclusion"])
        outcomes = {row["outcome"] for row in repair_search["strategies"]}
        self.assertIn("failed", outcomes)
        self.assertIn("survives_local_inspection", outcomes)
        self.assertEqual(
            ["lem:growing-max", "thm:main"], issue["affected_results"]
        )

        calibration = read_json(
            self.root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        self.assertTrue(calibration["sessions"][-1]["passed"])
        self.assertEqual([], proofcheck.checker_calibration_errors(self.root))

        thm = read_json(
            self.root / "audit" / "04_local_checks" / "thm-main.ledger.json"
        )
        self.assertEqual("refuted", lem["review"]["statement_status"])
        self.assertEqual(
            "refuted", thm["review"]["statement_status"]
        )
        historical = read_json(self.root / "audit/04_local_checks/history/protocol-1.3/thm-main.ledger.json")
        self.assertEqual("not_established", historical["review"]["statement_status"])
        # The upgrade is supported by a witness for the theorem itself, not
        # merely by changing a downstream label after its prerequisite failed.
        theorem_failures = [move.get("failure", {}) for step in thm["steps"]
                            for move in (step.get("inference") or {}).get("moves", [])]
        witness = next(row for row in theorem_failures if row.get("kind") == "counterexample")
        self.assertEqual(thm["obligation"]["conclusions"][0]["claim"], witness["target"])
        self.assertIn("hat{theta}_n-theta_0", witness["evidence"])
        self.assertIn({"kind": "conclusion", "unit_id": "thm:main", "conclusion_id": "C001"},
                      issue["contract_refs"])
        report = self.report_path.read_text(encoding="utf-8")
        readable = html.unescape(re.sub(r"<[^>]+>", " ", report))
        self.assertIn("Finding technical records", readable)
        self.assertIn(issue["id"], readable)
        self.assertIn("Failed inference · paper.tex, line 16", readable)
        self.assertIn("Findings and repairs", readable)
        self.assertIn("scientific cost", readable.lower())
        self.assertIn("recheck", readable.lower())

        changes = issue["suggested_changes"]
        by_action = {change["action"]: change for change in changes}
        strengthen = by_action["strengthen_assumption"]
        self.assertEqual("unit_statement", strengthen["repair_scope"])
        self.assertEqual(
            "adds_regularity_or_moment", strengthen["assumption_cost"]
        )
        self.assertNotIn("claim_cost", strengthen)
        weaken = by_action["weaken_claim"]
        self.assertEqual("none", weaken["assumption_cost"])
        self.assertEqual("restricts_scope", weaken["claim_cost"])
        for change in changes:
            self.assertIn(change["proposal"], readable)
            self.assertIn(
                proofcheck.repair_cost_language(change),
                readable,
            )

    def test_shipped_audit_has_answer_first_summary_and_full_verification(
        self,
    ) -> None:
        report = self.report_path.read_text(encoding="utf-8")
        manifest = read_json(self.root / "AUDIT_MANIFEST.json")
        renderer = proofcheck.report_renderer()
        projection = renderer.build_report_projection(
            proofcheck.report_api(), self.root, final=True,
            finalized_at=manifest["report_release"]["finalized_at"],
            report_context=manifest.get("report_context", {}),
        )
        self.assertEqual([], renderer.validate_html(report, projection))
        self.assertEqual("FINAL", projection["release"]["status"])
        self.assertTrue(all(projection["summary"].values()))
        self.assertEqual(2, len(projection["results"]))
        self.assertIn(renderer.ASSURANCE, html.unescape(report))
        errors, summaries, _ = proofcheck.audit_ledgers(self.root, True)
        self.assertTrue(all("stale" in error for error in errors))
        checked = {
            summary["unit_id"]
            for summary in summaries
            if summary.get("independent_check", {}).get("required") is True
        }
        self.assertEqual(set(manifest["audit_scope"]["in_scope_units"]), checked)

    def test_initial_challenges_preserve_exact_fresh_inputs_and_reasons(self) -> None:
        records = list((self.root / "audit/05_adversarial").glob("initial-*.json"))
        self.assertGreaterEqual(len(records), 4)
        for unit_id, stem in reference_refresh.UNITS.items():
            ledger = read_json(self.root / "audit/04_local_checks" / f"{stem}.ledger.json")
            reference = ledger["independent_check"]["initial_response"]
            initial_path = self.root / reference["artifact"]
            self.assertEqual(reference["sha256"], proofcheck.sha256_file(initial_path))
            initial = read_json(initial_path)
            self.assertTrue(initial["response"]["conclusions"][0]["decisive_reason"])
            self.assertEqual(2, initial["response"]["response_schema_version"])
            conclusion = initial["response"]["conclusions"][0]
            self.assertEqual("refuted", conclusion["statement_status"])
            self.assertEqual("invalid", conclusion["argument_status"])
            self.assertEqual("invalid", initial["primary_snapshot"]["conclusions"][0]["argument_status"])
            for field in ("initial_response", "reconciliation_artifact"):
                prior = initial["superseded_review"][field]
                self.assertEqual(prior["sha256"], proofcheck.sha256_file(self.root / prior["artifact"]))
            self.assertNotIn("normalization_checks", initial["packet"]["obligation"])
            if unit_id == "thm:main":
                self.assertEqual("agreed", ledger["independent_check"]["status"])
                self.assertEqual([], ledger["independent_check"]["disagreements"])
                # The new reviewer assessed the whole argument and agreed.
                # Renewal must still retain the actual earlier disagreement.
                historical, seen, found_disagreement = initial, set(), False
                while (historical.get("superseded_review") or {}).get("initial_response"):
                    superseded = historical["superseded_review"]
                    prior = superseded["initial_response"]
                    self.assertNotIn(prior["artifact"], seen)
                    seen.add(prior["artifact"])
                    prior_path = self.root / prior["artifact"]
                    self.assertEqual(prior["sha256"], proofcheck.sha256_file(prior_path))
                    historical = read_json(prior_path)
                    if historical["response"]["conclusions"][0].get("argument_status") == "conditional":
                        self.assertEqual("invalid", historical["primary_snapshot"]["conclusions"][0]["argument_status"])
                        artifact = self.root / superseded["reconciliation_artifact"]["artifact"]
                        self.assertIn("full-argument convention", artifact.read_text(encoding="utf-8"))
                        found_disagreement = True
                self.assertTrue(found_disagreement, "The original assessment-scope disagreement was lost")
                # This review must see the actual prerequisite applicability,
                # not merely a digest or a primary verdict.
                self.assertIn("applicability", json.dumps(initial["packet"]["dependencies"]))

    def test_packet_preparation_refuses_stale_protocol_without_writes(self) -> None:
        before = proofcheck.audit_state_manifest(self.root)
        output = Path(self.temp.name) / "packets"
        with self.assertRaisesRegex(ValueError, "stale"):
            reference_refresh.prepare(self.root, output)
        self.assertEqual(before, proofcheck.audit_state_manifest(self.root))
        self.assertFalse(output.exists())
        with self.assertRaises(ValueError):
            reference_refresh.prepare(self.root, self.root / "packets")

    def test_publish_never_restamps_stale_primary_or_missing_initial_evidence(self) -> None:
        ledger_path = self.root / "audit/04_local_checks/lem-growing-max.ledger.json"
        original = ledger_path.read_bytes()
        for mutation in ("work_context_sha256", "initial_response"):
            ledger = json.loads(original)
            if mutation == "work_context_sha256":
                ledger[mutation] = "0" * 64
            else:
                ledger["independent_check"].pop(mutation)
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            before = proofcheck.audit_state_manifest(self.root)
            with self.assertRaisesRegex(ValueError, "needs actual review"):
                reference_refresh.refresh(self.root)
            self.assertEqual(before, proofcheck.audit_state_manifest(self.root))

    def test_publish_requires_explicit_historical_contract_opt_in(self) -> None:
        manifest = read_json(self.root / "AUDIT_MANIFEST.json")
        manifest["protocol"].pop("challenge_contract_version", None)
        with mock.patch.object(reference_refresh, "_manifest", return_value=manifest):
            with self.assertRaisesRegex(ValueError, "Historical challenge contract"):
                reference_refresh.refresh(self.root)

    def test_presentation_refresh_refuses_stale_evidence(self) -> None:
        paths = [path for branch in ("04_local_checks", "05_adversarial", "07_runtime")
                 for path in (self.root / "audit" / branch).rglob("*") if path.is_file()]
        before = {path: path.read_bytes() for path in paths}
        with self.assertRaisesRegex(ValueError, "needs actual review"):
            reference_refresh.refresh(self.root)
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_workbench_examples_carry_the_current_annotation_schema(self) -> None:
        receipt = proofcheck.current_calibration_receipt(self.root)["sha256"]
        for name in ("lem", "thm"):
            annotations = read_json(
                REFERENCE / "workbench" / f"{name}.annotations.json"
            )
            self.assertEqual(
                proofcheck.SEMANTIC_ANNOTATION_SCHEMA_VERSION,
                annotations["annotation_schema_version"],
            )
            self.assertEqual(
                receipt, annotations["calibration_receipt_sha256"]
            )


if __name__ == "__main__":
    unittest.main()
