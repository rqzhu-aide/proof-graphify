from __future__ import annotations

import copy
import html
import importlib.util
import unittest
from collections import deque
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("proofcheck_graph", ROOT / "scripts/proofcheck_graph.py")
graph_view = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_view)


def result(key, kind="theorem", status="established", **values):
    return {"id": key, "unit_id": key + "-unit", "kind": kind, "claim": "For each fixed point x, P(x) holds.",
            "title": "Theorem: exact title " + key, "reader_description": "For each fixed point",
            "location": "paper.tex, lines 12 to 15", "conditions": [{"pointer": "/hypotheses/1", "value": "x is fixed"}],
            "judgments": {"argument_status": "verified", "statement_status": status}, **values}


def node(r):
    return {"id": r["id"], "kind": r["kind"], "claim": r["claim"], "label": r["title"],
            "status": r["judgments"]["statement_status"], "detail_id": r["id"], "source_ids": []}


def aux(key, kind, status="given", **values):
    return {"id": key, "kind": kind, "status": status, "label": key, "claim": "Exact " + key,
            "detail_id": key, "source_ids": [], **values}


class Tags(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.tags = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class GraphViewTests(unittest.TestCase):
    def test_use_color_depends_on_exact_application_not_lemma_verdict(self):
        source = aux("lemma", "lemma", "established")
        cases = [
            ({"use_id": "u", "status": "verified", "applicability_status": "verified"}, "checked", "checked use"),
            ({"use_id": "u", "status": "verified", "applicability_status": "passed"}, "checked", "checked use"),
            ({"use_id": "u", "status": "verified", "applicability_status": "failed"}, "broken", "invalid use"),
            ({"use_id": "u", "status": "verified", "applicability_status": "incorrect"}, "broken", "invalid use"),
            ({"use_id": "u", "status": "gap", "applicability_status": "verified"}, "broken", "gap"),
            ({"use_id": "u", "status": "conditionally_verified", "applicability_status": "verified"}, "pending", "conditional"),
            ({"use_id": "u", "status": "verified"}, "pending", "not checked"),
            ({"use_id": "u"}, "pending", "not checked"),
            ({"use_id": "u", "status": "unrecognized", "applicability_status": "verified"}, "pending", "unrecognized"),
            ({"kind": "refutation"}, "refutation", "refutes"),
        ]
        for edge, tone, label in cases:
            with self.subTest(edge=edge):
                p = graph_view.edge_presentation(edge, source)
                self.assertEqual((tone, label), (p["tone"], p["short_label"]))
        assumption = aux("given", "assumption")
        self.assertEqual("given", graph_view.edge_presentation({}, assumption)["tone"])
        self.assertEqual("pending", graph_view.edge_presentation({"use_id": "unreviewed"}, assumption)["tone"])

    def test_node_type_survives_verdict_and_variants_do_not_merge(self):
        original = result("main", display_label="Theorem 1.2", printed_label=None)
        base = {"nodes": [node(original), aux("restricted", "restricted statement", "verified", result_id="main", conditions=["The index set is finite"]),
                           aux("proof", "argument", "gap"), aux("supplement", "argument", "verified")],
                "edges": [{"from": "proof", "to": "main", "status": "gap"},
                          {"from": "supplement", "to": "restricted", "status": "verified"}]}
        copied = copy.deepcopy(base)
        prepared = graph_view.prepare_graph(base, [original])
        self.assertEqual(base, copied)
        changed = copy.deepcopy(base)
        changed["nodes"][0]["status"] = "refuted"
        other = graph_view.prepare_graph(changed, [original])
        self.assertEqual(prepared["nodes"][0]["display"]["accent"], other["nodes"][0]["display"]["accent"])
        self.assertEqual(prepared["nodes"][0]["display"]["accent"], prepared["nodes"][1]["display"]["accent"])
        self.assertEqual("Thm 1.2", prepared["nodes"][0]["display"]["identity"])
        self.assertTrue(prepared["nodes"][0]["display"]["full_title"].startswith("Thm 1.2 · "))
        self.assertEqual(original["reader_description"], prepared["nodes"][0]["display"]["topic"])
        self.assertEqual("Restricted form of Thm 1.2", prepared["nodes"][1]["display"]["identity"])
        self.assertTrue(prepared["nodes"][1]["display"]["variant"])
        self.assertEqual([*original["conditions"], "The index set is finite"], prepared["nodes"][1]["display"]["conditions"])
        self.assertEqual(["broken", "checked"], [e["presentation"]["tone"] for e in prepared["edges"]])
        self.assertEqual("Proof of Thm 1.2", prepared["nodes"][2]["display"]["identity"])
        self.assertEqual("Supplemental proof of Thm 1.2", prepared["nodes"][3]["display"]["identity"])
        self.assertTrue(prepared["nodes"][1]["display"]["full_title"].startswith("Restricted form of Thm 1.2 · "))
        self.assertTrue(prepared["nodes"][3]["display"]["full_title"].startswith("Supplemental proof of Thm 1.2 · "))
        self.assertEqual([n["id"] for n in base["nodes"]], [n["id"] for n in prepared["nodes"]])
        self.assertEqual([(e["from"], e["to"]) for e in base["edges"]], [(e["from"], e["to"]) for e in prepared["edges"]])

    def test_large_neighborhood_pages_retain_every_input_path_and_edge(self):
        results = [result("result" + str(i)) for i in range(15)]
        nodes = [node(r) for r in results]
        nodes += [aux("written", "argument", "gap"), aux("alternate", "argument", "verified"), aux("evidence", "counterexample", "refutation_evidence")]
        nodes += [aux("given" + str(i), "assumption") for i in range(24)]
        edges = [{"from": "written", "to": "result0", "status": "gap"}, {"from": "alternate", "to": "result0", "status": "verified"},
                 {"from": "evidence", "to": "result0", "kind": "refutation"}]
        edges += [{"from": "given" + str(i), "to": "written" if i < 15 else "alternate"} for i in range(24)]
        edges += [{"from": "result1", "to": "written", "use_id": "u", "status": "verified", "applicability_status": "verified"}]
        graph = graph_view.prepare_graph({"nodes": nodes, "edges": edges}, results)
        pages = graph["views"]["result0"]
        self.assertGreater(len(pages), 1)
        self.assertTrue({"result0", "written", "result1", "evidence"} <= set(pages[0]["node_ids"]))
        covered_nodes, covered_edges = set(), set()
        for page in pages:
            self.assertLessEqual(len(page["node_ids"]), 12)
            self.assertIn("result0", page["node_ids"])
            selected = set(page["node_ids"])
            adjacency = {key: [] for key in selected}
            for index in page["edge_indices"]:
                edge = graph["edges"][index]
                adjacency[edge["from"]].append(edge["to"])
                adjacency[edge["to"]].append(edge["from"])
            reached, queue = {"result0"}, deque(["result0"])
            while queue:
                for neighbor in adjacency[queue.popleft()]:
                    if neighbor not in reached:
                        reached.add(neighbor)
                        queue.append(neighbor)
            self.assertEqual(selected, reached)
            self.assertIn("connections omitted", page["note"])
            covered_nodes.update(selected)
            covered_edges.update(page["edge_indices"])
        self.assertEqual(set(range(len(edges))), covered_edges)
        self.assertTrue({"given" + str(i) for i in range(24)} <= covered_nodes)
        self.assertNotIn("result14", covered_nodes)
        self.assertNotIn("result14", pages[0]["positions"])
        # A declared target can be a disconnected result; it is not called main.
        graph = graph_view.prepare_graph({"nodes": nodes, "edges": edges}, results, ["result14-unit"])
        self.assertEqual("result14", graph["initial_focus"])
        self.assertEqual(["result14"], graph_view.initial_page(graph)["node_ids"])

    def test_static_and_interactive_views_use_shared_display_and_geometry(self):
        r = result("target", display_label="Theorem 2", reader_description="Uniform bound")
        graph = graph_view.prepare_graph({"nodes": [node(r), aux("proof", "argument", "gap"), aux("input", "definition")],
                                           "edges": [{"from": "proof", "to": "target", "status": "gap"}, {"from": "input", "to": "proof"}]}, [r])
        page = graph_view.initial_page(graph)
        value = graph_view.render_graph(graph)
        tags = Tags(value).tags
        visible_edges = [attrs for tag, attrs in tags if tag == "path" and attrs.get("class", "").startswith("graph-edge ")]
        markers = {attrs["id"] for tag, attrs in tags if tag == "marker"}
        self.assertEqual(len(page["edge_indices"]), len(visible_edges))
        for attrs, route in zip(visible_edges, page["routes"]):
            p = graph["edges"][route["index"]]["presentation"]
            self.assertEqual(route["d"], attrs["d"])
            self.assertIn(p["marker"], markers)
            self.assertIn(p["color"], attrs["style"])
            self.assertEqual("url(#" + p["marker"] + ")", attrs["marker-end"])
        for key in page["node_ids"]:
            n = next(n for n in graph["nodes"] if n["id"] == key)
            self.assertIn('href="#' + key + '"', value)
            self.assertIn(html.escape(n["display"]["identity"]), value)
        self.assertIn("page.routes.forEach", graph_view.SCRIPT)
        self.assertIn("page.node_ids.forEach", graph_view.SCRIPT)
        self.assertIn("edge.presentation", graph_view.SCRIPT)
        self.assertNotIn("function tone", graph_view.SCRIPT)
        raw = {"nodes": [node(r)], "edges": []}
        self.assertIn('href="#target"', graph_view.render_graph(raw))
        self.assertNotIn("display", raw["nodes"][0])

    def test_preview_uses_audited_math_and_preserves_distinct_conclusions(self):
        a = result("a", display_label="Theorem 1.2", graph_reading_claim=r"For each fixed $x$, $P(x)$ holds.", manuscript_title="Rates <source>")
        b = result("b", display_label="Theorem 1.2", reader_description="Uniformly over x", claim="For all x simultaneously, P(x) holds.")
        c = result("c", kind="conclusion", manuscript_label="thm:main", reader_description=None)
        graph = graph_view.prepare_graph({"nodes": [node(a), node(b), node(c)], "edges": []}, [a, b, c])
        seen = []
        def rich(value):
            seen.append(value)
            return '<span class="typeset">' + html.escape(str(value)) + '</span>'
        value = graph_view.render_previews(graph, rich)
        self.assertIn(a["graph_reading_claim"], seen)
        self.assertIn(b["claim"], seen)
        self.assertIn("Typeset from locked manuscript excerpt", value)
        self.assertNotIn("<source>", value)
        self.assertNotEqual(graph["nodes"][0]["display"]["topic_lines"], graph["nodes"][1]["display"]["topic_lines"])
        self.assertEqual("Conclusion", graph["nodes"][2]["display"]["identity"])
        self.assertNotIn("thm:main", graph_view.render_graph(graph))
        self.assertIn("x is fixed", seen)
        self.assertIn("Written argument: verified. Statement: established.", value)
        self.assertIn('role="dialog"', value)
        self.assertIn("event.key==='Escape'", graph_view.SCRIPT)
        self.assertIn("event.pointerType==='touch'", graph_view.SCRIPT)

    def test_math_claim_card_uses_source_locator_and_keeps_full_preview(self):
        claim = r"Assume $H_{\ell,n}$ is uniformly bounded for every $n$."
        raw = {"nodes": [aux("given", "assumption", claim=claim, location="paper.tex, lines 20 to 25")], "edges": []}
        graph = graph_view.prepare_graph(raw, [])
        display = graph["nodes"][0]["display"]
        self.assertEqual("paper.tex, lines 20 to 25", display["topic"])
        self.assertNotIn("H_{", " ".join(display["topic_lines"]))
        self.assertIn(html.escape(claim), graph_view.render_previews(graph, lambda value: html.escape(str(value))))
        self.assertIn("max-height:560px", graph_view.CSS)
        self.assertIn("scrollTop=0", graph_view.SCRIPT)

    def test_colliding_conclusions_use_exact_locations_or_named_audit_splits(self):
        a = result("a", display_label="Theorem 3.1", manuscript_title="Covariance", reader_description="Matched covariance", location="paper.tex, lines 20 to 22")
        b = result("b", display_label="Theorem 3.1", manuscript_title="Covariance", reader_description="Matched covariance", location="paper.tex, lines 30 to 32")
        raw = {"nodes": [node(a), node(b), aux("proof-a", "argument", "verified"), aux("proof-b", "argument", "verified")],
               "edges": [{"from": "proof-a", "to": "a", "status": "verified"}, {"from": "proof-b", "to": "b", "status": "verified"}]}
        graph = graph_view.prepare_graph(raw, [a, b])
        displays = {n["id"]: n["display"] for n in graph["nodes"]}
        self.assertEqual(a["location"], displays["a"]["disambiguator"])
        self.assertEqual(a["location"], displays["proof-a"]["disambiguator"])
        self.assertIn(b["location"], displays["b"]["topic"])
        self.assertNotIn("paper.tex", displays["a"]["preview_heading"])
        self.assertEqual("Thm 3.1 · Matched covariance", displays["a"]["preview_heading"])
        b["location"] = a["location"]
        graph = graph_view.prepare_graph(raw, [a, b])
        displays = {n["id"]: n["display"] for n in graph["nodes"]}
        self.assertEqual("Audit conclusion 1 of 2", displays["a"]["disambiguator"])
        self.assertEqual("Audit conclusion 2 of 2", displays["proof-b"]["disambiguator"])
        self.assertIn("Audit conclusion 1 of 2", graph_view.render_graph(graph))
        self.assertIn("Audit conclusion 2 of 2", displays["b"]["preview_heading"])
        self.assertEqual(["Matched covariance"], displays["a"]["topic_lines"])
        self.assertEqual(["Audit conclusion 1 of 2"], displays["a"]["disambiguator_lines"])

    def test_empty_graph_has_honest_static_fallback(self):
        graph = graph_view.prepare_graph({"nodes": [], "edges": []}, [])
        self.assertIn("No proof graph nodes", graph_view.render_graph(graph))
        self.assertIn("No proof graph nodes", graph_view.page_note(graph))


if __name__ == "__main__":
    unittest.main()
