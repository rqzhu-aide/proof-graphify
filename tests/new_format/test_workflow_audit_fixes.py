"""Regression cases for recovery, focused context and truthful work receipts."""
import copy
from unittest.mock import patch

from support import Fixture, R, TempCase, edit, locator
from paper_core import assistance, controller, packets, sources, work
from paper_core.canonical import canonical_bytes


class WorkflowAuditFixTests(TempCase):
    def replace(self, fx, db, collection, identifier, **changes):
        record = db.head(collection, identifier)
        fx.apply(db, [edit("replace", collection, identifier, dict(record.body, **changes), record.version)],
                 *fx.ITEMS, mode="primary")

    def test_item_focus_selects_own_argument_for_shared_setup(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            source_packet = fx.packet(db)
            sources.anchor_sources(db, request={"contract_version": 3, "request_id": fx.request_id(),
                "packet_id": source_packet["packet_id"], "anchors": [{"id": "anc_setup", "expected_version": None,
                    "source_id": fx.source_id, "locator": locator(start=1, end=1)}]})
            setup = Fixture.item_edit("itm_setup", "assumption", "Shared setup", "anc_setup", "anc_lem_proof")
            setup["body"]["passages"] = [{"role": "statement", "anchor_id": "anc_setup"}]
            fx.apply(db, [setup])
            self.replace(fx, db, "scopes", "scp_plain", assumptions=[R("items", "itm_setup")])
            view = work.derive_work(db, audit_id=fx.audit_id, focus=R("items", "itm_thm"))
            shared = next(t for t in view["tasks"] if t["target"] == R("items", "itm_setup"))
            self.assertEqual(["arguments:arg_lem", "arguments:arg_thm"], view["task_contexts"][shared["id"]])
            prefix = work.select_assignment(view, {"max_units": 1})
            self.assertEqual([shared["id"]], prefix["assigned_task_ids"])
            self.assertEqual({"owner": R("items", "itm_thm"), "argument": R("arguments", "arg_thm")}, prefix["context"])
            selected = work.select_assignment(view, {"max_units": 10, "allow_provisional": True})
            self.assertEqual(shared["id"], selected["assigned_task_ids"][0])
            self.assertEqual(R("arguments", "arg_thm"), selected["context"]["argument"])
            self.assertTrue(all(t["argument"] in (None, R("arguments", "arg_thm")) for t in selected["tasks"]))
            joint = next(u for u in selected["units"] if u["kind"] == "group")
            kinds = {t["kind"] for t in selected["tasks"] if t["id"] in joint["task_ids"]}
            self.assertEqual({"application", "derivation"}, kinds)
            self.assertTrue(selected["conditional_on_task_ids"], "The supplier's separate proof remains unfinished.")

    def test_global_checks_share_audit_context_and_keep_separate_questions(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            audit = db.head("audits", fx.audit_id)
            self.replace(fx, db, "audits", fx.audit_id, global_tasks=[dict(row,
                applicability="required" if row["kind"] != "method_interface" else "not_applicable")
                for row in audit.body["global_tasks"]])
            view = work.derive_work(db, audit_id=fx.audit_id)
            ids = [t["id"] for t in view["tasks"] if t["target"] == R("audits", fx.audit_id) and t["required"]]
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", task_ids=ids)
            self.assertTrue(prepared["prepared"])
            self.assertEqual(set(ids), set(prepared["assigned_task_ids"]))
            self.assertEqual(2, len(prepared["selected_unit_ids"]))
            self.assertEqual({"adversarial", "global_consistency"},
                             {t["kind"] for t in prepared["manifest"]["work"]["tasks"]})
            self.assertEqual(2, len(prepared["scaffold"]["results"]))
            self.assertNotIn("coverage_note", prepared["worker_guidance"])

    def test_missing_coverage_is_actionable_after_all_primary_checks(self):
        with patch.object(Fixture, "coverage_edits", return_value=[]):
            fx = self.fixture().primary()
        with fx.open() as db:
            self.replace(fx, db, "audits", fx.audit_id, qualification_id=None)
            view, (_, assessment) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
            self.assertTrue(all(t["state"] == "satisfied" for t in view["tasks"]
                                if t["required"] and t["role"] == "primary"))
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary")
            self.assertFalse(prepared["prepared"])
            actions = {a["code"]: a for a in prepared["coordinator_actions"]}
            self.assertIn("qualification_required", actions)
            action = actions["coverage_authoring"]
            missing = [p for p in assessment["problems"] if p.startswith("proof coverage for ")]
            self.assertTrue(missing)
            self.assertTrue(action["required"])
            self.assertFalse(assessment["progress"]["process_complete"])

            # Follow the action through late authoring and renewal. The existing
            # derivation covers the claims; only composition consumes coverage.
            coverage = fx.coverage_edits(db)[0]
            fx.apply(db, [coverage], *fx.ITEMS, mode="author")
            _, (_, changed) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
            self.assertEqual("current", changed["judgments"]["checks:chk_der_lem"]["freshness"])
            self.assertEqual("needs_review", changed["judgments"]["checks:chk_comp_lem"]["freshness"])
            self.assertFalse(any(p.startswith("proof coverage for arg_lem,") for p in changed["problems"]))
            renewed = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary",
                                              focus=R("items", "itm_lem"))
            self.assertEqual(["composition"], [t["kind"] for t in renewed["manifest"]["work"]["tasks"]])
            candidates = renewed["coordinator_guidance"]["renewal_candidates"]
            self.assertEqual(1, len(candidates))
            self.assertEqual(fx.pin(db, "checks", "chk_comp_lem"), candidates[0]["ref"])
            worker = copy.deepcopy(renewed["scaffold"])
            row = worker["results"][0]
            self.assertEqual(row["task_id"], candidates[0]["task_id"])
            self.assertIsNone(row["supersedes"], "Predecessors are offered, never silently selected.")
            row.update(state="complete", outcome="supported", supersedes=candidates[0]["ref"],
                       evidence_refs=["anc_lem_proof"], reasoning="Re-examined composition with its declared coverage.")
            raw = canonical_bytes(worker)
            envelope = {"contract_version": 4, "request_id": fx.request_id(), "packet_id": renewed["packet_id"],
                "rebase_packet_id": None, "reviewer": "primary-1", "qualification_id": None,
                "exposure": None, "exposure_note": ""}
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
            self.assertEqual("accepted", saved["state"], saved)
            self.assertEqual([], saved["remaining_task_ids"])
            _, (_, recovered) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
            successor = saved["record_map"][row["task_id"]]
            self.assertEqual("current", recovered["judgments"][f"checks:{successor['id']}"]["freshness"])
            self.assertTrue(recovered["judgments"]["checks:chk_comp_lem"]["superseded"])
            self.assertFalse(recovered["progress"]["process_complete"], "The other argument remains uncovered.")

    def test_complete_coverage_has_no_recovery_action(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            view = work.derive_work(db, audit_id=fx.audit_id)
            self.assertNotIn("coverage_authoring", {a["code"] for a in view["coordinator_actions"]})

    def test_composition_guidance_survives_inspection_and_partial_work_is_accepted(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            note = prepared["worker_guidance"]["coverage_note"]
            self.assertIn("check_task_ids", note)
            self.assertIn("existing_check_refs", note)
            inspected = controller.inspect_work(db, packet_id=prepared["packet_id"])
            self.assertEqual(prepared["worker_guidance"], inspected["worker_guidance"])
            self.assertIn("coverage_authoring", {a["code"] for a in prepared["coordinator_actions"]})
            worker = copy.deepcopy(prepared["scaffold"])
            worker["results"] = [row for row in worker["results"] if row["type"] == "source_fidelity"]
            for row in worker["results"]:
                row.update(result="matched", note="Compared this exact statement with the source.", evidence_refs=["anc_lem"])
            envelope = {"contract_version": 3, "request_id": fx.request_id(), "packet_id": prepared["packet_id"],
                "rebase_packet_id": None, "reviewer": "primary-1", "qualification_id": None,
                "exposure": None, "exposure_note": ""}
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
            self.assertEqual("accepted", saved["state"], saved)
        for mode in ("primary", "independent", "reconcile"):
            self.assertNotIn("coverage_note", assistance.worker_guidance(mode))
        self.assertNotIn("coverage_note", assistance.worker_guidance("independent", composition=True))

    def test_successful_prepare_retains_selector_deferrals(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            for cap, reason in ((1, "unit_limit"), (10, "different_context")):
                with self.subTest(cap=cap):
                    prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", max_units=cap)
                    self.assertTrue(prepared["prepared"])
                    self.assertTrue(prepared["deferred"])
                    self.assertEqual(prepared["deferred"], [row["unit_id"] for row in prepared["deferred_reasons"]])
                    self.assertEqual({reason}, {row["reason"] for row in prepared["deferred_reasons"]})

    def test_size_deferrals_and_selector_deferrals_are_both_retained(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            view = work.derive_work(db, audit_id=fx.audit_id, focus=R("items", "itm_lem"))
            selected = work.select_assignment(view, {"max_units": 3})
            first = copy.deepcopy(selected)
            first["units"] = first["units"][:1]
            first["tasks"] = [t for t in first["tasks"] if t["id"] in first["units"][0]["task_ids"]]
            one = packets.prepare_assignment(db, audit_id=fx.audit_id, mode="primary", selection=first)
            prepared = packets.prepare_assignment(db, audit_id=fx.audit_id, mode="primary", selection=selected,
                                                  max_bytes=one["size"]["worker_bytes"] + 10)
            self.assertTrue(prepared["prepared"])
            self.assertEqual(1, len(prepared["selected_unit_ids"]))
            self.assertEqual({"unit_limit", "packet_size_limit"}, {r["reason"] for r in prepared["deferred_reasons"]})
            self.assertEqual(prepared["deferred"], [r["unit_id"] for r in prepared["deferred_reasons"]])
            self.assertEqual("OVERSIZED_CONTEXT", prepared["diagnostics"][0]["code"])
            self.assertFalse(prepared["packet"]["truncated"])
            oversized = packets.prepare_assignment(db, audit_id=fx.audit_id, mode="primary", selection=selected,
                                                  max_bytes=1)
            self.assertFalse(oversized["prepared"])
            self.assertEqual(set(prepared["deferred"] + prepared["selected_unit_ids"]), set(oversized["deferred"]))
            self.assertEqual({"unit_limit", "packet_size_limit"}, {r["reason"] for r in oversized["deferred_reasons"]})
