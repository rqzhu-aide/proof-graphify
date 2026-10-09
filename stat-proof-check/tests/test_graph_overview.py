"""Manuscript overview preserves exact evidence while reducing navigation detail."""
from __future__ import annotations

import copy
import html
import unittest

from test_graph_view import Tags, aux, graph_view, node, result


def part(unit, index=1, **values):
    return result(f"{unit}-{index}", unit_id=unit, conclusion_id=f"C{index}",
                  display_label=None, manuscript_title="Tail bound", **values)


def groups(results):
    grouped = {}
    for r in results:
        grouped.setdefault(r["unit_id"], []).append(r)
    return [{"id": "group-" + unit, "unit_id": unit, "result_ids": [r["id"] for r in rows],
             "kind": rows[0]["kind"], "manuscript_title": rows[0]["manuscript_title"],
             "location": "paper.tex, lines " + str(index * 20 + 1) + " to " + str(index * 20 + 10),
             "claim": "Complete theorem statement, including all of its conclusions: $P_1$ and $P_2$.",
             "assessment_summary": f"{len(rows)} parts; see recorded outcomes",
             "assessment_counts": {"parts": len(rows)}, "availability": "available"}
            for index, (unit, rows) in enumerate(grouped.items())]


def raw_graph(results):
    nodes = [node(r) for r in results]
    nodes += [aux("proof-" + r["id"], "argument", "valid") for r in results]
    edges = [{"from": "proof-" + r["id"], "to": r["id"], "status": "valid", "unit_id": r["unit_id"]} for r in results]
    return {"nodes": nodes, "edges": edges}


def use(graph, source, target, identity="U1", **values):
    edge = {"from": source["id"], "to": "proof-" + target["id"], "kind": "support",
            "unit_id": target["unit_id"], "use_id": identity, "dependency_id": source.get("unit_id", source["id"]),
            "dependency_conclusion_id": source.get("conclusion_id"), "status": "verified",
            "applicability_status": "verified", "needed_form": "Exact consumed form $P_1$", **values}
    graph["edges"].append(edge)
    return edge


class OverviewTests(unittest.TestCase):
    def prepare(self, raw, results, group_rows=None):
        exact = graph_view.prepare_graph(raw, results)
        return exact, graph_view.prepare_overview(exact, results, groups(results) if group_rows is None else group_rows)

    def test_many_parts_and_conditions_make_one_group_with_complete_statement(self):
        rows = [part("main", index) for index in range(1, 25)]
        raw = raw_graph(rows)
        for index in range(80):
            given = aux("given" + str(index), "condition")
            raw["nodes"].append(given)
            raw["edges"].append({"from": given["id"], "to": "proof-main-1"})
        before = copy.deepcopy(raw)
        exact, overview = self.prepare(raw, rows)
        self.assertEqual(before, raw)
        self.assertEqual(1, len(overview["nodes"]))
        self.assertEqual(0, len(overview["edges"]))
        self.assertEqual({r["id"]: "group-main" for r in rows}, overview["result_to_group"])
        self.assertIn("including all", overview["nodes"][0]["claim"])
        self.assertNotEqual(rows[0]["claim"], overview["nodes"][0]["claim"])
        self.assertEqual(["group-main"], overview["selection_ids"])
        self.assertIn("Tail bound", graph_view.render_graph(overview))
        self.assertNotIn("Given condition", graph_view.render_graph(overview))
        self.assertEqual(len(raw["nodes"]), len(exact["nodes"]))

    def test_equal_titles_never_join_distinct_source_groups_and_fallback_is_visible(self):
        rows = [part("first"), part("second")]
        group_rows = groups(rows)
        group_rows[1]["manuscript_title"] = None
        _, overview = self.prepare(raw_graph(rows), rows, group_rows)
        self.assertEqual(2, len(overview["nodes"]))
        value = graph_view.render_graph(overview)
        self.assertIn("Tail bound", value)
        self.assertIn("paper.tex", value)
        for n in overview["nodes"]:
            self.assertLessEqual(n["display"]["card_height"], 76)

    def test_repeated_use_retains_conclusions_and_routes_without_double_counting(self):
        rows = [part("source"), part("target", 1), part("target", 2)]
        raw = raw_graph(rows)
        use(raw, rows[0], rows[1])
        use(raw, rows[0], rows[2])
        exact, overview = self.prepare(raw, rows)
        edge = overview["edges"][0]
        self.assertEqual(1, edge["use_count"])
        self.assertEqual(2, len(edge["contributors"]))
        self.assertEqual({r["id"] for r in rows[1:]}, {c["target_result_id"] for c in edge["contributors"]})
        self.assertEqual([["target", "U1"]] * 2, [c["qualified_use"] for c in edge["contributors"]])
        for contributor in edge["contributors"]:
            self.assertEqual("U1", exact["edges"][contributor["exact_edge_index"]]["use_id"])

    def test_mixed_uses_have_correct_counts_without_inheriting_source_verdict(self):
        rows = [part("source", status="refuted"), part("target")]
        raw = raw_graph(rows)
        use(raw, rows[0], rows[1], "checked")
        use(raw, rows[0], rows[1], "pending", status="stale")
        use(raw, rows[0], rows[1], "broken", applicability_status="failed")
        exact, overview = self.prepare(raw, rows)
        edge = overview["edges"][0]
        self.assertEqual({"checked": 1, "pending": 1, "broken": 1}, edge["use_counts"])
        self.assertEqual("broken", edge["presentation"]["tone"])
        self.assertIn("broken", edge["presentation"]["meaning"])
        self.assertIn(edge["presentation"]["meaning"], graph_view.render_legend(overview))
        clean = copy.deepcopy(raw)
        clean["edges"] = clean["edges"][:-2]
        _, checked = self.prepare(clean, rows)
        self.assertEqual("checked", checked["edges"][0]["presentation"]["tone"])
        self.assertIn("Every contributing use is checked", checked["edges"][0]["presentation"]["meaning"])
        self.assertEqual("display_group", checked["nodes"][0]["status"])
        self.assertEqual(exact["nodes"][0]["status"], "refuted")

    def test_external_registry_identity_keeps_distinct_consumed_forms(self):
        rows = [part("left"), part("right")]
        raw = raw_graph(rows)
        for index, target in enumerate(rows):
            external = aux("external" + str(index), "external result", "established", claim="Source form " + str(index))
            raw["nodes"].append(external)
            use(raw, external, target, dependency_id="registered-external")
        exact, overview = self.prepare(raw, rows)
        stubs = [n for n in overview["nodes"] if n.get("overview_stub")]
        self.assertEqual(1, len(stubs))
        self.assertEqual(["external0", "external1"], stubs[0]["exact_node_ids"])
        contributors = [c for e in overview["edges"] for c in e["contributors"]]
        self.assertEqual({("left", "U1"), ("right", "U1")}, {tuple(c["qualified_use"]) for c in contributors})
        previews = graph_view.render_previews(overview, html.escape, exact_graph=exact)
        self.assertIn("Source form 0", previews)
        self.assertIn("Source form 1", previews)
        self.assertIn("not a complete result statement", previews)

    def test_unavailable_internal_and_selected_supplement_stay_explicit(self):
        rows = [part("source"), part("target")]
        raw = raw_graph(rows)
        for index, kind in enumerate(("internal result", "unavailable supplement")):
            missing = aux("missing" + str(index), kind, "not_checked")
            raw["nodes"].append(missing)
            use(raw, missing, rows[1], str(index), dependency_id="source", statement_support={"sha256": "old-hash"})
        _, overview = self.prepare(raw, rows)
        self.assertEqual({"internal result", "unavailable supplement"}, {n["kind"] for n in overview["nodes"] if n.get("overview_stub")})
        self.assertTrue(all(e["presentation"]["tone"] == "pending" for e in overview["edges"]))
        self.assertTrue(all("unavailable" in e["presentation"]["meaning"] for e in overview["edges"]))
        self.assertEqual(4, len(overview["nodes"]))

    def test_supplemental_and_written_routes_keep_separate_contributors(self):
        rows = [part("source"), part("target")]
        raw = raw_graph(rows)
        use(raw, rows[0], rows[1])
        raw["nodes"].extend([aux("restricted", "restricted statement", "verified", result_id=rows[1]["id"], conditions=["Finite index set"]), aux("alternate", "argument", "verified")])
        raw["edges"].append({"from": "alternate", "to": "restricted", "status": "verified"})
        alternate = use(raw, rows[0], rows[1])
        alternate["to"] = "alternate"
        exact, overview = self.prepare(raw, rows)
        edge = overview["edges"][0]
        self.assertEqual(1, edge["use_count"])
        self.assertEqual({"written", "supplemental"}, {c["route_kind"] for c in edge["contributors"]})
        preview = graph_view.render_previews(overview, html.escape, exact_graph=exact)
        self.assertIn("Supplemental", preview)
        self.assertIn("Finite index set", preview)
        self.assertIn("Exact restricted", preview)
        self.assertIn('href="#alternate"', preview)

    def test_grouping_cycle_and_local_use_add_no_circularity_judgment(self):
        rows = [part("left", 1), part("right", 1), part("left", 2), part("right", 2)]
        raw = raw_graph(rows)
        use(raw, rows[0], rows[1], "forward")
        use(raw, rows[1], rows[2], "back")
        use(raw, rows[0], rows[2], "local")
        _, overview = self.prepare(raw, rows)
        self.assertEqual(2, len(overview["edges"]))
        self.assertEqual(1, len(overview["local_uses"]))
        self.assertEqual({"checked"}, {e["presentation"]["tone"] for e in overview["edges"]})
        page = graph_view.initial_page(overview)
        self.assertEqual(2, len(page["positions"]))
        self.assertEqual(2, len(page["routes"]))
        self.assertNotIn("circular", page["note"])

    def test_disconnected_results_form_compact_grid_and_bounded_pages_cover_all(self):
        rows = [part("unit" + str(index)) for index in range(9)]
        _, overview = self.prepare(raw_graph(rows), rows)
        page = graph_view.initial_page(overview)
        self.assertEqual(9, len(page["node_ids"]))
        self.assertLess(page["height"], 500)
        self.assertEqual(3, len({xy[0] for xy in page["positions"].values()}))
        large = [part("large" + str(index)) for index in range(35)]
        raw = raw_graph(large)
        for source, target in zip(large, large[1:]):
            use(raw, source, target)
        _, overview = self.prepare(raw, large)
        pages = overview["views"][overview["initial_focus"]]
        self.assertGreater(len(pages), 1)
        self.assertEqual(set(overview["selection_ids"]), {key for page in pages for key in page["node_ids"]})
        self.assertEqual(set(range(len(overview["edges"]))), {index for page in pages for index in page["edge_indices"]})
        self.assertTrue(all("omitted" in page["note"] for page in pages))
        self.assertTrue(all(len(page["node_ids"]) <= 12 for page in pages))
        self.assertTrue(all(page["width"] <= 1300 and page["height"] <= 900 for page in pages))

    def test_group_membership_must_be_exact_and_empty_scope_is_honest(self):
        rows = [part("one")]
        exact = graph_view.prepare_graph(raw_graph(rows), rows)
        with self.assertRaisesRegex(ValueError, "each result exactly once"):
            graph_view.prepare_overview(exact, rows, [])
        overview = graph_view.prepare_overview({"nodes": [], "edges": []}, [], [])
        self.assertIn("No proof graph nodes", graph_view.render_graph(overview))

    def test_branching_convergence_and_dense_edges_get_distinct_readable_lanes(self):
        rows = [part("unit" + str(index)) for index in range(6)]
        raw = raw_graph(rows)
        for source in rows[:3]:
            for target in rows[3:]:
                use(raw, source, target, source["id"])
        _, overview = self.prepare(raw, rows)
        page = graph_view.initial_page(overview)
        self.assertEqual(9, len(page["routes"]))
        self.assertEqual(9, len({(route["label_x"], route["label_y"]) for route in page["routes"]}))
        self.assertEqual(9, len({route["d"] for route in page["routes"]}))
        first, last = [page["positions"]["group-" + r["unit_id"]][1] for r in (rows[0], rows[-1])]
        self.assertLess(first, last)
        self.assertLess(page["width"], 1300)

    def test_overview_and_exact_previews_have_unique_ids_and_single_dialog(self):
        rows = [part("one"), part("two")]
        raw = raw_graph(rows)
        use(raw, rows[0], rows[1])
        exact, overview = self.prepare(raw, rows)
        value = graph_view.render_previews(overview, html.escape, exact_graph=exact)
        value += graph_view.render_previews(exact, html.escape, include_dialog=False)
        self.assertEqual(1, value.count('id="graph-preview"'))
        self.assertIn('id="overview-edge-preview-0"', value)
        self.assertIn('id="graph-edge-preview-0"', value)
        self.assertIn('data-graph-detail="two-1"', value)

    def test_static_svg_uses_pixel_geometry_instead_of_stretching_compact_cards(self):
        rows = [part("one"), part("two")]
        raw = raw_graph(rows)
        use(raw, rows[0], rows[1])
        exact, overview = self.prepare(raw, rows)
        for graph in (exact, overview):
            page = graph_view.initial_page(graph)
            self.assertIn(f'style="width:{page["width"]}px;min-width:{page["width"]}px"',
                          graph_view.render_graph(graph))
        self.assertEqual(308, graph_view.initial_page(overview)["width"])

    def test_dense_global_and_focus_pages_respect_geometry_and_preserve_every_use(self):
        rows = [part("dense" + str(index)) for index in range(12)]
        raw = raw_graph(rows)
        for index, source in enumerate(rows):
            for target in rows[index + 1:]:
                use(raw, source, target, source["id"])
        _, overview = self.prepare(raw, rows)
        self.assertEqual(66, len(overview["edges"]))
        for focus, pages in overview["views"].items():
            self.assertGreater(len(pages), 1)
            for page in pages:
                self.assertLessEqual(len(page["node_ids"]), 12)
                self.assertLessEqual(len(page["edge_indices"]), 48)
                self.assertLessEqual(page["height"], 900)
                self.assertLessEqual(page["width"], 1300)
                self.assertFalse(page["over_bound"])
                if focus != overview["initial_focus"]:
                    self.assertIn(focus, page["node_ids"])
            self.assertEqual(set(range(66)), {i for page in pages for i in page["edge_indices"]})
            self.assertEqual(set(overview["selection_ids"]), {key for page in pages for key in page["node_ids"]})

    def test_overview_keeps_issue_and_multiple_use_labels_without_repeating_checked_text(self):
        rows = [part("unit" + str(index)) for index in range(3)]
        raw = raw_graph(rows)
        use(raw, rows[0], rows[1])
        use(raw, rows[1], rows[2])
        use(raw, rows[0], rows[2], "pending", status="stale")
        use(raw, rows[0], rows[2], "broken", applicability_status="failed")
        _, overview = self.prepare(raw, rows)
        page = graph_view.initial_page(overview)
        shown = [route for route in page["routes"] if route["show_label"]]
        self.assertEqual(1, len(shown))
        self.assertEqual("start", shown[0]["label_anchor"])
        rightmost_card = max(xy[0] + 260 for xy in page["positions"].values())
        self.assertGreater(shown[0]["label_x"], rightmost_card)
        self.assertGreater(page["width"], shown[0]["label_x"] + 100)
        value = graph_view.render_graph(overview)
        tags = Tags(value).tags
        labels = [attrs for tag, attrs in tags if tag == "text" and attrs.get("class") == "graph-edge-label"]
        self.assertEqual(1, len(labels))
        self.assertIn("2 uses · 1 broken", value)
        self.assertIn('aria-label="1 use · checked:', value)

    def test_labeled_outside_lanes_reserve_separate_horizontal_label_space(self):
        rows = [part("cycle" + str(index)) for index in range(3)]
        raw = raw_graph(rows)
        for index, source in enumerate(rows):
            for target in rows:
                if source != target:
                    use(raw, source, target, source["id"], status="gap")
        _, overview = self.prepare(raw, rows)
        for page in overview["views"][overview["initial_focus"]]:
            routes = [route for route in page["routes"] if route["show_label"]]
            for left, right in zip(routes, routes[1:]):
                self.assertGreater(right["label_x"], left["label_x"] + len(left["label"]) * 6)


if __name__ == "__main__":
    unittest.main()
