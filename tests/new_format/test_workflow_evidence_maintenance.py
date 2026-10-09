"""Forward source-link maintenance preserves only explicitly consumed extent."""
from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import closing
from unittest import mock

from support import R, TempCase, edit, locator
from test_review import entry, judgment, mapping_request, source_target, worker_response
from paper_core import assessment, bindings, controller, export_import, review, sources, storage
from paper_core.canonical import canonical_bytes
from paper_core.proof_spans import boundary_selection_digest, reviewed_spans
from paper_core.validation import State


class WorkflowEvidenceMaintenanceTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def anchor(self, identity, start=9, end=9):
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 4,
            "request_id": self.fx.request_id(), "packet_id": packet["packet_id"], "anchors": [{
                "id": identity, "expected_version": None, "source_id": self.fx.source_id,
                "locator": locator(start=start, end=end)}]})

    def check(self, *, target=None, kind="derivation", evidence=("anc_lem_proof",)):
        target = target or R("groups", "grp_lem")
        packet = self.fx.packet(self.db, *self.fx.ITEMS, mode="primary")
        self.fx.apply(self.db, [self.fx.check_edit("chk_maintenance", target, kind, evidence=evidence)],
                      *self.fx.ITEMS, mode="primary")
        return packet

    def add_evidence(self, collection="groups", identity="grp_lem", anchor="anc_inside"):
        record = self.db.head(collection, identity)
        self.fx.apply(self.db, [edit("replace", collection, identity,
            dict(record.body, evidence_refs=record.body["evidence_refs"] + [anchor]), record.version)])

    def fresh(self, revision=None):
        snap = assessment.Snapshot(self.db, revision or self.db.max_revision())
        return assessment.judgment_freshness(snap, snap.live("checks", "chk_maintenance"), superseded=False)

    def binding(self):
        return self.db.binding("checks", "chk_maintenance", 1)["bindings"]

    def selection(self, *, marked=True):
        rows = []
        for name in ("lem", "thm"):
            anchor = self.db.head("anchors", f"anc_{name}_proof")
            rows.append({"argument_ref": self.fx.pin(self.db, "arguments", f"arg_{name}"),
                "anchor_ref": anchor.pinned, "start_offset": 0, "end_offset": len(anchor.body["excerpt"])})
        body = {"source_refs": [self.fx.pin(self.db, "sources", self.fx.source_id)],
            "anchor_refs": [row["anchor_ref"] for row in rows], "purpose": "proof_boundary",
            "decision": "accepted", "rationale": "Both complete proof excerpts were inspected.",
            "reviewer": "fixture", "proof_spans": rows}
        packet = self.fx.packet(self.db)
        if marked:
            sources.review_sources(self.db, batch=self.fx.batch([
                edit("create", "source_reviews", "srv_maintenance", body)], packet["packet_id"]))
        else:
            with mock.patch.object(bindings, "_mark_evidence_maintenance"):
                sources.review_sources(self.db, batch=self.fx.batch([
                    edit("create", "source_reviews", "srv_maintenance", body)], packet["packet_id"]))
        changes = []
        for name in ("lem", "thm"):
            boundary = self.db.head("proof_boundaries", f"bnd_{name}")
            changes.append(edit("replace", "proof_boundaries", boundary.id, dict(boundary.body,
                source_review_ref=self.fx.pin(self.db, "source_reviews", "srv_maintenance")), boundary.version))
        self.fx.apply(self.db, changes)
        return self.db.head("source_reviews", "srv_maintenance")

    def test_consumed_subexcerpt_addition_preserves_check_without_rebinding(self):
        self.check()
        before = copy.deepcopy(self.binding())
        self.anchor("anc_inside")
        self.add_evidence()
        self.assertEqual("current", self.fresh()["freshness"])
        self.assertEqual(before, self.binding())
        self.assertEqual(1, self.db.head("checks", "chk_maintenance").version)
        old_reader = copy.deepcopy(before)
        for row in old_reader["records"]:
            row.pop("evidence_maintenance", None)
        self.assertTrue(bindings.binding_changes(State(self.db, []), old_reader)["records"])

    def test_delivered_but_unmentioned_proof_is_not_consumed(self):
        self.check(evidence=("anc_lem",))
        self.anchor("anc_unmentioned", start=15, end=15)
        self.add_evidence(anchor="anc_unmentioned")
        self.assertNotEqual("current", self.fresh()["freshness"])

    def test_packet_anchor_presence_alone_cannot_authorize_maintenance(self):
        self.check(evidence=())
        self.anchor("anc_inside")
        self.add_evidence()
        self.assertNotEqual("current", self.fresh()["freshness"])

    def test_expanded_extent_and_changed_mathematics_remain_stale(self):
        self.check()
        self.anchor("anc_expanded", start=8, end=11)
        self.add_evidence(anchor="anc_expanded")
        self.assertNotEqual("current", self.fresh()["freshness"])
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, rationale="A different inference", evidence_refs=["anc_lem_proof"]), group.version)])
        self.assertNotEqual("current", self.fresh()["freshness"])

    def test_removed_and_reordered_links_are_not_additions(self):
        self.anchor("anc_inside")
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, evidence_refs=["anc_lem_proof", "anc_inside"]), group.version)])
        self.check()
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, evidence_refs=["anc_inside", "anc_lem_proof"]), group.version)])
        self.assertNotEqual("current", self.fresh()["freshness"])
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, evidence_refs=["anc_lem_proof"]), group.version)])
        self.assertNotEqual("current", self.fresh()["freshness"])

    def test_unknown_and_unmarked_bindings_remain_strict(self):
        self.check()
        old = copy.deepcopy(self.binding())
        unknown = copy.deepcopy(old)
        for row in old["records"]:
            row.pop("evidence_maintenance", None)
        for row in unknown["records"]:
            if "evidence_maintenance" in row:
                row["evidence_maintenance"]["version"] = 999
        self.anchor("anc_inside")
        self.add_evidence()
        for binding in (old, unknown):
            self.assertTrue(bindings.binding_changes(State(self.db, []), binding)["records"])

    def test_new_source_bytes_invalidate_consumed_source_guards(self):
        self.check()
        self.anchor("anc_inside")
        self.add_evidence()
        path = self.fx.source_root / "paper.tex"
        path.write_text(path.read_text(encoding="utf-8") + "\nNew source text.\n", encoding="utf-8")
        sources.capture_sources(self.db, files=["paper.tex"])
        self.assertNotEqual("current", self.fresh()["freshness"])

    def test_marked_source_review_retains_exact_span_after_consumed_addition(self):
        review = self.selection()
        self.fx.primary()
        state = State(self.db, [])
        boundary = self.db.head("proof_boundaries", "bnd_lem")
        before = boundary_selection_digest(state, boundary)
        self.anchor("anc_inside")
        self.add_evidence("arguments", "arg_lem")
        state = State(self.db, [])
        self.assertIsNotNone(reviewed_spans(state, review, self.db.head("arguments", "arg_lem"), boundary.body["anchor_refs"]))
        self.assertEqual(before, boundary_selection_digest(state, boundary))
        result = assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)
        self.assertFalse(any("proof boundary for arg_lem" in problem for problem in result["problems"]), result["problems"])

    def test_unmarked_boundary_digest_keeps_history_but_stale_selection_blocks(self):
        review = self.selection(marked=False)
        boundary = self.db.head("proof_boundaries", "bnd_lem")
        before = boundary_selection_digest(State(self.db, []), boundary)
        self.anchor("anc_inside")
        self.add_evidence("arguments", "arg_lem")
        state = State(self.db, [])
        self.assertEqual(before, boundary_selection_digest(state, boundary))
        self.assertIsNone(reviewed_spans(state, review, self.db.head("arguments", "arg_lem"), boundary.body["anchor_refs"]))

    def test_final_group_change_is_not_source_link_maintenance(self):
        review = self.selection()
        boundary = self.db.head("proof_boundaries", "bnd_lem")
        before = boundary_selection_digest(State(self.db, []), boundary)
        argument = self.db.head("arguments", "arg_lem")
        self.fx.apply(self.db, [self.fx.group_edit("grp_new", "arg_lem", "itm_lem", "anc_lem_proof"),
            edit("replace", "arguments", argument.id, dict(argument.body, final_group_id="grp_new"), argument.version)])
        state = State(self.db, [])
        self.assertIsNone(reviewed_spans(state, review, self.db.head("arguments", "arg_lem"), boundary.body["anchor_refs"]))
        self.assertNotEqual(before, boundary_selection_digest(state, boundary))

    def test_export_json_and_backup_preserve_forward_and_historical_comparisons(self):
        self.check()
        revision = self.db.max_revision()
        before = self.fresh(revision)
        self.anchor("anc_inside")
        self.add_evidence()
        exported = json.loads(json.dumps(export_import.export_snapshot(self.db, history=True)))
        binding = next(row["bindings"] for row in exported["bindings"] if row["ref"]["id"] == "chk_maintenance")
        self.assertEqual(self.binding(), binding)
        self.assertEqual({"records": [], "relations": []}, bindings.binding_changes(State(self.db, []), binding))
        backup = self.fx.root / "copy.db"
        with closing(sqlite3.connect(backup)) as target:
            self.db.conn.backup(target)
        with storage.Database(backup) as reopened:
            snap = assessment.Snapshot(reopened, revision)
            self.assertEqual(before, assessment.judgment_freshness(snap, snap.live("checks", "chk_maintenance"), superseded=False))
            self.assertEqual(binding, reopened.binding("checks", "chk_maintenance", 1)["bindings"])

    def test_mapped_independent_and_reconciliation_remain_current_after_consumed_link(self):
        self.fx.primary()
        audit = self.db.head("audits", self.fx.audit_id)
        self.fx.apply(self.db, [edit("replace", "audits", audit.id,
            dict(audit.body, independent_required=True), audit.version)], *self.fx.ITEMS, mode="primary")
        prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id,
            mode="independent", focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        worker = worker_response(prepared["packet_id"], [judgment(
            source_target("anc_lem_proof", "The written argument"), evidence=("anc_lem_proof",))])
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "checker-A", "qualification_id": "qua_r1",
            "exposure": "source_only", "exposure_note": "Fresh source-only reviewer."}
        returned = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
        private = self.fx.packet(self.db, "items:itm_lem", mode="reconcile")
        mapped = review.map_response(self.db, mapping=mapping_request(self.fx, private["packet_id"],
            returned["response_id"], [entry(0, R("arguments", "arg_lem"))]))
        independent = mapped["checks"][0]["check_id"]
        private = self.fx.packet(self.db, "items:itm_lem", mode="reconcile")
        review.reconcile(self.db, batch=self.fx.batch([self.fx.reconciliation_edit(self.db,
            "rec_maintenance", "arg_lem", "chk_comp_lem", independent)], private["packet_id"]))
        saved = copy.deepcopy(self.db.binding("checks", independent, 1))
        self.anchor("anc_inside")
        self.add_evidence()
        snap = assessment.Snapshot(self.db, self.db.max_revision())
        for collection, identity in (("checks", independent), ("checks", "chk_comp_lem"),
                                     ("reconciliations", "rec_maintenance")):
            self.assertEqual("current", assessment.judgment_freshness(snap,
                self.db.head(collection, identity), superseded=False)["freshness"])
        self.assertEqual(saved, self.db.binding("checks", independent, 1))

    def test_coordinator_only_passage_cannot_authorize_independent_maintenance(self):
        self.fx.primary()
        audit = self.db.head("audits", self.fx.audit_id)
        self.fx.apply(self.db, [edit("replace", "audits", audit.id,
            dict(audit.body, independent_required=True), audit.version)], *self.fx.ITEMS, mode="primary")
        prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id,
            mode="independent", focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        original = self.db.packet(prepared["packet_id"])
        self.assertNotIn("anc_thm_proof", [pin["id"] for pin in original["manifest"]["read_set"]])
        worker = worker_response(prepared["packet_id"], [judgment(
            source_target("anc_lem_proof", "The written argument"), evidence=("anc_lem_proof",))])
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "checker-A", "qualification_id": "qua_r1",
            "exposure": "source_only", "exposure_note": "Fresh source-only reviewer."}
        returned = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
        private = self.fx.packet(self.db, *self.fx.ITEMS, mode="reconcile")
        coordinator = self.db.packet(private["packet_id"])
        self.assertIn("anc_thm_proof", [pin["id"] for pin in coordinator["manifest"]["read_set"]])
        mapped = review.map_response(self.db, mapping=mapping_request(self.fx, private["packet_id"],
            returned["response_id"], [entry(0, R("arguments", "arg_lem"))]))
        independent = mapped["checks"][0]["check_id"]
        stored = self.db.binding("checks", independent, 1)["bindings"]
        for row in stored["records"]:
            for selection in row.get("evidence_maintenance", {}).get("selections", []):
                self.assertEqual("anc_lem_proof", selection["anchor_ref"]["id"])
        self.add_evidence(anchor="anc_thm_proof")
        snap = assessment.Snapshot(self.db, self.db.max_revision())
        self.assertNotEqual("current", assessment.judgment_freshness(snap,
            self.db.head("checks", independent), superseded=False)["freshness"])
