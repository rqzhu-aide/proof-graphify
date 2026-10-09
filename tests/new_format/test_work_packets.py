"""Controller assignments: bounded complete context and per-task mathematical inputs."""
from __future__ import annotations

import copy
import unittest
from unittest import mock

import support
from support import R, TempCase, edit, locator

from paper_core import bindings, controller, packets, sources, work
from paper_core.canonical import canonical_bytes
from paper_core.errors import ConflictError, InvalidRequest
from paper_core.validation import State


def task(id, target, kind, *, role="primary", action="check", prerequisites=(), **extra):
    return dict(id=id, target=target, kind=kind, role=role, action=action,
                prerequisite_ids=list(prerequisites), draft_refs=[], judgment_refs=[],
                owner=R("items", "itm_thm"), argument=R("arguments", "arg_thm"), **extra)


def selection(*units):
    """One tuple of tasks represents a whole context unit, not a model invocation."""
    return {"units": [{"id": f"unit_{i}", "task_ids": [t["id"] for t in ts],
                       "prerequisite_unit_ids": [f"unit_{i-1}"] if i else []}
                      for i, ts in enumerate(units)],
            "tasks": [t for ts in units for t in ts],
            "context": {"owner": R("items", "itm_thm"), "argument": R("arguments", "arg_thm")},
            "conditional_on_task_ids": [], "analysis_complete": True}


def record_keys(packet):
    return {(entry["ref"]["collection"], entry["ref"]["id"]) for entry in packet["records"]}


def intermediate_edits(fx, *, origin="source", passages=True):
    """A separately registered local argument with source outside its major owner."""
    intermediate = fx.item_edit("itm_step", "equation", "PRIVATE CAPTION", "anc_lem_proof", "anc_lem_proof")
    intermediate["body"].update(owner_id="itm_thm", origin=origin, scope_id="scp_step",
                                statement={"form": "verbatim", "text": "PRIVATE RECONSTRUCTION"},
                                proof_idea="PRIVATE PROOF OUTLINE")
    if not passages:
        intermediate["body"]["passages"] = []
    argument = fx.argument_edit("arg_step", "itm_step", "grp_step", "anc_lem_proof")
    argument["body"].update(scope_id="scp_step", label="PRIVATE ARGUMENT LABEL")
    group = fx.group_edit("grp_step", "arg_step", "itm_step", "anc_lem_proof")
    group["body"].update(scope_id="scp_step", rationale="PRIVATE COORDINATOR REASONING")
    return [intermediate,
        edit("create", "scopes", "scp_step", {"argument_id": "arg_step", "parent_id": "scp_plain",
            "assumptions": [R("items", "itm_lem")], "binders": [],
            "conditions": ["PRIVATE FORMAL CONDITION"], "evidence_refs": ["anc_lem"]}),
        argument, group,
        edit("create", "target_specs", "tgt_step", {"target": R("items", "itm_step"),
            "statement_ref": None, "statement": {"form": "verbatim", "text": "PRIVATE EXACT TARGET"},
            "scope_id": "scp_step", "evidence_refs": ["anc_lem_proof"], "state": "draft", "fidelity_ref": None})]


class WorkPacketTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()
        self.application = task("task_app", R("uses", "use_lem_thm"), "application")
        self.derivation = task("task_der", R("groups", "grp_thm"), "derivation")

    def prepare(self, db, selected=None, **kwargs):
        return packets.prepare_assignment(db, audit_id="aud_1", mode=kwargs.pop("mode", "primary"),
            selection=selected or selection((self.application, self.derivation)), **kwargs)

    def test_one_unit_carries_all_joint_inputs_but_not_the_suppliers_proof(self):
        with self.fx.open() as db:
            self.fx.apply(db, [
                self.fx.item_edit("itm_second", "lemma", "Lemma 2", "anc_lem", "anc_lem_proof"),
                edit("create", "uses", "use_second", dict(db.head("uses", "use_lem_thm").body,
                                                          **{"from": R("items", "itm_second")})),
                edit("create", "application_details", "use_second",
                     dict(db.head("application_details", "use_lem_thm").body, use_id="use_second"))])
            result = self.prepare(db)
            keys = record_keys(result["packet"])
            self.assertTrue(result["prepared"])
            self.assertTrue({("uses", "use_lem_thm"), ("uses", "use_second"),
                             ("items", "itm_lem"), ("items", "itm_second"),
                             ("anchors", "anc_thm_proof")} <= keys)
            self.assertNotIn(("anchors", "anc_lem_proof"), keys)
            self.assertNotIn(("arguments", "arg_lem"), keys)
            self.assertNotIn(("groups", "grp_lem"), keys)

    def test_explicit_proof_borrowing_adds_the_borrowed_proof(self):
        with self.fx.open() as db:
            use = db.head("uses", "use_lem_thm")
            self.fx.apply(db, [edit("replace", "uses", use.id, dict(use.body, type="proof_argument"), use.version)])
            result = self.prepare(db)
            self.assertIn(("anchors", "anc_lem_proof"), record_keys(result["packet"]))
            application = result["manifest"]["work"]["tasks"][0]
            self.assertTrue(any(r["ref"]["id"] == "anc_lem_proof" for r in application["consumed_inputs"]))

    def test_coherent_assignment_includes_successor_composition_with_its_own_slot(self):
        composition = task("task_comp", R("arguments", "arg_thm"), "composition",
                           prerequisites=("task_app", "task_der"))
        with self.fx.open() as db:
            result = self.prepare(db, selection((self.application, self.derivation), (composition,)))
            self.assertEqual(["task_app", "task_der", "task_comp"], result["assigned_task_ids"])
            self.assertEqual(2, len(result["selected_unit_ids"]))
            self.assertEqual(3, len(result["manifest"]["work"]["tasks"]))
            self.assertEqual(["task_app", "task_der", "task_comp"],
                             [t["id"] for t in result["packet"]["instructions"]["tasks"]])
            self.assertNotIn("work", result["packet"])
            self.assertEqual(result["manifest"], db.packet(result["packet_id"])["manifest"])

    def test_task_bindings_do_not_consume_sibling_composition_or_upstream_proof(self):
        composition = task("task_comp", R("arguments", "arg_thm"), "composition")
        with self.fx.open() as db:
            result = self.prepare(db, selection((self.application, self.derivation), (composition,)))
            app, der, comp = result["manifest"]["work"]["tasks"]
            app_keys = {(r["ref"]["collection"], r["ref"]["id"]) for r in app["consumed_inputs"]}
            self.assertNotIn(("arguments", "arg_thm"), app_keys)
            self.assertNotIn(("anchors", "anc_lem_proof"), app_keys)
            self.assertIn(("arguments", "arg_thm"),
                          {(r["ref"]["collection"], r["ref"]["id"]) for r in comp["consumed_inputs"]})

    def test_unrelated_thousand_sibling_groups_do_not_enlarge_local_packet(self):
        with self.fx.open() as db:
            before = self.prepare(db)
            self.fx.apply(db, [self.fx.group_edit(f"grp_sibling_{i}", "arg_thm", "itm_thm", "anc_thm_proof")
                               for i in range(1000)])
            after = self.prepare(db)
            self.assertEqual(record_keys(before["packet"]), record_keys(after["packet"]))
            self.assertEqual(before["size"], after["size"])

    def test_only_selected_audit_context_is_collected(self):
        with self.fx.open() as db:
            original = db.head("audits", "aud_1")
            self.fx.apply(db, [edit("create", "audits", "aud_unrelated", dict(original.body))], mode="primary")
            result = self.prepare(db)
            self.assertNotIn(("audits", "aud_unrelated"), record_keys(result["packet"]))

    def test_exact_worker_size_is_the_size_of_persisted_bytes(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            raw = db.get_blob(db.packet(result["packet_id"])["payload_sha256"])
            self.assertEqual(canonical_bytes(result["packet"]), raw)
            self.assertEqual(len(raw), result["size"]["worker_bytes"])

    def test_oversized_first_unit_stores_nothing_and_has_actionable_diagnostic(self):
        with self.fx.open() as db:
            before = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            result = self.prepare(db, max_bytes=200)
            self.assertFalse(result["prepared"])
            self.assertEqual("OVERSIZED_CONTEXT", result["diagnostics"][0]["code"])
            self.assertGreater(result["diagnostics"][0]["measured_or_lower_bound_bytes"], 200)
            self.assertEqual(before, db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])

    def test_fit_keeps_complete_first_unit_and_defers_complete_next_unit(self):
        fidelity = task("task_source", R("items", "itm_lem"), "source_fidelity", action="compare_source")
        with self.fx.open() as db:
            one = self.prepare(db, selection((fidelity,)))
            result = self.prepare(db, selection((fidelity,), (self.application, self.derivation)),
                                  max_bytes=one["size"]["worker_bytes"] + 10)
            self.assertTrue(result["prepared"])
            self.assertEqual(["task_source"], result["assigned_task_ids"])
            self.assertEqual(["unit_1"], result["deferred"])
            self.assertFalse(result["packet"]["truncated"])

    def test_record_ceiling_is_enforced_before_a_partial_packet_is_saved(self):
        with self.fx.open() as db, mock.patch.object(packets, "MAX_WORK_RECORDS", 3):
            result = self.prepare(db)
            self.assertFalse(result["prepared"])
            self.assertEqual("OVERSIZED_CONTEXT", result["diagnostics"][0]["code"])

    def test_invalid_byte_limits_and_excess_units_are_rejected(self):
        with self.fx.open() as db:
            for limit in (0, -1, True, 1048577):
                with self.subTest(limit=limit), self.assertRaises(InvalidRequest):
                    self.prepare(db, max_bytes=limit)
            with self.assertRaises(InvalidRequest):
                self.prepare(db, selection(*[(self.application,)] * 11))

    def test_changed_selection_snapshot_is_not_prepared(self):
        with self.fx.open() as db:
            selected = selection((self.application,))
            selected["revision"] = db.max_revision() - 1
            with self.assertRaises(ConflictError):
                self.prepare(db, selected)

    def test_incomplete_analysis_never_dispatches_partial_graph(self):
        with self.fx.open() as db:
            selected = selection((self.application,))
            selected["analysis_complete"] = False
            result = self.prepare(db, selected)
            self.assertFalse(result["prepared"])
            self.assertEqual("ANALYSIS_INCOMPLETE", result["diagnostics"][0]["code"])

    def test_generic_extension_refuses_work_packet_without_losing_whitelist(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            with self.assertRaises(InvalidRequest) as caught:
                packets.get_packet(db, extend=result["packet_id"], request={"targets": [],
                    "source_anchor_ids": [], "source_paths": [], "reason": "more context"})
            self.assertEqual("WORK_PACKET_EXTENSION", caught.exception.code)

    def test_independent_worker_receives_no_primary_task_outline(self):
        independent = task("private_obligation", R("arguments", "arg_thm"), "composition", role="independent")
        with self.fx.open() as db:
            result = self.prepare(db, selection((independent,)), mode="independent")
            raw = canonical_bytes(result["packet"]).decode("utf-8")
            self.assertEqual([], packets.blinding_violations(result["packet"]))
            for hidden in ("private_obligation", "grp_thm", "unit_0", "conditional_on_task_ids"):
                self.assertNotIn(hidden, raw)
            self.assertIn("work", result["manifest"])
            self.assertEqual("aud_1", result["packet"]["declared_scope"]["audit_id"])

    def test_blinding_validator_rejects_outline_even_without_forbidden_records(self):
        self.assertTrue(packets.blinding_violations({"records": [], "work": {}}))
        self.assertTrue(packets.blinding_violations({"records": [], "instructions": {"tasks": []}}))

    def test_independent_part_can_use_the_explicit_parent_audit(self):
        with self.fx.open() as db:
            self.fx.apply(db, [edit("create", "parts", "prt_thm", {"item_id": "itm_thm", "label": "Part 1",
                "statement": {"form": "verbatim", "text": "Part statement"},
                "passages": [{"role": "statement", "anchor_id": "anc_thm"}], "scope_id": None,
                "origin": "source"})])
            independent = task("private_part", R("parts", "prt_thm"), "composition", role="independent")
            result = self.prepare(db, selection((independent,)), mode="independent")
            self.assertTrue(result["prepared"])
            self.assertEqual([R("parts", "prt_thm")], result["packet"]["targets"])

    def test_scheduled_intermediate_composition_delivers_source_without_private_outline(self):
        with self.fx.open() as db:
            self.fx.apply(db, intermediate_edits(self.fx, origin="reconstruction"))
            scheduled = next(row for row in work.derive_work(db, audit_id="aud_1")["tasks"]
                             if row["role"] == "independent" and row["target"] == R("arguments", "arg_step"))
            result = controller.prepare_work(db, audit_id="aud_1", mode="independent",
                task_ids=[scheduled["id"]], allow_provisional=True,
                exception_purpose="Inspect source-only transport for a scheduled intermediate argument.",
                exception_limitations="Packet blinding investigation only; primary intermediate work is incomplete.")
            self.assertTrue(result["prepared"], result)
            self.assertEqual([R("items", "itm_thm")], result["packet"]["targets"])
            self.assertEqual(R("arguments", "arg_step"), result["manifest"]["work"]["tasks"][0]["target"])
            keys = record_keys(result["packet"])
            self.assertIn(("anchors", "anc_lem_proof"), keys)
            self.assertIn(("anchors", "anc_lem"), keys)
            self.assertIn(("items", "itm_lem"), keys)
            self.assertEqual([], packets.blinding_violations(result["packet"]))
            raw = canonical_bytes(result["packet"]).decode("utf-8")
            for hidden in ("PRIVATE", "itm_step", "arg_step", "grp_step", "scp_step", "tgt_step", scheduled["id"]):
                self.assertNotIn(hidden, raw)
            inputs = result["manifest"]["work"]["source_context_inputs"]
            self.assertTrue(any(row["ref"]["id"] == "itm_step" and "setup_digest" in row for row in inputs))
            self.assertTrue(any(row["ref"]["id"] == "scp_step" for row in inputs))

    def test_local_task_targets_resolve_to_major_owner_without_trusting_task_owner(self):
        with self.fx.open() as db:
            self.fx.apply(db, intermediate_edits(self.fx))
            self.fx.apply(db, [edit("create", "uses", "use_step", {
                "from": R("items", "itm_lem"), "to": R("items", "itm_step"), "type": "dependency",
                "reason": "PRIVATE USE REASON", "evidence_refs": ["anc_lem_proof"], "regime": None,
                "uncertainty": None})])
            for collection, identity, kind in (("items", "itm_step", "external_source"),
                    ("arguments", "arg_step", "composition"), ("groups", "grp_step", "derivation"),
                    ("uses", "use_step", "application"), ("target_specs", "tgt_step", "source_fidelity")):
                with self.subTest(target=identity):
                    local = task("private_local", R(collection, identity), kind, role="independent")
                    local["owner"] = R("items", "itm_lem")
                    result = self.prepare(db, selection((local,)), mode="independent")
                    self.assertEqual([R("items", "itm_thm")], result["packet"]["targets"])
                    self.assertIn(("anchors", "anc_lem_proof"), record_keys(result["packet"]))
                    self.assertEqual([], packets.blinding_violations(result["packet"]))

    def test_invalid_intermediate_owner_chain_is_still_rejected(self):
        with self.fx.open() as db:
            self.fx.apply(db, intermediate_edits(self.fx))
            invalid = self.fx.item_edit("itm_nested", "equation", "Nested", "anc_lem_proof", "anc_lem_proof")
            invalid["body"]["owner_id"] = "itm_step"
            before = db.max_revision()
            with self.assertRaisesRegex(InvalidRequest, "batch failed validation") as caught:
                self.fx.apply(db, [invalid])
            self.assertTrue(any("owner must be a major item" in message for message in caught.exception.records))
            self.assertEqual(before, db.max_revision())

    def test_missing_intermediate_passage_fails_without_storing_a_packet(self):
        with self.fx.open() as db:
            created = intermediate_edits(self.fx, passages=False)[0]
            created["body"]["scope_id"] = None
            self.fx.apply(db, [created])
            count = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            local = task("private_missing", R("items", "itm_step"), "external_source", role="independent")
            with self.assertRaisesRegex(InvalidRequest, "no captured local source passage"):
                self.prepare(db, selection((local,)), mode="independent")
            self.assertEqual(count, db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])


class GlobalProofSourcePacketTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)
        self.fx.primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)
        audit = self.db.head("audits", self.fx.audit_id)
        globals_ = [dict(row, applicability="required", reason="") if row["kind"] == "global_consistency"
                    else row for row in audit.body["global_tasks"]]
        self.fx.apply(self.db, [edit("replace", "audits", audit.id,
            dict(audit.body, global_tasks=globals_), audit.version)], mode="primary")

    def prepare(self, **kwargs):
        tasks = work.derive_work(self.db, audit_id=self.fx.audit_id)["tasks"]
        ids = [row["id"] for row in tasks if row["kind"] == "global_consistency" and row["required"]]
        return controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
            focus=R("audits", self.fx.audit_id), task_ids=ids,
            exception_purpose="Inspect bounded global proof-source transport and immutable source pins.",
            exception_limitations="Packet shape and freshness investigation only; changed boundaries are not fully covered.",
            **kwargs)

    def supplemental_boundary(self):
        (self.fx.source_root / "supplement.tex").write_text(
            "The theorem continues here.\nAn unrelated proof.\n", encoding="utf-8")
        captured = sources.capture_sources(self.db, files=["supplement.tex"])
        source_id = captured["sources"][0]["id"]
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 4,
            "request_id": self.fx.request_id(), "packet_id": packet["packet_id"], "anchors": [
                {"id": identity, "expected_version": None, "source_id": source_id,
                 "locator": locator(start=line, end=line)}
                for identity, line in (("anc_continuation", 1), ("anc_unrelated", 2))]})
        packet = self.fx.packet(self.db)
        sources.review_sources(self.db, batch=self.fx.batch([edit("create", "source_reviews", "srv_supplement", {
            "source_refs": [self.fx.pin(self.db, "sources", self.fx.source_id),
                            self.fx.pin(self.db, "sources", source_id)],
            "anchor_refs": [self.fx.pin(self.db, "anchors", identity)
                            for identity in ("anc_thm_proof", "anc_continuation", "anc_unrelated")],
            "purpose": "proof_boundary", "decision": "accepted", "reviewer": "fixture",
            "rationale": "The selected continuation and an unrelated proof were both inspected."})],
            packet["packet_id"]))
        boundary = self.db.head("proof_boundaries", "bnd_thm")
        self.fx.apply(self.db, [edit("replace", "proof_boundaries", boundary.id, dict(boundary.body,
            anchor_refs=boundary.body["anchor_refs"] + [self.fx.pin(self.db, "anchors", "anc_continuation")],
            source_review_ref=self.fx.pin(self.db, "source_reviews", "srv_supplement")), boundary.version)])

    def response(self, prepared, evidence=("anc_thm_proof",)):
        worker = copy.deepcopy(prepared["scaffold"])
        self.assertEqual(["global_consistency"], [row["kind"] for row in prepared["manifest"]["work"]["tasks"]])
        for result in worker["results"]:
            result.update(state="complete", outcome="gap", reasoning="Synthetic global examination preserves its defect.",
                          evidence_refs=list(evidence))
        return worker

    def submit(self, prepared, worker):
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(),
            "packet_id": prepared["packet_id"], "rebase_packet_id": None, "reviewer": "primary-1",
            "qualification_id": None, "exposure": None, "exposure_note": ""}
        return controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                      response_bytes=canonical_bytes(worker))

    def test_global_response_can_cite_proof_and_boundary_only_supplement(self):
        self.supplemental_boundary()
        prepared = self.prepare()
        self.assertTrue(prepared["prepared"], prepared)
        keys = record_keys(prepared["packet"])
        self.assertTrue({("anchors", "anc_lem_proof"), ("anchors", "anc_thm_proof"),
                         ("anchors", "anc_continuation"), ("proof_boundaries", "bnd_thm"),
                         ("source_reviews", "srv_supplement")} <= keys)
        self.assertNotIn(("anchors", "anc_unrelated"), keys)
        self.assertFalse(any(collection in ("groups", "coverage", "checks", "responses")
                             for collection, _ in keys))
        self.assertEqual([], prepared["manifest"]["write_scope"])
        outcome = self.submit(prepared, self.response(prepared, ("anc_thm_proof", "anc_continuation")))
        self.assertEqual("accepted", outcome["state"], outcome)
        checks = [row for row in self.db.heads("checks") if row.body["kind"] == "global_consistency"]
        self.assertEqual(["gap"], [row.body["outcome"] for row in checks])

    def test_registered_argument_evidence_is_supplied_without_its_groups(self):
        self.supplemental_boundary()
        item = self.db.head("items", "itm_thm")
        boundary = self.db.head("proof_boundaries", "bnd_thm")
        self.fx.apply(self.db, [
            edit("replace", "items", item.id, dict(item.body,
                passages=[p for p in item.body["passages"] if p["role"] != "proof"]), item.version),
            edit("replace", "proof_boundaries", boundary.id, dict(boundary.body, state="unresolved",
                anchor_refs=[self.fx.pin(self.db, "anchors", "anc_continuation")]), boundary.version)])
        prepared = self.prepare()
        self.assertTrue(prepared["prepared"], prepared)
        keys = record_keys(prepared["packet"])
        self.assertIn(("anchors", "anc_thm_proof"), keys)
        self.assertNotIn(("groups", "grp_thm"), keys)

    def test_focused_targets_and_full_exclusions_do_not_add_unselected_proofs(self):
        self.supplemental_boundary()
        for mode in ("focused", "full"):
            with self.subTest(mode=mode):
                audit = self.db.head("audits", self.fx.audit_id)
                self.fx.apply(self.db, [edit("replace", "audits", audit.id, dict(audit.body,
                    mode=mode, targets=[R("items", "itm_lem")], exclusions=[{
                        "target": R("items", "itm_thm"), "source_anchor_ids": [],
                        "reason": "Outside this test's requested scope.", "consequence": "The theorem is not audited."}]),
                    audit.version)], mode="primary")
                prepared = self.prepare()
                self.assertTrue(prepared["prepared"], prepared)
                keys = record_keys(prepared["packet"])
                self.assertIn(("anchors", "anc_lem_proof"), keys)
                self.assertNotIn(("anchors", "anc_thm_proof"), keys)
                self.assertNotIn(("anchors", "anc_continuation"), keys)

    def test_global_source_context_retains_byte_and_record_bounds(self):
        self.supplemental_boundary()
        prepared = self.prepare()
        self.assertTrue(prepared["prepared"], prepared)
        before = self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        for kwargs in ({"max_bytes": prepared["size"]["worker_bytes"] - 1}, {}):
            with self.subTest(kwargs=kwargs), mock.patch.object(packets, "MAX_WORK_RECORDS",
                    packets.MAX_WORK_RECORDS if kwargs else 3):
                result = self.prepare(**kwargs)
                self.assertFalse(result["prepared"], result)
                self.assertEqual("OVERSIZED_CONTEXT", result["diagnostics"][0]["code"])
                self.assertTrue(result["diagnostics"][0]["largest_contributors"])
                self.assertEqual(before, self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])

    def test_unrelated_inference_detail_does_not_enlarge_global_or_independent_context(self):
        before = self.prepare()
        independent_task = task("private_global_control", R("arguments", "arg_thm"), "composition", role="independent")
        independent = packets.prepare_assignment(self.db, audit_id=self.fx.audit_id, mode="independent",
                                                 selection=selection((independent_task,)))
        self.fx.apply(self.db, [self.fx.group_edit(f"grp_unrelated_{i}", "arg_thm", "itm_thm", "anc_thm_proof")
                               for i in range(30)])
        after = self.prepare()
        self.assertEqual(record_keys(before["packet"]), record_keys(after["packet"]))
        self.assertEqual(before["size"]["worker_bytes"], after["size"]["worker_bytes"])
        self.assertEqual([], packets.blinding_violations(independent["packet"]))
        self.assertFalse(any(collection in packets.BLINDED_COLLECTIONS
                             for collection, _ in record_keys(independent["packet"])))

    def test_changed_cited_anchor_rejects_saved_response_and_new_preparation_diagnoses_pin(self):
        prepared = self.prepare()
        worker = self.response(prepared)
        anchor = self.db.head("anchors", "anc_thm_proof")
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 4, "request_id": self.fx.request_id(),
            "packet_id": packet["packet_id"], "anchors": [{"id": anchor.id, "expected_version": anchor.version,
                "source_id": self.fx.source_id, "locator": locator(start=14, end=15)}]})
        outcome = self.submit(prepared, worker)
        self.assertEqual("conflict", outcome["state"], outcome)
        self.assertEqual("CONFLICT", outcome["error"]["code"])
        self.assertFalse(any(row.body["kind"] == "global_consistency" for row in self.db.heads("checks")))
        before = self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        with self.assertRaises(InvalidRequest) as caught:
            self.prepare()
        self.assertEqual("WORK_CONTEXT_PIN", caught.exception.code)
        self.assertEqual(anchor.pinned, caught.exception.records[0]["required_ref"])
        self.assertEqual(before, self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])

    def test_new_routes_stale_global_work_but_argument_labels_do_not(self):
        prepared = self.prepare()
        worker = self.response(prepared)
        argument = self.db.head("arguments", "arg_thm")
        self.fx.apply(self.db, [edit("replace", "arguments", argument.id,
            dict(argument.body, label="An editorial label"), argument.version)])
        self.assertEqual("accepted", self.submit(prepared, worker)["state"])
        # A separate prepared global task remains sensitive to new route membership.
        global_task = task("global_again", R("audits", self.fx.audit_id), "global_consistency")
        selected = selection((global_task,))
        selected["context"] = {"owner": None, "argument": None}
        later = packets.prepare_assignment(self.db, audit_id=self.fx.audit_id, mode="primary", selection=selected)
        later["scaffold"] = controller.response_scaffold(later["manifest"])
        self.fx.apply(self.db, [self.fx.argument_edit("arg_other", "itm_thm", "grp_other", "anc_thm_proof"),
                               self.fx.group_edit("grp_other", "arg_other", "itm_thm", "anc_thm_proof")])
        outcome = self.submit(later, self.response(later))
        self.assertEqual("conflict", outcome["state"], outcome)
        self.assertTrue(any(row["relation"] == "arguments_for_target"
                            for detail in outcome["diagnostics"] for row in detail.get("relations", [])))

    def test_old_boundary_review_pin_is_diagnosed_without_substituting_live_review(self):
        prior = self.db.head("source_reviews", "srv_boundaries")
        packet = self.fx.packet(self.db)
        sources.review_sources(self.db, batch=self.fx.batch([edit("create", "source_reviews", "srv_pending",
            dict(prior.body, decision="unresolved"))], packet["packet_id"]))
        boundary = self.db.head("proof_boundaries", "bnd_thm")
        pin = self.fx.pin(self.db, "source_reviews", "srv_pending")
        self.fx.apply(self.db, [edit("replace", "proof_boundaries", boundary.id,
            dict(boundary.body, state="unresolved", source_review_ref=pin), boundary.version)])
        prepared = self.prepare()
        self.assertTrue(prepared["prepared"], prepared)
        supplied = next(row for row in prepared["packet"]["records"] if row["ref"]["id"] == "srv_pending")
        self.assertEqual(pin, supplied["ref"])
        pending = self.db.head("source_reviews", "srv_pending")
        packet = self.fx.packet(self.db)
        sources.review_sources(self.db, batch=self.fx.batch([edit("replace", "source_reviews", pending.id,
            dict(pending.body, rationale="Later unresolved review; the old boundary still pins version 1."),
            pending.version)], packet["packet_id"]))
        before = self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        with self.assertRaises(InvalidRequest) as caught:
            self.prepare()
        self.assertEqual("WORK_CONTEXT_PIN", caught.exception.code)
        self.assertEqual(pin, caught.exception.records[0]["required_ref"])
        self.assertEqual(2, caught.exception.records[0]["current_ref"]["version"])
        self.assertEqual(before, self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])


class WorkBindingTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()
        self.application = task("task_app", R("uses", "use_lem_thm"), "application")
        self.derivation = task("task_der", R("groups", "grp_thm"), "derivation")

    prepare = WorkPacketTests.prepare

    def test_caption_and_unconsumed_proof_changes_do_not_stale_application(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            spec = result["manifest"]["work"]["tasks"][0]
            lemma = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", lemma.id,
                dict(lemma.body, caption="Changed caption", passages=lemma.body["passages"] +
                     [{"role": "evidence", "anchor_id": "anc_thm_proof"}]), lemma.version)])
            self.assertEqual({"records": [], "relations": []},
                bindings.task_binding_changes(State(db, []), spec, packet=result["manifest"]))

    def test_consumed_statement_change_is_reported(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            spec = result["manifest"]["work"]["tasks"][0]
            lemma = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", lemma.id,
                dict(lemma.body, statement={"form": "verbatim", "text": "Different statement"}), lemma.version)])
            changes = bindings.task_binding_changes(State(db, []), spec, packet=result["manifest"])
            self.assertTrue(any(r["ref"]["id"] == "itm_lem" for r in changes["records"]))

    def test_cosmetic_group_member_version_does_not_defeat_facet_comparison(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            spec = result["manifest"]["work"]["tasks"][0]
            use = db.head("uses", "use_lem_thm")
            self.fx.apply(db, [edit("replace", "uses", use.id, dict(use.body, uncertainty="editorial note"), use.version)])
            self.assertEqual({"records": [], "relations": []},
                bindings.task_binding_changes(State(db, []), spec, packet=result["manifest"]))

    def test_added_joint_input_changes_membership(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            spec = result["manifest"]["work"]["tasks"][0]
            self.fx.apply(db, [self.fx.item_edit("itm_second", "lemma", "Lemma 2", "anc_lem", "anc_lem_proof"),
                edit("create", "uses", "use_extra", dict(db.head("uses", "use_lem_thm").body,
                                                          **{"from": R("items", "itm_second")})),
                edit("create", "application_details", "use_extra",
                     dict(db.head("application_details", "use_lem_thm").body, use_id="use_extra"))])
            changes = bindings.task_binding_changes(State(db, []), spec, packet=result["manifest"])
            self.assertTrue(any(r["relation"] == "uses_in_group" for r in changes["relations"]))

    def test_extra_evidence_requires_original_packet_provenance(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            spec = result["manifest"]["work"]["tasks"][0]
            self.assertEqual([], bindings.task_binding_changes(State(db, []), spec,
                evidence_refs=["anc_thm_proof"], packet=result["manifest"])["records"])
            changes = bindings.task_binding_changes(State(db, []), spec,
                evidence_refs=["anc_lem_proof"], packet=result["manifest"])
            self.assertTrue(changes["records"])

    def test_prospective_composition_binds_generated_checks_but_application_does_not(self):
        composition = task("task_comp", R("arguments", "arg_thm"), "composition")
        with self.fx.open() as db:
            result = self.prepare(db, selection((self.application, self.derivation), (composition,)))
            self.fx.apply(db, [self.fx.check_edit("chk_new_der", R("groups", "grp_thm"), "derivation")], mode="primary")
            check = self.fx.check_edit("chk_comp", R("arguments", "arg_thm"), "composition")["body"]
            bound = bindings.compute_bindings(State(db, []), "checks", check,
                                               packet=db.packet(result["packet_id"]))
            self.assertTrue(any(r["ref"]["id"] == "chk_new_der" for r in bound["records"]))
            app = self.fx.check_edit("chk_app", R("uses", "use_lem_thm"), "application")["body"]
            app_bound = bindings.compute_bindings(State(db, []), "checks", app,
                                                   packet=db.packet(result["packet_id"]))
            self.assertFalse(any(r["ref"]["collection"] == "checks" for r in app_bound["records"]))


if __name__ == "__main__":
    unittest.main()
