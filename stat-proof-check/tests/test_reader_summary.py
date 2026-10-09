"""The opening summary reuses reviewed facts without creating new verdicts."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from test_html_report import REFERENCE, VisibleText, pc, report


def visible(value):
    parser = VisibleText()
    parser.feed(value)
    return " ".join(parser.parts)


def opening_html(value):
    return value.split('<section class="overview"', 1)[1].split('</section>', 1)[0]


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links = set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.links.append(attrs["href"][1:])


class InitialText(VisibleText):
    """Count the native initial reading view, excluding closed disclosure bodies."""

    def __init__(self):
        super().__init__()
        self.disclosures = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "details":
            self.disclosures.append({"open": "open" in dict(attrs), "summary": False})
        if tag == "summary" and self.disclosures:
            self.disclosures[-1]["summary"] = True

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "summary" and self.disclosures:
            self.disclosures[-1]["summary"] = False
        if tag == "details":
            self.disclosures.pop()

    def handle_data(self, text):
        if all(item["open"] or item["summary"] for item in self.disclosures):
            super().handle_data(text)


class ReaderSummaryTests(unittest.TestCase):
    """Controlled projections test presentation, not manuscript acceptance."""

    @classmethod
    def setUpClass(cls):
        cls.reference = report.build_report_projection(pc, REFERENCE, final=True)

    def project(self):
        return copy.deepcopy(self.reference)

    def prepare(self, projection):
        before = copy.deepcopy(projection)
        prepared = report._prepare_report_views(projection)
        self.assertEqual(before, projection)
        return prepared

    def issue(self, projection, identity, severity="S1", status="open", **fields):
        issue = copy.deepcopy(projection["issues"][0])
        issue.update(id=identity, anchor=report._id("issue", identity), severity=severity,
                     severity_rank=pc.ISSUE_SEVERITY_RANK[severity], status=status,
                     summary=f"Recorded finding {identity} has its own explanation.")
        issue.update(fields)
        return issue

    def test_nonfinal_complete_local_evidence_does_not_invent_a_release_diagnosis(self):
        projection = self.project()
        projection["release"] = {"status": "NONFINAL", "finalized_at": None}
        self.assertEqual(2, projection["coverage"]["checked_units"])
        self.assertEqual(2, projection["coverage"]["independent_checked_units"])
        prepared = self.prepare(projection)
        text = visible(opening_html(report.render_report(prepared))).lower()
        self.assertIn("no overall", prepared["summary"]["overall_judgment"].lower())
        self.assertIn("released", prepared["summary"]["overall_judgment"].lower())
        for invented in ("checking is incomplete", "only publication", "only finalization",
                         "missing evidence and remaining checks prevent"):
            self.assertNotIn(invented, text)
            self.assertNotIn(invented, report.render_report(prepared).lower())
        self.assertIn("2", " ".join(prepared["summary_details"]["coverage_text"]))
        self.assertTrue(prepared["summary_details"]["featured_findings"])

    def test_legacy_aggregate_review_counts_do_not_invent_group_completion(self):
        projection = self.project()
        projection["results"] = [projection["results"][0]]
        projection["issues"] = []
        projection["graph"] = {"nodes": [], "edges": []}
        projection["dependency_edges"] = []
        coverage = projection["coverage"]
        coverage.pop("checked_unit_ids", None)
        coverage.pop("independent_checked_unit_ids", None)
        coverage.update(expected_units=2, checked_units=1, independent_checked_units=1)
        prepared = self.prepare(projection)
        text = " ".join(prepared["summary_details"]["coverage_text"]).lower()
        self.assertNotIn("1 / 1 results reviewed", text)
        self.assertRegex(text, r"unit|per-result.*unavailable|per-result.*unresolved")

    def test_featured_findings_have_stable_priority_and_disclose_unfeatured_and_resolved(self):
        projection = self.project()
        projection["issues"] = [self.issue(projection, identity, severity, status) for identity, severity, status in (
            ("I-010", "S2", "open"), ("I-003", "S1", "deferred"),
            ("I-001", "S0", "open"), ("I-002", "S1", "open"),
            ("I-000", "S0", "resolved"))]
        prepared = self.prepare(projection)
        detail = prepared["summary_details"]
        self.assertEqual(["I-001", "I-002", "I-003"],
                         [item["issue_id"] for item in detail["featured_findings"]])
        self.assertEqual(1, detail["remaining_active_findings"])
        self.assertEqual(4, detail["active_findings"])
        self.assertEqual(1, detail["resolved_findings"])
        reverse = copy.deepcopy(projection)
        reverse["issues"].reverse()
        self.assertEqual(detail, self.prepare(reverse)["summary_details"])
        text = visible(opening_html(report.render_report(prepared))).lower()
        self.assertRegex(text, r"4 active")
        self.assertRegex(text, r"1 resolved")
        self.assertIn('href="#findings"', opening_html(report.render_report(prepared)))

    def test_inconclusive_and_presentation_findings_are_not_renamed_defects(self):
        projection = self.project()
        projection["issues"] = [self.issue(projection, "I-001", "S0", finding_status="inconclusive"),
                                self.issue(projection, "I-002", "S1", finding_status="defect", invalidation_kind="presentation_only")]
        prepared = self.prepare(projection)
        featured = prepared["summary_details"]["featured_findings"]
        labels = " ".join(item["label"] for item in featured).lower()
        self.assertIn("inconclusive", labels)
        self.assertIn("presentation", labels)
        self.assertNotIn("defect", labels)

    def test_long_reviewed_explanation_keeps_final_qualification_and_math_in_details(self):
        projection = self.project()
        issue = projection["issues"][0]
        formula = r"$\sup_{j\le m_n} P(|X_{n,j}|>\varepsilon)$"
        issue["summary"] = ("The local argument is valid. " + "Its applicability requires a separate bound. " * 35
                            + "The precise condition is " + formula + "; the claim remains conditional until that bound is supplied.")
        prepared = self.prepare(projection)
        feature = prepared["summary_details"]["featured_findings"][0]
        self.assertNotEqual("The local argument is valid.", feature["text"])
        self.assertNotIn("...", feature["text"])
        self.assertNotIn("The local argument is valid.", prepared["summary"]["main_reason"])
        html = report.render_report(prepared)
        markdown = report.render_markdown(prepared)
        self.assertIn(report._rich(issue["summary"]), html)
        self.assertIn(issue["summary"], markdown)
        self.assertIn('encoding="application/x-tex"', html)
        self.assertIn('href="#' + issue["anchor"] + '"', opening_html(html))

    def test_origin_is_the_failed_inference_not_the_theorem_statement(self):
        projection = self.prepare(self.project())
        featured = projection["summary_details"]["featured_findings"][0]
        self.assertIn("paper.tex, line 16", featured["location"])
        self.assertNotIn("lines 6 to 11", featured["location"])
        self.assertTrue(featured["location_anchor"])
        parser = Anchors()
        parser.feed(report.render_report(projection))
        self.assertIn(featured["location_anchor"], parser.ids)

    def test_nonstep_origin_never_inherits_an_unrelated_proof_step(self):
        for kind, origin, description in (
                ("dependency_use", {"unit_id": "thm:main", "use_id": "D001"}, "use"),
                ("obligation_pointer", {"unit_id": "lem:growing-max", "pointer": "/hypotheses/0"}, "contract"),
                ("interface_record", {"interface_id": "MI-01"}, "interface"),
                ("global_check", {"aspect": "assumption_compatibility", "evidence_spans": []}, "global")):
            with self.subTest(origin=kind):
                projection = self.project()
                issue = projection["issues"][0]
                issue.update(origin_ref={"kind": kind, **origin}, source_ids=[], failures=[],
                             proof_path={"status": "unavailable", "nodes": [], "edges": []})
                prepared = self.prepare(projection)
                featured = prepared["summary_details"]["featured_findings"][0]
                self.assertIn(description, featured["location"].lower())
                self.assertNotIn("paper.tex, line 16", featured["location"])
                self.assertNotIn("failed inference", featured["location"].lower())
                if kind == "dependency_use":
                    self.assertNotIn("lines 20 to 24", featured["location"])
                parser = Anchors()
                parser.feed(report.render_report(prepared))
                self.assertIn(featured["location_anchor"], parser.ids)

    def test_no_active_issue_does_not_turn_conditional_or_unchecked_support_into_success(self):
        projection = self.project()
        projection["issues"] = []
        for row, status in zip(projection["results"], ("conditionally_verified", "not_checked")):
            row["issue_ids"] = []
            row["judgments"].update(argument_status="valid", statement_status=status,
                                    dependency_closure="verified", use_site_sufficiency="sufficient")
        projection["release"]["status"] = "NONFINAL"
        prepared = self.prepare(projection)
        summary = " ".join(prepared["summary"].values()).lower()
        self.assertIn("conditional", summary)
        self.assertRegex(summary, r"unchecked|pending|not checked")
        self.assertNotIn("conclusion and dependency checks are complete", summary)
        self.assertNotIn("every check passed", summary)
        self.assertNotIn("no load-bearing defect", summary)
        html = opening_html(report.render_report(prepared))
        self.assertTrue(any('href="#' + group["id"] + '"' in html for group in prepared["result_groups"]))

    def test_multipart_results_keep_formal_assertion_and_supplement_judgments_separate(self):
        projection = self.project()
        template = copy.deepcopy(projection["results"][1])
        rows = []
        for index, (argument, statement) in enumerate((
                ("gap", "not_established"), ("invalid", "established"),
                ("valid", "conditionally_verified"), ("valid", "established")), 1):
            row = copy.deepcopy(template)
            row.update(id=f"formal-{index}", conclusion_id=f"C{index:03d}", issue_ids=[],
                       kind="theorem", separate_assertion=False, display_label="Theorem 2.1")
            row["judgments"].update(contract_fidelity="verified", argument_status=argument,
                                    statement_status=statement, dependency_closure="verified",
                                    use_site_sufficiency="sufficient")
            row["statement_support"] = ({"acceptance": "accepted", "extra_conditions": []}
                                         if index == 2 else
                                         {"acceptance": "accepted", "extra_conditions": ["Uniform tail control is assumed."]}
                                         if index == 3 else {})
            rows.append(row)
        associated = copy.deepcopy(rows[-1])
        associated.update(id="associated-refutation", conclusion_id="C005", kind="conclusion",
                          separate_assertion=True, display_label=None)
        associated["judgments"].update(argument_status="invalid", statement_status="refuted")
        other = copy.deepcopy(rows[-1])
        other.update(id="other-theorem", unit_id="thm:other", conclusion_id="C001")
        # The identical reader title must not merge independent manuscript owners.
        projection["results"] = [*rows, associated, other]
        projection["issues"] = []
        projection["graph"] = {"nodes": [], "edges": []}
        projection["dependency_edges"] = []
        prepared = self.prepare(projection)
        counts = prepared["summary_details"]["impact_counts"]
        self.assertEqual(2, len(prepared["result_groups"]))
        self.assertEqual(1, counts["affected_results"])
        self.assertEqual(1, counts["proof_problem_results"])
        self.assertEqual(2, counts["proof_problems"])
        self.assertEqual(0, counts["refuted"])
        self.assertEqual(1, counts["associated_assertions"])
        self.assertEqual(1, counts["associated_refuted"])
        self.assertEqual(3, counts["established"])
        self.assertEqual(1, counts["supplemented"])
        self.assertEqual(1, counts["restricted_supplements"])
        impact = prepared["summary"]["impact"].lower()
        self.assertIn("associated", impact)
        self.assertIn("additional conditions", impact)
        self.assertIn("unchanged", impact)
        self.assertNotRegex(impact, r"theorem(?:s)? (?:is|are) (?:false|refuted|established)")

    def test_failed_upstream_connection_does_not_refute_valid_downstream_statement(self):
        projection = self.project()
        downstream = projection["results"][1]
        downstream["judgments"].update(argument_status="valid", statement_status="established",
                                        dependency_closure="verified", use_site_sufficiency="sufficient")
        downstream["issue_ids"] = []
        # The overview still has an incoming failed use. It cannot supply a new
        # mathematical verdict for a statement whose recorded alternative passed.
        self.assertTrue(projection["dependency_edges"])
        prepared = self.prepare(projection)
        counts = prepared["summary_details"]["impact_counts"]
        self.assertEqual(1, counts["refuted"])
        self.assertEqual(1, counts["established"])
        self.assertEqual(1, counts["affected_results"])

    def test_failed_prerequisite_support_remains_attention_without_refuting_accepted_statement(self):
        for status in ("gap", "incorrect"):
            with self.subTest(dependency_closure=status):
                projection = self.project()
                projection["issues"] = []
                for row in projection["results"]:
                    row["issue_ids"] = []
                    row["judgments"].update(contract_fidelity="verified", argument_status="valid",
                                            statement_status="established", dependency_closure="verified",
                                            use_site_sufficiency="sufficient")
                projection["results"][0]["judgments"]["dependency_closure"] = status
                prepared = self.prepare(projection)
                counts = prepared["summary_details"]["impact_counts"]
                self.assertEqual(1, counts["affected_results"])
                self.assertEqual(0, counts["refuted"])
                self.assertEqual(0, counts["proof_problems"])
                self.assertEqual(2, counts["established"])
                self.assertRegex(prepared["summary"]["impact"].lower(), r"support|prerequisite|dependency")
                self.assertNotRegex(prepared["summary"]["impact"].lower(),
                                    r"conclusion[^.]*not established|conclusion[^.]*unclear")

    def test_verified_sufficient_active_option_is_neither_candidate_nor_applied_resolution(self):
        projection = self.project()
        issue = projection["issues"][0]
        issue["repairs"] = [copy.deepcopy(issue["repairs"][0])]
        issue["repairs"][0].update(verification_status="verified_sufficient", assumption_cost="none",
                                  scientific_cost="Preserves the statement and its assumptions.",
                                  statement_support_ref={"unit_id": "thm:main", "conclusion_id": "C001",
                                                         "sha256": "a" * 64})
        issue["repair_search"] = {}
        projection["results"][1]["statement_support"] = {
            "acceptance": "accepted", "extra_conditions": [], "sha256": "a" * 64}
        projection["results"][1]["judgments"]["statement_status"] = "established"
        prepared = self.prepare(projection)
        outlook = prepared["summary"]["repair_outlook"].lower()
        self.assertIn("verified", outlook)
        self.assertRegex(outlook, r"target|exact|conditions")
        self.assertRegex(outlook, r"application.*not|unapplied|does not.*(?:applied|edited)")
        self.assertNotIn("candidate", outlook)
        self.assertNotIn("issue resolved", outlook)
        self.assertEqual(1, prepared["summary_details"]["active_findings"])

    def test_resolved_history_preserves_resolution_without_reopening_active_repairs(self):
        projection = self.project()
        issue = projection["issues"][0]
        issue.update(status="resolved", resolution="The checked revised proof supplies the needed uniform bound.",
                     current_resolution={"kind": "source_span", "file": "paper.tex", "start_line": 16, "end_line": 17},
                     recheck_evidence=[{"unit_id": "lem:growing-max", "status": "complete"}])
        prepared = self.prepare(projection)
        details = prepared["summary_details"]
        self.assertEqual(0, details["active_findings"])
        self.assertEqual(1, details["resolved_findings"])
        self.assertFalse(details["featured_findings"])
        self.assertFalse(details["repair_directions"])
        outlook = prepared["summary"]["repair_outlook"].lower()
        self.assertIn("resolved", outlook)
        self.assertIn("recheck", outlook)
        # Other conclusion judgments in this projection still need attention.
        self.assertNotIn("all issues are fixed", outlook)

    def test_later_candidate_options_and_local_search_are_not_collapsed_into_verified_repair(self):
        prepared = self.prepare(self.project())
        outlook = visible(opening_html(report.render_report(prepared))).lower()
        self.assertRegex(outlook, r"stronger|regularity|moment|assumption")
        self.assertRegex(outlook, r"weaker|restrict|claim|narrower")
        self.assertRegex(outlook, r"proposed|candidate")
        self.assertRegex(outlook, r"locally|local inspection")
        self.assertRegex(outlook, r"recheck|unverified|not.*verif")
        self.assertNotIn("repairs are verified", outlook)
        self.assertNotIn("issue resolved", outlook)

    def test_same_finding_directions_keep_targets_costs_and_verification_without_inferred_alternatives(self):
        projection = self.project()
        issue = projection["issues"][0]
        issue["repair_search"] = {}
        issue["repairs"][1]["verification_status"] = "verified_sufficient"
        prepared = self.prepare(projection)
        directions = prepared["summary_details"]["repair_directions"]
        self.assertEqual(2, len(directions))
        by_cost = {item["cost"]: item for item in directions}
        stronger = by_cost[issue["repairs"][0]["scientific_cost"]]
        narrower = by_cost[issue["repairs"][1]["scientific_cost"]]
        self.assertIn("stronger regularity or moment assumptions", stronger["cost"])
        self.assertIn("proposed", stronger["verification"].lower())
        self.assertNotIn("verified sufficient", stronger["verification"].lower())
        self.assertIn("no stronger assumption", narrower["cost"])
        self.assertIn("narrower setting", narrower["cost"])
        self.assertIn("verified sufficient", narrower["verification"].lower())
        self.assertNotIn("proposed", narrower["verification"].lower())
        self.assertEqual([issue["anchor"]], stronger["issue_anchors"])
        self.assertEqual([issue["anchor"]], narrower["issue_anchors"])
        # Even suggestions for one finding need not be interchangeable.
        self.assertNotIn("alternatives", prepared["summary"]["repair_outlook"].lower())
        self.assertNotIn(") or (", prepared["summary"]["repair_outlook"])
        html = opening_html(report.render_report(prepared))
        initial = InitialText()
        initial.feed(html)
        featured = prepared["summary_details"]["featured_repair_directions"]
        self.assertTrue(featured)
        for direction in featured:
            self.assertIn(direction["cost"], " ".join(initial.parts))
            self.assertIn(direction["verification"], " ".join(initial.parts))
        for direction in (stronger, narrower):
            matching = [visible(item) for item in re.findall(r"<li>(.*?)</li>", html, re.S)
                        if direction["cost"] in visible(item)]
            self.assertTrue(matching)
            self.assertTrue(any(direction["verification"] in item for item in matching))
            self.assertTrue(any(direction["target"] in item for item in matching))

    def test_independent_repairs_with_equal_costs_keep_distinct_findings_and_targets(self):
        projection = self.project()
        issues = []
        for index, result in enumerate(projection["results"], 1):
            issue = self.issue(projection, f"I-{index:03d}", affected_result_ids=[result["id"]],
                               affected_units=[result["unit_id"]], repair_search={})
            issue["repairs"] = [copy.deepcopy(issue["repairs"][0])]
            repair = issue["repairs"][0]
            repair.update(scientific_cost="Adds regularity", target_source_ids=result["support_source_ids"],
                          verification_status="candidate", proposal=f"Repair only {result['unit_id']}.")
            issues.append(issue)
        projection["issues"] = issues
        prepared = self.prepare(projection)
        directions = prepared["summary_details"]["repair_directions"]
        self.assertEqual(2, len(directions))
        self.assertEqual(2, len(prepared["summary_details"]["featured_repair_directions"]))
        self.assertEqual(2, len({row["target"] for row in directions}))
        self.assertEqual(2, len({row["anchor"] for row in directions}))
        html = opening_html(report.render_report(prepared))
        markdown = report.render_markdown(prepared).split("## Results and impact", 1)[0]
        self.assertNotIn("alternatives", visible(html).lower())
        self.assertNotIn(" or ", visible(html).split("Repair outlook", 1)[1].lower())
        for index, direction in enumerate(directions):
            self.assertEqual([issues[index]["anchor"]], direction["issue_anchors"])
            row = next(item for item in re.findall(r"<li>(.*?)</li>", html, re.S)
                       if 'href="#' + direction["anchor"] + '"' in item)
            self.assertIn('href="#' + issues[index]["anchor"] + '"', row)
            self.assertNotIn('href="#' + issues[1 - index]["anchor"] + '"', row)
            self.assertIn(direction["target"], visible(row))
            self.assertIn(direction["cost"], visible(row))
            self.assertIn(direction["verification"], visible(row))
            md_row = next(item for item in markdown.splitlines() if '](#' + direction["anchor"] + ')' in item)
            self.assertIn('](#' + issues[index]["anchor"] + ')', md_row)
            for value in (direction["cost"], direction["verification"], direction["target"]):
                self.assertIn(value, md_row)

    def test_bounded_failure_to_find_repair_does_not_become_impossibility(self):
        projection = self.project()
        projection["issues"][0]["repairs"] = []
        projection["issues"][0]["repair_search"] = {"conclusion": "no_local_repair_found", "strategies": []}
        outlook = self.prepare(projection)["summary"]["repair_outlook"].lower()
        self.assertIn("bounded", outlook)
        self.assertIn("no local repair", outlook)
        self.assertNotIn("impossible", outlook)
        self.assertNotIn("cannot be repaired", outlook)

    def test_both_exports_select_same_facts_and_links_and_do_not_change_input(self):
        projection = self.project()
        projection["issues"] = [self.issue(projection, f"I-{index:03d}") for index in range(1, 8)]
        prepared = self.prepare(projection)
        before = copy.deepcopy(prepared)
        html, markdown = report.render_report(prepared), report.render_markdown(prepared)
        self.assertEqual(before, prepared)
        html_opening, md_opening = opening_html(html), markdown.split("## Results and impact", 1)[0]
        for item in prepared["summary_details"]["featured_findings"]:
            self.assertIn('href="#' + item["anchor"] + '"', html_opening)
            self.assertIn('](#' + item["anchor"] + ')', md_opening)
            self.assertIn(item["text"], visible(html_opening))
            self.assertIn(item["text"], md_opening)
        parser = Anchors()
        parser.feed(html)
        self.assertFalse(set(parser.links) - parser.ids)
        for target in re.findall(r"\]\(#([^)]*)\)", md_opening):
            self.assertIn('id="' + target + '"', markdown)
        initial = InitialText()
        initial.feed(html_opening)
        self.assertLessEqual(len(" ".join(initial.parts).split()), 240)
        self.assertNotIn("<script", html_opening)


class ReaderSummaryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "audit"
        shutil.copytree(REFERENCE, self.root)

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file()}

    def project(self):
        before = self.snapshot()
        projection = report.build_report_projection(pc, self.root)
        report.render_report(projection)
        report.render_markdown(projection)
        self.assertEqual(before, self.snapshot())
        return projection

    def test_missing_ledger_does_not_count_placeholder_as_assessed(self):
        (self.root / "audit/04_local_checks/thm-main.ledger.json").unlink()
        projection = self.project()
        self.assertEqual(1, projection["coverage"]["checked_units"])
        self.assertEqual(1, projection["coverage"]["checked_conclusions"])
        self.assertIsNone(projection["coverage"]["expected_conclusions"])
        summary = " ".join(projection["summary"].values()).lower()
        self.assertRegex(summary, r"missing|unavailable")
        self.assertNotIn("2 statements are refuted", summary)

    def test_source_drift_is_visible_and_does_not_reuse_past_refutations_as_current(self):
        source = self.root / "audit/00_sources/project/paper.tex"
        source.write_text(source.read_text(encoding="utf-8") + "% drift\n", encoding="utf-8")
        projection = self.project()
        self.assertEqual(0, projection["coverage"]["checked_units"])
        summary = " ".join(projection["summary"].values()).lower()
        self.assertRegex(summary, r"stale|changed|current.*unavailable|not current")
        self.assertNotIn("2 statements are refuted", summary)
        self.assertNotIn("2 refuted conclusions", summary)

    def test_unknown_scope_and_unreadable_issue_log_do_not_establish_clean_coverage(self):
        manifest_path = self.root / "AUDIT_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["audit_scope"].update(status="unreviewed", in_scope_units=[])
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (self.root / "audit/06_reports/ISSUE_LOG.json").write_text("{", encoding="utf-8")
        projection = self.project()
        self.assertIsNone(projection["coverage"]["expected_units"])
        text = visible(opening_html(report.render_report(projection))).lower()
        self.assertRegex(text, r"scope.*unresolved|scope.*unknown|unresolved.*scope")
        self.assertRegex(text, r"finding.*unavailable|issue.*unavailable|finding.*unreadable")
        self.assertNotIn("0 / 0", text)
        self.assertNotIn("no active issue", text)


if __name__ == "__main__":
    unittest.main()
