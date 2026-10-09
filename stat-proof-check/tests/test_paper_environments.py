"""Real manuscript customization at discovery and the existing FINAL gate."""
from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_proofcheck as fixtures

pc = fixtures.proofcheck


class PaperEnvironmentTests(unittest.TestCase):
    def scan(self, text: str, definitions: str = "") -> tuple[Path, dict]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        paper = root / "paper.tex"
        (root / "defs.tex").write_text(definitions, encoding="utf-8")
        paper.write_text("\\input{defs}\n" + text, encoding="utf-8")
        return paper, pc.scan_formal_units(paper)

    def test_declared_roles_and_literal_titles_are_preserved(self):
        _, result = self.scan(
            "\\begin{ass}\\label{ass:a}\n$X$ is integrable.\n\\end{ass}\n"
            "\\begin{defn}\\label{def:a}\nLet $m=EX$.\n\\end{defn}\n"
            "\\begin{thm}[Consistency]\\label{thm:a}\nThe result holds.\n\\end{thm}\n"
            "\\begin{proof}\nBy the assumptions.\n\\end{proof}\n",
            "\\newtheorem{ass}{Assumption}\n\\newtheorem{defn}[ass]{Definition}\n"
            "\\newtheorem{thm}{Theorem}\n",
        )
        units = {unit["id"]: unit for unit in result["units"]}
        self.assertFalse(units["ass:a"]["proof_required"])
        self.assertFalse(units["def:a"]["proof_required"])
        self.assertTrue(units["thm:a"]["proof_required"])
        self.assertEqual("theorem", units["thm:a"]["semantic_kind"])
        self.assertEqual("Consistency", units["thm:a"]["statement_title"])
        self.assertTrue(units["ass:a"]["environment_declaration"]["sha256"])

    def test_declared_theorem_without_proof_still_warns(self):
        _, result = self.scan("\\begin{thm}\\label{thm:a}\nFalse.\n\\end{thm}\n", "\\newtheorem{thm}{Theorem}\n")
        self.assertTrue(any("no associated proof" in value for value in result["warnings"]))

    def test_restatable_and_appendix_copy_have_one_original_identity(self):
        paper, result = self.scan(
            "\\begin{lemma}\\label{lem:a}\nA.\n\\end{lemma}\n"
            "\\begin{proof}\nA.\n\\end{proof}\n"
            "\\begin{restatable}[Main result]{thm}{mainresult}\\label{thm:main}\n"
            "B.\n\\end{restatable}\n"
            "\\section{Proofs}\n\\mainresult*\n"
            "\\begin{proof}\nB.\n\\end{proof}\n",
            "\\newtheorem{thm}{Theorem}\n",
        )
        self.assertEqual(["lem:a", "thm:main"], [u["id"] for u in result["units"]])
        unit = result["units"][1]
        self.assertEqual("thm", unit["environment"])
        self.assertEqual("Main result", unit["statement_title"])
        self.assertEqual(1, len(unit["restatements"]))
        self.assertEqual("restatement_adjacency", unit["proof_association"]["method"])
        self.assertTrue(pc.proof_span_has_safe_boundary(paper, unit["proof"]["start_line"], unit["proof"]["end_line"]))
        self.assertFalse(any("Named proof heading" in value for value in result["warnings"]))

    def test_dynamic_restatable_is_a_source_located_limitation(self):
        _, result = self.scan("\\begin{lemma}A.\\end{lemma}\n\\begin{restatable}{\\kind}{copy}\nB.\n\\end{restatable}\n")
        self.assertTrue(any("Unsupported restatable declaration" in value and "paper.tex:3" in value for value in result["warnings"]))

    def test_cross_file_literal_proof_wrapper_uses_complete_boundary(self):
        paper, result = self.scan(
            "\\begin{lemma}\\label{lem:a}\nA.\n\\end{lemma}\n"
            "\\section{Appendix}\n\\begin{pf}[Proof of \\ref{lem:a}]\nA.\n\\end{pf}\n",
            "\\newenvironment{pf}[1][Proof]{\\begin{proof}[#1]}{\\end{proof}}\n",
        )
        proof = result["units"][0]["proof"]
        self.assertIsNotNone(proof)
        self.assertTrue(pc.proof_span_has_safe_boundary(paper, proof["start_line"], proof["end_line"], source_files=[paper, paper.with_name("defs.tex")]))
        self.assertFalse(pc.proof_span_has_safe_boundary(paper, proof["start_line"], proof["end_line"] - 1, source_files=[paper, paper.with_name("defs.tex")]))
        paper.write_text(paper.read_text(encoding="utf-8").replace("\\end{pf}", ""), encoding="utf-8")
        rescanned = pc.scan_formal_units(paper)
        self.assertIsNone(rescanned["units"][0]["proof"])
        self.assertTrue(any("Unclosed \\begin{pf}" in value for value in rescanned["warnings"]))
        self.assertFalse(pc.proof_span_has_safe_boundary(paper, proof["start_line"], proof["end_line"], source_files=[paper, paper.with_name("defs.tex")]))

    def test_inactive_or_redefined_wrapper_is_not_accepted(self):
        paper, _ = self.scan("", "\\iffalse\n\\newenvironment{inactive}{\\begin{proof}}{\\end{proof}}\n\\fi\n"
                             "\\newenvironment{changed}{\\begin{proof}}{\\end{proof}}\n"
                             "\\renewenvironment{changed}{An additional claim.}{Done.}\n")
        self.assertEqual({"proof"}, pc.proof_alias_names([paper.with_name("defs.tex")]))

    def fixture(self, *, environment="lemma", title="Lemma", wrapper=False, extra_environment=None):
        fixture = fixtures.FinalizationTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.definitions.write_text(
            f"\\newtheorem{{{environment}}}{{{title}}}\n" +
            (f"\\newtheorem{{{extra_environment[0]}}}{{{extra_environment[1]}}}\n" if extra_environment else "") +
            ("\\newenvironment{pf}{\\begin{proof}}{\\end{proof}}\n" if wrapper else ""),
            encoding="utf-8",
        )
        text = fixture.paper.read_text(encoding="utf-8").replace("{lemma}", "{" + environment + "}")
        if wrapper:
            text = text.replace("{proof}", "{pf}")
        if extra_environment:
            text += f"\\begin{{{extra_environment[0]}}}\\label{{context:a}}\nThe stated context holds.\n\\end{{{extra_environment[0]}}}\n"
        fixture.paper.write_text(text, encoding="utf-8")
        fixture.audit = fixture.base / "custom-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_scaffold(argparse.Namespace(paper=fixture.paper, output=fixture.audit, report_format="markdown"))
        manifest_path = fixture.audit / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        fixtures.write_json(manifest_path, manifest)
        # The shared historical fixture authors a fixed four-source-unit
        # ledger. Preserve those units while supplying the new source mapping.
        original_write = fixtures.write_json
        def write_with_source_mapping(path, data):
            if isinstance(data, dict) and "source_fragments" in data:
                for source_unit in data.get("source_units", []):
                    source_unit["source_span"] = pc.source_unit_location(data, source_unit)
            original_write(path, data)
        with mock.patch.object(fixtures, "write_json", side_effect=write_with_source_mapping):
            fixture.make_complete_audit()
        return fixture

    def test_assumption_and_definition_aliases_pass_actual_final_gate(self):
        for environment, title in (("ass", "Assumption"), ("defn", "Definition")):
            with self.subTest(environment=environment):
                fixture = self.fixture(extra_environment=(environment, title))
                manifest_path = fixture.audit / "AUDIT_MANIFEST.json"
                manifest = fixtures.read_json(manifest_path)
                manifest["audit_scope"]["critical_units"] = []
                manifest["audit_scope"]["excluded_units"] = [{"id": "context:a", "reason": "This standalone contextual declaration is outside the focused reflexivity claim and is not used by its proof."}]
                fixtures.write_json(manifest_path, manifest)
                report_path = fixture.audit / "audit/06_reports/FINAL_REPORT.md"
                report_path.write_text(report_path.read_text(encoding="utf-8").replace("- Results not checked: none", "- Results not checked: context:a"), encoding="utf-8")
                errors, _ = pc.check_audit_finalization(fixture.audit)
                self.assertEqual([], errors)

    def test_critical_priority_can_be_omitted_at_actual_final_gate(self):
        fixture = self.fixture()
        manifest_path = fixture.audit / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(manifest_path)
        manifest["audit_scope"].pop("critical_units")
        fixtures.write_json(manifest_path, manifest)
        ledger_path = fixture.audit / "audit/04_local_checks/lem-main.ledger.json"
        fixture.seal_schema5_challenge(ledger_path, fixtures.read_json(ledger_path))
        errors, _ = pc.check_audit_finalization(fixture.audit)
        self.assertEqual([], errors)

    def test_literal_proof_wrapper_passes_actual_final_gate(self):
        fixture = self.fixture(wrapper=True)
        errors, _ = pc.check_audit_finalization(fixture.audit)
        self.assertEqual([], errors)

    def test_ambiguous_classification_is_source_bound_at_actual_final_gate(self):
        fixture = self.fixture(environment="condition", title="Condition")
        inventory_path = fixture.audit / "audit/01_index/theorem_inventory.json"
        inventory = fixtures.read_json(inventory_path)
        unit = inventory["units"][0]
        unit["semantic_kind"] = "assumption"
        unit["proof_required"] = False
        fixtures.write_json(inventory_path, inventory)
        fixture.refresh_dependency_review()
        manifest_path = fixture.audit / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(manifest_path)
        override = {"unit_id": unit["id"], "kind": "environment_classification",
                    "parser_proof_required": True, "parser_semantic_kind": None,
                    "reviewed_proof_required": False, "reviewed_semantic_kind": "assumption",
                    "statement_sha256": pc.source_span_sha256(fixture.paper, 2, 4),
                    "environment_declaration": unit["environment_declaration"],
                    "reason": "The Condition environment introduces the stated standing condition.",
                    "evidence": "The exact locked statement is used as a condition; the separate argument verifies its consistency."}
        manifest["audit_scope"]["inventory_overrides"] = [override]
        fixtures.write_json(manifest_path, manifest)
        ledger_path = fixture.audit / "audit/04_local_checks/lem-main.ledger.json"
        fixture.seal_schema5_challenge(ledger_path, fixtures.read_json(ledger_path))
        errors, _ = pc.check_audit_finalization(fixture.audit)
        self.assertEqual([], errors)
        override["statement_sha256"] = "0" * 64
        fixtures.write_json(manifest_path, manifest)
        errors, _ = pc.check_audit_finalization(fixture.audit)
        self.assertTrue(any("statement_sha256 is stale" in error for error in errors), errors)

    def test_explicit_theorem_cannot_be_demoted_by_override(self):
        fixture = self.fixture(environment="thm", title="Theorem")
        path = fixture.audit / "audit/01_index/theorem_inventory.json"
        inventory = fixtures.read_json(path)
        unit = inventory["units"][0]
        unit["proof_required"] = False
        unit["semantic_kind"] = "assumption"
        fixtures.write_json(path, inventory)
        manifest_path = fixture.audit / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(manifest_path)
        manifest["audit_scope"]["inventory_overrides"] = [{
            "unit_id": unit["id"], "kind": "environment_classification",
            "reason": "Attempt to remove the declared theorem proof requirement.",
            "evidence": "The literal source declaration still names this as a theorem.",
            "parser_semantic_kind": "theorem", "parser_proof_required": True,
            "reviewed_semantic_kind": "assumption", "reviewed_proof_required": False,
            "statement_sha256": pc.source_span_sha256(fixture.paper, 2, 4),
            "environment_declaration": unit["environment_declaration"],
        }]
        fixtures.write_json(manifest_path, manifest)
        errors, _ = pc.check_audit_finalization(fixture.audit)
        self.assertTrue(any("explicit declared theorem role" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
