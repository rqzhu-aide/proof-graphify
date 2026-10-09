"""Read-only layout diagnostics do not establish mathematical completeness."""
from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck_source_check.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_source_layout_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)

STATEMENT = (
    "\\begin{proposition}[Two identities]\\label{prop:pair}\\label{thm:alias}\n"
    "$x=x$ and $y=y$.\n"
    "\\end{proposition}\n"
)
PROOF = "\\begin{proof}\nBy reflexivity.\n\\end{proof}\n"


class SourceLayoutCheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.paper = self.base / "paper.tex"

    def write(self, text, name="paper.tex"):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def check(self, **kwargs):
        args = argparse.Namespace(
            paper=self.paper, input_kind="latex", additional_source=None,
            fls=None, project_root=None,
        )
        for key, value in kwargs.items():
            setattr(args, key, value)
        return layout.check_source(args)

    def reasons(self, report):
        return {row["kind"] for row in report["results"][0]["review_reasons"]}

    def run_core(self, *argv):
        parser = layout.core()
        args = parser.build_parser().parse_args(list(map(str, argv)))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = args.func(args)
        return code, json.loads(output.getvalue())

    def test_ordinary_complete_proof_has_no_layout_flags_or_math_verdict(self):
        self.write(STATEMENT + PROOF)
        report = self.check()
        self.assertEqual("no_layout_flags", report["status"])
        row = report["results"][0]
        self.assertEqual('Proposition "Two identities"', row["result"])
        self.assertEqual({"file": "paper.tex", "start_line": 4, "end_line": 6},
                         row["recognized_proof"])
        self.assertEqual("accepted", row["boundary"]["status"])
        self.assertIn("may still omit part of an argument", report["limitation"])
        self.assertIn("have not been performed", report["limitation"])

    def test_detached_named_proof_keeps_exact_region(self):
        self.write(STATEMENT + "\\section{Discussion}\nSome context.\n"
                   "\\section{Proof of Proposition~\\ref{prop:pair}}\n" + PROOF)
        report = self.check()
        self.assertEqual("no_layout_flags", report["status"])
        self.assertEqual({"file": "paper.tex", "start_line": 7, "end_line": 9},
                         report["results"][0]["recognized_proof"])
        self.assertEqual([], report["results"][0]["candidate_headings"])

    def test_original_split_headings_report_one_result_and_both_alias_targets(self):
        self.write(STATEMENT +
                   "\\section{Complete identity in Proposition~\\ref{prop:pair}}\n" + PROOF +
                   "\\section{Finite identity in Proposition~\\ref{thm:alias}}\n"
                   "The second part follows by another calculation.\n")
        report = self.check()
        self.assertEqual("review_required", report["status"])
        self.assertEqual(1, report["proof_required_units"])
        self.assertIn("unrecognized_association", self.reasons(report))
        self.assertIn("target_heading_outside_proof", self.reasons(report))
        row = report["results"][0]
        self.assertIsNone(row["recognized_proof"])
        self.assertEqual([4, 8], [x["start_line"] for x in row["candidate_headings"]])
        self.assertEqual([["prop:pair"], ["thm:alias"]],
                         [x["target_labels"] for x in row["candidate_headings"]])
        self.assertIn("does not establish that a proof is missing", row["review_reasons"][0]["cause"])

    def test_recognized_first_part_does_not_hide_later_alias_heading(self):
        self.write(STATEMENT + PROOF +
                   "\\section{Finite identity in Proposition~\\ref{thm:alias}}\n"
                   "The second identity needs a further argument.\n")
        report = self.check()
        row = report["results"][0]
        self.assertEqual("review_required", report["status"])
        self.assertEqual("accepted", row["boundary"]["status"])
        self.assertEqual({"target_heading_outside_proof"}, self.reasons(report))
        self.assertEqual(7, row["candidate_headings"][0]["start_line"])

    def test_multiple_named_proof_environments_retain_parser_warning(self):
        named = ("\\begin{proof}[Proof of Proposition~\\ref{prop:pair}]\n"
                 "By reflexivity.\n\\end{proof}\n")
        self.write(STATEMENT + named + named)
        report = self.check()
        self.assertEqual("review_required", report["status"])
        self.assertTrue(any("Multiple named proofs target prop:pair" in warning
                            for warning in report["parser_warnings"]), report)
        self.assertEqual(4, report["results"][0]["recognized_proof"]["start_line"])
        self.assertEqual(6, report["results"][0]["recognized_proof"]["end_line"])
        self.assertIn("Multiple named proofs target Proposition", layout.markdown(report))

    def test_inactive_fake_headings_do_not_create_layout_flags(self):
        self.write(STATEMENT + PROOF +
                   "% \\section{Proof of \\ref{prop:pair}}\n"
                   "\\iffalse\n\\section{Finite identity of \\ref{thm:alias}}\n"
                   "\\begin{proof}[Proof of \\ref{prop:pair}]\nFake.\n\\end{proof}\n\\fi\n"
                   "\\newcommand{\\unused}{\\section{Proof of \\ref{prop:pair}}}\n")
        report = self.check()
        self.assertEqual("no_layout_flags", report["status"], report)
        self.assertEqual([], report["results"][0]["candidate_headings"])

    def test_additional_source_defines_proof_wrapper_for_boundary_checker(self):
        definitions = self.write(
            "\\newenvironment{pf}[1][Proof]{\\begin{proof}[#1]}{\\end{proof}}\n",
            "definitions.tex",
        )
        self.write(STATEMENT + "\\section{Appendix}\n"
                   "\\begin{pf}[Proof of \\ref{prop:pair}]\nBy reflexivity.\n\\end{pf}\n")
        report = self.check(additional_source=[
            (definitions, "Literal proof wrapper declaration.", "The appendix uses the pf environment.")
        ])
        self.assertEqual("no_layout_flags", report["status"], report)
        self.assertEqual({"paper.tex", "definitions.tex"},
                         {row["file"] for row in report["source_files"]})
        self.assertEqual("accepted", report["results"][0]["boundary"]["status"])
        self.assertEqual(7, report["results"][0]["recognized_proof"]["end_line"])

    def test_duplicate_statement_label_does_not_supply_alias_heading_hint(self):
        self.write(STATEMENT + PROOF +
                   "\\begin{lemma}\\label{thm:alias}\n$z=z$.\n\\end{lemma}\n" + PROOF +
                   "\\section{Identity in \\ref{thm:alias}}\nDiscussion.\n")
        report = self.check()
        # Ambiguous label ownership cannot be used to locate a continuation.
        self.assertTrue(all(not row["candidate_headings"] for row in report["results"]))
        self.assertEqual("review_required", report["status"])
        self.assertEqual("thm:alias", report["layout_warnings"][0]["label"])
        self.assertEqual(2, len(report["layout_warnings"][0]["locations"]))

    def test_raw_pdf_and_empty_transcription_fail_without_a_success_status(self):
        for name, text, kind in (("paper.pdf", "%PDF-1.7", "latex"),
                                 ("empty.txt", " \n", "pdf_transcription")):
            with self.subTest(name=name):
                path = self.write(text, name)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = layout.main(["--paper", str(path), "--input-kind", kind, "--format", "json"])
                report = json.loads(output.getvalue())
                self.assertEqual(1, code)
                self.assertEqual("check_failed", report["status"])
                self.assertIn("have not been performed", report["limitation"])

    def test_plain_transcription_with_no_formal_units_requires_review(self):
        text = self.write("Proposition: x equals x. Proof: reflexivity.\n", "transcription.txt")
        report = self.check(paper=text, input_kind="pdf_transcription")
        self.assertEqual("review_required", report["status"])
        self.assertEqual(0, report["proof_required_units"])
        self.assertTrue(report["parser_warnings"])
        self.assertIn("No proof obligations were recognized", layout.markdown(report))

    def test_accepted_analyzer_region_must_equal_the_entire_inventory_span(self):
        self.write(STATEMENT + PROOF + "An additional unwrapped calculation.\n")
        parser = layout.core()
        inventory = parser.scan_formal_units(self.paper)
        baseline = inventory["units"][0]["proof"]
        self.assertEqual((4, 6), (baseline["start_line"], baseline["end_line"]))
        widened = copy.deepcopy(inventory)
        widened["units"][0]["proof"]["end_line"] = 7
        # Keep the real boundary analyzer. A future scanner mismatch must not
        # turn its accepted 4-6 response into acceptance of an inventory 4-7.
        with mock.patch.object(parser, "scan_formal_units", return_value=widened):
            report = self.check()
        self.assertEqual("review_required", report["status"])
        self.assertIn("unsupported_boundary", self.reasons(report))
        self.assertEqual("accepted", report["results"][0]["boundary"]["status"])
        self.assertEqual(6, report["results"][0]["boundary"]["end_line"])

    def test_checks_leave_all_source_and_existing_audit_files_unchanged(self):
        self.write("\\input{statement}\n\\input{appendix}\n")
        self.write(STATEMENT, "statement.tex")
        self.write("\\section{Proof of \\ref{prop:pair}}\n" + PROOF, "appendix.tex")
        self.write('{"preserve": true}\n', "proofcheck-audit/AUDIT_MANIFEST.json")
        self.write("Do not overwrite the reviewed audit.\n", "proofcheck-audit/audit/report.md")

        def snapshot():
            return {path.relative_to(self.base).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in self.base.rglob("*") if path.is_file()}

        before = snapshot()
        first = self.check()
        second = self.check()
        self.assertEqual("no_layout_flags", first["status"], first)
        self.assertEqual(first, second)
        self.assertEqual(before, snapshot())

    def test_colliding_generated_ids_survive_setup_and_portable_relocation(self):
        self.write("\\input{a/result}\n\\input{b/result}\n\\input{single}\n")
        unlabeled = "\\begin{theorem}\n$x=x$.\n\\end{theorem}\n" + PROOF
        self.write(unlabeled, "a/result.tex")
        self.write(unlabeled, "b/result.tex")
        self.write(unlabeled, "single.tex")
        report = self.check()
        expected = {"theorem:a/result.tex:1", "theorem:b/result.tex:1", "theorem:single.tex:1"}
        self.assertEqual("no_layout_flags", report["status"], report)
        self.assertEqual(expected, {row["unit_id"] for row in report["results"]})
        for row in report["results"]:
            self.assertEqual(row["statement"]["file"], row["recognized_proof"]["file"])
        audit = self.base / "audit"
        code, doctor = self.run_core("doctor", "--paper", self.paper, "--output", audit,
                                     "--input-kind", "latex", "--portable-sources")
        self.assertEqual((0, True), (code, doctor["ready"]), doctor)
        code, _ = self.run_core("scaffold", "--paper", self.paper, "--output", audit,
                                "--input-kind", "latex", "--portable-sources")
        self.assertEqual(0, code)
        relocated = self.base / "relocated" / "audit"
        shutil.copytree(audit, relocated)
        for root in (audit, relocated):
            code, status = self.run_core("status", "--root", root)
            self.assertEqual(0, code, status)
            self.assertEqual([], status["structural_errors"], status)
            inventory = layout.core().scan_formal_units(root / "audit/00_sources/project/paper.tex")
            self.assertEqual(expected, {unit["id"] for unit in inventory["units"]})
            self.assertEqual(expected, {unit["proof_association"]["target"] for unit in inventory["units"]})

    def test_duplicate_explicit_ids_fail_early_with_both_locations(self):
        self.write("\\input{a/result}\n\\input{b/result}\n")
        for name in ("a/result.tex", "b/result.tex"):
            self.write(STATEMENT + PROOF, name)
        with self.assertRaisesRegex(ValueError, "Duplicate proof-unit identity") as caught:
            self.check()
        for location in ("a/result.tex:1", "b/result.tex:1"):
            self.assertIn(location, str(caught.exception))
        audit = self.base / "audit"
        code, doctor = self.run_core("doctor", "--paper", self.paper, "--output", audit,
                                     "--input-kind", "latex", "--portable-sources")
        self.assertNotEqual(0, code)
        self.assertFalse(doctor["ready"])
        self.assertIn("a/result.tex:1", doctor["source_discovery"]["error"])
        with self.assertRaisesRegex(ValueError, "Cannot create audit"):
            self.run_core("scaffold", "--paper", self.paper, "--output", audit,
                          "--input-kind", "latex", "--portable-sources")
        self.assertFalse(audit.exists())
        self.assertEqual([], list(self.base.glob("*.proofcheck.stage")))

    def test_generated_collision_does_not_rename_explicit_label(self):
        self.write("\\input{a/result}\n\\input{named}\n")
        self.write("\\begin{theorem}\n$x=x$.\n\\end{theorem}\n" + PROOF, "a/result.tex")
        self.write("\\begin{lemma}\\label{theorem:result.tex:1}\n$x=x$.\n\\end{lemma}\n" + PROOF, "named.tex")
        report = self.check()
        self.assertEqual("no_layout_flags", report["status"], report)
        self.assertEqual({"theorem:a/result.tex:1", "theorem:result.tex:1"},
                         {row["unit_id"] for row in report["results"]})

    def test_content_after_end_document_requires_explicit_source_selection(self):
        original = (STATEMENT + PROOF + "\\end{document}\n"
                    "\\begin{theorem}\\label{thm:abandoned}\n$z=z$.\n\\end{theorem}\n" + PROOF)
        self.write(original)
        report = self.check()
        self.assertEqual("review_required", report["status"], report)
        self.assertEqual(2, report["proof_required_units"])
        warning = next(row for row in report["parser_warnings"] if "content follows" in row)
        self.assertIn("paper.tex:7:1", warning)
        self.assertIn("explicit scope exclusions", warning)
        self.assertIn("\\end{document}", layout.markdown(report))
        self.assertEqual(original, self.paper.read_text(encoding="utf-8"))

    def test_includeonly_is_reviewed_before_audit_scope_is_chosen(self):
        self.write("\\includeonly{live}\n\\include{live}\n\\include{unused}\n")
        self.write(STATEMENT + PROOF, "live.tex")
        self.write("\\begin{lemma}\\label{lem:unused}\n$x=x$.\n\\end{lemma}\n" + PROOF, "unused.tex")
        report = self.check()
        self.assertEqual("review_required", report["status"], report)
        self.assertEqual(2, report["proof_required_units"])
        warnings = [row for row in report["parser_warnings"] if "\\includeonly" in row]
        self.assertEqual(1, len(warnings))
        self.assertIn("paper.tex:1:1", warnings[0])
        self.assertIn("selected build or the full manuscript", warnings[0])
        audit = self.base / "audit"
        _, doctor = self.run_core("doctor", "--paper", self.paper, "--output", audit,
                                   "--input-kind", "latex", "--portable-sources")
        self.assertIn(warnings[0], doctor["source_discovery"]["warnings"])
        self.run_core("scaffold", "--paper", self.paper, "--output", audit,
                      "--input-kind", "latex", "--portable-sources")
        manifest = json.loads((audit / "AUDIT_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertIn(warnings[0], manifest["parser_warnings"])
        self.assertFalse(manifest["completion"]["parser_warnings_reviewed"])
        self.assertEqual({"prop:pair", "lem:unused"},
                         {unit["id"] for unit in layout.core().scan_formal_units(audit / "audit/00_sources/project/paper.tex")["units"]})
        _, status = self.run_core("status", "--root", audit)
        self.assertEqual([], status["structural_errors"], status)
        self.assertEqual("NONFINAL", status["delivery_status"])

    def test_source_controls_in_masked_or_escaped_text_do_not_trigger_selection(self):
        inert = (
            "% \\includeonly{unused} \\end{document}\n"
            "\\verb|\\includeonly{unused} \\end{document}|\n"
            "\\begin{verbatim}\n\\includeonly{unused}\n\\end{document}\n\\end{verbatim}\n"
            "\\newcommand{\\draft}{\\includeonly{unused}\\end{document}}\n"
            "\\iffalse\n\\includeonly{unused}\n\\end{document}\n\\fi\n"
            "\\iftrue\nActive.\n\\else\n\\includeonly{unused}\\end{document}\n\\fi\n"
            "\\\\includeonly{unused} \\\\end{document}\n"
        )
        self.write(inert + STATEMENT + PROOF + "\\end{document}\n% final comment\n")
        report = self.check()
        self.assertEqual("no_layout_flags", report["status"], report)
        self.assertFalse(any("source selection" in warning for warning in report["parser_warnings"]))
        self.assertEqual(1, report["proof_required_units"])

    def test_active_and_dynamic_includeonly_selections_are_not_silently_ignored(self):
        for control in ("\\iftrue\n\\includeonly{live}\n\\fi\n",
                        "\\includeonly{\\selected}\n", "\\includeonly\\selected\n"):
            with self.subTest(control=control):
                self.write(control + STATEMENT + PROOF)
                report = self.check()
                self.assertEqual("review_required", report["status"], report)
                self.assertTrue(any("\\includeonly" in row for row in report["parser_warnings"]))


if __name__ == "__main__":
    unittest.main()
