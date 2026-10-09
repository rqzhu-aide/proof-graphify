from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import unittest

import test_proofcheck as fixtures


proofcheck = fixtures.proofcheck
read_json = fixtures.read_json
write_json = fixtures.write_json


class IssueReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reuse the existing complete evidence fixture without inheriting its tests.
        self.fixture = fixtures.FinalizationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.audit = self.fixture.audit
        self.ledger = self.fixture.make_complete_audit()
        self.completed_check = copy.deepcopy(read_json(self.ledger)["independent_check"])
        self.make_pending(self.ledger)

    def make_pending(self, ledger_path) -> None:
        ledger = read_json(ledger_path)
        ledger["independent_check"]["status"] = "pending"
        ledger["independent_check"]["challenger_verdict"] = "not_checked"
        ledger["independent_check"]["reconciled_verdict"] = "not_checked"
        write_json(ledger_path, ledger)

    def snapshot(self) -> dict:
        return {str(path.relative_to(self.audit)): path.read_bytes()
                for path in self.audit.rglob("*") if path.is_file()}

    def run_issues(self, *, before_challenge=True, final=False):
        before = self.snapshot()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = proofcheck.cmd_issues(argparse.Namespace(
                root=self.audit, before_challenge=before_challenge, final=final,
                write_summary=False, write_report_views=False,
            ))
        self.assertEqual(before, self.snapshot())
        payload = json.loads(stdout.getvalue())
        if before_challenge:
            self.assertEqual("NONFINAL", payload["delivery_status"])
            self.assertTrue(payload["read_only"])
            self.assertFalse(payload["report_views_written"])
            self.assertEqual("ready" if status == 0 else "not_ready", payload["readiness"])
        return status, payload, stderr.getvalue()

    def test_pending_independent_review_passes_readiness_but_not_final(self) -> None:
        status, payload, errors = self.run_issues()
        self.assertEqual(0, status, errors)
        self.assertEqual(0, payload["errors"])
        status, _, errors = self.run_issues(before_challenge=False, final=True)
        self.assertEqual(1, status)
        self.assertIn("required independent check must be agreed or resolved", errors)

    def test_current_challenge_contract_needs_no_fabricated_initial_response(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["challenge_contract_version"] = 3
        write_json(manifest_path, manifest)
        self.fixture.install_calibration()
        ledger = read_json(self.ledger)
        packet = proofcheck.build_context_packet(self.audit, "lem:main", "primary")
        ledger["work_context_sha256"] = packet["work_context_sha256"]
        write_json(self.ledger, ledger)
        status, _, errors = self.run_issues()
        self.assertEqual(0, status, errors)

    def test_unfinished_report_and_progress_do_not_block_primary_readiness(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["completion"]["final_report_ready"] = False
        write_json(manifest_path, manifest)
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress.update(status="in_progress", current_pass=6,
                        next_action="Dispatch the primary evidence for independent review.")
        write_json(progress_path, progress)
        (self.audit / "audit/06_reports/FINAL_REPORT.md").write_text(
            "# Working Proof-Check Report\n\nNONFINAL: independent review remains pending.\n",
            encoding="utf-8")
        status, _, errors = self.run_issues()
        self.assertEqual(0, status, errors)
        final_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(any("final_report_ready" in error for error in final_errors))
        self.assertTrue(any("status must be complete" in error for error in final_errors))
        self.assertTrue(any("challenger" in error or "independent check" in error
                            for error in final_errors))

    def test_association_metadata_omissions_fail_before_dispatch(self) -> None:
        # Reproduce the four source-bound diagnostics in the preserved release
        # trial's receipts/036-primary-status.json without touching that audit.
        inventory_path = self.audit / "audit/01_index/theorem_inventory.json"
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        inventory = read_json(inventory_path)
        unit = inventory["units"][0]
        parser_association = copy.deepcopy(unit["proof_association"])
        proof_location = proofcheck.canonical_location(unit["proof"])
        unit["proof_association"] = {"method": "reviewed_manual"}
        write_json(inventory_path, inventory)
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["inventory_overrides"] = [{
            "unit_id": "lem:main", "kind": "proof_location",
            "parser_proof": proof_location, "reviewed_proof": proof_location,
            "reason": "The reviewer records the source proof for the formal statement.",
            "evidence": "The complete proof span is inspected in the locked source.",
        }]
        write_json(manifest_path, manifest)
        self.fixture.refresh_dependency_review()
        ledger = read_json(self.ledger)
        ledger["work_context_sha256"] = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary")["work_context_sha256"]
        write_json(self.ledger, ledger)
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        expected = (
            "audit_scope.inventory_overrides[1].association_method must match the reviewed association",
            "audit_scope.inventory_overrides[1].reviewed_proof_sha256 is stale",
            "Reviewed inventory additions lack explicit overrides: lem:main/proof_association",
            "lem:main: every reviewed proof span requires an explicitly associated proof_association",
        )
        final_errors, _ = proofcheck.check_audit_finalization(self.audit)
        for diagnostic in expected:
            self.assertIn(diagnostic, errors)
            self.assertIn(diagnostic, final_errors)

        unit["proof_association"].update(status="associated", target="lem:main",
                                         evidence_occurrence_ids=[])
        write_json(inventory_path, inventory)
        # Its physical proof span is unchanged, so only its reviewed association
        # needs an override. Bind that change to the exact parser association.
        manifest["audit_scope"]["inventory_overrides"] = [{
            "unit_id": "lem:main", "kind": "proof_association",
            "parser_association": parser_association,
            "reviewed_association": copy.deepcopy(unit["proof_association"]),
            "rendered_source_evidence": "The complete locked proof establishes the displayed reflexive equality.",
            "reason": "The reviewer explicitly confirms the source proof association.",
            "evidence": "The formal statement and complete proof have exact source bounds.",
        }]
        write_json(manifest_path, manifest)
        self.fixture.refresh_dependency_review()
        ledger["work_context_sha256"] = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary")["work_context_sha256"]
        write_json(self.ledger, ledger)
        status, _, errors = self.run_issues()
        self.assertEqual(0, status, errors)

    def test_write_flags_and_final_are_rejected_without_mutation(self) -> None:
        for flag in ("write_summary", "write_report_views", "final"):
            with self.subTest(flag=flag):
                args = argparse.Namespace(
                    root=self.audit, before_challenge=True, final=False,
                    write_summary=False, write_report_views=False,
                )
                setattr(args, flag, True)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "read-only"):
                    proofcheck.cmd_issues(args)
                self.assertEqual(before, self.snapshot())
        parser = proofcheck.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["issues", "--root", str(self.audit),
                               "--before-challenge", "--final"])

    def test_missing_primary_scope_unit_fails(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["in_scope_units"].append("lem:missing")
        write_json(manifest_path, manifest)
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        self.assertIn("in-scope unit lem:missing; found 0", errors)

    def test_empty_missing_and_duplicate_scope_cannot_claim_readiness(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        original = read_json(manifest_path)
        for values in ([], None, ["lem:main", "lem:main"]):
            with self.subTest(values=values):
                manifest = copy.deepcopy(original)
                if values is None:
                    manifest["audit_scope"].pop("in_scope_units")
                else:
                    manifest["audit_scope"]["in_scope_units"] = values
                write_json(manifest_path, manifest)
                status, _, errors = self.run_issues()
                self.assertEqual(1, status)
                self.assertIn("unique nonempty in_scope_units", errors)

    def test_stale_primary_context_fails(self) -> None:
        ledger = read_json(self.ledger)
        ledger["work_context_sha256"] = "0" * 64
        write_json(self.ledger, ledger)
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        self.assertIn("work_context_sha256 is stale", errors)

    def test_candidate_disposition_readiness_matches_challenge_dispatch(self) -> None:
        # A real parser candidate can be navigation rather than a proof premise.
        self.fixture.paper.write_text(
            self.fixture.paper.read_text(encoding="utf-8").replace(
                r"see \ref{eq:reflexive}", r"see \ref{lem:prior}"
            )
            + "\\begin{lemma}\\label{lem:prior}\n"
              "Every real object is equal to itself.\n"
              "\\end{lemma}\n"
              "\\begin{proof}\n"
              "Reflexivity gives this equality.\n"
              "\\end{proof}\n",
            encoding="utf-8",
        )
        self.audit = self.fixture.base / "candidate-audit"
        self.fixture.audit = self.audit
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(argparse.Namespace(
                paper=self.fixture.paper, output=self.audit, report_format="markdown",
            ))
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        write_json(manifest_path, manifest)
        self.ledger = self.fixture.make_complete_audit()
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["excluded_units"] = [{
            "id": "lem:prior",
            "reason": "This navigation reference supplies no premise to the focused proof.",
        }]
        write_json(manifest_path, manifest)
        self.make_pending(self.ledger)
        packet = proofcheck.build_context_packet(self.audit, "lem:main", "primary")
        self.assertFalse(packet["semantic_review_ready"])
        candidate_paths = packet["inventory"]["candidate_dependency_paths"]
        self.assertEqual({"lem:prior"}, {row["candidate_id"] for row in candidate_paths})
        ledger = read_json(self.ledger)
        self.assertEqual(ledger["work_context_sha256"], packet["work_context_sha256"])
        local_errors, _ = proofcheck.check_ledger_data(self.ledger, True, primary_only=True)
        self.assertEqual([], local_errors)

        disposition = {
            "candidate_id": "lem:prior",
            "path_ids": sorted(row["path_id"] for row in candidate_paths),
            "disposition": "non_load_bearing",
            "evidence": "The reference offers navigation; reflexivity directly proves x equals x without importing the other lemma.",
        }
        for present in (False, True, False, True):
            with self.subTest(disposition_present=present):
                ledger["review"]["candidate_dependency_dispositions"] = [disposition] if present else []
                write_json(self.ledger, ledger)
                current = proofcheck.build_context_packet(self.audit, "lem:main", "primary")
                self.assertEqual(ledger["work_context_sha256"], current["work_context_sha256"])
                status, _, errors = self.run_issues()
                if present:
                    self.assertEqual(0, status, errors)
                    challenge = proofcheck.build_context_packet(self.audit, "lem:main", "challenge")
                    self.assertTrue(challenge["semantic_review_ready"])
                else:
                    self.assertEqual(1, status)
                    for reason in current["semantic_review_reasons"]:
                        self.assertIn(reason, errors)
                    with self.assertRaisesRegex(ValueError, "Candidate internal dependencies"):
                        proofcheck.build_context_packet(self.audit, "lem:main", "challenge")

    def test_invalid_primary_evidence_and_source_drift_fail(self) -> None:
        original = self.ledger.read_bytes()
        ledger = read_json(self.ledger)
        ledger["steps"][2]["inference"]["moves"][0]["justification"] = ""
        write_json(self.ledger, ledger)
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        self.assertIn("justification", errors)
        self.ledger.write_bytes(original)
        self.fixture.paper.write_text(self.fixture.paper.read_text(encoding="utf-8")
                                      + "% changed source\n", encoding="utf-8")
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        self.assertIn("drift", errors.lower())

    def test_missing_dependency_use_fails(self) -> None:
        ledger = read_json(self.ledger)
        ledger["independent_check"] = self.completed_check
        write_json(self.ledger, ledger)
        self.fixture.install_internal_dependency(self.ledger)
        for path in self.ledger.parent.glob("*.ledger.json"):
            self.make_pending(path)
        registry_path = self.audit / "audit/03_dependencies/DEPENDENCY_REGISTRY.json"
        registry = read_json(registry_path)
        registry["internal_uses"] = []
        write_json(registry_path, registry)
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        self.assertIn("D001", errors)
        self.assertIn("registry", errors.lower())

    def test_incomplete_global_checks_fail(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["completion"]["global_consistency_pass"]["checks"] = []
        write_json(manifest_path, manifest)
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        self.assertIn("global_consistency_pass", errors)

    def test_unrelated_root_conclusion_issue_anchor_fails_before_review(self) -> None:
        ledger = read_json(self.ledger)
        second = copy.deepcopy(ledger["obligation"]["conclusions"][0])
        second.update(id="C002", claim="Every real x is identical to itself")
        ledger["obligation"]["conclusions"].append(second)
        failed = ledger["steps"][2]
        clean = copy.deepcopy(failed)
        clean.update(id="S004", restatement=second["claim"],
                     goal="Establish the independent verbal conclusion.")
        clean["inference"]["moves"][0].update(
            claim=second["claim"], rule="Reflexivity in verbal form",
            justification="Reflexivity establishes identity with itself for arbitrary real x.",
        )
        ledger["steps"][3]["id"] = "S005"
        ledger["steps"].insert(3, clean)
        second_result = copy.deepcopy(ledger["review"]["conclusion_results"][0])
        second_result.update(conclusion_id="C002", support={"step_id": "S004", "move_id": "M001"})
        ledger["review"]["conclusion_results"].append(second_result)
        ledger["review"]["conclusion_step_id"] = ""
        failed.update(status="gap", issue_ids=["I-001"])
        failed["inference"]["moves"][0]["failure"] = {
            "kind": "unsupported_assertion", "issue_id": "I-001",
            "evidence": "The recorded premise does not establish this conclusion.",
        }
        ledger["review"]["conclusion_results"][0].update(
            argument_status="gap", statement_status="not_established", issue_ids=["I-001"],
        )
        ledger["review"].update(unit_status="gap", argument_status="gap", statement_status="not_established")
        write_json(self.ledger, ledger)
        issue = self.fixture.make_global_issue(
            finding_status="defect", load_bearing=True, severity="S1",
            summary="The first conclusion has an unsupported proof move.",
        )
        issue.update(
            scope="unit", invalidation_kind="proof_gap",
            origin_ref={"kind": "ledger_move", "unit_id": "lem:main", "step_id": "S003", "move_id": "M001"},
            contract_refs=[{"kind": "conclusion", "unit_id": "lem:main", "conclusion_id": value}
                           for value in ("C001", "C002")],
        )
        issue_path = self.audit / "audit/06_reports/ISSUE_LOG.json"
        issue_log = read_json(issue_path)
        issue_log["issues"] = [issue]
        write_json(issue_path, issue_log)
        packet = proofcheck.build_context_packet(self.audit, "lem:main", "primary")
        ledger["work_context_sha256"] = packet["work_context_sha256"]
        write_json(self.ledger, ledger)
        status, _, errors = self.run_issues()
        self.assertEqual(1, status)
        self.assertIn("I-001.contract_refs[2]", errors)
        self.assertIn("C002", errors)
        self.assertIn("not linked back", errors)
        # Removing only the spurious ancestry link keeps both conclusions intact.
        issue["contract_refs"].pop()
        write_json(issue_path, issue_log)
        status, _, errors = self.run_issues()
        self.assertEqual(0, status, errors)


if __name__ == "__main__":
    unittest.main()
