"""Reviewed PDF selections account for the proof without trimming its page evidence."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest import mock

from support import R, TempCase, edit, locator
from test_sources import mini_pdf
from paper_core import PROOF_SPANS_FEATURE, assessment, controller, export_import, overview, packets, queries, sources, storage
from paper_core.bindings import binding_changes
from paper_core.errors import IncompatibleError, InvalidRequest
from paper_core.validation import State
from paper_core.refs import setup_digest
from paper_core.proof_spans import boundary_selection_digest


PAGE = "Unrelated heading.\nLemma proof: α ≤ 1; hence the claim. □\nOther theorem proof: apply the lemma. □\nUnrelated footer."
CONTINUATION = "Other result.\nThe lemma's remaining case follows by symmetry. □\nFooter."


class ReviewedProofSpansTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)
        self.db = self.fx.open()
        self.addCleanup(self.db.close)
        (self.fx.source_root / "paper.pdf").write_bytes(mini_pdf(2))
        captured = sources.capture_sources(self.db, files=["paper.pdf"])
        self.pdf_id = captured["sources"][0]["id"]
        with mock.patch.object(sources, "_extract_page", side_effect=lambda raw, page: (
                PAGE if page == 1 else CONTINUATION, "Synthetic PDF extraction; inspect its page.")):
            packet = self.fx.packet(self.db)
            sources.anchor_sources(self.db, request={
                "contract_version": 4, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
                "anchors": [{"id": f"anc_{name}_proof", "expected_version": 1, "source_id": self.pdf_id,
                             "locator": locator(page=1)} for name in ("lem", "thm")] + [
                    {"id": "anc_continuation", "expected_version": None, "source_id": self.pdf_id,
                     "locator": locator(page=2)}]})
        self.ranges = {"lem": (PAGE.index("Lemma proof"), PAGE.index("\nOther theorem")),
                       "thm": (PAGE.index("Other theorem"), PAGE.index("\nUnrelated footer"))}

    def span(self, name, *, anchor=None, interval=None):
        anchor = anchor or f"anc_{name}_proof"
        start, end = interval or self.ranges[name]
        return {"argument_ref": self.fx.pin(self.db, "arguments", f"arg_{name}"),
                "anchor_ref": self.fx.pin(self.db, "anchors", anchor), "start_offset": start, "end_offset": end}

    def body(self, spans=None):
        return {"source_refs": [self.fx.pin(self.db, "sources", self.pdf_id)],
                "anchor_refs": [self.fx.pin(self.db, "anchors", identity) for identity in
                                ("anc_lem_proof", "anc_thm_proof", "anc_continuation")],
                "purpose": "proof_boundary", "decision": "accepted", "rationale": "Reviewed both complete proofs and continuations.",
                "reviewer": "fixture", "proof_spans": spans if spans is not None else [self.span(name) for name in ("lem", "thm")]}

    def record(self, body=None, identity="srv_spans"):
        packet = self.fx.packet(self.db)
        return sources.review_sources(self.db, batch=self.fx.batch([
            edit("create", "source_reviews", identity, body or self.body())], packet["packet_id"]))

    def boundaries(self, review="srv_spans", *, continuation=False, shared=False):
        edits = []
        for name in ("lem", "thm"):
            boundary = self.db.head("proof_boundaries", f"bnd_{name}")
            ids = ["anc_lem_proof" if shared else f"anc_{name}_proof"] + (["anc_continuation"] if name == "lem" and continuation else [])
            edits.append(edit("replace", "proof_boundaries", boundary.id, dict(boundary.body,
                anchor_refs=[self.fx.pin(self.db, "anchors", identity) for identity in ids],
                source_review_ref=self.fx.pin(self.db, "source_reviews", review)), boundary.version))
        self.fx.apply(self.db, edits)

    def primary(self, rows=None):
        coverages = self.fx.coverage_edits(self.db)
        for row in coverages:
            start, end = self.ranges[row["id"].removeprefix("cov_")]
            row["body"].update(start_offset=start, end_offset=end)
        with mock.patch.object(self.fx, "coverage_edits", return_value=rows or coverages):
            self.fx.primary()

    def status(self):
        return assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)

    def test_two_proofs_on_one_page_need_no_neighbor_or_margin_coverage(self):
        self.record()
        self.boundaries()
        self.primary()
        result = self.status()
        self.assertTrue(result["progress"]["process_complete"], result["problems"])
        self.assertEqual(PAGE, self.db.head("anchors", "anc_lem_proof").body["excerpt"])
        self.assertEqual(2, len(self.db.heads("coverage")))
        self.assertTrue(queries.validate_snapshot(self.db)["ok"])

    def test_shared_anchor_keeps_each_arguments_own_selection(self):
        target = self.db.head("items", "itm_thm")
        argument = self.db.head("arguments", "arg_thm")
        self.fx.apply(self.db, [
            edit("replace", "items", target.id, dict(target.body, passages=[dict(passage,
                anchor_id="anc_lem_proof") if passage["role"] == "proof" else passage for passage in target.body["passages"]]), target.version),
            edit("replace", "arguments", argument.id, dict(argument.body, evidence_refs=["anc_lem_proof"]), argument.version)])
        self.record(self.body([self.span("lem"), self.span("thm", anchor="anc_lem_proof")]))
        self.boundaries(shared=True)
        rows = self.fx.coverage_edits(self.db)
        for row in rows:
            start, end = self.ranges[row["id"].removeprefix("cov_")]
            row["body"].update(anchor_id="anc_lem_proof", start_offset=start, end_offset=end)
        self.primary(rows)
        self.assertTrue(self.status()["progress"]["process_complete"], self.status()["problems"])

    def test_reconstructed_alternative_does_not_expand_the_written_proof_to_a_page(self):
        self.record()
        self.boundaries()
        self.primary()
        argument = self.fx.argument_edit("arg_alt", "itm_lem", "grp_alt", "anc_lem_proof")
        argument["body"]["origin"] = "reconstruction"
        self.fx.apply(self.db, [argument, self.fx.group_edit("grp_alt", "arg_alt", "itm_lem", "anc_lem_proof")])
        result = self.status()
        self.assertFalse(result["progress"]["process_complete"])
        self.assertFalse(any(problem.startswith("proof coverage") for problem in result["problems"]), result["problems"])

    def test_disjoint_spans_and_continuation_are_all_required(self):
        start, end = self.ranges["lem"]
        split = PAGE.index("hence")
        rows = [self.span("lem", interval=(start, split)), self.span("lem", interval=(split + 5, end)), self.span("thm"),
                self.span("lem", anchor="anc_continuation", interval=(CONTINUATION.index("The lemma"), CONTINUATION.index("\nFooter")))]
        self.record(self.body(rows))
        self.boundaries(continuation=True)
        self.primary()
        result = self.status()
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(any("anc_continuation" in problem and "uncovered" in problem for problem in result["problems"]))
        with self.assertRaisesRegex(InvalidRequest, "batch failed validation"):
            self.boundaries()  # A mutable boundary cannot silently drop the reviewed continuation.

    def test_shortened_coverage_does_not_shrink_the_reviewed_requirement(self):
        self.record()
        self.boundaries()
        self.primary()
        cov = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", cov.id,
            dict(cov.body, end_offset=cov.body["end_offset"] - 2), cov.version)], mode="primary")
        self.assertTrue(any("uncovered" in problem for problem in self.status()["problems"]))

    def test_disjoint_proof_and_continuation_complete_without_covering_gaps(self):
        start, end = self.ranges["lem"]
        split = PAGE.index("hence")
        spans = [self.span("lem", interval=(start, split)), self.span("lem", interval=(split + 5, end)), self.span("thm"),
                 self.span("lem", anchor="anc_continuation", interval=(CONTINUATION.index("The lemma"), CONTINUATION.index("\nFooter")))]
        self.record(self.body(spans))
        self.boundaries(continuation=True)
        rows = []
        for index, span in enumerate(spans):
            name = span["argument_ref"]["id"].removeprefix("arg_")
            rows.append(edit("create", "coverage", f"cov_span_{index}", {
                "argument_id": f"arg_{name}", "anchor_id": span["anchor_ref"]["id"],
                "start_offset": span["start_offset"], "end_offset": span["end_offset"],
                "classification": "substantive", "claim_refs": [R("items", f"itm_{name}")],
                "check_ids": [f"chk_der_{name}"], "note": "A reviewed proof segment."}))
        self.primary(rows)
        self.assertTrue(self.status()["progress"]["process_complete"], self.status()["problems"])

    def test_invalid_spans_are_rejected_without_feature_or_revision_writes(self):
        for change in (lambda b: b.update(proof_spans=[]),
                       lambda b: b["proof_spans"][0].update(start_offset=3, end_offset=3),
                       lambda b: b["proof_spans"][0].update(end_offset=len(PAGE) + 1),
                       lambda b: b.update(purpose="locator_confirmation"),
                       lambda b: b.update(anchor_refs=[]),
                       lambda b: b.update(source_refs=[])):
            body = self.body()
            change(body)
            before = self.db.max_revision()
            with self.assertRaises(InvalidRequest):
                self.record(body)
            self.assertEqual(before, self.db.max_revision())
            self.assertNotIn(PROOF_SPANS_FEATURE, json.loads(self.db.check_compatibility()["features"]))

    def test_first_span_write_gates_old_readers_without_rewriting_legacy_review(self):
        old = self.db.head("source_reviews", "srv_boundaries")
        before = self.db.conn.execute("SELECT body_json FROM record_versions WHERE collection='source_reviews' AND id=?", (old.id,)).fetchone()[0]
        self.record()
        self.assertIn(PROOF_SPANS_FEATURE, json.loads(self.db.check_compatibility()["features"]))
        supported = tuple(feature for feature in storage.SUPPORTED_FEATURES if feature != PROOF_SPANS_FEATURE)
        with mock.patch.object(storage, "SUPPORTED_FEATURES", supported), self.assertRaises(IncompatibleError):
            storage.Database(self.fx.path)
        self.assertEqual(before, self.db.conn.execute("SELECT body_json FROM record_versions WHERE collection='source_reviews' AND id=?", (old.id,)).fetchone()[0])
        exported = export_import.export_snapshot(self.db)
        self.assertEqual(self.body(), next(row["body"] for row in exported["records"]
                                          if row["collection"] == "source_reviews" and row["id"] == "srv_spans"))

    def test_changed_source_cannot_reuse_a_span_certificate(self):
        self.record()
        self.boundaries()
        self.primary()
        (self.fx.source_root / "paper.pdf").write_bytes(mini_pdf(3))
        sources.capture_sources(self.db, files=["paper.pdf"])
        self.assertFalse(self.status()["progress"]["process_complete"])
        self.assertTrue(any("proof boundary" in problem for problem in self.status()["problems"]))

    def test_accepted_selectors_are_immutable_and_neutral_context_pins_the_selection(self):
        self.record()
        self.boundaries()
        self.primary()
        audit = self.db.head("audits", self.fx.audit_id)
        self.fx.apply(self.db, [edit("replace", "audits", audit.id, dict(audit.body, independent_required=True), audit.version)],
                      *self.fx.ITEMS, mode="primary")
        prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="independent", focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        stored = self.db.packet(prepared["packet_id"])
        original = packets.independent_context_binding(State(self.db, []), stored["manifest"])
        self.assertTrue(any(row["ref"]["collection"] == "proof_boundaries" for row in original["records"]))
        payload = packets.load_packet(self.db, prepared["packet_id"])
        self.assertEqual(PAGE, next(row["body"]["excerpt"] for row in payload["records"] if row["ref"]["id"] == "anc_lem_proof"))
        self.assertFalse(any(row["ref"]["collection"] in ("source_reviews", "proof_boundaries") for row in payload["records"]))
        old = self.db.head("source_reviews", "srv_spans")
        revised = copy.deepcopy(old.body)
        revised["proof_spans"][0]["start_offset"] += 1
        packet = self.fx.packet(self.db)
        with self.assertRaises(InvalidRequest):
            sources.review_sources(self.db, batch=self.fx.batch([
                edit("replace", "source_reviews", old.id, revised, old.version)], packet["packet_id"]))
        self.record(revised, "srv_new_spans")
        self.boundaries("srv_new_spans")
        changed = binding_changes(State(self.db, []), original)
        self.assertTrue(any(row["ref"]["collection"] == "proof_boundaries" for row in changed["records"]))

    def test_omitted_selectors_still_require_the_whole_page(self):
        body = self.body()
        del body["proof_spans"]
        self.record(body)
        self.boundaries()
        self.primary()
        self.assertFalse(self.status()["progress"]["process_complete"])
        self.assertTrue(any("[0," in problem for problem in self.status()["problems"] if "uncovered" in problem))
        self.assertNotIn(PROOF_SPANS_FEATURE, json.loads(self.db.check_compatibility()["features"]))

    def test_cosmetic_argument_rename_keeps_the_reviewed_proof_certificate(self):
        self.record()
        self.boundaries()
        self.primary()
        argument = self.db.head("arguments", "arg_lem")
        self.fx.apply(self.db, [edit("replace", "arguments", argument.id,
            dict(argument.body, label="A clearer navigation label"), argument.version)])
        self.assertTrue(self.status()["progress"]["process_complete"], self.status()["problems"])

    def test_changed_argument_setup_requires_a_new_boundary_review(self):
        self.record()
        self.boundaries()
        self.primary()
        argument = self.db.head("arguments", "arg_lem")
        self.fx.apply(self.db, [edit("create", "scopes", "scp_new", {"argument_id": None,
            "parent_id": "scp_plain", "assumptions": [], "binders": [], "conditions": ["Additional setup"],
            "evidence_refs": ["anc_lem"]}),
            edit("replace", "arguments", argument.id, dict(argument.body, scope_id="scp_new"), argument.version)])
        result = self.status()
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(any("proof boundary for arg_lem" in problem for problem in result["problems"]))
        self.assertFalse(any("proof coverage for arg_lem" in problem for problem in result["problems"]), result["problems"])
        self.assertFalse(any(row["code"] == "missing_coverage" and "arg_lem" in row["argument_ids"]
                             for row in result.get("coverage_diagnostics", [])))

    def test_stale_explicit_selection_keeps_neighbor_ranges_and_no_page_credit(self):
        self.record()
        self.boundaries()
        self.primary()
        argument = self.db.head("arguments", "arg_lem")
        self.fx.apply(self.db, [self.fx.group_edit("grp_new", "arg_lem", "itm_lem", "anc_lem_proof"),
            edit("replace", "arguments", argument.id, dict(argument.body, final_group_id="grp_new"), argument.version)])
        derivation, result = assessment.derive_full(self.db, audit_id=self.fx.audit_id)
        self.assertIsNone(derivation.reviewed_boundaries["arg_lem"])
        self.assertEqual({"anc_thm_proof": [self.ranges["thm"]]}, derivation.reviewed_boundaries["arg_thm"])
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(any(row["code"] == "boundary_spans" and row["argument_ids"] == ["arg_lem"]
                            for row in result["coverage_diagnostics"]))
        self.assertFalse(any(row["code"] == "missing_coverage" and "arg_lem" in row["argument_ids"]
                             for row in result["coverage_diagnostics"]))
        self.assertFalse(any("proof coverage" in problem for problem in result["problems"]), result["problems"])

    def test_new_full_page_link_is_outside_consumed_subpage_selection(self):
        self.record()
        self.boundaries()
        self.fx.apply(self.db, [self.fx.check_edit("chk_selected", R("groups", "grp_lem"), "derivation",
            evidence=["anc_lem_proof"])], *self.fx.ITEMS, mode="primary")
        packet = self.fx.packet(self.db)
        with mock.patch.object(sources, "_extract_page", return_value=(PAGE, "Synthetic page.")):
            sources.anchor_sources(self.db, request={"contract_version": 4, "request_id": self.fx.request_id(),
                "packet_id": packet["packet_id"], "anchors": [{"id": "anc_same_page", "expected_version": None,
                    "source_id": self.pdf_id, "locator": locator(page=1)}]})
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, evidence_refs=group.body["evidence_refs"] + ["anc_same_page"]), group.version)])
        snap = assessment.Snapshot(self.db, self.db.max_revision())
        self.assertNotEqual("current", assessment.judgment_freshness(snap,
            self.db.head("checks", "chk_selected"), superseded=False)["freshness"])

    def test_equivalent_reordered_split_and_overlapping_selection_keeps_freshness(self):
        self.record()
        self.boundaries()
        original = self.db.head("proof_boundaries", "bnd_lem")
        entry = {"ref": original.pinned, "facet": "coverage", "digest": "unused",
                 "proof_span_selection_digest": boundary_selection_digest(State(self.db, []), original)}
        start, end = self.ranges["lem"]
        middle = (start + end) // 2
        spans = [self.span("thm"), self.span("lem", interval=(middle, end)),
                 self.span("lem", interval=(start, middle + 1))]
        self.record(self.body(spans), "srv_reordered")
        self.boundaries("srv_reordered")
        self.assertEqual({"records": [], "relations": []},
                         binding_changes(State(self.db, []), {"records": [entry], "relations": []}))

    def test_graphify_edit_and_export_preserve_full_page_and_span_reviews(self):
        from test_sql_overview import overview_cli

        self.record()
        self.boundaries()
        self.fx.apply(self.db, [edit("create", "overview_selections", "overview-default", {
            "paper_id": self.fx.paper_id, "title": "Selected results", "scope": "Both results",
            "item_ids": ["itm_lem", "itm_thm"], "use_ids": ["use_lem_thm"], "main_item_ids": ["itm_thm"],
            "source_ids": [self.fx.source_id, self.pdf_id], "authoring_profile": "compatibility",
            "roots": [], "unresolved": []})])
        before = {record.key: (record.version, record.body) for collection in ("proof_boundaries", "source_reviews")
                  for record in self.db.heads(collection)}
        pdf_reader = mock.Mock(return_value=SimpleNamespace(pages=[mock.Mock(extract_text=mock.Mock(return_value=text))
                                                                  for text in (PAGE, CONTINUATION)]))
        with mock.patch.object(overview_cli, "_common_core", return_value=(
                overview, storage.Database, storage.initialize, storage.paper_record)), \
                mock.patch.dict("sys.modules", {"pypdf": SimpleNamespace(PdfReader=pdf_reader)}):
            data = overview_cli.export_snapshot(self.fx.path)
            item = next(row for row in data["items"] if row["id"] == "itm_lem")
            item["caption"] = "Clearer overview caption"
            overview_cli.apply_edits(self.fx.path, {"expected_snapshot": data["snapshot_id"],
                "edits": [{"collection": "items", "op": "upsert", "id": item["id"], "record": item}]})
            exported = overview_cli.export_snapshot(self.fx.path)
        self.assertEqual(PAGE, next(row["excerpt"] for row in exported["anchors"] if row["id"] == "anc_lem_proof"))
        self.assertEqual(before, {record.key: (record.version, record.body) for collection in ("proof_boundaries", "source_reviews")
                                  for record in self.db.heads(collection)})


class HistoricalProofSelectionTests(TempCase):
    def test_pre_span_manifest_preserves_whole_anchor_context_but_not_new_selectors(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", focus=R("items", "itm_lem"))
            manifest = copy.deepcopy(db.packet(prepared["packet_id"])["manifest"])
            for row in manifest["work"]["source_context_inputs"]:
                if row.pop("proof_span_selection_digest", None) is not None:
                    record = db.version(**{key: row["ref"][key] for key in ("collection", "id", "version")})
                    row["setup_digest"] = setup_digest(record.collection, record.body)
            binding = packets.independent_context_binding(State(db, []), manifest)
            guard = {"relation": "uses_in_group", "key": R("groups", "grp_lem")}
            self.assertTrue(packets.neutral_relation_covered(State(db, []), guard, binding["records"]))
            prior = db.head("source_reviews", "srv_boundaries")
            body = dict(prior.body, proof_spans=[{"argument_ref": fx.pin(db, "arguments", "arg_lem"),
                "anchor_ref": fx.pin(db, "anchors", "anc_lem_proof"), "start_offset": 1,
                "end_offset": len(db.head("anchors", "anc_lem_proof").body["excerpt"])}])
            authority = fx.packet(db)
            sources.review_sources(db, batch=fx.batch([edit("create", "source_reviews", "srv_selection", body)], authority["packet_id"]))
            boundary = db.head("proof_boundaries", "bnd_lem")
            fx.apply(db, [edit("replace", "proof_boundaries", boundary.id,
                dict(boundary.body, source_review_ref=fx.pin(db, "source_reviews", "srv_selection")), boundary.version)])
            self.assertFalse(packets.neutral_relation_covered(State(db, []), guard, binding["records"]))
