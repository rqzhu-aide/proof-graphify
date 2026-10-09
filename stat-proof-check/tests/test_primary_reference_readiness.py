from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

import test_proofcheck as fixtures


proofcheck = fixtures.proofcheck
read_json = fixtures.read_json
write_json = fixtures.write_json


class PrimaryReferenceRuleTests(unittest.TestCase):
    """Exercise source-role meaning separately from local premise syntax."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.paper = self.base / "paper.tex"
        self.paper.write_text(
            "\\begin{lemma}\\label{lem:main}\n"
            "$x=x$.\\label{eq:target}\n"
            "\\end{lemma}\n"
            "\\begin{proof}\n"
            "Fix a real x.\n"
            "Use the definition of equality.\n"
            "The intermediate expression is x.\n"
            "Reflexivity applies to every real x.\n"
            "Thus x=x.\n"
            "This proves the lemma.\n"
            "\\end{proof}\n",
            encoding="utf-8",
        )
        self.unit = {
            "id": "lem:main", "proof_required": True, "environment": "lemma",
            "statement": {"file": "paper.tex", "start_line": 1, "end_line": 3},
            "proof": {"file": "paper.tex", "start_line": 4, "end_line": 11},
            "candidate_internal_dependencies": [],
        }
        self.units = {
            "lem:main": self.unit,
            "lem:prior": {"id": "lem:prior", "proof_required": True, "environment": "lemma"},
            "ass:domain": {"id": "ass:domain", "proof_required": False, "environment": "assumption"},
        }
        self.occurrence = {
            "occurrence_id": "R-one", "file": "paper.tex", "line": 6,
            "command": "ref", "target": "eq:target", "structural_context": "proof_body",
            "resolution_status": "unique", "owner_unit_id": "lem:main",
            "owner_region": "statement",
        }
        self.summary = {
            "declared_unit_status": "verified", "direct_dependencies": [],
            "result_dependency_claims": [], "candidate_dependency_dispositions": [],
            "source_reference_dispositions": [{
                "occurrence_id": "R-one", "target": "eq:target", "command": "ref",
                "disposition": "non_load_bearing",
                "evidence": "The reference names the expression whose value is then derived.",
            }],
        }

    def roles(self, role: str, **occurrence_changes) -> list[str]:
        self.occurrence.update(occurrence_changes)
        row = self.summary["source_reference_dispositions"][0]
        row.update(disposition=role, target=self.occurrence["target"],
                   command=self.occurrence["command"])
        errors: list[str] = []
        proofcheck.validate_primary_reference_roles(
            "lem:main", self.unit, self.summary, [self.occurrence],
            self.units, self.base, errors,
        )
        return errors

    def test_equation_label_is_not_own_result_identification(self) -> None:
        for line in (6, 10):
            with self.subTest(line=line):
                errors = self.roles("own_result_identification", line=line)
                self.assertEqual(1, len(errors))
                self.assertIn("not a proof header or reviewed closing identification", errors[0])
                self.assertIn(f"paper.tex:{line}", errors[0])
                self.assertIn("/review/source_reference_dispositions/0", errors[0])

    def test_headers_and_closing_result_identification_pass(self) -> None:
        self.assertEqual([], self.roles(
            "own_result_identification", target="lem:main", line=4,
            structural_context="proof_header"))
        self.assertEqual([], self.roles(
            "own_result_identification", target="lem:main", line=10,
            structural_context="proof_body"))
        self.assertTrue(self.roles("own_result_identification", line=6))

    def test_announcements_expression_naming_and_local_uses_pass(self) -> None:
        for role in ("non_load_bearing", "local_step"):
            with self.subTest(role=role):
                self.assertEqual([], self.roles(role))
        self.assertTrue(self.roles("non_load_bearing", target="lem:main", line=6))

    def test_obligation_context_cannot_import_a_proved_foreign_result(self) -> None:
        for owner, region in (("lem:prior", "statement"), ("lem:prior", "proof"),
                              ("lem:main", "proof")):
            with self.subTest(owner=owner, region=region):
                errors = self.roles("obligation_context", owner_unit_id=owner,
                                    owner_region=region)
                self.assertEqual(1, len(errors))
                self.assertIn("reviewed foreign non-proof unit", errors[0])
                self.assertIn("paper.tex:6", errors[0])
                self.assertIn("/review/source_reference_dispositions/0", errors[0])
        self.assertEqual([], self.roles("obligation_context", owner_unit_id="lem:main",
                                        owner_region="statement"))
        self.assertEqual([], self.roles("obligation_context", owner_unit_id="ass:domain",
                                        owner_region="statement"))

    def candidate(self, mapped_use: str, *, registry_use="D002") -> list[str]:
        self.unit["candidate_internal_dependencies"] = ["lem:prior"]
        self.occurrence.update(target="lem:prior", owner_unit_id="lem:prior")
        self.summary["candidate_dependency_dispositions"] = [{
            "candidate_id": "lem:prior", "path_ids": ["CP001"],
            "disposition": "internal_result", "dependency_use_id": mapped_use,
            "evidence": "The earlier lemma supplies the exact result invoked in this proof.",
        }]
        errors: list[str] = []
        proofcheck.validate_primary_candidate_references(
            self.base, {"units": list(self.units.values())}, "lem:main", self.unit,
            self.summary, self.units, self.base, [self.occurrence], [],
            [{"dependent_unit": "lem:main", "dependency_id": "lem:prior",
              "use_id": registry_use, "kind": "internal_result"}], errors,
            candidate_paths=[{"path_id": "CP001", "candidate_id": "lem:prior",
                              "reference_chain": [self.occurrence]}],
        )
        return errors

    def test_candidate_must_match_the_exact_registry_use(self) -> None:
        errors = self.candidate("D001")
        self.assertEqual(1, len(errors))
        self.assertIn("must map to its exact registry dependency use", errors[0])
        self.assertIn("paper.tex:6", errors[0])
        self.assertIn("/review/candidate_dependency_dispositions/0", errors[0])
        self.assertEqual([], self.candidate("D002"))

    def test_diagnostic_pointer_uses_the_complete_candidate_id(self) -> None:
        for candidate_id in ("lem:ab", "lem:a-b", "lem:a.b", "lem:a/b",
                             "lem:a_b", "lem:a:b"):
            with self.subTest(candidate_id=candidate_id):
                summary = {"candidate_dependency_dispositions": [
                    {"candidate_id": "lem:a"}, {"candidate_id": candidate_id},
                ]}
                occurrences = [
                    {"owner_unit_id": "lem:a", "file": "paper.tex", "line": 6},
                    {"owner_unit_id": candidate_id, "file": "paper.tex", "line": 9},
                ]
                reason = (f"lem:main: candidate {candidate_id} must map to its "
                          "exact registry dependency use")
                errors = [reason]
                proofcheck.annotate_primary_reference_errors(
                    errors, 0, self.unit, summary, occurrences,
                    "candidate_dependency_dispositions", "candidate_id",
                )
                self.assertEqual(
                    [reason + " [paper.tex:9; /review/candidate_dependency_dispositions/1]"],
                    errors,
                )

    def test_internal_occurrence_matches_owner_and_actual_proof_use(self) -> None:
        dependency = {"use_id": "D002", "kind": "internal_result", "id": "lem:prior"}
        self.summary["direct_dependencies"] = [dependency]
        self.summary["result_dependency_claims"] = [copy.deepcopy(dependency)]
        self.summary["source_reference_dispositions"][0]["dependency_use_id"] = "D002"
        self.assertEqual([], self.roles("internal_result", target="lem:prior",
                                        owner_unit_id="lem:prior"))
        self.summary["result_dependency_claims"] = []
        self.assertTrue(any("exact proof-step dependency use" in error
                            for error in self.roles("internal_result")))


class PrimaryReferenceReadinessIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.FinalizationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.audit = self.fixture.audit
        self.ledger_path = self.fixture.make_complete_audit()
        ledger = read_json(self.ledger_path)
        ledger["independent_check"].update(status="pending", challenger_verdict="not_checked",
                                            reconciled_verdict="not_checked")
        write_json(self.ledger_path, ledger)

    def issues(self) -> tuple[int, str]:
        before = {str(path.relative_to(self.audit)): path.read_bytes()
                  for path in self.audit.rglob("*") if path.is_file()}
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = proofcheck.cmd_issues(argparse.Namespace(
                root=self.audit, before_challenge=True, final=False,
                write_summary=False, write_report_views=False,
            ))
        self.assertTrue(json.loads(stdout.getvalue())["read_only"])
        self.assertEqual(before, {str(path.relative_to(self.audit)): path.read_bytes()
                                  for path in self.audit.rglob("*") if path.is_file()})
        return status, stderr.getvalue()

    def test_manual_wrong_role_fails_before_dispatch_and_at_finalization(self) -> None:
        ledger = read_json(self.ledger_path)
        ledger["review"]["source_reference_dispositions"][0]["disposition"] = "own_result_identification"
        write_json(self.ledger_path, ledger)
        # Local source and premise syntax alone accepts the old historical shape.
        local_errors, _ = proofcheck.check_ledger_data(self.ledger_path, True, primary_only=True)
        self.assertEqual([], local_errors)
        primary = proofcheck.build_context_packet(self.audit, "lem:main", "primary")
        self.assertFalse(primary["primary_record_ready"])
        with self.assertRaisesRegex(ValueError, "own-result occurrence"):
            proofcheck.build_context_packet(self.audit, "lem:main", "challenge")
        status, errors = self.issues()
        self.assertEqual(1, status)
        self.assertIn("own-result occurrence", errors)
        self.assertIn("paper.tex:6", errors)
        self.assertIn("/review/source_reference_dispositions/0", errors)
        final_errors, _ = proofcheck.check_audit_finalization(self.audit, check_reports=False)
        self.assertTrue(any("own-result occurrence" in error for error in final_errors))

    def test_valid_primary_needs_no_independent_completion_or_report(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["completion"]["final_report_ready"] = False
        write_json(manifest_path, manifest)
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["status"] = "in_progress"
        write_json(progress_path, progress)
        status, errors = self.issues()
        self.assertEqual(0, status, errors)
        packet = proofcheck.build_context_packet(self.audit, "lem:main", "challenge")
        self.assertTrue(packet["primary_record_ready"])


if __name__ == "__main__":
    unittest.main()
