"""Publication: math display, render input, the Node renderer, mechanical acceptance and release.

Covers ``paper_core.publish``, ``paper_core.math_render`` and the bundled renderer. The renderer is an
external program, so every test that needs it is guarded by ``support.node_available()``; the pure
functions (``render_text``, ``display_fragments``, ``mechanical_acceptance``) are exercised without it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import stat
import subprocess
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

import support
from support import CLI_ENV, CORE, Fixture, TempCase, run_cli

from paper_core import CORE_VERSION, math_render, publish
from paper_core.errors import InvalidRequest, PublicationError
from paper_core.math_render import render_text
from paper_core.packets import source_context_digest
from paper_core.projection import build_projection

RENDERER_DIR = CORE / "renderer"
SELFTEST = RENDERER_DIR / "selftest.mjs"
NO_NODE = "node is not installed; the bundled renderer cannot run"
RENDER_ONLY_RECEIPT_KEYS = {"artifact_sha256", "connections", "geometry", "input_bytes", "input_sha256",
                            "layout_mode", "nodes", "python_acceptance", "representation", "math_diagnostics"}
PUBLICATION_RECEIPT_KEYS = RENDER_ONLY_RECEIPT_KEYS | {"kind", "output_path", "publication_id", "started_at", "state"}
# The renderer's own two receipts. Both lists are part of the build evidence: a check that silently
# disappears from the renderer would otherwise weaken every publication without failing anything.
REPRESENTATION_CHECKS = ["projection_script", "render_input_script", "archify_shell", "dag_nodes", "dag_edges", "no_index_articles",
                         "detail_elements", "detail_sections", "section_record_refs", "section_obligation_ids",
                         "canonical_record_templates", "contextual_reader_overviews", "visible_report_state", "visible_assessments", "visible_applications", "visible_graph_states", "assessment_styles", "visible_scope",
                         "summary_counts", "process_complete", "summary_findings", "summary_source_limits", "summary_limitations",
                         "search_input", "no_external_requests"]
GEOMETRY_CHECKS = ["finite_node_geometry", "node_clipping", "node_overlaps", "finite_route_geometry",
                   "edge_endpoints_on_boxes", "routes_through_unrelated_nodes"]
SELFTEST_CHECKS = ["hash:assets/archify/template.html", "hash:assets/archify/utils.mjs",
                   "hash:assets/archify/i18n.mjs", "hash:assets/archify/LICENSE",
                   "hash:assets/archify/JetBrainsMono-OFL.txt", "render:dag_small.json",
                   "render:index_fallback.json", "render:long_math.json", "fail:cycle_dag.json",
                   "render:cyclic", "render:cyclic-dense", "reader:pinned-context-and-tampering", "reader:missing-strategy",
                   "reader:clutter-preserves-evidence-and-limitations"]
ISO_INSTANT = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
SHA256_HEX = r"^[0-9a-f]{64}$"
# The page embeds the projection and the render input as JSON. Assertions about what a reader can
# actually see must run against the page with those two data islands removed, or the JSON alone
# would satisfy them while the visible report showed nothing.
DATA_ISLANDS = re.compile(br'<script id="proof-(?:projection|render-input)"[^>]*>.*?</script>', re.S)


class MathFixture(Fixture):
    """The standard two-item paper with explicit LaTeX in both item statements."""

    MATH = r"for every $n$, $a_n \le 1$."

    @staticmethod
    def item_edit(iid, kind, label, anchor, proof):
        item = Fixture.item_edit(iid, kind, label, anchor, proof)
        item["body"]["statement"] = {"form": "verbatim", "text": f"{label}: {MathFixture.MATH}"}
        return item


class PublicationCase(TempCase):
    """Temp-directory case that builds a process-complete paper through the public API."""

    fixture_class = Fixture

    def complete_paper(self, name="paper", **kwargs):
        root = self.work / name
        root.mkdir(parents=True, exist_ok=True)
        fixture = self.fixture_class(root, **kwargs)
        fixture.complete()
        return fixture

    def scratch(self, name="render") -> Path:
        target = self.work / name
        target.mkdir(parents=True, exist_ok=True)
        return target

    def require_node(self):
        if not support.node_available():
            self.skipTest(NO_NODE)

    def fragment_keys(self, fixture) -> set:
        """The fragment keys the standard fixture must produce, including the generated check ids."""
        fixed = ["items:itm_lem:1", "items:itm_thm:1", "arguments:arg_lem:1", "arguments:arg_thm:1",
                 "groups:grp_lem:1", "groups:grp_thm:1",
                 "uses:use_lem_thm:1", "scopes:scp_plain:1", "reconciliations:rec_lem:1",
                 "reconciliations:rec_thm:1", "checks:chk_comp_lem:1", "checks:chk_comp_thm:1",
                 "checks:chk_der_lem:1", "checks:chk_der_thm:1", "checks:chk_app:1",
                 "application_details:use_lem_thm:1", "source_reviews:srv_boundaries:1"]
        return set(fixed) | {f"checks:{cid}:1" for cid in fixture.independent_checks.values()}


# -- math display ----------------------------------------------------------------------------------
class MathRenderTests(unittest.TestCase):
    """``math_render.render_text`` is a display adapter: it never loses or rewrites source text."""

    def assert_math_source(self, tex):
        markup, reason = math_render._convert(tex, "inline")
        self.assertIsNotNone(markup, reason)
        root = ET.fromstring(markup)
        namespace = {"m": math_render.MATHML_NS}
        self.assertEqual(root.find(".//m:annotation", namespace).text, tex)
        self.assertEqual(root.get("aria-label"), "LaTeX: " + tex)
        return root, namespace

    def test_ordinary_product_spacing_preserves_tree_and_exact_source(self):
        for tex in (r"Y=W\!\cdot\!b+\varepsilon", r"2\!\cdot\!3",
                    r"x\!\cdot\!2", r"2\!\cdot\!x", r"x\!\cdot\!y\!\cdot\!z"):
            with self.subTest(tex=tex):
                actual, namespace = self.assert_math_source(tex)
                expected, _ = self.assert_math_source(tex.replace(r"\!", " "))
                self.assertFalse(actual.findall(".//m:mspace", namespace))
                self.assertIn("·", [node.text for node in actual.findall(".//m:mo", namespace)])
                for root in (actual, expected):
                    root.attrib.pop("aria-label")
                    root.find(".//m:annotation", namespace).text = "source"
                self.assertEqual(ET.tostring(actual), ET.tostring(expected))

    def test_other_product_spacing_keeps_readable_literal_fallback(self):
        for tex in (r"x\!y", r"x\!\cdot y", r"x\cdot\!y", r"x\!\!\cdot\!y",
                    r"x\!\cdot\!\!y", r"x_i\!\cdot\!y", r"x\!\cdot\!y^2",
                    r"{x+y}\!\cdot\!z", r"x\!\cdot\!\frac{y}{z}",
                    r"\!\cdot\!x", r"x\!\cdot\!", r"x\!\times\!y"):
            with self.subTest(tex=tex):
                diagnostics = []
                literal = "$" + tex + "$"
                markup = render_text(literal, diagnostics)
                self.assertIn('class="math-fallback"', markup)
                self.assertNotIn("<math", markup)
                self.assertEqual(diagnostics[0]["excerpt"], literal)
                self.assertIn("negative spacing", diagnostics[0]["reason"])

    def test_product_spacing_rejects_nonbare_or_malformed_nodes(self):
        thin = '<mspace width="negativethinmathspace"/>'
        row = '<mi>x</mi>' + thin + '<mo>·</mo>' + thin + '<mn>2</mn>'
        bad_spaces = (
            '<mspace width="negativethinmathspace" height="1em"/>',
            '<mspace width="negativethinmathspace"> </mspace>',
            thin + 'tail', '<mspace width="negativethinmathspace"><mi>a</mi></mspace>',
            '<mspace width="negativeverythinmathspace"/>', '<f:mspace width="negativethinmathspace"/>',
        )
        malformed = []
        for bad in bad_spaces:
            malformed.extend((row.replace(thin, bad, 1), row.rsplit(thin, 1)[0] + bad + '<mn>2</mn>'))
        for bad in ('<mo form="infix">·</mo>', '<mo>·<mi>a</mi></mo>', '<mo>·</mo>tail',
                    '<mo> ·</mo>', '<mo>⋅</mo>', '<f:mo>·</f:mo>'):
            malformed.append(row.replace('<mo>·</mo>', bad))
        for bad in ('<mi/>', '<mi> </mi>', '<mtext>x</mtext>', '<mi>x<mn>1</mn></mi>',
                    '<msub><mi>x</mi><mn>1</mn></msub>', '<mi>x</mi>tail', '<f:mi>x</f:mi>'):
            malformed.append(row.replace('<mi>x</mi>', bad))
        malformed.append(row.replace('<mi>x</mi>', '<mi onclick="bad">x</mi>'))
        for fragment in malformed:
            with self.subTest(fragment=fragment), self.assertRaises(ValueError):
                math_render._safe_mathml('<math xmlns:f="urn:foreign"><mrow>' + fragment
                                         + '</mrow></math>', "original", "inline")
        for namespace in ('', ' xmlns="' + math_render.MATHML_NS + '"'):
            root = ET.fromstring(math_render._safe_mathml('<math' + namespace + '><mrow>'
                                + row + '</mrow></math>', "original", "inline"))
            self.assertEqual([node.text for node in root.iter()
                              if node.tag.endswith('}mo')], ["·"])

    def test_frozen_render_input_regenerates_product_display_without_scientific_changes(self):
        tex = r"Y=W\!\cdot\!b+\varepsilon"
        snapshot = {"paper": {"title": "Frozen display fixture"}, "revision": 7,
                    "audit_id": "aud_original", "source_identity": "saved-source",
                    "kind": "working", "producer": {"core_version": "saved-producer"},
                    "process_complete": False, "representation_settled": True,
                    "finalization_blockers": [], "finalization_blocker_count": 0,
                    "projection": {"records": [{"ref": {"collection": "items", "id": "itm_product", "version": 1},
                        "body": {"statement": {"form": "verbatim", "text": "$" + tex + "$"}}}]}}
        original = copy.deepcopy(snapshot)
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        payload = publish.frozen_render_input(snapshot, snapshot_sha256=digest)
        self.assertEqual(snapshot, original)
        self.assertEqual(payload["projection"], original["projection"])
        self.assertEqual(payload["build"]["scientific_producer"], original["producer"])
        self.assertEqual(payload["build"]["source_identity"], original["source_identity"])
        self.assertEqual(payload["build"]["finalization"]["snapshot_sha256"], digest)
        markup = payload["display"]["refs"]["items:itm_product:1"]["statement_html"]
        self.assertNotIn("math-fallback", markup)
        root = ET.fromstring(markup)
        self.assertEqual(root.find(".//m:annotation", {"m": math_render.MATHML_NS}).text, tex)
        self.assertEqual(payload["display"]["math_diagnostics"], [])

    def test_all_sized_brace_commands_and_aliases_keep_size_and_fence_attributes(self):
        for size in ("big", "Big", "bigg", "Bigg"):
            for suffix in ("", "l", "r", "m"):
                command = "\\" + size + suffix
                for opening, closing in ((r"\{", r"\}"), (r"\lbrace", r"\rbrace")):
                    tex = command + opening + " x " + command + closing
                    with self.subTest(tex=tex):
                        root, namespace = self.assert_math_source(tex)
                        operators = root.findall(".//m:mo", namespace)
                        self.assertEqual([node.text for node in operators], ["{", "}"])
                        from latex2mathml.converter import convert
                        raw = ET.fromstring(convert(tex)).findall(".//m:mo", namespace)
                        self.assertEqual([node.attrib for node in operators], [node.attrib for node in raw])
                        for node in operators:
                            self.assertTrue(node.get("minsize"))
                            self.assertEqual(node.get("minsize"), node.get("maxsize"))

    def test_sized_braces_preserve_grouping_scripts_fractions_and_nested_fences(self):
        cases = (
            (r"\Bigl\{x\Bigr\}_{i}^{2}", ["{", "}"], "msubsup"),
            (r"\frac{\Bigl\{x\Bigr\}}{y}", ["{", "}"], "mfrac"),
            (r"\Bigl \{ x \Bigr \}", ["{", "}"], None),
            (r"\Bigm\{", ["{"], None), (r"\Bigm\}", ["}"], None),
            (r"\Bigl\lbrace{x+y}\Bigr\rbrace", ["{", "+", "}"], None),
            (r"\biggl\{\frac{x}{y}\biggr\}", ["{", "}"], "mfrac"),
            (r"\left\{\Bigl\{x\Bigr\}\right\}", ["{", "{", "}", "}"], None),
            (r"\begin{matrix}\Bigl\{x\Bigr\} & y\\z & w\end{matrix}", ["{", "}"], "mtable"),
        )
        for tex, expected, structure in cases:
            with self.subTest(tex=tex):
                root, namespace = self.assert_math_source(tex)
                self.assertEqual([node.text for node in root.findall(".//m:mo", namespace)], expected)
                if structure:
                    node = root.find(".//m:" + structure, namespace)
                    self.assertIsNotNone(node)
                    if structure == "msubsup":
                        self.assertEqual(["".join(child.itertext()) for child in node], ["}", "i", "2"])
                    elif structure == "mfrac":
                        self.assertEqual(["".join(child.itertext()) for child in node],
                                         ["{x}", "y"] if tex.startswith(r"\frac") else ["x", "y"])
                    else:
                        self.assertEqual(len(node), 2)
                        self.assertEqual([len(row) for row in node], [2, 2])

    def test_sized_brace_fix_keeps_existing_control_outcomes(self):
        controls = (
            (r"\{x\}", ["{", "}"], ""), (r"\left\{x\right\}", ["{", "}"], ""),
            (r"\lbrace x\rbrace", [], ""), (r"\Bigl(x\Bigr)", ["(", ")"], ""),
            (r"\Bigl[x\Bigr]", ["[", "]"], ""),
            (r"\Bigl\lVert x\Bigr\rVert_{\mathcal H}", ["‖", "‖"], ""),
            (r"\binom nk^{-1}", ["(", ")", "−"], ""),
            (r"R\perp\!\!\perp S\mid X", ["⫫", "∣"], ""),
            (r"\Bigl\lbraceFoo", None, r"\lbraceFoo"),
            (r"\\Bigl\{", None, "likely doubled LaTeX command slash"),
            (r"\Bigleft\{", None, r"\Bigleft"), (r"\Bigl\\{", None, "unmatched brace"),
            (r"\privateMacro_x", None, r"\privateMacro"),
            (r"\text{\Bigl\{x\Bigr\}}", None, r"\Bigl"),
            (r"\Bigl\lBrace x\Bigr\rBrace", None, r"\lBrace"),
        )
        for tex, operators, expected_reason in controls:
            with self.subTest(tex=tex):
                markup, reason = math_render._convert(tex, "inline")
                if operators is None:
                    self.assertIsNone(markup)
                    self.assertIn(expected_reason, reason)
                    diagnostics = []
                    rendered = render_text("$" + tex + "$", diagnostics)
                    self.assertIn('class="math-fallback"', rendered)
                    self.assertEqual(len(diagnostics), 1)
                    self.assertEqual(diagnostics[0]["excerpt"], "$" + tex + "$")
                else:
                    root, namespace = self.assert_math_source(tex)
                    self.assertEqual([node.text for node in root.findall(".//m:mo", namespace)], operators)

    def test_all_sized_norm_commands_keep_size_and_operator_attributes(self):
        from latex2mathml.converter import convert
        for size, extent in (("big", "1.2em"), ("Big", "1.623em"),
                             ("bigg", "2.047em"), ("Bigg", "2.470em")):
            for suffix in ("", "l", "r", "m"):
                command = "\\" + size + suffix
                tex = command + r"\|x" + command + r"\|"
                with self.subTest(tex=tex):
                    root, namespace = self.assert_math_source(tex)
                    bars = root.findall(".//m:mo", namespace)
                    self.assertEqual([bar.text for bar in bars], ["‖", "‖"])
                    raw = ET.fromstring(convert(tex)).findall(".//m:mo", namespace)
                    self.assertEqual([bar.attrib for bar in bars], [bar.attrib for bar in raw])
                    self.assertEqual([(bar.get("minsize"), bar.get("maxsize")) for bar in bars],
                                     [(extent, extent)] * 2)

    def test_sized_norm_scripts_keep_the_sized_bar_as_their_base(self):
        for size in ("big", "Big", "bigg", "Bigg"):
            for left, right in ((size, size), (size + "l", size + "r"), (size + "m", size + "m")):
                for script, tag, contents in (("_2", "msub", ["2"]), ("^2", "msup", ["2"]),
                                               ("_2^3", "msubsup", ["2", "3"])):
                    tex = "\\" + left + r"\|x" + "\\" + right + r"\|" + script
                    with self.subTest(tex=tex):
                        root, namespace = self.assert_math_source(tex)
                        node = root.find(".//m:" + tag, namespace)
                        self.assertIsNotNone(node)
                        self.assertEqual(node[0].tag, "{" + math_render.MATHML_NS + "}mrow")
                        self.assertEqual(len(node[0]), 1)
                        self.assertEqual(node[0][0].text, "‖")
                        self.assertTrue(node[0][0].get("minsize"))
                        self.assertEqual(node[0][0].get("minsize"), node[0][0].get("maxsize"))
                        self.assertEqual(["".join(child.itertext()) for child in node][1:], contents)

    def test_norm_normalization_is_limited_to_exact_sized_operator_leaves(self):
        fragments = (
            (r'<mo minsize="1em" maxsize="1em" fence="true">\|</mo>', "‖"),
            (r'<mo>\|</mo>', r"\|"),
            (r'<mo minsize="1em" maxsize="2em">\|</mo>', r"\|"),
            (r'<mo minsize="" maxsize="">\|</mo>', r"\|"),
            (r'<mo minsize="1em">\|</mo>', r"\|"),
            (r'<mi minsize="1em" maxsize="1em">\|</mi>', r"\|"),
            (r'<mtext minsize="1em" maxsize="1em">\|</mtext>', r"\|"),
            (r'<mo minsize="1em" maxsize="1em">\|<mi>x</mi></mo>', r"\|"),
            (r'<mo minsize="1em" maxsize="1em"> \|</mo>', r" \|"),
            (r'<mo minsize="1em" maxsize="1em">\|\|</mo>', r"\|\|"),
        )
        for fragment, expected in fragments:
            with self.subTest(fragment=fragment):
                root = ET.fromstring(math_render._safe_mathml("<math>" + fragment + "</math>",
                                                             "original source", "inline"))
                namespace = {"m": math_render.MATHML_NS}
                token = root.find(".//m:mrow", namespace)[0]
                raw = ET.fromstring(fragment)
                self.assertEqual(token.text, expected)
                self.assertEqual(token.attrib, raw.attrib)
                self.assertEqual(len(token), len(raw))
                self.assertEqual(root.find(".//m:annotation", namespace).text, "original source")

    def test_unsized_and_named_norm_bars_keep_their_existing_display(self):
        for tex in (r"\|x\|_2", r"\left\|x\right\|_2", r"\lVert x\rVert_2",
                    r"\bigl\lVert x\bigr\rVert_2", r"\Biggl\Vert x\Biggr\Vert_2"):
            with self.subTest(tex=tex):
                root, namespace = self.assert_math_source(tex)
                self.assertEqual([bar.text for bar in root.findall(".//m:mo", namespace)], ["‖", "‖"])
        self.assertEqual(render_text(r"A literal \big\| in prose."), r"A literal \big\| in prose.")

    def test_brace_normalization_is_limited_to_exact_sized_operator_leaves(self):
        probes = (
            ('<mo>\\{</mo>', None, "unconverted LaTeX brace"),
            ('<mo minsize="1.623em" maxsize="1.623em" fence="true" form="prefix">\\{</mo>', "{", ""),
            ('<mo>\\</mo>', "\\", ""), ('<mo>{</mo>', "{", ""),
            ('<mtext>\\{</mtext>', r"\{", ""),
            ('<mo minsize="1em" maxsize="2em">\\}</mo>', None, "unconverted LaTeX brace"),
            ('<mo minsize="1em" maxsize="1em">\\lbraceFoo</mo>', None, r"\lbraceFoo"),
        )
        for fragment, expected, reason in probes:
            with self.subTest(fragment=fragment):
                source = "<math>" + fragment + "</math>"
                if expected is None:
                    with self.assertRaisesRegex(ValueError, re.escape(reason)):
                        math_render._safe_mathml(source, "original", "inline")
                else:
                    root = ET.fromstring(math_render._safe_mathml(source, "original", "inline"))
                    namespace = {"m": math_render.MATHML_NS}
                    token = root.find(".//m:mrow", namespace)[0]
                    self.assertEqual(token.text, expected)
                    self.assertEqual(token.attrib, ET.fromstring(fragment).attrib)
                    self.assertEqual(root.find(".//m:annotation", namespace).text, "original")

    def test_unsized_empty_bound_and_nonleaf_brace_tokens_fall_back(self):
        for fragment in ('<mo minsize="" maxsize="">\\{</mo>',
                         '<mo minsize="1em" maxsize="1em">\\}<mi>x</mi></mo>',
                         '<mo>\\lbrace</mo>', '<mo>\\rbrace</mo>'):
            with self.subTest(fragment=fragment):
                with self.assertRaisesRegex(ValueError, "unconverted LaTeX brace"):
                    math_render._safe_mathml("<math>" + fragment + "</math>", "original", "inline")

    def test_prose_is_escaped_and_inline_math_becomes_annotated_mathml(self):
        """Prose is HTML-escaped and $...$ becomes inline MathML that still carries the original TeX."""
        html = render_text(r'a < b & "q": $a_n \le 1$')
        self.assertIn("a &lt; b &amp; &quot;q&quot;: ", html)
        self.assertIn('<math display="inline"', html)
        self.assertIn('class="math-inline"', html)
        self.assertIn(r'aria-label="LaTeX: a_n \le 1"', html)
        self.assertIn(r'<annotation encoding="application/x-tex">a_n \le 1</annotation>', html)
        self.assertIn("<msub><mi>a</mi><mi>n</mi></msub>", html)
        self.assertNotIn("math-fallback", html)

    def test_double_dollar_produces_block_math_and_single_dollar_does_not(self):
        """The delimiter chooses the display mode: $$ gives block MathML, $ gives inline."""
        block = render_text("see $$x^2$$ now")
        self.assertIn('<math display="block"', block)
        self.assertIn('class="math-display"', block)
        self.assertIn("<msup><mi>x</mi><mn>2</mn></msup>", block)
        inline = render_text("see $x^2$ now")
        self.assertIn('<math display="inline"', inline)
        self.assertNotIn('display="block"', inline)

    def test_the_paren_and_bracket_delimiters_typeset_inline_and_block(self):
        r"""The documented \( \) and \[ \] delimiters are honoured and pick the same modes as $ and $$."""
        paren = render_text(r"x \(a_n\) y")
        self.assertIn('<math display="inline"', paren)
        self.assertIn('class="math-inline"', paren)
        self.assertIn("<msub><mi>a</mi><mi>n</mi></msub>", paren)
        self.assertTrue(paren.startswith("x <math "), paren[:40])
        self.assertTrue(paren.endswith("</math> y"), paren[-40:])
        bracket = render_text(r"x \[a_n\] y")
        self.assertIn('<math display="block"', bracket)
        self.assertIn('class="math-display"', bracket)
        self.assertNotIn("math-fallback", bracket)

    def test_an_escaped_dollar_never_opens_a_formula(self):
        r"""A backslash-escaped \$ is prose: it stays literal and does not start a math span."""
        html = render_text(r"cost \$5 and \$6")
        self.assertEqual(r"cost \$5 and \$6", html)
        self.assertNotIn("<math", html)
        self.assertNotIn("math-fallback", html)

    def test_unsupported_latex_stays_inspectable_as_a_labelled_literal(self):
        """A formula the converter rejects keeps its exact source text in a labelled fallback span."""
        html = render_text(r"bad $\unknowncmd{x}$ tail")
        self.assertIn('<span class="math-fallback" title="This LaTeX expression is unsupported by the offline'
                      ' converter.', html)
        self.assertIn(r"\unknowncmd", html)
        self.assertIn('<span class="math-fallback-label">LaTeX (not rendered): </span>', html)
        self.assertIn(r"<code>$\unknowncmd{x}$</code>", html)
        self.assertTrue(html.startswith("bad ") and html.endswith(" tail"), html)
        self.assertNotIn("<math", html)

    def test_an_unmatched_opening_delimiter_keeps_the_whole_tail(self):
        """An opener with no closer must not swallow the rest of the text; the tail stays as evidence."""
        html = render_text("open $a_n and more")
        self.assertIn('title="The LaTeX opening delimiter has no matching closing delimiter."', html)
        self.assertIn("<code>$a_n and more</code>", html)
        self.assertNotIn("<math", html)

    def test_an_empty_formula_reports_the_limit_reason_not_the_converter_reason(self):
        """Whitespace between delimiters is refused with its own reason so the cause stays diagnosable."""
        html = render_text("$ $ blank")
        self.assertIn('title="The expression is empty or exceeds the display limit."', html)
        self.assertIn("<code>$ $</code>", html)
        self.assertTrue(html.endswith("</span> blank"), html[-30:])
        self.assertNotIn("<math", html)

    def test_unbalanced_braces_never_produce_partial_markup(self):
        """An unmatched brace falls back to the literal rather than emitting truncated MathML."""
        html = render_text(r"x $\frac{1}{2$ y")
        self.assertNotIn("<math", html)
        self.assertIn(r"<code>$\frac{1}{2$</code>", html)
        self.assertIn('title="This LaTeX expression is unsupported by the offline converter. unmatched brace"', html)
        self.assertTrue(html.endswith(" y"), html[-20:])

    def test_decoded_json_escapes_fall_back_with_a_specific_reason(self):
        r"""An under-escaped \theta, \rho or \nabla arrives as a control character plus letters; it must not render."""
        for command, reason in (("theta", "tab + heta"), ("rho", "carriage return + ho"),
                                ("nabla", "newline + abla"), ("rVert", "carriage return + Vert")):
            with self.subTest(command=command):
                text = json.loads('"$x \\' + command + ' y$"')
                html = render_text(text)
                self.assertNotIn("<math", html)
                self.assertIn(f"Likely decoded LaTeX escape ({reason})", html)
        for legitimate in (r"$\theta\to\rho\nabla$", "$x =\t" + "o(1)$", "$x +\r\n" + "ho$", "$x +\t" + "hetas$"):
            with self.subTest(legitimate=legitimate):
                self.assertNotIn("decoded LaTeX escape", render_text(legitimate))

    def test_little_o_with_tex_whitespace_still_renders(self):
        for whitespace in (" ", "  ", "\t", "\n", "\r\n"):
            with self.subTest(whitespace=whitespace):
                html = render_text("$x =\to" + whitespace + "(1)$")
                self.assertIn("<math", html)
                self.assertNotIn("math-fallback", html)

    def test_macro_definitions_are_refused_rather_than_expanded(self):
        """Source macro definitions are never expanded, so a definition renders as its literal text."""
        html = render_text(r"m $\newcommand{\z}{1}\z$ x")
        self.assertNotIn("<math", html)
        self.assertIn(r"<code>$\newcommand{\z}{1}\z$</code>", html)
        self.assertIn('title="This LaTeX expression is unsupported by the offline converter. source macro definitions are not expanded"', html)


# -- display fragments and render input ------------------------------------------------------------
class DisplayFragmentTests(PublicationCase):
    """``display_fragments`` decides exactly which record prose the renderer is allowed to replace."""

    def test_the_documented_fragment_fields_are_the_only_ones_offered(self):
        """FRAGMENT_FIELDS is the published contract between the core and the renderer."""
        self.assertEqual(("label", "statement", "reason", "needed_form", "rationale", "conditions", "reasoning",
                          "description", "proof_idea", "regime", "uncertainty", "impact_reason"), publish.FRAGMENT_FIELDS)

    def test_fragments_are_keyed_by_pinned_ref_and_skip_records_without_prose(self):
        """Keys are collection:id:version and only the documented text-bearing records appear."""
        fixture = self.complete_paper()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
        fragments = publish.display_fragments(projection)
        keys = {f"{e['ref']['collection']}:{e['ref']['id']}:{e['ref']['version']}" for e in projection["records"]}
        self.assertEqual(self.fragment_keys(fixture), set(fragments))
        without_prose = {key.split(":")[0] for key in keys - set(fragments)}
        self.assertEqual({"anchors", "audits", "coverage", "observations", "responses", "sources",
                          "target_specs", "proof_boundaries"}, without_prose)
        self.assertEqual({"label_html": "Lemma 1", "statement_html": "Lemma 1 text"}, fragments["items:itm_lem:1"])
        self.assertEqual({"reason_html": "applied as stated"}, fragments["uses:use_lem_thm:1"])
        self.assertEqual({"rationale_html": "one step"}, fragments["groups:grp_lem:1"])
        self.assertEqual({"rationale_html": "adjudicated"}, fragments["reconciliations:rec_lem:1"])
        self.assertEqual({"conditions_html": [], "reasoning_html": "checked against the source"},
                         fragments["checks:chk_comp_lem:1"])
        # An empty condition list is still a fragment: the renderer must be told the list is empty.
        self.assertEqual({"conditions_html": []}, fragments["scopes:scp_plain:1"])

    def test_statement_math_is_typeset_into_the_item_fragment(self):
        """An item statement carrying LaTeX becomes MathML while keeping the surrounding prose."""
        self.fixture_class = MathFixture
        fixture = self.complete_paper()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
        statement = publish.display_fragments(projection)["items:itm_lem:1"]["statement_html"]
        self.assertTrue(statement.startswith("Lemma 1: for every "), statement[:60])
        self.assertTrue(statement.endswith("."), statement[-40:])
        self.assertEqual(2, statement.count('<math display="inline"'), statement)
        self.assertIn(r'<annotation encoding="application/x-tex">a_n \le 1</annotation>', statement)
        self.assertIn("<msub><mi>a</mi><mi>n</mi></msub>", statement)
        self.assertNotIn("math-fallback", statement)
        self.assertNotIn("$", statement)

    def test_only_the_documented_fields_become_fragments(self):
        """statement dicts unwrap to their text, string condition lists render, everything else is dropped."""
        projection = {"records": [
            {"ref": {"collection": "checks", "id": "chk_a", "version": 3},
             "body": {"reasoning": "because $n$", "conditions": ["if $n$", "plain"], "next_action": None,
                      "outcome": "supported"}},
            {"ref": {"collection": "items", "id": "itm_a", "version": 2},
             "body": {"statement": {"form": "verbatim", "text": "S & T"}, "label": "Lemma 9 <x> & y"}},
            {"ref": {"collection": "checks", "id": "chk_b", "version": 1},
             "body": {"conditions": [{"text": "structured"}]}},
            {"ref": {"collection": "items", "id": "itm_b", "version": 1},
             "body": {"statement": None, "reason": None, "label": "Lemma 8"}},
        ]}
        fragments = publish.display_fragments(projection)
        self.assertEqual({"checks:chk_a:3", "items:itm_a:2", "items:itm_b:1"}, set(fragments))
        self.assertEqual({"conditions_html", "reasoning_html"}, set(fragments["checks:chk_a:3"]))
        conditions = fragments["checks:chk_a:3"]["conditions_html"]
        self.assertEqual(2, len(conditions))
        self.assertTrue(conditions[0].startswith("if <math "), conditions[0])
        self.assertIn('<annotation encoding="application/x-tex">n</annotation>', conditions[0])
        self.assertEqual("plain", conditions[1])
        self.assertEqual({"label_html": "Lemma 9 &lt;x&gt; &amp; y", "statement_html": "S &amp; T"},
                         fragments["items:itm_a:2"])
        self.assertEqual({"label_html": "Lemma 8"}, fragments["items:itm_b:1"])

    def test_the_remaining_prose_fields_render_under_their_own_html_names(self):
        """reason, needed_form and description each become ``<field>_html`` with the same escaping rules."""
        projection = {"records": [
            {"ref": {"collection": "uses", "id": "u1", "version": 4},
             "body": {"reason": "r & r", "needed_form": "form $n$", "type": "dependency"}},
            {"ref": {"collection": "responses", "id": "s1", "version": 2},
             "body": {"description": "desc <x>", "state": "accepted"}},
        ]}
        fragments = publish.display_fragments(projection)
        self.assertEqual({"uses:u1:4", "responses:s1:2"}, set(fragments))
        self.assertEqual({"reason_html", "needed_form_html"}, set(fragments["uses:u1:4"]))
        self.assertEqual("r &amp; r", fragments["uses:u1:4"]["reason_html"])
        needed = fragments["uses:u1:4"]["needed_form_html"]
        self.assertTrue(needed.startswith("form <math "), needed)
        self.assertIn('<annotation encoding="application/x-tex">n</annotation>', needed)
        self.assertEqual({"description_html": "desc &lt;x&gt;"}, fragments["responses:s1:2"])

    def test_render_input_carries_the_build_identity(self):
        """render_input pins version, title, core version, revision, audit, source identity and kind."""
        fixture = self.complete_paper()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
            payload = publish.render_input(db, projection, release=True, source_identity="src-identity-x")
            working = publish.render_input(db, projection, release=False, source_identity="src-identity-x")
        self.assertEqual(1, payload["render_input_version"])
        self.assertEqual("Test paper", payload["title"])
        self.assertEqual({"core_version": CORE_VERSION, "revision": projection["snapshot_revision"],
                          "audit_id": "aud_1", "source_identity": "src-identity-x", "kind": "release"},
                         {k: v for k, v in payload["build"].items() if k != "built_at"})
        self.assertRegex(payload["build"]["built_at"], ISO_INSTANT)
        self.assertEqual("working", working["build"]["kind"])
        self.assertEqual({"build", "display", "projection", "render_input_version", "title"}, set(payload))

    def test_render_input_embeds_the_projection_and_its_fragments_unaltered(self):
        """The payload carries the whole projection, and building it never edits the caller's projection."""
        fixture = self.complete_paper()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
            untouched = copy.deepcopy(projection)
            payload = publish.render_input(db, projection, release=False, source_identity="sid")
        # Compared against a copy taken before the call, so an in-place edit of the caller's projection
        # cannot hide behind the payload embedding that same object.
        self.assertEqual(untouched, payload["projection"])
        self.assertEqual(untouched, projection)
        self.assertEqual(publish.display_fragments(untouched), payload["display"]["refs"])
        self.assertEqual({"label_html": "Lemma 1", "statement_html": "Lemma 1 text"},
                         payload["display"]["refs"]["items:itm_lem:1"])
        self.assertEqual(self.fragment_keys(fixture), set(payload["display"]["refs"]))


# -- the Node renderer -----------------------------------------------------------------------------
class RenderHtmlTests(PublicationCase):
    """``render_html`` runs the bundled renderer and refuses anything it cannot vouch for."""

    def setUp(self):
        super().setUp()
        self.require_node()

    def test_the_page_shows_the_item_labels_and_the_typeset_statement_math(self):
        """The visible report, not just its JSON data islands, carries the labels and the MathML."""
        self.fixture_class = MathFixture
        fixture = self.complete_paper()
        workdir = self.scratch()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
            html, _ = publish.render_html(db, projection, release=False, source_identity="sid", workdir=workdir)
        visible = DATA_ISLANDS.sub(b"", html)
        self.assertLess(len(visible), len(html))
        self.assertNotIn(b'"snapshot_revision"', visible)
        self.assertRegex(visible, br'<g data-node-id="itm_lem"[^>]*aria-label="Lemma 1\.')
        self.assertRegex(visible, br'<g data-node-id="itm_thm"[^>]*aria-label="Theorem 1\.')
        self.assertIn(br'aria-label="LaTeX: a_n \le 1"', visible)
        self.assertIn(br'<annotation encoding="application/x-tex">a_n \le 1</annotation>', visible)
        self.assertIn(b"<msub><mi>a</mi><mi>n</mi></msub>", visible)
        self.assertNotIn(b"math-fallback", visible)

    def test_the_receipt_pins_the_page_hash_the_input_and_the_projection_shape(self):
        """render_html returns only build evidence: hashes, both acceptance verdicts and the shape counts."""
        fixture = self.complete_paper()
        workdir = self.scratch()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
            html, receipt = publish.render_html(db, projection, release=False, source_identity="sid",
                                                workdir=workdir)
            self.assertEqual([], db.publications())
        self.assertEqual(RENDER_ONLY_RECEIPT_KEYS, set(receipt))
        self.assertEqual(hashlib.sha256(html).hexdigest(), receipt["artifact_sha256"])
        self.assertEqual(html, (workdir / "report.html").read_bytes())
        rendered_input = (workdir / "render-input.json").read_bytes()
        self.assertEqual(hashlib.sha256(rendered_input).hexdigest(), receipt["input_sha256"])
        self.assertEqual(len(rendered_input), receipt["input_bytes"])
        self.assertEqual({"status": "pass", "checks": REPRESENTATION_CHECKS}, receipt["representation"])
        self.assertEqual({"status": "pass", "checks": GEOMETRY_CHECKS, "diagnostics": []}, receipt["geometry"])
        self.assertEqual({"status": "pass", "failures": [], "nodes": 2, "connections": 1, "layout_mode": "dag"},
                         receipt["python_acceptance"])
        self.assertEqual((len(projection["nodes"]), len(projection["connections"]), projection["layout"]["mode"]),
                         (receipt["nodes"], receipt["connections"], receipt["layout_mode"]))

    def test_the_rendered_input_is_the_payload_render_input_builds(self):
        """The file handed to the renderer is compact JSON of render_input, modulo its build timestamp."""
        fixture = self.complete_paper()
        workdir = self.scratch()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
            publish.render_html(db, projection, release=True, source_identity="sid-42", workdir=workdir)
            expected = publish.render_input(db, projection, release=True, source_identity="sid-42")
        raw = (workdir / "render-input.json").read_bytes()
        written = json.loads(raw.decode("utf-8"))
        # Byte-exact: the receipt's input_sha256 is only evidence if the serialisation is fixed.
        self.assertEqual(json.dumps(written, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), raw)
        expected["build"]["built_at"] = written["build"]["built_at"]
        self.assertEqual(expected, written)
        self.assertEqual("release", written["build"]["kind"])
        self.assertEqual("sid-42", written["build"]["source_identity"])

    def test_a_projection_the_renderer_rejects_raises_and_writes_no_page(self):
        """An unknown node kind fails at the renderer's validate stage and leaves no output file."""
        fixture = self.complete_paper()
        workdir = self.scratch()
        with fixture.open(write=False) as db:
            projection = build_projection(db, audit_id="aud_1")
            broken = copy.deepcopy(projection)
            broken["nodes"][0]["kind"] = "not_a_kind"
            with self.assertRaises(PublicationError) as caught:
                publish.render_html(db, broken, release=False, source_identity="sid", workdir=workdir)
        error = caught.exception
        self.assertEqual(("PUBLICATION_FAILED", 6, "renderer failed"), (error.code, error.exit_code, error.message))
        self.assertEqual(1, len(error.records))
        self.assertEqual("validate", error.records[0]["stage"])
        self.assertIs(False, error.records[0]["ok"])
        self.assertTrue(any("not_a_kind" in line for line in error.records[0]["diagnostics"]),
                        error.records[0]["diagnostics"])
        self.assertFalse((workdir / "report.html").exists())


# -- mechanical acceptance -------------------------------------------------------------------------
class MechanicalAcceptanceTests(PublicationCase):
    """The Python scan is a second opinion on the page: every identity marker must match the projection."""

    def setUp(self):
        super().setUp()
        self.require_node()
        fixture = self.complete_paper()
        self.db = fixture.open(write=False)
        self.addCleanup(self.db.close)
        self.projection = build_projection(self.db, audit_id="aud_1")
        self.html, _ = publish.render_html(self.db, self.projection, release=False, source_identity="sid",
                                           workdir=self.scratch())

    def swap(self, old: bytes, new: bytes) -> bytes:
        self.assertEqual(1, self.html.count(old), f"expected exactly one {old!r} in the page")
        return self.html.replace(old, new)

    def before_body_end(self, injected: bytes) -> bytes:
        return self.swap(b"</body>", injected + b"</body>")

    def test_a_faithful_page_passes_with_the_projection_shape(self):
        """The page the renderer just produced accepts, reporting the projection's own shape."""
        self.assertEqual({"status": "pass", "failures": [], "nodes": 2, "connections": 1, "layout_mode": "dag"},
                         publish.mechanical_acceptance(self.html, self.projection))

    def test_a_changed_embedded_projection_is_detected(self):
        """Editing the embedded projection, even by one revision digit, fails acceptance."""
        revision = self.projection["snapshot_revision"]
        tampered = self.swap(f'"snapshot_revision":{revision}'.encode(),
                             f'"snapshot_revision":{revision - 1}'.encode())
        result = publish.mechanical_acceptance(tampered, self.projection)
        self.assertEqual(["embedded projection differs from the built projection"], result["failures"])
        self.assertEqual("fail", result["status"])

    def test_an_unreadable_embedded_projection_is_reported(self):
        """A projection script that is not JSON is reported rather than silently ignored."""
        tampered = self.swap(b'<script id="proof-projection" type="application/json">',
                             b'<script id="proof-projection" type="application/json">not json ')
        result = publish.mechanical_acceptance(tampered, self.projection)
        self.assertEqual("fail", result["status"])
        self.assertEqual(1, len(result["failures"]), result["failures"])
        self.assertTrue(result["failures"][0].startswith("embedded projection is not JSON:"), result["failures"])

    def test_each_visible_identity_marker_must_match_the_projection(self):
        """A single wrong state, count or completion marker produces exactly its own failure line."""
        connection = self.projection["connections"][0]["id"]
        cases = [
            ('data-node-id="itm_lem" data-node-label="Lemma 1" data-node-sublabel="Lemma 1" data-node-state="green"',
             'data-node-id="itm_lem" data-node-label="Lemma 1" data-node-sublabel="Lemma 1" data-node-state="red"',
             "node itm_lem shows state 'red'"),
            ('data-edge-state="green"', 'data-edge-state="amber"',
             f"connection {connection} shows ('itm_lem', 'itm_thm', 'amber')"),
            ('data-proof-count="nodes.green">2<', 'data-proof-count="nodes.green">3<',
             "count nodes.green shows '3', projection has 2"),
            ('data-proof-count="progress.required_obligations">13<',
             'data-proof-count="progress.required_obligations">10<',
             "count progress.required_obligations shows '10', projection has 13"),
            ('data-proof-process-complete="true"', 'data-proof-process-complete="false"',
             "process completion marker shows ['false']"),
        ]
        for old, new, expected in cases:
            with self.subTest(marker=old):
                result = publish.mechanical_acceptance(self.swap(old.encode(), new.encode()), self.projection)
                self.assertEqual([expected], result["failures"])

    def test_a_missing_status_count_is_a_failure_not_a_pass(self):
        """Deleting a count element is caught: an absent count reads as None, never as agreement."""
        tampered = self.swap(b'data-proof-count="connections.green"', b'data-absent-count="connections.green"')
        result = publish.mechanical_acceptance(tampered, self.projection)
        self.assertEqual(["count connections.green shows None, projection has 1"], result["failures"])

    def test_a_stray_diagram_identity_is_rejected(self):
        """The diagram may show exactly the projection's nodes and connections, no more."""
        cases = [
            (b'<g data-node-id="ghost" data-node-state="green"></g>',
             "diagram node identities differ from projection nodes"),
            (b'<path data-edge-id="ghost" data-edge-from="itm_lem" data-edge-to="itm_thm"'
             b' data-edge-state="green"></path>',
             "diagram edge identities differ from projection connections"),
            (b'<article data-proof-index-item="itm_lem" data-node-state="green"></article>',
             "dag mode emitted index articles"),
        ]
        for injected, expected in cases:
            with self.subTest(injected=injected):
                result = publish.mechanical_acceptance(self.before_body_end(injected), self.projection)
                self.assertEqual([expected], result["failures"])

    def test_readable_scope_labels_keep_exact_target_identity(self):
        marker = b'<span data-proof-scope-target="items:itm_thm">'
        self.assertIn(marker, self.html)
        for replacement in (b'<span data-proof-scope-target="items:itm_lem">',
                            marker + b'Unrelated label '):
            with self.subTest(replacement=replacement):
                result = publish.mechanical_acceptance(self.swap(marker, replacement), self.projection)
                self.assertIn("visible audit scope differs from the canonical scope", result["failures"])

    def test_a_listed_finding_or_source_limit_must_come_from_the_summary(self):
        """The page cannot invent a finding or a source limitation the summary does not carry."""
        self.assertEqual([], self.projection["summary"]["findings"]["refs"])
        self.assertEqual([], self.projection["summary"]["source_limits"])
        cases = [
            (b'<li data-proof-finding="fnd_ghost"></li>', "listed findings differ from summary.findings.refs"),
            (b'<li data-proof-source-limit="src_ghost"></li>',
             "listed source limits differ from summary.source_limits"),
        ]
        for injected, expected in cases:
            with self.subTest(injected=injected):
                result = publish.mechanical_acceptance(self.before_body_end(injected), self.projection)
                self.assertEqual([expected], result["failures"])

    def test_a_page_that_reaches_out_to_the_network_is_rejected(self):
        """A report must be self-contained: any external src or href in a non-anchor fails acceptance."""
        tampered = self.before_body_end(b'<img src="https://example.invalid/pixel.png" alt="">')
        result = publish.mechanical_acceptance(tampered, self.projection)
        self.assertEqual(["page references external resources: ['https://example.invalid/pixel.png']"],
                         result["failures"])

    def test_a_plain_outbound_link_is_not_an_external_resource(self):
        """The rule targets loaded resources, so an ``<a href>`` to the web is explicitly allowed."""
        tampered = self.before_body_end(b'<a href="https://example.invalid/paper">source</a>')
        self.assertEqual({"status": "pass", "failures": [], "nodes": 2, "connections": 1, "layout_mode": "dag"},
                         publish.mechanical_acceptance(tampered, self.projection))

    def test_a_dag_page_is_rejected_against_an_index_mode_projection(self):
        """Layout mode is part of the identity: dag markup cannot satisfy an index-mode projection."""
        claimed = copy.deepcopy(self.projection)
        claimed["layout"] = {"mode": "index", "reasons": ["forced for the test"]}
        result = publish.mechanical_acceptance(self.html, claimed)
        self.assertEqual("index", result["layout_mode"])
        self.assertEqual(["embedded projection differs from the built projection",
                          "index item identities differ from projection nodes",
                          "index connection identities differ from projection connections",
                          "index mode emitted diagram elements"], result["failures"])


# -- publish_report --------------------------------------------------------------------------------
class PublishReportTests(PublicationCase):
    """``publish_report`` writes the page atomically and records what it wrote."""

    def setUp(self):
        super().setUp()
        self.require_node()

    def test_a_working_publication_writes_the_page_blob_and_row(self):
        """The page, the stored blob and the publications row all agree on one artifact hash."""
        fixture = self.complete_paper()
        output = self.work / "out" / "report.html"
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            result = publish.publish_report(db, projection=projection, output=output)
            rows = db.publications()
            self.assertTrue(db.has_blob(result["artifact_sha256"]))
            self.assertEqual(output.read_bytes(), db.get_blob(result["artifact_sha256"]))
        self.assertEqual(("published", "working", projection["snapshot_revision"], str(output)),
                         (result["state"], result["kind"], result["revision"], result["output_path"]))
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), result["artifact_sha256"])
        self.assertEqual(1, len(rows))
        self.assertEqual((result["publication_id"], projection["snapshot_revision"], "working", "published",
                          str(output), result["artifact_sha256"]),
                         (rows[0]["id"], rows[0]["revision"], rows[0]["kind"], rows[0]["state"],
                          rows[0]["output_path"], rows[0]["artifact_sha256"]))
        self.assertEqual(result["receipt"], json.loads(rows[0]["receipt_json"]))
        self.assertEqual(["report.html"], sorted(p.name for p in output.parent.iterdir()))

    def test_a_database_with_no_statements_publishes_an_index_page(self):
        """A checkpoint straight after init has nothing to lay out; it publishes an index page, not bad geometry."""
        root = self.scratch("empty")
        (root / "paper.tex").write_text(support.PAPER_TEX, encoding="utf-8")
        database = root / "paper.db"
        run_cli("init", database, "--source-root", root, "--title", "Empty paper")
        output = self.work / "out" / "report.html"
        payload, _ = run_cli("checkpoint", database, "--out", output)
        self.assertEqual(("published", "index", 0, 0),
                         (payload["state"], payload["receipt"]["layout_mode"], payload["receipt"]["nodes"],
                          payload["receipt"]["connections"]))
        self.assertEqual("not_applicable", payload["receipt"]["geometry"]["status"])
        self.assertEqual("pass", payload["receipt"]["python_acceptance"]["status"])
        self.assertIn(b"No statements are recorded yet", output.read_bytes())

    def test_the_receipt_records_the_projection_identity_and_both_acceptances(self):
        """The stored receipt names the publication and pins the rendered projection's shape."""
        fixture = self.complete_paper()
        output = self.work / "out" / "report.html"
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            result = publish.publish_report(db, projection=projection, output=output,
                                            publication_id="pub_fixed_for_test")
        receipt = result["receipt"]
        self.assertEqual(PUBLICATION_RECEIPT_KEYS, set(receipt))
        self.assertEqual("pub_fixed_for_test", result["publication_id"])
        self.assertEqual(("pub_fixed_for_test", "working", "published", str(output)),
                         (receipt["publication_id"], receipt["kind"], receipt["state"], receipt["output_path"]))
        self.assertEqual((len(projection["nodes"]), len(projection["connections"]), projection["layout"]["mode"]),
                         (receipt["nodes"], receipt["connections"], receipt["layout_mode"]))
        self.assertEqual({"status": "pass", "failures": [], "nodes": 2, "connections": 1, "layout_mode": "dag"},
                         receipt["python_acceptance"])
        self.assertEqual({"status": "pass", "checks": REPRESENTATION_CHECKS}, receipt["representation"])
        self.assertEqual(result["artifact_sha256"], receipt["artifact_sha256"])
        self.assertRegex(receipt["started_at"], ISO_INSTANT)

    def test_a_release_publication_is_stamped_release_everywhere(self):
        """release=True marks the result, the receipt, the row and the page's own embedded build."""
        fixture = self.complete_paper()
        output = self.work / "rel" / "report.html"
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            result = publish.publish_report(db, projection=projection, output=output, release=True)
            rows = db.publications()
        self.assertEqual(("release", "release"), (result["kind"], result["receipt"]["kind"]))
        self.assertEqual([("release", "published")], [(row["kind"], row["state"]) for row in rows])
        page = output.read_bytes()
        self.assertIn(b'"kind":"release"', page)
        self.assertNotIn(b'"kind":"working"', page)

    def test_the_default_source_identity_is_the_database_source_digest(self):
        """Omitting source_identity stamps the page with the paper's own source-context digest."""
        fixture = self.complete_paper()
        output = self.work / "out" / "report.html"
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            digest = source_context_digest(db)
            publish.publish_report(db, projection=projection, output=output)
        self.assertRegex(digest, SHA256_HEX)
        page = output.read_bytes()
        self.assertIn(f'"source_identity":"{digest}"'.encode(), page)

    def test_publishing_sets_the_published_revision_of_later_projections(self):
        """Before any publication summary.published_revision is None; afterwards it is the published revision."""
        fixture = self.complete_paper()
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            self.assertIsNone(projection["summary"]["published_revision"])
            publish.publish_report(db, projection=projection, output=self.work / "out" / "report.html")
            later = build_projection(db, audit_id="aud_1")
        self.assertEqual(projection["snapshot_revision"], later["summary"]["published_revision"])

    def test_a_read_only_database_cannot_publish(self):
        """Publication needs a writable database; the refusal writes no file at all."""
        fixture = self.complete_paper()
        output = self.work / "ro" / "report.html"
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
        with fixture.open(write=False) as db:
            with self.assertRaises(InvalidRequest) as caught:
                publish.publish_report(db, projection=projection, output=output)
            self.assertEqual([], db.publications())
        self.assertEqual("INVALID_REQUEST", caught.exception.code)
        self.assertEqual("publication requires a writable database", caught.exception.message)
        self.assertFalse(output.exists())
        self.assertFalse(output.parent.exists())

    def test_a_directory_as_the_output_path_is_refused(self):
        """Pointing the output at an existing directory is refused before anything is rendered."""
        fixture = self.complete_paper()
        directory = self.scratch("already-a-directory")
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            with self.assertRaises(InvalidRequest) as caught:
                publish.publish_report(db, projection=projection, output=directory)
            self.assertEqual([], db.publications())
        self.assertEqual("INVALID_REQUEST", caught.exception.code)
        self.assertEqual(f"output path is a directory: {directory}", caught.exception.message)
        self.assertEqual([], list(directory.iterdir()))

    def test_a_failed_render_retains_the_prior_page_and_records_a_failed_row(self):
        """When the renderer rejects the projection the previous page survives byte for byte."""
        fixture = self.complete_paper()
        output = self.work / "out" / "report.html"
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            good = publish.publish_report(db, projection=projection, output=output)
            before = output.read_bytes()
            broken = copy.deepcopy(projection)
            broken["nodes"][0]["kind"] = "not_a_kind"
            with self.assertRaises(PublicationError) as caught:
                publish.publish_report(db, projection=broken, output=output)
            rows = db.publications()
            self.assertTrue(db.has_blob(good["artifact_sha256"]))
        error = caught.exception
        self.assertEqual(("PUBLICATION_FAILED", 6), (error.code, error.exit_code))
        self.assertIs(True, error.records[-1]["prior_output_retained"])
        self.assertEqual(before, output.read_bytes())
        self.assertEqual(["report.html"], sorted(p.name for p in output.parent.iterdir()))
        self.assertEqual([("published", good["artifact_sha256"]), ("failed", None)],
                         [(row["state"], row["artifact_sha256"]) for row in rows])
        failed = rows[1]
        self.assertEqual((error.records[-1]["publication_id"], projection["snapshot_revision"], "working"),
                         (failed["id"], failed["revision"], failed["kind"]))
        stored = json.loads(failed["receipt_json"])
        self.assertEqual("failed", stored["state"])
        self.assertEqual("PUBLICATION_FAILED", stored["error"]["code"])
        self.assertEqual("renderer failed", stored["error"]["message"])
        self.assertEqual(str(output), stored["output_path"])

    def test_a_failed_first_publication_leaves_nothing_at_the_destination(self):
        """With no prior page the failure reports no retention and creates no file in the output directory."""
        fixture = self.complete_paper()
        output = self.work / "fresh" / "report.html"
        with fixture.open(write=True) as db:
            projection = build_projection(db, audit_id="aud_1")
            broken = copy.deepcopy(projection)
            broken["nodes"][0]["kind"] = "not_a_kind"
            with self.assertRaises(PublicationError) as caught:
                publish.publish_report(db, projection=broken, output=output)
            rows = db.publications()
        self.assertIs(False, caught.exception.records[-1]["prior_output_retained"])
        self.assertFalse(output.exists())
        self.assertEqual([], list(output.parent.iterdir()))
        self.assertEqual([("failed", None)], [(row["state"], row["artifact_sha256"]) for row in rows])


# -- the release command ---------------------------------------------------------------------------
class ReleaseCommandTests(PublicationCase):
    """``release`` publishes only a process-complete audit, and only into an empty directory."""

    def setUp(self):
        super().setUp()
        self.require_node()

    def test_release_is_refused_while_the_process_is_incomplete(self):
        """An audit with unmet obligations is blocked with RELEASE_BLOCKED and no directory is created."""
        root = self.work / "incomplete"
        root.mkdir(parents=True)
        fixture = Fixture(root)
        fixture.primary()
        output = self.work / "release-attempt"
        payload, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", output, expect=2)
        self.assertEqual("RELEASE_BLOCKED", payload["error"]["code"])
        self.assertIn("audit aud_1 is not process-complete", payload["error"]["message"])
        records = payload["error"]["records"]
        self.assertEqual(["obligation"] * 4, [record["kind"] for record in records])
        ids = [record["id"] for record in records]
        self.assertEqual(4, len(set(ids)))
        for obligation_id in ids:
            self.assertRegex(obligation_id, r"^obl_[0-9a-f]{64}$")
        self.assertFalse(output.exists())
        with fixture.open(write=False) as db:
            self.assertEqual([], db.publications())

    def test_a_release_writes_report_export_and_receipt_with_matching_hashes(self):
        """The three release files are written, marked release kind, and the receipt hashes match them."""
        fixture = self.complete_paper()
        output = self.work / "release"
        payload, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", output)
        self.assertEqual(["export.json", "receipt.json", "report.html"], sorted(p.name for p in output.iterdir()))
        self.assertEqual(["report.html", "export.json", "receipt.json"], payload["files"])
        self.assertEqual(str(output), payload["directory"])
        self.assertIs(True, payload["process_complete"])
        self.assertEqual({"ok": True, "warnings": []}, payload["validation"])
        self.assertEqual(("proofcheck-records/4", CORE_VERSION, "aud_1"),
                         (payload["contract"], payload["core_version"], payload["audit_id"]))
        report = (output / "report.html").read_bytes()
        self.assertEqual(hashlib.sha256(report).hexdigest(), payload["publication"]["artifact_sha256"])
        self.assertEqual(hashlib.sha256((output / "export.json").read_bytes()).hexdigest(),
                         payload["export"]["sha256"])
        self.assertEqual(("release", "published", payload["revision"], str(output / "report.html")),
                         (payload["publication"]["kind"], payload["publication"]["state"],
                          payload["publication"]["revision"], payload["publication"]["output_path"]))
        self.assertEqual(payload["revision"], payload["export"]["revision"])
        self.assertIn(b'"kind":"release"', report)
        self.assertNotIn(b'"kind":"working"', report)
        on_disk = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in payload.items() if k not in ("directory", "files")}, on_disk)
        with fixture.open(write=False) as db:
            self.assertEqual([("release", "published")], [(r["kind"], r["state"]) for r in db.publications()])

    def test_the_released_export_carries_the_same_revision_and_contract(self):
        """export.json is the self-describing archive of the released revision, not a loose dump."""
        fixture = self.complete_paper()
        output = self.work / "release"
        payload, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", output)
        export = json.loads((output / "export.json").read_text(encoding="utf-8"))
        self.assertEqual((4, 4, payload["revision"], payload["paper_id"]),
                         (export["contract_version"], export["storage_format"], export["revision"],
                          export["paper_id"]))
        self.assertEqual(CORE_VERSION, export["provenance"]["core_version"])
        self.assertRegex(export["provenance"]["source_identity"], SHA256_HEX)
        self.assertEqual([], payload["export"]["missing_blobs"])
        self.assertEqual((len(export["records"]), len(export["history"]), len(export["blobs"])),
                         (payload["export"]["records"], payload["export"]["history"], payload["export"]["blobs"]))

    def test_released_files_are_left_read_only(self):
        """A release is evidence: every written file loses its write bits so it cannot be edited in place."""
        fixture = self.complete_paper()
        output = self.work / "release"
        run_cli("release", fixture.path, "--audit", "aud_1", "--out", output)
        for path in sorted(output.iterdir()):
            with self.subTest(name=path.name):
                self.assertEqual(0, stat.S_IMODE(path.stat().st_mode) & 0o222, path.name)

    def test_a_second_release_into_the_same_directory_is_refused(self):
        """A non-empty output directory is refused and the released files are left untouched."""
        fixture = self.complete_paper()
        output = self.work / "release"
        first, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", output)
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        payload, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", output, expect=2)
        self.assertEqual("INVALID_REQUEST", payload["error"]["code"])
        self.assertIn("is not empty", payload["error"]["message"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
        with fixture.open(write=False) as db:
            rows = db.publications()
        self.assertEqual([first["publication"]["publication_id"]], [row["id"] for row in rows])


# -- the renderer is unavailable -------------------------------------------------------------------
class MissingRendererTests(PublicationCase):
    """Ported from stat-paper-proofcheck test_transaction_publication: a failed build never damages the
    page that is already published."""

    def setUp(self):
        super().setUp()
        self.require_node()

    def test_a_checkpoint_without_node_fails_and_keeps_the_published_page(self):
        """With no node on PATH the command exits 6, reports the retained output, and the page is unchanged."""
        fixture = self.complete_paper()
        output = self.work / "checkpoints" / "report.html"
        first, _ = run_cli("checkpoint", fixture.path, "--out", output)
        before = output.read_bytes()
        self.assertEqual(hashlib.sha256(before).hexdigest(), first["artifact_sha256"])

        blind = dict(CLI_ENV, PATH="")
        payload, stderr = run_cli("checkpoint", fixture.path, "--out", output, expect=6, env=blind)
        self.assertEqual("PUBLICATION_FAILED", payload["error"]["code"])
        self.assertEqual("Node.js is required to render reports but no `node` executable was found",
                         payload["error"]["message"])
        self.assertIn("PUBLICATION_FAILED", stderr)
        self.assertEqual(1, len(payload["error"]["records"]))
        retained = payload["error"]["records"][-1]
        self.assertIs(True, retained["prior_output_retained"])

        self.assertEqual(before, output.read_bytes(), "the previously published report must survive byte for byte")
        self.assertEqual(["report.html"], sorted(p.name for p in output.parent.iterdir()))
        with fixture.open(write=False) as db:
            rows = db.publications()
            self.assertTrue(db.has_blob(first["artifact_sha256"]))
        self.assertEqual([("published", first["artifact_sha256"]), ("failed", None)],
                         [(row["state"], row["artifact_sha256"]) for row in rows])
        self.assertEqual(retained["publication_id"], rows[1]["id"])
        self.assertEqual(first["revision"], rows[1]["revision"])
        stored = json.loads(rows[1]["receipt_json"])
        self.assertEqual(("failed", "PUBLICATION_FAILED", str(output)),
                         (stored["state"], stored["error"]["code"], stored["output_path"]))

    def test_a_release_without_node_leaves_the_release_directory_empty(self):
        """The release command needs the renderer too: the directory is made but no release file lands."""
        fixture = self.complete_paper()
        output = self.work / "release"
        blind = dict(CLI_ENV, PATH="")
        payload, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", output, expect=6, env=blind)
        self.assertEqual("PUBLICATION_FAILED", payload["error"]["code"])
        self.assertEqual("Node.js is required to render reports but no `node` executable was found",
                         payload["error"]["message"])
        publication = next(record for record in payload["error"]["records"]
                           if "prior_output_retained" in record)
        self.assertIs(False, publication["prior_output_retained"])
        delivery = next(record for record in payload["error"]["records"] if "delivery_complete" in record)
        self.assertIs(False, delivery["delivery_complete"])
        self.assertEqual("report", delivery["stage"])
        self.assertEqual([], delivery["available_files"])
        self.assertTrue(output.is_dir(), output)
        self.assertEqual([], sorted(p.name for p in output.iterdir()))
        with fixture.open(write=False) as db:
            rows = db.publications()
        self.assertEqual([("release", "failed", None, str(output / "report.html"))],
                         [(r["kind"], r["state"], r["artifact_sha256"], r["output_path"]) for r in rows])


# -- the renderer's own self-test ------------------------------------------------------------------
class RendererSelftestTests(unittest.TestCase):
    """The bundled renderer ships its own fixture and vendored-hash self-test; it must pass here."""

    def test_the_renderer_selftest_passes_every_check(self):
        """node selftest.mjs exits 0 with every vendored hash, fixture render and the cycle failure ok."""
        if not support.node_available():
            self.skipTest(NO_NODE)
        self.assertTrue(SELFTEST.is_file(), f"missing {SELFTEST}")
        run = subprocess.run(["node", str(SELFTEST)], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", cwd=str(RENDERER_DIR))
        self.assertEqual(0, run.returncode, f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}")
        report = json.loads(run.stdout)
        self.assertIs(True, report["ok"])
        self.assertEqual([], [check for check in report["checks"] if not check["ok"]])
        self.assertEqual(SELFTEST_CHECKS, [check["check"] for check in report["checks"]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
