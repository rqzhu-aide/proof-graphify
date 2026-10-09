"""Controller behavior through real packets, acceptance and restartable intake."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Fixture, R, edit, run_cli, write_json
from paper_core import controller
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest
from paper_core.queries import status


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(self.tmp.name).audit(independent_required=False)
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def prepare(self, target="itm_lem", **kw):
        result = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
                                         focus=R("items", target), **kw)
        self.assertTrue(result["prepared"], result)
        return result

    def envelope(self, packet, **changes):
        body = {"contract_version": 3, "request_id": self.fx.request_id(),
                "packet_id": packet["packet_id"], "rebase_packet_id": None, "reviewer": "primary-1",
                "qualification_id": None, "exposure": None, "exposure_note": ""}
        body.update(changes)
        return body

    def completed(self, packet):
        worker = copy.deepcopy(packet["scaffold"])
        for result in worker["results"]:
            if result["type"] == "source_fidelity":
                result.update(result="matched", note="Compared with source", evidence_refs=["anc_lem"])
            else:
                result.update(state="complete", outcome="supported", reasoning="Explicit fixture examination",
                              evidence_refs=["anc_lem_proof"])
        tasks = packet["manifest"]["work"]["tasks"]
        derivation = next((t for t in tasks if t["kind"] == "derivation"), None)
        if derivation:
            worker["coverage"] = [{"argument_id": "arg_lem", "anchor_id": "anc_lem_proof",
                "start_offset": 0, "end_offset": len(self.db.head("anchors", "anc_lem_proof").body["excerpt"]),
                "classification": "substantive", "claim_refs": [R("items", "itm_lem")],
                "check_task_ids": [derivation["id"]], "existing_check_refs": [], "replaces": None,
                "note": "Explicit source coverage"}]
        return worker

    def submit(self, envelope, worker):
        return controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                      response_bytes=canonical_bytes(worker))

    def test_coherent_complete_batch_and_coverage(self):
        packet = self.prepare()
        self.assertEqual({t["kind"] for t in packet["manifest"]["work"]["tasks"]},
                         {"source_fidelity", "derivation", "composition"})
        result = self.submit(self.envelope(packet), self.completed(packet))
        self.assertEqual(result["state"], "accepted", result)
        self.assertEqual(len(result["receipt"]["changed"]), 5)
        next_work = controller.derive_work(self.db, audit_id=self.fx.audit_id, focus=R("items", "itm_lem"))
        self.assertTrue(all(t["state"] == "satisfied" for t in next_work["tasks"] if t["required"]),
                        next_work["tasks"])

    def test_explicit_requests_explain_prerequisites_then_return_to_requested_work(self):
        view = controller.derive_work(self.db, audit_id=self.fx.audit_id, focus=R("items", "itm_lem"))
        requested = [t["id"] for t in view["tasks"] if t["kind"] in ("derivation", "composition")]
        first = self.prepare(task_ids=requested, max_units=1)
        guidance = first["task_selection"]
        self.assertEqual(sorted(requested), guidance["requested_task_ids"])
        self.assertFalse(set(requested) & set(first["assigned_task_ids"]))
        self.assertTrue(all(row["assigned_prerequisite_task_ids"] for row in guidance["requests"]))
        self.assertEqual(first["assigned_task_ids"], guidance["assigned_task_ids"])
        self.assertEqual("accepted", self.submit(self.envelope(first), self.completed(first))["state"])
        second = self.prepare(task_ids=requested)
        self.assertTrue(set(requested) <= set(second["assigned_task_ids"]))
        self.assertTrue(all(row["assigned"] for row in second["task_selection"]["requests"]))

    def test_explicit_request_guidance_uses_final_packet_after_size_failure(self):
        view = controller.derive_work(self.db, audit_id=self.fx.audit_id)
        task = next(t for t in view["tasks"] if t["kind"] == "composition" and t["role"] == "primary")
        result = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
                                         task_ids=[task["id"]], max_bytes=1)
        self.assertFalse(result["prepared"])
        self.assertEqual([], result["task_selection"]["assigned_task_ids"])
        self.assertFalse(result["task_selection"]["requests"][0]["assigned"])

    def test_one_bad_included_result_retains_bytes_and_commits_nothing(self):
        packet = self.prepare()
        worker = self.completed(packet)
        del worker["results"][-1]["outcome"]
        envelope = self.envelope(packet)
        revision = self.db.max_revision()
        result = self.submit(envelope, worker)
        self.assertEqual(result["state"], "needs_revision", result)
        self.assertTrue(result["stored"])
        self.assertEqual(self.db.max_revision(), revision)
        row = self.db.work_submission(envelope["request_id"])
        self.assertEqual(self.db.get_blob(row["response_sha256"]), canonical_bytes(worker))
        self.assertTrue(any("outcome" in str(d) for d in result["diagnostics"]))

    def test_one_assignment_saves_five_judgments_for_two_joint_inputs(self):
        from paper_core import review
        first = self.prepare()
        self.assertEqual(self.submit(self.envelope(first), self.completed(first))["state"], "accepted")
        extra = Fixture.item_edit("itm_extra", "assumption", "Assumption 2", "anc_lem", "anc_lem_proof")
        argument = self.db.head("arguments", "arg_thm")
        group = self.db.head("groups", "grp_thm")
        supplier_use = dict(self.db.head("uses", "use_lem_thm").body)
        supplier_use["from"] = R("items", "itm_extra")
        supplier_application = dict(self.db.head("application_details", "use_lem_thm").body,
                                    use_id="use_extra_thm",
                                    needed_form={"form": "verbatim", "text": "Assumption 2 text"})
        self.fx.apply(self.db, [extra,
            edit("create", "scopes", "scp_thm", {"argument_id": "arg_thm", "parent_id": None,
                "assumptions": [R("items", "itm_extra")], "binders": [], "conditions": [], "evidence_refs": []}),
            edit("replace", "arguments", "arg_thm", {**argument.body, "scope_id": "scp_thm"}, argument.version),
            edit("replace", "groups", "grp_thm", {**group.body, "scope_id": "scp_thm"}, group.version),
            edit("create", "uses", "use_extra_thm", supplier_use),
            edit("create", "application_details", "use_extra_thm", supplier_application)], mode="primary")
        context = self.fx.packet(self.db, "items:itm_extra", mode="primary")
        review.compare(self.db, batch=self.fx.batch([edit("create", "observations", "obs_extra", {
            "target": R("items", "itm_extra"), "result": "matched", "reviewer": "primary-1",
            "note": "Fixture source comparison", "evidence_refs": ["anc_lem"]})], context["packet_id"]))
        packet = self.prepare("itm_thm")
        tasks = packet["manifest"]["work"]["tasks"]
        self.assertEqual(sorted(t["kind"] for t in tasks),
                         ["application", "application", "composition", "derivation",
                          "source_fidelity", "source_fidelity"])
        worker = copy.deepcopy(packet["scaffold"])
        for row in worker["results"]:
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Compared", evidence_refs=["anc_thm"])
            else:
                row.update(state="complete", outcome="supported", reasoning="Explicit fixture joint check",
                           evidence_refs=["anc_thm_proof"])
        worker["coverage"] = [{"argument_id": "arg_thm", "anchor_id": "anc_thm_proof",
            "start_offset": 0, "end_offset": len(self.db.head("anchors", "anc_thm_proof").body["excerpt"]),
            "classification": "substantive", "claim_refs": [R("items", "itm_thm")],
            "check_task_ids": [t["id"] for t in tasks if t["kind"] == "derivation"],
            "existing_check_refs": [], "replaces": None, "note": "Explicit joint coverage"}]
        saved = self.submit(self.envelope(packet), worker)
        self.assertEqual(saved["state"], "accepted", saved)
        self.assertEqual(len(saved["record_map"]), 6)
        self.assertEqual(len(saved["receipt"]["changed"]), 7)

    def test_wrong_task_cannot_use_context_supplier(self):
        packet = self.prepare()
        worker = self.completed(packet)
        worker["results"][-1]["task_id"] = "obl_unassigned"
        result = self.submit(self.envelope(packet), worker)
        self.assertEqual(result["error"]["code"], "TASK_SCOPE")
        self.assertTrue(result["stored"])

    def test_exact_replay_and_conflicting_reuse(self):
        packet = self.prepare()
        worker, envelope = self.completed(packet), self.envelope(packet)
        accepted = self.submit(envelope, worker)
        self.assertEqual(self.submit(envelope, worker), accepted)
        worker["results"][0]["note"] += " changed"
        result = self.submit(envelope, worker)
        self.assertEqual(result["error"]["code"], "REQUEST_ID_REUSED")
        self.assertFalse(result["stored"])
        self.assertIn("earlier work submission", result["next_actions"][0])
        self.assertIn("new request ID", result["next_actions"][0])
        self.assertIsNotNone(self.db.work_submission(envelope["request_id"]))
        self.assertEqual(self.db.max_revision(), accepted["committed_revision"])

    def test_terminal_failure_requires_new_id_for_correction_and_preserves_replay(self):
        packet = self.prepare()
        envelope, worker = self.envelope(packet), self.completed(packet)
        invalid = copy.deepcopy(worker)
        invalid["results"][-1]["task_id"] = "obl_unassigned"
        rejected = self.submit(envelope, invalid)
        self.assertTrue(rejected["stored"])
        self.assertEqual("author_response_correction", rejected["recovery"][0]["operation"])
        self.assertIn("saved receipt", " ".join(rejected["next_actions"]))
        self.assertIn("new request ID", " ".join(rejected["next_actions"]))
        self.assertEqual(rejected, self.submit(envelope, invalid))
        changed = self.submit(envelope, worker)
        self.assertEqual("REQUEST_ID_REUSED", changed["error"]["code"])
        corrected = self.submit(dict(envelope, request_id=self.fx.request_id()), worker)
        self.assertEqual("accepted", corrected["state"], corrected)
        inspected = controller.inspect_work(self.db, request_id=envelope["request_id"])
        self.assertEqual(rejected, inspected["result"])
        self.assertEqual("CURRENT_ASSIGNED_WORK_SATISFIED", inspected["current"]["recovery"][0]["reason_code"])
        self.assertTrue(inspected["current"]["analysis_complete"])
        self.assertTrue(all(t["state"] == "satisfied" for t in inspected["current"]["assigned_tasks"]))

    def test_packet_disagreement_requires_pairing_in_both_directions(self):
        original, other = self.prepare(), self.prepare("itm_thm", allow_provisional=True)
        worker = self.completed(original)
        wrong_worker = dict(worker, packet_id=other["packet_id"])
        revision = self.db.max_revision()
        for envelope, response in ((self.envelope(other), worker), (self.envelope(original), wrong_worker)):
            with self.subTest(envelope=envelope["packet_id"]):
                rejected = self.submit(envelope, response)
                self.assertEqual("PACKET_MISMATCH", rejected["error"]["code"])
                action = rejected["recovery"][0]
                self.assertEqual("inspect_assignment", action["operation"])
                self.assertEqual(envelope["packet_id"], action["envelope_packet_id"])
                self.assertEqual(response["packet_id"], action["worker_packet_id"])
                retained = self.db.work_submission(envelope["request_id"])
                self.assertEqual(canonical_bytes(response), self.db.get_blob(retained["response_sha256"]))
                self.assertEqual(revision, self.db.max_revision())
                self.assertEqual(rejected, self.submit(envelope, response))
                inspected = controller.inspect_work(self.db, request_id=envelope["request_id"])
                self.assertEqual("inspect_assignment", inspected["current"]["recovery"][0]["operation"])
        accepted = self.submit(self.envelope(original), worker)
        self.assertEqual("accepted", accepted["state"], accepted)
        # Satisfying one side does not authorize guessing which packet the author examined.
        inspected = controller.inspect_work(self.db, request_id=envelope["request_id"])
        self.assertEqual("inspect_assignment", inspected["current"]["recovery"][0]["operation"])

    def test_missing_or_nonobject_worker_identity_is_an_authoring_problem(self):
        packet = self.prepare()
        for worker in ([], {}, {"packet_id": None}, {"packet_id": []}, {"packet_id": ""}):
            with self.subTest(worker=worker):
                rejected = self.submit(self.envelope(packet), worker)
                self.assertEqual("needs_revision", rejected["state"])
                self.assertEqual("author_response_correction", rejected["recovery"][0]["operation"])
                self.assertNotEqual("PACKET_MISMATCH", rejected["error"]["code"])

    def rejected_complete_response(self):
        packet = self.prepare()
        worker, envelope = self.completed(packet), self.envelope(packet)
        malformed = copy.deepcopy(worker)
        del malformed["results"][-1]["outcome"]
        rejected = self.submit(envelope, malformed)
        self.assertEqual("needs_revision", rejected["state"], rejected)
        return packet, worker, envelope, malformed, rejected

    def test_rejected_attempt_current_advice_retains_adverse_completed_evidence(self):
        packet, worker, envelope, malformed, rejected = self.rejected_complete_response()
        outcomes = iter(("gap", "refuted"))
        for row in worker["results"]:
            if row["type"] == "check":
                row.update(outcome=next(outcomes), reasoning="Synthetic adverse examination preserved.")
        self.assertEqual("accepted", self.submit(self.envelope(packet), worker)["state"])
        revision = self.db.max_revision()
        inspected = controller.inspect_work(self.db, request_id=envelope["request_id"])
        current = inspected["current"]
        self.assertEqual("CURRENT_ASSIGNED_WORK_SATISFIED", current["recovery"][0]["reason_code"])
        self.assertEqual({"gap", "refuted"}, {t["outcome"] for t in current["assigned_tasks"] if t["kind"] != "source_fidelity"})
        self.assertTrue(all(t["judgment_refs"] for t in current["assigned_tasks"] if t["role"] == "primary" and t["kind"] != "source_fidelity"))
        self.assertIn("unresolved scientific concerns", current["recovery"][0]["message"])
        self.assertEqual(revision, self.db.max_revision())
        self.assertEqual(rejected, inspected["result"])
        self.assertEqual(rejected, self.submit(envelope, malformed))

    def test_rejected_attempt_partial_success_and_drafts_still_show_remaining_work(self):
        packet, worker, envelope, _, _ = self.rejected_complete_response()
        source_rows = [row for row in worker["results"] if row["type"] == "source_fidelity"]
        partial = dict(worker, results=source_rows, coverage=[])
        self.assertEqual("accepted", self.submit(self.envelope(packet), partial)["state"])
        current = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
        self.assertEqual("CURRENT_ASSIGNED_WORK_REMAINS", current["recovery"][0]["reason_code"])
        self.assertGreater(current["remaining_task_count"], 0)
        self.assertTrue(any(t["state"] == "satisfied" for t in current["assigned_tasks"]))
        checks = [dict(row, state="draft", outcome=None, next_action="Finish the saved reasoning.")
                  for row in worker["results"] if row["type"] == "check"]
        self.assertEqual("accepted", self.submit(self.envelope(packet), dict(worker, results=checks, coverage=[]))["state"])
        current = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
        self.assertEqual("CURRENT_ASSIGNED_WORK_REMAINS", current["recovery"][0]["reason_code"])
        self.assertTrue(any(t["judgment_refs"] for t in current["assigned_tasks"] if t["state"] != "satisfied"))

    def test_rejected_attempt_source_changes_and_conflicting_checks_keep_work_open(self):
        packet, worker, envelope, _, _ = self.rejected_complete_response()
        self.assertEqual("accepted", self.submit(self.envelope(packet), worker)["state"])
        self.fx.apply(self.db, [self.fx.check_edit("chk_conflicting", R("groups", "grp_lem"), "derivation",
                      evidence=("anc_lem_proof",), reviewer="other-primary", outcome="gap")], mode="primary")
        current = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
        self.assertEqual("CURRENT_ASSIGNED_WORK_REMAINS", current["recovery"][0]["reason_code"])
        disputed = next(t for t in current["assigned_tasks"] if t["kind"] == "derivation")
        self.assertEqual("inconclusive", disputed["outcome"])
        self.assertEqual(2, disputed["judgment_count"])
        item = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "items", item.id,
            dict(item.body, statement={"form": "synopsis", "text": "A different mathematical claim"}), item.version)], mode="primary")
        current = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
        self.assertEqual("CURRENT_ASSIGNED_WORK_REMAINS", current["recovery"][0]["reason_code"])
        self.assertTrue(any(t["freshness"] == "needs_review" for t in current["assigned_tasks"]), current)

    def test_rejected_attempt_incomplete_or_missing_current_tasks_are_not_completion(self):
        _, _, envelope, _, _ = self.rejected_complete_response()
        view = controller.derive_work(self.db, audit_id=self.fx.audit_id)
        for facts, reason in ((dict(view, analysis_complete=False, tasks=[]), "CURRENT_ANALYSIS_INCOMPLETE"),
                              (dict(view, tasks=[]), "ASSIGNMENT_RELEVANCE_UNKNOWN")):
            with self.subTest(reason=reason), patch.object(controller, "derive_work", return_value=facts):
                current = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
                self.assertEqual(reason, current["recovery"][0]["reason_code"])
                self.assertGreater(current["unknown_task_count"], 0)
        audit = self.db.head("audits", self.fx.audit_id)
        self.fx.apply(self.db, [edit("replace", "audits", audit.id,
            dict(audit.body, targets=[R("items", "itm_thm")]), audit.version)], mode="primary")
        current = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
        self.assertFalse(current["assignment_scope_current"])
        self.assertEqual("ASSIGNMENT_RELEVANCE_UNKNOWN", current["recovery"][0]["reason_code"])

    def test_pre_intake_failure_does_not_consume_an_unused_id(self):
        packet = self.prepare()
        envelope, worker = self.envelope(packet), self.completed(packet)
        rejected = self.submit(dict(envelope, unknown_field=True), worker)
        self.assertFalse(rejected["stored"])
        self.assertEqual("correct_envelope", rejected["recovery"][0]["operation"])
        self.assertIn("did not reserve", rejected["next_actions"][0])
        self.assertIsNone(self.db.work_submission(envelope["request_id"]))
        self.assertEqual("accepted", self.submit(envelope, worker)["state"])

    def test_rejected_current_inspection_uses_one_revision_despite_intervening_write(self):
        packet, worker, envelope, _, _ = self.rejected_complete_response()
        self.assertEqual("accepted", self.submit(self.envelope(packet), worker)["state"])
        revision = self.db.max_revision()
        derive = controller.derive_work

        def change_scope(db, **kwargs):
            audit = db.head("audits", self.fx.audit_id)
            self.fx.apply(db, [edit("replace", "audits", audit.id,
                dict(audit.body, targets=[R("items", "itm_thm")]), audit.version)], mode="primary")
            return derive(db, **kwargs)

        with patch.object(controller, "derive_work", side_effect=change_scope):
            current = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
        self.assertGreater(self.db.max_revision(), revision)
        self.assertEqual(revision, current["revision"])
        self.assertTrue(current["assignment_scope_current"])
        self.assertEqual("CURRENT_ASSIGNED_WORK_SATISFIED", current["recovery"][0]["reason_code"])
        fresh = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]
        self.assertEqual(self.db.max_revision(), fresh["revision"])
        self.assertFalse(fresh["assignment_scope_current"])
        self.assertEqual("ASSIGNMENT_RELEVANCE_UNKNOWN", fresh["recovery"][0]["reason_code"])

    def test_other_command_id_requires_new_id_without_work_inspection(self):
        packet = self.prepare()
        old_id = self.db.conn.execute("SELECT request_id FROM commits ORDER BY revision LIMIT 1").fetchone()[0]
        rejected = self.submit(self.envelope(packet, request_id=old_id), self.completed(packet))
        self.assertFalse(rejected["stored"])
        self.assertEqual("REQUEST_ID_REUSED", rejected["error"]["code"])
        self.assertIsNone(self.db.work_submission(old_id))
        self.assertIn("new request ID", rejected["next_actions"][0])
        self.assertIn("no work submission to inspect", rejected["next_actions"][0])

    def test_canonical_envelope_replay_does_not_depend_on_whitespace(self):
        packet = self.prepare()
        worker, envelope = self.completed(packet), self.envelope(packet)
        result = self.submit(envelope, worker)
        import json
        replay = controller.submit_work(self.db, envelope_bytes=json.dumps(envelope, indent=3).encode(),
                                         response_bytes=canonical_bytes(worker))
        self.assertEqual(result, replay)

    def test_partial_fidelity_then_rebase_unchanged_reasoning(self):
        packet = self.prepare()
        worker = self.completed(packet)
        first = {**worker, "results": [r for r in worker["results"] if r["type"] == "source_fidelity"],
                 "coverage": []}
        result = self.submit(self.envelope(packet), first)
        self.assertEqual(result["state"], "accepted", result)
        fresh = self.prepare()
        remaining = {**worker, "results": [r for r in worker["results"] if r["type"] == "check"]}
        second = self.submit(self.envelope(packet, rebase_packet_id=fresh["packet_id"]), remaining)
        self.assertEqual(second["state"], "accepted", second)
        self.assertEqual(second["receipt"]["packet_id"], packet["packet_id"])
        self.assertEqual(second["receipt"]["acceptance_packet_id"], fresh["packet_id"])

    def test_cosmetic_caption_does_not_require_new_reasoning(self):
        packet = self.prepare()
        worker = self.completed(packet)
        item = self.db.head("items", "itm_lem")
        body = {**item.body, "caption": "An improved display caption"}
        self.fx.apply(self.db, [edit("replace", "items", item.id, body, item.version)],
                      "items:itm_lem", mode="primary")
        result = self.submit(self.envelope(packet), worker)
        self.assertEqual(result["state"], "accepted", result)

    def test_consumed_statement_change_is_preserved_conflict(self):
        packet = self.prepare()
        item = self.db.head("items", "itm_lem")
        body = {**item.body, "statement": {"form": "synopsis", "text": "A different mathematical claim"}}
        self.fx.apply(self.db, [edit("replace", "items", item.id, body, item.version)],
                      "items:itm_lem", mode="primary")
        result = self.submit(self.envelope(packet), self.completed(packet))
        self.assertEqual(result["state"], "conflict", result)
        self.assertTrue(result["stored"])

    def test_interruption_after_intake_is_resumable(self):
        packet = self.prepare()
        worker, envelope = self.completed(packet), self.envelope(packet)
        with patch.object(controller, "accept_in_transaction", side_effect=RuntimeError("interrupted")):
            interrupted = self.submit(envelope, worker)
            self.assertEqual(interrupted["state"], "received")
            self.assertTrue(interrupted["stored"])
            self.assertIn("unchanged input with the same request ID", interrupted["next_actions"][0])
        row = self.db.work_submission(envelope["request_id"])
        self.assertEqual(row["state"], "received")
        inspected = controller.inspect_work(self.db, request_id=envelope["request_id"])
        self.assertIsNone(inspected["result"])
        self.assertEqual("replay_saved_submission", inspected["current"]["recovery"][0]["operation"])
        result = self.submit(envelope, worker)
        self.assertEqual(result["state"], "accepted", result)

    def test_explicit_draft_saves_without_completion(self):
        packet = self.prepare()
        worker = self.completed(packet)
        for row in worker["results"]:
            if row["type"] == "check":
                row.update(state="draft", outcome=None, next_action="Finish the argument")
        result = self.submit(self.envelope(packet), worker)
        self.assertEqual(result["state"], "accepted", result)
        self.assertEqual(len(result["remaining_task_ids"]), 2)
        self.assertFalse(status(self.db, audit_id=self.fx.audit_id)["process_complete"])

    def test_negative_judgment_is_accepted_not_transport_failure(self):
        packet = self.prepare()
        worker = self.completed(packet)
        for row in worker["results"]:
            if row["type"] == "check":
                row.update(outcome="gap", reasoning="The written argument omits the required justification.")
        result = self.submit(self.envelope(packet), worker)
        self.assertEqual(result["state"], "accepted", result)
        view = controller.derive_work(self.db, audit_id=self.fx.audit_id, focus=R("items", "itm_lem"))
        self.assertTrue(all(t["state"] == "satisfied" for t in view["tasks"] if t["required"]))

    def test_history_and_artifact_inspection(self):
        packet = self.prepare()
        info = controller.inspect_work(self.db, packet_id=packet["packet_id"])
        out = Path(self.tmp.name) / "output"
        paths = controller.write_artifacts(self.db, info, out)
        self.assertEqual(set(paths), {"worker-packet.json", "coordinator-manifest.json",
                                      "response-scaffold.json", "worker-guidance.json",
                                      "coordinator-guidance.json", "submission-envelope-template.json"})
        expected = {"worker-packet.json": info["packet"], "coordinator-manifest.json": info["manifest"],
                    "response-scaffold.json": info["scaffold"], "worker-guidance.json": info["worker_guidance"],
                    "coordinator-guidance.json": info["coordinator_guidance"],
                    "submission-envelope-template.json": info["submission_envelope_template"]}
        for name, value in paths.items():
            raw = Path(value["path"]).read_bytes()
            self.assertGreater(len(raw.splitlines()), 1)
            self.assertEqual(expected[name], json.loads(raw))
            self.assertEqual(len(raw), value["bytes"])
        self.assertEqual(controller.write_artifacts(self.db, info, out), paths)
        (out / "worker-packet.json").write_text("different")
        with self.assertRaises(InvalidRequest):
            controller.write_artifacts(self.db, info, out)
        history = controller.inspect_work(self.db, audit_id=self.fx.audit_id)
        self.assertTrue(any(row["id"] == packet["packet_id"] for row in history["entries"]))

    def test_history_paging_does_not_load_worker_blobs(self):
        first = self.prepare(max_units=1)
        self.submit(self.envelope(first), self.completed(first))
        second = self.prepare()
        before = self.db.max_revision()
        entries, cursor = [], None
        with patch.object(self.db, "get_blob", side_effect=AssertionError("history must be metadata only")):
            while True:
                page = controller.inspect_work(self.db, audit_id=self.fx.audit_id, limit=1, cursor=cursor)
                self.assertLessEqual(len(page["entries"]), 1)
                entries.extend(page["entries"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
        self.assertEqual(len(entries), len({row["key"] for row in entries}))
        self.assertTrue({first["packet_id"], second["packet_id"]} <= {row["id"] for row in entries})
        self.assertEqual(before, self.db.max_revision())

    def test_old_minified_packet_is_preserved_and_recovered_to_fresh_directory(self):
        packet = self.prepare()
        out = Path(self.tmp.name) / "old-output"
        out.mkdir()
        canonical = self.db.get_blob(self.db.packet(packet["packet_id"])["payload_sha256"])
        old = out / "worker-packet.json"
        old.write_bytes(canonical)
        with self.assertRaises(InvalidRequest) as caught:
            controller.write_artifacts(self.db, packet, out)
        self.assertEqual("OUTPUT_CONFLICT", caught.exception.code)
        self.assertIn("fresh-directory", caught.exception.retry)
        self.assertEqual(canonical, old.read_bytes())
        fresh = controller.write_artifacts(self.db, packet, Path(self.tmp.name) / "fresh-output")
        exported = Path(fresh["worker-packet.json"]["path"]).read_bytes()
        self.assertEqual(canonical, canonical_bytes(json.loads(exported)))
        self.assertEqual(canonical, self.db.get_blob(self.db.packet(packet["packet_id"])["payload_sha256"]))

    def test_reconciliation_guidance_reuses_preparation_assessment(self):
        from paper_core import assessment
        from paper_core import stages, work
        fx = Fixture(Path(self.tmp.name) / "reconcile").independent()
        with fx.open() as db:
            with patch.object(stages, "derive_full", wraps=assessment.derive_full) as calculate, \
                    patch.object(work, "derive_full", side_effect=AssertionError("duplicate work assessment")), \
                    patch.object(assessment, "derive_full", side_effect=AssertionError("duplicate assessment")):
                prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile",
                                                   focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            self.assertEqual(calculate.call_count, 1)
            self.assertTrue(prepared["coordinator_guidance"]["reconciliation_candidates"])

    def test_reconciliation_exports_stable_initial_identity_and_blank_envelope(self):
        fx = Fixture(Path(self.tmp.name) / "reconcile_stable").independent()
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            first = controller.write_artifacts(db, prepared, Path(self.tmp.name) / "stable")
            inspected = controller.inspect_work(db, packet_id=prepared["packet_id"])
            self.assertEqual(prepared["scaffold"], inspected["scaffold"])
            self.assertEqual(first, controller.write_artifacts(db, inspected, Path(self.tmp.name) / "stable"))
            envelope = prepared["submission_envelope_template"]
            self.assertEqual(prepared["initial_request_id"], envelope["request_id"])
            self.assertEqual(envelope["request_id"], prepared["scaffold"]["request_id"])
            self.assertEqual("", envelope["reviewer"])
            self.assertIsNone(envelope["qualification_id"])
            self.assertIsNone(envelope["exposure"])
            result = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope),
                                            response_bytes=canonical_bytes(prepared["scaffold"]))
            self.assertFalse(result["stored"])

    def test_artifact_io_failure_names_saved_packet_and_inspection_recovery(self):
        prepared = self.prepare()
        packets_before = self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        with patch.object(Path, "mkdir", side_effect=OSError("fixture denied write")):
            with self.assertRaises(InvalidRequest) as caught:
                controller.write_artifacts(self.db, prepared, Path(self.tmp.name) / "denied")
        self.assertEqual("ARTIFACT_WRITE_FAILED", caught.exception.code)
        self.assertIn(prepared["packet_id"], str(caught.exception))
        self.assertIn("work inspect", str(caught.exception))
        recovered = controller.inspect_work(self.db, packet_id=prepared["packet_id"])
        controller.write_artifacts(self.db, recovered, Path(self.tmp.name) / "recovered")
        self.assertEqual(packets_before, self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])

    def test_old_submission_ids_are_recovered_explicitly_without_rewriting_bytes(self):
        fx = Fixture(Path(self.tmp.name) / "old_reconciliation").independent()
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            envelope = dict(prepared["submission_envelope_template"], request_id="req_older_saved_attempt", reviewer="coordinator")
            worker = {"contract_version": 4, "request_id": envelope["request_id"], "packet_id": prepared["packet_id"],
                "edits": [fx.reconciliation_edit(db, "rec_old_attempt", "arg_lem", "chk_comp_lem", fx.independent_checks["itm_lem"])]}
            raw_envelope, raw_worker = json.dumps(envelope, indent=2).encode(), json.dumps(worker, indent=3).encode()
            saved = controller.submit_work(db, envelope_bytes=raw_envelope, response_bytes=raw_worker)
            self.assertEqual("accepted", saved["state"], saved)
            second = dict(envelope, request_id="req_explicit_second_attempt")
            second_worker = dict(worker, request_id=second["request_id"], edits=[])
            controller.submit_work(db, envelope_bytes=canonical_bytes(second), response_bytes=canonical_bytes(second_worker))
            inspected = controller.inspect_work(db, packet_id=prepared["packet_id"])
            self.assertTrue(inspected["submission_recovery"]["selection_required"])
            self.assertEqual({envelope["request_id"], second["request_id"]}, set(inspected["submission_recovery"]["request_ids"]))
            self.assertEqual(prepared["initial_request_id"], inspected["initial_request_id"])
            recovered = controller.inspect_work(db, request_id=envelope["request_id"])
            paths = controller.write_artifacts(db, recovered, Path(self.tmp.name) / "original_attempt")
            self.assertEqual(raw_envelope, Path(paths["submission-envelope.json"]["path"]).read_bytes())
            self.assertEqual(raw_worker, Path(paths["worker-response.json"]["path"]).read_bytes())
            self.assertEqual(saved, controller.submit_work(db, envelope_bytes=raw_envelope, response_bytes=raw_worker))

    def test_live_guidance_changes_require_fresh_output_without_overwriting_old_files(self):
        fx = Fixture(Path(self.tmp.name) / "live_guidance").primary()
        with fx.open() as db:
            coverage = db.head("coverage", "cov_lem")
            fx.apply(db, [edit("replace", "coverage", coverage.id,
                dict(coverage.body, end_offset=coverage.body["end_offset"] - 1), coverage.version)], mode="primary")
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            destination = Path(self.tmp.name) / "original_guidance"
            paths = controller.write_artifacts(db, prepared, destination)
            original = {name: Path(value["path"]).read_bytes() for name, value in paths.items()}
            predecessor = prepared["coordinator_guidance"]["renewal_candidates"][0]["ref"]
            fx.apply(db, [Fixture.check_edit("chk_explicit_renewal", R("arguments", "arg_lem"), "composition",
                                            supersedes=predecessor)], mode="primary")
            inspected = controller.inspect_work(db, packet_id=prepared["packet_id"])
            self.assertNotIn("renewal_candidates", inspected["coordinator_guidance"])
            with self.assertRaises(InvalidRequest) as caught:
                controller.write_artifacts(db, inspected, destination)
            self.assertEqual("OUTPUT_CONFLICT", caught.exception.code)
            self.assertIn("fresh-directory", caught.exception.retry)
            self.assertEqual(original, {name: Path(value["path"]).read_bytes() for name, value in paths.items()})
            controller.write_artifacts(db, inspected, Path(self.tmp.name) / "updated_guidance")

    def test_input_limits_and_empty_response(self):
        self.assertFalse(controller.submit_work(self.db, envelope_bytes=b"x" * 65537,
                                                response_bytes=b"{}")["stored"])
        packet = self.prepare()
        result = self.submit(self.envelope(packet), {"packet_id": packet["packet_id"],
                              "results": [], "coverage": [], "findings": []})
        self.assertEqual(result["error"]["code"], "NO_WORK")

    def test_cli_preparation_submission_and_inspection(self):
        out = Path(self.tmp.name) / "cli-packet"
        result, _ = run_cli("work", "prepare", self.fx.path, "--audit", self.fx.audit_id,
                            "--mode", "primary", "--focus", "items:itm_lem", "--out", out)
        info = controller.inspect_work(self.db, packet_id=result["packet_id"])
        worker, envelope = self.completed(info), self.envelope(info)
        worker_path = write_json(Path(self.tmp.name)/"worker.json", worker)
        envelope_path = write_json(Path(self.tmp.name)/"envelope.json", envelope)
        saved, _ = run_cli("work", "submit", self.fx.path, "--submission", envelope_path, "--response", worker_path)
        self.assertEqual(saved["state"], "accepted", saved)
        recovered, _ = run_cli("work", "inspect", self.fx.path, "--request", envelope["request_id"])
        self.assertEqual(recovered["result"]["receipt"], saved["receipt"])


if __name__ == "__main__":
    unittest.main()
