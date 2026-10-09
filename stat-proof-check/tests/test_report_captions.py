"""Independent mathematical properties of shortened navigation and excerpts."""
from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("proofcheck_report", ROOT / "scripts/proofcheck_report.py")
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)
NS = "{http://www.w3.org/1998/Math/MathML}"
SRF_PREMISE = (r"$X_i=\psi_{1,n}(Z_i)$ and $Y_i=\psi_{2,n}(Z_i)$ are scalar scores; "
               r"$\bar X=n^{-1}\sum_iX_i$ and $\bar Y=n^{-1}\sum_iY_i$.")


def annotations(rendered):
    return [node.text for node in ET.fromstring("<div>" + rendered + "</div>").iter(NS + "annotation")]


class MathematicalCaptionTests(unittest.TestCase):
    def test_every_cut_near_inline_or_display_delimiters_retains_whole_math(self):
        tex = r"\frac{x_i^2}{n}"
        for opening, closing in (("$", "$"), ("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]")):
            text = "Assume the bound " + opening + tex + closing + " holds for every sample size under the listed conditions."
            for limit in range(19, len(text)):
                with self.subTest(opening=opening, limit=limit):
                    caption = report._caption(text, limit)
                    rendered = report._rich(caption)
                    self.assertLessEqual(len(caption), limit)
                    self.assertNotIn("math-fallback", rendered)
                    self.assertIn(annotations(rendered), ([], [tex]))
                    if tex in caption:
                        self.assertIn(opening + tex + closing, caption)

    def test_multiple_formulas_keep_original_tex_whitespace_and_separate_annotations(self):
        text = "Given $x_i$ and \\(\\frac{a + b}{n}\\), compare $\\sum_i\n x_i$ with a long explanation of the final step."
        expected = ["x_i", r"\frac{a + b}{n}", "\\sum_i\n x_i"]
        for limit in (28, 43, 70, 90):
            with self.subTest(limit=limit):
                rendered = report._rich(report._caption(text, limit))
                self.assertNotIn("math-fallback", rendered)
                observed = annotations(rendered)
                self.assertEqual(expected[:len(observed)], observed)
        self.assertEqual(expected, annotations(report._rich(text)))

    def test_formula_longer_than_caption_uses_full_statement_pointer(self):
        tex = "+".join("x_{" + str(i) + "}" for i in range(30))
        text = "$" + tex + "$ is the complete expression."
        caption = report._caption(text)
        self.assertEqual("See full statement.", caption)
        self.assertNotIn("math-fallback", report._rich(caption))
        self.assertEqual([tex], annotations(report._rich(text)))

    def test_real_srf_premise_does_not_generate_truncated_bar_command(self):
        caption = report._caption(SRF_PREMISE)
        rendered = report._rich(caption)
        self.assertNotIn("math-fallback", rendered)
        self.assertNotIn(r"$\bar...", caption)
        self.assertEqual([r"X_i=\psi_{1,n}(Z_i)", r"Y_i=\psi_{2,n}(Z_i)"], annotations(rendered))
        self.assertEqual([r"X_i=\psi_{1,n}(Z_i)", r"Y_i=\psi_{2,n}(Z_i)",
                          r"\bar X=n^{-1}\sum_iX_i", r"\bar Y=n^{-1}\sum_iY_i"],
                         annotations(report._rich(SRF_PREMISE)))

    def test_unsupported_or_authored_unmatched_tex_still_has_exact_explicit_fallback(self):
        for text in (r"Assume $\unknownproofmacro{x}$.", r"Assume $x_i"):
            with self.subTest(text=text):
                caption = report._caption(text)
                rendered = report._rich(caption)
                self.assertEqual(text, caption)
                self.assertIn("math-fallback", rendered)
                self.assertIn(text.split("Assume ")[1], "".join(ET.fromstring("<div>" + rendered + "</div>").itertext()))

    def test_escaped_dollar_and_adjacent_punctuation_do_not_introduce_math(self):
        text = r"For price \$5, the expression $x_i$; holds in a longer discussion of the assumptions."
        for limit in (20, 34, 50):
            with self.subTest(limit=limit):
                rendered = report._rich(report._caption(text, limit))
                self.assertNotIn("math-fallback", rendered)
                self.assertIn(annotations(rendered), ([], ["x_i"]))


class MathematicalExcerptTests(unittest.TestCase):
    def test_excerpt_boundary_is_proved_from_containing_text_without_widening_quote(self):
        lines = ["Before.", r"\[", "a_n=1,", "b_n=2.", r"\]", "After."]
        cache = {}
        for start, end, partial in ((1, 4, True), (3, 6, True), (3, 3, True),
                                    (2, 5, False), (1, 6, False), (6, 6, False)):
            with self.subTest(start=start, end=end):
                source = {"quote": "\n".join(lines[start - 1:end]), "start_line": start, "end_line": end}
                before = copy.deepcopy(source)
                self.assertIs(partial, report._math_excerpt_boundary(source, lines, cache=cache))
                self.assertEqual(before, source)
        self.assertEqual(1, len(cache), "Containing math was reparsed for every excerpt")

    def test_real_srf_review_excerpt_has_authenticated_closing_line_outside_range(self):
        # proofs.tex:184-189, cited through line 187 by the preserved review.
        lines = [r"\[", r"a_n=\E(X_i^2),\quad", r"b_n=\E(Y_i^2),\quad",
                 r"c_n=\E(X_iY_i),\quad", r"d_n=\E(X_i^2Y_i^2).", r"\]"]
        source = {"quote": "\n".join(lines[:4]), "start_line": 184, "end_line": 187}
        self.assertTrue(report._math_excerpt_boundary(source, lines, 184))
        before = copy.deepcopy(source)
        rendered = report._source_reading({**source, "math_excerpt_boundary": True})
        self.assertIn("excerpt boundary, not a LaTeX syntax finding", rendered)
        self.assertNotIn("math-fallback", rendered)
        self.assertNotIn("<math", rendered)
        self.assertEqual(before, source)

    def test_missing_closer_mismatched_text_or_uncovered_range_is_not_reclassified(self):
        lines = ["Before.", r"\[", "x_i=0"]
        source = {"quote": "\n".join(lines[1:]), "start_line": 2, "end_line": 3}
        self.assertFalse(report._math_excerpt_boundary(source, lines))
        self.assertIn("math-fallback", report._source_reading(source))
        complete = [*lines, r"\]"]
        self.assertFalse(report._math_excerpt_boundary({**source, "quote": "changed"}, complete))
        self.assertFalse(report._math_excerpt_boundary({**source, "start_line": 0}, complete))
        self.assertFalse(report._math_excerpt_boundary({**source, "end_line": 9}, complete))

    def test_neighboring_tex_comments_or_escaped_dollars_cannot_make_whole_math_partial(self):
        for surrounding in (("% unmatched $ in comment", "% another $"),
                            (r"\\% $ after an even number of slashes is a comment", "% $"),
                            (r"A literal \$5 or \% is escaped", "After.")):
            with self.subTest(surrounding=surrounding):
                lines = [surrounding[0], r"\[", "x_i=0", r"\]", surrounding[1]]
                source = {"file": "paper.tex", "quote": "\n".join(lines[1:4]), "start_line": 2, "end_line": 4}
                self.assertFalse(report._math_excerpt_boundary(source, lines))
                source.update(quote="\n".join(lines[1:3]), end_line=3)
                self.assertTrue(report._math_excerpt_boundary(source, lines))


if __name__ == "__main__":
    unittest.main()
