"""Acceptance and freshness transitions required before stage scheduling."""
import copy
from unittest import mock

from support import Fixture, R, TempCase, edit, locator
from test_review import entry, judgment, mapping_request, source_target, submission, worker_response
from test_work_packets import selection, task
from paper_core import assessment, bindings, controller, packets, review, sources, work
from paper_core.canonical import canonical_bytes
from paper_core.errors import ConflictError
from paper_core.validation import State


class ReviewReliabilityTests(TempCase):
    def test_partial_mapping_keeps_scope_invalid_judgment_pending_and_ineligible(self):
        for controller_path in (False, True):
            with self.subTest(controller_path=controller_path):
                fx = self.fixture(str(controller_path)).primary()
                with fx.open() as db:
                    prepared = (controller.prepare_work(db, audit_id=fx.audit_id, mode="independent",
                                    focus=R("items", "itm_thm")) if controller_path else
                                packets.get_packet(db, targets=Fixture.ITEM_REFS, mode="independent"))
                    worker = worker_response(prepared["packet_id"], [
                        judgment(R("items", "itm_lem"), kind="external_source", evidence=("anc_lem",), outcome="gap"),
                        judgment(source_target("anc_thm_proof", "the assigned proof"), evidence=("anc_thm_proof",))],
                        covered=[R("items", "itm_thm")])
                    raw, envelope = canonical_bytes(worker), submission(fx, prepared["packet_id"])
                    if controller_path:
                        envelope["rebase_packet_id"] = None
                        saved = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
                    else:
                        saved = review.submit_review(db, submission=envelope, response_bytes=raw)
                    self.assertEqual("needs_revision", saved["state"])
                    original_receipt = db.commit_by_request(envelope["request_id"])["receipt_json"]
                    authority = fx.packet(db, *Fixture.ITEMS, mode="primary")
                    mapped = review.map_response(db, mapping=mapping_request(fx, authority["packet_id"],
                        saved["response_id"], [entry(1, R("arguments", "arg_thm"))]))
                    self.assertEqual("needs_revision", mapped["state"])
                    self.assertEqual([0], mapped["remaining"])
                    info = review.inspect_response(db, response_id=saved["response_id"], limit=1)
                    self.assertEqual([0], info["pending_judgment_indexes"])
                    self.assertEqual([1], info["mapped_judgment_indexes"])
                    self.assertEqual(0, info["eligible_independent_check_count"])
                    live = work.derive_work(db, audit_id=fx.audit_id)
                    composition = next(task for task in live["tasks"] if task["target"] == R("arguments", "arg_thm")
                                       and task["kind"] == "composition" and task["role"] == "independent")
                    self.assertNotEqual("satisfied", composition["state"])
                    self.assertEqual(raw, db.get_blob(info["original_blob_sha256"]))
                    self.assertEqual(original_receipt, db.commit_by_request(envelope["request_id"])["receipt_json"])

    def test_submission_and_inspection_agree_when_original_mapping_guards_already_changed(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", focus=R("items", "itm_lem"))
            item = db.head("items", "itm_lem")
            fx.apply(db, [edit("replace", "items", item.id, dict(item.body, caption="Updated display caption"), item.version)])
            raw = canonical_bytes(worker_response(prepared["packet_id"], [judgment(source_target("anc_lem_proof", "lemma proof"))]))
            envelope = dict(submission(fx, prepared["packet_id"]), rebase_packet_id=None)
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertTrue(info["mapping_input_changes"]["records"])
            for result in (saved, info):
                self.assertNotIn("map_saved_response", [row["operation"] for row in result["recovery"]])
                self.assertIn("original_mapping_inputs_changed", [row["reason_code"] for row in result["recovery"]])
            authority = fx.packet(db, "items:itm_lem", mode="primary")
            revision = db.max_revision()
            with self.assertRaises(ConflictError):
                review.map_response(db, mapping=mapping_request(fx, authority["packet_id"], saved["response_id"],
                    [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(raw, db.get_blob(info["original_blob_sha256"]))

    def test_cross_mode_pairing_advice_preserves_provenance_rejection_and_actual_worker_bytes(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            primary = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            independent = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", focus=R("items", "itm_lem"),
                exception_purpose="Exercise cross-mode packet-pairing recovery",
                exception_limitations="Protocol fixture with primary examination unfinished")
            worker = copy.deepcopy(primary["scaffold"])
            worker["results"] = [row for row in worker["results"] if row["type"] == "source_fidelity"]
            for row in worker["results"]:
                row.update(result="matched", note="Compared the source", evidence_refs=["anc_lem"])
            raw = canonical_bytes(worker)
            envelope = {"contract_version": 4, "request_id": fx.request_id(), "packet_id": independent["packet_id"],
                "rebase_packet_id": None, "reviewer": "primary-1", "qualification_id": None,
                "exposure": None, "exposure_note": ""}
            rejected = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
            self.assertEqual("QUALIFICATION_INVALID", rejected["error"]["code"])
            self.assertFalse(rejected["stored"])
            pair = rejected["recovery"][0]
            self.assertEqual("PACKET_MISMATCH", pair["reason_code"])
            self.assertEqual(independent["packet_id"], pair["envelope_packet_id"])
            self.assertEqual(primary["packet_id"], pair["worker_packet_id"])
            corrected_envelope = dict(envelope, request_id=fx.request_id(), packet_id=primary["packet_id"])
            accepted = controller.submit_work(db, envelope_bytes=canonical_bytes(corrected_envelope), response_bytes=raw)
            self.assertEqual("accepted", accepted["state"])
            row = db.work_submission(corrected_envelope["request_id"])
            self.assertEqual(raw, db.get_blob(row["response_sha256"]))


class ExtensionReliabilityTests(TempCase):
    def test_harmless_version_changes_allow_extension_with_current_pins_and_immutable_parent(self):
        for field, value in (("label", "New result label"), ("proof_idea", "PRIVATE COORDINATOR PROOF IDEA")):
            with self.subTest(field=field):
                fx = self.fixture(field).primary()
                with fx.open() as db:
                    prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", focus=R("items", "itm_thm"))
                    stored = db.packet(prepared["packet_id"])
                    original_payload = db.get_blob(stored["payload_sha256"])
                    original_manifest = copy.deepcopy(stored["manifest"])
                    item = db.head("items", "itm_thm")
                    fx.apply(db, [edit("replace", "items", item.id, dict(item.body, **{field: value}), item.version)])
                    self.assertEqual({"records": [], "relations": []}, packets.independent_context_changes(State(db, []), original_manifest))
                    extended = controller.extend_work(db, packet_id=prepared["packet_id"], request={
                        "source_refs": [db.head("anchors", "anc_lem_proof").pinned], "reason": "Read the supplier proof too."})
                    self.assertTrue(extended["prepared"], extended)
                    self.assertEqual(prepared["assigned_task_ids"], extended["assigned_task_ids"])
                    live_pin = db.head("items", "itm_thm").pinned
                    self.assertIn(live_pin, extended["manifest"]["read_set"])
                    self.assertEqual([], packets.blinding_violations(extended["packet"]))
                    self.assertNotIn(b"PRIVATE COORDINATOR", canonical_bytes(extended["packet"]))
                    self.assertEqual(original_payload, db.get_blob(stored["payload_sha256"]))
                    self.assertEqual(original_manifest, db.packet(prepared["packet_id"])["manifest"])

    def test_equivalent_part_membership_guards_are_refreshed_for_extended_mapping(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            fx.apply(db, [edit("create", "parts", "prt_thm", {"item_id": "itm_thm", "label": "Part A",
                "statement": {"form": "verbatim", "text": "A source claim"}, "scope_id": None, "origin": "source",
                "passages": [{"role": "statement", "anchor_id": "anc_thm"}]})])
            prepared = packets.prepare_assignment(db, audit_id=fx.audit_id, mode="independent", selection=selection((
                task("independent_proof", R("arguments", "arg_thm"), "composition", role="independent"),)))
            part = db.head("parts", "prt_thm")
            fx.apply(db, [edit("replace", "parts", part.id, dict(part.body, label="Editorial part label"), part.version)])
            extended = controller.extend_work(db, packet_id=prepared["packet_id"], request={
                "source_refs": [db.head("anchors", "anc_lem_proof").pinned], "reason": "Read the supplier proof too."})
            worker = worker_response(extended["packet_id"], [judgment(source_target("anc_thm_proof", "the theorem proof"),
                evidence=("anc_thm_proof",))], covered=[R("items", "itm_thm")])
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes(dict(submission(fx, extended["packet_id"]),
                rebase_packet_id=None)), response_bytes=canonical_bytes(worker))
            self.assertEqual("needs_revision", saved["state"], saved)
            self.assertIn("map_saved_response", [row["operation"] for row in saved["recovery"]])
            authority = fx.packet(db, "items:itm_thm", mode="primary")
            mapped = review.map_response(db, mapping=mapping_request(fx, authority["packet_id"], saved["response_id"],
                [entry(0, R("arguments", "arg_thm"))]))
            self.assertEqual("accepted", mapped["state"])

    def test_scientific_change_still_rejects_extension_without_writing_a_packet(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", focus=R("items", "itm_thm"))
            item = db.head("items", "itm_thm")
            fx.apply(db, [edit("replace", "items", item.id,
                dict(item.body, statement={"form": "transcription", "text": "Changed mathematical conclusion"}), item.version)])
            count = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            with self.assertRaises(ConflictError):
                controller.extend_work(db, packet_id=prepared["packet_id"], request={
                    "source_refs": [db.head("anchors", "anc_lem_proof").pinned], "reason": "Read the supplier proof too."})
            self.assertEqual(count, db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])


class GlobalSelectionReliabilityTests(TempCase):
    def global_fixture(self, name):
        fx = self.fixture(name).audit(independent_required=False).primary()
        with fx.open() as db:
            audit = db.head("audits", fx.audit_id)
            globals_ = [dict(row, applicability="required", reason="") if row["kind"] == "global_consistency"
                        else row for row in audit.body["global_tasks"]]
            fx.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, global_tasks=globals_), audit.version)], mode="primary")
            authority = fx.packet(db)
            sources.anchor_sources(db, request={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": authority["packet_id"], "anchors": [{"id": "anc_extra", "expected_version": None,
                    "source_id": fx.source_id, "locator": locator(start=17, end=17)}]})
            authority = fx.packet(db)
            sources.review_sources(db, batch=fx.batch([edit("create", "source_reviews", "srv_extra", {
                "source_refs": [db.head("sources", fx.source_id).pinned],
                "anchor_refs": [db.head("anchors", identity).pinned for identity in ("anc_thm_proof", "anc_extra")],
                "purpose": "proof_boundary", "decision": "accepted", "reviewer": "fixture", "rationale": "Selected captured continuation"})],
                authority["packet_id"]))
        return fx

    @staticmethod
    def legacy_binding(binding):
        # Reproduce the prior global binding writer, which did not bind item
        # proof selection or boundary selection. Stored bytes stay untouched.
        result = copy.deepcopy(binding)
        result["records"] = [row for row in result["records"] if not (
            row["ref"]["collection"] in ("items", "parts") and row["facet"] == "proof")]
        return result

    def prepare(self, fx, db, historical=False):
        original = packets.task_binding
        def legacy_task(state, task):
            result = original(state, task)
            result["consumed_inputs"] = self.legacy_binding({"records": result["consumed_inputs"]})["records"]
            return result
        with mock.patch.object(packets, "task_binding", side_effect=legacy_task) if historical else mock.patch.object(packets, "task_binding", wraps=original):
            ids = [row["id"] for row in work.derive_work(db, audit_id=fx.audit_id)["tasks"]
                   if row["kind"] == "global_consistency" and row["required"]]
            return controller.prepare_work(db, audit_id=fx.audit_id, mode="primary",
                focus=R("audits", fx.audit_id), task_ids=ids)

    def submit(self, fx, db, prepared, historical=False):
        worker = copy.deepcopy(prepared["scaffold"])
        for row in worker["results"]:
            row.update(state="complete", outcome="gap", reasoning="The synthetic global examination found a gap.", evidence_refs=["anc_thm_proof"])
        envelope = {"contract_version": 4, "request_id": fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "primary-1", "qualification_id": None, "exposure": None, "exposure_note": ""}
        insert = db.insert_binding
        def legacy_insert(collection, identity, version, packet_id, binding):
            return insert(collection, identity, version, packet_id, self.legacy_binding(binding) if collection == "checks" else binding)
        with mock.patch.object(db, "insert_binding", side_effect=legacy_insert) if historical else mock.patch.object(db, "insert_binding", wraps=insert):
            return controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))

    def change_selection(self, fx, db, change):
        if change == "item":
            item = db.head("items", "itm_thm")
            fx.apply(db, [edit("replace", "items", item.id,
                dict(item.body, passages=item.body["passages"] + [{"role": "proof", "anchor_id": "anc_extra"}]), item.version)])
        elif change == "boundary":
            boundary = db.head("proof_boundaries", "bnd_thm")
            fx.apply(db, [edit("replace", "proof_boundaries", boundary.id,
                dict(boundary.body, anchor_refs=boundary.body["anchor_refs"] + [db.head("anchors", "anc_extra").pinned],
                    source_review_ref=db.head("source_reviews", "srv_extra").pinned), boundary.version)])
        else:
            boundary = db.head("proof_boundaries", "bnd_thm")
            fx.apply(db, [{"op": "retire", "collection": "proof_boundaries", "id": boundary.id,
                "expected_version": boundary.version, "reason": "Replace the selected source boundary."},
                edit("create", "proof_boundaries", "bnd_extra", {
                "target": R("items", "itm_thm"), "argument_ids": ["arg_thm"],
                "anchor_refs": [db.head("anchors", "anc_extra").pinned],
                "source_review_ref": db.head("source_reviews", "srv_extra").pinned, "state": "complete"})])

    def test_new_selection_rejects_prepared_response_and_stales_saved_credit_including_old_bindings(self):
        for historical in (False, True):
            for saved_before_change in (False, True):
                for change in ("item", "boundary", "attach_boundary"):
                    with self.subTest(historical=historical, saved=saved_before_change, change=change):
                        fx = self.global_fixture(f"{historical}_{saved_before_change}_{change}")
                        with fx.open() as db:
                            prepared = self.prepare(fx, db, historical)
                            self.assertTrue(prepared["prepared"], prepared)
                            self.assertNotIn("anc_extra", [row["ref"]["id"] for row in prepared["packet"]["records"]])
                            saved = self.submit(fx, db, prepared, historical) if saved_before_change else None
                            if saved:
                                self.assertEqual("accepted", saved["state"], saved)
                                check = db.head("checks", next(row["id"] for row in saved["receipt"]["changed"] if row["collection"] == "checks"))
                                bound_before = db.binding("checks", check.id, check.version)
                            self.change_selection(fx, db, change)
                            if saved:
                                with mock.patch.object(db, "get_blob", side_effect=AssertionError("historical freshness must not load worker blobs")):
                                    current = assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), check, superseded=False)
                                self.assertEqual("needs_review", current["freshness"], current)
                                self.assertEqual(bound_before, db.binding("checks", check.id, check.version))
                                obligation = next(row for row in work.derive_work(db, audit_id=fx.audit_id)["tasks"]
                                                  if row["kind"] == "global_consistency")
                                self.assertNotEqual("satisfied", obligation["state"])
                            else:
                                rejected = self.submit(fx, db, prepared, historical)
                                self.assertEqual("conflict", rejected["state"], rejected)
                                self.assertIsNone(rejected["receipt"])

    def test_harmless_labels_and_boundary_review_metadata_keep_old_and_new_global_credit_current(self):
        for historical in (False, True):
            with self.subTest(historical=historical):
                fx = self.global_fixture(str(historical))
                with fx.open() as db:
                    prepared = self.prepare(fx, db, historical)
                    saved = self.submit(fx, db, prepared, historical)
                    self.assertEqual("accepted", saved["state"], saved)
                    check = db.head("checks", next(row["id"] for row in saved["receipt"]["changed"] if row["collection"] == "checks"))
                    item = db.head("items", "itm_thm")
                    boundary = db.head("proof_boundaries", "bnd_thm")
                    fx.apply(db, [edit("replace", "items", item.id, dict(item.body, label="Editorial label", proof_idea="PRIVATE NOTE"), item.version),
                        edit("replace", "proof_boundaries", boundary.id,
                            dict(boundary.body, source_review_ref=db.head("source_reviews", "srv_extra").pinned), boundary.version)])
                    current = assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), check, superseded=False)
                    self.assertEqual("current", current["freshness"], current)

    def test_unavailable_historical_provenance_reports_unknown_without_loading_worker_blobs(self):
        fx = self.global_fixture("unknown_history")
        with fx.open() as db:
            prepared = self.prepare(fx, db, historical=True)
            saved = self.submit(fx, db, prepared, historical=True)
            check = db.head("checks", next(row["id"] for row in saved["receipt"]["changed"] if row["collection"] == "checks"))
            with mock.patch.object(db, "packet", return_value=None), mock.patch.object(db, "get_blob",
                    side_effect=AssertionError("historical freshness must not load worker blobs")):
                current = assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), check, superseded=False)
            self.assertNotEqual("current", current["freshness"])
            self.assertTrue(any("unknown" in row.get("reason", "") for row in current["changes"]["records"]))


class AssessedPreparationReliabilityTests(TempCase):
    def test_assessed_helper_reuses_view_and_existing_packet_revision_conflict(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            view, assessed = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
            with mock.patch.object(controller, "derive_work", side_effect=AssertionError("must reuse assessed view")):
                prepared = controller.prepare_assessed_work(db, audit_id=fx.audit_id, mode="primary", view=view,
                    assessed=assessed, candidate_task_ids=[task["id"] for task in view["tasks"] if task["role"] == "primary"])
            self.assertTrue(prepared["prepared"], prepared)
            item = db.head("items", "itm_lem")
            fx.apply(db, [edit("replace", "items", item.id, dict(item.body, label="Changed after assessment"), item.version)])
            with self.assertRaises(ConflictError):
                controller.prepare_assessed_work(db, audit_id=fx.audit_id, mode="primary", view=view, assessed=assessed)
