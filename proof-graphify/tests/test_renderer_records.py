"""Exercise the prepared-record renderer independently of the storage adapter."""
from __future__ import annotations

from copy import deepcopy
from html import escape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


RENDERER = Path(__file__).resolve().parents[1] / "scripts" / "render.mjs"
NODE = shutil.which("node")


class RenderedRecords(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.svg_depth = 0
        self.nodes = []
        self.uses = []
        self.index_items = []
        self.index_uses = []
        self.record_text = []
        self.record_script = False
        self.regions = {}
        self.active_region = None
        self.feed(html)

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag == "svg":
            self.svg_depth += 1
        if self.svg_depth and "data-node-id" in attrs:
            self.nodes.append(attrs["data-node-id"])
        if self.svg_depth and "data-edge-id" in attrs:
            self.uses.append((attrs["data-edge-id"], attrs["data-edge-from"], attrs["data-edge-to"]))
        if tag == "article" and "data-proof-index-item" in attrs:
            self.index_items.append(attrs["data-proof-index-item"])
        if tag == "article" and "data-proof-index-use" in attrs:
            self.index_uses.append((attrs["data-proof-index-use"], attrs["data-proof-from"], attrs["data-proof-to"]))
        if tag in ("template", "article") and attrs.get("id"):
            self.active_region = (tag, attrs["id"])
            self.regions[self.active_region[1]] = []
        if tag == "script" and attrs.get("id") == "proof-overview-records":
            self.record_script = True

    def handle_endtag(self, tag):
        if tag == "svg":
            self.svg_depth -= 1
        if tag == "script":
            self.record_script = False
        if self.active_region and tag == self.active_region[0]:
            self.active_region = None

    def handle_data(self, text):
        if self.record_script:
            self.record_text.append(text)
        if self.active_region:
            self.regions[self.active_region[1]].append(text)

    @property
    def records(self):
        return json.loads("".join(self.record_text))


@unittest.skipUnless(NODE, "A shared Node installation is required.")
class RendererRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.input = self.base / "prepared.json"
        self.output = self.base / "overview.html"
        self.data = {
            "schema_version": 3,
            "details": [], "detail_uses": [],
            "graph_mode": "dag",
            "title": "Two distinct uses",
            "scope": "Synthetic renderer fixture.",
            "source": {"title": "Fixture paper"},
            "build_context": {
                "input_snapshot": "snapshot-example",
                "source_revision": "source-example",
                "source_status": "current",
                "source_comparison": {"status": "incomplete", "unreviewed": 2},
                "mathematical_assessment": "not_performed",
            },
            "items": [
                {"id": "bound", "kind": "lemma", "label": "Lemma 1", "caption": "Moment bound", "statement_html": "A bound holds.", "statement_form": "synopsis",
                 "aliases": ["lem:bound", "lem:moment"], "source_passages": [
                    {"role": "statement", "source_display": "main.tex:3", "source_excerpt": "STATEMENT PASSAGE", "verification": {"status": "checked", "method": "line_range"}},
                    {"role": "proof", "source_display": "supplement.tex:8", "source_excerpt": "PROOF PASSAGE", "verification": {"status": "checked", "method": "line_range"}},
                 ]},
                {"id": "rate", "kind": "theorem", "label": "Theorem 2", "caption": "Rate", "statement_html": "The rate follows."},
            ],
            "uses": [
                {"id": "use-moment", "from": "bound", "to": "rate", "type": "dependency", "reason": "Use the moment bound.",
                 "source_passages": [{"role": "evidence", "source_display": "main.tex:20", "source_excerpt": "FIRST USE PASSAGE", "verification": {"status": "checked", "method": "line_range"}}]},
                {"id": "use-tail", "from": "bound", "to": "rate", "type": "proof_argument", "regime": "Tail regime", "reason": "Use the separate tail argument.",
                 "source_passages": [{"role": "evidence", "source_display": "supplement.tex:30", "source_excerpt": "SECOND USE PASSAGE", "verification": {"status": "unverified", "method": "entered_locator"}}]},
            ],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def render(self, expect_success=True):
        self.input.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([NODE, str(RENDERER), str(self.input), str(self.output)], capture_output=True, text=True, encoding="utf-8")
        if not expect_success:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return json.loads(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        html = self.output.read_text(encoding="utf-8")
        return json.loads(result.stdout), html, RenderedRecords(html)

    def expected_uses(self):
        return sorted((use["id"], use["from"], use["to"]) for use in self.data["uses"])

    def test_parallel_uses_retain_separate_svg_paths_and_exact_records(self):
        original = deepcopy(self.data)
        receipt, _, rendered = self.render()
        self.assertEqual(sorted(rendered.nodes), ["bound", "rate"])
        self.assertEqual(sorted(rendered.uses), self.expected_uses())
        self.assertEqual(rendered.records["items"], original["items"])
        self.assertEqual(rendered.records["uses"], original["uses"])
        self.assertEqual(rendered.records["build_context"], original["build_context"])
        self.assertEqual(receipt["graph_preservation"]["status"], "pass")
        self.assertEqual(receipt["geometry"]["status"], "pass")
        for field in ("browser_review", "visual_review", "mathematical_assessment"):
            self.assertEqual(receipt[field], "not_performed")

    def test_main_result_selection_preserves_prerequisite_and_parallel_connections(self):
        self.data["main_items"] = ["rate"]
        _, html, rendered = self.render()
        self.assertEqual(sorted(rendered.nodes), ["bound", "rate"])
        self.assertEqual(sorted(rendered.uses), self.expected_uses())
        self.assertEqual(sorted(rendered.index_items), ["bound", "rate"])
        self.assertEqual(sorted(rendered.index_uses), self.expected_uses())
        self.assertIn("Selected statements and connections (2 statements, 2 connections)", html)
        self.assertTrue('<p class="proof-scope-lead">Synthetic renderer fixture.</p>' in html,
                        'The selected scope must remain visible above the graph.')
        self.assertEqual(re.findall(r'data-reader-node="([^"]+)"', html), ["rate", "bound"],
                         'The shared navigator leads with the main result and retains its prerequisite once.')
        self.assertNotIn("Intermediate steps (", html)

    def test_missing_connections_are_disclosed_in_graph_and_index(self):
        for mode in ("dag", "index"):
            with self.subTest(mode=mode):
                self.data["graph_mode"] = mode
                _, connected_html, _ = self.render()
                self.assertNotIn('class="proof-empty-connections"', connected_html)
                connected_uses = self.data["uses"]
                self.data["uses"] = []
                _, html, rendered = self.render()
                self.assertIn('class="proof-empty-connections" role="note"', html)
                self.assertIn("No connections are recorded in this overview. "
                              "This does not establish that the results are independent.", html)
                self.assertEqual(rendered.records["uses"], [])
                self.assertEqual(sorted(rendered.index_items), ["bound", "rate"])
                self.data["uses"] = connected_uses

    def test_all_passages_are_available_in_selection_and_static_index(self):
        _, _, rendered = self.render()
        for region in ("proof-detail-bound", "proof-index-item-bound"):
            text = " ".join(rendered.regions[region])
            for expected in ("STATEMENT PASSAGE", "PROOF PASSAGE", "FIRST USE PASSAGE", "SECOND USE PASSAGE", "lem:moment"):
                self.assertIn(expected, text, region)
        for use_id, excerpt in (("use-moment", "FIRST USE PASSAGE"), ("use-tail", "SECOND USE PASSAGE")):
            for prefix in ("proof-use-", "proof-index-use-"):
                self.assertIn(excerpt, " ".join(rendered.regions[prefix + use_id]))

    def test_connection_evidence_keeps_prepared_restrictions_in_its_body(self):
        formulas = (
            ('m_n', '<msub><mi>m</mi><mi>n</mi></msub>'),
            (r'\eta_n<1', '<msub><mi>η</mi><mi>n</mi></msub><mo>&lt;</mo><mn>1</mn>'),
            (r'k\leq n/2', '<mi>k</mi><mo>≤</mo><mi>n</mi><mo>/</mo><mn>2</mn>'),
        )
        math = [f'<math><semantics><mrow>{body}</mrow><annotation encoding="application/x-tex">'
                f'{escape(tex)}</annotation></semantics></math>' for tex, body in formulas]
        regime = r'Grid size \(m_n\), with \(\eta_n<1\) and \(k\leq n/2\).'
        prepared = f'Grid size {math[0]}, with {math[1]} and {math[2]}.'
        unsupported = r'When $\unresolvedRegimeMacro{x}$.'
        fallback = ('When <span class="math-fallback" title="Unsupported macro">'
                    '<span class="math-fallback-label">LaTeX (not rendered): </span>'
                    r'<code>\unresolvedRegimeMacro{x}</code></span>.')
        cases = (
            ('math', regime, prepared),
            ('prose', 'Fixed sample only', None),
            ('absent', None, None),
            ('escaped', '<img src="REGIME_ATTACK"> & fixed sample', None),
            ('unsupported', unsupported, fallback),
            ('parallel', regime, prepared),
        )
        original = deepcopy(self.data)
        for mode in ('dag', 'index'):
            for case, restriction, restriction_html in cases:
                with self.subTest(mode=mode, case=case):
                    self.data = deepcopy(original)
                    self.data['graph_mode'] = mode
                    self.data['items'][0]['label'] = 'A.3'
                    self.data['items'][1]['label'] = 'C.1'
                    if case == 'escaped':
                        self.data['items'][0]['label'] += ' <img src="LABEL_ATTACK"> & source'
                    first, second = self.data['uses']
                    if restriction is not None:
                        first['regime'] = restriction
                    if restriction_html is not None:
                        first['regime_html'] = restriction_html
                    if case == 'parallel':
                        second['type'] = first['type']
                    for use in self.data['uses']:
                        use.update(source_display=f"{use['id']} source", source_href=f"https://example.org/{use['id']}",
                                   fidelity='matched', comparison_note=f"Compared {use['id']} & retained.")
                    snapshot = deepcopy(self.data)
                    receipt, html, rendered = self.render()
                    for field in ('items', 'uses', 'details', 'detail_uses', 'build_context'):
                        self.assertEqual(rendered.records[field], snapshot[field])
                    self.assertEqual(receipt['graph_preservation']['status'], 'pass')
                    self.assertEqual(sorted(rendered.index_uses), self.expected_uses())
                    self.assertEqual(sorted(rendered.uses), self.expected_uses() if mode == 'dag' else [])
                    self.assertNotIn('<img src="REGIME_ATTACK">', html)
                    self.assertNotIn('<img src="LABEL_ATTACK">', html)
                    item_panels = [('proof-index-item-', 'article')]
                    if mode == 'dag':
                        item_panels.append(('proof-detail-', 'template'))
                    for prefix, tag in item_panels:
                        for item in self.data['items']:
                            panel = re.search(fr'<{tag}[^>]*id="{prefix}{item["id"]}"[^>]*>([\s\S]*?)</{tag}>', html).group(1)
                            disclosures = re.findall(r'data-proof-evidence-use="([^"]+)"><summary>(.*?)</summary>'
                                                     r'([\s\S]*?)(?=<details[^>]*data-proof-evidence-use=|$)', panel)
                            self.assertEqual([entry[0] for entry in disclosures], [use['id'] for use in self.data['uses']])
                            for (use_id, summary, body), use in zip(disclosures, self.data['uses']):
                                relation = 'Dependency' if use['type'] == 'dependency' else 'Proof argument'
                                self.assertEqual(summary, f'{escape(self.data["items"][0]["label"])} → '
                                                 f'{escape(self.data["items"][1]["label"])} ({relation})')
                                if use.get('regime'):
                                    expected = use.get('regime_html') or escape(use['regime'])
                                    for fragment in re.split(r'(<math>[\s\S]*?</math>)', expected):
                                        if fragment:
                                            self.assertIn(fragment, body)
                                    self.assertTrue(body.startswith('<p class="proof-regime">Only in regime: '))
                                else:
                                    self.assertNotIn('proof-regime', body)
                                    self.assertTrue(body.startswith('<div class="proof-hint proof-comparison-note">'))
                                self.assertIn(escape(use['comparison_note']), body)
                                self.assertIn(f'href="{use["source_href"]}"', body)
                                self.assertIn(use['source_passages'][0]['source_excerpt'], body)
                                other = second if use is first else first
                                self.assertNotIn(other['source_passages'][0]['source_excerpt'], body)
                    for use in self.data['uses']:
                        for prefix in (('proof-use-', 'proof-index-use-') if mode == 'dag' else ('proof-index-use-',)):
                            text = ' '.join(rendered.regions[prefix + use['id']])
                            self.assertIn(use['source_passages'][0]['source_excerpt'], text)
                            if use.get('regime'):
                                self.assertIn('Only in regime:', text)

    def test_result_sections_prioritize_authored_logic_and_retain_visible_status(self):
        node = self.data["items"][1]
        node.update({"fidelity": "needs_attention", "issue": "Confirm the applicable tail regime."})
        self.data["uses"][1]["fidelity"] = "stale"
        self.data["uses"][1]["issue"] = "Check the tail condition."
        _, baseline, _ = self.render()
        node.update({"proof_idea": "Combine the two bounds to control x.",
                     "proof_idea_html": 'Combine the two bounds to control <math><mi>x</mi></math>.'})
        _, html, rendered = self.render()
        self.assertEqual(re.search(r"<svg[\s\S]*?</svg>", baseline).group(),
                         re.search(r"<svg[\s\S]*?</svg>", html).group(),
                         "A proof idea must not change graph nodes or layout.")
        for prefix, tag in (("proof-detail-", "template"), ("proof-index-item-", "article")):
            panel = re.search(fr'<{tag}[^>]*id="{prefix}rate"[^>]*>([\s\S]*?)</{tag}>', html).group(1)
            self.assertRegex(panel, r'proof-statement-section"[^>]*><h4>Statement</h4>')
            self.assertIn('<h4>Proof idea</h4>', panel)
            self.assertIn('proof-idea">Combine the two bounds to control <span class="proof-formula"><math>', panel)
            self.assertLess(panel.index("The rate follows."), panel.index("Combine the two bounds"))
            self.assertLess(panel.index("The rate follows."), panel.index("Source comparison"))
            self.assertLess(panel.index("Source comparison"), panel.index("Combine the two bounds"))
            self.assertLess(panel.index("Combine the two bounds"), panel.index("Prerequisites (2)"))
            evidence = re.search(r'<details class="proof-evidence(?: [^"]*)?"', panel).start()
            for visible in ("Use the moment bound.", "Use the separate tail argument.",
                            "Confirm the applicable tail regime.", "Check the tail condition.",
                            'data-proof-fidelity="needs_attention"', 'data-proof-fidelity="stale"'):
                self.assertLess(panel.index(visible), evidence)
            for use_id, excerpt in (("use-moment", "FIRST USE PASSAGE"), ("use-tail", "SECOND USE PASSAGE")):
                self.assertIn(f'data-proof-evidence-use="{use_id}"', panel)
                self.assertGreater(panel.index(excerpt), evidence)
            self.assertNotIn("Proof idea", " ".join(rendered.regions[prefix + "bound"]))
        self.assertEqual(rendered.records["items"][1], node)

    def test_index_and_intermediate_proof_ideas_keep_math_and_escape_plain_text(self):
        self.data["graph_mode"] = "index"
        self.data["items"][1]["proof_idea"] = "Combine <untrusted> bounds."
        self.data["details"] = [{"id": "bound-detail", "owner": "bound", "kind": "claim",
                                 "label": "Intermediate claim", "statement_html": "The smaller bound holds.",
                                 "proof_idea": "Apply the estimate to x.",
                                 "proof_idea_html": 'Apply the estimate to <math><mi>x</mi></math>.'}]
        receipt, html, rendered = self.render()
        rate = " ".join(rendered.regions["proof-index-item-rate"])
        self.assertIn("Proof idea", rate)
        self.assertIn("Combine <untrusted> bounds.", rate)
        self.assertNotIn("<untrusted>", html)
        bound = " ".join(rendered.regions["proof-index-item-bound"])
        self.assertIn("Apply the estimate to", bound)
        self.assertIn('proof-idea">Apply the estimate to <span class="proof-formula"><math>', html)
        self.assertIn("Prerequisites (0)", bound)
        self.assertIn("No prerequisite use is recorded", bound)
        self.assertIn('[data-theme="dark"]{--proof-reading-text:', html)
        self.assertEqual(receipt["graph_preservation"]["status"], "pass")

    def test_compact_prerequisites_keep_roles_parallel_uses_and_searchable_downstream(self):
        self.data['items'].append({'id': 'condition', 'kind': 'assumption', 'label': 'Assumption 3',
                                   'statement_html': 'The local condition holds.'})
        self.data['uses'].append({'id': 'use-condition', 'from': 'condition', 'to': 'rate',
                                  'type': 'dependency', 'reason': 'Retain the additional local condition.',
                                  'regime': 'Only for positive indices'})
        for use in self.data['uses']:
            use['group'] = {'id': 'shared-legacy-group', 'kind': 'joint'}
        for mode in ('dag', 'index'):
            self.data['graph_mode'] = mode
            _, html, rendered = self.render()
            panel = re.search(r'<article[^>]*id="proof-index-item-rate"[^>]*>([\s\S]*?)</article>', html).group(1)
            self.assertLess(panel.index('Source comparison'), panel.index('Prerequisites (3)'))
            self.assertLess(panel.index('Hypotheses and setup'), panel.index('Results and other inputs used'))
            self.assertIn('Assumed', panel)
            self.assertEqual(panel.count('Joint inputs 1'), 3)
            for use in self.data['uses']:
                self.assertEqual(panel.count(f'data-proof-relation-use="{use["id"]}"'), 1)
                self.assertIn(f'data-reader-open="use:{use["id"]}"', panel)
                self.assertIn(use['reason'], panel)
            self.assertIn('Only for positive indices', panel)
            outgoing = re.search(r'<details[^>]*data-reader-search-key="item:bound:outgoing"[^>]*>', html).group()
            self.assertNotIn(' open', outgoing)
            self.assertIn('"key":"item:bound:outgoing"', html)
            self.assertRegex(html, r'"key":"item:bound:outgoing"[^\n]*?"label":"Used by"')
            self.assertEqual(rendered.records['uses'], self.data['uses'])

    def test_search_text_selects_one_math_representation_and_preserves_routes(self):
        symbol = ('<math><semantics><mi>G</mi>'
                  '<annotation encoding="application/x-tex">G</annotation></semantics></math>')
        fraction_tex = r'\frac{\sqrt{x}}{2}'
        matrix_tex = r'\begin{matrix}a & b\\c<d\end{matrix}'
        literal = '<math><mi>LITERAL_MATH</mi></math><script>LITERAL_SCRIPT</script>'
        cases = (
            ('symbol', symbol, 'G'),
            ('display', '<math display="block"><semantics><mfrac><msqrt><mi>x</mi>'
             '</msqrt><mn>2</mn></mfrac><annotation encoding="application/x-tex">'
             + escape(fraction_tex) + '</annotation></semantics></math>', fraction_tex),
            ('first_nonempty', '<math aria-label="IGNORE_ARIA"><semantics><mi>κ</mi>'
             '<annotation encoding="application/x-tex"> </annotation>'
             '<annotation encoding="text/plain">IGNORE_ANNOTATION</annotation>'
             '<annotation encoding="application/x-tex">\\kappa</annotation>'
             '<annotation encoding="application/x-tex">IGNORE_LATER_TEX</annotation>'
             '</semantics></math>', r'\kappa'),
            ('empty_annotation_aria', '<math aria-label="LaTeX: \\alpha &amp;amp; z">'
             '<semantics><mi>IGNORE_PRESENTATION</mi><annotation encoding="application/x-tex">'
             ' </annotation></semantics></math>', r'\alpha &amp; z'),
            ('absent_annotation_aria', '<math aria-label="LaTeX: \\beta"><mi>β</mi></math>', r'\beta'),
            ('custom_aria', '<math aria-label="Geometry: x &amp; y"><mi>IGNORE_ARIA_LEAF</mi></math>',
             'Geometry: x & y'),
            ('presentation', '<math><semantics><mfrac><mi>a</mi><mi>b</mi></mfrac>'
             '<mrow><mi>IGNORE_SECOND_BRANCH</mi></mrow>'
             '<annotation encoding="application/x-tex"> </annotation>'
             '<annotation encoding="text/plain">IGNORE_FALLBACK_ANNOTATION</annotation>'
             '<annotation-xml encoding="application/xml"><mi>IGNORE_ANNOTATION_XML</mi>'
             '</annotation-xml></semantics></math>', 'ab'),
            ('plain_presentation', '<math><mi>p</mi><mo>+</mo><mi>q</mi></math>', 'p+q'),
            ('empty_math', '<math><semantics><mrow></mrow>'
             '<annotation encoding="application/x-tex"> </annotation></semantics></math>', ''),
            ('repeated', symbol + ' and ' + symbol, 'G and G'),
            ('blocks', '<h5>Heading</h5><p>Body</p><div>Block</div><ul><li>First</li>'
             '<li>Second</li></ul><table><tr><td>CellA</td><td>CellB</td></tr>'
             '<tr><td>CellC</td></tr></table>Line<br>Break',
             'Heading Body Block First Second CellA CellB CellC Line Break'),
            ('inline', 'un<span>broken</span><em>word</em>', 'unbrokenword'),
            ('qualifications', '<span class="proof-use-type">Proof argument</span>'
             '<span class="proof-regime">Only in regime: fixed sample</span>'
             '<span class="proof-group">Joint inputs</span>',
             'Proof argument Only in regime: fixed sample Joint inputs'),
            ('entities', '&amp; &lt; &#60; &#x3e; &amp;lt; &nbsp;', '& < < > &lt;'),
            ('tex_entities', '<math><semantics><mi>IGNORE_MATRIX_LEAF</mi>'
             '<annotation encoding="application/x-tex">' + escape(matrix_tex)
             + '</annotation></semantics></math>', matrix_tex),
            ('literal_markup', escape(literal), literal),
            ('noncontent', 'Before<!--IGNORE_COMMENT--><script>IGNORE_SCRIPT</script>'
             '<style>IGNORE_STYLE</style>After', 'BeforeAfter'),
            ('unsupported', '<span class="math-fallback"><span class="math-fallback-label">'
             'LaTeX (not rendered): </span><code>\\unknownMacro{x}</code></span>',
             r'LaTeX (not rendered): \unknownMacro{x}'),
        )
        markup = ''.join(f'<div>BEGIN_{name}:{body}:END_{name}</div>' for name, body, _ in cases)
        excerpt = r'SOURCE <math><mi>SOURCE_LITERAL</mi></math> </script> &amp; \unknownMacro{x}'
        self.data['items'][0]['statement_html'] = markup
        self.data['items'][0]['source_passages'][0]['source_excerpt'] = excerpt
        self.data['details'] = [{'id': 'search-detail', 'owner': 'bound', 'kind': 'claim',
                                 'label': 'Intermediate claim', 'statement_html': markup,
                                 'source_passages': [{'source_display': 'detail.tex:4',
                                                      'source_excerpt': excerpt}]}]
        self.data['uses'][0]['reason_html'] = markup
        expected_metadata = []
        rows = (
            (self.data['items'][0], 'item:bound', 'Lemma 1', (
                'item:bound:source:0', 'item:bound:source:1', 'use:use-moment:source:0',
                'use:use-tail:source:0', 'detail:search-detail:source:0', 'item:bound:statement',
                'item:bound:logic', 'item:bound:outgoing', 'item:bound:sources', 'detail:search-detail')),
            (self.data['items'][1], 'item:rate', 'Theorem 2', (
                'use:use-moment:source:0', 'use:use-tail:source:0', 'item:rate:statement',
                'item:rate:logic', 'item:rate:outgoing', 'item:rate:sources')),
            (self.data['uses'][0], 'use:use-moment', 'Lemma 1 applied to Theorem 2', (
                'use:use-moment:source:0', 'use:use-moment:logic', 'use:use-moment:sources')),
            (self.data['uses'][1], 'use:use-tail', 'Lemma 1 applied to Theorem 2', (
                'use:use-tail:source:0', 'use:use-tail:logic', 'use:use-tail:sources')),
        )
        for row, detail, owner, keys in rows:
            for key in (*keys, detail):
                label = (row.get('label', owner) if key == detail else
                         'Source passages and locators' if ':source:' in key or key.endswith(':sources') else
                         'Used by' if key.endswith(':outgoing') else
                         'Proof idea and contributions' if key.endswith(':logic') else
                         'Intermediate claim' if key == 'detail:search-detail' else row.get('label', owner))
                aliases = [row['id'], *([] if key == detail else [key]), *row.get('aliases', [])]
                expected_metadata.append(dict(key=key, aliases=aliases, label=label, detail=detail,
                                              section=None, owner=owner))
        by_mode = {}
        for mode in ('dag', 'index'):
            with self.subTest(mode=mode):
                self.data['graph_mode'] = mode
                snapshot = deepcopy(self.data)
                receipt, html, rendered = self.render()
                entries = json.loads(re.search(r'<script id="proof-reader-search"[^>]*>([\s\S]*?)</script>',
                                              html).group(1))
                self.assertEqual([{key: value for key, value in entry.items() if key != 'text'}
                                  for entry in entries], expected_metadata)
                for field in ('items', 'uses', 'details', 'detail_uses', 'build_context'):
                    self.assertEqual(rendered.records[field], snapshot[field])
                self.assertEqual(receipt['graph_preservation']['status'], 'pass')
                self.assertEqual(sorted(rendered.index_uses), self.expected_uses())
                self.assertEqual(sorted(rendered.uses), self.expected_uses() if mode == 'dag' else [])
                for key in ('item:bound:statement', 'detail:search-detail', 'use:use-moment:logic',
                            'item:bound', 'use:use-moment'):
                    entry = next(entry for entry in entries if entry['key'] == key)
                    for name, _, expected in cases:
                        with self.subTest(mode=mode, destination=key, case=name):
                            matches = re.findall(fr'BEGIN_{name}:([\s\S]*?):END_{name}', entry['text'])
                            self.assertEqual(len(matches), 3 if key == 'item:bound' else 1)
                            self.assertEqual([' '.join(match.split()) for match in matches],
                                             [expected] * len(matches))
                    # Original commands remain searchable; rendered glyph-only recall is intentionally different.
                    self.assertIn(r'\kappa', entry['text'])
                    self.assertNotIn('κ', entry['text'])
                for key in ('item:bound:source:0', 'detail:search-detail:source:0'):
                    self.assertTrue(any(entry['key'] == key and excerpt in entry['text'] for entry in entries))
                    self.assertIn(f'data-reader-search-key="{key}"', html)
                for key in ('item:bound:outgoing', 'detail:search-detail', 'use:use-moment:logic'):
                    self.assertIn(f'data-reader-search-key="{key}"', html)
                for fragment in (symbol, escape(literal), escape(excerpt)):
                    self.assertIn(fragment, html)
                self.assertNotIn('</script> &amp;', html)
                by_mode[mode] = entries
        self.assertEqual(by_mode['dag'], by_mode['index'])

    def test_cycle_and_self_reference_have_complete_index_representation(self):
        self.data["graph_mode"] = "index"
        self.data["uses"].extend([
            {"id": "use-reverse", "from": "rate", "to": "bound", "type": "dependency", "reason": "A recorded reverse use."},
            {"id": "use-self", "from": "rate", "to": "rate", "type": "dependency", "reason": "An unresolved self reference."},
        ])
        receipt, html, rendered = self.render()
        self.assertEqual(rendered.nodes, [])
        self.assertEqual(rendered.uses, [])
        self.assertEqual(sorted(rendered.index_items), ["bound", "rate"])
        self.assertEqual(sorted(rendered.index_uses), self.expected_uses())
        self.assertEqual(rendered.records["uses"], self.data["uses"])
        self.assertEqual(receipt["graph_mode"], "index")
        self.assertEqual(receipt["geometry"]["status"], "not_applicable")
        self.assertEqual(receipt["graph_preservation"]["rendered_uses"], 4)
        self.assertIn("This overview explains the written argument; it does not verify the proofs", html)
        self.assertIn("Cyclic mappings alone do not establish a circular proof", html)

    def test_invalid_candidate_preserves_last_successful_artifact(self):
        _, html, _ = self.render()
        self.data["uses"][1]["id"] = self.data["uses"][0]["id"]
        failure = self.render(expect_success=False)
        self.assertIn("unique", failure["error"])
        self.assertEqual(self.output.read_text(encoding="utf-8"), html)

    def test_passages_cannot_terminate_the_embedded_record_script(self):
        attack = '</script><img src="RECORD_ATTACK" onerror="alert(1)">'
        self.data["items"][0]["source_passages"][0]["source_excerpt"] = attack
        _, html, rendered = self.render()
        self.assertNotIn('<img src="RECORD_ATTACK"', html)
        self.assertEqual(rendered.records["items"][0]["source_passages"][0]["source_excerpt"], attack)
        self.assertIn(attack, " ".join(rendered.regions["proof-detail-bound"]))

    def test_reader_sees_synopsis_and_actionable_locator_notes_without_full_digest(self):
        digest = "abcdef0123456789" * 4
        self.data["build_context"]["source_revision"] = digest
        self.data["build_context"]["source_status"] = "historical_changed"
        self.data["items"][0]["source_passages"][1]["verification"] = {
            "status": "unverified", "method": "entered_locator",
            "note": "The entered label has not been matched; compare the source passage.",
        }
        _, html, rendered = self.render()
        visible_prefix = html.split('<script id="proof-overview-records"')[0]
        self.assertNotIn(digest, visible_prefix)
        self.assertNotIn('title="Captured revision ', visible_prefix)
        self.assertIn("manuscript files have changed", visible_prefix)
        self.assertIn("earlier captured version", visible_prefix)
        for region in ("proof-detail-bound", "proof-index-item-bound"):
            text = " ".join(rendered.regions[region])
            self.assertIn("Statement synopsis", text)
            self.assertIn("Source location is not fully verified", text)
            self.assertIn("compare the source passage", text)
        self.assertEqual(rendered.records["build_context"]["source_revision"], digest)

    def test_repeated_build_uses_identical_prepared_snapshot(self):
        first, original, _ = self.render()
        second, repeated, _ = self.render()
        self.assertEqual(original, repeated)
        self.assertEqual(first["artifact_sha256"], second["artifact_sha256"])
        self.assertEqual(first["input_sha256"], second["input_sha256"])

    def test_pdf_extraction_notice_follows_source_type_in_item_and_use_panels(self):
        for row in (self.data["items"][0], self.data["uses"][0]):
            row["source_passages"][0].update({
                "source_media_type": "application/pdf", "source_display": "PDF p. 2",
                "verification": {"status": "checked", "method": "pdf_page_bounds"},
            })
        self.data["uses"][1]["source_passages"][0]["source_media_type"] = "text/x-tex"
        _, _, rendered = self.render()
        note = "Approximate text extracted from the PDF"
        for region in ("proof-detail-bound", "proof-index-item-bound",
                       "proof-use-use-moment", "proof-index-use-use-moment"):
            text = " ".join(rendered.regions[region])
            self.assertIn(note, text, region)
            self.assertIn("PDF p. 2", text, region)
            self.assertNotIn("Locator checked", text, region)
            self.assertIn("Check the original page for formulas and layout", text, region)
        for collection, index in (("items", 0), ("uses", 0)):
            self.assertEqual(rendered.records[collection][index]["source_passages"][0]["verification"],
                             {"status": "checked", "method": "pdf_page_bounds"})
        for region in ("proof-use-use-tail", "proof-index-use-use-tail"):
            self.assertNotIn(note, " ".join(rendered.regions[region]), region)

    def test_scan_metrics_remain_embedded_without_reader_accounting(self):
        self.data["build_context"]["citation_candidates"] = {
            "pairs": 2, "attributed": 3, "unattributed": 7,
            "not_mechanically_matchable": 4, "missing_uses": 0,
            "unsupported_uses": 1, "unmatched_labels": 5,
        }
        receipt, html, rendered = self.render()
        visible_prefix = html.split('<script id="proof-overview-records"')[0]
        for expected in ("2 cited result pairs", "3 attributed and 7 unattributed matched references",
                         "4 records without unique citation labels", "0 missing-use candidates",
                         "1 recorded uses not corroborated by this scan"):
            self.assertNotIn(expected, visible_prefix)
        self.assertIn("have not yet been compared with the source", visible_prefix)
        self.assertEqual(rendered.records["build_context"]["citation_candidates"],
                         self.data["build_context"]["citation_candidates"])
        self.assertEqual(receipt["input_sha256"], hashlib.sha256(self.input.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
