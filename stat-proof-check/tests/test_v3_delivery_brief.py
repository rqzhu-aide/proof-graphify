from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import Fixture, edit, node_available
from paper_core import finalization, publish
from paper_core.errors import PublicationError


class DeliveryBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def freeze(self, *, independent=False, mode="focused", targets=None):
        fixture = Fixture(self.root / "audit").audit(independent_required=independent, mode=mode)
        if targets is not None:
            with fixture.open() as db:
                audit = db.head("audits", fixture.audit_id)
                fixture.apply(db, [edit("replace", "audits", audit.id,
                    dict(audit.body, targets=targets), audit.version)], mode="primary")
        fixture.primary()
        bundle = self.root / "frozen"
        with fixture.open() as db:
            finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
        return fixture, bundle

    def test_frozen_facts_persist_once_and_ignore_later_live_changes(self):
        fixture, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        expected = publish._delivery_brief(snapshot, frozen)
        with fixture.open() as db:
            paper = db.head("papers", fixture.paper_id)
            fixture.apply(db, [edit("replace", "papers", paper.id,
                dict(paper.body, title="Later title"), paper.version)])
        fixture.path.rename(fixture.path.with_suffix(".saved"))
        saved = {p.name: p.read_bytes() for p in bundle.iterdir()}
        output = self.root / "report.html"
        with mock.patch.object(finalization, "load_finalization", wraps=finalization.load_finalization) as load, \
             mock.patch.object(finalization, "derive_full", side_effect=AssertionError("extra assessment")), \
             mock.patch("paper_core.assessment.derive_full", side_effect=AssertionError("extra assessment")), \
             mock.patch("paper_core.projection.project", side_effect=AssertionError("extra projection")), \
             mock.patch("paper_core.storage.Database", side_effect=AssertionError("live database")), \
             mock.patch.object(publish, "Database", side_effect=AssertionError("live database")), \
             mock.patch.object(publish, "render_payload", return_value=(b"published report", {})), \
             mock.patch.object(publish, "_source_capture_notes", wraps=publish._source_capture_notes) as captures:
            result = publish.publish_frozen(bundle, output=output)
        self.assertEqual(1, load.call_count)
        self.assertEqual(1, captures.call_count)
        self.assertNotIn("delivery_brief", result)
        self.assertEqual(expected, result["receipt"]["delivery_brief"])
        self.assertEqual("Test paper", expected["title"])
        self.assertEqual(result["receipt"], json.loads(Path(result["build_receipt_path"]).read_text(encoding="utf-8")))
        self.assertEqual(saved, {p.name: p.read_bytes() for p in bundle.iterdir()})
        self.assertEqual(b"published report", output.read_bytes())

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_capture_notes_reach_visible_html_and_brief_without_changing_scientific_facts(self):
        _, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        projection = snapshot["projection"]
        pin = lambda ref: (ref["collection"], ref["id"], ref["version"])
        selected = {pin(ref) for detail in projection["details"].values()
                    for section in detail["sections"] if section["kind"] == "sources"
                    for ref in section["record_refs"] if ref["collection"] == "anchors"}
        anchor = next(row for row in projection["records"] if pin(row["ref"]) in selected)
        anchor["body"]["limitation"] = " Captured text omitted <symbols> & spacing.\nSaved note. "
        before = copy.deepcopy(snapshot)
        payload = publish.frozen_render_input(snapshot, snapshot_sha256=frozen["snapshot_sha256"])
        rows = payload["display"]["source_capture_notes"]
        self.assertEqual(1, len(rows))
        self.assertEqual({"items": rows, "total": 1}, publish._delivery_brief(snapshot, frozen)["source_capture_notes"])
        workdir = self.root / "capture-render"
        workdir.mkdir()
        html, receipt = publish.render_payload(payload, workdir=workdir)
        self.assertEqual("pass", receipt["python_acceptance"]["status"])
        self.assertEqual(before, snapshot)
        for old, new in ((b"data-source-capture-note=\"0\"", b"data-source-capture-note=\"9\""),
                         (b"Captured text omitted", b"Changed text"),
                         (b"Captured text omitted", b"<span hidden>Captured text omitted</span>"),
                         (b"data-source-evidence", b"hidden data-source-evidence")):
            with self.subTest(mutation=old):
                self.assertIn(old, html)
                self.assertEqual("fail", publish.mechanical_acceptance(
                    html.replace(old, new), projection, build=payload["build"])["status"])

    def test_missing_legacy_facts_are_unknown_and_never_clean_or_severe(self):
        _, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        projection = snapshot["projection"]
        projection["summary"].pop("factual")
        projection["summary"]["findings"].pop("current_by_review_status", None)
        projection.pop("finding_displays", None)
        projection["records"].append({"ref": {"collection": "findings", "id": "fnd_old", "version": 1},
            "body": {"description": "Saved concern", "impact_reason": "Saved impact", "severity": "severe"}})
        brief = publish._delivery_brief(snapshot, frozen)
        self.assertIsNone(brief["current_primary_outcomes"])
        self.assertIsNone(brief["current_effective_outcomes"])
        self.assertIsNone(brief["current_effective_outcomes_basis"])
        self.assertIsNone(brief["current_effective_outcomes_qualification"])
        self.assertIsNone(brief["statement_support"])
        self.assertIsNone(brief["independent_review"])
        self.assertIsNone(brief["scope"]["requested"]["items"])
        self.assertEqual(0, brief["findings"]["current"]["total"])
        self.assertEqual(1, brief["findings"]["unknown"]["total"])
        self.assertIsNone(brief["findings"]["unknown"]["items"][0]["review_display"])
        self.assertNotIn("severity", brief["findings"]["unknown"]["items"][0])
        self.assertNotIn("current_by_review_status", brief["findings"])
        self.assertNotIn("overview_scope", brief)

    def test_external_source_qualifications_are_bounded_saved_rows(self):
        _, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        factual = snapshot["projection"]["summary"]["factual"]
        baseline = publish._delivery_brief(snapshot, frozen)
        rows = [{"label": f"External result {i}",
                 "ref": {"collection": "items", "id": f"itm_ext_{i}"},
                 "availability": "unavailable", "kind": "external_result",
                 "scope_id": f"scope_ext_{i}"} for i in range(5)]
        for value in (rows, [], None):
            with self.subTest(value=value):
                factual["unresolved_external_sources"] = value
                before = copy.deepcopy(snapshot)
                brief = publish._delivery_brief(snapshot, frozen)
                self.assertEqual({"items": None if value is None else value[:3],
                                  "total": None if value is None else len(value)},
                                 brief["unresolved_external_sources"])
                self.assertEqual({k: v for k, v in baseline.items() if k != "unresolved_external_sources"},
                                 {k: v for k, v in brief.items() if k != "unresolved_external_sources"})
                self.assertEqual(before, snapshot)
        del factual["unresolved_external_sources"]
        self.assertEqual({"items": None, "total": None},
                         publish._delivery_brief(snapshot, frozen)["unresolved_external_sources"])

    def test_saved_finding_counts_and_overview_provenance_stay_separate(self):
        _, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        summary = snapshot["projection"]["summary"]
        counts = {"severe": 1, "moderate": 3, "minor": 1, "unresolved": 2, "unrated": 0}
        summary["findings"]["current_by_review_status"] = counts
        text = "Original overview omitted external sources; later audit scope is recorded separately."
        summary["overview_scope"] = {"text": text, "exclusions": [f"Original boundary {i}" for i in range(5)]}
        summary["factual"]["scope"]["exclusions"] = [{"label": "Current exclusion", "reason": "Saved reason"}]
        before = copy.deepcopy(snapshot)
        brief = publish._delivery_brief(snapshot, frozen)
        self.assertEqual(counts, brief["findings"]["current_by_review_status"])
        self.assertIsNot(counts, brief["findings"]["current_by_review_status"])
        self.assertEqual(text, brief["overview_scope"]["text"])
        self.assertEqual({"items": summary["overview_scope"]["exclusions"][:3], "total": 5},
                         brief["overview_scope"]["exclusions"])
        self.assertEqual("Current exclusion", brief["scope"]["exclusions"]["items"][0]["label"])
        self.assertNotIn("closure_statement_count", brief["scope"])
        self.assertNotIn("current_by_category", brief["findings"])
        self.assertEqual(before, snapshot)

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_full_scope_and_finding_counts_render_without_changing_outcomes(self):
        _, bundle = self.freeze(mode="full", targets=[])
        snapshot, frozen = finalization.load_finalization(bundle)
        projection = snapshot["projection"]
        summary = projection["summary"]
        self.assertEqual([], summary["scope"]["target_refs"])
        self.assertIn("all registered major items", summary["factual"]["scope"]["explanation"])
        self.assertEqual({"itm_lem", "itm_thm"}, {node["id"] for node in projection["nodes"]})
        outcomes = copy.deepcopy(summary["factual"]["work"]["current_effective_outcomes"])
        counts = {"severe": 1, "moderate": 2, "minor": 3, "unresolved": 4, "unrated": 5}
        summary["findings"]["current_by_review_status"] = counts
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    del summary["findings"]["current_by_review_status"]
                    del summary["factual"]["scope"]["explanation"]
                payload = publish.frozen_render_input(snapshot, snapshot_sha256=frozen["snapshot_sha256"])
                workdir = self.root / ("old-count-render" if legacy else "count-render")
                workdir.mkdir()
                html, receipt = publish.render_payload(payload, workdir=workdir)
                text = html.decode("utf-8")
                self.assertEqual("pass", receipt["python_acceptance"]["status"])
                self.assertIn("<dt>Explicit targets</dt>", text)
                self.assertIn("No explicit targets recorded", text)
                if legacy:
                    self.assertNotIn('data-proof-fact="current_findings"', text)
                    self.assertNotIn('data-proof-fact="scope_explanation"', text)
                else:
                    for status, color in (("severe", "red"), ("moderate", "orange"), ("minor", "yellow"),
                                          ("unresolved", "gray"), ("unrated", "gray")):
                        self.assertIn(f'data-proof-finding-status="{status}"><span class="proof-state-badge s-{color}"', text)
                    for altered in (html.replace(b"2 moderate", b"9 moderate"),
                                    html.replace(b'data-proof-fact="current_findings"', b'data-removed-fact="current_findings"'),
                                    html.replace(b'data-proof-finding-status="unresolved"><span class="proof-state-badge s-gray"',
                                                 b'data-proof-finding-status="unresolved"><span class="proof-state-badge s-green"')):
                        self.assertEqual("fail", publish.mechanical_acceptance(
                            altered, payload["projection"], build=payload["build"])["status"])
                self.assertEqual(outcomes, summary["factual"]["work"]["current_effective_outcomes"])

    def test_saved_display_separates_history_and_uncertainty_and_preserves_math(self):
        _, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        projection = snapshot["projection"]
        text = r"For every $n \geq 1$, $\sum_{j=1}^{n} a_j \leq n$; " * 30
        rows = [("fnd_stale", "historical"), ("fnd_resolved", "historical"),
                ("fnd_disputed", "unresolved"), ("fnd_inconclusive", "unresolved"),
                ("fnd_unrated", "unrated"), ("fnd_current", "moderate")]
        for ident, status in rows:
            projection["records"].append({"ref": {"collection": "findings", "id": ident, "version": 1},
                "body": {"description": text, "impact_reason": text, "severity": "severe",
                         "target": {"collection": "items", "id": "itm_thm"}, "check_refs": [], "evidence_refs": []}})
            projection.setdefault("finding_displays", {})[ident] = {"status": status, "explanation": text}
        before = copy.deepcopy(snapshot)
        findings = publish._delivery_brief(snapshot, frozen)["findings"]
        self.assertEqual(2, findings["historical_count"])
        self.assertEqual(4, findings["current"]["total"])
        self.assertEqual(["unresolved", "unresolved", "unrated", "moderate"],
            [row["review_display"]["status"] for row in findings["current"]["items"]])
        for row in findings["current"]["items"]:
            self.assertEqual(text, row["description"])
            self.assertEqual(text, row["impact_reason"])
        self.assertEqual(before, snapshot)

    def test_counts_and_limit_totals_are_saved_without_equating_release_and_support(self):
        fixture, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        factual = snapshot["projection"]["summary"]["factual"]
        factual["work"]["current_primary_outcomes"] = {"supported": 0, "gap": 1, "refuted": 0, "inconclusive": 1}
        factual["statement_support"]["counts"] = {"available": 7, "conditional": 2, "unavailable": 1}
        factual["scope"]["exclusions"] = [{"label": f"Excluded {i}", "reason": f"Reason {i}"} for i in range(8)]
        factual["source_limits"] = [{"description": f"Missing source {i}"} for i in range(7)]
        factual["independent_review"]["qualification_limitations"] = ["Saved qualification limit"]
        frozen["validation"]["projection_problems"] = [f"Saved projection limit {i}" for i in range(6)]
        release = publish._delivery_brief(snapshot, frozen)
        self.assertEqual("release", release["kind"])
        self.assertTrue(release["process_complete"])
        self.assertEqual(1, release["current_primary_outcomes"]["gap"])
        self.assertEqual(7, release["statement_support"]["counts"]["available"])
        self.assertEqual(8, release["scope"]["exclusions"]["total"])
        self.assertEqual("Excluded 0", release["scope"]["exclusions"]["items"][0]["label"])
        self.assertEqual(7, release["source_limits"]["total"])
        self.assertEqual(6, release["projection_limitations"]["total"])
        self.assertEqual(["Saved qualification limit"], release["independent_review"]["qualification_limitations"])
        snapshot.update(kind="working", process_complete=False, representation_settled=False,
            finalization_blockers=[{"code": "required_work", "message": "Unfinished source comparison."}],
            finalization_blocker_count=12)
        working = publish._delivery_brief(snapshot, frozen)
        self.assertEqual("working", working["kind"])
        self.assertFalse(working["representation_settled"])
        self.assertEqual(12, working["finalization_blockers"]["total"])
        self.assertEqual("Unfinished source comparison.", working["finalization_blockers"]["items"][0]["message"])

    def test_failed_render_preserves_prior_delivery_and_never_projects_brief(self):
        _, bundle = self.freeze(independent=True)
        output = self.root / "report.html"
        receipt = output.with_name(output.name + ".receipt.json")
        output.write_bytes(b"prior report")
        receipt.write_bytes(b"prior receipt")
        with mock.patch.object(publish, "render_payload", side_effect=PublicationError("renderer failed")), \
             mock.patch.object(publish, "_delivery_brief", side_effect=AssertionError("premature brief")):
            with self.assertRaises(PublicationError) as caught:
                publish.publish_frozen(bundle, output=output)
        self.assertTrue(caught.exception.records[-1]["prior_output_retained"])
        self.assertTrue(caught.exception.records[-1]["prior_receipt_retained"])
        self.assertEqual(b"prior report", output.read_bytes())
        self.assertEqual(b"prior receipt", receipt.read_bytes())

    def test_summary_limitations_and_aggregate_review_are_not_hidden_by_selection(self):
        _, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        summary = snapshot["projection"]["summary"]
        summary["limitations"] = ["Saved assessment limitation"]
        summary["review_display"] = {"status": "severe", "finding_refs": ["fnd_late"],
            "explanation": "Saved aggregate explanation"}
        frozen["validation"]["projection_problems"] = []
        brief = publish._delivery_brief(snapshot, frozen)
        self.assertEqual(["Saved assessment limitation"], brief["limitations"]["items"])
        self.assertEqual(1, brief["limitations"]["total"])
        self.assertEqual({"items": [], "total": 0}, brief["projection_limitations"])
        self.assertEqual(summary["review_display"], brief["review_display"])

    def test_effective_outcomes_and_compact_reviewers_reuse_saved_facts(self):
        _, bundle = self.freeze()
        snapshot, frozen = finalization.load_finalization(bundle)
        factual = snapshot["projection"]["summary"]["factual"]
        initial = {"supported": 5, "gap": 0, "refuted": 0, "inconclusive": 0}
        effective = {"supported": 2, "gap": 1, "refuted": 1, "inconclusive": 1}
        factual["work"].update(current_primary_outcomes=initial, current_effective_outcomes=effective)
        context = {"primary": {"items": ["coordinator"], "total": 1},
                   "independent": {"items": ["reviewer-a", "reviewer-b", "reviewer-c"], "total": 5}}
        factual["independent_review"].update(reviewer_context=context, state="disputed",
            response_exposures={"source_only": 8, "route_provided": 1},
            qualification_limitations=["Some targets received coordinator-only examination."])
        before = copy.deepcopy(snapshot)
        brief = publish._delivery_brief(snapshot, frozen)
        self.assertEqual(initial, brief["current_primary_outcomes"])
        self.assertEqual(effective, brief["current_effective_outcomes"])
        self.assertIn("including external-result checks", brief["current_effective_outcomes_basis"])
        self.assertIn("do not measure full coverage or reviewer agreement", brief["current_effective_outcomes_basis"])
        self.assertIn("pending, stale or disputed", brief["current_effective_outcomes_qualification"])
        self.assertEqual(context, brief["independent_review"]["reviewer_context"])
        self.assertEqual(factual["independent_review"], brief["independent_review"])
        self.assertEqual(before, snapshot)
        del factual["work"]["current_effective_outcomes"]
        del factual["independent_review"]["reviewer_context"]
        legacy = publish._delivery_brief(snapshot, frozen)
        self.assertEqual(initial, legacy["current_primary_outcomes"])
        self.assertIsNone(legacy["current_effective_outcomes"])
        self.assertIsNone(legacy["current_effective_outcomes_basis"])
        self.assertNotIn("reviewer_context", legacy["independent_review"])

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_current_and_legacy_html_outcomes_keep_correct_labels_and_limits(self):
        _, bundle = self.freeze(independent=True)
        snapshot, frozen = finalization.load_finalization(bundle)
        factual = snapshot["projection"]["summary"]["factual"]
        factual["work"]["current_primary_outcomes"] = {"supported": 5, "gap": 0, "refuted": 0, "inconclusive": 0}
        factual["work"]["current_effective_outcomes"] = {"supported": 2, "gap": 1, "refuted": 1, "inconclusive": 1}
        factual["independent_review"]["reviewer_context"] = {
            "primary": {"items": ["coordinator"], "total": 1},
            "independent": {"items": ["saved reviewer"], "total": 4}}
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    del factual["work"]["current_effective_outcomes"]
                    factual["independent_review"].pop("reviewer_context", None)
                payload = publish.frozen_render_input(snapshot, snapshot_sha256=frozen["snapshot_sha256"])
                workdir = self.root / ("legacy-render" if legacy else "current-render")
                workdir.mkdir()
                html, receipt = publish.render_payload(payload, workdir=workdir)
                text = html.decode("utf-8")
                expected = "Current initial assessment outcomes: supported." if legacy else \
                    "Current examination outcomes: 2 supported, 1 gap, 1 refuted, 1 inconclusive."
                self.assertIn(expected, text)
                self.assertEqual("pass", receipt["python_acceptance"]["status"])
                self.assertIn("Completion of the examination does not establish that every statement is supported.", text)
                self.assertIn("This working report does not establish completion of the promised audit scope.", text)
                if not legacy:
                    self.assertIn("Pending, stale or disputed integrations retain initial opinions.", text)
                # Existing publication acceptance must catch a changed aggregate.
                altered = html.replace(expected.encode(), b"All statements supported.")
                self.assertEqual("fail", publish.mechanical_acceptance(
                    altered, payload["projection"], build=payload["build"])["status"])


if __name__ == "__main__":
    unittest.main()
