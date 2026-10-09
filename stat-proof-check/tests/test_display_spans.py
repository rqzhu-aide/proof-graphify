from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import test_proofcheck as fixtures


proofcheck = fixtures.proofcheck


class DisplaySpansTests(unittest.TestCase):
    def test_delimiters_preserve_exact_source_positions(self) -> None:
        for opening, closing in ((r"\[", r"\]"), ("$$", "$$")):
            with self.subTest(opening=opening):
                lines = ["preface", f"  {opening}", "x = x", f"{closing} trailing"]
                self.assertEqual([{
                    "environment": opening, "start_line": 2, "start_column": 3,
                    "end_line": 4, "end_column": 2,
                    "length": len(opening + "\nx = x\n" + closing),
                }], proofcheck.display_math_spans(lines))

    def test_named_starred_displays_and_nested_aligned(self) -> None:
        for environment in ("equation", "equation*", "align", "align*", "subequations"):
            with self.subTest(environment=environment):
                lines = [rf"\begin{{{environment}}}", r"\begin{aligned}",
                         "x &= x", r"\end{aligned}", rf"\end{{{environment}}}"]
                spans = proofcheck.display_math_spans(lines)
                self.assertEqual(1, len(spans))
                self.assertEqual(environment, spans[0]["environment"])
                self.assertEqual((1, 5), (spans[0]["start_line"], spans[0]["end_line"]))
        for opening, closing in ((r"\[", r"\]"), ("$$", "$$")):
            lines = [opening, r"\begin{aligned}", "x &= x", r"\end{aligned}", closing]
            self.assertEqual(1, len(proofcheck.display_math_spans(lines)))
        for text in (r"\begin{equation*}", r"\end{equation*}", r"\begin{aligned}"):
            self.assertEqual(set(), proofcheck.extract_step_math_tokens(text, whole_math=True))

    def test_structural_masking_comments_literals_definitions_and_inactive_tex(self) -> None:
        lines = [r"% \[ fake \] $$fake$$", r"\verb|\[ fake \] $$fake$$|",
                 r"\begin{verbatim}", r"\[ fake \] $$fake$$", r"\end{verbatim}",
                 r"\newcommand{\fake}{\[ fake \] $$fake$$}",
                 r"\iffalse \[ fake \] $$fake$$ \fi", r"\[ % \]",
                 r"x=x % $$", r"\]"]
        spans = proofcheck.display_math_spans(lines)
        self.assertEqual(1, len(spans))
        self.assertEqual((8, 10), (spans[0]["start_line"], spans[0]["end_line"]))

    def test_escaping_unmatched_and_malformed_delimiters(self) -> None:
        for text in (r"\\[ x \\]", r"\$$ x \$$", r"\[ x", r"x \]", "$$x",
                     r"\[ x $$ y \]", r"$$ x \[ y $$", r"\[ \[ x \] \]"):
            with self.subTest(text=text):
                self.assertEqual([], proofcheck.display_math_spans([text]))
        for text in (r"\\\[ x \\\]", r"\\$$ x \\$$"):
            with self.subTest(text=text):
                spans = proofcheck.display_math_spans([text])
                self.assertEqual(1, len(spans))
                self.assertEqual(3, spans[0]["start_column"])
        escaped_dollar = proofcheck.display_math_spans([r"\$$$x$$"])
        self.assertEqual(1, len(escaped_dollar))
        self.assertEqual((3, 7), (escaped_dollar[0]["start_column"], escaped_dollar[0]["end_column"]))

    def test_adjacent_displays_have_distinct_exact_boundaries(self) -> None:
        for text in (r"\[x\]\[y\]", "$$x$$$$y$$"):
            with self.subTest(text=text):
                spans = proofcheck.display_math_spans([text])
                self.assertEqual(2, len(spans))
                self.assertEqual([(1, 5), (6, 10)], [
                    (span["start_column"], span["end_column"]) for span in spans
                ])

    def test_adjacent_inline_formulas_do_not_turn_prose_into_display_math(self) -> None:
        lines = ["$x$$y$", "Consequently.", "Done.", "$z$$w$"]
        spans = proofcheck.display_math_spans(lines)
        masked = proofcheck.mask_structural_tex("\n".join(lines)).split("\n")
        self.assertEqual([], spans)
        self.assertFalse(proofcheck.display_math_contains_lines(spans, masked, 2, 2))
        self.assertEqual([], self.validate_groups(lines, [(1, 1), (2, 2), (3, 3), (4, 4)]))
        errors = self.validate_groups(lines, [(1, 1), (2, 3), (4, 4)])
        self.assertTrue(any("one complete" in error for error in errors), errors)

    def test_real_displays_survive_inline_dollars_and_masked_single_dollars(self) -> None:
        for opening, closing in ((r"\[", r"\]"), ("$$", "$$")):
            with self.subTest(opening=opening):
                lines = ["$a$$b$", r"% $", r"\verb|$|", r"\newcommand{\fake}{$}",
                         r"\iffalse $ \fi", r"\begin{verbatim}$\end{verbatim}",
                         opening, r"x=\text{$c$$d$ and \$5}", closing, "$e$$f$"]
                spans = proofcheck.display_math_spans(lines)
                self.assertEqual(1, len(spans))
                self.assertEqual((7, 1, 9, 2), (
                    spans[0]["start_line"], spans[0]["start_column"],
                    spans[0]["end_line"], spans[0]["end_column"],
                ))
        for text, bounds in (("$a$$$x$$", (4, 8)), ("$$x$$$a$", (1, 5)),
                             ("$a$$$x$$$b$", (4, 8))):
            with self.subTest(text=text):
                spans = proofcheck.display_math_spans([text])
                self.assertEqual(1, len(spans))
                self.assertEqual(bounds, (spans[0]["start_column"], spans[0]["end_column"]))

    def validate_groups(self, lines: list[str], ranges: list[tuple[int, int]]) -> list[str]:
        units = [{
            "id": f"U{index:03d}", "lines": [start + 6, end + 6],
            "kind": "one_line" if start == end else "continued_display",
            "source_sha256": proofcheck.sha256_text("\n".join(lines[start - 1:end])),
            "partition_evidence": "The source grouping follows one displayed identity.",
        } for index, (start, end) in enumerate(ranges, 1)]
        errors: list[str] = []
        proofcheck.validate_source_units(units, start=7, end=6 + len(lines),
                                        selected_lines=lines, final=True, errors=errors)
        return errors

    def test_grouped_and_split_displays_preserve_physical_coverage(self) -> None:
        for opening, closing in ((r"\[", r"\]"), ("$$", "$$"),
                                 (r"\begin{equation*}", r"\end{equation*}")):
            with self.subTest(opening=opening):
                lines = [opening, "x =", "x", closing]
                for groups in ([(1, 4)], [(1, 1), (2, 3), (4, 4)],
                               [(1, 1), (2, 2), (3, 3), (4, 4)]):
                    self.assertEqual([], self.validate_groups(lines, groups))
                crossing = [opening, "x=x", closing, opening, "y=y", closing]
                self.assertTrue(any("one complete" in error for error in self.validate_groups(
                    crossing, [(1, 1), (2, 5), (6, 6)])))
                shared_line = [opening, "x=x", closing + " " + opening, "y=y", closing]
                self.assertTrue(any("one complete" in error for error in self.validate_groups(
                    shared_line, [(1, 3), (4, 5)])))
                outside = ["prose " + opening, "x=x", closing]
                self.assertTrue(any("one complete" in error for error in self.validate_groups(
                    outside, [(1, 3)])))

    def test_unowned_label_support_stops_at_each_display(self) -> None:
        for opening, closing in ((r"\[", r"\]"), ("$$", "$$"),
                                 (r"\begin{equation*}", r"\end{equation*}")):
            with self.subTest(opening=opening), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                source = base / "paper.tex"
                lines = [r"Before the heading see \ref{thm:outside}.",
                         r"\section*{Proof of an identity}", r"Using \ref{thm:prior}, derive",
                         opening, r"x=x\label{eq:bridge}", closing,
                         r"After the display see \ref{thm:outside}."]
                source.write_text("\n".join(lines), encoding="utf-8")
                owners = {"eq:bridge": {"status": "unowned", "locations": [{
                    "file": "paper.tex", "line": 5, "column": 4,
                }]}}
                index = proofcheck.build_unowned_label_support_index(
                    {source: lines}, [], owners, base)
                self.assertEqual({"eq:bridge"}, set(index))
                self.assertEqual(["thm:prior"], [
                    row["target"] for row in index["eq:bridge"]["reference_occurrences"]
                ])
                self.assertEqual({"file": "paper.tex", "start_line": 3, "end_line": 6},
                                 index["eq:bridge"]["region"])


class DisplayEvidenceAnchoringTests(unittest.TestCase):
    def test_one_line_interior_math_requires_its_own_object_in_evidence(self) -> None:
        fixture = fixtures.FinalizationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        ledger_path = fixture.make_complete_audit()
        original = fixtures.read_json(ledger_path)
        for opening, closing in ((r"\[", r"\]"), ("$$", "$$"),
                                 (r"\begin{equation*}", r"\end{equation*}")):
            with self.subTest(opening=opening):
                fixtures.write_json(ledger_path, original)
                source = fixture.base / "interior-display.tex"
                source.write_text(
                    "\\begin{lemma}\\label{lem:main}For real $x$, $x=x$.\\end{lemma}\n"
                    "\\begin{proof}\n" + opening + "\nx=x % z is commentary\n" + closing + "\n\\end{proof}\n",
                    encoding="utf-8")
                ledger, extracted = fixture.replace_ledger_source(
                    ledger_path, source, statement_start=1, statement_end=1, source_end=6)
                ledger["source_units"] = extracted["source_units"]
                for unit in ledger["source_units"]:
                    unit["partition_evidence"] = "Each line retains its exact physical source position."
                statement = copy.deepcopy(original["steps"][0])
                statement["source_unit_id"] = "U001"
                conclusion = copy.deepcopy(original["steps"][2])
                conclusion["source_unit_id"] = "U004"
                # Keep mathematical x in the claim and literal transcription,
                # but deliberately remove it from all authored evidence fields.
                conclusion["checks"]["atomicity"]["evidence"] = "Reflexivity is one equality inference."
                conclusion["checks"]["adversarial"] = ["Reflexivity holds throughout the stated domain."]
                conclusion["inference"]["moves"][0]["justification"] = "Reflexivity establishes z as the identical pair."
                for risk in conclusion["risk_checks"]:
                    risk["evidence"] = risk["evidence"].replace(" x ", " the fixed object ")
                extra_steps = []
                for number in (2, 3, 5, 6):
                    step = copy.deepcopy(original["steps"][1 if number == 2 else 3])
                    step.update(id=f"S{number + 10:03d}", source_unit_id=f"U{number:03d}")
                    if number in (3, 5):
                        # Display delimiters have structural content under the
                        # existing source-unit contract; they are not this step.
                        step = copy.deepcopy(conclusion)
                        step.update(id=f"S{number + 10:03d}", source_unit_id=f"U{number:03d}")
                    extra_steps.append(step)
                ledger["steps"] = [statement, *extra_steps[:2], conclusion, *extra_steps[2:]]
                fixtures.write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True, primary_only=True)
                self.assertEqual(1, len(errors), errors)
                self.assertTrue(any("S003: step evidence never names" in error for error in errors), errors)
                conclusion["inference"]["moves"][0]["justification"] = "Reflexivity establishes x equals x."
                fixtures.write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True, primary_only=True)
                self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
