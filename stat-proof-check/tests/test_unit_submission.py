from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import test_compile_annotations as fixture_support

proofcheck = fixture_support.proofcheck
read_json = fixture_support.read_json
write_json = fixture_support.write_json


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck_authoring.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_authoring_tests", SCRIPT)
authoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(authoring)


class UnitSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_support.CompileAnnotationsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.draft = self.fixture.base / "reviewed.annotations.json"
        self.registry = self.fixture.audit / "audit/03_dependencies/DEPENDENCY_REGISTRY.json"

    def submit(self, annotations=None):
        if annotations is not None:
            write_json(self.draft, annotations)
        return authoring.submit_unit(proofcheck, ledger_path=self.fixture.ledger,
                                     annotations_path=self.draft, packet_path=self.fixture.packet)

    def test_publishes_same_canonical_ledger_as_compiler_and_repeats_without_writes(self):
        annotations = self.fixture.annotations()
        expected = proofcheck.compile_annotation_data(read_json(self.fixture.ledger), annotations,
                                                      self.fixture.ledger, read_json(self.fixture.packet))
        write_json(self.draft, annotations)
        parsed = proofcheck.build_parser().parse_args([
            "submit-unit", str(self.fixture.ledger), "--annotations", str(self.draft),
            "--packet", str(self.fixture.packet)])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(0, parsed.func(parsed))
        result = json.loads(stdout.getvalue())
        self.assertEqual("submitted", result["status"])
        self.assertEqual(expected, read_json(self.fixture.output))
        before = {p: p.read_bytes() for p in self.fixture.audit.rglob("*") if p.is_file()}
        self.assertEqual("unchanged", self.submit()["status"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_external_binding_follows_compiler_step_map_without_editing_draft(self):
        annotations = self.fixture.dependency_annotations()
        registry = read_json(self.registry)
        registry["external_results"][0]["uses"][0]["step_ids"] = ["S999"]
        write_json(self.registry, registry)
        # Step bindings are operational; the original reviewed packet remains usable.
        write_json(self.draft, annotations)
        before = self.draft.read_bytes()
        self.assertEqual("submitted", self.submit()["status"])
        after = read_json(self.registry)
        self.assertEqual(["S003.1"], after["external_results"][0]["uses"][0]["step_ids"])
        registry["external_results"][0]["uses"][0]["step_ids"] = ["S003.1"]
        self.assertEqual(registry, after)
        self.assertEqual(before, self.draft.read_bytes())

    def test_fresh_unchecked_use_requires_explicit_matching_reviewed_status(self):
        annotations = self.fixture.dependency_annotations("unchecked")
        registry = read_json(self.registry)
        registry["external_results"][0]["uses"][0]["step_ids"] = []
        write_json(self.registry, registry)
        self.fixture.regenerate_packet()
        annotations["context_binding_sha256"] = read_json(self.fixture.packet)["context_binding_sha256"]
        annotations["dependencies"][0]["status"] = "verified"
        self.assertEqual("submitted", self.submit(annotations)["status"])
        use = read_json(self.registry)["external_results"][0]["uses"][0]
        self.assertEqual("verified", use["status"])
        self.assertEqual(["S003.1"], use["step_ids"])
        self.assertEqual("unchanged", self.submit()["status"])

    def test_missing_judgment_is_not_promoted(self):
        annotations = self.fixture.annotations()
        annotations["steps"][1]["risks"]["domain"] = None
        before = self.registry.read_bytes()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.submit(annotations)
        self.assertFalse(self.fixture.output.exists())
        self.assertEqual(before, self.registry.read_bytes())

    def test_failed_internal_use_from_reference_keeps_its_mathematical_status(self):
        root = SCRIPT.parents[2] / "tests/fixtures/reference-audit/proofcheck-audit"
        skeleton_path = root / "audit/04_local_checks/thm-main.skeleton.json"
        skeleton = read_json(skeleton_path)
        annotations = read_json(SCRIPT.parents[2] / "tests/fixtures/reference-audit/workbench/thm.annotations.json")
        registry = read_json(root / "audit/03_dependencies/DEPENDENCY_REGISTRY.json")
        projection = proofcheck.packet_dependency_projection(registry, root, "thm:main", "primary", skeleton)
        _, bindings = authoring._step_bindings(proofcheck, skeleton, annotations)
        registry["internal_uses"][0]["step_ids"] = ["S999"]
        registry["internal_uses"][0]["status"] = "unchecked"
        projection["direct_internal_uses"][0]["step_ids"] = []
        projection["direct_internal_uses"][0]["status"] = "unchecked"
        candidate = authoring._candidate_registry(proofcheck, root, registry, {"dependencies": projection}, annotations, bindings)
        self.assertEqual("incorrect", candidate["internal_uses"][0]["status"])
        self.assertEqual(["S003"], candidate["internal_uses"][0]["step_ids"])
        registry["internal_uses"][0].update(status="incorrect", step_ids=["S003"])
        self.assertEqual(registry, candidate)

    def test_unchecked_status_is_not_silently_filled(self):
        annotations = self.fixture.dependency_annotations("unchecked")
        with self.assertRaisesRegex(ValueError, "authored status"):
            self.submit(annotations)
        self.assertFalse(self.fixture.output.exists())

    def test_changed_compatibility_claim_is_not_a_mechanical_refresh(self):
        annotations = self.fixture.dependency_annotations()
        annotations["dependencies"][0]["needed_form"] = "A stronger conclusion on a different domain."
        with self.assertRaisesRegex(ValueError, "reviewed dependency fields changed"):
            self.submit(annotations)
        self.assertFalse(self.fixture.output.exists())

    def test_stale_packet_and_changed_calibration_fail_before_publishing(self):
        annotations = self.fixture.dependency_annotations()
        registry = read_json(self.registry)
        registry["external_results"][0]["uses"][0]["compatibility_check"] += " Changed domain."
        write_json(self.registry, registry)
        with self.assertRaisesRegex(ValueError, "semantic context is stale"):
            self.submit(annotations)
        self.assertFalse(self.fixture.output.exists())
        self.fixture.regenerate_packet()
        annotations = self.fixture.annotations()
        annotations["calibration_receipt_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "calibration"):
            self.submit(annotations)

    def test_existing_changed_evidence_is_never_overwritten(self):
        self.submit(self.fixture.annotations())
        candidate = read_json(self.fixture.output)
        candidate["review"]["reviewer_notes"].append("Subsequent authored evidence.")
        write_json(self.fixture.output, candidate)
        before = self.fixture.output.read_bytes()
        with self.assertRaisesRegex(FileExistsError, "explicit audit renewal"):
            self.submit()
        self.assertEqual(before, self.fixture.output.read_bytes())

    def test_retry_after_independent_review_preserves_the_attached_challenge(self):
        self.submit(self.fixture.annotations())
        packet_path = self.fixture.base / "challenge-packet.json"
        response_path = self.fixture.base / "initial-response.json"
        packet = proofcheck.build_context_packet(self.fixture.audit, "lem:compact", "challenge")
        write_json(packet_path, packet)
        conclusion = {"conclusion_id": "C001", "verdict": "verified", "argument_status": "valid",
                      "statement_status": "established", "decisive_reason": "Reflexivity on proof line 5 gives x=x for the arbitrary real x.",
                      "source_refs": [{"packet_pointer": "/source/proof", "start_line": 5, "end_line": 5}]}
        response = {"response_schema_version": 2, "unit_id": "lem:compact",
                    "independence_level": "fresh_context_same_model", "challenger_verdict": "verified",
                    "conclusions": [conclusion], "issue_assessments": []}
        write_json(response_path, response)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_record_challenge(argparse.Namespace(root=self.fixture.audit,
                unit_id="lem:compact", packet=packet_path, response=response_path))
        review_path = self.fixture.base / "reconciliation.json"
        review = {"reconciliation_schema_version": 1, "unit_id": "lem:compact", "status": "agreed",
                  "reconciled_verdict": "verified", "conclusions": [conclusion],
                  "disagreements": [], "resolution": "", "issue_assessments": []}
        write_json(review_path, review)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_submit_reconciliation(argparse.Namespace(root=self.fixture.audit, review=review_path))
        check = read_json(self.fixture.output)["independent_check"]
        self.assertEqual("agreed", check["status"])
        self.assertEqual([], proofcheck.challenge_semantic_freshness_errors(self.fixture.audit, "lem:compact", check, []))
        before = {path: path.read_bytes() for path in self.fixture.audit.rglob("*") if path.is_file()}
        self.assertEqual("unchanged", self.submit()["status"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_archived_primary_allows_explicit_renewal_and_preserves_submission_receipt(self):
        self.submit(self.fixture.annotations())
        receipt_path = next((self.fixture.audit / "audit/07_runtime").glob("SUBMISSION_*.json"))
        receipt_bytes = receipt_path.read_bytes()
        history = self.fixture.output.parent / "history/renewal-001"
        history.mkdir(parents=True)
        old_ledger = history / self.fixture.output.name
        self.fixture.output.rename(old_ledger)
        old_bytes = old_ledger.read_bytes()
        self.fixture.regenerate_packet()
        annotations = self.fixture.annotations()
        annotations["review"]["reviewer_notes"].append("The exact reflexivity conclusion was explicitly reviewed again.")
        self.assertEqual("submitted", self.submit(annotations)["status"])
        archived_receipts = list((receipt_path.parent / "history/submissions").glob("*.json"))
        self.assertEqual(1, len(archived_receipts))
        self.assertEqual(receipt_bytes, archived_receipts[0].read_bytes())
        self.assertEqual(old_bytes, old_ledger.read_bytes())
        self.assertEqual("unchanged", self.submit()["status"])

    def test_missing_prior_evidence_does_not_become_silent_renewal(self):
        self.submit(self.fixture.annotations())
        self.fixture.output.unlink()
        with self.assertRaisesRegex(ValueError, "Prior submitted primary evidence is missing"):
            self.submit()
        self.assertFalse(self.fixture.output.exists())

    def test_concurrent_registry_change_is_not_lost(self):
        original = proofcheck.compile_annotation_data
        def concurrent(*args, **kwargs):
            result = original(*args, **kwargs)
            registry = read_json(self.registry)
            registry["review"]["evidence"].append("Another coordinator added a review note.")
            write_json(self.registry, registry)
            return result
        with mock.patch.object(proofcheck, "compile_annotation_data", side_effect=concurrent):
            with self.assertRaisesRegex(ValueError, "changed during submission"):
                self.submit(self.fixture.annotations())
        self.assertFalse(self.fixture.output.exists())
        self.assertIn("Another coordinator", self.registry.read_text(encoding="utf-8"))

    def test_concurrent_source_change_prevents_publication(self):
        original = proofcheck.check_ledger_data
        altered = False
        def concurrent(path, *args, **kwargs):
            nonlocal altered
            result = original(path, *args, **kwargs)
            if Path(path).name.startswith(".") and not altered:
                altered = True
                self.fixture.paper.write_text(self.fixture.paper.read_text(encoding="utf-8") + "% changed\n", encoding="utf-8")
            return result
        with mock.patch.object(proofcheck, "check_ledger_data", side_effect=concurrent):
            with self.assertRaisesRegex(ValueError, "changed during submission"):
                self.submit(self.fixture.annotations())
        self.assertTrue(altered)
        self.assertFalse(self.fixture.output.exists())

    def test_interrupted_publication_restores_registry_and_removes_new_ledger(self):
        annotations = self.fixture.dependency_annotations()
        registry = read_json(self.registry)
        registry["external_results"][0]["uses"][0]["step_ids"] = ["S999"]
        write_json(self.registry, registry)
        before = self.registry.read_bytes()
        original = proofcheck.publish_no_overwrite
        def fail_receipt(candidate, destination, description):
            if destination.name.startswith("SUBMISSION_"):
                raise OSError("Injected interrupted publication")
            return original(candidate, destination, description)
        with mock.patch.object(proofcheck, "publish_no_overwrite", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "Injected interrupted"):
                self.submit(annotations)
        self.assertEqual(before, self.registry.read_bytes())
        self.assertFalse(self.fixture.output.exists())
        self.assertFalse(proofcheck.migration_update_lock_path(self.fixture.audit).exists())

    def test_annotation_check_and_compile_report_same_exact_binding_failure(self):
        annotations = self.fixture.dependency_annotations()
        registry = read_json(self.registry)
        registry["external_results"][0]["uses"][0]["step_ids"] = ["S999"]
        write_json(self.registry, registry)
        self.fixture.regenerate_packet()
        write_json(self.draft, annotations)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = proofcheck.cmd_annotation_check(argparse.Namespace(
                ledger=self.fixture.ledger, annotations=self.draft, packet=self.fixture.packet, json=True))
        result = json.loads(stdout.getvalue())
        self.assertNotEqual(0, code)
        self.assertFalse(result["compile_ready"])
        self.assertTrue(any(row["pointer"] == "/steps/2/inputs/1/reference" and
                            "D001" in row["message"] and "conclusion" in row["message"]
                            for row in result["diagnostics"]))
        with self.assertRaisesRegex(ValueError, "step_ids disagrees"):
            proofcheck.cmd_compile_annotations(argparse.Namespace(
                ledger=self.fixture.ledger, annotations=self.draft, packet=self.fixture.packet,
                output=self.fixture.output))

    def test_source_lookup_returns_exact_text_reference_and_compiler_step(self):
        write_json(self.draft, self.fixture.annotations())
        result = authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger,
                                         annotations_path=self.draft, step_key="conclusion")
        self.assertEqual("S003", result["step_id"])
        self.assertEqual([5, 5], result["coverage_positions"])
        self.assertIn("reflexivity", result["lines"][0]["text"])
        self.assertEqual(5, result["lines"][0]["source"]["start_line"])
        reference = authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger,
                                            packet_path=self.fixture.packet, reference="lem:compact")
        self.assertEqual(1, len(reference["occurrences"]))
        statement = authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger, part="statement")
        self.assertIn("For every real", statement["passages"][0]["text"])

    def test_source_lookup_rejects_proof_drift_and_invalid_selectors(self):
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger, lines=[5, 5], step_key="conclusion")
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger, lines=[5, 5], reference="lem:compact")
        with self.assertRaisesRegex(ValueError, "positive inclusive"):
            authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger, lines=[5, 4])
        self.fixture.paper.write_text(self.fixture.paper.read_text(encoding="utf-8").replace(
            "reflexivity gives", "a different premise gives"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Source drift"):
            authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger, lines=[5, 5])

    def test_source_lookup_works_before_mathematical_normalization(self):
        skeleton = read_json(self.fixture.ledger)
        skeleton["obligation"]["quantified_variables"] = []
        skeleton["obligation"]["normalization_checks"] = []
        write_json(self.fixture.ledger, skeleton)
        result = authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger, lines=[5, 5])
        self.assertIn("reflexivity", result["lines"][0]["text"])
        skeleton["source_lines"][0] = []
        write_json(self.fixture.ledger, skeleton)
        with self.assertRaisesRegex(ValueError, "Source drift"):
            authoring.source_lookup(proofcheck, ledger_path=self.fixture.ledger, lines=[5, 5])


if __name__ == "__main__":
    unittest.main()
