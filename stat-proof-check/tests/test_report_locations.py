"""Reader navigation follows physical manuscript evidence, not audit counters."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from test_html_report import REFERENCE, pc, report


class ReportLocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "audit"
        shutil.copytree(REFERENCE, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def project(self):
        return report.build_report_projection(pc, self.root)

    def test_bundled_links_follow_top_level_and_legacy_report_locations_after_move(self):
        manifest = pc.load_audit_manifest(self.root)[1]
        original = self.project()
        for primary in ("proofcheck-report.html", "audit/06_reports/FINAL_REPORT.html"):
            with self.subTest(primary=primary):
                staged = copy.deepcopy(manifest)
                staged["report_contract"]["primary"] = primary
                projection = report.build_report_projection(pc, self.root, manifest_override=staged)
                links = [(source["file"], source["bundle_href"]) for source in projection["sources"] if source.get("bundle_href")]
                links.extend((link["artifact"], link["href"]) for result in projection["results"]
                             for link in result["initial_review"].get("artifacts", []))
                self.assertTrue(links)
                report_parent = (self.root / primary).parent
                for relative, href in links:
                    self.assertEqual((self.root / relative).resolve(), (report_parent / unquote(href)).resolve())
                    self.assertTrue((report_parent / unquote(href)).is_file())
                self.assertEqual([r["judgments"] for r in original["results"]],
                                 [r["judgments"] for r in projection["results"]])
                if primary == "proofcheck-report.html":
                    self.assertTrue(all(not href.startswith("../") for _, href in links))

    def test_essential_scope_is_authored_typeset_and_adjacent_to_judgment(self):
        projection = report.build_report_projection(pc, self.root, report_context={
            "essential_scope": r"Coverage concerns a fixed grid $\mathcal{T}$ under the stated approximation conditions."})
        html = report.render_report(projection)
        overview = html.split('<section class="overview"', 1)[1].split('</section>', 1)[0]
        self.assertIn('Essential scope', overview)
        self.assertIn('<math ', overview)
        self.assertIn('Coverage concerns a fixed grid', overview)
        self.assertLess(overview.index('Essential scope'), overview.index('Key issues'))
        for missing in ("", None, [], {}):
            with self.assertRaisesRegex(ValueError, "essential_scope must be a nonempty string"):
                report.build_report_projection(pc, self.root, report_context={"essential_scope": missing})
        with self.assertRaises(ValueError):
            report.build_report_projection(pc, self.root, report_context={"essential_scope": "The proof is formally verified."})

    def test_latex_reading_note_preserves_review_record_and_does_not_apply_to_pdf(self):
        projection = self.project()
        provenance = projection["audit"]["source_provenance"]
        self.assertEqual("latex", provenance["kind"])
        before = copy.deepcopy(provenance)
        note = report._source_review_note(provenance)
        for rendered in (report.render_report(projection), report.render_markdown(projection)):
            self.assertIn(note, rendered)
            self.assertIn("not_started", rendered)
        self.assertEqual(before, provenance)
        pdf_projection = copy.deepcopy(projection)
        pdf_projection["audit"]["source_provenance"]["kind"] = "pdf_transcription"
        for rendered in (report.render_report(pdf_projection), report.render_markdown(pdf_projection)):
            self.assertNotIn(note, rendered)
            self.assertIn("not_started", rendered)

    def test_reference_path_locates_premise_failure_conclusion_and_actual_consumer(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        projection = self.project()
        issue = projection["issues"][0]
        path = issue["proof_path"]
        self.assertEqual("available", path["status"])
        self.assertEqual(["paper.tex, line 15", "paper.tex, line 16", "paper.tex, line 17", "paper.tex, line 29"],
                         [node["location"] for node in path["nodes"]])
        self.assertEqual(["Consumed premise", "Failed inference", "Conclusion step", "Later consuming inference"],
                         [node["role"] for node in path["nodes"]])
        self.assertEqual(["verified", "incorrect", "incorrect", "incorrect"], [node["status"] for node in path["nodes"]])
        edge = next(edge for edge in path["edges"] if edge["kind"] == "dependency_use")
        sources = {row["id"]: row for row in projection["sources"]}
        citation = sources[edge["citation_source_ids"][0]]
        self.assertEqual((27, 28), (citation["start_line"], citation["end_line"]))
        self.assertEqual(("incorrect", "passed"), (edge["effective_status"], edge["applicability_status"]))
        value = report.render_report(projection)
        self.assertIn('Cited result use · paper.tex, lines 27 to 28', value)
        self.assertIn('Later consuming inference · paper.tex, line 29', value)
        conclusion = path["nodes"][2]
        conclusion_article = value.split('id="' + conclusion["id"] + '"', 1)[1].split('</article>', 1)[0]
        reading, technical = conclusion_article.split('<details class="original-claim"', 1)
        self.assertIn('Hence the maximum converges to zero in probability.', reading)
        self.assertNotIn(report._e(conclusion["claim"]), reading)
        self.assertIn(report._e(conclusion["claim"]), technical)
        self.assertEqual([], report.validate_html(value, projection))
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_finding_contains_exact_premise_assertion_and_return_links(self):
        projection = self.project()
        issue = projection["issues"][0]
        value = report.render_report(projection)
        finding = value.split('id="' + issue["anchor"] + '"', 1)[1].split('<h2 id="source-evidence">', 1)[0]
        self.assertIn(report._rich(r'For each fixed $j$, $P(|X_{n,j}| > \varepsilon) \to 0$ by hypothesis.'), finding)
        self.assertIn(report._rich(r'Therefore $P(\max_{1 \le j \le m_n} |X_{n,j}| > \varepsilon) \to 0$.'), finding)
        for result_id in issue["affected_result_ids"]:
            self.assertIn('href="#' + result_id + '"', finding)
        self.assertEqual(2, finding.count('Directly refuted by evidence for this statement.'))
        for repair in issue["repairs"]:
            self.assertEqual("source_span", repair["target_ref"]["kind"])
            self.assertTrue(repair["target_source_ids"])
        self.assertIn('Proposed repair target · paper.tex, lines 6 to 11', finding)
        self.assertNotIn('Failed inference · paper.tex:16-16', finding)

    def test_path_and_detail_labels_preserve_each_finding_classification(self):
        projection = self.project()
        original = projection["issues"][0]
        result = projection["results"][0]
        unit = result["unit_id"]
        source_id = original["source_ids"][0]
        sources = {row["id"]: row for row in projection["sources"]}
        ledger = {"steps": [{"id": "S001", "status": "unclear", "premise_uses": [],
                            "inference": {"conclusion_move": "M001", "moves": [
                                {"id": "M001", "claim": "The bound is under review.",
                                 "justification": "The recorded concern requires analysis.",
                                 "prior_move_ids": [], "premise_ids": []}]}}]}
        cases = (("inconclusive", "scope_inconclusive", "open", "Unresolved inference"),
                 ("defect", "presentation_only", "open", "Presentation concern"),
                 ("defect", "proof_gap", "open", "Failed inference"),
                 ("inconclusive", "scope_inconclusive", "resolved", "Historical finding"),
                 ("defect", "presentation_only", "resolved", "Historical finding"))
        issues = []
        for index, (status, kind, lifecycle, role) in enumerate(cases):
            with self.subTest(finding=status, kind=kind, lifecycle=lifecycle):
                issue = copy.deepcopy(original)
                issue.update(id=f"I-{index + 20:03d}", anchor=f"finding-classification-{index}",
                             summary=f"Reviewed concern {index}.", finding_status=status,
                             invalidation_kind=kind, status=lifecycle, failures=[],
                             load_bearing=kind != "presentation_only",
                             origin_ref={"kind": "ledger_move", "unit_id": unit,
                                         "step_id": "S001", "move_id": "M001"})
                step_status = "verified" if kind == "presentation_only" else "unclear" if status == "inconclusive" else "gap"
                ledger["steps"][0]["status"] = step_status
                issue["proof_path"] = report._issue_proof_path(
                    pc, issue, projection["results"], {unit: (Path("unused-ledger.json"), ledger)},
                    {unit: {}}, {}, [], lambda *_: source_id, sources)
                path = issue["proof_path"]
                if lifecycle == "resolved":
                    self.assertEqual("historical", path["status"])
                    self.assertFalse(path["nodes"])
                    issue.update(resolution="The reviewed concern is resolved.", recheck_evidence=["Reviewed resolution"])
                else:
                    self.assertEqual([role], [node["role"] for node in path["nodes"]])
                    self.assertEqual([step_status], [node["status"] for node in path["nodes"]])
                    # An older projection's stored role must not override the
                    # finding classification when it is displayed again.
                    path["nodes"][0]["role"] = "Failed inference"
                    issue["failures"] = [{"claim": "Recorded assertion.", "premises": "Recorded premises.",
                                          "evidence": "This is the reviewed explanation."}]
                issues.append(issue)
        projection["issues"] = issues
        value = report.render_report(projection)
        markdown = report.render_markdown(projection)
        for issue, (_, _, lifecycle, role) in zip(issues, cases):
            with self.subTest(rendered_role=role, lifecycle=lifecycle):
                path_html = value.split('id="' + issue["anchor"] + '-path"', 1)[1].split('<details class="issue-path"', 1)[0].split('<h2 id="results"', 1)[0]
                detail_html = value.split('id="' + issue["anchor"] + '"', 1)[1].split('<details class="issue"', 1)[0].split('<details id="source-evidence"', 1)[0]
                md_detail = markdown.split('### ' + issue["id"] + ' ', 1)[1].split('\n### I-', 1)[0].split('## Exact source evidence', 1)[0]
                self.assertIn('Inspect ' + role.lower(), path_html)
                if role == "Failed inference":
                    self.assertIn("Why this inference fails and how to repair it", path_html)
                    self.assertIn("Why the step fails", detail_html)
                else:
                    for section in (path_html, detail_html, md_detail):
                        self.assertNotIn("Failed inference", section)
                        self.assertNotIn("Why this inference fails", section)
                        self.assertNotIn("Why the step fails", section)
                        self.assertNotIn("Original failure", section)
                if lifecycle == "resolved":
                    self.assertIn("historical", path_html)
                    self.assertIn("Recorded resolution", detail_html)
                else:
                    self.assertIn(role + ' · ', path_html)
                    self.assertIn(role + ' · ', detail_html)

    def test_reader_labels_use_locations_and_keep_ids_in_technical_evidence(self):
        projection = self.project()
        self.assertEqual(["Lemma · paper.tex, lines 6 to 11", "Theorem · paper.tex, lines 20 to 24"],
                         [result["title"] for result in projection["results"]])
        self.assertTrue(all("C001" not in node["label"] and "S005" not in node["label"] and "/hypotheses/" not in node["label"]
                            for node in projection["graph"]["nodes"]))
        value = report.render_report(projection)
        self.assertNotIn('Source excerpt 1', value)
        self.assertIn('Manuscript label: <code>lem:growing-max</code>', value)
        self.assertIn('Finding technical records', value)
        self.assertIn('C001', value)
        self.assertIn('/hypotheses/0', value)
        self.assertTrue('class="graph-edge broken"' in value)

    def test_titles_require_an_exact_unambiguous_locked_opening(self):
        source = {"status": "locked", "quote": r"\begin{lemma}[Uniform tail control]\label{lem:x}"}
        self.assertEqual("Uniform tail control", report._manuscript_title("lemma", [source]))
        self.assertIsNone(report._manuscript_title("lemma", [{**source, "status": "unavailable"}]))
        self.assertIsNone(report._manuscript_title("lemma", [source, source]))
        self.assertIsNone(report._manuscript_title("lemma", [{**source, "quote": r"\begin{lemma}\label{lem:x}"}]))
        self.assertEqual("Uniform tail control", report._manuscript_title("lem", [{**source, "quote": r"\begin{restatable}[Uniform tail control]{lem}{uniformtail}"}]))

    def test_literal_numbered_heading_requires_locked_unambiguous_source(self):
        source = {"status": "locked", "quote": "Lemma 2.2. Let $k<d$. Then"}
        self.assertEqual("Lemma 2.2", report._printed_result_label("lemma", [source]))
        self.assertIsNone(report._printed_result_label("theorem", [source]))
        self.assertIsNone(report._printed_result_label("lemma", [{**source, "status": "unavailable"}]))
        self.assertIsNone(report._printed_result_label("lemma", [source, source]))
        self.assertIsNone(report._printed_result_label("lemma", [{**source, "quote": "We apply Lemma 2.2. to this case."}]))
        self.assertIsNone(report._printed_result_label("lemma", [{**source, "quote": r"\begin{lemma}\label{lem:2.2}"}]))

    def caption_fixture(self, numbered=False, semantic_kind=None):
        """Keep the validator's judgments fixed while exercising real locked source."""
        source = self.root / "audit/00_sources/project/caption.tex"
        opening = "Theorem 2.2. Let $x>0$." if numbered else r"\begin{theorem*}\label{main}"
        source.write_text("\n".join((opening, "$x^2>0$.", "$x+x>0$.",
                                    r"\end{theorem*}" if not numbered else "End of the statement.",
                                    r"\begin{proof}Both follow directly.\end{proof}",
                                    "Equality in the bound holds exactly when $x=0$.")) + "\n", encoding="utf-8")
        ledger_path = self.root / "audit/04_local_checks/lem-growing-max.ledger.json"
        inventory_path = self.root / "audit/01_index/theorem_inventory.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        item = inventory["units"][0]
        item.update(environment="theorem" if numbered else "theorem*", semantic_kind=semantic_kind,
                    statement={"file": "caption.tex", "start_line": 1, "end_line": 4})

        def span(start, end):
            return pc.locked_span_projection({"file": "../00_sources/project/caption.tex",
                                              "start_line": start, "end_line": end}, ledger_path.parent)

        ledger["obligation"]["statement_spans"] = [span(1, 4), span(6, 6)]
        original = copy.deepcopy(ledger["obligation"]["conclusions"][0])
        ledger["obligation"]["conclusions"] = [
            {**original, "id": "C001", "claim": "$x^2>0$", "source_spans": [span(2, 2)],
             "reader_description": "First bound, equation (1), PDF page 1"},
            {**original, "id": "C002", "claim": "$x+x>0$", "source_spans": [span(3, 3)],
             "reader_description": "Second consequence"},
            {**original, "id": "C003", "claim": "Equality holds exactly when $x=0$.", "source_spans": [span(6, 6)],
             "reader_description": "Post-proof equality characterization, PDF page 2"},
        ]
        original_load, original_check = pc.load_json_object, pc.check_ledger_data
        _, summary = original_check(ledger_path, False)

        def load_record(path, label):
            replacement = {ledger_path: ledger, inventory_path: inventory}.get(Path(path))
            return (copy.deepcopy(replacement), []) if replacement else original_load(path, label)

        before = {path: path.read_bytes() for path in (source, ledger_path, inventory_path)}
        with patch.object(pc, "load_json_object", side_effect=load_record), \
             patch.object(pc, "check_ledger_data", side_effect=lambda path, final: ([], copy.deepcopy(summary)) if Path(path) == ledger_path else original_check(path, final)):
            projection = self.project()
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        return projection, [row for row in projection["results"] if row["unit_id"] == "lem:growing-max"]

    def test_unnumbered_theorem_keeps_formal_and_post_proof_conclusions_distinct(self):
        projection, rows = self.caption_fixture()
        _, mapped_rows = self.caption_fixture(semantic_kind="theorem")
        self.assertEqual([row["title"] for row in rows], [row["title"] for row in mapped_rows])
        self.assertEqual(["unnumbered theorem", "unnumbered theorem", "conclusion"], [row["kind"] for row in rows])
        self.assertTrue(all(row["source_environment"] == "theorem*" for row in rows))
        self.assertEqual("Unnumbered theorem · First bound, equation (1), PDF page 1 · caption.tex, line 2", rows[0]["title"])
        self.assertEqual("Conclusion · Post-proof equality characterization, PDF page 2 · caption.tex, line 6", rows[2]["title"])
        self.assertTrue(all(row["printed_label"] is None and row["paper_location"] is None for row in rows))
        for value in (report.render_report(projection), report.render_markdown(projection)):
            self.assertIn(rows[0]["title"], value)
            self.assertIn(rows[2]["title"], value)
            self.assertNotIn("Theorem*", value)
        html = report.render_report(projection)
        self.assertIn("Source environment", html)
        self.assertIn("theorem*", html)
        self.assertEqual([], report.validate_html(html, projection))

    def test_numbered_heading_is_not_inherited_by_separate_post_proof_assertion(self):
        projection, rows = self.caption_fixture(numbered=True)
        self.assertEqual(["Theorem 2.2", "Theorem 2.2", None], [row["printed_label"] for row in rows])
        self.assertTrue(rows[0]["title"].startswith("Theorem 2.2 · "))
        self.assertTrue(rows[2]["title"].startswith("Conclusion · Post-proof equality characterization"))
        self.assertEqual([], report.validate_html(report.render_report(projection), projection))

    def test_separate_assertion_label_requires_locked_disjoint_source_ranges(self):
        statement = {"file": "paper.tex", "start_line": 60, "end_line": 75}
        conclusion = {"file": "paper.tex", "start_line": 105, "end_line": 105, "status": "locked"}
        self.assertTrue(report._separate_assertion(statement, [conclusion]))
        self.assertFalse(report._separate_assertion(statement, [{**conclusion, "status": "unavailable"}]))
        self.assertFalse(report._separate_assertion(statement, [{**conclusion, "start_line": 65}]))
        self.assertFalse(report._separate_assertion({}, [conclusion]))
        self.assertFalse(report._separate_assertion(statement, []))

    def test_pdf_page_map_is_literal_ordered_and_does_not_guess_missing_pages(self):
        text = "[PDF page 1; journal page 60]\nFirst page.\n[PDF page 2; journal page 61]\nSecond page."
        self.assertEqual("PDF page 1 (journal page 60)", report._pdf_page_location(text, 2, 2))
        self.assertEqual("PDF page 2 (journal page 61)", report._pdf_page_location(text, 4, 4))
        self.assertEqual("PDF pages 1 to 2", report._pdf_page_location(text, 2, 4))
        self.assertIsNone(report._pdf_page_location(text.replace("page 2;", "page 3;"), 4, 4))
        self.assertIsNone(report._pdf_page_location("Page 1\nUnmapped source.", 2, 2))
        self.assertIsNone(report._pdf_page_location("Unmapped source.\n[PDF page 1]", 1, 1))

    def test_coincident_locators_use_exact_claims_without_invented_numbers(self):
        rows = [{"title": "Lemma 2.2 · PDF page 3", "claim": r"$p\le B$"},
                {"title": "Lemma 2.2 · PDF page 3", "claim": r"$B\le e^{-t}$"}]
        before = copy.deepcopy(rows)
        report._distinguish_result_titles(rows)
        self.assertNotEqual(rows[0]["title"], rows[1]["title"])
        for original, result in zip(before, rows):
            self.assertEqual(original["claim"], result["claim"])
            self.assertTrue(result["title"].endswith(original["claim"]))
        value = self.project()
        for result, row in zip(value["results"], rows):
            result["title"] = row["title"]
        rendered = report.render_report(value)
        self.assertNotIn('class="math-fallback"', rendered)
        self.assertIn(report._rich(rows[0]["title"]), rendered)
        self.assertEqual([], report.validate_html(rendered, value))

    def test_technical_disclosures_start_closed_and_keep_evidence_accessible(self):
        value = report.render_report(self.project())
        self.assertNotIn('class="technical" open', value)
        self.assertNotIn('class="original-claim" open', value)
        self.assertIn('Manuscript label: <code>lem:growing-max</code>', value)
        self.assertIn('printState.forEach(([d])=>d.open=true)', value)

    def test_reviewed_reader_description_distinguishes_coincident_source_spans(self):
        ledger_path = self.root / "audit/04_local_checks/lem-growing-max.ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        first = ledger["obligation"]["conclusions"][0]
        first["reader_description"] = "Uniform probability bound"
        second = copy.deepcopy(first)
        second.update(id="C002", reader_description="Rate comparison", claim=r"$a_n\le b_n$")
        ledger["obligation"]["conclusions"].append(second)
        original_load, original_check = pc.load_json_object, pc.check_ledger_data
        _, summary = original_check(ledger_path, False)
        with patch.object(pc, "load_json_object", side_effect=lambda path, label: (copy.deepcopy(ledger), []) if Path(path) == ledger_path else original_load(path, label)), \
             patch.object(pc, "check_ledger_data", side_effect=lambda path, final: ([], copy.deepcopy(summary)) if Path(path) == ledger_path else original_check(path, final)):
            projection = self.project()
        rows = [row for row in projection["results"] if row["unit_id"] == "lem:growing-max"]
        self.assertEqual(first["claim"], rows[0]["claim"])
        self.assertEqual(second["claim"], rows[1]["claim"])
        self.assertIn("Uniform probability bound", rows[0]["title"])
        self.assertIn("Rate comparison", rows[1]["title"])
        self.assertEqual(rows[0]["location"], rows[1]["location"])
        self.assertNotEqual(rows[0]["title"], rows[1]["title"])

    def graph_with_supplement(self, conditions):
        # Presentation input represents already derived validator judgments.
        # Mathematical acceptance is exercised by the core support tests.
        projection = self.project()
        ledgers, summaries = {}, {}
        for path in (self.root / "audit/04_local_checks").glob("*.ledger.json"):
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledgers[ledger["unit_id"]] = (path, ledger)
            _, summaries[ledger["unit_id"]] = pc.check_ledger_data(path, False)
        result = projection["results"][0]
        supplement = {"support": result["support"], "sha256": "a" * 64,
                      "claim": result["claim"], "extra_conditions": conditions,
                      "status": "conditional" if conditions else "verified", "acceptance": "accepted",
                      "source_ids": result["support_source_ids"], "reason": "A separately checked supplemental argument."}
        result["statement_support"] = supplement
        edge = projection["dependency_edges"][0]
        edge.update(statement_support=supplement, effective_status="verified",
                    statement_support_conditions=[{"condition": condition, "status": "satisfied", "evidence": "Checked at this application."} for condition in conditions])
        if not conditions:
            result["judgments"].update(argument_status="gap", statement_status="established")
        projection["graph"] = report._proof_graph(pc, projection["results"], ledgers, summaries, {}, lambda *args: None, [], projection["dependency_edges"])
        return projection, result

    def test_restricted_supplement_is_a_separate_form_used_by_the_selected_edge(self):
        projection, result = self.graph_with_supplement([r"$m_n=m$ for a fixed finite $m$."])
        graph = projection["graph"]
        restricted = next(node for node in graph["nodes"] if node["kind"] == "restricted statement")
        self.assertEqual("refuted", result["judgments"]["statement_status"])
        self.assertEqual("conditional", restricted["status"])
        self.assertFalse(any(edge["from"] == restricted["id"] and edge["to"] == result["id"] for edge in graph["edges"]))
        use = next(edge for edge in graph["edges"] if edge.get("use_id"))
        self.assertEqual((restricted["id"], "verified"), (use["from"], use["status"]))
        value = report.render_report(projection)
        self.assertIn(report._rich(restricted["conditions"][0]), value)
        self.assertIn("This use selects the supplemental form.", value)
        self.assertEqual([], report.validate_html(value, projection))

    def test_full_supplement_preserves_the_written_gap_and_unchanged_statement(self):
        projection, result = self.graph_with_supplement([])
        graph = projection["graph"]
        written = next(node for node in graph["nodes"] if node["kind"] == "argument" and node["label"].startswith("Conclusion step") and node["technical_reference"]["unit_id"] == result["unit_id"])
        support = next(node for node in graph["nodes"] if node["kind"] == "supplemented statement")
        self.assertEqual("gap", written["status"])
        self.assertEqual("verified", support["status"])
        self.assertEqual("established", result["judgments"]["statement_status"])
        self.assertTrue(any(edge["from"] == support["id"] and edge["to"] == result["id"] for edge in graph["edges"]))
        value = report.render_report(projection)
        self.assertIn("The written argument retains its recorded judgment.", value)
        self.assertIn("This accepted supplement addresses the unchanged statement", value)
        self.assertEqual([], report.validate_html(value, projection))

    def test_two_unnumbered_conclusions_use_distinct_physical_ranges(self):
        ledger_path = self.root / "audit/04_local_checks/lem-growing-max.ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        second = copy.deepcopy(ledger["obligation"]["conclusions"][0])
        second.update(id="C002", claim="A separately recorded conclusion.", source_spans=copy.deepcopy(ledger["obligation"]["statement_spans"]))
        ledger["obligation"]["conclusions"].append(second)
        original_load, original_check = pc.load_json_object, pc.check_ledger_data
        _, summary = original_check(ledger_path, False)

        def load_record(path, label):
            return (copy.deepcopy(ledger), []) if Path(path) == ledger_path else original_load(path, label)

        def check_record(path, final):
            return ([], copy.deepcopy(summary)) if Path(path) == ledger_path else original_check(path, final)

        with patch.object(pc, "load_json_object", side_effect=load_record), patch.object(pc, "check_ledger_data", side_effect=check_record):
            projection = self.project()
        conclusions = [row for row in projection["results"] if row["unit_id"] == "lem:growing-max"]
        self.assertEqual(2, len(conclusions))
        self.assertEqual(["Lemma · paper.tex, lines 9 to 10", "Lemma · paper.tex, lines 6 to 11"], [row["title"] for row in conclusions])
        self.assertNotEqual(conclusions[0]["id"], conclusions[1]["id"])

    def test_adjacent_unconsumed_step_never_creates_a_path_edge(self):
        projection = self.project()
        issue = projection["issues"][0]
        ledgers, summaries = {}, {}
        for path in (self.root / "audit/04_local_checks").glob("*.ledger.json"):
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledgers[ledger["unit_id"]] = (path, ledger)
            _, summaries[ledger["unit_id"]] = pc.check_ledger_data(path, False)
        lemma = ledgers["lem:growing-max"][1]
        failure_step = next(step for step in lemma["steps"] if step["id"] == "S004")
        failure_step["inference"]["moves"][0]["premise_ids"].remove("P001")
        path = report._issue_proof_path(pc, issue, projection["results"], ledgers, summaries, {},
                                        projection["dependency_edges"], lambda *args: None, {})
        self.assertFalse(any(node["step_id"] == "S003" and node["unit_id"] == "lem:growing-max" for node in path["nodes"]))
        self.assertTrue(any(node["step_id"] == "S004" for node in path["nodes"]))

    def test_issue_path_follows_selected_supplement_instead_of_broad_failed_route(self):
        projection = self.project()
        ledgers, summaries = {}, {}
        for path in (self.root / "audit/04_local_checks").glob("*.ledger.json"):
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledgers[ledger["unit_id"]] = (path, ledger)
            _, summaries[ledger["unit_id"]] = pc.check_ledger_data(path, False)
        edge = projection["dependency_edges"][0]
        edge["statement_support"] = {"support": {"step_id": "S003", "move_id": "M001"}}
        selected_path = report._issue_proof_path(pc, projection["issues"][0], projection["results"], ledgers, summaries, {},
                                                 projection["dependency_edges"], lambda *args: None, {})
        self.assertTrue(any(node["role"] == "Failed inference" for node in selected_path["nodes"]))
        self.assertFalse(any(node["unit_id"] == "thm:main" for node in selected_path["nodes"]))

    def test_unavailable_or_historical_path_never_substitutes_current_steps(self):
        projection = self.project()
        issue = copy.deepcopy(projection["issues"][0])
        unavailable = report._issue_proof_path(pc, issue, projection["results"], {}, {}, {}, [], lambda *args: None, {})
        self.assertEqual({"status": "unavailable", "nodes": [], "edges": []}, unavailable)
        issue["status"] = "resolved"
        historical = report._issue_proof_path(pc, issue, projection["results"], {}, {}, {}, [], lambda *args: self.fail("Current steps read for historical issue"), {})
        self.assertEqual({"status": "historical", "nodes": [], "edges": []}, historical)


if __name__ == "__main__":
    unittest.main()
