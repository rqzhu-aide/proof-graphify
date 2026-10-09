from __future__ import annotations

import argparse
import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path

import test_compile_annotations as fixtures


proofcheck = fixtures.proofcheck


class StatementLabelPremiseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "paper.tex"
        self.source.write_text(
            "\\begin{lemma}\\label{lem:pair}\n"
            "For real x and y, x=x and y=y. \\label{eq:pair}\n"
            "\\end{lemma}\n"
            "\\begin{proof}\n"
            "Reflexivity gives x=x.\n"
            "Reflexivity gives y=y.\n"
            "Add the equalities in \\eqref{eq:pair}.\n"
            "\\end{proof}\n",
            encoding="utf-8",
        )
        span = proofcheck.locked_span(self.source, 2, 2, self.base)
        self.ledger = {
            "unit_id": "lem:pair",
            "source": {"file": "paper.tex"},
            "obligation": {
                "statement_spans": [proofcheck.locked_span(self.source, 1, 3, self.base)],
                "conclusions": [
                    {"id": "C001", "claim": "x equals x", "source_spans": [span]},
                    {"id": "C002", "claim": "y equals y", "source_spans": [copy.deepcopy(span)]},
                ],
            },
            "review": {"conclusion_results": [
                {"conclusion_id": "C001", "support": {"step_id": "S002", "move_id": "M001"}},
                {"conclusion_id": "C002", "support": {"step_id": "S003", "move_id": "M001"}},
            ]},
        }
        self.claims = {"S002": "x equals x", "S003": "y equals y"}
        self.ranges = {"S002": (5, 5), "S003": (6, 6)}

    def check(self, references: tuple[str, ...] = ("S002",), **overrides) -> list[str]:
        premises = [
            {"id": f"P{index:03d}", "role": "fact", "claim": self.claims[reference],
             "origin": {"kind": "prior_step", "reference": reference},
             "evidence": "The earlier reflexivity derivation establishes this coordinate equality.",
             "source_reference_id": "eq:pair",
             "source_reference_occurrence_id": "R-0123456789abcdef"}
            for index, reference in enumerate(references, 1)
        ]
        args = {
            "value": premises, "prefix": "S004", "obligation": self.ledger["obligation"],
            "ledger_dir": self.base,
            "dependencies_by_id": {reference: {"kind": "step", "needed_form": self.claims[reference]}
                                   for reference in references},
            "prior_step_statuses": {reference: "verified" for reference in self.claims},
            "prior_step_kinds": {reference: "conclusion" for reference in self.claims},
            "prior_step_claims": self.claims, "prior_step_ranges": self.ranges,
            "prior_step_conclusion_moves": {reference: "M001" for reference in self.claims},
            "source_path": self.source, "final": True, "source_ledger": self.ledger,
        }
        args.update(overrides)
        errors: list[str] = []
        proofcheck.validate_premise_uses(**args, errors=errors)
        return errors

    def assert_anchor_rejected(self) -> None:
        errors = self.check()
        self.assertTrue(any("source_reference_id eq:pair is not active" in error for error in errors), errors)

    def test_statement_label_resolves_to_earlier_establishing_move(self) -> None:
        self.assertEqual([], self.check())

    def test_shared_label_resolves_two_separate_conclusions(self) -> None:
        self.assertEqual([], self.check(("S002", "S003")))

    def test_wrong_support_step_or_move_is_rejected(self) -> None:
        support = self.ledger["review"]["conclusion_results"][0]["support"]
        for field, wrong in (("step_id", "S003"), ("move_id", "M002")):
            with self.subTest(field=field):
                original = support[field]
                support[field] = wrong
                self.assert_anchor_rejected()
                support[field] = original

    def test_missing_or_duplicate_conclusion_support_is_rejected(self) -> None:
        results = self.ledger["review"]["conclusion_results"]
        first = results.pop(0)
        self.assert_anchor_rejected()
        results.extend([first, copy.deepcopy(first)])
        self.assert_anchor_rejected()

    def test_label_on_different_conclusion_does_not_bind(self) -> None:
        self.ledger["obligation"]["conclusions"][0]["claim"] = "x is positive"
        self.assert_anchor_rejected()

    def test_future_and_self_support_do_not_bypass_prior_order(self) -> None:
        for reference in ("S004", "S005"):
            with self.subTest(reference=reference):
                self.claims[reference] = "x equals x"
                self.ledger["review"]["conclusion_results"][0]["support"]["step_id"] = reference
                errors = self.check(
                    (reference,), prior_step_statuses={"S002": "verified"},
                    prior_step_claims={"S002": "x equals x"},
                    prior_step_conclusion_moves={"S002": "M001"},
                )
                self.assertTrue(any("is not established before use" in error for error in errors), errors)

    def test_statement_and_noninferential_steps_remain_invalid_premises(self) -> None:
        errors = self.check(prior_step_kinds={"S002": "statement"})
        self.assertTrue(any("cannot use the theorem statement step" in error for error in errors), errors)
        errors = self.check(prior_step_conclusion_moves={"S002": None})
        self.assertTrue(any("cannot use non-inferential or unsupported step" in error for error in errors), errors)

    def test_inactive_or_commented_statement_label_is_rejected(self) -> None:
        original = self.source.read_text(encoding="utf-8")
        for replacement in (r"% \label{eq:pair}", r"\iffalse\label{eq:pair}\fi"):
            with self.subTest(replacement=replacement):
                self.source.write_text(original.replace(r"\label{eq:pair}", replacement), encoding="utf-8")
                self.ledger["obligation"]["conclusions"][0]["source_spans"] = [
                    proofcheck.locked_span(self.source, 2, 2, self.base)
                ]
                self.assert_anchor_rejected()

    def test_stale_statement_conclusion_span_is_rejected(self) -> None:
        self.ledger["obligation"]["conclusions"][0]["source_spans"][0]["sha256"] = "0" * 64
        self.assert_anchor_rejected()

    def test_foreign_statement_label_is_rejected(self) -> None:
        other = self.base / "other.tex"
        other.write_text("x=x. \\label{eq:pair}\n", encoding="utf-8")
        self.ledger["obligation"]["conclusions"][0]["source_spans"] = [
            proofcheck.locked_span(other, 1, 1, self.base)
        ]
        self.assert_anchor_rejected()

    def test_original_proof_local_label_path_remains_valid(self) -> None:
        self.source.write_text(self.source.read_text(encoding="utf-8").replace(r"\label{eq:pair}", "").replace(
            "Reflexivity gives x=x.", "Reflexivity gives x=x. \\label{eq:pair}"
        ), encoding="utf-8")
        self.ledger["review"]["conclusion_results"] = []
        self.assertEqual([], self.check())


class StatementLabelCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.CompileAnnotationsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.annotations = self.fixture.annotations()
        obligation = copy.deepcopy(fixtures.read_json(self.fixture.ledger)["obligation"])
        self.fixture.paper = self.fixture.base / "statement equation.tex"
        self.fixture.paper.write_text(
            "\\begin{theorem}\\label{lem:compact}\n"
            "For every real $x$,\n"
            "\\begin{equation}\\label{eq:double}\n"
            "  2x=x+x.\n"
            "\\end{equation}\n"
            "Moreover, $|2x|\\leq 2|x|$.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Distributivity gives $2x=(1+1)x=x+x$.\n"
            "Using \\eqref{eq:double}, the triangle inequality gives\n"
            "$|2x|=|x+x|\\leq |x|+|x|=2|x|$.\n"
            "\\end{proof}\n", encoding="utf-8",
        )
        self.fixture.audit = self.fixture.base / "statement equation audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(argparse.Namespace(paper=self.fixture.paper, output=self.fixture.audit))
        self.fixture.ledger = self.fixture.audit / "audit/04_local_checks/unit.skeleton.json"
        self.fixture.output = self.fixture.ledger.with_name("unit.ledger.json")
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(argparse.Namespace(
                file=self.fixture.paper, start=1, end=12, statement_file=self.fixture.paper,
                statement_start=1, statement_end=7, separate_statement_reason=None,
                unit_id="lem:compact", output=self.fixture.ledger, force=False,
            ))
        skeleton = fixtures.read_json(self.fixture.ledger)
        obligation["statement_spans"] = skeleton["obligation"]["statement_spans"]
        obligation["conclusion"] = "2x equals x+x and |2x| is at most 2|x|"
        next(row for row in obligation["normalization_checks"] if row["aspect"] == "conclusion")["evidence"] = (
            "The normalized conclusions retain the displayed doubling identity and its absolute-value bound."
        )
        first = obligation["conclusions"][0]
        first["claim"] = "2x equals x+x"
        first["source_spans"] = [proofcheck.locked_span(self.fixture.paper, 3, 5, self.fixture.ledger.parent)]
        first["normalization"]["evidence"] = "The labeled display states exactly the real scalar identity 2x=x+x."
        second = copy.deepcopy(first)
        second.update(id="C002", claim="|2x| is at most 2|x|",
                      source_spans=[proofcheck.locked_span(self.fixture.paper, 6, 6, self.fixture.ledger.parent)])
        second["normalization"]["evidence"] = "The moreover clause gives exactly the absolute-value bound with constant two."
        obligation["conclusions"].append(second)
        skeleton["obligation"] = obligation
        fixtures.write_json(self.fixture.ledger, skeleton)
        manifest_path = self.fixture.audit / "AUDIT_MANIFEST.json"
        manifest = fixtures.read_json(manifest_path)
        manifest["audit_scope"].update(status="reviewed", target_units=["lem:compact"],
                                       in_scope_units=["lem:compact"], critical_units=[])
        fixtures.write_json(manifest_path, manifest)
        registry_path = self.fixture.audit / "audit/03_dependencies/DEPENDENCY_REGISTRY.json"
        registry = fixtures.read_json(registry_path)
        registry["review"] = {
            "status": "reviewed", "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            "inventory_sha256": proofcheck.sha256_file(self.fixture.audit / "audit/01_index/theorem_inventory.json"),
            "in_scope_units": ["lem:compact"], "evidence": ["The identity and bound follow by distributivity and triangle inequality; no foreign result is used."],
        }
        fixtures.write_json(registry_path, registry)
        fixtures.install_calibration(self.fixture.audit)
        self.fixture.packet = self.fixture.base / "statement equation packet.json"
        self.fixture.regenerate_packet()
        packet = fixtures.read_json(self.fixture.packet)
        self.annotations.update(
            source_unit_sha256=skeleton["source"]["unit_sha256"],
            obligation_sha256=proofcheck.canonical_sha256(obligation),
            context_binding_sha256=packet["context_binding_sha256"],
            calibration_receipt_sha256=packet["context_binding"]["calibration_receipt_sha256"],
        )
        statement, establish = self.annotations["steps"]
        self.annotations["source_groups"] = [
            {"lines": [1, 7], "kind": "continued_sentence",
             "partition_evidence": "Lines 1-7 are the full formal statement, including its labeled identity and moreover clause."},
            {"lines": [10, 11], "kind": "continued_sentence",
             "partition_evidence": "The triangle-inequality sentence starts on line 10 and its formula completes on line 11."},
        ]
        statement.update(lines=[1, 7], claim="For every real x, 2x equals x+x and |2x| is at most 2|x|.",
                         literal="The statement contains a labeled doubling identity followed by its absolute-value bound.")
        establish.update(lines=[9, 9], claim="2x equals x+x", goal="Establish the labeled doubling identity.",
                         literal="Line 9 distributes x over 1+1 to obtain 2x=x+x.",
                         atomicity_evidence="Distributivity supplies the one stated scalar identity.",
                         adversarial=["Distributivity applies to every real x, including zero and negative values."],
                         rule="Distributivity", justification="Since 2=1+1, distributivity gives 2x=x+x.")
        establish["inputs"][0].pop("source_reference_id")
        establish["inputs"][0].pop("source_reference_occurrence_id")
        use = copy.deepcopy(establish)
        occurrence = packet["inventory"]["reference_occurrences"][0]
        use.update(
            key="triangle", lines=[10, 11], kind="inequality", claim="|2x| is at most 2|x|",
            goal="Bound the absolute value using the established doubling identity.",
            literal="Lines 10-11 use the previously proved identity and apply triangle inequality to x+x.",
            atomicity_evidence="Triangle inequality bounds the sum of the same two real scalars.",
            rule="Triangle inequality", justification="The established identity gives |2x|=|x+x|, bounded by |x|+|x|=2|x|.",
            inputs=[{"kind": "prior_step", "reference": "conclusion", "role": "fact",
                     "evidence": "Distributivity already established the labeled doubling identity.",
                     "compatibility_check": "The same arbitrary real x is used in the same exact equality.",
                     "source_reference_id": occurrence["target"],
                     "source_reference_occurrence_id": occurrence["occurrence_id"]}],
        )
        use["risks"]["sign"] = {"status": "passed", "evidence": "Absolute values are nonnegative and triangle inequality has the displayed upper-bound direction."}
        use["risks"]["constant"] = {"status": "passed", "evidence": "The two equal terms |x|+|x| give the exact coefficient two."}
        self.annotations["steps"].append(use)
        second_result = copy.deepcopy(self.annotations["conclusions"][0])
        second_result.update(conclusion_id="C002", support_step="triangle")
        self.annotations["conclusions"].append(second_result)
        self.annotations["review"]["source_reference_dispositions"] = [{
            "occurrence_id": occurrence["occurrence_id"], "target": occurrence["target"],
            "command": occurrence["command"], "disposition": "local_step",
            "evidence": "The statement label names the equality established by the earlier distributivity move.",
        }]

    def test_compiler_and_primary_validator_accept_statement_label_reuse(self) -> None:
        self.fixture.compile(self.annotations, self.fixture.output)
        ledger = fixtures.read_json(self.fixture.output)
        self.assertNotIn("source_fragments", ledger)
        errors, _ = proofcheck.check_ledger_data(self.fixture.output, True, primary_only=True)
        self.assertEqual([], errors)
        use = next(step for step in ledger["steps"] if step.get("restatement") == "|2x| is at most 2|x|")
        self.assertEqual("eq:double", use["premise_uses"][0]["source_reference_id"])

    def test_compiler_rejects_support_that_does_not_establish_the_referenced_conclusion(self) -> None:
        self.annotations["conclusions"][0]["support_step"] = "triangle"
        with self.assertRaisesRegex(ValueError, "statement conclusion it establishes|support move must exactly match"):
            self.fixture.compile(self.annotations, self.fixture.output)


if __name__ == "__main__":
    unittest.main()
