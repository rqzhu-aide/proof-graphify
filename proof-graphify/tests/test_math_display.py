"""Math display adaptation and diagnostics.

Fixtures cover independence notation, negative spacing, sized named bar
delimiters, unbraced binomial arguments, private macros, and the two saved DSH
terminal-tag failures.
The tests assert converter-input adaptation and located diagnostics, never
mathematical content.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree as ET


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import overview_math as math_display
import paper_records as records
import proof_overview as overview
from paper_core import math_render as common_math


NODE = shutil.which("node")
RENDERER = SKILL / "scripts" / "render.mjs"


class FaithfulEquationDisplayTests(unittest.TestCase):
    def test_align_blocks_do_not_invent_numbers_and_keep_original_tex(self):
        namespace = {"m": math_display.MATHML_NS}
        expressions = [r"\begin{align}a&=b\\c&=d\nonumber\end{align}",
                       r"\begin{align}e&=f\notag\end{align}"]
        diagnostics = []
        markup = math_display.render_text(" ".join(r"\[" + tex + r"\]" for tex in expressions), diagnostics)
        root = ET.fromstring("<div>" + markup + "</div>")
        self.assertEqual(diagnostics, [])
        self.assertEqual(len(root.findall(".//m:mtr", namespace)), 3)
        self.assertEqual(root.findall(".//m:mlabeledtr", namespace), [])
        self.assertEqual(root.findall(".//m:mtext", namespace), [])
        self.assertEqual([node.text for node in root.findall(".//m:annotation", namespace)], expressions)
        self.assertEqual([node.get("aria-label") for node in root.findall("m:math", namespace)],
                         ["LaTeX: " + tex for tex in expressions])

    def test_existing_unnumbered_row_environments_keep_their_behavior(self):
        namespace = {"m": math_display.MATHML_NS}
        for environment in ("align*", "split"):
            tex = "\\begin{" + environment + r"}a&=b\\c&=d\end{" + environment + "}"
            with self.subTest(environment=environment):
                markup, reason = math_display._convert(tex, "block")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                self.assertEqual(len(root.findall(".//m:mtr", namespace)), 2)
                self.assertEqual(root.findall(".//m:mtext", namespace), [])
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)

    def test_simple_terminal_block_tags_keep_body_structure_and_original_tex(self):
        namespace = {"m": common_math.MATHML_NS}
        # Exact saved DSH expressions, including their whitespace and tags.
        cases = [
            ("\n" + r"\sum_i\operatorname{ord}_{z=z_i}F_l(z,z'_i)\le N(d_l+d'_l)+2d_ld'_l. "
             + r"\tag{3.6}" + "\n", "3.6"),
            ("\n" + r"\sum_{p\le X,\ \chi(p)=-1}\log p\sum_{r,s}\min(\lfloor r/p\rfloor,S-1-s)"
             + "\n" + r"\le \tfrac12 RS(R+S)\log(2N\sqrt q)+O(X^3). \tag{6.1}" + "\n", "6.1"),
            (r"x^2\tag{A.1}", "A.1"),
            (" " + r"\frac{a}{b}\tag {B12.3}" + "\t\n", "B12.3"),
            (r"\begin{aligned}x&=1\\y&=2\end{aligned}\tag{A.1}", "A.1"),
            (r"\begin{matrix}x\end{matrix}+\begin{matrix}y\end{matrix}\tag{2}", "2"),
        ]
        for tex, label in cases:
            with self.subTest(tex=tex):
                diagnostics = []
                markup = common_math.render_text(r"\[" + tex + r"\]", diagnostics)
                self.assertEqual(diagnostics, [])
                root = ET.fromstring(markup)
                self.assertEqual(root.get("display"), "block")
                self.assertEqual(root.get("aria-label"), "LaTeX: " + tex)
                self.assertEqual(root.find("m:semantics/m:annotation", namespace).text, tex)
                row = root.find("m:semantics/m:mrow", namespace)
                self.assertEqual(row[-2].tag, "{" + common_math.MATHML_NS + "}mspace")
                self.assertEqual(row[-2].attrib, {"width": "1em"})
                self.assertEqual(row[-1].tag, "{" + common_math.MATHML_NS + "}mtext")
                self.assertEqual(row[-1].text, "(" + label + ")")
                body = tex[:tex.rfind(r"\tag")]
                plain, reason = common_math._convert(body, "block")
                self.assertIsNotNone(plain, reason)
                del row[-2:]
                self.assertEqual(ET.tostring(row), ET.tostring(
                    ET.fromstring(plain).find("m:semantics/m:mrow", namespace)))

    def test_unsupported_tags_keep_the_whole_expression_as_escaped_literal(self):
        import html
        cases = [r"a=b\tag*{A}", r"a=b\tag{{1}a}",
                 r"a=b\tag{1}\tag{2}", r"a<b\tag{<script>&}",
                 r"\begin{align}a&=b\tag{3}\\c&=d\end{align}",
                 r"{x\tag{1}}", r"x\tag{\alpha}", r"x\tag{1}+y", r"\tag{1}",
                 r"x\tag{A-1}", r"x\tag{1.}", r"x\tag{}", r"x\tag{1", r"x\tag1",
                 "x% comment\n" + r"\tag{1}", r"x\tag{1}% trailing comment",
                 r"x{\tag{1}", r"\begin{matrix}x\end{cases}\tag{1}"]
        for tex in cases:
            for opening, closing in (("$", "$"), (r"\[", r"\]")):
                with self.subTest(tex=tex, opening=opening):
                    literal = opening + tex + closing
                    diagnostics = []
                    markup = common_math.render_text(literal, diagnostics)
                    self.assertNotIn("<math", markup)
                    self.assertIn('class="math-fallback"', markup)
                    self.assertIn("LaTeX (not rendered):", markup)
                    self.assertIn("<code>" + html.escape(literal, quote=True) + "</code>", markup)
                    self.assertEqual(len(diagnostics), 1)
                    self.assertEqual(diagnostics[0]["kind"], "unsupported_expression")
                    self.assertIn("tags", diagnostics[0]["reason"])
                    self.assertEqual(diagnostics[0]["excerpt"], literal)
                    self.assertEqual(diagnostics[0]["expression_index"], 0)
        literal = r"$x\tag{3.6}$"
        diagnostics = []
        markup = common_math.render_text(literal, diagnostics)
        self.assertNotIn("<math", markup)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["excerpt"], literal)

    def test_terminal_tag_does_not_bypass_existing_body_checks_or_size_limit(self):
        import html
        cases = [
            (r"\newcommand{\a}{x}\a\tag{1}", "unsupported_expression"),
            (r"\privateUnknown{x}\tag{1}", "unsupported_expression"),
            (r"\\mathbf{x}\tag{1}", "damaged_escape"),
            ("x+\theta" + r"\tag{1}", "damaged_escape"),
            (r"\begin{unknown}x\end{unknown}\tag{1}", "unsupported_expression"),
            ("x" * common_math.CONFIGURATION["maximum_formula_characters"] + r"\tag{1}",
             "unsupported_expression"),
        ]
        for tex, classification in cases:
            with self.subTest(tex=tex[:100]):
                literal = r"\[" + tex + r"\]"
                diagnostics = []
                markup = common_math.render_text("Before " + literal + " after.", diagnostics)
                self.assertNotIn("<math", markup)
                self.assertIn("<code>" + html.escape(literal, quote=True) + "</code>", markup)
                self.assertEqual(len(diagnostics), 1)
                self.assertEqual(diagnostics[0]["kind"], classification)
                self.assertEqual(diagnostics[0]["excerpt"], literal[:200])
                self.assertEqual(diagnostics[0]["expression_index"], 0)

    def test_tag_detection_respects_command_boundaries_and_escaping(self):
        common_math._check_tex(r"\tagged{A}")
        with self.assertRaises(ValueError) as caught:
            common_math._check_tex(r"\\tag{A}")
        self.assertNotIn("equation tags", str(caught.exception))

    def test_sim_is_a_relation_in_plain_scripted_and_overset_forms(self):
        namespace = {"m": math_display.MATHML_NS}
        for tex in (r"X\sim N(0,1)", r"x^{\sim}", r"\overset{iid}{\sim}"):
            with self.subTest(tex=tex):
                markup, reason = math_display._convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                self.assertIn("∼", [node.text for node in root.findall(".//m:mo", namespace)])
                self.assertNotIn("~", [node.text for node in root.findall(".//m:mi", namespace)])
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)

    def test_tilde_spaces_accents_text_and_other_relations_are_unchanged(self):
        from latex2mathml.converter import convert
        for tex in ("a~b", r"\tilde{x}", r"\widetilde{x}", r"\text{a~b}", r"a\nsim b", r"a\simeq b"):
            with self.subTest(tex=tex):
                # Compare converter tokens, excluding the adapter's annotation.
                raw = ET.fromstring(convert(tex, display="inline"))
                markup, reason = math_display._convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                adapted = ET.fromstring(markup)
                def tokens(root):
                    return [(node.tag.rsplit("}", 1)[-1], node.text, dict(node.attrib))
                            for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"mi", "mo", "mtext", "mspace"}]
                self.assertEqual(tokens(adapted), tokens(raw))

    def test_unavailable_converter_keeps_original_inspectable(self):
        literal = r"\[X\sim N(0,1)\]"
        common_math._convert.cache_clear()
        try:
            with mock.patch.dict(sys.modules, {"latex2mathml.converter": None}):
                diagnostics = []
                markup = common_math.render_text(literal, diagnostics)
            self.assertIn("<code>" + literal + "</code>", markup)
            self.assertIn("unavailable", diagnostics[0]["reason"])
        finally:
            common_math._convert.cache_clear()


class ConverterAdaptationTests(unittest.TestCase):
    def test_standalone_aligned_preserves_columns_and_original_tex(self):
        namespace = {"m": common_math.MATHML_NS}
        for tex in (r"\begin{aligned}a&=b\\c&=d\end{aligned}",
                    r"\begin{aligned}a&=b\\\gamma&=d\end{aligned}",
                    r"\begin{aligned}a&=b\\\leq&d\end{aligned}",
                    r"\begin{aligned}&\mathbb E\!\left[X\right]\\&=y\end{aligned}",
                    r"\begin{aligned}&{\mathbb E\!\left[X\right]}\\ &=\Big\langle U^{\!\top},v\Big\rangle\end{aligned}"):
            with self.subTest(tex=tex):
                markup, reason = common_math._convert(tex, "block")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                table = root.find(".//m:mtable", namespace)
                self.assertEqual(table.get("displaystyle"), "true")
                self.assertEqual(len(table.findall("m:mtr", namespace)), 2)
                self.assertEqual([cell.get("columnalign") for cell in table.findall("m:mtr/m:mtd", namespace)],
                                 ["right", "left", "right", "left"])
                self.assertFalse(root.findall(".//m:mlabeledtr", namespace))
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
                self.assertEqual(root.get("aria-label"), "LaTeX: " + tex)

    def test_aligned_outside_bounded_contract_stays_visible(self):
        for tex, display in (
            (r"\begin{aligned}a&=b\end{aligned}", "inline"),
            (r"x+\begin{aligned}a&=b\end{aligned}", "block"),
            (r"\begin{aligned}[t]a&=b\end{aligned}", "block"),
            (r"\begin{aligned}a&=b\\[2pt]c&=d\end{aligned}", "block"),
            (r"\begin{aligned}a&=b\tag{1}\end{aligned}", "block"),
            (r"\begin{aligned}\begin{matrix}a\end{matrix}\end{aligned}", "block"),
            ("\\begin{aligned}a&=b% comment\n\\end{aligned}", "block"),
            (r"\\begin{aligned}a&=b\end{aligned}", "block"),
            (r"\begin{aligned}a&=b\\end{aligned}", "block"),
        ):
            with self.subTest(tex=tex, display=display):
                markup, reason = common_math._convert(tex, display)
                self.assertIsNone(markup)
                self.assertTrue(reason)

        for body in (r"x\\*y", r"x\\ [2pt]y", r"x\\\*y", r"x\\\[2pt]y",
                     r"x\\\ foo", r"x\\\{y}", r"x\\\%", r"x\\\,y",
                     "x" + "\\" * 3, r"x\\\α", r"x\\\\alpha", r"x\\\\\alpha",
                     r"x\\\unknownCommand", r"x\\\frac{a}", r"x\\\tag{1}",
                     r"x\\\label{a}", r"x\\\notag", r"x\\\nonumber", r"x\\\cr",
                     r"x\\\hline", r"x\\\intertext{y}"):
            tex = r"\begin{aligned}" + body + r"\end{aligned}"
            with self.subTest(body=body):
                markup, reason = common_math._convert(tex, "block")
                self.assertIsNone(markup)
                self.assertTrue(reason)

    def test_sized_angles_keep_converter_attributes_and_original_tex(self):
        from latex2mathml.converter import convert
        namespace = {"m": common_math.MATHML_NS}
        for size in ("big", "Big", "bigg", "Bigg"):
            tex = "\\" + size + r"l\langle\frac{x}{y}" + "\\" + size + r"r\rangle_{\mathcal H}"
            raw = ET.fromstring(convert(tex, display="block"))
            markup, reason = common_math._convert(tex, "block")
            self.assertIsNotNone(markup, reason)
            root = ET.fromstring(markup)
            before = [n for n in raw.findall(".//m:mo", namespace) if n.get("minsize")]
            after = [n for n in root.findall(".//m:mo", namespace) if n.get("minsize")]
            self.assertEqual([n.text for n in after], ["⟨", "⟩"])
            self.assertEqual([n.attrib for n in before], [n.attrib for n in after])
            self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
            scripted = root.find(".//m:msub", namespace)
            self.assertEqual(scripted[0].tag, "{" + common_math.MATHML_NS + "}mrow")
            self.assertEqual(scripted[0][0].text, "⟩")

    def test_sized_floors_preserve_operator_attributes_and_original_tex(self):
        from latex2mathml.converter import convert
        namespace = {"m": common_math.MATHML_NS}
        for size in ("big", "Big", "bigg", "Bigg"):
            tex = "\\" + size + r"l\lfloor\frac rp" + "\\" + size + r"r\rfloor"
            with self.subTest(size=size):
                raw = ET.fromstring(convert(tex, display="block"))
                diagnostics = []
                root = ET.fromstring(math_display.render_text(r"\[" + tex + r"\]", diagnostics))
                self.assertEqual(diagnostics, [])
                before = [n for n in raw.findall(".//m:mo", namespace) if n.get("minsize")]
                after = [n for n in root.findall(".//m:mo", namespace) if n.get("minsize")]
                self.assertEqual([n.text for n in after], ["⌊", "⌋"])
                self.assertEqual([n.attrib for n in after], [n.attrib for n in before])
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
                self.assertEqual(root.get("aria-label"), "LaTeX: " + tex)
                self.assertIsNotNone(root.find(".//m:mfrac", namespace))
        for token in (r'<mo>\lfloor</mo>',
                      r'<mi minsize="1.2em" maxsize="1.2em">\lfloor</mi>',
                      r'<mo minsize="1.2em" maxsize="1.623em">\rfloor</mo>',
                      r'<mo minsize="1.2em" maxsize="1.2em">\lfloor<mi>x</mi></mo>',
                      r'<mo minsize="1.2em" maxsize="1.2em">\lceil</mo>'):
            with self.subTest(token=token), self.assertRaises(ValueError):
                common_math._safe_mathml("<math>" + token + "</math>", "original", "inline")

    def test_bounded_spacing_preserves_nonspacing_tree_and_evidence(self):
        namespace = {"m": common_math.MATHML_NS}
        for tex in (r"\mathbb E\!\left[X\right]", r"f\!\left(x\right)",
                    r"U^{\!\top}", r"\int\!\!\int f(x,y)\,dx\,dy",
                    r"\int\!\int f", r"\int\!\int C_k\lesssim(\prod h_l)^{-1}",
                    r"\int\!\int C_k\lesssim(\prod_l h_l)^{-2+1/(dH)}",
                    r"k\in[\![1,\lfloor T\rfloor]\!]", r"k\in[\![1,T]\!]",
                    r"\operatorname{Var}(T^{-1}\!\int_0^T F(X_s)ds)\asymp T^{2H-2},",
                    r"[\!{[x]}\!]", r"k\in[\!\left[1,T\right]\!]",
                    r"x\!\int f", r"2\!\int f", r"x_i^2\!\int_A^B f",
                    r"\|\!|x|\!\|", r"\|\!|x|\!\|_A", r"\|\!|x|\!\|^2",
                    r"\|\!|x|\!\|_A^2", r"\left\|\!|x|\!\right\|",
                    r"\left\|\!|x|\!\right\|_A", r"\left\|\!|x|\!\right\|^2",
                    r"\left\|\!|x|\!\right\|_A^2",
                    r"p_t(\ell;y)\le t^{-dH}\exp\{C(1+t^\eta\|\!|\ell|\!\|_{\mathbb C^\gamma}^2)-c|y-\ell(t)|^2/t^{2H}\}",
                    r"\begin{aligned}&\mathbb E\!\left[X\right]\end{aligned}",
                    r"\begin{aligned}&a\!\cdot\! b\\&\int\!\!\int f\end{aligned}"):
            with self.subTest(tex=tex):
                markup, reason = common_math._convert(tex, "block")
                plain, plain_reason = common_math._convert(tex.replace(r"\!", ""), "block")
                self.assertIsNotNone(markup, reason)
                self.assertIsNotNone(plain, plain_reason)
                actual, expected = ET.fromstring(markup), ET.fromstring(plain)
                self.assertEqual(actual.find(".//m:annotation", namespace).text, tex)
                self.assertEqual(actual.get("aria-label"), "LaTeX: " + tex)
                actual.attrib.pop("aria-label")
                expected.attrib.pop("aria-label")
                for root in (actual, expected):
                    root.find(".//m:annotation", namespace).text = "source"
                self.assertEqual(ET.tostring(actual), ET.tostring(expected))

    def test_archived_multiline_formulas_preserve_nonspacing_tree_and_source(self):
        namespace = {"m": common_math.MATHML_NS}
        cases = (
            (r"\begin{aligned}\mathbb P\!\left\{|Z-\widetilde Z|>\frac{bK_n}{\gamma^{1/2}n^{1/2-1/q}}+\frac{(b\sigma)^{1/2}K_n^{3/4}}{\gamma^{1/2}n^{1/4}}+\frac{(b\sigma^2K_n^2)^{1/3}}{\gamma^{1/3}n^{1/6}}\right\}\\\leq C\left(\gamma+\frac{\log n}{n}\right).\end{aligned}", 2),
            (r"\begin{aligned}\mathbb E[B_n(x,g)B_n(x',g')]={}&h_n^{-d}c_n(x,g)c_n(x',g')\\&\times\operatorname{Cov}\!\left(g(Y_1)k(h_n^{-1}(X_1-x)),\,g'(Y_1)k(h_n^{-1}(X_1-x'))\right).\end{aligned}", 4),
            (r"\begin{aligned}|W_n-\widetilde W_n|=O_P\!\big(&n^{-1/6}\xi_n^{1/3}\log n+n^{-1/4}\xi_n^{1/2}(\log n)^{5/4}\\&+n^{-1/2+\theta}\xi_n(\log n)^{3/2}\big),\end{aligned}", 4),
        )
        for tex, cells in cases:
            with self.subTest(tex=tex):
                diagnostics = []
                actual = ET.fromstring(common_math.render_text(r"\[" + tex + r"\]", diagnostics))
                self.assertEqual(diagnostics, [])
                self.assertEqual(len(actual.findall(".//m:mtr", namespace)), 2)
                self.assertEqual(len(actual.findall(".//m:mtd", namespace)), cells)
                self.assertEqual(actual.find(".//m:annotation", namespace).text, tex)
                self.assertEqual(actual.get("aria-label"), "LaTeX: " + tex)
                ordinary = tex.replace(r"\!", "").replace(r"\\\leq", r"\\ \leq")
                markup, reason = common_math._convert(ordinary, "block")
                self.assertIsNotNone(markup, reason)
                expected = ET.fromstring(common_math._alphabet_mathml(markup))
                for root in (actual, expected):
                    root.attrib.pop("aria-label")
                    root.find(".//m:annotation", namespace).text = "source"
                self.assertEqual(ET.tostring(actual), ET.tostring(expected))

    def test_other_spacing_forms_remain_unsupported(self):
        for tex in (r"E\!\!\left[X\right]", r"U^{\!\!\top}", r"U^{\!\top+1}",
                    r"U_{\!\top}", r"U^{\!T}", r"\int\!\!\!\int f",
                    r"\int_A\!\!\int_B f", r"\sum\!\!\int f", r"\frac\!\left[x\right]",
                    r"x\!y", r"x\!\!\int f", r"[\!\![x]\!]", r"[\![x]\!\!]",
                    r"\int_A\!\int_B f", r"x\hspace{-0.2em}\int f",
                    r"\|\!\!|x|\!\|", r"\|\!|x|\!\!\|", r"|\!|x|\!|",
                    r"\|\!\|x\|\!\|", r"\|\hspace{-0.2em}|x|\!\|",
                    r"\begin{aligned}&E\!\!\left[X\right]\end{aligned}",
                    r"\begin{aligned}&a\!\times b\\&\int\!\int f\end{aligned}"):
            with self.subTest(tex=tex):
                markup, reason = common_math._convert(tex, "block")
                self.assertIsNone(markup)
                self.assertTrue(reason)

    def test_spacing_normalization_never_discards_markup_or_text(self):
        shapes = (
            '<mrow><mo>∫</mo><mspace width="negativethinmathspace"/><mo>∫</mo></mrow>',
            '<mtd><mo>∫</mo><mspace width="negativethinmathspace"/><mo>∫</mo></mtd>',
            '<mrow><mo>‖</mo><mspace width="negativethinmathspace"/><mo>|</mo></mrow>',
            '<mrow><mo>|</mo><mspace width="negativethinmathspace"/><msubsup><mo>‖</mo><mi>A</mi><mn>2</mn></msubsup></mrow>',
            '<mrow><mi>E</mi><mspace width="negativethinmathspace"/><mo fence="true" form="prefix">[</mo></mrow>',
            '<msup><mi>U</mi><mrow><mspace width="negativethinmathspace"/><mo>⊤</mo></mrow></msup>',
            '<mrow><mo>∫</mo><mspace width="negativethinmathspace"/><mspace width="negativethinmathspace"/><mo>∫</mo></mrow>',
            '<mtd><mi>E</mi><mspace width="negativethinmathspace"/><mo fence="true" form="prefix">[</mo></mtd>',
            '<mtd><mi>a</mi><mspace width="negativethinmathspace"/><mo>·</mo><mspace width="negativethinmathspace"/><mi>b</mi></mtd>',
            '<mtd><mo>∫</mo><mspace width="negativethinmathspace"/><mspace width="negativethinmathspace"/><mo>∫</mo></mtd>',
            '<mrow><mo stretchy="false">[</mo><mspace width="negativethinmathspace"/><mrow><mo>[</mo><mi>x</mi><mo>]</mo></mrow><mspace width="negativethinmathspace"/><mo>]</mo></mrow>',
            '<mtd><msup><mi>T</mi><mn>2</mn></msup><mspace width="negativethinmathspace"/><msubsup><mo>∫</mo><mn>0</mn><mi>T</mi></msubsup></mtd>',
        )
        for shape in shapes:
            for namespace in ("", ' xmlns="' + common_math.MATHML_NS + '"'):
                raw = '<math' + namespace + '>' + shape + '</math>'
                ordinary = raw.replace('<mspace width="negativethinmathspace"/>', '')
                with self.subTest(shape=shape, namespace=namespace):
                    actual = common_math._safe_mathml(raw, "original", "block")
                    expected = common_math._safe_mathml(ordinary, "original", "block")
                    self.assertEqual(ET.tostring(ET.fromstring(actual)), ET.tostring(ET.fromstring(expected)))
                    self.assertEqual(ET.fromstring(actual).find(
                        ".//{" + common_math.MATHML_NS + "}annotation").text, "original")
            for bad_space in (
                '<mspace width="negativethinmathspace" height="1em"/>',
                '<mspace width="negativethinmathspace">x</mspace>',
                '<mspace width="negativethinmathspace"/>tail',
                '<mspace width="negativethinmathspace"><mi>x</mi></mspace>',
                '<f:mspace width="negativethinmathspace"/>',
            ):
                value = '<math xmlns:f="urn:foreign">' + shape.replace(
                    '<mspace width="negativethinmathspace"/>', bad_space, 1) + '</math>'
                with self.subTest(value=value), self.assertRaises(ValueError):
                    common_math._safe_mathml(value, "original", "block")
            for tag in ("mrow", "mtd", "mo", "mi", "msup", "msubsup"):
                if '<' + tag not in shape:
                    continue
                foreign = shape.replace('<' + tag, '<f:' + tag).replace('</' + tag + '>', '</f:' + tag + '>')
                with self.subTest(foreign=foreign), self.assertRaises(ValueError):
                    common_math._safe_mathml('<math xmlns:f="urn:foreign">' + foreign + '</math>', "original", "block")
        for row in ('text<mspace width="negativethinmathspace"/><mo>⊤</mo>',
                    '<mspace width="negativethinmathspace"/><mo>⊤</mo>tail'):
            with self.assertRaises(ValueError):
                common_math._safe_mathml('<math><msup><mi>U</mi><mrow>' + row + '</mrow></msup></math>', "original", "block")

    def test_norm_bar_spacing_has_bounded_neighbors(self):
        space = '<mspace width="negativethinmathspace"/>'
        cases = (
            ('<mo>‖</mo>', '<mrow><mo>|</mo></mrow>'),
            ('<mrow><mo>|</mo></mrow>', '<mo>‖</mo>'),
            ('<mo>|</mo>', '<msup><mrow><mo>‖</mo></mrow><mn>2</mn></msup>'),
            ('<mo>|</mo>', '<msubsup><mo>‖</mo><mi>A</mi></msubsup>'),
            ('<mo>|</mo>', '<msup>text<mo>‖</mo><mn>2</mn></msup>'),
            ('<mo>|</mo>', '<msup><mo>‖</mo><mn>2</mn></msup>tail'),
            ('<mo>|</mo>', '<msup><mo>‖</mo><mfrac><mi>x</mi></mfrac></msup>'),
            ('<mo>|</mo>', '<f:msup><mo>‖</mo><mn>2</mn></f:msup>'),
            ('<mo>‖</mo>', '<mo bad="1">|</mo>'),
            ('<mo>‖</mo>tail', '<mo>|</mo>'),
            ('<mo>‖</mo>', '<mo><mi>x</mi></mo>'),
        )
        for left, right in cases:
            raw = '<math xmlns:f="urn:foreign"><mrow>' + left + space + right + '</mrow></math>'
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                common_math._safe_mathml(raw, "original", "block")

    def test_bracket_and_integral_spacing_has_bounded_neighbors(self):
        space = '<mspace width="negativethinmathspace"/>'
        cases = (
            ('<mo>[</mo>', '<mrow><mrow><mo>[</mo></mrow></mrow>'),
            ('<mrow><mrow><mo>]</mo></mrow></mrow>', '<mo>]</mo>'),
            ('<mo>[</mo>', '<mrow>text<mo>[</mo></mrow>'),
            ('<mo>[</mo>', '<mrow><mo>[</mo></mrow>tail'),
            ('<mo>[</mo>', '<mo>[</mo>tail'),
            ('<mi>x</mi>tail', '<mo>∫</mo>'),
            ('<mi> </mi>', '<mo>∫</mo>'),
            ('<mi><mi>x</mi></mi>', '<mo>∫</mo>'),
            ('<msup><mo>∫</mo><mi>A</mi></msup>', '<mo>∫</mo>'),
            ('<msup><mi>x</mi></msup>', '<mo>∫</mo>'),
            ('<msup>text<mi>x</mi><mn>2</mn></msup>', '<mo>∫</mo>'),
            ('<msup><mi>x</mi><mn>2</mn></msup>tail', '<mo>∫</mo>'),
            ('<msup><msub><mi>x</mi><mi>i</mi></msub><mn>2</mn></msup>', '<mo>∫</mo>'),
            ('<mi>x</mi>', '<msubsup><mo>∫</mo><mn>0</mn></msubsup>'),
            ('<mi>x</mi>', '<msup><mo>∫</mo><mn>2</mn></msup>tail'),
        )
        for left, right in cases:
            for parent in ("mrow", "mtd"):
                with self.subTest(left=left, right=right, parent=parent), self.assertRaises(ValueError):
                    common_math._safe_mathml('<math><' + parent + '>' + left + space + right
                                             + '</' + parent + '></math>', "original", "block")

    def test_decoded_beta_is_diagnosed_without_guessing_a_replacement(self):
        literal = '$' + '\b' + r'eta_{smp}(\lambda)$'
        diagnostics = []
        markup = common_math.render_text(literal, diagnostics)
        self.assertEqual(diagnostics[0]["classification"], "damaged_escape")
        self.assertIn("backspace", diagnostics[0]["reason"])
        self.assertIn(literal, markup)
        self.assertNotIn("<math", markup)
        clean = []
        self.assertIn("<math", common_math.render_text(r'$\beta_{smp}(\lambda)$', clean))
        self.assertEqual(clean, [])

    def test_sized_braces_render_through_overview_wrapper_with_original_tex(self):
        namespace = {"m": math_display.MATHML_NS}
        for tex in (r"\Bigl\{x\Bigr\}_{i}^{2}", r"\biggl\lbrace\frac{x}{y}\biggr\rbrace"):
            with self.subTest(tex=tex):
                diagnostics = []
                markup = math_display.render_text("$" + tex + "$", diagnostics)
                root = ET.fromstring(markup)
                operators = root.findall(".//m:mo", namespace)
                self.assertEqual([node.text for node in operators], ["{", "}"])
                for node in operators:
                    self.assertTrue(node.get("minsize"))
                    self.assertEqual(node.get("minsize"), node.get("maxsize"))
                    self.assertEqual(node.get("fence"), "true")
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
                self.assertEqual(root.get("aria-label"), "LaTeX: " + tex)
                self.assertEqual(diagnostics, [])

    def test_independence_renders_one_relation_and_retains_conditioning_and_scripts(self):
        namespace = {"m": math_display.MATHML_NS}
        for tex in (r"R\perp\!\perp S\mid X",
                    r"R\perp\!\!\perp S'\mid X",
                    r"R\perp\!\!\!\perp S\mid X",
                    r"R\perp \! \! \perp_{Z} S\mid X"):
            with self.subTest(tex=tex):
                markup, reason = math_display._convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                operators = [node.text for node in root.findall(".//m:mo", namespace)]
                self.assertEqual(operators.count("⫫"), 1)
                self.assertIn("∣", operators)
                self.assertEqual(root.findall(".//m:mspace", namespace), [])
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
                self.assertEqual(root.attrib["aria-label"], "LaTeX: " + tex)
                if "_{Z}" in tex:
                    self.assertEqual(root.find(".//m:msub/m:mo", namespace).text, "⫫")

    def test_independence_adaptation_does_not_join_other_perpendicular_uses(self):
        for tex in (r"R\perp S", r"\perp\perp", r"\perp\,\perp",
                    r"\\perp\!\!\perp", r"\perp\!\!\perpendicular",
                    r"\perp\!\!\!\!\perp"):
            with self.subTest(tex=tex):
                self.assertEqual(math_display._independence_symbol(tex), tex)
        markup, reason = math_display._convert(r"R\perp S", "inline")
        self.assertIsNotNone(markup, reason)
        self.assertNotIn("⫫", markup)

    def test_remaining_negative_spacing_is_visible_and_diagnosed(self):
        for tex in (r"x\!y", r"x\negthinspace y", r"x\negmedspace y",
                    r"x\negthickspace y", r"x\hspace{-0.2em}y",
                    r"R\perp\!\!\!\!\perp S"):
            with self.subTest(tex=tex):
                literal = "$" + tex + "$"
                diagnostics = []
                markup = math_display.render_text(literal, diagnostics)
                self.assertIn('class="math-fallback"', markup)
                self.assertIn(literal, markup)
                self.assertNotIn("<math", markup)
                self.assertEqual(len(diagnostics), 1)
                self.assertEqual(diagnostics[0]["excerpt"], literal)
                self.assertIn("unsupported negative spacing", diagnostics[0]["reason"])

    def test_positive_math_spacing_still_renders(self):
        namespace = {"m": math_display.MATHML_NS}
        for tex in (r"x\,y", r"x\;y", r"x\quad y", r"x\hspace{0.2em}y"):
            with self.subTest(tex=tex):
                markup, reason = math_display._convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                self.assertTrue(ET.fromstring(markup).findall(".//m:mspace", namespace))

    def test_arg_operator_keeps_argument_and_minimum_forms_distinct(self):
        namespace = {"m": math_display.MATHML_NS}
        for tex, expected in ((r"\arg\min_x f(x)", ["arg", "min"]),
                              (r"\arg z", ["arg"])):
            with self.subTest(tex=tex):
                markup, reason = math_display._convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                operators = [node.text for node in root.findall(".//m:mo", namespace)
                             if node.text in ("arg", "min")]
                self.assertEqual(operators, expected)
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
                self.assertEqual(root.attrib["aria-label"], "LaTeX: " + tex)

    def test_arg_adaptation_respects_command_names_and_escaping(self):
        for tex in (r"\argmin", r"\argument", r"\\arg", r"\\arg\min"):
            with self.subTest(tex=tex):
                self.assertEqual(math_display._argument_operator(tex), tex)
        self.assertEqual(math_display._argument_operator(r"\arg_z"), r"\operatorname{arg}_z")

    def test_arg_adaptation_does_not_hide_unsupported_commands(self):
        diagnostics = []
        literal = r"$\arg\privateMinimum_x f(x)$"
        markup = math_display.render_text(literal, diagnostics=diagnostics)
        self.assertIn('class="math-fallback"', markup)
        self.assertIn(literal, markup)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["excerpt"], literal)
        self.assertIn(r"\privateMinimum", diagnostics[0]["reason"])

    def test_sized_named_bars_convert_at_the_authored_size(self):
        namespace = {"m": math_display.MATHML_NS}
        for tex in (r"\Bigl\lVert x \Bigr\rVert_{\mathcal H}^2",
                    r"\bigl\lVert x \bigr\rVert",
                    r"\Biggl\lVert x \Biggr\rVert",
                    r"\Bigl\vert x \Bigr\vert",
                    r"\big\Vert x \big\Vert"):
            with self.subTest(tex=tex):
                markup, reason = math_display._convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                expected = "‖" if "Vert" in tex else "|"
                fences = root.findall(".//m:mo", namespace)
                self.assertEqual([node.text for node in fences], [expected, expected])
                # Explicit sizing survives (a \left/\right rewrite would not fix it).
                for fence in fences:
                    self.assertTrue(fence.get("minsize"))
                    self.assertEqual(fence.get("minsize"), fence.get("maxsize"))
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
                if "_{" in tex:
                    scripted = root.find(".//m:msubsup", namespace)
                    self.assertEqual("".join(scripted[0].itertext()), "‖")
                    self.assertEqual("".join(scripted[1].itertext()), "H")
                    self.assertEqual(scripted[2].text, "2")

    def test_escaped_sizing_command_is_not_adapted(self):
        literal = r"\\Bigl\lVert"
        self.assertEqual(math_display._sized_named_bars(literal), literal)

    def test_unbraced_binomial_with_script_converts(self):
        for tex, script_tag in ((r"\binom nk^{-1}", "<msup"), (r"\binom{n}k^{-1}", "<msup"),
                                (r"\binom \alpha k_{i}", "<msub"), (r"\binom{n}{k}^{-1}", "<msup")):
            with self.subTest(tex=tex):
                markup, reason = math_display._convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                self.assertIn("<mfrac", markup)
                self.assertIn(script_tag, markup)

    def test_binomial_without_script_needs_no_grouping(self):
        self.assertEqual(math_display._group_scripted_binomials(r"\binom nk"), r"\binom nk")
        markup, reason = math_display._convert(r"\binom{n}{k}", "inline")
        self.assertIsNotNone(markup, reason)

    def test_malformed_and_unsupported_input_still_falls_back_with_reason(self):
        markup, reason = math_display._convert(r"\binom{", "inline")
        self.assertIsNone(markup)
        self.assertIn("unmatched brace", reason)
        markup, reason = math_display._convert(r"\cS_n", "inline")
        self.assertIsNone(markup)
        self.assertIn(r"\cS", reason)
        markup, reason = math_display._convert(r"\newcommand{\x}{1}", "inline")
        self.assertIsNone(markup)
        self.assertIn("macro", reason)

    def test_adaptation_keeps_the_original_tex_as_evidence(self):
        tex = r"\Bigl\lVert x \Bigr\rVert_{\mathcal H}"
        markup, _ = math_display._convert(tex, "inline")
        self.assertIn('encoding="application/x-tex"', markup)
        self.assertIn(r"\Bigl\lVert", markup)

    def test_render_text_reports_each_fallback_once(self):
        diagnostics = []
        html = math_display.render_text(
            r"For $x\in\cS$ the norm $\Bigl\lVert x\Bigr\rVert$ and $\binom nk^{-1}$.", diagnostics=diagnostics)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["display"], "inline")
        self.assertIn(r"\cS", diagnostics[0]["reason"])
        self.assertIn(r"$x\in\cS$", diagnostics[0]["excerpt"])
        self.assertEqual(html.count('class="math-fallback"'), 1)
        self.assertEqual(html.count("<math"), 2)

    def test_doubled_commands_do_not_silently_render_as_word_letters(self):
        for literal in (r"$\\mathbf{U}$", r"$\\frac{1}{n}$", r"$x + \\alpha$", r"$\\frac 1n$"):
            with self.subTest(literal=literal):
                # Exercise the decoded canonical text, as a JSON record supplies it.
                decoded = json.loads(json.dumps({"text": literal}))["text"]
                diagnostics = []
                markup = math_display.render_text(decoded, diagnostics)
                self.assertIn('class="math-fallback"', markup)
                self.assertNotIn("<math", markup)
                self.assertIn(literal, markup)
                self.assertEqual(diagnostics[0]["excerpt"], decoded)
                self.assertIn("likely doubled LaTeX command slash", diagnostics[0]["reason"])

    def test_decoded_norm_commands_do_not_silently_render_as_letters(self):
        for command in ("rVert", "rvert"):
            for opening, closing in (("$", "$"), ("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]")):
                with self.subTest(command=command, opening=opening):
                    # This JSON is valid, but its single backslash consumes r.
                    tex = json.loads('"x\\' + command + '_2"')
                    literal = opening + tex + closing
                    diagnostics = []
                    markup = math_display.render_text(literal, diagnostics)
                    self.assertIn('class="math-fallback"', markup)
                    self.assertNotIn("<math", markup)
                    self.assertIn(literal, markup)
                    self.assertEqual(len(diagnostics), 1)
                    self.assertEqual(diagnostics[0]["excerpt"], literal)
                    self.assertIn("likely decoded latex escape", diagnostics[0]["reason"].lower())
                    self.assertIn("\\" + command, diagnostics[0]["reason"])

    def test_decoded_common_commands_do_not_silently_render_as_letters(self):
        for command in ("theta", "tau", "times", "to", "tfrac{1}{2}", "rho", "right)", "rightarrow",
                        "rangle", "rfloor", "nabla", "notin"):
            with self.subTest(command=command):
                # Valid JSON: the single backslash decodes \t, \r or \n.
                tex = json.loads('"(x\\' + command + ' y"')
                diagnostics = []
                markup = math_display.render_text("$" + tex + "$", diagnostics)
                self.assertIn('class="math-fallback"', markup)
                self.assertEqual(len(diagnostics), 1)
                self.assertIn("likely decoded latex escape", diagnostics[0]["reason"].lower())

    def test_legitimate_math_whitespace_and_commands_are_not_escape_warnings(self):
        for tex in (r"\lVert x\rVert_2", r"\lvert x\rvert",
                    "x +\n y", "x +\r y", "x +\t y", "x +\r\nVert",
                    "x +\rVertex", "x +\rvertical", "x +\n" + "eq", "x +\t" + "ext{y}",
                    "x =\t" + "o(1)", "x =\t" + "o (1)", "x =\t" + "o\n(1)",
                    "x =\t" + "o\t(1)", "x +\t" + "hetas", r"\theta\to\rho\nabla", "x +\n" + "u",
                    "x +\r\n" + "ho"):
            with self.subTest(tex=tex):
                diagnostics = []
                markup = math_display.render_text("$" + tex + "$", diagnostics)
                self.assertEqual(diagnostics, [])
                self.assertIn("<math", markup)

    def test_control_whitespace_in_prose_does_not_become_math_diagnostics(self):
        literal = "A carriage-return line break:\rVert and a tab:\t" + "ext."
        diagnostics = []
        self.assertEqual(math_display.render_text(literal, diagnostics), literal)
        self.assertEqual(diagnostics, [])

    def test_paired_doubled_delimiters_are_located_without_losing_math(self):
        for literal in (r"\\(x_n\\to 0\\)", r"\\[\\frac{1}{n}\\]"):
            with self.subTest(literal=literal):
                diagnostics = []
                markup = math_display.render_text("Before " + literal + " after $y$.", diagnostics)
                self.assertIn('class="math-fallback"', markup)
                self.assertIn(literal, markup)
                self.assertEqual(markup.count("<math"), 1)
                self.assertEqual(len(diagnostics), 1)
                self.assertEqual(diagnostics[0]["excerpt"], literal)
                self.assertIn("doubled LaTeX delimiter", diagnostics[0]["reason"])

    def test_correct_delimiters_and_commands_keep_their_rendering_and_annotation(self):
        literal = r"\(\mathbf{U}\) and $\frac{1}{n}$ and \[\alpha\to0\]"
        diagnostics = []
        markup = math_display.render_text(literal, diagnostics)
        self.assertEqual(diagnostics, [])
        self.assertEqual(markup.count("<math"), 3)
        self.assertIn("<mfrac", markup)
        self.assertIn(r'encoding="application/x-tex">\mathbf{U}</annotation>', markup)

    def test_legitimate_row_breaks_are_not_misdiagnosed_as_doubled_commands(self):
        namespace = {"m": math_display.MATHML_NS}
        for tex in (r"\begin{matrix}a\\beta\end{matrix}",
                    r"\begin{align}x&=1\\frac&=2\end{align}",
                    r"\substack{a\\beta}"):
            with self.subTest(tex=tex):
                markup, reason = math_display._convert(tex, "block")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                self.assertGreaterEqual(len(root.findall(".//m:mtr", namespace)), 2)
                self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
        # The standalone display adapter also preserves a bare next-row word.
        markup, reason = math_display._convert(r"\begin{aligned}x&=1\\beta&=2\end{aligned}", "block")
        self.assertIsNotNone(markup, reason)
        self.assertEqual(len(ET.fromstring(markup).findall(".//m:mtr", namespace)), 2)

    def test_commands_after_a_row_environment_are_still_checked(self):
        tex = r"\begin{matrix}a\\beta\end{matrix}+\\mathbf{U}"
        markup, reason = math_display._convert(tex, "block")
        self.assertIsNone(markup)
        self.assertIn("likely doubled LaTeX command slash", reason)

    def test_literal_prose_backslashes_are_not_reported_as_math(self):
        literal = r"Open C:\papers\main.tex or \\server\share; literal \\mathbf and an unmatched \\( path."
        diagnostics = []
        self.assertEqual(math_display.render_text(literal, diagnostics), literal)
        self.assertEqual(diagnostics, [])

    def test_groups_repeated_macro_failures_and_keeps_all_record_locations(self):
        diagnostics = []
        for record_id, literal in (("a", r"$x\in\privateClass$ and $y\in\privateClass$"),
                                   ("b", r"$z\in\privateClass$ and $z\in\anotherClass$")):
            failures = []
            math_display.render_text(literal, failures)
            diagnostics.extend({"collection": "items", "id": record_id, "field": "statement", **row}
                               for row in failures)
        original = deepcopy(diagnostics)
        groups = math_display.group_diagnostics(diagnostics)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["count"], 3)
        self.assertEqual(groups[0]["locations"], [
            {"collection": "items", "id": "a", "field": "statement"},
            {"collection": "items", "id": "b", "field": "statement"}])
        self.assertIn(r"\privateClass", groups[0]["reason"])
        self.assertEqual(groups[0]["example"], r"$x\in\privateClass$")
        self.assertEqual(diagnostics, original)


class ScopeDisplayTests(unittest.TestCase):
    def test_short_lead_discloses_only_later_paragraphs(self):
        scope = 'Coverage <all> with $x < y$.\n\nLimits "apply" to $z$.'
        result = math_display.render_scope(scope)
        self.assertIn("Coverage &lt;all&gt;", result["lead_html"])
        self.assertIn("<math", result["lead_html"])
        self.assertIn('encoding="application/x-tex">x &lt; y</annotation>', result["lead_html"])
        self.assertNotIn("Limits", result["lead_html"])
        self.assertIn("Limits &quot;apply&quot;", result["details_html"])
        self.assertIn("<math", result["details_html"])
        self.assertNotIn("Coverage", result["details_html"])

    def test_cutoff_keeps_the_whole_formula_and_discloses_full_original(self):
        prefix = " ".join(["word"] * 99)
        scope = prefix + r" $x + y$ follows here." + "\n\nLater limits."
        diagnostics = []
        result = math_display.render_scope(scope, diagnostics=diagnostics)
        self.assertIn('encoding="application/x-tex">x + y</annotation>', result["lead_html"])
        self.assertTrue(result["lead_html"].endswith("</math>…"))
        self.assertNotIn("follows", result["lead_html"])
        self.assertEqual(result["details_html"], math_display.render_text(scope))
        self.assertEqual(diagnostics, [])

    def test_paragraph_breaks_inside_explicit_math_do_not_split_the_lead(self):
        for opening, closing in (("$", "$"), ("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]")):
            with self.subTest(opening=opening):
                scope = "Coverage " + opening + "x +\n\n y" + closing + " continues.\n\nLater limits."
                diagnostics = []
                result = math_display.render_scope(scope, diagnostics=diagnostics)
                self.assertIn("continues.", result["lead_html"])
                self.assertIn('encoding="application/x-tex">x +\n\n y</annotation>', result["lead_html"])
                self.assertEqual(result["details_html"], "Later limits.")
                self.assertEqual(diagnostics, [])

    def test_repeated_preview_diagnoses_each_original_occurrence_once(self):
        prefix = " ".join(["word"] * 99)
        scope = prefix + r" $x + \privateClass$ and $x + \privateClass$."
        diagnostics = []
        result = math_display.render_scope(scope, diagnostics=diagnostics)
        self.assertEqual(result["lead_html"].count('class="math-fallback"'), 1)
        self.assertEqual(result["details_html"].count('class="math-fallback"'), 2)
        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(all(row["excerpt"] == r"$x + \privateClass$" for row in diagnostics))

    def test_unmatched_math_tail_stays_visible_across_blank_lines_and_cutoff(self):
        for prefix in ("Coverage", " ".join(["word"] * 99)):
            with self.subTest(long_lead=prefix != "Coverage"):
                scope = prefix + ' $x +\n\n <unclosed> formula with more words'
                diagnostics = []
                result = math_display.render_scope(scope, diagnostics=diagnostics)
                self.assertIn('class="math-fallback"', result["lead_html"])
                self.assertIn("&lt;unclosed&gt; formula with more words", result["lead_html"])
                self.assertEqual(len(diagnostics), 1)
                self.assertIn("no matching closing delimiter", diagnostics[0]["reason"])
                self.assertEqual(result["details_html"], "" if prefix == "Coverage"
                                 else math_display.render_text(scope))

    def test_plain_prose_retains_the_existing_preview_limit(self):
        words = " ".join(["word"] * 100)
        self.assertEqual(math_display.render_scope(words), {"lead_html": words, "details_html": ""})
        scope = words + " last"
        self.assertEqual(math_display.render_scope(scope), {"lead_html": words + "…", "details_html": scope})
        self.assertEqual(math_display.render_scope(""), {"lead_html": "", "details_html": ""})


class PrepareDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "main.tex").write_text(
            "\\begin{lemma}\\label{lem:norm}\nThe norm bound holds.\n\\end{lemma}\n"
            "\\begin{theorem}\\label{thm:main}\nThe main bound holds.\n\\end{theorem}\n",
            encoding="utf-8")
        self.seed = {
            "schema_version": 3, "title": "Math diagnostics fixture",
            "scope": "Two synthetic declarations.",
            "source": {"title": "Synthetic manuscript", "file": "main.tex"},
            "items": [
                {"id": "norm-bound", "kind": "lemma", "label": "Lemma 1", "caption": "Norm bound",
                 "statement": {"text": r"The norm $\Bigl\lVert x\Bigr\rVert_{\mathcal H}$ is finite.", "form": "synopsis"},
                 "source": {"label": "lem:norm", "start_line": 1, "end_line": 1}},
                {"id": "main-bound", "kind": "theorem", "label": "Theorem 1", "caption": "Main bound",
                 "statement": {"text": r"The private set $\cS_n$ is compact.", "form": "synopsis"},
                 "source": {"label": "thm:main", "start_line": 2, "end_line": 2}},
            ],
            "uses": [
                {"id": "use-norm-main", "from": "norm-bound", "to": "main-bound", "type": "dependency",
                 "reason": r"The display $\binom nk^{-1}$ bounds $\cD_n$.",
                 "source": {"start_line": 1, "end_line": 2}},
            ],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        return records.prepare_records(records.normalize(deepcopy(self.seed), self.base), self.base)

    def test_diagnostics_identify_the_record_and_field(self):
        prepared = self.prepare()
        entries = {(row["collection"], row["id"], row["field"]) for row in prepared["math_diagnostics"]}
        self.assertEqual(entries, {("items", "main-bound", "statement"), ("uses", "use-norm-main", "reason")})
        for row in prepared["math_diagnostics"]:
            self.assertIn(r"\c", row["reason"])
            self.assertTrue(row["excerpt"])
        for row in prepared["items"] + prepared["uses"]:
            self.assertNotIn("statement_diagnostics", row)
            self.assertNotIn("reason_diagnostics", row)

    def test_adapted_expressions_render_and_keep_record_text(self):
        prepared = self.prepare()
        lemma = next(row for row in prepared["items"] if row["id"] == "norm-bound")
        use = prepared["uses"][0]
        self.assertEqual(lemma["statement"], r"The norm $\Bigl\lVert x\Bigr\rVert_{\mathcal H}$ is finite.")
        self.assertIn("<math", lemma["statement_html"])
        self.assertIn("<math", use["reason_html"])
        self.assertEqual(use["reason"], r"The display $\binom nk^{-1}$ bounds $\cD_n$.")
        self.assertIn(r"\cD_n", use["reason_html"])  # unconverted macro stays a labeled fallback
        self.assertIn('class="math-fallback"', use["reason_html"])

    def test_aggregated_warning_locates_failures_without_per_row_noise(self):
        prepared = self.prepare()
        math_warnings = [text for text in prepared["warnings"] if "could not be typeset" in text]
        self.assertEqual(len(math_warnings), 1)
        self.assertIn("2 LaTeX expressions", math_warnings[0])
        self.assertIn("main-bound (statement)", math_warnings[0])
        self.assertIn("use-norm-main (reason)", math_warnings[0])
        self.assertNotIn("A dependency reason", math_warnings[0])

    def test_display_adaptation_leaves_snapshot_identity_and_comparison_unchanged(self):
        statement = (r"\[\begin{aligned}a&=b\\c&=d\end{aligned}\] "
                     r"$\Big\langle U^{\!\top},v\Big\rangle$ "
                     r"$\mathbb E\!\left[X\right]$ and $\int\!\!\int f(x,y)\,dx\,dy$.")
        self.seed["items"][0]["statement"]["text"] = statement
        data = records.normalize(deepcopy(self.seed), self.base)
        snapshot = data["snapshot_id"]
        targets = [{"collection": group, "id": row["id"]}
                   for group in ("items", "uses") for row in data[group]]
        data["observations"].extend(records.make_observations(
            data, targets, reviewer="Synthetic source reviewer", note="Compared the synthetic passages."))
        data = records.validate_records(data)
        original = deepcopy(data)
        prepared = records.prepare_records(data, self.base)
        self.assertEqual(data, original)
        self.assertEqual(prepared["items"][0]["statement"], statement)
        self.assertEqual(prepared["items"][0]["statement_html"].count("<math"), 4)
        self.assertNotIn('class="math-fallback"', prepared["items"][0]["statement_html"])
        self.assertEqual(prepared["build_context"]["input_snapshot"], snapshot)
        self.assertEqual(prepared["build_context"]["source_comparison"]["status"], "complete")
        self.assertTrue(all(row["fidelity"] == "matched"
                            for row in prepared["items"] + prepared["uses"]))

    def test_sized_braces_leave_records_sources_and_comparisons_unchanged(self):
        statement = r"The set $\Bigl\{x\Bigr\}_{i}^{2}$ is finite."
        reason = r"The target uses $\biggl\lbrace\frac{x}{y}\biggr\rbrace$."
        self.seed["items"][0]["statement"]["text"] = statement
        self.seed["items"][1]["statement"]["text"] = "The main bound holds."
        self.seed["uses"][0]["reason"] = reason
        data = records.normalize(deepcopy(self.seed), self.base)
        targets = [{"collection": group, "id": row["id"]}
                   for group in ("items", "uses") for row in data[group]]
        data["observations"].extend(records.make_observations(
            data, targets, reviewer="Synthetic reviewer", note="Compared the synthetic passages."))
        data = records.validate_records(data)
        original = deepcopy(data)
        digests = [records.target_digest(data, row["collection"], row["id"]) for row in targets]
        prepared = records.prepare_records(data, self.base)
        self.assertEqual(data, original)
        self.assertEqual(prepared["items"][0]["statement"], statement)
        self.assertEqual(prepared["uses"][0]["reason"], reason)
        namespace = {"m": math_display.MATHML_NS}
        for fragment in (prepared["items"][0]["statement_html"], prepared["uses"][0]["reason_html"]):
            root = ET.fromstring("<div>" + fragment + "</div>")
            self.assertEqual([node.text for node in root.findall(".//m:mo", namespace)], ["{", "}"])
        self.assertEqual(prepared["math_diagnostics"], [])
        self.assertEqual(prepared["build_context"]["input_snapshot"], original["snapshot_id"])
        self.assertEqual(prepared["build_context"]["source_comparison"]["status"], "complete")
        self.assertTrue(all(row["fidelity"] == "matched" for row in prepared["items"] + prepared["uses"]))
        self.assertEqual([records.target_digest(data, row["collection"], row["id"]) for row in targets], digests)

    def test_independence_and_spacing_fallback_leave_records_and_comparisons_unchanged(self):
        independence = r"The variables satisfy \(R\perp\!\!\perp S'\mid X\)."
        spacing = r"The product is $x\!y$."
        self.seed["items"][0]["statement"]["text"] = independence
        self.seed["items"][1]["statement"]["text"] = spacing
        self.seed["uses"][0]["reason"] = "The target uses the stated condition."
        data = records.normalize(deepcopy(self.seed), self.base)
        targets = [{"collection": group, "id": row["id"]}
                   for group in ("items", "uses") for row in data[group]]
        data["observations"].extend(records.make_observations(
            data, targets, reviewer="Synthetic reviewer", note="Compared the synthetic passages."))
        data = records.validate_records(data)
        original = deepcopy(data)
        digests = [records.target_digest(data, row["collection"], row["id"]) for row in targets]
        prepared = records.prepare_records(data, self.base)
        lemma, theorem = prepared["items"]
        self.assertEqual(lemma["statement"], independence)
        self.assertIn("<mo>⫫</mo>", lemma["statement_html"])
        self.assertEqual(theorem["statement"], spacing)
        self.assertIn('class="math-fallback"', theorem["statement_html"])
        self.assertEqual([(row["id"], row["field"]) for row in prepared["math_diagnostics"]],
                         [("main-bound", "statement")])
        self.assertEqual(prepared["build_context"]["input_snapshot"], original["snapshot_id"])
        self.assertTrue(all(row["fidelity"] == "matched" for row in prepared["items"] + prepared["uses"]))
        self.assertEqual(data, original)
        self.assertEqual([records.target_digest(data, row["collection"], row["id"]) for row in targets], digests)

    def test_corrupted_escaping_is_located_but_never_rewrites_canonical_text(self):
        literal = r"The map is $\\mathbf{U}$ with \\(x_n\\to0\\)."
        self.seed["items"][0]["statement"]["text"] = literal
        data = records.normalize(deepcopy(self.seed), self.base)
        original = deepcopy(data)
        prepared = records.prepare_records(data, self.base)
        lemma = next(row for row in prepared["items"] if row["id"] == "norm-bound")
        failures = [row for row in prepared["math_diagnostics"] if row["id"] == "norm-bound"]
        self.assertEqual(data, original)
        self.assertEqual(lemma["statement"], literal)
        self.assertEqual(lemma["statement_html"].count('class="math-fallback"'), 2)
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(row["collection"] == "items" and row["field"] == "statement"
                            for row in failures))
        self.assertEqual(prepared["build_context"]["input_snapshot"], original["snapshot_id"])

    def test_decoded_escape_fallback_preserves_records_and_comparisons(self):
        literal = r"The norm $\lVert x" + "\rVert_2$ is finite."
        self.seed["items"][0]["statement"]["text"] = literal
        data = records.normalize(deepcopy(self.seed), self.base)
        data["observations"].extend(records.make_observations(
            data, [{"collection": "items", "id": "norm-bound"}],
            reviewer="Synthetic reviewer", note="Compared the synthetic source."))
        data = records.validate_records(data)
        original = deepcopy(data)
        prepared = records.prepare_records(data, self.base)
        lemma = next(row for row in prepared["items"] if row["id"] == "norm-bound")
        failures = [row for row in prepared["math_diagnostics"] if row["id"] == "norm-bound"]
        self.assertEqual(data, original)
        self.assertEqual(lemma["statement"], literal)
        self.assertEqual(lemma["fidelity"], "matched")
        self.assertIn('class="math-fallback"', lemma["statement_html"])
        self.assertEqual(len(failures), 1)
        self.assertEqual((failures[0]["collection"], failures[0]["field"]), ("items", "statement"))
        self.assertIn("likely decoded latex escape", failures[0]["reason"].lower())
        self.assertEqual(prepared["build_context"]["input_snapshot"], original["snapshot_id"])


@unittest.skipUnless(NODE, "node is needed for the renderer")
class RendererDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        fixture = SKILL / "tests" / "fixtures" / "schema3-intermediates.json"
        self.prepared = records.prepare_records(
            records.validate_records(json.loads(fixture.read_text(encoding="utf-8"))), fixture.parent)
        self.input = self.base / "prepared.json"
        self.output = self.base / "overview.html"

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, prepared, expect_success=True):
        self.input.write_text(json.dumps(prepared, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([NODE, str(RENDERER), str(self.input), str(self.output)],
                                capture_output=True, text=True, encoding="utf-8")
        if not expect_success:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return json.loads(result.stderr), None
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout), self.output.read_text(encoding="utf-8")

    def test_math_diagnostics_render_a_collapsible_note(self):
        prepared = deepcopy(self.prepared)
        prepared["math_diagnostics"] = [
            {"collection": "items", "id": "key-bound", "field": "statement",
             "excerpt": r"$\cS_n$", "reason": "unsupported command remains literal: \\cS"}]
        receipt, html = self.render(prepared)
        self.assertIn("Math display notes", html)
        self.assertIn("key-bound", html)
        self.assertIn("statement", html)

    def test_malformed_math_diagnostics_are_rejected(self):
        prepared = deepcopy(self.prepared)
        prepared["math_diagnostics"] = [{"id": "key-bound"}]
        receipt, _ = self.render(prepared, expect_success=False)
        self.assertIn("math_diagnostics", receipt["error"])

    def test_absent_math_diagnostics_render_no_note(self):
        _, html = self.render(self.prepared)
        self.assertNotIn("Math display notes", html)

    def test_render_receipt_carries_the_diagnostics(self):
        fixture = SKILL / "tests" / "fixtures" / "schema3-intermediates.json"
        data = records.validate_records(json.loads(fixture.read_text(encoding="utf-8")))
        row = next(item for item in data["items"] if item["id"] == "key-bound")
        row["statement"]["text"] = r"The private class $\cK$ is closed."
        data.pop("snapshot_id", None)
        data = records.validate_records(data)
        output = self.base / "artifact.html"
        receipt = overview.render_dataset(data, fixture.parent, output)
        self.assertEqual([(d["id"], d["field"]) for d in receipt["math_diagnostics"]],
                         [("key-bound", "statement")])
        self.assertIn("key-bound (statement)", receipt["warnings"][-1])

    def test_render_receipt_locates_decoded_escape_fallback_without_extra_scan(self):
        fixture = SKILL / "tests" / "fixtures" / "schema3-intermediates.json"
        data = records.validate_records(json.loads(fixture.read_text(encoding="utf-8")))
        row = next(item for item in data["items"] if item["id"] == "key-bound")
        literal = r"The bound is $\lVert x" + "\rVert_2$."
        row["statement"]["text"] = literal
        data.pop("snapshot_id", None)
        data = records.validate_records(data)
        output = self.base / "decoded-escape.html"
        receipt = overview.render_dataset(data, fixture.parent, output)
        self.assertEqual(overview.compact_render_receipt(receipt)["math_diagnostic_count"], 1)
        diagnostic, = receipt["math_diagnostics"]
        self.assertEqual((diagnostic["collection"], diagnostic["id"], diagnostic["field"]),
                         ("items", "key-bound", "statement"))
        self.assertIn("likely decoded latex escape", diagnostic["reason"].lower())
        self.assertEqual(diagnostic["excerpt"], literal[len("The bound is "):-1])
        self.assertIn("key-bound (statement)", receipt["warnings"][-1])
        self.assertIn("Math display notes", output.read_text(encoding="utf-8"))

    def test_render_receipt_distinguishes_independence_from_unsupported_spacing(self):
        fixture = SKILL / "tests" / "fixtures" / "schema3-intermediates.json"
        data = records.validate_records(json.loads(fixture.read_text(encoding="utf-8")))
        row = next(item for item in data["items"] if item["id"] == "key-bound")
        literal = r"Under \(R\perp\!\!\perp S'\mid X\), the product is $x\!y$."
        row["statement"]["text"] = literal
        data.pop("snapshot_id", None)
        data = records.validate_records(data)
        original = deepcopy(data)
        output = self.base / "negative-spacing.html"
        receipt = overview.render_dataset(data, fixture.parent, output)
        self.assertEqual(overview.compact_render_receipt(receipt)["math_diagnostic_count"], 1)
        diagnostic, = receipt["math_diagnostics"]
        self.assertEqual((diagnostic["collection"], diagnostic["id"], diagnostic["field"]),
                         ("items", "key-bound", "statement"))
        self.assertEqual(diagnostic["excerpt"], r"$x\!y$")
        self.assertIn("unsupported negative spacing", diagnostic["reason"])
        html = output.read_text(encoding="utf-8")
        self.assertIn("<mo>⫫</mo>", html)
        self.assertNotIn('width="negativethinmathspace"', html)
        self.assertIn("Math display notes", html)
        self.assertEqual(data, original)


if __name__ == "__main__":
    unittest.main()
