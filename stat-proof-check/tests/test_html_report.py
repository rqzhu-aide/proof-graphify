from __future__ import annotations

import copy
import argparse
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pc = load("proofcheck")
report = load("proofcheck_report")
REFERENCE = ROOT.parent / "tests/fixtures/reference-audit/proofcheck-audit"


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip -= 1

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


class HtmlReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "audit with spaces"
        shutil.copytree(REFERENCE, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, *, final=False, context=None):
        return report.build_report_projection(
            pc, self.root, final=final, finalized_at="2026-09-04T12:00:00Z",
            report_context=context,
        )

    def test_source_backed_latex_reading_preserves_normalized_and_raw_evidence(self):
        projection = self.project(final=True)
        original = copy.deepcopy(projection)
        value = report.render_report(projection)
        self.assertEqual(original, projection)
        self.assertIn('Stated conclusion, typeset from the linked manuscript excerpt:', value)
        self.assertIn('Normalized audit wording', value)
        self.assertIn('<math ', value)
        self.assertIn('<mover', value)
        self.assertIn('encoding="application/x-tex"', value)
        self.assertNotIn('class="math-fallback"', value)
        for result in projection['results']:
            self.assertIn(result['claim'], self.visible(value))
        for source in projection['sources']:
            if source.get('quote') and source['start_line'] is not None:
                numbered = '\n'.join(f"{source['start_line'] + i:>4}  {line}"
                                     for i, line in enumerate(source['quote'].splitlines()))
                self.assertIn('<pre class="source">' + report._e(numbered) + '</pre>', value)
        self.assertEqual([], report.validate_html(value, projection))

    def test_delimited_claims_and_prose_are_typeset_without_source_guessing(self):
        projection = self.project(final=True)
        projection['results'][0]['claim'] = r'$\frac{1}{n}\sum_{j=1}^n X_j \to \mu$'
        projection['results'][0]['conditions'][0]['value'] = r'For $n\ge1$, assume $\mathbb{E}X_n=0$.'
        projection['report_context']['notes'] = [r'Compare $a^2$ with $\frac{b}{c}$.']
        value = report.render_report(projection)
        self.assertIn('<mfrac>', value)
        self.assertIn(report._rich(projection['results'][0]['claim']), value)
        self.assertIn(report._rich(projection['report_context']['notes'][0]), value)
        self.assertEqual([], report.validate_html(value, projection))

    def test_converter_configuration_is_bound_to_renderer_identity(self):
        release = pc.report_module('proofcheck_release')
        before = release.renderer_identity(pc)
        engine = pc.report_renderer().math_renderer()
        info = engine.renderer_info()
        with patch.object(engine, 'renderer_info', return_value={**info, 'version': 'changed'}):
            self.assertNotEqual(before, release.renderer_identity(pc))

    def test_paired_doubled_source_quote_keeps_the_normalized_claim_primary(self):
        projection = self.project(final=True)
        result = projection['results'][0]
        claim, quote = "The normalized conclusion remains primary.", r"\\(x_n \to 0\\)"
        result['claim'] = claim
        sources = {source['id']: source for source in projection['sources']}
        for key in result['conclusion_source_ids']:
            sources[key]['quote'] = quote
        source = sources[result['conclusion_source_ids'][0]]
        reading = report._claim_reading(claim, [source['id']], sources)
        self.assertEqual('<div class="claim-text">' + claim + '</div>', reading)
        value = report.render_report(projection)
        result_section = value.split('id="' + result['id'] + '">', 1)[1].split(
            '<p class="source-label">Record availability:', 1)[0]
        self.assertIn('<div class="claim-text">' + claim + '</div>', result_section)
        self.assertNotIn('Normalized audit wording', result_section)
        evidence = value.split('<details id="' + source['id'] + '">', 1)[1].split('</details>', 1)[0]
        self.assertNotIn('typeset-source', evidence)
        numbered = '\n'.join(f"{source['start_line'] + i:>4}  {line}"
                             for i, line in enumerate(quote.splitlines()))
        self.assertIn('<pre class="source">' + report._e(numbered) + '</pre>', evidence)

    def test_paired_doubled_claim_keeps_manuscript_math_primary_and_claim_disclosed(self):
        projection = self.project(final=True)
        result = projection['results'][0]
        claim = r"\\(normalized_x_n \to 0\\)"
        result['claim'] = claim
        sources = {source['id']: source for source in projection['sources']}
        source = sources[result['conclusion_source_ids'][0]]
        source['quote'] = r"The manuscript states $x_n \to 0$."
        reading = report._claim_reading(claim, [source['id']], sources)
        self.assertIn('class="claim-text source-reading"', reading)
        self.assertIn('Normalized audit wording', reading)
        self.assertIn('<code>' + report._e(claim) + '</code>', reading)
        value = report.render_report(projection)
        result_section = value.split('id="' + result['id'] + '">', 1)[1].split(
            '<p class="source-label">Record availability:', 1)[0]
        self.assertIn('Stated conclusion, typeset from the linked manuscript excerpt:', result_section)
        self.assertIn('Normalized audit wording</summary><p>' + report._e(claim), result_section)
        evidence = value.split('<details id="' + source['id'] + '">', 1)[1].split('</details>', 1)[0]
        self.assertIn('typeset-source', evidence)
        self.assertIn(report._e(source['quote']), evidence)

    def edit(self, relative, change):
        path = self.root / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def visible(self, value):
        parser = VisibleText()
        parser.feed(value)
        return " ".join(parser.parts)

    def test_reference_preserves_both_direct_refutations_and_failed_use(self):
        projection = self.project(final=True)
        results = {r["unit_id"]: r for r in projection["results"]}
        self.assertEqual("refuted", results["lem:growing-max"]["judgments"]["statement_status"])
        self.assertEqual("refuted", results["thm:main"]["judgments"]["statement_status"])
        self.assertEqual("insufficient", results["lem:growing-max"]["judgments"]["use_site_sufficiency"])
        edge = projection["dependency_edges"][0]
        self.assertEqual(("incorrect", "passed", "incorrect"), tuple(edge[k] for k in ("source_status", "applicability_status", "effective_status")))
        self.assertEqual([], report.validate_html(report.render_report(projection), projection))

    def test_all_repairs_costs_and_counterexample_are_visible_without_script(self):
        projection = self.project(final=True)
        text = self.visible(report.render_report(projection))
        for issue in projection["issues"]:
            for repair in issue["repairs"]:
                self.assertIn(repair["proposal"], text)
                self.assertIn(repair["scientific_cost"], text)
                self.assertIn("Candidate", text)
            for failure in issue["failures"]:
                self.assertIn(failure["evidence"], text)
        self.assertIn("Bernoulli", text)
        self.assertIn(report.ASSURANCE, text)
        self.assertIn("Fresh context, same model", text)
        self.assertEqual(2, len(projection["issues"][0]["repairs"]))

    def test_source_excerpts_are_exact_and_links_remain_portable(self):
        projection = self.project()
        for source in projection["sources"]:
            if source["start_line"] is not None and source["quote"] is not None:
                path = self.root / source["file"]
                text = "\n".join(path.read_text(encoding="utf-8").splitlines()[source["start_line"] - 1:source["end_line"]])
                self.assertEqual(text, source["quote"])
                self.assertEqual(pc.sha256_text(text), source["sha256"])
        value = report.render_report(projection)
        self.assertNotIn(str(self.root), value)
        source = next(item for item in projection["sources"] if item["file"] == "audit/00_sources/project/paper.tex")
        report_parent = (self.root / pc.preferred_report_path(pc.load_audit_manifest(self.root)[1])).parent
        self.assertEqual((self.root / source["file"]).resolve(), (report_parent / unquote(source["bundle_href"])).resolve())
        self.assertTrue('href="' + source["bundle_href"] + '"' in value)
        moved = Path(self.tmp.name) / "moved unicode \u03bb"
        shutil.copytree(self.root, moved)
        after = report.build_report_projection(pc, moved)
        self.assertEqual(projection, after)

    def test_missing_ledger_counts_expected_inventory_and_does_not_claim_clean(self):
        (self.root / "audit/04_local_checks/thm-main.ledger.json").unlink()
        projection = self.project()
        self.assertEqual(2, projection["coverage"]["expected_units"])
        self.assertEqual(["thm:main"], projection["coverage"]["missing_units"])
        self.assertIsNone(projection["coverage"]["expected_conclusions"])
        missing = next(r for r in projection["results"] if r["unit_id"] == "thm:main")
        self.assertEqual("missing", missing["availability"])
        self.assertEqual("not_checked", missing["judgments"]["statement_status"])
        self.assertEqual("NONFINAL", projection["release"]["status"])
        self.assertIn("no overall judgment has been released", projection["summary"]["overall_judgment"])
        self.assertIn("unavailable", projection["summary"]["overall_judgment"])
        with self.assertRaises(ValueError):
            self.project(final=True)

    def test_unreviewed_scope_never_invents_expected_denominator(self):
        self.edit("AUDIT_MANIFEST.json", lambda m: m["audit_scope"].update(status="unreviewed", in_scope_units=[]))
        projection = self.project()
        self.assertIsNone(projection["coverage"]["expected_units"])
        self.assertEqual(2, len(projection["results"]))
        self.assertIn("unresolved", report.render_report(projection))

    def test_malformed_ledger_does_not_supply_recorded_judgment(self):
        self.edit("audit/04_local_checks/lem-growing-max.ledger.json", lambda m: m["review"].update(statement_status="fabricated_success"))
        projection = self.project()
        result = next(r for r in projection["results"] if r["unit_id"] == "lem:growing-max")
        self.assertEqual("invalid", result["availability"])
        self.assertEqual("not_checked", result["judgments"]["statement_status"])
        self.assertNotIn("fabricated_success", result["judgments"].values())

    def test_source_drift_cannot_reuse_current_status(self):
        source = self.root / "audit/00_sources/project/paper.tex"
        source.write_text(source.read_text(encoding="utf-8") + "% changed\n", encoding="utf-8")
        projection = self.project()
        self.assertEqual(0, projection["coverage"]["checked_units"])
        self.assertEqual(2, len(projection["coverage"]["invalid_units"]))
        self.assertTrue(projection["diagnostics"])
        with self.assertRaises(ValueError):
            self.project(final=True)

    def test_graph_uses_exact_conclusion_support_and_retains_kind(self):
        projection = self.project(final=True)
        nodes = {node["id"]: node for node in projection["graph"]["nodes"]}
        lemma = next(node for node in nodes.values() if node["kind"] == "lemma")
        theorem = next(node for node in nodes.values() if node["kind"] == "theorem")
        self.assertEqual("refuted", lemma["status"])
        self.assertEqual("refuted", theorem["status"])
        self.assertEqual("Refuted", theorem["status_label"])
        uses = [edge for edge in projection["graph"]["edges"] if "use_id" in edge]
        self.assertEqual(["D001"], [edge["use_id"] for edge in uses])
        self.assertEqual(lemma["id"], uses[0]["from"])
        argument = nodes[uses[0]["to"]]
        self.assertEqual("argument", argument["kind"])
        self.assertTrue(any(edge["from"] == argument["id"] and edge["to"] == theorem["id"] for edge in projection["graph"]["edges"]))
        pointers = [edge["pointer"] for edge in projection["graph"]["edges"] if edge["unit_id"] == "thm:main" and "pointer" in edge]
        self.assertEqual(["/hypotheses/1"], pointers)
        self.assertIn("jointly", projection["graph"]["convention"])

    def test_explicit_counterexamples_target_both_named_conclusions(self):
        projection = self.project(final=True)
        nodes = {node["id"]: node for node in projection["graph"]["nodes"]}
        refutations = [edge for edge in projection["graph"]["edges"] if edge["kind"] == "refutation"]
        self.assertEqual(2, len(refutations))
        self.assertEqual({"lemma", "theorem"}, {nodes[edge["to"]]["kind"] for edge in refutations})
        for edge in refutations:
            self.assertEqual("counterexample", nodes[edge["from"]]["kind"])
            self.assertEqual("I-001", edge["issue_id"])
        self.assertIn("estimator", next(nodes[e["from"]]["claim"] for e in refutations if nodes[e["to"]]["kind"] == "theorem"))
        value = report.render_report(projection)
        # The default manuscript overview summarizes attention; exact-target
        # refutation arrows remain in Detailed proof and its preserved data.
        self.assertIn('class="graph-edge refutation"', report._svg(projection["graph"]))
        self.assertTrue(all(group["assessment_counts"]["refuted"] == 1 for group in projection["result_groups"]))
        self.assertIn("Dashed red arrows show explicit refutation evidence", value)
        self.assertIn("Refutation evidence</h3>", value)
        self.assertEqual([], report.validate_html(value, projection))
        self.edit("audit/06_reports/ISSUE_LOG.json", lambda value: value["issues"][0].update(invalidation_kind="argument_gap"))
        self.assertFalse(any(edge["kind"] == "refutation" for edge in self.project()["graph"]["edges"]))

    def test_visible_tamper_rejected_even_when_payload_unchanged(self):
        projection = self.project(final=True)
        value = report.render_report(projection)
        target = '<span class="badge defect">Refuted</span>'
        self.assertIn(target, value)
        tampered = value.replace(target, '<span class="badge checked">Established</span>', 1)
        self.assertNotEqual(value, tampered)
        self.assertTrue(report.validate_html(tampered, projection))

    def test_payload_and_manuscript_text_cannot_inject_markup(self):
        projection = self.project(context={"notes": ["</script><script>alert('x')</script>", "<img src=https://example.test/x>"]})
        value = report.render_report(projection)
        self.assertIn("&lt;img", value)
        self.assertNotIn("<script>alert", value)
        self.assertEqual([], report.validate_html(value, projection))

    def test_finalization_metadata_and_output_hashes_do_not_change_projection(self):
        before = self.project(final=True)
        def mutate(m):
            m["report_release"] = {"projection_sha256": "f" * 64, "finalized_at": "2099-01-01T00:00:00Z"}
            m["completion"]["final_report_ready"] = False
            m["report_contract"]["renderer_sha256"] = "f" * 64
        self.edit("AUDIT_MANIFEST.json", mutate)
        self.assertEqual(before, self.project(final=True))

    def test_staged_manifest_is_used_without_mutation_or_output_metadata_cycle(self):
        manifest_path = self.root / "AUDIT_MANIFEST.json"
        original_bytes = manifest_path.read_bytes()
        manifest = json.loads(original_bytes)
        manifest["audit_scope"]["target_units"] = ["lem:growing-max"]
        manifest["report_context"] = {"title": "A staged report title"}
        manifest["report_deliverables"] = [{"id": "R001", "role": "user_facing_report",
            "path": "audit/06_reports/FINAL_REPORT.html", "issue_ids": [],
            "overall_verdict": "inconclusive", "sha256": "0" * 64}]
        before = copy.deepcopy(manifest)
        projection = report.build_report_projection(pc, self.root, manifest_override=manifest)
        self.assertEqual(["lem:growing-max"], projection["audit"]["target_units"])
        self.assertEqual("A staged report title", projection["report_context"]["title"])
        self.assertEqual(before, manifest)
        self.assertEqual(original_bytes, manifest_path.read_bytes())
        manifest["report_deliverables"][0].update(issue_ids=["I-001"], overall_verdict="defects_found", sha256="f" * 64)
        self.assertEqual(projection, report.build_report_projection(pc, self.root, manifest_override=manifest))

    def test_timestamp_has_no_clock_dependency(self):
        before = self.project(final=True)
        self.assertEqual("2026-09-04T12:00:00Z", before["release"]["finalized_at"])
        self.assertIsNone(self.project()["release"]["finalized_at"])
        self.assertEqual(report.render_report(before), report.render_report(self.project(final=True)))

    def test_context_types_are_checked_and_legacy_prose_is_not_lost(self):
        for bad in ([], {"title": 42}, {"notes": "not a list"}, {"limitations": [None]}):
            with self.subTest(context=bad), self.assertRaises(ValueError):
                self.project(context=bad)
        context = {"Description of checked scope": "Only the named proof chain was reviewed.",
                   "Limits of certification": "Execution provenance was not checked.",
                   "Mathematical confidence": "High confidence in the explicit counterexample."}
        value = report.render_report(self.project(context=context))
        for statement in context.values():
            self.assertIn(statement, self.visible(value))

    def test_author_context_cannot_replace_canonical_scope_or_aliases(self):
        baseline = self.project(final=True)
        context = {"Depth": "full-paper", "Target_units": ["fake:all"],
                   "In-scope units": ["fake:all"], "Source revision": "invented",
                   "notes": ["A multiline note\nwith a retained second line."]}
        projection = self.project(final=True, context=context)
        self.assertEqual(baseline["audit"], projection["audit"])
        html = report.render_report(projection)
        canonical = html.split('id="scope-records"', 1)[1].split('</details>', 1)[0]
        self.assertNotIn("fake:all", canonical)
        self.assertNotIn("invented", canonical)
        self.assertIn("Historical or additional prose", html)
        self.assertIn("fake:all", html.split('id="author-context"', 1)[1])
        markdown = report.render_markdown(projection)
        self.assertIn(report.ASSURANCE, markdown)
        self.assertIn("retained second line", markdown)

    def test_author_context_forbidden_assurance_is_rejected_separately(self):
        self.project(final=True)  # The baseline is otherwise valid.
        for text in ("The proof is formally verified.", "`The proof is formally verified.`",
                     "    The proof\nis formally verified."):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "unsupported formal-verification language"):
                self.project(final=True, context={"notes": [text]})

    def test_missing_internal_prerequisite_is_unavailable_not_external_or_verified(self):
        (self.root / "audit/04_local_checks/lem-growing-max.ledger.json").unlink()
        projection = self.project()
        inputs = [node for node in projection["graph"]["nodes"] if node["kind"] == "internal result"]
        self.assertEqual(1, len(inputs))
        self.assertEqual("Lemma · paper.tex, lines 6 to 11", inputs[0]["label"])
        self.assertEqual("not_checked", inputs[0]["status"])
        self.assertFalse(any(node["kind"] == "external result" for node in projection["graph"]["nodes"]))
        self.assertFalse(any(node["claim"].strip().lower() == "none" for node in projection["graph"]["nodes"] if node["status"] == "refutation_evidence"))

    def test_initial_reasoning_and_portable_artifact_links_are_per_conclusion(self):
        projection = self.project(final=True)
        seen = []
        for result in projection["results"]:
            check = result["initial_review"]
            self.assertEqual("recorded", check["status"])
            self.assertTrue(check["source_ids"])
            self.assertTrue(check["decisive_reason"])
            seen.append(check["decisive_reason"])
            for link in check["artifacts"]:
                self.assertTrue((self.root / link["artifact"]).is_file())
                report_parent = (self.root / pc.preferred_report_path(pc.load_audit_manifest(self.root)[1])).parent
                self.assertEqual((self.root / link["artifact"]).resolve(), (report_parent / unquote(link["href"])).resolve())
            self.assertIn(report._rich(check["decisive_reason"]), report.render_report(projection))
        self.assertNotEqual(*seen)
        self.assertIn("source_provenance", projection["audit"])

    def test_long_decisive_explanation_is_complete_in_issue_details(self):
        text = "The argument uses " + "a condition " * 45 + "that the source does not supply."
        self.edit("audit/06_reports/ISSUE_LOG.json", lambda value: value["issues"][0].update(summary=text))
        projection = self.project()
        self.assertNotIn("...", projection["summary"]["main_reason"])
        self.assertIn(text, self.visible(report.render_report(projection)))

    def test_external_contract_conditions_remain_available_in_nonfinal_view(self):
        self.edit("audit/03_dependencies/DEPENDENCY_REGISTRY.json", lambda r: r.update(external_results=[{
            "id": "ext:bounded", "exact_statement": "The external bound holds only for x in [-1, 1].",
            "assumptions": ["The argument x belongs to [-1, 1]."],
            "uses": [{"needed_form": "Apply the bound at x = 2.", "status": "unchecked"}],
        }]))
        projection = self.project()
        self.assertTrue(projection["diagnostics"])
        text = self.visible(report.render_report(projection))
        self.assertIn("The external bound holds only for x in [-1, 1].", text)
        self.assertIn("Apply the bound at x = 2.", text)

    def test_long_graph_chain_has_distinct_logical_layers(self):
        nodes = [{"id": f"result-{i}", "detail_id": f"result-{i}", "kind": "lemma",
                  "label": f"Lemma {i}", "claim": f"Conclusion {i}", "status": "established"} for i in range(8)]
        graph = {"nodes": nodes, "edges": [{"from": nodes[i]["id"], "to": nodes[i+1]["id"]} for i in range(7)]}
        view = report._presentation_module("graph")
        graph = view.prepare_graph(graph, [])
        page = view.initial_page(graph)
        page.update(node_ids=[n["id"] for n in nodes], edge_indices=list(range(7)))
        view._layout(graph, page)
        positions = [page["positions"][node["id"]][0] for node in nodes]
        self.assertEqual(sorted(set(positions)), positions)
        self.assertEqual(8, len(set(positions)))
        svg = report._svg(graph)
        self.assertEqual(8, svg.count('class="graph-node'))
        self.assertNotRegex(svg, r'<path class="graph-edge"[^>]+\sC')

    def test_fifty_results_keep_summary_bounded_and_complete_results_visible(self):
        names = [f"thm:synthetic-{index}" for index in range(50)]
        self.edit("AUDIT_MANIFEST.json", lambda m: m["audit_scope"].update(in_scope_units=names, target_units=names))
        self.edit("audit/01_index/theorem_inventory.json", lambda m: m.update(units=[
            {"id": name, "environment": "theorem", "proof_required": True,
             "statement_excerpt": f"Exact manuscript statement of {name}."} for name in names
        ]))
        projection = self.project()
        self.assertEqual(50, projection["coverage"]["expected_units"])
        self.assertEqual(50, len(projection["results"]))
        self.assertLessEqual(sum(len(value.split()) for value in projection["summary"].values()), 150)
        text = self.visible(report.render_report(projection))
        for result in projection["results"]:
            self.assertIn(result["title"], text)
            self.assertIn(result["claim"], text)
        html = report.render_report(projection)
        page = report._presentation_module("graph").initial_page(projection["graph"])
        self.assertEqual(1, len(page["node_ids"]))
        self.assertIn("50 nodes", report._presentation_module("graph").page_note(projection["graph"]))
        self.assertTrue('connections omitted on this page' in html)
        self.assertIn('id="graph-more"', html)

    def test_multiple_issues_preserve_every_recorded_repair(self):
        def duplicate(value):
            issue = copy.deepcopy(value["issues"][0])
            issue["id"] = "I-002"
            issue["summary"] = "A second distinct recorded finding."
            issue["suggested_changes"][0]["proposal"] = "The second issue has its own exact candidate repair."
            value["issues"].append(issue)
        self.edit("audit/06_reports/ISSUE_LOG.json", duplicate)
        projection = self.project()
        self.assertEqual(2, len(projection["issues"]))
        self.assertEqual(4, sum(len(issue["repairs"]) for issue in projection["issues"]))
        text = self.visible(report.render_report(projection))
        self.assertIn("The second issue has its own exact candidate repair.", text)
        self.assertEqual([], report.validate_html(report.render_report(projection), projection))

    def test_fresh_scaffold_renders_without_any_ledger(self):
        source = Path(self.tmp.name) / "fresh.tex"
        source.write_text("\\begin{lemma}\\label{lem:fresh}\nFor every real x, x=x.\n\\end{lemma}\n\\begin{proof}\nReflexivity.\n\\end{proof}\n", encoding="utf-8")
        destination = Path(self.tmp.name) / "fresh audit"
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_scaffold(argparse.Namespace(paper=source, output=destination))
        projection = report.build_report_projection(pc, destination)
        self.assertEqual("NONFINAL", projection["release"]["status"])
        self.assertEqual(0, projection["coverage"]["checked_units"])
        self.assertIsNone(projection["coverage"]["expected_units"])
        self.assertTrue(projection["coverage"]["missing_units"])
        self.assertEqual([], report.validate_html(report.render_report(projection), projection))

    def test_print_and_no_javascript_preserve_complete_content(self):
        value = report.render_report(self.project(final=True))
        self.assertIn('class="result"', value)
        self.assertIn('open><summary>', value)
        self.assertIn("beforeprint", value)
        self.assertIn("printState.forEach(([d])=>d.open=true)", value)
        self.assertNotIn(".scope{display:none", value)
        self.assertIn("@media print", value)
        self.assertIn(report.ASSURANCE, self.visible(value))


class ReportMeaningTests(unittest.TestCase):
    """Small explicit canonical-record fixtures isolate display semantics."""

    def graph_fixture(self):
        results, ledgers = [], {}
        for index, (unit, kind, argument, statement) in enumerate((
            ("lem:failed", "lemma", "invalid", "refuted"),
            ("thm:unsupported", "theorem", "gap", "not_established"),
            ("thm:alternative", "theorem", "valid", "established"),
        ), 1):
            claim = "The same downstream claim." if index > 1 else "The prerequisite claim."
            support = {"step_id": "S001", "move_id": "M001"}
            results.append({"id": "r" + str(index), "unit_id": unit, "conclusion_id": "C001",
                            "kind": kind, "title": unit + "/C001", "claim": claim,
                            "judgments": {"argument_status": argument, "statement_status": statement},
                            "source_ids": [], "support": support, "support_reason": "Reason for " + unit,
                            "support_failure": {"kind": "counterexample", "issue_id": "I-001",
                                                "target": claim, "evidence": "At x=1 the prerequisite asserts 1=0."} if index == 1 else {}})
            premise = {"id": "P001", "origin": {"kind": "internal_result", "reference": "D001"}} if index == 2 else {"id": "P001", "origin": {"kind": "obligation", "reference": "/hypotheses/1"}}
            ledger = {"obligation": {"hypotheses": {"1": "The condition for " + unit}},
                      "steps": [{"id": "S001", "premise_uses": [premise],
                                 "inference": {"moves": [{"id": "M001", "premise_ids": ["P001"]}]}}],
                      "review": {"direct_dependencies": [{"use_id": "D001", "id": "lem:failed", "kind": "internal_result", "conclusion_id": "C001", "status": "verified", "needed_form": "The prerequisite claim."}] if index == 2 else []}}
            ledgers[unit] = (Path("fixture.ledger.json"), ledger)
        issues = [{"id": "I-001", "anchor": "issue-1", "invalidation_kind": "statement_refuted", "status": "open",
                   "contract_refs": [{"kind": "conclusion", "unit_id": "lem:failed", "conclusion_id": "C001"}, {"kind": "conclusion", "unit_id": "thm:unsupported", "conclusion_id": "C001"}],
                   "failures": [{"evidence": "none"}], "source_ids": []}]
        return results, ledgers, issues

    def graph(self, results, ledgers, issues):
        return report._proof_graph(pc, results, ledgers, {key: {} for key in ledgers}, {}, lambda *args: None, issues,
                                   [{"dependent_unit": "thm:unsupported", "use_id": "D001", "effective_status": "incorrect", "applicability_status": "passed"}])

    def test_historical_failed_proof_does_not_refute_unsupported_downstream_statement(self):
        results, ledgers, issues = self.graph_fixture()
        graph = self.graph(results, ledgers, issues)
        nodes = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual("not_established", nodes["r2"]["status"])
        self.assertEqual("Not established by this proof", nodes["r2"]["status_label"])
        self.assertEqual(["r1"], [edge["to"] for edge in graph["edges"] if edge["kind"] == "refutation"])
        failed_use = next(edge for edge in graph["edges"] if edge.get("use_id") == "D001")
        self.assertEqual("incorrect", failed_use["status"])
        self.assertEqual("argument", nodes[failed_use["to"]]["kind"])

    def test_separate_valid_route_is_not_merged_into_failed_route_for_same_claim(self):
        results, ledgers, issues = self.graph_fixture()
        graph = self.graph(results, ledgers, issues)
        nodes = {node["id"]: node for node in graph["nodes"]}
        routes = {edge["to"]: edge["from"] for edge in graph["edges"] if edge["to"] in {"r2", "r3"}}
        self.assertNotEqual(routes["r2"], routes["r3"])
        self.assertEqual("gap", nodes[routes["r2"]]["status"])
        self.assertEqual("valid", nodes[routes["r3"]]["status"])
        self.assertEqual("established", nodes["r3"]["status"])
        self.assertFalse(any(edge["from"] == "r1" and edge["to"] == routes["r3"] for edge in graph["edges"]))

    def test_two_conclusions_in_one_unit_keep_distinct_inputs_and_judgments(self):
        results, ledgers, issues = self.graph_fixture()
        first = ledgers.pop("thm:unsupported")[1]
        second = ledgers.pop("thm:alternative")[1]
        second["steps"][0]["id"] = "S002"
        first["steps"].extend(second["steps"])
        ledgers["thm:two"] = (Path("two.ledger.json"), first)
        for index, row in enumerate(results[1:], 1):
            row.update(unit_id="thm:two", conclusion_id=f"C00{index}", title=f"thm:two/C00{index}", claim=f"Distinct conclusion {index}.")
            row["support"]["step_id"] = f"S00{index}"
        graph = self.graph(results, ledgers, [])
        nodes = {node["id"]: node for node in graph["nodes"]}
        routes = {edge["to"]: edge["from"] for edge in graph["edges"] if edge["to"] in {"r2", "r3"}}
        self.assertEqual("gap", nodes[routes["r2"]]["status"])
        self.assertEqual("valid", nodes[routes["r3"]]["status"])
        self.assertTrue(any(edge["from"] == "r1" and edge["to"] == routes["r2"] for edge in graph["edges"]))
        self.assertFalse(any(edge["from"] == "r1" and edge["to"] == routes["r3"] for edge in graph["edges"]))

    def test_refutation_requires_substantive_evidence_bound_to_exact_target(self):
        results, ledgers, issues = self.graph_fixture()
        for mutation in ({"evidence": "none"}, {"target": "Another statement."}, {"issue_id": "I-999"}):
            modified = copy.deepcopy(results)
            modified[0]["support_failure"].update(mutation)
            self.assertFalse(any(edge["kind"] == "refutation" for edge in self.graph(modified, ledgers, issues)["edges"]))

    def test_effective_sufficiency_distinguishes_absence_unknown_and_adverse_evidence(self):
        edge = {"kind": "internal_result", "dependency_id": "lem:x", "dependency_conclusion_id": "C001",
                "applicability_status": "passed", "effective_status": "verified"}
        self.assertEqual("sufficient", pc.derive_use_site_sufficiency([edge], "lem:x", "C001"))
        self.assertEqual("not_applicable", pc.derive_use_site_sufficiency([edge], "lem:x", "C002"))
        for status, expected in (("incorrect", "insufficient"), ("gap", "insufficient"), ("unchecked", "not_checked"),
                                 ("stale", "not_checked"), ("unrecognized", "not_checked"), (None, "not_checked"),
                                 ("unclear", "unclear"), ("conditional", "conditional")):
            with self.subTest(status=status):
                self.assertEqual(expected, pc.derive_use_site_sufficiency([{**edge, "effective_status": status}], "lem:x", "C001"))
        del edge["effective_status"]
        self.assertEqual("not_checked", pc.derive_use_site_sufficiency([edge], "lem:x", "C001"))

    def test_resolved_lifecycle_exposes_actual_mapping_and_completed_rechecks(self):
        import test_proofcheck as fixtures
        fixture = fixtures.FinalizationTests()
        fixture.setUp()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                _, _, original = fixture.make_resolved_s1_lifecycle_audit()
            projection = report.build_report_projection(fixtures.proofcheck, fixture.audit, final=True)
            issue = next(row for row in projection["issues"] if row["id"] == original["id"])
            self.assertEqual(original["resolution"], issue["resolution"])
            self.assertEqual(original["current_resolution"], issue["current_resolution"])
            self.assertEqual(original["recheck_evidence"], issue["recheck_evidence"])
            html = report.render_report(projection)
            markdown = report.render_markdown(projection)
            self.assertIn("Finding before resolution", html)
            self.assertIn("This finding is historical", html)
            for text in (original["resolution"], original["current_resolution"]["mapping"], *original["recheck_evidence"]):
                self.assertIn(text, html)
                self.assertIn(text, markdown)
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
