"""Reader groups retain source statements, uncertainty, and exact evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from html.parser import HTMLParser

from test_html_report import REFERENCE, pc, report


def assessed_result(unit="unit", conclusion="C1", **values):
    row = {
        "id": unit + "-" + str(conclusion), "unit_id": unit,
        "conclusion_id": conclusion, "kind": "theorem", "separate_assertion": False,
        "manuscript_title": "Tail control", "display_label": "Theorem 2.1",
        "location": "paper.tex, lines 10 to 20", "statement_source_ids": [],
        "availability": "available", "issue_ids": [], "claim": "Selected conclusion.",
        "judgments": {"contract_fidelity": "verified", "argument_status": "valid",
                      "statement_status": "established", "dependency_closure": "verified",
                      "use_site_sufficiency": "sufficient"},
    }
    row.update(values)
    return row


def group_projection(rows, **values):
    projection = {"results": rows, "sources": [], "issues": [], "manuscript_units": {},
                  "coverage": {"unresolved_conclusion_units": []}}
    projection.update(values)
    return projection


class Disclosures(HTMLParser):
    """Read native disclosure ancestry independently of the report's script."""

    def __init__(self):
        super().__init__()
        self.stack, self.elements, self.details, self.links = [], {}, {}, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        identity = attrs.get("id")
        if identity:
            self.elements[identity] = (tag, attrs, tuple(self.stack))
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.links.append(attrs["href"][1:])
        if tag == "details":
            if identity:
                self.details[identity] = attrs
            self.stack.append(identity)

    def handle_endtag(self, tag):
        if tag == "details":
            self.stack.pop()


class ResultGroupTests(unittest.TestCase):
    def test_unclear_unchecked_and_insufficient_remain_visible_without_issue_ids(self):
        cases = (("statement_status", "unclear", "unclear"),
                 ("argument_status", "unclear", "unclear"),
                 ("dependency_closure", "unchecked", "pending"),
                 ("use_site_sufficiency", "insufficient", "insufficient"))
        for field, status, count in cases:
            with self.subTest(field=field, status=status):
                row = assessed_result()
                row["judgments"][field] = status
                projection = group_projection([row])
                before = copy.deepcopy(projection)
                group = report._result_groups(projection)[0]
                self.assertEqual(1, group["assessment_counts"][count])
                self.assertEqual(1, group["assessment_counts"]["attention"])
                self.assertIn(count, group["assessment_summary"].lower())
                self.assertEqual([], row["issue_ids"])
                self.assertEqual(before, projection)

    def test_missing_placeholder_and_partially_known_coverage_do_not_invent_conclusions(self):
        placeholder = assessed_result(conclusion=None, availability="missing")
        placeholder["judgments"] = {key: "not_checked" for key in report.JUDGMENT_FIELDS}
        for rows, unresolved_units, known_count in (
                ([placeholder], [], 0),
                ([assessed_result()], ["unit"], 1),
                ([assessed_result(), placeholder], ["unit"], 1)):
            with self.subTest(known_count=known_count, records=len(rows)):
                projection = group_projection(rows, coverage={"unresolved_conclusion_units": unresolved_units})
                group = report._result_groups(projection)[0]
                self.assertTrue(group["assessment_counts"]["unresolved_conclusion_count"])
                self.assertEqual(known_count, group["assessment_counts"]["conclusions"])
                self.assertIn("coverage unresolved", group["assessment_summary"].lower())
                self.assertEqual([row["id"] for row in rows], group["result_ids"])
                if not known_count:
                    self.assertNotIn("1 recorded conclusion", group["assessment_summary"])

    def test_associated_refutation_is_distinguished_from_the_formal_result(self):
        formal = assessed_result()
        separate = assessed_result(conclusion="outside", kind="conclusion", separate_assertion=True,
                                   display_label=None, manuscript_title=None,
                                   location="paper.tex, lines 40 to 42")
        separate["judgments"]["statement_status"] = "refuted"
        projection = group_projection([formal, separate])
        before = copy.deepcopy(projection)
        group = report._result_groups(projection)[0]
        self.assertEqual([formal["id"]], group["formal_result_ids"])
        self.assertEqual([separate["id"]], group["associated_result_ids"])
        self.assertEqual(1, group["assessment_counts"]["refuted"])
        self.assertIn("Associated assertions: refuted", group["assessment_summary"])
        self.assertNotIn("1 refuted conclusion", group["assessment_summary"])
        self.assertEqual("Theorem 2.1", group["display_label"])
        self.assertEqual(before, projection)

    def test_only_current_complete_statement_is_presented_as_complete(self):
        source = {"id": "passage", "status": "locked", "quote": "Then $P_1$ holds.",
                  "file": "paper.tex", "start_line": 19, "end_line": 19}
        row = assessed_result(statement_source_ids=[source["id"]])
        for metadata, expected in (({}, False),
                                   ({"unit": {"statement_source_ids": [source["id"]],
                                              "complete_statement": True}}, True)):
            with self.subTest(complete=expected):
                projection = group_projection([row], sources=[source], manuscript_units=metadata)
                before = copy.deepcopy(projection)
                group = report._result_groups(projection)[0]
                self.assertIs(expected, group["complete_statement"])
                self.assertEqual(source["quote"], group["claim"])
                self.assertEqual([source["id"]], group["statement_source_ids"])
                if expected:
                    self.assertNotIn("unavailable", group["statement_label"])
                else:
                    self.assertIn("complete statement unavailable", group["statement_label"])
                    self.assertIn(group["statement_label"], group["graph_reading_claim"])
                self.assertEqual(before, projection)

        for broken_source in ({**source, "status": "unavailable", "quote": None},
                              {**source, "math_excerpt_boundary": True}):
            with self.subTest(source=broken_source["status"], boundary=broken_source.get("math_excerpt_boundary")):
                projection = group_projection([row], sources=[broken_source], manuscript_units={
                    "unit": {"statement_source_ids": [source["id"]], "complete_statement": True}})
                group = report._result_groups(projection)[0]
                self.assertFalse(group["complete_statement"])
                self.assertIn("unavailable", group["statement_label"])
                self.assertEqual([source["id"]], group["statement_source_ids"])

    def test_identical_titles_and_labels_do_not_merge_different_units(self):
        rows = [assessed_result("first", "C1"), assessed_result("second", "C1"),
                assessed_result("first", "C2")]
        projection = group_projection(rows)
        before = copy.deepcopy(projection)
        groups = report._result_groups(projection)
        self.assertEqual(["first", "second"], [group["unit_id"] for group in groups])
        self.assertEqual([["first-C1", "first-C2"], ["second-C1"]],
                         [group["result_ids"] for group in groups])
        self.assertEqual(2, len({group["id"] for group in groups}))
        self.assertEqual(before, projection)


class OverviewReportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_hashes = cls.reference_hashes()
        cls.projection = report.build_report_projection(pc, REFERENCE, final=False)

    @staticmethod
    def reference_hashes():
        return {path.relative_to(REFERENCE).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in REFERENCE.rglob("*") if path.is_file()}

    def test_full_statement_is_extracted_from_the_inventory_range_and_keeps_hypotheses(self):
        projection = copy.deepcopy(self.projection)
        manifest = pc.load_audit_manifest(REFERENCE)[1]
        inventory = json.loads((REFERENCE / manifest["inventory_file"]).read_text(encoding="utf-8"))
        paper = pc.resolve_stored_path(manifest["paper_file"], REFERENCE)
        sources = {source["id"]: source for source in projection["sources"]}
        units = {unit["id"]: unit for unit in inventory["units"]}
        for group in projection["result_groups"]:
            with self.subTest(unit=group["unit_id"]):
                statement = units[group["unit_id"]]["statement"]
                path = pc.resolve_stored_path(statement["file"], paper.parent)
                exact = "\n".join(path.read_text(encoding="utf-8").splitlines()[
                    statement["start_line"] - 1:statement["end_line"]])
                self.assertTrue(group["complete_statement"])
                self.assertEqual(1, len(group["statement_source_ids"]))
                source = sources[group["statement_source_ids"][0]]
                self.assertEqual(exact, source["quote"])
                self.assertEqual(pc.sha256_text(exact), source["sha256"])
                self.assertEqual((statement["start_line"], statement["end_line"]),
                                 (source["start_line"], source["end_line"]))
                self.assertEqual("locked", source["status"])
                first_claim = next(row for row in projection["results"] if row["id"] == group["result_ids"][0])
                first_claim["claim"] = "Only one narrow checked consequence."
        renewed = report._prepare_report_views(projection)
        lemma = next(group for group in renewed["result_groups"] if group["unit_id"] == "lem:growing-max")
        self.assertIn("random variables on one probability", lemma["claim"])
        self.assertIn("for each", lemma["claim"])
        self.assertNotIn("Only one narrow", lemma["claim"])
        self.assertEqual(self.source_hashes, self.reference_hashes())

    def test_native_collapsed_groups_retain_conclusion_and_source_anchors(self):
        projection = copy.deepcopy(self.projection)
        value = report.render_report(projection)
        parser = Disclosures()
        parser.feed(value)
        self.assertEqual([], parser.stack)
        for group in projection["result_groups"]:
            self.assertNotIn("open", parser.details[group["id"]])
            for identity in group["result_ids"]:
                self.assertIn(group["id"], parser.elements[identity][2])
                self.assertNotIn("open", parser.details[identity])
                self.assertIn(identity, parser.links)
        for wrapper in ("premises", "source-evidence"):
            self.assertNotIn("open", parser.details[wrapper])
        for source in projection["sources"]:
            self.assertIn("source-evidence", parser.elements[source["id"]][2])
            self.assertNotIn("open", parser.details[source["id"]])
            if source.get("quote") is not None:
                numbered = source["quote"]
                if source.get("start_line") is not None:
                    numbered = "\n".join(f"{source['start_line'] + index:>4}  {line}"
                                         for index, line in enumerate(source["quote"].splitlines()))
                self.assertIn('<pre class="source">' + report._e(numbered) + '</pre>', value)
        for node in projection["graph"]["nodes"]:
            self.assertIn(node["detail_id"], parser.elements)
        self.assertFalse(set(parser.links) - set(parser.elements))
        self.assertEqual([], report.validate_html(value, projection))

    def test_deriving_and_rendering_views_leave_projection_and_reference_unchanged(self):
        projection = copy.deepcopy(self.projection)
        projection.pop("result_groups")
        projection.pop("overview")
        before = copy.deepcopy(projection)
        prepared = report._prepare_report_views(projection)
        self.assertEqual(before, projection)
        self.assertEqual(before["results"], prepared["results"])
        self.assertEqual(before["graph"], prepared["graph"])
        self.assertEqual(before["sources"], prepared["sources"])
        ready_before = copy.deepcopy(prepared)
        value = report.render_report(prepared)
        self.assertEqual(ready_before, prepared)
        self.assertEqual([], report.validate_html(value, prepared))
        self.assertEqual(ready_before, prepared)
        self.assertEqual(self.source_hashes, self.reference_hashes())


if __name__ == "__main__":
    unittest.main()
