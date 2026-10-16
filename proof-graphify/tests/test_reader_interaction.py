"""Exercise the emitted reader adapter in a deliberately small DOM simulation.

This is not browser layout, pointer hit testing, or a visual review. The real
generated adapter runs against a focus stub; every emitted script is also parsed.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class ReaderDocument(HTMLParser):
    """Retain document structure, inert templates, and executable script text."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.root = {"tag": "document", "attrs": {}, "children": [], "text": ""}
        self.stack = [self.root]
        self.scripts = []
        self.template = None
        self.feed(html)

    def handle_starttag(self, tag, pairs):
        if self.template is not None:
            self.template["innerHTML"] += self.get_starttag_text()
            return
        element = {"tag": tag, "attrs": dict(pairs), "children": [], "text": ""}
        self.stack[-1]["children"].append(element)
        if tag == "template":
            element["innerHTML"] = ""
            self.template = element
        elif tag not in VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag, pairs):
        self.handle_starttag(tag, pairs)
        if self.template is None and tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.template is not None:
            if tag == "template":
                self.template = None
            else:
                self.template["innerHTML"] += f"</{tag}>"
            return
        if len(self.stack) > 1 and self.stack[-1]["tag"] == tag:
            element = self.stack.pop()
            if tag == "script" and element["attrs"].get("type", "") not in {"application/json", "application/ld+json"}:
                self.scripts.append(element["text"])

    def handle_data(self, data):
        if self.template is not None:
            self.template["innerHTML"] += data
        elif self.stack[-1]["tag"] != "style":
            self.stack[-1]["text"] += data

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


@unittest.skipUnless(NODE, "A shared Node installation is required.")
class ReaderInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name)
        dataset = {
            "schema_version": 3, "graph_mode": "dag", "title": "Shallow reader fixture",
            "details": [], "detail_uses": [],
            "scope": "Two synthetic statements; no mathematical assessment.",
            "source": {"title": "Reader fixture"}, "main_items": ["result"],
            "items": [
                {"id": "assumption", "kind": "assumption", "label": "Assumption 1", "caption": "Independent observations <literal> & finite variance",
                 "statement_html": "ASSUMPTION_TEXT: the observations are independent and have finite variance."},
                {"id": "result", "kind": "theorem", "label": "Theorem 2", "caption": "Variance identity",
                 "statement_html": "RESULT_TEXT: the variance of the average is the individual variance divided by the sample size.",
                 "source_passages": [{"role": "statement", "source_display": "main.tex:42",
                                      "source_excerpt": "SOURCE_QUOTE: the saved variance identity uses independent observations."}]},
                {"id": "moment", "kind": "assumption", "label": "Assumption 3", "caption": "Second moment",
                 "statement_html": "MOMENT_TEXT: the common second moment is finite."},
            ],
            "uses": [{"id": "independence-use", "from": "assumption", "to": "result", "type": "dependency",
                      "regime": "Fixed sample", "reason": "RELATION_TEXT: independence removes the covariance terms."}],
        }
        dataset["uses"].append({"id": "moment-use", "from": "moment", "to": "result", "type": "dependency",
                                "reason": "The variance identity uses the finite second moment."})
        prepared, output = cls.base / "prepared.json", cls.base / "overview.html"
        prepared.write_text(json.dumps(dataset), encoding="utf-8")
        rendered = subprocess.run([NODE, str(SKILL / "scripts/render.mjs"), str(prepared), str(output)],
                                  capture_output=True, text=True, encoding="utf-8")
        if rendered.returncode:
            raise AssertionError(rendered.stderr)
        parsed = ReaderDocument(output.read_text(encoding="utf-8"))
        cls.packet = cls.base / "reader-dom.json"
        cls.packet.write_text(json.dumps({"document": parsed.root, "scripts": parsed.scripts}), encoding="utf-8")
        dataset["graph_mode"] = "index"
        prepared.write_text(json.dumps(dataset), encoding="utf-8")
        rendered = subprocess.run([NODE, str(SKILL / "scripts/render.mjs"), str(prepared), str(output)],
                                  capture_output=True, text=True, encoding="utf-8")
        if rendered.returncode:
            raise AssertionError(rendered.stderr)
        parsed = ReaderDocument(output.read_text(encoding="utf-8"))
        cls.index_packet = cls.base / "index-dom.json"
        cls.index_packet.write_text(json.dumps({"document": parsed.root, "scripts": parsed.scripts}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_harness(self, mode):
        packet = self.index_packet if mode == "index" or mode.endswith("-index") else self.packet
        result = subprocess.run([NODE, str(SKILL / "tests/fixtures/reader-interaction.mjs"), str(packet), mode],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_every_generated_executable_script_compiles(self):
        self.assertGreater(self.run_harness("compile")["compiled_scripts"], 1)

    def test_shallow_graph_details_selection_navigation_and_close(self):
        result = self.run_harness("interact")
        self.assertTrue(result["details_outside_diagram"])
        self.assertEqual(result["checked_selections"], ["assumption", "result", "independence-use"])
        self.assertTrue(result["close_cleared_details"])
        self.assertTrue(result["controls_preserved_selection"])
        self.assertTrue(result["background_and_fit_cleared_details"])

    def test_audit_details_keep_their_product_context_after_relocation(self):
        self.assertTrue(self.run_harness("audit")["details_outside_diagram"])

    def test_graph_and_index_share_source_search_print_and_focus_restoration(self):
        for mode in ("interact", "index"):
            with self.subTest(mode=mode):
                result = self.run_harness(mode)
                self.assertTrue(result["source_search_exact_destination"])
                self.assertTrue(result["print_state_restored"])
                self.assertTrue(result["escape_restored_activator"])

    def test_optional_previews_use_escaped_templates_and_dismiss_for_selection_and_print(self):
        result = self.run_harness("preview")
        self.assertTrue(result["template_bytes_preserved"])
        self.assertTrue(result["pointer_and_keyboard_preview"])
        self.assertTrue(result["leave_selection_and_print_dismissal"])

    def test_initial_public_item_and_connection_fragments_reveal_saved_content(self):
        for mode in ("fragment", "fragment-use", "fragment-index", "fragment-use-index"):
            with self.subTest(mode=mode):
                result = self.run_harness(mode)
                self.assertTrue(result["public_fragment_resolved"])
                self.assertTrue(result["index_visible"])


if __name__ == "__main__":
    unittest.main()
