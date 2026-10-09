"""Report integration preserves source identity and mathematical judgments."""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_report_locations as locations
from test_html_report import REFERENCE, VisibleText, load, pc, report


release = load("proofcheck_release")


class GraphReportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "audit with spaces"
        shutil.copytree(REFERENCE, self.root)
        self.context = {}

    def project(self, *, context=None, final=False):
        return report.build_report_projection(
            pc, self.root, final=final,
            finalized_at="2026-09-09T12:00:00Z" if final else None,
            report_context=self.context if context is None else context)

    def reviewed_mapping(self, projection):
        result = projection["results"][0]
        sources = {row["id"]: row for row in projection["sources"]}
        source = sources[result["statement_source_ids"][0]]
        self.assertEqual("locked", source["status"])
        pdf = self.root / "audit/00_sources/display-evidence/manuscript.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        # The test exercises display metadata, not PDF extraction or an actual
        # claim that the mathematical statement was reviewed in this fixture.
        pdf.write_bytes(b"%PDF-1.7\nreviewed-label integration fixture\n%%EOF\n")
        mapping = {
            "version": 1, "source_snapshot_sha256": projection["audit"]["source_revision"],
            "pdf": {"path": pdf.relative_to(self.root).as_posix(),
                    "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
            "entries": [{
                "result_id": result["id"], "unit_id": result["unit_id"],
                "conclusion_id": result["conclusion_id"],
                "statement_anchor": {key: source[key] for key in ("file", "start_line", "end_line", "sha256")},
                "label": result["kind"].capitalize() + " 2.2", "pdf_page": 3,
                "review": {"status": "matched", "note": "Fixture review assertion: compared the PDF heading and the exact statement with the locked source; no actual PDF review is claimed by this test."},
            }],
        }
        return mapping, result, source

    def test_reviewed_label_reaches_projection_static_graph_and_own_preview(self):
        baseline = self.project()
        mapping, before_result, _ = self.reviewed_mapping(baseline)
        files_before = {path.relative_to(self.root): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in self.root.rglob("*") if path.is_file()}
        projection = self.project(context={"manuscript_labels": mapping})
        result = next(row for row in projection["results"] if row["id"] == before_result["id"])
        node = next(row for row in projection["graph"]["nodes"] if row["id"] == result["id"])
        observed = mapping["entries"][0]["label"]
        self.assertEqual(observed, result["display_label"])
        self.assertIsNone(result["printed_label"])
        self.assertEqual(3, result["display_pdf_page"])
        self.assertEqual(mapping["entries"][0]["statement_anchor"], result["label_provenance"]["statement_anchor"])
        self.assertEqual(before_result["judgments"], result["judgments"])
        self.assertEqual(baseline["diagnostics"], projection["diagnostics"])
        self.assertEqual([], projection["display_notes"])
        static = report._svg(projection["graph"])
        self.assertTrue(node["display"]["identity"] in static, "The static card omitted its reviewed label")
        graph = report._presentation_module("graph")
        previews = graph.render_previews(projection["graph"], rich=report._rich)
        own_preview = previews.split('<template id="' + node["display"]["preview_id"] + '">', 1)[1].split('</template>', 1)[0]
        self.assertTrue(any(label in own_preview for label in (observed, node["display"]["identity"])),
                        "The mapped result's own preview omitted its reviewed label")
        self.assertTrue("Manuscript p. 3" in own_preview, "The mapped PDF location is absent from its preview")
        rendered = report.render_report(projection)
        self.assertEqual([], report.validate_html(rendered, projection))
        self.assertFalse(any(row["file"] == mapping["pdf"]["path"] for row in projection["audit"]["source_files"]),
                         "Display evidence was added to the TeX source closure")
        files_after = {path.relative_to(self.root): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(files_before, files_after, "Projection or rendering rewrote canonical audit files")

    def test_changed_source_closure_withholds_current_digest_from_label_resolver(self):
        baseline = self.project()
        mapping, _, source = self.reviewed_mapping(baseline)
        paper = self.root / source["file"]
        paper.write_text(paper.read_text(encoding="utf-8") + "\n% Change outside the mapped statement.\n", encoding="utf-8")
        resolver = report._presentation_module("labels")
        with patch.object(resolver, "resolve_labels", wraps=resolver.resolve_labels) as resolve:
            projection = self.project(context={"manuscript_labels": mapping})
        self.assertEqual("", resolve.call_args.args[2], "A stale recorded source digest authorized PDF labels")
        self.assertTrue(projection["diagnostics"], "Actual source drift must remain a proof diagnostic")
        self.assertTrue(any("snapshot" in note for note in projection["display_notes"]))
        self.assertFalse(any(row.get("display_pdf_page") for row in projection["results"]))

    def test_literal_heading_survives_invalid_mapping_and_separate_assertion_stays_unnumbered(self):
        self.context = {"manuscript_labels": {"version": 999}}
        # Reuse the existing physical caption fixture and fixed validator
        # judgments, which isolate source presentation from mathematical review.
        projection, rows = locations.ReportLocationTests.caption_fixture(self, numbered=True)
        self.assertEqual(["Theorem 2.2", "Theorem 2.2", None], [row["printed_label"] for row in rows])
        self.assertEqual(["Theorem 2.2", "Theorem 2.2", ""], [row["display_label"] for row in rows])
        self.assertEqual("conclusion", rows[2]["kind"])
        self.assertTrue(projection["display_notes"])
        value = report._svg(projection["graph"])
        self.assertTrue("Thm 2.2" in value, "The static graph lost its literal source heading")

    def test_invalid_mapping_is_a_display_note_and_does_not_block_final_projection(self):
        baseline = self.project(final=True)
        marker = "LABEL_METADATA_IS_STRUCTURED_ONLY"
        projection = self.project(context={"manuscript_labels": {"version": 999, "review_marker": marker}}, final=True)
        self.assertEqual(baseline["diagnostics"], projection["diagnostics"])
        self.assertEqual([], projection["diagnostics"])
        self.assertEqual([row["judgments"] for row in baseline["results"]],
                         [row["judgments"] for row in projection["results"]])
        self.assertTrue(projection["display_notes"])
        rendered = report.render_report(projection)
        self.assertEqual([], report.validate_html(rendered, projection))
        self.assertTrue("Manuscript label notes" in rendered, "The display-resolution note is not visible")
        visible = VisibleText()
        visible.feed(rendered)
        self.assertFalse(marker in " ".join(visible.parts),
                         "Reserved label metadata leaked into miscellaneous authored prose")

    def test_renderer_identity_binds_graph_and_label_modules(self):
        baseline = release.renderer_identity(pc)
        original_hash = pc.sha256_portable_text_file
        for filename in ("proofcheck_graph.py", "proofcheck_labels.py"):
            with self.subTest(module=filename):
                def changed_hash(path):
                    return "0" * 64 if Path(path).name == filename else original_hash(path)

                with patch.object(pc, "sha256_portable_text_file", side_effect=changed_hash):
                    changed = release.renderer_identity(pc)
                self.assertNotEqual(baseline, changed, "Renderer identity omitted " + filename)


if __name__ == "__main__":
    unittest.main()
