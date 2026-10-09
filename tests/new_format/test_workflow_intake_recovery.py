"""Useful intake and current-successor authorization at public write boundaries."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from support import Fixture, R, TempCase, edit
from paper_core import acceptance, controller, export_import, review
from paper_core.canonical import canonical_bytes, digest
from paper_core.errors import CoreError, InvalidRequest


class IntakeRecoveryTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def prepare(self):
        prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
                                           focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        return prepared

    def envelope(self, packet, reviewer="primary-1"):
        return {"contract_version": 3, "request_id": self.fx.request_id(),
                "packet_id": packet["packet_id"], "rebase_packet_id": None, "reviewer": reviewer,
                "qualification_id": None, "exposure": None, "exposure_note": ""}

    def submit(self, packet, worker, envelope=None):
        return controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope or self.envelope(packet)),
                                      response_bytes=canonical_bytes(worker))

    @staticmethod
    def draft(row):
        row.update(reasoning="The induction base holds; the supplied text does not establish the uniform step.",
                   next_action="Locate the missing uniform-step assumption and examine whether it applies.")
        return row

    def save_draft(self):
        packet = self.prepare()
        worker = copy.deepcopy(packet["scaffold"])
        row = next(row for row in worker["results"] if row["type"] == "check")
        self.draft(row)
        result = self.submit(packet, worker)
        self.assertEqual("accepted", result["state"], result)
        return row, result["record_map"][row["task_id"]]

    def continuation(self, row, pin):
        packet = self.prepare()
        worker = copy.deepcopy(packet["scaffold"])
        worker["results"] = [dict(row, replaces=pin)]
        return packet, worker

    def test_repeated_untouched_scaffolds_preserve_bytes_without_scientific_revision(self):
        packet = self.prepare()
        worker = copy.deepcopy(packet["scaffold"])
        before = export_import.export_snapshot(self.db, history=True)
        for _ in range(3):
            envelope = self.envelope(packet)
            result = self.submit(packet, worker, envelope)
            self.assertEqual("needs_revision", result["state"], result)
            self.assertEqual("NO_AUTHORED_WORK", result["error"]["code"])
            self.assertEqual(sorted(packet["assigned_task_ids"]), result["omitted_task_ids"])
            self.assertEqual(before, export_import.export_snapshot(self.db, history=True))
            intake = self.db.work_submission(envelope["request_id"])
            self.assertEqual(canonical_bytes(worker), self.db.get_blob(intake["response_sha256"]))
            self.assertEqual(result, self.submit(packet, worker, envelope))
        self.assertEqual([], self.db.heads("checks"))
        self.assertEqual([], self.db.heads("observations"))

    def test_changed_defaults_and_task_identity_are_validated_not_omitted(self):
        packet = self.prepare()
        for change in ({"outcome": "inconclusive"}, {"next_action": "Finish it"},
                       {"task_id": "obl_not_assigned"}, {"conditions": ["n is finite"]}):
            worker = copy.deepcopy(packet["scaffold"])
            row = next(row for row in worker["results"] if row["type"] == "check")
            row.update(change)
            result = self.submit(packet, worker)
            self.assertEqual("needs_revision", result["state"], result)
            self.assertNotIn(row["task_id"], result["omitted_task_ids"])
        worker = copy.deepcopy(packet["scaffold"])
        worker["results"][0]["type"] = "check"
        result = self.submit(packet, worker)
        self.assertEqual("needs_revision", result["state"])
        self.assertEqual([], result["omitted_task_ids"])

    def test_useful_missing_source_draft_is_saved_without_completion(self):
        row, pin = self.save_draft()
        stored = self.db.version("checks", pin["id"], pin["version"])
        self.assertEqual(row["reasoning"], stored.body["reasoning"])
        self.assertEqual(row["next_action"], stored.body["next_action"])
        self.assertEqual([], stored.body["evidence_refs"])
        intake = self.db.work_submissions(audit_id=self.fx.audit_id)[0]
        result = controller.inspect_work(self.db, request_id=intake["request_id"])["result"]
        self.assertEqual([pin], result["saved_draft_check_refs"])
        self.assertEqual([], result["saved_complete_check_refs"])
        self.assertEqual([], result["satisfied_task_ids"])
        self.assertIn(row["task_id"], result["remaining_task_ids"])

    def test_mixed_return_saves_completed_and_draft_checks_and_omits_comparison(self):
        packet = self.prepare()
        worker = copy.deepcopy(packet["scaffold"])
        checks = [row for row in worker["results"] if row["type"] == "check"]
        checks[0].update(state="complete", outcome="gap", reasoning="The induction step omits a necessary bound.")
        self.draft(checks[1])
        result = self.submit(packet, worker)
        self.assertEqual("accepted", result["state"], result)
        self.assertEqual(1, len(result["saved_complete_check_refs"]))
        self.assertEqual(1, len(result["saved_draft_check_refs"]))
        self.assertEqual([row["task_id"] for row in worker["results"] if row["type"] == "source_fidelity"],
                         result["omitted_task_ids"])
        self.assertEqual([], self.db.heads("observations"))
        self.assertFalse(result["no_change"])

    def test_authored_coverage_and_finding_linked_to_omitted_check_are_rejected_atomically(self):
        packet = self.prepare()
        task = next(task for task in packet["manifest"]["work"]["tasks"] if task["kind"] == "derivation")
        coverage = {"argument_id": "arg_lem", "anchor_id": "anc_lem_proof", "start_offset": 0,
                    "end_offset": 1, "classification": "substantive", "claim_refs": [R("items", "itm_lem")],
                    "check_task_ids": [task["id"]], "existing_check_refs": [], "replaces": None,
                    "note": "The first step needs its justification."}
        finding = {"target": R("groups", "grp_lem"), "category": "proof_gap",
                   "description": "The uniform induction assumption is absent.", "evidence_refs": [],
                   "related_task_ids": [task["id"]], "existing_check_refs": [], "affected_uses": [],
                   "impact_reason": "The step remains unproved."}
        before = export_import.export_snapshot(self.db, history=True)
        for field, row in (("coverage", coverage), ("findings", finding)):
            worker = copy.deepcopy(packet["scaffold"])
            worker["results"][0].update(note="The statement was compared.")
            worker[field] = [row]
            result = self.submit(packet, worker)
            self.assertEqual("OMITTED_CHECK_LINK", result["error"]["code"], result)
            self.assertEqual(task["id"], result["diagnostics"][0]["task_id"])
            self.assertEqual(before, export_import.export_snapshot(self.db, history=True))

    def test_duplicate_untouched_rows_are_not_silently_omitted(self):
        packet = self.prepare()
        worker = copy.deepcopy(packet["scaffold"])
        worker["results"].append(copy.deepcopy(worker["results"][0]))
        result = self.submit(packet, worker)
        self.assertEqual("TASK_SCOPE", result["error"]["code"])

    def test_identical_explicit_continuation_is_retained_without_version_or_binding_change(self):
        row, pin = self.save_draft()
        packet, worker = self.continuation(row, pin)
        before = export_import.export_snapshot(self.db, history=True)
        envelope = self.envelope(packet)
        result = self.submit(packet, worker, envelope)
        self.assertEqual("needs_revision", result["state"], result)
        self.assertTrue(result["no_change"])
        self.assertEqual(0, result["exit_code"])
        self.assertEqual("UNCHANGED_DRAFT", result["diagnostics"][0]["code"])
        self.assertIsNone(result["receipt"])
        self.assertIsNone(result["committed_revision"])
        self.assertEqual([pin], result["unchanged_check_refs"])
        self.assertEqual([], result["saved_draft_check_refs"])
        self.assertEqual(pin, result["record_map"][row["task_id"]])
        self.assertEqual(before, export_import.export_snapshot(self.db, history=True))
        self.assertEqual(result, self.submit(packet, worker, envelope))

    def test_same_prose_after_changed_inputs_cannot_rebind_saved_draft(self):
        row, pin = self.save_draft()
        item = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "items", item.id, dict(item.body,
            statement={"form": "verbatim", "text": "A different bound with a different quantifier."}), item.version)],
            "items:itm_lem", mode="primary")
        packet, worker = self.continuation(row, pin)
        before = export_import.export_snapshot(self.db, history=True)
        result = self.submit(packet, worker)
        self.assertEqual("conflict", result["state"], result)
        self.assertEqual("renew_affected_work", result["recovery"][0]["operation"])
        self.assertEqual(before, export_import.export_snapshot(self.db, history=True))

    def test_another_reviewer_cannot_claim_the_unchanged_draft(self):
        row, pin = self.save_draft()
        packet, worker = self.continuation(row, pin)
        result = self.submit(packet, worker, self.envelope(packet, reviewer="different-reader"))
        self.assertEqual("WRITE_SCOPE", result["error"]["code"])
        self.assertEqual(1, self.db.head("checks", pin["id"]).version)

    def test_interrupted_noop_resumes_with_same_bytes_and_no_scientific_commit(self):
        row, pin = self.save_draft()
        packet, worker = self.continuation(row, pin)
        envelope = self.envelope(packet)
        before = self.db.max_revision()
        with patch.object(controller, "derive_work", side_effect=RuntimeError("interrupted")):
            result = self.submit(packet, worker, envelope)
        self.assertEqual("received", result["state"], result)
        accepted = self.submit(packet, worker, envelope)
        self.assertEqual("needs_revision", accepted["state"], accepted)
        self.assertTrue(accepted["no_change"])
        self.assertEqual(before, self.db.max_revision())

    def test_old_terminal_receipt_replays_exactly_without_new_fields(self):
        packet = self.prepare()
        worker, envelope = packet["scaffold"], self.envelope(packet)
        historical = {"request_id": envelope["request_id"], "stored": True, "state": "needs_revision",
                      "committed_revision": None, "receipt": None, "diagnostics": ["Old authoring diagnostic"]}
        raw_envelope, raw_worker = canonical_bytes(envelope), canonical_bytes(worker)
        from paper_core.canonical import sha256_bytes
        request_digest = digest({"command": "work submit", "envelope": envelope,
                                 "response_sha256": sha256_bytes(raw_worker)})
        self.db.begin_immediate()
        self.db.insert_work_submission(request_id=envelope["request_id"], request_digest=request_digest,
            packet_id=packet["packet_id"], audit_id=self.fx.audit_id, role="primary",
            envelope_bytes=raw_envelope, response_bytes=raw_worker)
        self.db.finalize_work_submission(envelope["request_id"], state="needs_revision", result=historical)
        self.db.commit()
        self.assertEqual(historical, self.submit(packet, worker, envelope))

    def test_authored_finding_without_checks_saves_useful_partial_work(self):
        packet = self.prepare()
        worker = copy.deepcopy(packet["scaffold"])
        worker["findings"] = [{"target": R("groups", "grp_lem"), "category": "inconclusive",
            "description": "The excerpt does not state the uniform induction hypothesis.", "evidence_refs": [],
            "related_task_ids": [], "existing_check_refs": [], "affected_uses": [],
            "impact_reason": "Acquire the missing hypothesis before deciding the bound."}]
        result = self.submit(packet, worker)
        self.assertEqual("accepted", result["state"], result)
        self.assertEqual([], result["saved_complete_check_refs"])
        self.assertEqual([], result["saved_draft_check_refs"])
        self.assertEqual(1, len(self.db.heads("findings")))
        self.assertEqual([], self.db.heads("checks"))

    def test_changed_reasoning_is_saved_as_an_authorized_draft_version(self):
        row, pin = self.save_draft()
        packet, worker = self.continuation(row, pin)
        worker["results"][0]["reasoning"] += " The finite case also follows by direct substitution."
        result = self.submit(packet, worker)
        self.assertEqual("accepted", result["state"], result)
        self.assertFalse(result["no_change"])
        self.assertEqual([], result["unchanged_check_refs"])
        self.assertEqual(2, self.db.head("checks", pin["id"]).version)

    def test_mixed_unchanged_draft_and_authored_comparison_commit_only_new_content(self):
        row, pin = self.save_draft()
        packet, worker = self.continuation(row, pin)
        comparison = next(copy.deepcopy(row) for row in packet["scaffold"]["results"]
                          if row["type"] == "source_fidelity")
        comparison.update(note="Compared the exact statement with the captured lemma text.",
                          result="matched", evidence_refs=["anc_lem"])
        worker["results"].append(comparison)
        result = self.submit(packet, worker)
        self.assertEqual("accepted", result["state"], result)
        self.assertFalse(result["no_change"])
        self.assertEqual([pin], result["unchanged_check_refs"])
        self.assertEqual(1, self.db.head("checks", pin["id"]).version)
        self.assertEqual(["observations"], [changed["collection"] for changed in result["receipt"]["changed"]])


class SuccessorWriteTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def check(self, identity, predecessor=None, **kwargs):
        return Fixture.check_edit(identity, R("groups", "grp_lem"), "derivation", supersedes=predecessor, **kwargs)

    def write(self, rows):
        return self.fx.apply(self.db, rows, "items:itm_lem", mode="primary")

    def test_already_superseded_ancestor_is_rejected_with_current_candidates(self):
        self.write([self.check("chk_ancestor")])
        ancestor = self.fx.pin(self.db, "checks", "chk_ancestor")
        self.write([self.check("chk_terminal", ancestor)])
        terminal = self.fx.pin(self.db, "checks", "chk_terminal")
        before = export_import.export_snapshot(self.db, history=True)
        with self.assertRaises(InvalidRequest) as caught:
            self.write([self.check("chk_invalid_branch", ancestor)])
        self.assertEqual("PREDECESSOR_SUPERSEDED", caught.exception.code)
        self.assertEqual([terminal], caught.exception.retry["current_candidates"])
        self.assertEqual(before, export_import.export_snapshot(self.db, history=True))
        self.write([self.check("chk_next", terminal)])

    def test_duplicate_prospective_successors_are_rejected_atomically(self):
        self.write([self.check("chk_ancestor")])
        ancestor = self.fx.pin(self.db, "checks", "chk_ancestor")
        before = self.db.max_revision()
        with self.assertRaises(InvalidRequest) as caught:
            self.write([self.check("chk_a", ancestor), self.check("chk_b", ancestor)])
        self.assertEqual("DUPLICATE_SUCCESSORS", caught.exception.code)
        self.assertEqual([ancestor], caught.exception.retry["current_candidates"])
        self.assertEqual(before, self.db.max_revision())
        self.assertIsNone(self.db.head("checks", "chk_a"))
        self.assertIsNone(self.db.head("checks", "chk_b"))

    def test_new_successor_rejects_old_draft_version_in_direct_and_controller_writes(self):
        self.write([self.check("chk_draft", state="draft", outcome=None)])
        old = self.fx.pin(self.db, "checks", "chk_draft")
        packet = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
            focus=R("items", "itm_lem"))
        self.assertTrue(packet["prepared"], packet)
        task = next(t for t in packet["manifest"]["work"]["tasks"] if t["kind"] == "derivation")
        draft = self.db.head("checks", "chk_draft")
        self.write([edit("replace", "checks", draft.id, dict(draft.body, state="complete", outcome="gap",
            reasoning="The bound fails at the induction step.", next_action=None), draft.version)])
        current = self.fx.pin(self.db, "checks", "chk_draft")
        before = export_import.export_snapshot(self.db, history=True)
        with self.assertRaises(InvalidRequest) as caught:
            self.write([self.check("chk_old_pin", old)])
        self.assertEqual("PREDECESSOR_NOT_CURRENT", caught.exception.code)
        self.assertEqual([current], caught.exception.retry["current_candidates"])
        self.assertEqual(current, caught.exception.records[0]["current_predecessor"])
        self.assertEqual(before, export_import.export_snapshot(self.db, history=True))
        worker = {"packet_id": packet["packet_id"], "results": [{"type": "check", "task_id": task["id"],
            "state": "complete", "outcome": "supported", "reasoning": "Examined the changed bound.",
            "evidence_refs": [], "conditions": [], "next_action": None, "replaces": None, "supersedes": old}],
            "coverage": [], "findings": []}
        envelope = {"contract_version": 3, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
            "rebase_packet_id": None, "reviewer": "primary-1", "qualification_id": None,
            "exposure": None, "exposure_note": ""}
        result = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
            response_bytes=canonical_bytes(worker))
        self.assertEqual("PREDECESSOR_NOT_CURRENT", result["error"]["code"], result)
        self.assertEqual([current], result["recovery"][0]["current_candidates"])
        self.assertEqual(before, export_import.export_snapshot(self.db, history=True))
        self.write([self.check("chk_current_pin", current)])
        self.assertEqual(current, self.db.head("checks", "chk_current_pin").body["supersedes"])

    def test_inherited_draft_keeps_older_predecessor_pin_after_predecessor_completion(self):
        self.write([self.check("chk_parent", state="draft", outcome=None)])
        inherited = self.fx.pin(self.db, "checks", "chk_parent")
        self.write([self.check("chk_child", inherited, state="draft", outcome=None)])
        for identity in ("chk_parent", "chk_child"):
            draft = self.db.head("checks", identity)
            self.write([edit("replace", "checks", identity, dict(draft.body, state="complete", outcome="gap",
                reasoning="Examined the remaining induction step.", next_action=None), draft.version)])
        self.assertEqual(2, self.db.head("checks", "chk_parent").version)
        self.assertEqual(2, self.db.head("checks", "chk_child").version)
        self.assertEqual(inherited, self.db.head("checks", "chk_child").body["supersedes"])

    def test_inherited_same_reviewer_draft_can_complete_through_direct_write_and_controller(self):
        self.write([self.check("chk_ancestor")])
        ancestor = self.fx.pin(self.db, "checks", "chk_ancestor")
        self.write([self.check("chk_draft", ancestor, state="draft", outcome=None)])
        draft = self.db.head("checks", "chk_draft")
        replacement = edit("replace", "checks", draft.id, dict(draft.body, state="complete", outcome="gap",
                            reasoning="The bound fails at the induction step.", next_action=None), draft.version)
        self.write([replacement])
        self.assertEqual(2, self.db.head("checks", "chk_draft").version)
        terminal = self.fx.pin(self.db, "checks", "chk_draft")
        self.write([self.check("chk_next_draft", terminal, state="draft", outcome=None)])
        packet = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
                                         focus=R("items", "itm_lem"))
        task = next(t for t in packet["manifest"]["work"]["tasks"] if t["kind"] == "derivation")
        saved = self.db.head("checks", "chk_next_draft")
        worker = {"packet_id": packet["packet_id"], "results": [{"type": "check", "task_id": task["id"],
                  "state": "complete", "outcome": "supported", "reasoning": "Examined the missing step.",
                  "evidence_refs": [], "conditions": [], "next_action": None,
                  "replaces": saved.pinned, "supersedes": terminal}], "coverage": [], "findings": []}
        envelope = {"contract_version": 3, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
                    "rebase_packet_id": None, "reviewer": "primary-1", "qualification_id": None,
                    "exposure": None, "exposure_note": ""}
        result = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                        response_bytes=canonical_bytes(worker))
        self.assertEqual("accepted", result["state"], result)
        self.assertEqual(2, self.db.head("checks", "chk_next_draft").version)

    def test_distinct_current_opinions_are_preserved(self):
        rows = [self.check("chk_adverse", reviewer="reader-a", outcome="gap"),
                self.check("chk_support", reviewer="reader-b", outcome="supported")]
        self.write(rows)
        self.assertEqual("gap", self.db.head("checks", "chk_adverse").body["outcome"])
        self.assertEqual("supported", self.db.head("checks", "chk_support").body["outcome"])

    def test_import_preserves_historical_branches_and_blank_records(self):
        ancestor = self.check("chk_ancestor")
        pin = {"collection": "checks", "id": "chk_ancestor", "version": 1}
        blank = self.check("chk_blank", state="draft", outcome=None)
        blank["body"].update(reasoning="", next_action=None)
        observation = edit("create", "observations", "obs_blank", {"target": R("items", "itm_lem"),
                           "result": "needs_attention", "reviewer": "old-reader", "note": "", "evidence_refs": []})
        rows = [ancestor, self.check("chk_old_a", pin), self.check("chk_old_b", pin), blank, observation]
        receipt = acceptance.accept(self.db, request_id=self.fx.request_id(), request_digest=digest(rows),
                                    packet_id=None, edits=rows, command="import")
        snapshot = export_import.export_snapshot(self.db, history=True)
        self.assertEqual(5, len(receipt["changed"]))
        self.assertEqual("", self.db.head("checks", "chk_blank").body["reasoning"])
        self.assertEqual("", self.db.head("observations", "obs_blank").body["note"])
        self.write([self.check("chk_unrelated", reviewer="new-reader")])
        self.assertEqual(snapshot["records"], export_import.export_snapshot(self.db, revision=receipt["revision"],
                                                                          history=True)["records"])

    def test_empty_direct_authoring_rejected_but_useful_missing_source_draft_accepted(self):
        row = self.check("chk_empty", state="draft", outcome=None)
        row["body"].update(reasoning="", next_action=None)
        with self.assertRaises(InvalidRequest) as caught:
            self.write([row])
        self.assertEqual("NO_AUTHORED_WORK", caught.exception.code)
        packet = self.fx.packet(self.db, "items:itm_lem", mode="primary")
        with self.assertRaises(InvalidRequest) as caught:
            review.compare(self.db, batch=self.fx.batch([edit("create", "observations", "obs_empty", {
                "target": R("items", "itm_lem"), "result": "needs_attention", "reviewer": "primary-1",
                "note": "", "evidence_refs": []})], packet["packet_id"]))
        self.assertEqual("NO_AUTHORED_WORK", caught.exception.code)
        self.write([self.check("chk_useful", state="draft", outcome=None)])

    def test_racing_writers_cannot_create_two_successors_even_without_packet_guard_checks(self):
        self.write([self.check("chk_ancestor")])
        predecessor = self.fx.pin(self.db, "checks", "chk_ancestor")
        packet = self.fx.packet(self.db, "items:itm_lem", mode="primary")
        barrier = threading.Barrier(2)
        rows = [self.check("chk_race_a", predecessor), self.check("chk_race_b", predecessor)]
        requests = [self.fx.request_id(), self.fx.request_id()]

        def write_racing(index):
            with self.fx.open() as db:
                barrier.wait(timeout=10)
                try:
                    return acceptance.accept(db, request_id=requests[index], request_digest=digest(rows[index]),
                        packet_id=packet["packet_id"], edits=[rows[index]], command="apply", check_guards=False)
                except CoreError as exc:
                    return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write_racing, (0, 1)))
        self.assertEqual(1, sum(isinstance(result, dict) for result in results), results)
        rejected = next(result for result in results if isinstance(result, CoreError))
        self.assertEqual("PREDECESSOR_SUPERSEDED", rejected.code)
        self.assertEqual(2, len(self.db.heads("checks")))
