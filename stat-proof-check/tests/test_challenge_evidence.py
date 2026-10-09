from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import unittest
from unittest import mock
from pathlib import Path


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TESTS = Path(__file__).resolve().parent
workflow = load_module("challenge_workflow_fixture", TESTS / "test_workflow_efficiency.py")
proofcheck = workflow.proofcheck
read_json = workflow.read_json
write_json = workflow.write_json


class InitialChallengeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = workflow.WorkflowEfficiencyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.audit
        self.base = self.fixture.base
        manifest = read_json(self.root / "AUDIT_MANIFEST.json")
        manifest["protocol"]["challenge_contract_version"] = 2
        write_json(self.root / "AUDIT_MANIFEST.json", manifest)
        with contextlib.redirect_stdout(io.StringIO()):
            self.ledger_path = self.fixture.extract_ledger()
        self.packet = proofcheck.build_context_packet(self.root, "lem:a", "challenge")
        self.packet_path = self.base / "consumed-packet.json"
        self.response_path = self.base / "initial-response.json"
        write_json(self.packet_path, self.packet)

    def response(self, verdict: str = "verified") -> dict:
        return {
            "response_schema_version": 1,
            "unit_id": "lem:a",
            "independence_level": "fresh_context_same_model",
            "challenger_verdict": verdict,
            "conclusions": [{
                "conclusion_id": "C001",
                "verdict": verdict,
                "decisive_reason": "For the arbitrary real x, reflexivity on proof line 5 gives x=x without another assumption.",
                "source_refs": [{"packet_pointer": "/source/proof", "start_line": 5, "end_line": 5}],
            }],
            "issue_assessments": [],
        }

    def record(self, response: dict | None = None) -> tuple[dict, dict]:
        write_json(self.response_path, response or self.response())
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_record_challenge(argparse.Namespace(
                root=self.root, unit_id="lem:a", packet=self.packet_path, response=self.response_path
            ))
        record, reference, errors = proofcheck.load_initial_challenge(self.root, "lem:a", self.packet)
        self.assertEqual([], errors)
        return record, reference

    def prepare_reconciliation(self, *, initial_verdict: str = "verified") -> None:
        ledger = read_json(self.ledger_path)
        check = ledger["independent_check"]
        check.update({
            "independence_level": "fresh_context_same_model",
            "challenger_verdict": initial_verdict,
            "reconciled_verdict": "verified",
            "artifact": "audit/05_adversarial/lem-a-challenge.md",
            "disagreements": [],
            "resolution": "",
            "issue_assessments": [],
        })
        if initial_verdict != "verified":
            check["disagreements"] = ["The initial review treated reflexivity as needing an external theorem."]
            check["resolution"] = "Reflexivity directly proves x=x for every real x, so the written step is valid."
        write_json(self.ledger_path, ledger)
        (self.root / check["artifact"]).write_text(
            "# Independent reconciliation\n\nReflexivity proves x=x for the arbitrary real x on proof line 5.\n",
            encoding="utf-8",
        )

    def bind(self) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_bind_challenge(argparse.Namespace(root=self.root, unit_id="lem:a"))
        return read_json(self.ledger_path)["independent_check"]

    def test_challenge_contract_extension_preserves_exact_core_identity(self) -> None:
        protocol = dict(proofcheck.protocol_identity(), challenge_contract_version=2)
        self.assertTrue(proofcheck.protocol_matches_current(protocol))
        protocol["validator_sha256"] = "0" * 64
        self.assertFalse(proofcheck.protocol_matches_current(protocol))
        protocol = dict(proofcheck.protocol_identity(), challenge_contract_version=True)
        self.assertFalse(proofcheck.protocol_matches_current(protocol))

    def test_blinding_removes_primary_normalization_but_retains_source(self) -> None:
        self.assertNotIn("normalization_checks", self.packet["obligation"])
        self.assertNotIn("normalization", self.packet["obligation"]["conclusions"][0])
        self.assertEqual("For every real x.", self.packet["obligation"]["quantifier_scope"])
        self.assertTrue(self.packet["source"]["statement"]["lines"])
        primary = proofcheck.build_context_packet(self.root, "lem:a", "primary")
        self.assertTrue(primary["obligation"]["normalization_checks"])

    def test_preserves_exact_packet_and_response_without_overwrite(self) -> None:
        record, reference = self.record()
        self.assertEqual(self.packet, record["packet"])
        self.assertEqual(proofcheck.canonical_sha256(self.packet), record["packet_sha256"])
        path = self.root / reference["artifact"]
        before = path.read_bytes()
        replacement = self.response()
        replacement["conclusions"][0]["decisive_reason"] = "A replacement account of the equality proof must not overwrite the first response."
        with self.assertRaises(FileExistsError):
            self.record(replacement)
        self.assertEqual(before, path.read_bytes())

    def test_generic_assertion_cannot_replace_conclusion_and_source_records(self) -> None:
        response = self.response()
        response["conclusions"] = []
        response["justification"] = "Every inferential step was independently checked."
        self.assertTrue(proofcheck.validate_initial_challenge_response(response, self.packet))
        for reference in ([], [{"packet_pointer": "/obligation", "start_line": 5, "end_line": 5}],
                          [{"packet_pointer": "/source/proof", "start_line": 400, "end_line": 400}]):
            with self.subTest(reference=reference):
                response = self.response()
                response["conclusions"][0]["source_refs"] = reference
                self.assertTrue(proofcheck.validate_initial_challenge_response(response, self.packet))

    def test_new_contract_cannot_bind_without_preserved_initial_response(self) -> None:
        self.prepare_reconciliation()
        with self.assertRaisesRegex(ValueError, "record-challenge"):
            self.bind()

    def test_reconciliation_preserves_different_initial_judgment(self) -> None:
        response = self.response("gap")
        response["conclusions"][0]["decisive_reason"] = "The first review treated the invocation of reflexivity on line 5 as an unavailable external result."
        _, reference = self.record(response)
        initial_bytes = (self.root / reference["artifact"]).read_bytes()
        self.prepare_reconciliation(initial_verdict="gap")
        check = self.bind()
        self.assertEqual("gap", check["challenger_verdict"])
        self.assertEqual("verified", check["reconciled_verdict"])
        self.assertEqual("resolved", check["status"])
        self.assertEqual(initial_bytes, (self.root / reference["artifact"]).read_bytes())
        self.assertEqual([], proofcheck.challenge_semantic_freshness_errors(self.root, "lem:a", check, []))

    def test_tampered_initial_response_cannot_be_restamped(self) -> None:
        _, reference = self.record()
        self.prepare_reconciliation()
        self.bind()
        path = self.root / reference["artifact"]
        record = read_json(path)
        record["response"]["conclusions"][0]["decisive_reason"] = "Changed first reasoning with a recomputed payload must still break its established binding."
        record["record_payload_sha256"] = proofcheck.canonical_sha256({
            key: value for key, value in record.items() if key != "record_payload_sha256"
        })
        write_json(path, record)
        with self.assertRaisesRegex(ValueError, "original response cannot be rebound"):
            self.bind()

    def test_progress_metadata_does_not_replace_initial_check(self) -> None:
        _, reference = self.record()
        progress = read_json(self.root / "PROGRESS.json")
        progress["next_action"] = "Continue this unit after a routine handoff."
        write_json(self.root / "PROGRESS.json", progress)
        current = proofcheck.build_context_packet(self.root, "lem:a", "challenge")
        self.assertEqual(proofcheck.challenge_input_projection(self.packet), proofcheck.challenge_input_projection(current))
        _, current_reference, errors = proofcheck.load_initial_challenge(self.root, "lem:a", current)
        self.assertEqual([], errors)
        self.assertEqual(reference, current_reference)

    def test_changed_source_or_applicability_requires_new_initial_check(self) -> None:
        self.record()
        changed = json.loads(json.dumps(self.packet))
        changed["obligation"]["quantifier_scope"] = "For every positive real x."
        _, _, errors = proofcheck.load_initial_challenge(self.root, "lem:a", changed)
        self.assertTrue(any("record-challenge" in error for error in errors))

    def test_altered_consumed_packet_is_rejected(self) -> None:
        changed = json.loads(json.dumps(self.packet))
        changed["source"]["proof"]["lines"][1]["text"] = "A different proof statement."
        write_json(self.packet_path, changed)
        with self.assertRaisesRegex(ValueError, "differs from current"):
            self.record()

    def test_initial_hash_is_anchored_before_reconciliation(self) -> None:
        record, reference = self.record()
        ledger = read_json(self.ledger_path)
        self.assertEqual(reference, ledger["independent_check"]["initial_response"])
        record["response"]["conclusions"][0]["decisive_reason"] = "A replacement conclusion reason authored during reconciliation."
        record["record_payload_sha256"] = proofcheck.canonical_sha256(
            {key: value for key, value in record.items() if key != "record_payload_sha256"})
        write_json(self.root / reference["artifact"], record)
        _, _, errors = proofcheck.load_initial_challenge(self.root, "lem:a", self.packet)
        self.assertTrue(any("original response cannot be rebound" in error for error in errors), errors)

    def test_removing_initial_reference_is_rejected(self) -> None:
        self.record()
        ledger = read_json(self.ledger_path)
        ledger["independent_check"].pop("initial_response")
        write_json(self.ledger_path, ledger)
        _, _, errors = proofcheck.load_initial_challenge(self.root, "lem:a", self.packet)
        self.assertTrue(any("reference is missing" in error for error in errors), errors)

    def test_failed_initial_publication_restores_ledger(self) -> None:
        original = self.ledger_path.read_bytes()
        with mock.patch.object(proofcheck, "atomic_create_json", side_effect=OSError("injected initial publication failure")):
            with self.assertRaisesRegex(OSError, "injected initial publication failure"):
                self.record()
        self.assertEqual(original, self.ledger_path.read_bytes())


class ExplicitJudgmentTests(InitialChallengeTests):
    def setUp(self) -> None:
        super().setUp()
        manifest = read_json(self.root / "AUDIT_MANIFEST.json")
        manifest["protocol"]["challenge_contract_version"] = 3
        write_json(self.root / "AUDIT_MANIFEST.json", manifest)
        self.packet = proofcheck.build_context_packet(self.root, "lem:a", "challenge")
        write_json(self.packet_path, self.packet)

    def response(self, verdict: str = "verified") -> dict:
        result = super().response(verdict)
        result["response_schema_version"] = 2
        result["conclusions"][0].update(
            argument_status={"verified": "valid", "gap": "gap"}[verdict],
            statement_status="established" if verdict == "verified" else "not_established")
        return result

    def test_statement_disagreement_cannot_hide_behind_equal_verdicts(self) -> None:
        response = self.response()
        response["conclusions"][0]["statement_status"] = "not_established"
        self.record(response)
        self.prepare_reconciliation()
        with self.assertRaisesRegex(ValueError, "C001.statement_status"):
            self.bind()
        ledger = read_json(self.ledger_path)
        ledger["independent_check"].update(disagreements=["C001's statement status differs despite equal argument verdicts."],
            resolution="The exact reflexivity step establishes C001 for every real x, resolving the initial statement reservation.")
        write_json(self.ledger_path, ledger)
        self.assertEqual("resolved", self.bind()["status"])

    def test_copied_operational_span_is_not_source_provenance(self) -> None:
        self.packet["operational_binding"]["injected_source"] = self.packet["source"]["proof"]
        self.packet["operational_binding_sha256"] = proofcheck.canonical_sha256(self.packet["operational_binding"])
        write_json(self.packet_path, self.packet)
        response = self.response()
        response["conclusions"][0]["source_refs"][0]["packet_pointer"] = "/operational_binding/injected_source"
        with self.assertRaisesRegex(ValueError, "canonical locked source span"):
            self.record(response)

    def test_new_contract_requires_both_dimensions(self) -> None:
        response = self.response()
        response["conclusions"][0].pop("statement_status")
        with self.assertRaisesRegex(ValueError, "statement_status"):
            self.record(response)

    def test_source_identity_cannot_be_relabelled(self) -> None:
        self.packet["source"]["proof"]["source_member"]["file_sha256"] = "0" * 64
        write_json(self.packet_path, self.packet)
        with self.assertRaisesRegex(ValueError, "source identities"):
            self.record()

    def test_primary_before_reconciliation_is_retained(self) -> None:
        record, reference = self.record()
        self.assertEqual("established", record["primary_snapshot"]["conclusions"][0]["statement_status"])
        original = (self.root / reference["artifact"]).read_bytes()
        ledger = read_json(self.ledger_path)
        ledger["review"]["conclusion_results"][0]["statement_status"] = "not_established"
        errors = proofcheck.initial_conclusion_reconciliation_errors(record, ledger, {"disagreements": [], "resolution": ""})
        self.assertTrue(any("primary pre-reconciliation" in error for error in errors), errors)
        self.assertEqual(original, (self.root / reference["artifact"]).read_bytes())

    def test_superseded_response_and_bound_reconciliation_are_retained(self) -> None:
        _, previous_ref = self.record()
        self.prepare_reconciliation()
        previous_check = self.bind()
        previous_bytes = (self.root / previous_ref["artifact"]).read_bytes()
        reconciliation_bytes = (self.root / previous_check["artifact"]).read_bytes()
        ledger = read_json(self.ledger_path)
        ledger["obligation"]["quantifier_scope"] = "For every real x, independently of any auxiliary parameter."
        for step in ledger["steps"]:
            for premise in step.get("premise_uses", []):
                if premise.get("claim") == "For every real x.":
                    premise["claim"] = ledger["obligation"]["quantifier_scope"]
        write_json(self.ledger_path, ledger)
        # Refresh the fixture's checked work context after the explicit primary
        # restatement, while retaining the previous independently bound record.
        refreshed = proofcheck.build_context_packet(self.root, "lem:a", "primary")
        ledger["work_context_sha256"] = refreshed["work_context_sha256"]
        write_json(self.ledger_path, ledger)
        self.packet = proofcheck.build_context_packet(self.root, "lem:a", "challenge")
        write_json(self.packet_path, self.packet)
        record, _ = self.record()
        historical = record["superseded_review"]
        self.assertEqual(previous_ref, historical["initial_response"])
        self.assertEqual(previous_check, historical["independent_check"])
        self.assertEqual(previous_bytes, (self.root / previous_ref["artifact"]).read_bytes())
        self.assertEqual(reconciliation_bytes, (self.root / historical["reconciliation_artifact"]["artifact"]).read_bytes())

    def test_opposite_conclusions_and_missing_ids_require_reconciliation(self) -> None:
        ledger = read_json(self.ledger_path)
        second = json.loads(json.dumps(ledger["obligation"]["conclusions"][0]))
        second["id"] = "C002"
        ledger["obligation"]["conclusions"].append(second)
        result = json.loads(json.dumps(ledger["review"]["conclusion_results"][0]))
        result["conclusion_id"] = "C002"
        first_result = ledger["review"]["conclusion_results"][0]
        first_step = next(row for row in ledger["steps"] if row["id"] == first_result["support"]["step_id"])
        second_step = json.loads(json.dumps(first_step))
        second_step["id"] = "S099"
        ledger["steps"].append(second_step)
        result["support"]["step_id"] = "S099"
        first_step["status"] = "gap"
        first_result.update(argument_status="gap", statement_status="not_established")
        ledger["review"]["unit_status"] = "gap"
        ledger["review"]["conclusion_results"].append(result)
        response = self.response()
        second_response = json.loads(json.dumps(response["conclusions"][0]))
        second_response.update(conclusion_id="C002", verdict="gap", argument_status="gap", statement_status="not_established")
        response["conclusions"].append(second_response)
        response["challenger_verdict"] = "gap"
        initial = {"response": response}
        check = {"disagreements": [], "resolution": ""}
        errors = proofcheck.initial_conclusion_reconciliation_errors(initial, ledger, check)
        self.assertTrue(any("C002.verdict" in error for error in errors), errors)
        for malformed in ([], [second_response, second_response]):
            with self.subTest(malformed=malformed):
                changed = json.loads(json.dumps(initial))
                changed["response"]["conclusions"] = malformed
                self.assertTrue(any("same IDs exactly once" in error for error in
                    proofcheck.initial_conclusion_reconciliation_errors(changed, ledger, check)))


class PrerequisiteContextTests(unittest.TestCase):
    def test_external_hypothesis_must_be_anchored_in_actual_theorem_source(self) -> None:
        fixture = workflow.WorkflowEfficiencyTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        source = fixture.base / "external-bound.txt"
        source.write_text("Theorem 2, version 3\nFor independent mean-zero X with finite variance, the bound holds.\n", encoding="utf-8")
        result = {"source_evidence": [{"file": str(source), "sha256": proofcheck.sha256_file(source),
            "locator": "Theorem 2, version 3, line 2", "role": "authoritative_theorem_source"}]}
        # A plausible shortened transcription is not a source-bound hypothesis.
        row = {"prerequisite": "X is mean-zero", "status": "satisfied", "source_evidence_spans": []}
        use = {"prerequisite_map": [row]}
        errors = proofcheck.external_prerequisite_source_errors(fixture.audit, result, use, "D001")
        self.assertTrue(any("actual external hypothesis" in error for error in errors), errors)
        row["prerequisite"] = "X is independent, mean-zero, and has finite variance"
        row["source_evidence_spans"] = [proofcheck.locked_span(source, 2, 2, fixture.audit)]
        self.assertEqual([], proofcheck.external_prerequisite_source_errors(fixture.audit, result, use, "D001"))
        other = fixture.base / "authored-summary.txt"
        other.write_text("X is mean-zero.\n", encoding="utf-8")
        row["source_evidence_spans"] = [proofcheck.locked_span(other, 1, 1, fixture.audit)]
        self.assertTrue(any("hash-locked external theorem" in error for error in
            proofcheck.external_prerequisite_source_errors(fixture.audit, result, use, "D001")))

    def test_external_source_and_mapping_are_visible_without_primary_assessment(self) -> None:
        fixture = workflow.WorkflowEfficiencyTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        source = fixture.base / "external-source.txt"
        source.write_text("For independent X with finite second moment, the bound holds.\n", encoding="utf-8")
        result = {"id": "ext:bound", "source_identity": "Example theorem", "version": "3",
            "theorem_location": "Theorem 2", "exact_statement": "The bound holds for mean-zero X.",
            "source_evidence": [{"file": str(source), "sha256": proofcheck.sha256_file(source),
                "locator": "Theorem 2", "role": "theorem_source"}], "status": "verified", "uses": []}
        use = {"dependent_unit": "lem:a", "dependency_id": "ext:bound", "use_id": "D001",
            "dependency_conclusion": result["exact_statement"], "dependency_contract_sha256": proofcheck.canonical_sha256(proofcheck.external_result_contract(result)),
            "prerequisite_map": [{"prerequisite": "X is mean-zero", "manuscript_evidence": "The manuscript says X has mean zero.",
                "status": "satisfied", "issue_ids": [], "evidence_spans": [], "source_evidence_spans": []}]}
        result["uses"] = [use]
        packet = proofcheck.packet_dependency_projection({"external_results": [result]}, fixture.audit, "lem:a", "challenge", None)
        external = packet["external_results"][0]
        self.assertIn("finite second moment", external["source_evidence"][0]["source_span"]["lines"][0]["text"])
        self.assertEqual("3", external["version"])
        mapped = external["uses"][0]["prerequisite_map"][0]
        self.assertEqual("X is mean-zero", mapped["prerequisite"])
        self.assertNotIn("status", mapped)
        self.assertNotIn("issue_ids", mapped)

    def test_repeated_uses_share_one_complete_internal_contract(self) -> None:
        core = load_module("challenge_dependency_fixture", TESTS / "test_proofcheck.py")
        fixture = core.FinalizationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_path = fixture.make_complete_audit()
            fixture.install_internal_dependency(ledger_path)
        registry = read_json(fixture.audit / "audit/03_dependencies/DEPENDENCY_REGISTRY.json")
        repeat = json.loads(json.dumps(registry["internal_uses"][0]))
        repeat["use_id"] = "D002"
        registry["internal_uses"].append(repeat)
        projected = proofcheck.packet_dependency_projection(
            registry, fixture.audit, "lem:main", "challenge", read_json(ledger_path)
        )
        self.assertEqual(2, len(projected["direct_internal_uses"]))
        self.assertEqual(1, len(projected["internal_contracts"]))
        contract = projected["internal_contracts"][0]
        self.assertTrue(contract["applicability"])
        self.assertTrue(contract["statement_spans"][0]["lines"])
        self.assertEqual({contract["contract_ref"]}, {row["contract_ref"] for row in projected["direct_internal_uses"]})

    def test_actual_conditions_constants_and_source_are_exposed_per_conclusion(self) -> None:
        fixture = workflow.WorkflowEfficiencyTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        prior = fixture.base / "bounded.tex"
        prior.write_text(
            "\\begin{lemma}\nFor x in [-1,1], f(x) <= C_d; for real y, g(y)=y.\n\\end{lemma}\nC_d depends on dimension d.\n",
            encoding="utf-8",
        )
        audit = fixture.base / "bounded-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(argparse.Namespace(paper=prior, output=audit))
        ledger_path = audit / "audit/04_local_checks/bounded.ledger.json"
        statement = proofcheck.locked_span(prior, 1, 3, ledger_path.parent)
        context = proofcheck.locked_span(prior, 4, 4, ledger_path.parent)
        ledger = {"unit_id": "lem:bounded", "obligation": {
            "hypotheses": ["x in [-1,1]", "y is real"],
            "constant_dependencies": ["C_d may depend on dimension d"],
            "statement_spans": [statement], "context_spans": [context],
            "conclusions": [{"id": "C001", "claim": "f(x) <= C_d", "source_spans": [statement],
                             "applies_under": ["/hypotheses/0", "/constant_dependencies/0"]},
                            {"id": "C002", "claim": "g(y)=y", "source_spans": [statement],
                             "applies_under": ["/hypotheses/1"]}],
        }}
        contract = proofcheck.packet_prerequisite_contract(audit, ledger_path, ledger, "C001")
        self.assertEqual(["x in [-1,1]", "C_d may depend on dimension d"], [row["resolved"] for row in contract["applicability"]])
        self.assertTrue(contract["statement_spans"][0]["lines"])
        self.assertEqual("C_d depends on dimension d.", contract["context_spans"][0]["lines"][0]["text"])
        for needed_form in ("f(2) <= C_d", "f(1/2) <= C_d"):
            use = proofcheck.packet_dependency_use({"dependency_id": "lem:bounded", "needed_form": needed_form}, audit, "challenge")
            self.assertEqual(needed_form, use["needed_form"])
            self.assertEqual("x in [-1,1]", contract["applicability"][0]["resolved"])
        ledger["obligation"]["statement_spans"] = []
        with self.assertRaisesRegex(ValueError, "prerequisite statement is missing"):
            proofcheck.packet_prerequisite_contract(audit, ledger_path, ledger, "C001")


class FullChallengeGateTests(unittest.TestCase):
    def test_equal_aggregate_opposite_conclusions_fail_binding_and_full_gate(self) -> None:
        core = load_module("opposite_conclusion_fixture", TESTS / "test_proofcheck.py")
        fixture = core.FinalizationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_path = fixture.make_complete_audit()
        ledger = read_json(ledger_path)
        second = json.loads(json.dumps(ledger["obligation"]["conclusions"][0]))
        second.update(id="C002", claim="Every real x is identical to itself")
        ledger["obligation"]["conclusions"].append(second)
        failed = ledger["steps"][2]
        clean = json.loads(json.dumps(failed))
        clean.update(id="S004", restatement=second["claim"], goal="Establish the independent verbal conclusion.")
        clean["inference"]["moves"][0].update(claim=second["claim"], rule="Reflexivity in verbal form",
            justification="Reflexivity establishes identity with itself for the arbitrary real x.")
        ledger["steps"][3]["id"] = "S005"
        ledger["steps"].insert(3, clean)
        second_result = json.loads(json.dumps(ledger["review"]["conclusion_results"][0]))
        second_result.update(conclusion_id="C002", support={"step_id": "S004", "move_id": "M001"})
        ledger["review"]["conclusion_results"].append(second_result)
        failed.update(status="gap", issue_ids=["I-001"])
        failed["inference"]["moves"][0]["failure"] = {"kind": "unsupported_assertion", "issue_id": "I-001",
            "evidence": "The first conclusion is recorded as unsupported by its written move."}
        ledger["review"]["conclusion_results"][0].update(argument_status="gap", statement_status="not_established", issue_ids=["I-001"])
        ledger["review"].update(unit_status="gap", argument_status="gap", statement_status="not_established", conclusion_step_id="")
        ledger["independent_check"].update(challenger_verdict="gap", reconciled_verdict="gap")
        write_json(ledger_path, ledger)
        with contextlib.redirect_stdout(io.StringIO()):
            fixture.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        self.assertEqual([], proofcheck.check_ledger_data(ledger_path, True)[0])
        issue = fixture.make_global_issue(finding_status="defect", load_bearing=True, severity="S1",
            summary="The first conclusion has an unsupported proof move.")
        issue.update(origin_ref={"kind": "ledger_move", "unit_id": "lem:main", "step_id": "S003", "move_id": "M001"},
            contract_refs=[{"kind": "conclusion", "unit_id": "lem:main", "conclusion_id": "C001"}], invalidation_kind="proof_gap")
        with contextlib.redirect_stdout(io.StringIO()):
            fixture.install_canonical_issue(issue, migrate=False, reconcile_report_views=False)
            fixture.set_expected_assessment("defects_found")
        manifest = read_json(fixture.audit / "AUDIT_MANIFEST.json")
        manifest["protocol"]["challenge_contract_version"] = 3
        write_json(fixture.audit / "AUDIT_MANIFEST.json", manifest)
        packet = proofcheck.build_context_packet(fixture.audit, "lem:main", "challenge")
        self.assertNotIn("severity", json.dumps(packet["issue_triggers"]))
        response = {"response_schema_version": 2, "unit_id": "lem:main", "independence_level": "fresh_context_same_model",
            "challenger_verdict": "gap", "conclusions": [], "issue_assessments": []}
        for identifier, verdict, argument, statement in (("C001", "verified", "valid", "established"), ("C002", "gap", "gap", "not_established")):
            response["conclusions"].append({"conclusion_id": identifier, "verdict": verdict, "argument_status": argument,
                "statement_status": statement, "decisive_reason": "Reflexivity is considered separately for the exact stated conclusion and its written support.",
                "source_refs": [{"packet_pointer": "/source/statement", "start_line": 3, "end_line": 3}]})
        for trigger in packet["issue_triggers"]:
            response["issue_assessments"].append({"issue_id": trigger["id"], "assessment": "not_confirmed",
                "target_assessment": "The initial checker regards C001 as established by direct reflexivity.",
                "downstream_assessment": "No downstream result depends on the separate C002 conclusion in this fixture."})
        packet_path, response_path = fixture.base / "packet.json", fixture.base / "response.json"
        write_json(packet_path, packet)
        write_json(response_path, response)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_record_challenge(argparse.Namespace(root=fixture.audit, unit_id="lem:main", packet=packet_path, response=response_path))
        ledger = read_json(ledger_path)
        ledger["independent_check"].update(disagreements=[], resolution="", issue_assessments=[], challenger_verdict="gap", reconciled_verdict="gap")
        write_json(ledger_path, ledger)
        with self.assertRaisesRegex(ValueError, "C001.verdict.*C002.verdict"):
            proofcheck.cmd_bind_challenge(argparse.Namespace(root=fixture.audit, unit_id="lem:main"))
        errors, _ = proofcheck.check_audit_finalization(fixture.audit)
        self.assertTrue(any("Changed conclusion judgments" in error for error in errors), errors)

    def test_full_gate_requires_initial_evidence_after_explicit_upgrade(self) -> None:
        core = load_module("challenge_full_gate_fixture", TESTS / "test_proofcheck.py")
        fixture = core.FinalizationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with contextlib.redirect_stdout(io.StringIO()):
            fixture.make_complete_audit()
        self.assertEqual([], proofcheck.check_audit_finalization(fixture.audit)[0])
        manifest_path = fixture.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["challenge_contract_version"] = 2
        write_json(manifest_path, manifest)
        errors, _ = proofcheck.check_audit_finalization(fixture.audit)
        self.assertTrue(any("initial" in error or "record-challenge" in error for error in errors), errors)
        packet = proofcheck.build_context_packet(fixture.audit, "lem:main", "challenge")
        source = packet["source"]["proof"]["lines"]
        number = next(row["line"] for row in source if "x" in row["text"])
        response = {
            "response_schema_version": 1, "unit_id": "lem:main",
            "independence_level": "fresh_context_same_model", "challenger_verdict": "verified",
            "conclusions": [{"conclusion_id": "C001", "verdict": "verified",
                "decisive_reason": "Reflexivity establishes x=x for the arbitrary real variable fixed by the statement.",
                "source_refs": [{"packet_pointer": "/source/proof", "start_line": number, "end_line": number}]}],
            "issue_assessments": [],
        }
        packet_path, response_path = fixture.base / "packet.json", fixture.base / "response.json"
        write_json(packet_path, packet)
        write_json(response_path, response)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_record_challenge(argparse.Namespace(root=fixture.audit, unit_id="lem:main", packet=packet_path, response=response_path))
            proofcheck.cmd_bind_challenge(argparse.Namespace(root=fixture.audit, unit_id="lem:main"))
            fixture.refresh_report_views()
        errors, _ = proofcheck.check_audit_finalization(fixture.audit)
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
