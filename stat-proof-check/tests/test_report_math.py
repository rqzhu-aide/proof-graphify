from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("proofcheck_math", ROOT / "scripts/proofcheck_math.py")
math = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(math)

ORIGINAL_C001 = (r"\Pr(\sum_{i=1}^nX_i\ge\beta n)\le\binom{\beta n}{k}^{-1}"
                 r"\sum_{S\subseteq[n],\ |S|=k}\Pr(\bigwedge_{i\in S}(X_i=1))")


class MathRenderingTests(unittest.TestCase):
    def setUp(self):
        math._convert.cache_clear()

    def document(self, text):
        return ET.fromstring("<div>" + math.render_text(text) + "</div>")

    def formulas(self, document):
        return list(document.iter("{" + math.MATHML_NS + "}math"))

    def test_common_statistical_notation_has_real_math_structure(self):
        document = self.document(r"Assume $X_{n,j} \to 0$ and $\hat\theta_n=\frac{1}{n}\sum_{j=1}^n X_{n,j}$. Then $\Pr(|X_n|>\varepsilon)\le\frac{\mathbb{E}[X_n^2]}{\varepsilon^2}$.")
        self.assertEqual(3, len(self.formulas(document)))
        for name in ("msub", "mfrac", "mover", "msup"):
            self.assertTrue(list(document.iter("{" + math.MATHML_NS + "}" + name)), name)
        self.assertNotIn("math-fallback", math.render_text(r"$\max_{1\le j\le m_n}|X_{n,j}|\to0$"))

    def test_inline_and_display_delimiters_preserve_original_tex(self):
        expressions = [("$x_i$", "inline", "x_i"), (r"\(\hat\theta\)", "inline", r"\hat\theta"),
                       ("$$x^2$$", "block", "x^2"), (r"\[\frac{a}{b}\]", "block", r"\frac{a}{b}")]
        document = self.document(" and ".join(row[0] for row in expressions))
        formulas = self.formulas(document)
        self.assertEqual(4, len(formulas))
        for node, (_, display, tex) in zip(formulas, expressions):
            self.assertEqual(display, node.get("display"))
            annotation = node.find(".//{" + math.MATHML_NS + "}annotation")
            self.assertEqual("application/x-tex", annotation.get("encoding"))
            self.assertEqual(tex, annotation.text)
            self.assertEqual("LaTeX: " + tex, node.get("aria-label"))

    def test_single_negative_thin_space_before_ordinary_opening_fences(self):
        expressions = [
            r"\exp\!\left\{x\right\}", r"E\!\left\lbrace x\right\rbrace",
            r"P(\|\delta(t,t')\|_\infty>u)\le2k\exp\!\left\{-\frac{q u^2}{2L\|t-t'\|_2+(4G/3)u}\right\}.",
            r"(\tilde\theta^*-\hat\theta)^2/\sigma_n^2=O_P\!\big(\mathrm{polylog}(n/s)\max\{s^{-2a},(s/n)^{1/3}\}\big)\to_p0",
        ]
        for size in ("big", "Big", "bigg", "Bigg"):
            for opening, closing in (("(", ")"), ("[", "]"), (r"\{", r"\}"),
                                     (r"\lbrace", r"\rbrace")):
                expressions.append("E\\!\\" + size + opening + " x\\" + size + closing)
        for tex in expressions:
            with self.subTest(tex=tex):
                document = self.document("$" + tex + "$")
                formulas = self.formulas(document)
                self.assertEqual(1, len(formulas))
                self.assertEqual(tex, formulas[0].find(".//{" + math.MATHML_NS + "}annotation").text)
                self.assertEqual("LaTeX: " + tex, formulas[0].get("aria-label"))
        for tex in (r"\eta_n\ge{}^{4}\!\sqrt{s/n}", r"E\!\!\left\{x\right\}",
                    r"E{\!}\!\big(x\big)", r"E\hspace{-1em}\!\big(x\big)",
                    r"E\!\big\}", r"E\!\big\langle x"):
            with self.subTest(tex=tex):
                document = self.document("$" + tex + "$")
                self.assertFalse(self.formulas(document))
                self.assertEqual("$" + tex + "$", document.find(".//code").text)

    def test_opening_fence_spacing_keeps_nonordinary_converter_shapes_unsupported(self):
        space = '<mspace width="negativethinmathspace"/>'
        fence = '<mo minsize="1.2em" maxsize="1.2em">(</mo>'
        cases = [(space, '<mo minsize="' + size + '" maxsize="' + size + '">' + text + '</mo>', True)
                 for size in ("1.2em", "1.623em", "2.047em", "2.470em")
                 for text in ("(", "[", "{", r"\{", r"\lbrace")]
        cases += [
            (space, '<mo fence="true" form="prefix">{</mo>', True),
            (space.replace('/>', '>x</mspace>'), fence, False),
            (space + "x", fence, False),
            (space.replace('/>', '><mi>x</mi></mspace>'), fence, False),
            (space.replace('/>', ' height="1em"/>'), fence, False),
            (space, fence.replace('maxsize="1.2em"', 'maxsize="1.623em"'), False),
            (space, fence.replace("1.2em", "2em"), False),
            (space, fence.replace('<mo ', '<mo fence="true" '), False),
            (space, fence.replace(">(</mo>", "><mi>x</mi></mo>"), False),
            (space * 2, fence, False),
        ]
        tex = r"original \!\{x & y\}"
        cases += [(space.replace("negativethinmathspace", width), fence, False)
                  for width in ("-1em", "negativemediummathspace")]
        variants = [(spacing, opening, accepted, parent, namespace)
                    for spacing, opening, accepted in cases
                    for parent in ("mrow", "mtd")
                    for namespace in ("", ' xmlns="' + math.MATHML_NS + '"')]
        for spacing, opening, accepted, parent, namespace in variants:
            raw = ("<math" + namespace + "><" + parent + "><mi>E</mi>" + spacing
                   + opening + "<mi>x</mi></" + parent + "></math>")
            with self.subTest(spacing=spacing, opening=opening, parent=parent, namespace=namespace):
                if not accepted:
                    with self.assertRaisesRegex(ValueError, "unsupported negative spacing"):
                        math._safe_mathml(raw, tex, "inline")
                    continue
                node = ET.fromstring(math._safe_mathml(raw, tex, "inline"))
                self.assertEqual(tex, node.find(".//{" + math.MATHML_NS + "}annotation").text)
                self.assertEqual("LaTeX: " + tex, node.get("aria-label"))

    def test_bounded_bracket_norm_and_operand_integral_spacing_preserves_source_and_tree(self):
        ns = "{" + math.MATHML_NS + "}"
        for tex in (r"k\in[\![1,\lfloor T\rfloor]\!]", r"k\in[\![1,T]\!]",
                    r"\int\!\int C_k\lesssim(\prod h_l)^{-1}",
                    r"\int\!\int C_k\lesssim(\prod_l h_l)^{-2+1/(dH)}",
                    r"\operatorname{Var}(T^{-1}\!\int_0^T F(X_s)ds)\asymp T^{2H-2},",
                    r"[\!{[x]}\!]", r"k\in[\!\left[1,T\right]\!]",
                    r"x\!\int f", r"2\!\int f", r"x_i^2\!\int_A^B f",
                    r"\|\!|x|\!\|", r"\|\!|x|\!\|_A", r"\|\!|x|\!\|^2",
                    r"\|\!|x|\!\|_A^2", r"\left\|\!|x|\!\right\|_A^2",
                    r"p_t(\ell;y)\le t^{-dH}\exp\{C(1+t^\eta\|\!|\ell|\!\|_{\mathbb C^\gamma}^2)-c|y-\ell(t)|^2/t^{2H}\}"):
            with self.subTest(tex=tex):
                diagnostics = []
                actual = ET.fromstring(math.render_text(r"\[" + tex + r"\]", diagnostics))
                expected = ET.fromstring(math.render_text(r"\[" + tex.replace(r"\!", "") + r"\]"))
                self.assertEqual(diagnostics, [])
                self.assertEqual(actual.find(".//" + ns + "annotation").text, tex)
                self.assertEqual(actual.get("aria-label"), "LaTeX: " + tex)
                for root in (actual, expected):
                    root.attrib.pop("aria-label")
                    root.find(".//" + ns + "annotation").text = "source"
                self.assertEqual(ET.tostring(actual), ET.tostring(expected))
        for tex in (r"x\!y", r"x\!\!\int f", r"[\!\![x]\!]", r"[\![x]\!\!]",
                    r"\int_A\!\int_B f", r"x\hspace{-0.2em}\int f",
                    r"\|\!\!|x|\!\|", r"\|\!|x|\!\!\|", r"|\!|x|\!|",
                    r"\|\!\|x\|\!\|", r"\|\hspace{-0.2em}|x|\!\|"):
            with self.subTest(tex=tex):
                self.assertIn("math-fallback", math.render_text("$" + tex + "$"))

    def test_archived_sized_floors_preserve_the_equation_and_source(self):
        expressions = (
            r"S\sum_{p}\log p\sum_{r<R}\Bigl\lfloor\frac rp\Bigr\rfloor\ge S\sum_p\log p\Bigl(\frac{R(R-1)}{2p}-R\Bigr)=\frac12SR^{2}\sum_p\frac{\log p}{p}-O(X^{3}),",
            r"\sum_{\substack{p\le X\\ \chi(p)=-1}}\log p\sum_{r,s}\min\Bigl(\Bigl\lfloor\frac rp\Bigr\rfloor,S-1-s\Bigr)\le \frac12\log\det G\le \frac12RS(R+S)\log(2N\sqrt q)+O(X^{3}),",
            r"\sum_{r,s}h_{r,s}\ge S\sum_{r<R}\Bigl\lfloor\frac rp\Bigr\rfloor-\sum_{r<R}\Bigl(\frac rp\Bigr)^{2}\ge S\sum_{r<R}\Bigl\lfloor\frac rp\Bigr\rfloor-\frac{R^{3}}{3p^{2}}.",
            r"e_p\ \ge\ 2\sum_{0\le r<R}\sum_{0\le s<S}\min\Bigl(\Bigl\lfloor\frac{r}{p}\Bigr\rfloor,\,S-1-s\Bigr).",
        )
        ns = "{" + math.MATHML_NS + "}"
        for tex in expressions:
            with self.subTest(tex=tex):
                diagnostics = []
                actual = ET.fromstring(math.render_text("$$" + tex + "$$", diagnostics))
                equivalent = tex.replace(r"\lfloor", "⌊").replace(r"\rfloor", "⌋")
                expected = ET.fromstring(math.render_text("$$" + equivalent + "$$"))
                self.assertEqual(diagnostics, [])
                self.assertEqual(actual.find(".//" + ns + "annotation").text, tex)
                self.assertEqual(actual.get("aria-label"), "LaTeX: " + tex)
                for root in (actual, expected):
                    root.attrib.pop("aria-label")
                    root.find(".//" + ns + "annotation").text = "source"
                self.assertEqual(ET.tostring(actual), ET.tostring(expected))

    def test_bracket_norm_and_integral_spacing_keeps_strict_space_and_neighbor_boundaries(self):
        space = '<mspace width="negativethinmathspace"/>'
        shapes = (('<mo>‖</mo>', '<mo>|</mo>'),
                  ('<mo>|</mo>', '<msubsup><mo>‖</mo><mi>A</mi><mn>2</mn></msubsup>'),
                  ('<mo stretchy="false">[</mo>', '<mo stretchy="false">[</mo>'),
                  ('<mrow><mo>]</mo></mrow>', '<mo>]</mo>'),
                  ('<msup><mi>T</mi><mn>2</mn></msup>',
                   '<msubsup><mo>∫</mo><mn>0</mn><mi>T</mi></msubsup>'))
        bad_spaces = (space.replace('/>', ' height="1em"/>'), space.replace('/>', '>x</mspace>'),
                      space + 'tail', space.replace('/>', '><mi>x</mi></mspace>'),
                      space.replace('mspace', 'f:mspace'), space * 2,
                      space.replace('negativethinmathspace', '-1em'),
                      space.replace('negativethinmathspace', 'negativemediummathspace'))
        for left, right in shapes:
            for parent in ("mrow", "mtd"):
                for namespace in ("", ' xmlns="' + math.MATHML_NS + '"'):
                    raw = ('<math' + namespace + ' xmlns:f="urn:foreign"><' + parent + '>'
                           + left + space + right + '</' + parent + '></math>')
                    with self.subTest(raw=raw):
                        self.assertEqual(math._safe_mathml(raw, "original", "inline"),
                                         math._safe_mathml(raw.replace(space, ''), "original", "inline"))
                    for bad in bad_spaces:
                        with self.subTest(raw=raw, bad=bad), self.assertRaises(ValueError):
                            math._safe_mathml(raw.replace(space, bad), "original", "inline")

    def test_powered_binomial_and_exact_c001_keep_grouped_base_and_original_tex(self):
        # Exact probes from the frozen paper's five-probe rendering diagnosis.
        plain = r"\binom{\beta n}{k}"
        powered = plain + "^{-1}"
        grouped = "{" + plain + "}^{-1}"
        for tex in (plain, powered, grouped, ORIGINAL_C001,
                    ORIGINAL_C001.replace(powered, grouped)):
            with self.subTest(tex=tex):
                document = self.document("$" + tex + "$")
                formulas = self.formulas(document)
                self.assertEqual(1, len(formulas))
                node = formulas[0]
                ns = "{" + math.MATHML_NS + "}"
                self.assertEqual(tex, node.find(".//" + ns + "annotation").text)
                self.assertEqual("LaTeX: " + tex, node.get("aria-label"))
                binomial = next(node.iter(ns + "mfrac"))
                self.assertEqual("0", binomial.get("linethickness"))
                powers = list(node.iter(ns + "msup"))
                self.assertEqual(0 if tex == plain else 1, len(powers))
                for power in powers:
                    self.assertEqual(2, len(power))
                    self.assertEqual(["mo", "mfrac", "mo"],
                                     [child.tag.removeprefix(ns) for child in power[0]])
                    self.assertEqual("(", power[0][0].text)
                    self.assertEqual(")", power[0][-1].text)
                    self.assertEqual("−1", "".join(power[1].itertext()))

    def test_binomial_grouping_preserves_neighboring_and_combined_scripts(self):
        ns = "{" + math.MATHML_NS + "}"
        for tex in (r"x_i+\binom{\beta n}{k}^{-1}+y_j^2",
                    r"x_i+\binom{\beta n}{k}_j^{-1}+y_j^2",
                    r"x_i+\binom{{\beta} n}{k}^{-1}_j+y_j^2"):
            with self.subTest(tex=tex):
                document = self.document("$" + tex + "$")
                self.assertEqual(1, len(self.formulas(document)))
                scripts = [node for node in document.iter()
                           if node.tag in {ns + "msub", ns + "msup", ns + "msubsup"}]
                x = next(node for node in scripts if node[0].text == "x")
                y = next(node for node in scripts if node[0].text == "y")
                self.assertEqual(["x", "i"], ["".join(child.itertext()) for child in x])
                self.assertEqual(["y", "j", "2"], ["".join(child.itertext()) for child in y])
                binomial = next(node for node in scripts if node[0].find(ns + "mfrac") is not None)
                self.assertEqual(["βn", "k"], ["".join(child.itertext()) for child in binomial[0][1]])
                if "_j" in tex.split("+", 2)[1]:
                    self.assertEqual(["j", "−1"], ["".join(child.itertext()) for child in binomial][1:])

    def test_exact_c001_rendering_does_not_modify_canonical_or_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.tex"
            canonical = root / "ledger.json"
            source.write_bytes(("\\[\r\n" + ORIGINAL_C001 + "\r\n\\]\r\n").encode("utf-8"))
            canonical.write_bytes((json.dumps({"claim": "$" + ORIGINAL_C001 + "$"}) + "\n").encode("utf-8"))
            before = {path: path.read_bytes() for path in (source, canonical)}
            record = json.loads(canonical.read_bytes())
            for text in (record["claim"], source.read_bytes().decode("utf-8")):
                self.assertNotIn("math-fallback", math.render_text(text))
            self.assertEqual("$" + ORIGINAL_C001 + "$", record["claim"])
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_binomial_workaround_never_accepts_malformed_converter_structures(self):
        malformed = ('<math xmlns="' + math.MATHML_NS + '"><msup>'
                     '<mo>(</mo><mfrac linethickness="0"><mi>n</mi><mi>k</mi></mfrac>'
                     '<mo>)</mo><mrow><mo>−</mo><mn>1</mn></mrow></msup></math>')
        with self.assertRaisesRegex(ValueError, "incomplete mathematical structure"):
            math._safe_mathml(malformed, ORIGINAL_C001, "inline")
        for output in (malformed, '<math><msub><mi>x</mi></msub></math>',
                       '<math><msubsup><mi>x</mi><mi>i</mi></msubsup></math>'):
            math._convert.cache_clear()
            with self.subTest(output=output), patch("latex2mathml.converter.convert", return_value=output):
                document = self.document("$" + ORIGINAL_C001 + "$")
                self.assertFalse(self.formulas(document))
                self.assertIn("LaTeX (not rendered)", "".join(document.itertext()))
                self.assertIn("$" + ORIGINAL_C001 + "$", "".join(document.itertext()))

    def test_plain_pseudo_math_and_escaped_delimiters_are_not_reinterpreted(self):
        text = r"max_{j <= m_n} X_n -> 0; price \$5; unpaired \\(x; <source>"
        self.assertFalse(math.has_math(text))
        self.assertEqual(text, "".join(self.document(text).itertext()))
        self.assertNotIn("<source>", math.render_text(text))

    def test_paired_doubled_delimiters_are_exact_diagnosed_literal_candidates(self):
        for literal in (r"\\(x\\)", r"\\[\mathcal H\\]"):
            with self.subTest(literal=literal):
                diagnostics = []
                rendered = math.render_text(literal, diagnostics)
                document = ET.fromstring("<div>" + rendered + "</div>")
                self.assertTrue(math.has_math(literal))
                self.assertFalse(math.legacy_reading_has_math(literal))
                self.assertEqual(literal, document.find(".//code").text)
                self.assertFalse(self.formulas(document))
                self.assertEqual(1, len(diagnostics))
                self.assertEqual("damaged_escape", diagnostics[0]["kind"])
                self.assertEqual(literal, diagnostics[0]["excerpt"])

    def test_legacy_wording_selector_retains_supported_openers_and_ordinary_escapes(self):
        for text in (r"$x$", r"\[x", r"\(x\)", r"\\(price $x$\\)"):
            self.assertTrue(math.legacy_reading_has_math(text), text)
        for text in (r"price \$5", r"\\(x\\)", r"unpaired \\(x", "ordinary prose"):
            self.assertFalse(math.legacy_reading_has_math(text), text)

    def test_mathematical_alphabets_share_the_common_display_and_original_tex(self):
        tex = r"R\in\mathbb R, H\in\mathcal H"
        document = self.document("$" + tex + "$")
        namespace = "{" + math.MATHML_NS + "}"
        self.assertEqual(["R", "ℝ", "H", "ℋ"],
                         [node.text for node in document.iter(namespace + "mi")])
        self.assertEqual(tex, next(document.iter(namespace + "annotation")).text)
        unsupported = r"$\mathcal{\alpha}$"
        diagnostics = []
        literal = ET.fromstring("<div>" + math.render_text(unsupported, diagnostics) + "</div>")
        self.assertEqual(unsupported, literal.find(".//code").text)
        self.assertEqual(1, len(diagnostics))
        self.assertIn("no Unicode", diagnostics[0]["reason"])

    def test_unmatched_and_unsupported_math_remain_labeled_and_exact(self):
        for text in (r"before $x_i", r"before \[x", r"$\unknownproofmacro{x}$"):
            with self.subTest(text=text):
                self.assertTrue(math.has_math(text))
                value = math.render_text(text)
                self.assertIn("LaTeX (not rendered)", value)
                self.assertIn(text.split("before ")[-1], "".join(self.document(text).itertext()))
                self.assertNotIn("<math", value)

    def test_supported_multiline_cases_and_alignment_are_real_math(self):
        for tex in (r"\begin{cases}1 & x>0\\0 & x\le0\end{cases}",
                    r"\begin{align*}a&=b+c\\d&=e\end{align*}",
                    r"\begin{aligned}a&=b\\c&=d\end{aligned}",
                    r"\begin{aligned}a&=b\\\gamma&=d\end{aligned}",
                    r"\begin{aligned}x&=y\\\leq&z\end{aligned}",
                    r"\begin{aligned}&E\!\left[X\right]\\&E\!\big(x\big)\end{aligned}",
                    r"\begin{aligned}&a\!\cdot\!b\\&\int\!\!\int f\end{aligned}"):
            with self.subTest(tex=tex):
                document = self.document("\\[" + tex + "\\]")
                self.assertTrue(list(document.iter("{" + math.MATHML_NS + "}mtable")))
                self.assertEqual(2, len(list(document.iter("{" + math.MATHML_NS + "}mtr"))))
                self.assertEqual(4, len(list(document.iter("{" + math.MATHML_NS + "}mtd"))))
                self.assertEqual(tex, next(document.iter("{" + math.MATHML_NS + "}annotation")).text)

    def test_unsupported_environment_is_not_silently_dropped(self):
        for tex in (r"\begin{aligned}[t]a&=b\\c&=d\end{aligned}",
                    r"\begin{unknown}x\end{unknown}"):
            with self.subTest(tex=tex):
                document = self.document("\\[" + tex + "\\]")
                self.assertFalse(self.formulas(document))
                self.assertIn(tex, "".join(document.itertext()))
                self.assertIn("LaTeX (not rendered)", "".join(document.itertext()))

    def test_incomplete_math_and_source_macros_remain_literal(self):
        for tex in (r"\frac{1}", r"x_", r"\sqrt[3]", "{x", "x}",
                    r"\newcommand{\foo}{x}\foo", r"\def\foo{x}\foo",
                    r"\DeclareMathOperator{\foo}{bar}\foo x"):
            with self.subTest(tex=tex):
                value = math.render_text("$" + tex + "$")
                self.assertNotIn("<math", value)
                self.assertIn("math-fallback", value)
                self.assertIn(tex, "".join(ET.fromstring("<div>" + value + "</div>").itertext()))

    def test_tex_and_plain_html_cannot_introduce_executable_links(self):
        text = r'<script>alert(1)</script> $\href{javascript:alert(1)}{x}$'
        value = math.render_text(text)
        self.assertNotIn("<script", value)
        self.assertNotIn('href="javascript:', value)
        self.assertIn("LaTeX (not rendered)", value)

    def test_converter_output_is_restricted_to_safe_mathml(self):
        for body in ('<mtext href="https://example.test">x</mtext>', '<mtext onclick="x()">x</mtext>',
                     '<mtext style="color:red">x</mtext>', '<img src="x"/>',
                     '<mtext xmlns="http://www.w3.org/1999/xhtml">x</mtext>', '<mi>\\unknown</mi>'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                math._safe_mathml('<math xmlns="' + math.MATHML_NS + '">' + body + '</math>', 'x', 'inline')
        with self.assertRaises(ValueError):
            math._safe_mathml('<!DOCTYPE math [<!ENTITY x "bad">]><math>&x;</math>', 'x', 'inline')

    def test_converter_failure_preserves_formula_and_surrounding_prose(self):
        with patch("latex2mathml.converter.convert", side_effect=ValueError("unsupported")):
            value = math.render_text("Before $x_i$ after.")
        self.assertIn("Before ", value)
        self.assertIn("$x_i$", value)
        self.assertTrue(value.endswith(" after."))
        self.assertIn("math-fallback", value)

    def test_empty_and_oversized_formula_have_bounded_literal_fallback(self):
        for text in ("$$", "$$  $$", r"\(\)", "$" + "x" * 8193 + "$"):
            with self.subTest(length=len(text)):
                self.assertIn("math-fallback", math.render_text(text))

    def test_converter_identity_covers_package_data_but_not_python_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            origin = package / "__init__.py"
            origin.write_text("# converter\n", encoding="utf-8")
            data = package / "symbols.txt"
            data.write_text("alpha", encoding="utf-8")
            with patch.object(math.importlib.util, "find_spec", return_value=SimpleNamespace(origin=str(origin))), patch.object(math.importlib.metadata, "version", return_value="test-1"):
                before = math.renderer_info()
                self.assertTrue(before["available"])
                json.dumps(before)
                cache = package / "__pycache__"
                cache.mkdir()
                (cache / "runtime.pyc").write_bytes(b"cache")
                self.assertEqual(before, math.renderer_info())
                data.write_text("beta", encoding="utf-8")
                self.assertNotEqual(before["package_sha256"], math.renderer_info()["package_sha256"])

    def test_by_filename_facades_use_their_own_bundled_math_in_one_process(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loaded = []
            for name in ("first", "second"):
                install = root / name
                install.mkdir()
                facade = install / "proofcheck_math.py"
                facade.write_bytes((ROOT / "scripts/proofcheck_math.py").read_bytes())
                common = install / "paper_core/math_render.py"
                common.parent.mkdir()
                common.write_text("def render_text(text, diagnostics=None):\n    return " + repr(name) + "\n",
                                  encoding="utf-8")
                spec = importlib.util.spec_from_file_location("math_facade_" + name, facade)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertEqual(common.resolve(), Path(module._common().__file__).resolve())
                self.assertEqual(name, module.render_text("probe"))
                loaded.append(module)
            self.assertIsNot(loaded[0]._common(), loaded[1]._common())
            self.assertEqual("first", loaded[0].render_text("probe"))
            for module in loaded:
                sys.modules.pop(module._common().__name__, None)


if __name__ == "__main__":
    unittest.main()
