from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import unittest
from unittest import mock

import test_compile_annotations as fixtures
import test_archive_renewal as archive_fixtures


proofcheck = fixtures.proofcheck


class StatementSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.CompileAnnotationsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def supplied_annotations(self, *, conditional: bool = False) -> dict:
        annotations = self.fixture.annotations()
        written = annotations["steps"][1]
        supplement = copy.deepcopy(written)
        written.update(status="gap", inputs=[], issue_ids=["I-001"])
        written["failure"] = {
            "kind": "missing_premise", "issue_id": "I-001",
            "evidence": "The written invocation omits the derivation establishing x equals x.",
        }
        supplement.update(key="supplement", literal="The same source line is the location of a separately supplied reflexivity derivation for x.")
        supplement["inputs"][0].pop("source_reference_id", None)
        supplement["inputs"][0].pop("source_reference_occurrence_id", None)
        extra = []
        if conditional:
            extra = ["x is positive"]
            supplement.update(status="conditionally_verified", side_conditions=[{
                "condition": "x is positive", "status": "open",
            }])
        annotations["steps"].append(supplement)
        annotations["conclusions"][0].update(
            statement_status="conditional" if conditional else "established",
            statement_support={"support_step": "supplement", "extra_conditions": extra,
                               "evidence": "The reviewer supplies the reflexivity derivation of x equals x; the written gap remains recorded."},
        )
        annotations["review"]["source_reference_dispositions"][0].update(
            disposition="unresolved", evidence="The original source invocation remains unresolved in the written argument for x.",
        )
        return annotations

    def compile_support(self, *, conditional: bool = False) -> dict:
        self.fixture.compile(self.supplied_annotations(conditional=conditional), self.fixture.output)
        return fixtures.read_json(self.fixture.output)

    def projection(self, ledger: dict, *, provisional: bool = True) -> dict:
        errors = []
        result = proofcheck.statement_support_projection(ledger, ledger["review"]["conclusion_results"][0], errors, provisional=provisional)
        self.assertEqual(errors, [])
        self.assertIsNotNone(result)
        return result

    def test_checked_supplement_keeps_written_gap_and_establishes_statement(self) -> None:
        ledger = self.compile_support()
        row = ledger["review"]["conclusion_results"][0]
        self.assertEqual(row["argument_status"], "gap")
        self.assertEqual(row["statement_status"], "established")
        self.assertEqual(ledger["review"]["unit_status"], "gap")
        self.assertNotEqual(row["support"], row["statement_support"]["support"])
        self.assertEqual(self.projection(ledger)["extra_conditions"], [])

    def test_promotion_without_supplement_still_fails(self) -> None:
        annotations = self.supplied_annotations()
        del annotations["conclusions"][0]["statement_support"]
        with self.assertRaisesRegex(ValueError, "statement_status is inconsistent"):
            self.fixture.compile(annotations, self.fixture.output)

    def test_undeclared_extra_conditions_fail(self) -> None:
        annotations = self.supplied_annotations(conditional=True)
        annotations["conclusions"][0]["statement_support"]["extra_conditions"] = []
        with self.assertRaisesRegex(ValueError, "extra_conditions"):
            self.fixture.compile(annotations, self.fixture.output)

    def test_extra_conditions_cannot_promote_unrestricted_statement(self) -> None:
        annotations = self.supplied_annotations(conditional=True)
        annotations["conclusions"][0]["statement_status"] = "established"
        with self.assertRaisesRegex(ValueError, "extra conditions cannot establish"):
            self.fixture.compile(annotations, self.fixture.output)

    def test_conditional_supplement_is_explicit(self) -> None:
        ledger = self.compile_support(conditional=True)
        self.assertEqual(ledger["review"]["conclusion_results"][0]["statement_status"], "conditional")
        self.assertEqual(self.projection(ledger)["extra_conditions"], ["x is positive"])

    def test_multistep_restriction_retains_exact_inherited_side_condition(self) -> None:
        annotations = self.supplied_annotations(conditional=True)
        first = annotations["steps"][-1]
        first.update(key="positive-domain", kind="inequality", claim="x is real under the positive restriction")
        final = copy.deepcopy(first)
        final.update(key="supplement", kind="conclusion", claim="x equals x", side_conditions=[],
                     inputs=[{"kind": "prior_step", "reference": "positive-domain", "role": "fact",
                              "evidence": "The preceding supplied move fixes real x under the positive restriction.",
                              "compatibility_check": "The same real x is used for reflexivity under the inherited restriction."}])
        annotations["steps"].append(final)
        self.fixture.compile(annotations, self.fixture.output)
        ledger = fixtures.read_json(self.fixture.output)
        self.assertEqual(self.projection(ledger)["extra_conditions"], ["x is positive"])

    def test_stale_target_digest_is_rejected(self) -> None:
        ledger = self.compile_support()
        row = ledger["review"]["conclusion_results"][0]
        row["statement_support"]["target_contract_sha256"] = "0" * 64
        errors = []
        proofcheck.statement_support_projection(ledger, row, errors)
        self.assertTrue(any("stale" in error for error in errors))

    def test_changed_support_evidence_changes_review_target(self) -> None:
        ledger = self.compile_support()
        before = self.projection(ledger)["sha256"]
        supplied = ledger["review"]["conclusion_results"][0]["statement_support"]["support"]
        step = next(row for row in ledger["steps"] if row["id"] == supplied["step_id"])
        step["inference"]["moves"][0]["justification"] += " This is changed evidence for x."
        self.assertNotEqual(before, self.projection(ledger)["sha256"])

    def test_pending_support_is_provisional_only(self) -> None:
        ledger = self.compile_support()
        row = copy.deepcopy(ledger["review"]["conclusion_results"][0])
        row["statement_support"] = self.projection(ledger, provisional=False)
        self.assertEqual(proofcheck.internal_dependency_status({"conclusion_results": [row]}, "C001"), "unchecked")
        row["statement_support"]["provisional"] = True
        self.assertEqual(proofcheck.internal_dependency_status({"conclusion_results": [row]}, "C001"), "verified")

    def test_reader_description_is_bounded(self) -> None:
        ledger = self.compile_support()
        ledger["obligation"]["conclusions"][0]["reader_description"] = "x" * 121
        errors = []
        proofcheck.validate_conclusion_records(ledger["obligation"], self.fixture.output, True, errors)
        self.assertTrue(any("reader_description" in error for error in errors))

    def preserve_reviews(self, *, conditional: bool = False) -> tuple[dict, dict]:
        ledger = self.compile_support(conditional=conditional)
        packet = proofcheck.build_context_packet(self.fixture.audit, "lem:compact", "challenge")
        span_pointer, span = next(iter(proofcheck.challenge_source_spans(packet).items()))
        response = {
            "response_schema_version": 2, "unit_id": "lem:compact", "independence_level": "fresh_context_same_model",
            "challenger_verdict": "gap", "conclusions": [{
                "conclusion_id": "C001", "verdict": "gap", "argument_status": "gap",
                "statement_status": "conditional" if conditional else "established",
                "decisive_reason": "The written derivation omits its justification; independent reflexivity establishes x equals x.",
                "source_refs": [{"packet_pointer": span_pointer, "start_line": span["start_line"], "end_line": span["end_line"]}],
            }], "issue_assessments": [],
        }
        packet_path = self.fixture.base / "blind.json"
        response_path = self.fixture.base / "blind-response.json"
        fixtures.write_json(packet_path, packet)
        fixtures.write_json(response_path, response)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_record_challenge(argparse.Namespace(root=self.fixture.audit, unit_id="lem:compact", packet=packet_path, response=response_path))
        supplied_packet = proofcheck.build_statement_support_packet(self.fixture.audit, "lem:compact")
        supplied_response = {
            "response_schema_version": 1, "unit_id": "lem:compact", "packet_sha256": proofcheck.canonical_sha256(supplied_packet),
            "independence_level": "fresh_context_same_model", "assessments": [{
                "conclusion_id": "C001", "statement_support_sha256": supplied_packet["statement_supports"][0]["statement_support_sha256"],
                "assessment": "accepted", "reason": "The separate derivation applies reflexivity to the arbitrary real x and establishes x equals x under exactly the recorded conditions.",
            }],
        }
        support_packet_path = self.fixture.base / "support.json"
        support_response_path = self.fixture.base / "support-response.json"
        fixtures.write_json(support_packet_path, supplied_packet)
        fixtures.write_json(support_response_path, supplied_response)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_record_statement_support(argparse.Namespace(root=self.fixture.audit, unit_id="lem:compact", packet=support_packet_path, response=support_response_path))
        return fixtures.read_json(self.fixture.output), supplied_packet

    def test_real_packet_and_immutable_supplement_response(self) -> None:
        ledger, packet = self.preserve_reviews()
        acceptance, errors = proofcheck.load_statement_support_review(self.fixture.audit, ledger)
        self.assertEqual(errors, [])
        self.assertEqual(acceptance, {"C001": "accepted"})
        self.assertNotIn("argument_status", json.dumps(packet))
        self.assertNotIn("statement_status", json.dumps(packet))
        proposal = packet["statement_supports"][0]
        step = next(row for row in ledger["steps"] if row["id"] == proposal["steps"][0]["step_id"])
        source_unit = next(row for row in ledger["source_units"] if row["id"] == step["source_unit_id"])
        self.assertEqual(proposal["steps"][0]["source_span"], proofcheck.source_unit_location(ledger, source_unit))
        self.assertEqual(proposal["steps"][0]["moves"][0]["premise_ids"], step["inference"]["moves"][0]["premise_ids"])
        self.assertEqual(proposal["steps"][0]["moves"][0]["prior_move_ids"], step["inference"]["moves"][0]["prior_move_ids"])
        self.assertNotIn("inputs", proposal["steps"][0]["moves"][0])
        self.assertNotIn("lines", proposal["steps"][0])

    def test_tampered_review_bytes_cannot_supply_acceptance(self) -> None:
        ledger, _ = self.preserve_reviews()
        path = self.fixture.audit / ledger["independent_check"]["statement_support_review"]["artifact"]
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        acceptance, errors = proofcheck.load_statement_support_review(self.fixture.audit, ledger)
        self.assertEqual(acceptance, {})
        self.assertTrue(any("altered" in error for error in errors))

    def test_changed_proof_invalidates_preserved_acceptance(self) -> None:
        ledger, _ = self.preserve_reviews()
        ledger["review"]["conclusion_results"][0]["statement_support"]["evidence"] += " The proposal is revised."
        acceptance, errors = proofcheck.load_statement_support_review(self.fixture.audit, ledger)
        self.assertEqual(acceptance, {})
        self.assertTrue(any("stale" in error for error in errors))

    def test_restricted_use_requires_complete_current_condition_evidence(self) -> None:
        ledger, _ = self.preserve_reviews(conditional=True)
        errors, summary = proofcheck.check_ledger_data(self.fixture.output, True)
        self.assertEqual(errors, [])
        support = summary["conclusion_results"][0]["statement_support"]
        span = ledger["obligation"]["statement_spans"][0]
        use = {"use_id": "D001", "statement_support_sha256": support["sha256"], "statement_support_conditions": []}
        errors = []
        proofcheck.statement_support_use_status(summary, "C001", use, self.fixture.audit, errors)
        self.assertTrue(any("cover exactly" in error for error in errors))
        use["statement_support_conditions"] = [{"condition": "x is positive", "status": "satisfied",
            "evidence": "The dependent argument explicitly restricts its real x to a positive value.",
            "evidence_spans": [{**span, "file": str(self.fixture.paper), "role": "dependent condition evidence"}]}]
        errors = []
        status, _ = proofcheck.statement_support_use_status(summary, "C001", use, self.fixture.audit, errors, dependent_summary=summary)
        self.assertEqual(errors, [])
        self.assertEqual(status, "verified")
        use["statement_support_conditions"][0]["evidence_spans"][0]["sha256"] = "0" * 64
        errors = []
        proofcheck.statement_support_use_status(summary, "C001", use, self.fixture.audit, errors, dependent_summary=summary)
        self.assertTrue(errors)

    def test_no_support_packet_before_initial_blind_response(self) -> None:
        self.compile_support()
        with self.assertRaisesRegex(ValueError, "initial blind"):
            proofcheck.build_statement_support_packet(self.fixture.audit, "lem:compact")

    def test_current_supplement_response_cannot_be_overwritten(self) -> None:
        ledger, _ = self.preserve_reviews()
        reference = ledger["independent_check"]["statement_support_review"]
        artifact = self.fixture.audit / reference["artifact"]
        before = artifact.read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            proofcheck.cmd_record_statement_support(argparse.Namespace(
                root=self.fixture.audit, unit_id="lem:compact", packet=self.fixture.base / "support.json",
                response=self.fixture.base / "support-response.json",
            ))
        self.assertEqual(before, artifact.read_bytes())

    def test_stale_selection_cannot_supply_downstream_verification(self) -> None:
        ledger, _ = self.preserve_reviews()
        _, summary = proofcheck.check_ledger_data(self.fixture.output, True)
        errors = []
        status, _ = proofcheck.statement_support_use_status(summary, "C001", {"use_id": "D001", "statement_support_sha256": "0" * 64}, self.fixture.audit, errors)
        self.assertEqual(status, "unchecked")
        self.assertTrue(errors)

    def test_archive_preserves_actual_acceptance_and_rejects_changed_bytes(self) -> None:
        ledger, _ = self.preserve_reviews()
        refs = [ledger["independent_check"][name] for name in ("initial_response", "statement_support_review")]
        sealed = [proofcheck.sealed_file_record(self.fixture.audit / ref["artifact"], ref["artifact"]) for ref in refs]
        hashes = {record["file"]: record["sha256"] for record in sealed}
        errors = []
        summaries = proofcheck.archived_statement_support_summaries({"lem:compact": ledger}, sealed, hashes, errors)
        self.assertEqual(errors, [])
        self.assertEqual(proofcheck.internal_dependency_status(summaries["lem:compact"], "C001"), "verified")
        bad_hashes = {**hashes, refs[1]["artifact"]: "0" * 64}
        errors = []
        proofcheck.archived_statement_support_summaries({"lem:compact": ledger}, sealed, bad_hashes, errors)
        self.assertTrue(any("prior finalization" in error for error in errors))

    def test_unapplied_proposal_needs_accepted_exact_edit_review(self) -> None:
        ledger, _ = self.preserve_reviews()
        support = self.projection(ledger)
        change = {"verification_status": "verified_sufficient", "proposal": "Supply the reflexivity derivation.",
                  "statement_support_ref": {"unit_id": "lem:compact", "conclusion_id": "C001", "sha256": support["sha256"]}}
        issue = {"id": "I-001", "affected_result": "lem:compact", "status": "open"}
        errors = proofcheck.checked_suggested_change_errors(issue, change, 1, self.fixture.audit, {"lem:compact": ledger})
        self.assertTrue(any("does not verify this exact proposed edit" in error for error in errors))
        self.assertEqual(issue["status"], "open")

    def test_downstream_selection_does_not_create_context_digest_cycle(self) -> None:
        first = {"downstream_internal_uses": [{"use_id": "D001", "needed_form": "x equals x", "statement_support_sha256": "a" * 64, "statement_support_conditions": []}]}
        second = copy.deepcopy(first)
        second["downstream_internal_uses"][0]["statement_support_sha256"] = "b" * 64
        self.assertEqual(proofcheck.packet_semantic_dependencies(first), proofcheck.packet_semantic_dependencies(second))


class StatementSupportDeliveryTests(unittest.TestCase):
    def test_finalize_archive_and_refinalize_preserves_open_written_defect(self) -> None:
        fixture = archive_fixtures.ArchiveRenewalTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        pc = archive_fixtures.pc
        ledger_path, issue, _ = fixture.fixture.make_ledger_move_defect_audit()
        root = fixture.root
        manifest_path = root / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(manifest_path)
        manifest["protocol"]["challenge_contract_version"] = 3
        fixtures.write_json(manifest_path, manifest)
        ledger = fixtures.read_json(ledger_path)
        original = next(row for row in ledger["steps"] if row["id"] == "S003")
        supplied = copy.deepcopy(original)
        supplied.update(id="S003.1", status="verified", issue_ids=[])
        supplied["inference"]["moves"][0].pop("failure")
        supplied["checks"]["literal"] = "At this source invocation the reviewer separately supplies reflexivity for the stated real x."
        ledger["steps"].insert(ledger["steps"].index(original) + 1, supplied)
        result = ledger["review"]["conclusion_results"][0]
        result["statement_status"] = "established"
        result["statement_support"] = {
            "schema_version": 1, "support": {"step_id": "S003.1", "move_id": "M001"},
            "target_contract_sha256": pc.canonical_sha256(pc.conclusion_contract_payload(ledger["obligation"], "C001")),
            "extra_conditions": [], "evidence": "The supplied reflexivity derivation establishes x equals x while the recorded written invalid-rule defect stays open.",
        }
        ledger["review"]["statement_status"] = "established"
        ledger["independent_check"].update(required=False, status="not_required")
        fixtures.write_json(ledger_path, ledger)
        work = pc.build_context_packet(root, "lem:main", "primary")
        ledger["work_context_sha256"] = work["work_context_sha256"]
        fixtures.write_json(ledger_path, ledger)
        support_errors = []
        support = pc.statement_support_projection(ledger, result, support_errors)
        self.assertEqual(support_errors, [])
        issue_path = root / "audit/06_reports/ISSUE_LOG.json"
        issue_log = fixtures.read_json(issue_path)
        issue_log["issues"][0]["suggested_changes"][0]["statement_support_ref"] = {
            "unit_id": "lem:main", "conclusion_id": "C001", "sha256": support["sha256"],
        }
        fixtures.write_json(issue_path, issue_log)
        self.assertEqual(pc.build_context_packet(root, "lem:main", "primary")["work_context_sha256"], work["work_context_sha256"])
        packet = pc.build_context_packet(root, "lem:main", "challenge")
        response = {
            "response_schema_version": 2, "unit_id": "lem:main", "independence_level": "fresh_context_same_model",
            "challenger_verdict": "incorrect", "conclusions": [{"conclusion_id": "C001", "verdict": "incorrect",
                "argument_status": "invalid", "statement_status": "established",
                "decisive_reason": "The written rule fails as recorded; reflexivity independently establishes x equals x for the stated real domain.",
                "source_refs": [{"packet_pointer": "/source/proof", "start_line": 6, "end_line": 6}]}],
            "issue_assessments": [],
        }
        packet_path, response_path = fixture.fixture.base / "initial.json", fixture.fixture.base / "response.json"
        fixtures.write_json(packet_path, packet)
        fixtures.write_json(response_path, response)
        fixture.run_command(pc.cmd_record_challenge, unit_id="lem:main", packet=packet_path, response=response_path)
        support_packet = pc.build_statement_support_packet(root, "lem:main")
        support_response = {"response_schema_version": 1, "unit_id": "lem:main", "packet_sha256": pc.canonical_sha256(support_packet),
            "independence_level": "fresh_context_same_model", "assessments": [{"conclusion_id": "C001",
                "statement_support_sha256": support_packet["statement_supports"][0]["statement_support_sha256"],
                "assessment": "accepted", "reason": "The proposed reconstruction uses the exact universal real x premise and applies reflexivity to establish the unchanged target x equals x."}]}
        support_response["change_assessments"] = [{
            "issue_id": row["issue_id"], "change_index": row["change_index"], "sha256": row["sha256"],
            "assessment": "accepted", "reason": "The exact local edit replaces the invalid inference with the supplied reflexivity derivation under the same real-number premise.",
        } for row in support_packet["suggested_changes"]]
        fixtures.write_json(packet_path, support_packet)
        fixtures.write_json(response_path, support_response)
        fixture.run_command(pc.cmd_record_statement_support, unit_id="lem:main", packet=packet_path, response=response_path)
        issue_log["issues"][0]["suggested_changes"][0]["verification_status"] = "verified_sufficient"
        fixtures.write_json(issue_path, issue_log)
        ledger = fixtures.read_json(ledger_path)
        ledger["independent_check"].update(disagreements=[], resolution="", issue_assessments=[], reconciled_verdict="incorrect")
        fixtures.write_json(ledger_path, ledger)
        fixture.run_command(pc.cmd_bind_challenge, unit_id="lem:main")
        fixture.run_command(pc.cmd_migrate_report, markdown=True)
        fixture.run_command(pc.cmd_finalize)
        self.assertTrue(pc.check_finalization_freshness(root)["usable_finalization"])
        fixture.run_command(pc.cmd_archive_issue, issue_id="I-001")
        fixture.run_command(pc.cmd_finalize)
        issue = fixtures.read_json(root / "audit/06_reports/ISSUE_LOG.json")["issues"][0]
        archive = fixtures.read_json(root / issue["historical_origin"]["artifact"])
        self.assertEqual(len(archive["prior_artifacts"]["statement_support_reviews"]), 2)
        self.assertEqual(issue["status"], "open")
        self.assertEqual(issue["suggested_changes"][0]["verification_status"], "verified_sufficient")
        self.assertTrue(pc.check_finalization_freshness(root)["usable_finalization"])


if __name__ == "__main__":
    unittest.main()
