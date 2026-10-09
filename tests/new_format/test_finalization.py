"""Scientific finalization survives live edits and presentation-only retries."""
from __future__ import annotations

import builtins
import copy
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

from support import Fixture, R, TempCase, edit, node_available, sha, write_json
from paper_core import finalization, math_render, publish, review, sources
from paper_core.assessment import derive_full
from paper_core.errors import InvalidRequest, PublicationError


DATA_ISLANDS = re.compile(br'<script id="proof-(?:projection|render-input)"[^>]*>.*?</script>', re.S)


class FinalizationTests(TempCase):
    def freeze(self, fixture, name="frozen", **kwargs):
        with fixture.open() as db:
            return finalization.finalize_audit(db, audit_id="aud_1", output=self.work / name, **kwargs)

    def title(self, fixture, value):
        with fixture.open() as db:
            paper = db.head("papers", fixture.paper_id)
            fixture.apply(db, [edit("replace", "papers", paper.id, dict(paper.body, title=value), paper.version)])

    def mismatch(self, fixture, target):
        with fixture.open() as db:
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            body = {"target": target, "result": "needs_attention", "reviewer": "primary-1",
                    "note": "The transcription differs from the captured statement.", "evidence_refs": ["anc_lem"]}
            if target["collection"] == "target_specs":
                body["context_kind"] = "exact_target"
            review.compare(db, batch=fixture.batch([edit("create", "observations", "obs_mismatch", body)], packet["packet_id"]))

    def require_node(self):
        if not node_available():
            self.skipTest("shared Node installation unavailable")

    def test_finalization_derives_once_and_needs_no_renderer_or_math_converter(self):
        fixture = self.fixture().complete()
        before = fixture.path.read_bytes()
        with patch.object(finalization, "derive_full", wraps=derive_full) as derived, \
                patch.object(publish, "_node_executable", side_effect=AssertionError("Node during finalization")), \
                patch.object(publish, "display_fragments", side_effect=AssertionError("math display during finalization")):
            result = self.freeze(fixture)
        self.assertEqual(1, derived.call_count)
        self.assertEqual(before, fixture.path.read_bytes())
        self.assertEqual(["finalization.json", "report-snapshot.json"], sorted(p.name for p in Path(result["directory"]).iterdir()))
        snapshot, receipt = finalization.load_finalization(result["directory"])
        self.assertTrue(snapshot["process_complete"])
        self.assertTrue(snapshot["representation_settled"])
        self.assertEqual("release", snapshot["kind"])
        self.assertEqual(sha(Path(result["snapshot_path"]).read_bytes()), receipt["snapshot_sha256"])

    def test_one_read_transaction_pins_title_scope_sources_projection_and_legacy_export(self):
        fixture = self.fixture().complete()
        # WAL lets the writer commit while the finalizer retains its earlier read view.
        with fixture.open() as db:
            db.conn.execute("PRAGMA journal_mode=WAL")
            revision = db.max_revision()
            before_sources = derive_full(db, audit_id="aud_1")[1]["context"]["source_context_digest"]
        original = finalization.project

        def concurrent_write(db, **kwargs):
            self.assertTrue(db.conn.in_transaction)
            with fixture.open() as writer:
                paper = writer.head("papers", fixture.paper_id)
                audit = writer.head("audits", "aud_1")
                fixture.apply(writer, [edit("replace", "papers", paper.id, dict(paper.body, title="Later live title"), paper.version)])
                fixture.apply(writer, [edit("replace", "audits", audit.id,
                    dict(audit.body, targets=[R("items", "itm_lem")]), audit.version)], *fixture.ITEMS, mode="primary")
                source = fixture.source_root / "paper.tex"
                source.write_text(source.read_text(encoding="utf-8") + "\n% later source capture\n", encoding="utf-8")
                sources.capture_sources(writer, files=["paper.tex"])
            return original(db, **kwargs)

        with patch.object(finalization, "project", side_effect=concurrent_write):
            result = self.freeze(fixture, include_export=True)
        snapshot, receipt = finalization.load_finalization(result["directory"])
        exported = json.loads(Path(result["export_path"]).read_text(encoding="utf-8"))
        self.assertEqual(revision, snapshot["revision"])
        self.assertEqual(revision, snapshot["projection"]["snapshot_revision"])
        self.assertEqual(revision, exported["revision"])
        self.assertEqual("Test paper", snapshot["paper"]["title"])
        self.assertEqual(2, len(snapshot["scope"]["target_refs"]))
        self.assertEqual(before_sources, snapshot["source_identity"])
        exported_paper = next(row for row in exported["records"] if row["collection"] == "papers")
        self.assertEqual("Test paper", exported_paper["body"]["title"])
        self.assertEqual(before_sources, exported["provenance"]["source_identity"])
        with fixture.open() as db:
            self.assertFalse(db.conn.in_transaction)
            self.assertGreater(db.max_revision(), receipt["revision"])
            self.assertEqual("Later live title", db.head("papers", fixture.paper_id).body["title"])

    def test_repeated_finalization_ignores_publication_metadata_and_preserves_original_bytes(self):
        self.require_node()
        fixture = self.fixture().complete()
        result = self.freeze(fixture)
        before = {p.name: p.read_bytes() for p in Path(result["directory"]).iterdir()}
        with fixture.open() as db:
            revision = db.max_revision()
            publish.publish_frozen(result["directory"], output=self.work / "report.html", db=db)
            self.assertEqual(revision, db.max_revision())
            with patch.object(finalization, "derive_full", side_effect=AssertionError("unnecessary rederivation")):
                repeated = finalization.finalize_audit(db, audit_id="aud_1", output=result["directory"])
        self.assertTrue(repeated["reused"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in Path(result["directory"]).iterdir()})
        with self.assertRaises(InvalidRequest):
            self.freeze(fixture, partial=True)
        self.title(fixture, "New revision")
        with self.assertRaises(InvalidRequest):
            self.freeze(fixture)
        self.assertEqual(before, {p.name: p.read_bytes() for p in Path(result["directory"]).iterdir()})

    def test_selected_audit_is_not_confused_with_additional_audit_provenance(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            body = dict(db.head("audits", "aud_1").body, targets=[R("items", "itm_lem")])
            fixture.apply(db, [edit("create", "audits", "aud_other", body)], *fixture.ITEMS, mode="primary")
        result = self.freeze(fixture)
        snapshot, receipt = finalization.load_finalization(result["directory"])
        snapshot["projection"]["records"].append({"ref": {"collection": "audits", "id": "aud_other", "version": 1}, "body": body})
        finalization.validate_finalization(snapshot, receipt)
        self.assertEqual("aud_1", snapshot["audit_id"])
        self.assertTrue(snapshot["process_complete"])

    def test_triage_and_incomplete_audits_produce_only_working_delivery(self):
        for mode in ("triage", "focused"):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode).audit(mode=mode, independent_required=False)
                with self.assertRaises(InvalidRequest):
                    self.freeze(fixture, mode + "-release")
                result = self.freeze(fixture, mode + "-working", partial=True)
                snapshot, receipt = finalization.load_finalization(result["directory"])
                self.assertFalse(snapshot["process_complete"])
                self.assertEqual("working", snapshot["kind"])
                self.assertTrue(receipt["analysis_complete"])
                self.assertGreater(receipt["remaining_work"]["count"], 0)

    def test_working_snapshot_discloses_item_and_exact_target_mismatch_with_complete_counts(self):
        self.require_node()
        for collection, identifier in (("items", "itm_lem"), ("target_specs", "tgt_lem")):
            with self.subTest(collection=collection):
                fixture = self.fixture(collection).complete()
                self.mismatch(fixture, R(collection, identifier))
                with self.assertRaises(InvalidRequest) as blocked:
                    self.freeze(fixture, collection + "-blocked")
                self.assertEqual("RELEASE_BLOCKED", blocked.exception.code)
                result = self.freeze(fixture, collection + "-working", partial=True)
                snapshot, _ = finalization.load_finalization(result["directory"])
                self.assertTrue(snapshot["process_complete"])
                self.assertEqual(snapshot["projection"]["summary"]["progress"]["required_obligations"],
                                 snapshot["projection"]["summary"]["progress"]["completed_current_obligations"])
                self.assertFalse(snapshot["representation_settled"])
                published = publish.publish_frozen(result["directory"], output=self.work / (collection + ".html"))
                visible = DATA_ISLANDS.sub(b"", Path(published["output_path"]).read_bytes())
                self.assertIn(b"Working report; delivery has not been finalized.", visible)
                self.assertIn(b"Source representation remains unresolved.", visible)
                self.assertIn(b"Canonical examination accounting is complete; delivery remains unfinished.", visible)
                self.assertIn(b'data-proof-process-complete="true"', visible)
                self.assertIn(b'data-proof-finalization-blocker="0"', visible)
                self.assertIn(b"obs_mismatch", visible)
                self.assertEqual("pass", published["receipt"]["python_acceptance"]["status"])

    def test_frozen_build_uses_old_revision_after_live_edit_without_any_live_derivation(self):
        self.require_node()
        fixture = self.fixture().complete()
        result = self.freeze(fixture)
        self.title(fixture, "Latest live title")
        with patch.object(finalization, "derive_full", side_effect=AssertionError("live derivation")), \
                patch.object(publish, "paper_record", side_effect=AssertionError("live paper read")):
            published = publish.publish_frozen(result["directory"], output=self.work / "historical.html")
        html = Path(published["output_path"]).read_bytes()
        self.assertIn(b"Test paper", html)
        self.assertNotIn(b"Latest live title", html)
        self.assertEqual(result["revision"], published["revision"])
        self.assertEqual(result["snapshot_sha256"], published["build_receipt"]["snapshot_sha256"])

    def test_cross_field_inconsistency_is_rejected_before_render_even_with_valid_hashes(self):
        fixture = self.fixture().complete()
        result = self.freeze(fixture)
        snapshot, receipt = finalization.load_finalization(result["directory"])
        cases = [lambda s, r: s["projection"].update(snapshot_revision=s["revision"] + 1),
                 lambda s, r: s["projection"].update(audit_id="aud_other"),
                 lambda s, r: s["projection"]["summary"]["progress"].update(process_complete=False),
                 lambda s, r: r.update(representation_settled=False),
                 lambda s, r: (s.update(kind="partial"), r.update(kind="partial")),
                 lambda s, r: s["projection"].update(summary=None),
                 lambda s, r: s["projection"].update(records=[None]),
                 lambda s, r: r.update(validation=None)]
        for index, mutate in enumerate(cases):
            with self.subTest(index=index):
                directory = self.work / f"bad-{index}"
                directory.mkdir()
                altered, altered_receipt = copy.deepcopy(snapshot), copy.deepcopy(receipt)
                mutate(altered, altered_receipt)
                path = write_json(directory / finalization.SNAPSHOT_NAME, altered)
                altered_receipt["snapshot_sha256"] = sha(path.read_bytes())
                write_json(directory / finalization.RECEIPT_NAME, altered_receipt)
                with patch.object(publish, "render_payload", side_effect=AssertionError("rendered malformed bundle")), \
                        self.assertRaises(InvalidRequest):
                    publish.publish_frozen(directory, output=self.work / "should-not-exist.html")
        self.assertFalse((self.work / "should-not-exist.html").exists())

    def test_analysis_failure_saves_only_diagnostics_and_keeps_an_existing_snapshot(self):
        fixture = self.fixture().complete()
        result = self.freeze(fixture)
        snapshot_bytes = Path(result["snapshot_path"]).read_bytes()
        with patch.object(finalization, "derive_full", side_effect=InvalidRequest("analysis exceeded its bound", code="ANALYSIS_LIMIT")):
            with self.assertRaises(InvalidRequest) as blocked:
                self.freeze(fixture, "limit")
        self.assertTrue(any("diagnostic_path" in row for row in blocked.exception.records if isinstance(row, dict)))
        self.assertEqual([finalization.DIAGNOSTIC_NAME], sorted(p.name for p in (self.work / "limit").iterdir()))
        self.assertEqual(snapshot_bytes, Path(result["snapshot_path"]).read_bytes())

    def test_frozen_output_cannot_replace_database_source_or_input_even_by_hardlink(self):
        fixture = self.fixture().complete()
        result = self.freeze(fixture)
        directory = Path(result["directory"])
        protected = [fixture.path, fixture.source_root / "paper.tex", directory / finalization.SNAPSHOT_NAME,
                     directory / finalization.RECEIPT_NAME]
        before = {path: path.read_bytes() for path in protected}
        for path in protected:
            with self.subTest(path=str(path)), self.assertRaises(InvalidRequest):
                publish.publish_frozen(directory, output=path)
        link = self.work / "db-alias.html"
        try:
            os.link(fixture.path, link)
        except OSError:
            pass
        else:
            with self.assertRaises(InvalidRequest):
                publish.publish_frozen(directory, output=link)
        for path in protected:
            self.assertEqual(before[path], path.read_bytes())

    def test_failed_receipt_replacement_restores_prior_pair_and_rolls_back_published_row(self):
        self.require_node()
        fixture = self.fixture().complete()
        first = self.freeze(fixture)
        output = self.work / "report.html"
        receipt_path = Path(str(output) + ".receipt.json")
        with fixture.open() as db:
            publish.publish_frozen(first["directory"], output=output, db=db)
        prior_html, prior_receipt = output.read_bytes(), receipt_path.read_bytes()
        self.title(fixture, "Changed frozen title")
        second = self.freeze(fixture, "second")
        original = publish._replace_file

        def fail_receipt(staged, destination):
            if destination == receipt_path:
                raise OSError("forced receipt replacement failure")
            original(staged, destination)

        with fixture.open() as db:
            revision = db.max_revision()
            with patch.object(publish, "_replace_file", side_effect=fail_receipt), self.assertRaises(PublicationError):
                publish.publish_frozen(second["directory"], output=output, db=db)
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(["published", "failed"], [row["state"] for row in db.publications()])
        self.assertEqual(prior_html, output.read_bytes())
        self.assertEqual(prior_receipt, receipt_path.read_bytes())
        recovered = publish.publish_frozen(second["directory"], output=output)
        self.assertIn(b"Changed frozen title", output.read_bytes())
        self.assertEqual("pass", recovered["receipt"]["python_acceptance"]["status"])
        with patch.object(publish, "render_payload", side_effect=AssertionError("unnecessary render")):
            reused = publish.publish_frozen(second["directory"], output=output)
        self.assertTrue(reused["reused"])

    def test_missing_node_retains_last_output_and_same_frozen_input_for_retry(self):
        self.require_node()
        fixture = self.fixture().complete()
        first = self.freeze(fixture)
        output = self.work / "report.html"
        publish.publish_frozen(first["directory"], output=output)
        prior_html, prior_receipt = output.read_bytes(), Path(str(output) + ".receipt.json").read_bytes()
        self.title(fixture, "Retry title")
        second = self.freeze(fixture, "second")
        with patch.object(publish, "_node_executable", side_effect=PublicationError("Node unavailable")), \
                self.assertRaises(PublicationError) as blocked:
            publish.publish_frozen(second["directory"], output=output)
        self.assertTrue(blocked.exception.records[-1]["prior_output_retained"])
        self.assertEqual(prior_html, output.read_bytes())
        self.assertEqual(prior_receipt, Path(str(output) + ".receipt.json").read_bytes())
        recovered = publish.publish_frozen(second["directory"], output=output)
        self.assertEqual(second["snapshot_sha256"], recovered["snapshot_sha256"])

    def test_inconsistent_existing_build_receipt_cannot_claim_a_successful_new_revision(self):
        self.require_node()
        fixture = self.fixture().complete()
        frozen = self.freeze(fixture)
        output = self.work / "report.html"
        publish.publish_frozen(frozen["directory"], output=output)
        receipt_path = Path(str(output) + ".receipt.json")
        altered = json.loads(receipt_path.read_text(encoding="utf-8"))
        altered["publication"]["revision"] = frozen["revision"] + 1
        write_json(receipt_path, altered)
        before_html, before_receipt = output.read_bytes(), receipt_path.read_bytes()
        with patch.object(publish, "_node_executable", side_effect=PublicationError("Node unavailable")), \
                self.assertRaises(PublicationError):
            publish.publish_frozen(frozen["directory"], output=output)
        self.assertEqual(before_html, output.read_bytes())
        self.assertEqual(before_receipt, receipt_path.read_bytes())
        recovered = publish.publish_frozen(frozen["directory"], output=output)
        self.assertFalse(recovered["reused"])
        self.assertEqual(frozen["revision"], recovered["revision"])

    def test_missing_converter_remains_nonblocking_with_visible_literal_tex(self):
        self.require_node()
        from test_publication import MathFixture
        fixture = MathFixture(self.work / "paper").complete()
        result = self.freeze(fixture)
        original_import = builtins.__import__

        def missing_converter(name, *args, **kwargs):
            if name.startswith("latex2mathml"):
                raise ImportError("forced missing converter")
            return original_import(name, *args, **kwargs)

        math_render._convert.cache_clear()
        try:
            with patch("builtins.__import__", side_effect=missing_converter):
                published = publish.publish_frozen(result["directory"], output=self.work / "literal.html")
        finally:
            math_render._convert.cache_clear()
        self.assertTrue(published["receipt"]["math_diagnostics"]["nonblocking"])
        self.assertGreater(published["receipt"]["math_diagnostics"]["count"], 0)
        self.assertIn(b"math-fallback", Path(published["output_path"]).read_bytes())

    def test_unavailable_originals_are_disclosed_while_captured_passages_remain(self):
        self.require_node()
        fixture = self.fixture().complete()
        result = self.freeze(fixture)
        (fixture.source_root / "paper.tex").unlink()
        published = publish.publish_frozen(result["directory"], output=self.work / "captured.html")
        visible = DATA_ISLANDS.sub(b"", Path(published["output_path"]).read_bytes())
        self.assertIn(b"External original source files are unavailable", visible)
        self.assertIn(b"Captured source excerpts remain embedded.", visible)
        self.assertIn(b"By induction", visible)
