"""Generated layout contract, without recreating the removed width/observer loop.

Actual responsive geometry and exports remain browser acceptance work.
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


class Structure(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes, self.stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, pairs):
        node = {"tag": tag, "attrs": dict(pairs), "parent": self.stack[-1] if self.stack else None}
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()

    def by_class(self, name):
        return [node for node in self.nodes if name in node["attrs"].get("class", "").split()]


@unittest.skipUnless(NODE, "A shared Node installation is required.")
class ReaderLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        base = Path(cls.temporary.name)
        data = {
            "schema_version": 3, "graph_mode": "dag", "title": "Reader layout fixture",
            "details": [], "detail_uses": [], "scope": "Synthetic layout fixture; no mathematical assessment.",
            "source": {"title": "Layout fixture"}, "main_items": ["result"],
            "items": [
                {"id": "assumption", "kind": "assumption", "label": "Assumption 1", "caption": "Condition", "statement_html": "A condition holds."},
                {"id": "result", "kind": "theorem", "label": "Theorem 2", "caption": "Conclusion", "statement_html": "A conclusion follows."},
            ],
            "uses": [{"id": "condition-use", "from": "assumption", "to": "result", "type": "dependency", "reason": "The conclusion uses the condition."}],
        }
        cls.pages = {}
        for mode in ("dag", "index"):
            data["graph_mode"] = mode
            prepared, output = base / "prepared.json", base / "overview.html"
            prepared.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run([NODE, str(SKILL / "scripts/render.mjs"), str(prepared), str(output)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            if result.returncode:
                raise AssertionError(result.stderr)
            html = output.read_text(encoding="utf-8")
            cls.pages[mode] = (html, Structure(html))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_graph_and_scientific_content_have_explicit_sibling_slots(self):
        _, page = self.pages["dag"]
        shell, = page.by_class("container")
        children = [node for node in page.nodes if node["parent"] is shell]
        selectors = ["header", "proof-reader-before", "diagram-container", "reader-rail", "proof-selection-host", "proof-reader-after"]
        positions = []
        for selector in selectors:
            matches = [i for i, node in enumerate(children) if selector in node["attrs"].get("class", "").split() or node["attrs"].get("id") == selector]
            self.assertEqual(len(matches), 1, selector)
            positions.append(matches[0])
        self.assertEqual(positions, sorted(positions))

    def test_results_have_one_entry_per_node_and_real_fallback_destinations(self):
        _, page = self.pages["dag"]
        navigation, = page.by_class("proof-results")
        links = page.by_class("proof-result-link")
        self.assertEqual([node["attrs"]["data-reader-node"] for node in links], ["result", "assumption"])
        ids = [node["attrs"]["id"] for node in page.nodes if "id" in node["attrs"]]
        self.assertEqual(len(ids), len(set(ids)), "Generated DOM IDs must be unique.")
        for link in links:
            self.assertEqual(link["tag"], "a")
            destination = link["attrs"]["href"].removeprefix("#")
            target, = [node for node in page.nodes if node["attrs"].get("id") == destination]
            self.assertEqual(target["tag"], "article")
            ancestor = target
            while ancestor:
                self.assertNotEqual(ancestor["tag"], "template", "A fallback link must reach real content.")
                if ancestor["tag"] == "details":
                    self.assertIn("open", ancestor["attrs"], "Fallback articles must be visible before JavaScript starts.")
                ancestor = ancestor["parent"]
        self.assertIsNotNone(navigation)

    def test_no_competing_layout_or_outline_runs_and_index_has_no_graph_runtime(self):
        for html, _ in self.pages.values():
            self.assertNotIn("Archify.readerLayout = (function", html)
            self.assertNotIn("Archify.outline = (function", html)
            self.assertNotIn('class="proof-main-navigation"', html)
        graph, _ = self.pages["dag"]
        self.assertIn("Archify.waitForStableLayout =", graph)
        index, page = self.pages["index"]
        self.assertFalse(page.by_class("diagram-container"))
        self.assertFalse(page.by_class("proof-results"))
        self.assertNotIn("var Archify = {}", index)
        ids = {node["attrs"].get("id") for node in page.nodes}
        self.assertIn("proof-index-theme", ids)
        self.assertTrue({"btn-export", "btn-present", "btn-preset", "btn-finder", "btn-map"}.isdisjoint(ids))


if __name__ == "__main__":
    unittest.main()
