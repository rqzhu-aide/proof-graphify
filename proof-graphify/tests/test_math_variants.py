"""Mathematical alphabets remain visible without rewriting source evidence."""
from __future__ import annotations

import html
from pathlib import Path
import sys
import unicodedata
import unittest
from unittest import mock
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import overview_math
from paper_core import math_render

NS = {"m": math_render.MATHML_NS}


class MathematicalAlphabetTests(unittest.TestCase):
    def rendered(self, tex):
        diagnostics = []
        markup = overview_math.render_text(r"\(" + tex + r"\)", diagnostics)
        self.assertEqual(diagnostics, [])
        root = ET.fromstring(markup)
        self.assertEqual(root.find(".//m:annotation", NS).text, tex)
        self.assertEqual(root.get("aria-label"), "LaTeX: " + tex)
        return root

    def test_rkhs_and_real_number_alphabets_are_distinct_from_plain_letters(self):
        root = self.rendered(r"R\in\mathbb R, H\in\mathcal H")
        self.assertEqual([node.text for node in root.findall(".//m:mi", NS)], ["R", "ℝ", "H", "ℋ"])

    def test_legacy_script_fraktur_and_double_struck_letters_are_assigned(self):
        for command, letters, expected in (
            ("mathcal", "BEFHILMRego", "ℬℰℱℋℐℒℳℛℯℊℴ"),
            ("mathfrak", "CHIRZ", "ℭℌℑℜℨ"),
            ("mathbb", "CHNPQRZ", "ℂℍℕℙℚℝℤ"),
            ("mathit", "h", "ℎ"),
        ):
            with self.subTest(command=command):
                root = self.rendered("\\" + command + "{" + letters + "}")
                actual = "".join(node.text for node in root.findall(".//m:mi", NS))
                self.assertEqual(actual, expected)
                for base, styled in zip(letters, actual):
                    self.assertEqual(unicodedata.decomposition(styled), "<font> " + f"{ord(base):04X}")

    def test_converter_emitted_latin_alphabets_use_their_unicode_letters(self):
        for command, style in (
            ("mathbf", "BOLD"), ("mathit", "ITALIC"), ("bm", "BOLD ITALIC"),
            ("mathcal", "SCRIPT"), ("mathfrak", "FRAKTUR"), ("mathbb", "DOUBLE-STRUCK"),
            ("mathsf", "SANS-SERIF"), ("mathsfit", "SANS-SERIF ITALIC"), ("mathtt", "MONOSPACE"),
        ):
            with self.subTest(command=command):
                root = self.rendered("\\" + command + "{Az}")
                actual = [node.text for node in root.findall(".//m:mi", NS)]
                expected = [unicodedata.lookup("MATHEMATICAL " + style + " CAPITAL A"),
                            unicodedata.lookup("MATHEMATICAL " + style + " SMALL Z")]
                self.assertEqual(actual, expected)

    def test_numbers_preserve_multiple_digits_and_decimal_punctuation(self):
        for tex, expected in ((r"\mathbb{0123}", "𝟘𝟙𝟚𝟛"), (r"\mathbf{12.3}", "𝟏𝟐.𝟑"),
                              (r"\mathtt{12}", "𝟷𝟸")):
            with self.subTest(tex=tex):
                root = self.rendered(tex)
                self.assertEqual("".join(node.text for node in root.findall(".//m:mn", NS)), expected)

    def test_greek_capitals_lowercase_and_variant_symbols_remain_distinct(self):
        for tex, expected in (
            (r"\mathbf{\Gamma\alpha\vartheta}", ["MATHEMATICAL BOLD CAPITAL GAMMA",
              "MATHEMATICAL BOLD SMALL ALPHA", "MATHEMATICAL BOLD THETA SYMBOL"]),
            (r"\boldsymbol{\Gamma\alpha}", ["MATHEMATICAL BOLD ITALIC CAPITAL GAMMA",
              "MATHEMATICAL BOLD ITALIC SMALL ALPHA"]),
        ):
            with self.subTest(tex=tex):
                root = self.rendered(tex)
                self.assertEqual([node.text for node in root.findall(".//m:mi", NS)],
                                 [unicodedata.lookup(name) for name in expected])
        root = self.rendered(r"\mathbb{\Gamma\gamma\Pi\pi}")
        self.assertEqual([node.text for node in root.findall(".//m:mi", NS)], ["ℾ", "ℽ", "ℿ", "ℼ"])

    def test_subscripts_keep_their_structure_and_source_annotation(self):
        root = self.rendered(r"\|f\|_{\mathcal H}^2\leq M")
        scripted = root.find(".//m:msubsup", NS)
        self.assertEqual(scripted.find(".//m:mi", NS).text, "ℋ")
        self.assertEqual(scripted[-1].text, "2")

    def test_normal_overrides_stop_inherited_alphabet_and_annotation_is_untouched(self):
        markup = ('<math xmlns="' + math_render.MATHML_NS + '"><semantics>'
                  '<mstyle mathvariant="script"><mi>A</mi><mi mathvariant="normal">R</mi>'
                  '<mstyle mathvariant="normal"><mi>H</mi></mstyle></mstyle>'
                  '<annotation encoding="application/x-tex">\\mathcal{A} R H</annotation>'
                  '</semantics></math>')
        root = ET.fromstring(overview_math._alphabet_mathml(markup))
        self.assertEqual([node.text for node in root.findall(".//m:mi", NS)], ["𝒜", "R", "H"])
        self.assertEqual(root.find(".//m:annotation", NS).text, r"\mathcal{A} R H")

    def test_operators_and_text_are_not_rewritten_as_identifiers(self):
        root = self.rendered(r"\mathbf{a+b=1}\textit{R H}")
        self.assertEqual([node.text for node in root.findall(".//m:mo", NS)], ["+", "="])
        self.assertEqual(root.find(".//m:mtext", NS).text, "R H")
        prose = r"R and H, \mathcal H, <mi mathvariant='script'>H</mi>."
        self.assertEqual(overview_math.render_text(prose), html.escape(prose, quote=True))

    def test_missing_alphabet_glyphs_keep_the_original_formula_and_one_diagnostic(self):
        for tex in (r"\mathcal{\alpha}", r"\mathcal{1}", r"\mathfrak{3}", r"\mathsf{\alpha}"):
            with self.subTest(tex=tex):
                literal = "$" + tex + "$"
                diagnostics = []
                markup = overview_math.render_text(literal, diagnostics)
                self.assertIn('class="math-fallback"', markup)
                self.assertIn(html.escape(literal, quote=True), markup)
                self.assertNotIn("<math", markup)
                self.assertEqual(len(diagnostics), 1)
                self.assertEqual(diagnostics[0]["excerpt"], literal)
                self.assertIn("no Unicode", diagnostics[0]["reason"])
                self.assertNotIn("kind", diagnostics[0])

    def test_unknown_mathematical_variant_is_not_silently_discarded(self):
        markup = '<math><mi mathvariant="initial">A</mi></math>'
        with self.assertRaisesRegex(ValueError, "unsupported mathematical alphabet: initial"):
            overview_math._alphabet_mathml(markup)

    def test_existing_fallbacks_keep_exact_output_and_diagnostic_content(self):
        for text in (r"Before $\privateMacro_x$ after $x\!y$.", r"$\binom{$", r"$\\mathbb R$",
                     r"Unclosed \(\mathcal H", r"\\(x\\)"):
            with self.subTest(text=text):
                core_diagnostics, diagnostics = [], []
                expected = math_render.render_text(text, core_diagnostics)
                self.assertEqual(overview_math.render_text(text, diagnostics), expected)
                self.assertEqual(diagnostics, [{key: value for key, value in entry.items() if key != "kind"}
                                               for entry in core_diagnostics])

    def test_unavailable_converter_still_uses_the_existing_fallback(self):
        reason = "The shared LaTeX converter is unavailable."
        with mock.patch.object(math_render, "_convert", return_value=(None, reason)):
            diagnostics, core_diagnostics = [], []
            literal = r"$\mathbb R$"
            expected = math_render.render_text(literal, core_diagnostics)
            self.assertEqual(overview_math.render_text(literal, diagnostics), expected)
            self.assertEqual(diagnostics, [{key: value for key, value in entry.items() if key != "kind"}
                                           for entry in core_diagnostics])


if __name__ == "__main__":
    unittest.main()
