from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fragment_proofcheck", ROOT / "scripts/proofcheck.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


class SourceFragmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paper = self.root / "paper.tex"
        self.paper.write_text("\\begin{lemma}\\label{lem:mean}\nA claimed mean identity.\n\\end{lemma}\n"
                              "\\begin{proof}\n\\input{parts/body}\n\\end{proof}\n", encoding="utf-8")
        (self.root / "parts").mkdir()
        self.body = self.root / "parts/body.tex"
        self.body.write_text("By \\cite{false-source}, $0=1$.\n\\input{parts/nested}\n", encoding="utf-8")
        self.nested = self.root / "parts/nested.tex"
        self.nested.write_text("Thus \\ref{lem:other} implies the claimed identity.\n", encoding="utf-8")
        self.output = self.root / "mean.skeleton.json"

    def extract(self, *, start=1, end=6):
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_extract(argparse.Namespace(file=self.paper, output=self.output, start=start, end=end,
                unit_id="lem:mean", force=True, statement_start=1, statement_end=3,
                statement_file=None, separate_statement_reason="The formal statement is locked separately."))
        return json.loads(self.output.read_text(encoding="utf-8"))

    def members(self):
        return [(path, {"file": path.name, "sha256": pc.sha256_file(path)})
                for path in (self.paper, self.body, self.nested)]

    def test_nested_expansion_preserves_every_original_line_and_coverage(self):
        ledger = self.extract()
        self.assertEqual(ledger["source"]["end_line"], 6)
        self.assertEqual(pc.source_coverage_bounds(ledger), (1, 9))
        self.assertEqual(len(ledger["source_lines"]), 9)
        self.assertEqual([row["text"] for row in ledger["source_lines"]][5:8], [
            "By \\cite{false-source}, $0=1$.", "\\input{parts/nested}",
            "Thus \\ref{lem:other} implies the claimed identity."])
        false_unit = ledger["source_units"][5]
        self.assertEqual(pc.source_unit_location(ledger, false_unit),
                         {"file": "parts/body.tex", "start_line": 1, "end_line": 1})
        self.assertEqual(ledger["source_units"][4]["kind"], "non_substantive")
        self.assertEqual(ledger["source_lines"][4]["text"], "\\input{parts/body}")
        self.assertTrue(ledger["source_lines"][4]["include_directive"])
        ledger["source_units"].pop(5)
        pc.atomic_write_json(self.output, ledger)
        errors, _ = pc.check_ledger_data(self.output, True)
        self.assertTrue(any("Uncovered source-unit lines: 6" in error for error in errors), errors)

    def test_packet_and_blinded_source_index_include_false_assertion_and_nested_reference(self):
        self.extract()
        span = pc.packet_span(self.root, self.root,
            {"file": "paper.tex", "start_line": 4, "end_line": 6}, self.members())
        source_spans = pc.challenge_source_spans({"source": {"proof": span}})
        quotes = ["\n".join(row["text"] for row in item["lines"]) for item in source_spans.values()]
        self.assertTrue(any("$0=1$" in quote and "false-source" in quote for quote in quotes))
        self.assertTrue(any("lem:other" in quote for quote in quotes))
        self.assertTrue(any("fragments" in pointer for pointer in source_spans))
        evidence = pc.scan_span_evidence(self.paper, 4, 6, self.root)
        self.assertEqual(evidence["citations"], ["false-source"])
        self.assertEqual(evidence["dependencies"], ["lem:other"])
        self.assertEqual(evidence["reference_occurrences"][0]["file"], "parts/nested.tex")

    def test_original_coordinates_in_live_and_archived_step_projection(self):
        ledger = self.extract()
        ledger["steps"] = [{"id": "S001", "source_unit_id": "U006"}]
        pc.atomic_write_json(self.output, ledger)
        archived = pc.archived_ledger_step_projection(ledger, "S001")
        live = pc.ledger_step_projection({"ledger": str(self.output)}, "S001")
        for result in (archived, live):
            self.assertEqual(result["file"], "parts/body.tex")
            self.assertEqual(result["start_line"], 1)
            self.assertIn("$0=1$", result["quote"])
        anchor = pc.packet_issue_step_anchor(self.root, self.output, ledger, ledger["steps"][0], self.members())
        self.assertEqual(anchor["source_member"]["name"], "body.tex")
        self.assertEqual(anchor["start_line"], 1)

    def test_wrapper_only_legacy_lock_cannot_be_ready(self):
        ledger = self.extract(start=4)
        del ledger["source_fragments"]
        with self.assertRaisesRegex(ValueError, "wrapper-only ledger omits included source"):
            pc.source_fragment_support().current(pc.report_api(), ledger, self.root)
        readiness = pc.packet_semantic_readiness(self.output, ledger, "lem:mean")
        self.assertFalse(readiness["ready"])
        self.assertIn("re-extract", " ".join(readiness["reasons"]))

    def test_child_drift_and_forged_structural_flags_fail_source_lock(self):
        ledger = self.extract()
        for mutation in (lambda value: value["source_lines"][5].update(include_directive=True),
                         lambda value: value["source_fragments"]["fragments"].pop()):
            candidate = copy.deepcopy(ledger)
            mutation(candidate)
            with self.assertRaisesRegex(ValueError, "stale or incomplete"):
                pc.source_fragment_support().current(pc.report_api(), candidate, self.root)
        self.body.write_text("Changed claimed identity.\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale or incomplete"):
            pc.source_fragment_support().current(pc.report_api(), ledger, self.root)

    def test_source_groups_cannot_claim_cross_file_physical_continuity(self):
        ledger = self.extract()
        with self.assertRaisesRegex(ValueError, "included-source boundary"):
            pc.build_compiled_source_units(ledger, [{"lines": [5, 6], "kind": "continued_sentence",
                "partition_evidence": "This claimed grouping improperly spans the inclusion boundary."}])

    def test_dynamic_missing_inline_and_cycle_are_actionable_errors(self):
        for body, expected in ((r"\input{\bodyfile}", "dynamic"), (r"\input{missing}", "missing"),
                               (r"We claim \input{parts/body} now.", "own line"),
                               (r"\input{paper}", "cycle")):
            with self.subTest(body=body):
                self.paper.write_text("\\begin{lemma}\nClaim.\n\\end{lemma}\n\\begin{proof}\n" + body + "\n\\end{proof}\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, expected):
                    self.extract()
                with self.assertRaisesRegex(ValueError, "Incomplete included proof"):
                    pc.packet_span(self.root, self.root, {"file": "paper.tex", "start_line": 4, "end_line": 6}, self.members())

    def test_plain_single_file_records_keep_original_format(self):
        self.paper.write_text("\\begin{lemma}\nClaim.\n\\end{lemma}\n\\begin{proof}\nArgument.\n\\end{proof}\n", encoding="utf-8")
        ledger = self.extract()
        self.assertNotIn("source_fragments", ledger)
        self.assertEqual(set(ledger["source_lines"][0]), {"line", "sha256", "text"})
        self.assertNotIn("source_span", ledger["source_units"][0])
        self.assertEqual(pc.source_fragment_support().current(pc.report_api(), ledger, self.root), self.paper.read_text().splitlines())

    def test_included_statement_is_locked_and_missing_statement_fragment_is_rejected(self):
        self.paper.write_text("\\begin{lemma}\n\\input{parts/body}\n\\end{lemma}\n\\begin{proof}\nArgument.\n\\end{proof}\n", encoding="utf-8")
        ledger = self.extract()
        spans = ledger["obligation"]["statement_spans"]
        self.assertEqual(len(spans), 3)
        binding = {"statement": {"file": "paper.tex", "start_line": 1, "end_line": 3},
                   "proof": {"file": "paper.tex", "start_line": 4, "end_line": 6}}
        self.assertEqual(pc.packet_inventory_binding_errors(self.root, binding, self.output, ledger), [])
        spans.pop()
        self.assertTrue(any("omits included statement" in error for error in
                            pc.packet_inventory_binding_errors(self.root, binding, self.output, ledger)))

    def test_included_local_labels_keep_owner_and_closing_order(self):
        self.body.write_text("$0=1$.\\label{eq:bad}\n\\input{parts/nested}\n", encoding="utf-8")
        self.nested.write_text("By \\ref{eq:bad}, Lemma~\\ref{lem:mean} follows.\n", encoding="utf-8")
        inventory = pc.scan_formal_units(self.paper)
        self.assertEqual(inventory["label_owners"]["eq:bad"]["owner_unit_id"], "lem:mean")
        evidence = pc.scan_span_evidence(self.paper, 4, 6, self.root)
        occurrences = evidence["reference_occurrences"]
        self.assertEqual(occurrences[-1]["line"], 1)
        self.assertGreater(occurrences[-1]["source_position"], 4)

    def test_macro_hidden_and_repeated_inclusion_do_not_silently_lose_argument(self):
        self.paper.write_text("\\newcommand{\\proofbody}{\\input{parts/body}}\n\\begin{lemma}\nClaim.\n\\end{lemma}\n\\begin{proof}\n\\proofbody\n\\end{proof}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hides an inclusion"):
            pc.source_fragment_support().expand(pc.report_api(), self.paper, 5, 7, self.root)
        self.paper.write_text("\\begin{proof}\n\\input{parts/nested}\n\\input{parts/nested}\n\\end{proof}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "repeated inclusion"):
            pc.source_fragment_support().expand(pc.report_api(), self.paper, 1, 4, self.root)

    def test_unreadable_auxiliary_context_retains_warning_without_hiding_required_body(self):
        style = self.root / "unreadable.sty"
        style.write_bytes(b"\\ProvidesPackage{unreadable}\n\xff\xfe\n")
        self.paper.write_text(self.paper.read_text(encoding="utf-8") +
                              "\\usepackage{./unreadable}\n", encoding="utf-8")
        ledger = self.extract()
        self.assertIn("$0=1$", "\n".join(row["text"] for row in ledger["source_lines"]))
        closure = pc.discover_source_closure(self.paper)
        self.assertIn(style, closure["files"])
        self.assertTrue(any("Cannot decode" in warning and "unreadable.sty" in warning
                            for warning in closure["warnings"]))
        # Decoding uncertainty in an actual included argument is not optional
        # auxiliary context: extraction must fail, rather than dropping it.
        self.body.write_bytes(b"Claimed included argument.\n\xff\xfe\n")
        with self.assertRaises(pc.TextArtifactReadError):
            self.extract()


if __name__ == "__main__":
    unittest.main()
