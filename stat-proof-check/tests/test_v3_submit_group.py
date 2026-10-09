"""Saved group returns end after one pass and retain truthful authored input."""
from copy import deepcopy
import json
from pathlib import Path
from unittest import mock

from support import R, TempCase, edit, locator, run_cli, write_json
from paper_core import controller, returned_work, review_groups, sources, stage1, stage2
from paper_core.canonical import canonical_bytes, digest, sha256_bytes
from paper_core.errors import InvalidRequest
from paper_core.work import derive_work


class SubmitGroupTests(TempCase):
    REVIEWER = "one actual independent reviewer"

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def group(self, name="group", **kwargs):
        return review_groups.prepare_group(self.db, audit_id=self.fx.audit_id,
                                           output=self.path(name), **kwargs)

    def response(self, packet_id, *, partial=False, outcome="supported"):
        worker = deepcopy(controller.inspect_work(self.db, packet_id=packet_id)["scaffold"])
        worker["coverage_note"] = "Synthetic examination for finite-return mechanics."
        worker["exposure_report"] = {"status": "none_known", "note": "One independent source-only context."}
        for row in worker["judgments"]:
            row.update(state="complete", outcome=outcome,
                       reasoning="Synthetic source examination with the stated assumptions.",
                       extent="partial" if partial else "whole_unit",
                       omissions="The final inference remains unexamined." if partial else "")
        return worker

    def fill(self, group, *, partial=False):
        return [write_json(row["response_path"], self.response(row["packet_id"], partial=partial))
                for row in group["packets"]]

    def submit(self, group, **kwargs):
        return review_groups.submit_group(self.db, audit_id=self.fx.audit_id,
            index_path=group["group_index"], reviewer=self.REVIEWER, exposure="source_only", **kwargs)

    def count(self):
        return self.db.conn.execute("SELECT COUNT(*) FROM work_submissions").fetchone()[0]

    def entry(self, packet_id, path, **kwargs):
        return {"packet_id": packet_id, "response_path": str(path), "reviewer": self.REVIEWER,
                "exposure": "source_only", **kwargs}

    def test_stage_envelope_preserves_existing_identity_and_default_exposure(self):
        expected = {"contract_version": 4, "packet_id": "pkt_existing", "reviewer": "actual primary",
                    "qualification_id": None, "exposure": None, "exposure_note": "", "rebase_packet_id": None}
        expected["request_id"] = "req_" + digest({"command": "stage submit", "submission": expected,
                                                  "response_sha256": sha256_bytes(b"actual raw input")})
        self.assertEqual(expected, controller.stage_submission_envelope(packet_id="pkt_existing",
            reviewer="actual primary", response_bytes=b"actual raw input"))
        self.assertEqual("req_explicit", controller.stage_submission_envelope(packet_id="pkt_existing",
            reviewer="actual primary", response_bytes=b"changed input", request_id="req_explicit")["request_id"])

    def test_restart_and_formatting_do_not_resubmit_accepted_pending_work(self):
        group = self.group(max_packets=1)
        path = self.fill(group, partial=True)[0]
        first = self.submit(group)
        self.assertEqual("accepted", first["entries"][0]["state"], first)
        self.assertTrue(first["entries"][0]["remaining_task_ids"])
        self.assertEqual(1, self.count())
        original = path.read_bytes()
        request_id = first["entries"][0]["request_id"]
        restarted, _ = run_cli("stage2", "submit-group", self.fx.path, "--audit", self.fx.audit_id,
            "--group-index", group["group_index"], "--reviewer", self.REVIEWER, "--exposure", "source_only")
        self.assertEqual("already_saved", restarted["entries"][0]["status"], restarted)
        formatted = self.path("other-directory", "formatted.json")
        formatted.write_text(json.dumps(json.loads(original), indent=4, sort_keys=True), encoding="utf-8")
        repeated = self.submit(group, response_paths={group["packet_ids"][0]: formatted})
        self.assertEqual(request_id, repeated["entries"][0]["request_id"])
        self.assertEqual(1, self.count())
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(original, self.db.get_blob(self.db.work_submission(request_id)["response_sha256"]))
        delivery = json.loads(Path(group["reviewer_delivery"]).read_text(encoding="utf-8"))["instructions"]
        for field in ("response-scaffold.json", "worker-guidance.json", "question_id", "coverage_note",
                      "judgment reasoning and outcome"):
            self.assertIn(field, delivery)

    def test_malformed_first_native_return_does_not_discard_valid_second(self):
        group = self.group(max_packets=2)
        paths = self.fill(group)
        wrong = json.loads(paths[0].read_bytes())
        wrong["findings"] = [{"description": "An additional concern survives in the original file."}]
        write_json(paths[0], wrong)
        original = paths[0].read_bytes()
        result = self.submit(group)
        self.assertEqual(["deferred", "submitted"], [row["status"] for row in result["entries"]], result)
        self.assertEqual(["needs_revision", "accepted"], [row["state"] for row in result["entries"]], result)
        self.assertEqual(2, self.count())
        self.assertEqual(original, paths[0].read_bytes())
        again = self.submit(group)
        self.assertEqual(["already_saved", "already_saved"], [row["status"] for row in again["entries"]])
        self.assertEqual(2, self.count())
        repaired = deepcopy(wrong)
        repaired.pop("findings")
        repaired["coverage_note"] += " An additional concern survives in the original file."
        self.assertEqual(wrong["judgments"], repaired["judgments"])
        repaired_path = write_json(self.path("explicit-repair.json"), repaired)
        final = self.submit(group, response_paths={group["packet_ids"][0]: repaired_path})
        self.assertEqual("accepted", final["entries"][0]["state"], final)
        self.assertEqual(3, self.count())
        self.assertEqual(original, paths[0].read_bytes())

    def test_changed_explicit_adverse_return_proceeds_after_current_completion(self):
        group = self.group(max_packets=1)
        path = self.fill(group)[0]
        first = self.submit(group)
        original = path.read_bytes()
        self.assertFalse(first["entries"][0]["remaining_task_ids"])
        adverse = write_json(self.path("current-adverse.json"), self.response(group["packet_ids"][0], outcome="gap"))
        result = self.submit(group, response_paths={group["packet_ids"][0]: adverse})
        self.assertEqual("submit", result["entries"][0]["decision"], result)
        self.assertEqual("accepted", result["entries"][0]["state"], result)
        self.assertEqual(2, self.count())
        earlier = self.db.work_submission(first["entries"][0]["request_id"])
        self.assertEqual(original, self.db.get_blob(earlier["response_sha256"]))
        repeated = self.submit(group, response_paths={group["packet_ids"][0]: adverse})
        self.assertEqual("already_saved", repeated["entries"][0]["status"])
        self.assertEqual(2, self.count())

    def test_structural_comparison_preserves_json_scalar_types(self):
        group = self.group(max_packets=1)
        path = self.fill(group)[0]
        worker = json.loads(path.read_bytes())
        for value in (True, 1, 1.0):
            worker["coverage_note"] = value
            write_json(path, worker)
            result = self.submit(group)
            self.assertEqual("submit", result["entries"][0]["decision"], result)
            self.assertEqual("needs_revision", result["entries"][0]["state"], result)
        self.assertEqual(3, self.count())

    def test_missing_unreadable_nonobject_and_malformed_json_continue(self):
        group = self.group(max_packets=2)
        paths = self.fill(group)
        good_read = returned_work.read_bounded
        cases = ((b"{unfinished", "JSON_INVALID"), (b"[]", "RESPONSE_SHAPE"),
                 (b'{"packet_id":"wrong"}', "PACKET_MISMATCH"),
                 (b'{"packet_id":"wrong","packet_id":"also-wrong"}', "JSON_INVALID"),
                 (b'{"value":1e999}', "JSON_INVALID"), (b'{"value":"\\ud800"}', "JSON_INVALID"))
        for raw, code in cases:
            with self.subTest(code=code, raw=raw):
                paths[0].write_bytes(raw)
                result = self.submit(group)
                self.assertEqual("locally_failed", result["entries"][0]["status"])
                self.assertEqual(code, result["entries"][0]["error"]["code"])
                self.assertIn(result["entries"][1]["status"], ("submitted", "already_saved"))
                self.assertEqual(raw, paths[0].read_bytes())
                self.assertEqual(1, self.count())
        def unreadable(path, limit):
            if str(path) == str(paths[0]):
                raise InvalidRequest("injected permission failure", code="FILE_UNREADABLE")
            return good_read(path, limit)
        with mock.patch.object(returned_work, "read_bounded", side_effect=unreadable):
            result = self.submit(group)
        self.assertEqual("locally_failed", result["entries"][0]["status"])
        paths[0].unlink()
        result = self.submit(group)
        self.assertEqual("missing", result["entries"][0]["status"])
        self.assertEqual("already_saved", result["entries"][1]["status"])
        self.assertEqual(1, self.count())

    def test_prior_paths_need_explicit_selection_and_distinct_files_are_ambiguous(self):
        original = self.group(max_packets=1)
        old_path = self.fill(original, partial=True)[0]
        group = review_groups.reexport_group(self.db, audit_id=self.fx.audit_id,
            index_path=original["group_index"], output=self.path("reexport"))
        result = self.submit(group)
        entry = result["entries"][0]
        self.assertEqual("missing", entry["status"])
        self.assertEqual([str(old_path)], entry["existing_prior_response_paths"])
        self.assertEqual(0, self.count())
        selected = self.submit(group, response_paths={group["packet_ids"][0]: old_path})
        self.assertEqual("accepted", selected["entries"][0]["state"], selected)
        new_path = write_json(group["packets"][0]["response_path"],
                              self.response(group["packet_ids"][0], outcome="gap"))
        ambiguous = self.submit(group)
        self.assertEqual("deferred", ambiguous["entries"][0]["status"])
        self.assertEqual("RESPONSE_SELECTION", ambiguous["entries"][0]["error"]["code"])
        self.assertEqual(1, self.count())
        changed = self.submit(group, response_paths={group["packet_ids"][0]: new_path})
        self.assertEqual("accepted", changed["entries"][0]["state"], changed)
        self.assertFalse(changed["entries"][0]["remaining_task_ids"])
        self.assertEqual(2, self.count())
        with self.assertRaises(InvalidRequest):
            self.submit(group, response_paths={"pkt_unlisted": old_path})

    def test_new_wrapper_and_unrelated_revision_do_not_establish_new_work(self):
        group = self.group(max_packets=1)
        path = self.fill(group, partial=True)[0]
        first = self.submit(group)
        manifest = self.db.packet(group["packet_ids"][0])["manifest"]
        fresh = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="independent",
                                        task_ids=[task["id"] for task in manifest["work"]["tasks"]])
        self.assertNotEqual(group["packet_ids"][0], fresh["packet_id"])
        separate = dict(json.loads(path.read_bytes()), packet_id=fresh["packet_id"])
        separate_path = write_json(self.path("separately-authored-return.json"), separate)
        repeated = returned_work.consume_returns(self.db, [self.entry(fresh["packet_id"], separate_path)])
        self.assertEqual("saved_terminal_return", repeated["entries"][0]["decision"], repeated)
        self.assertEqual(first["entries"][0]["request_id"], repeated["entries"][0]["request_id"])
        thm = self.db.head("items", "itm_thm")
        self.fx.apply(self.db, [edit("replace", "items", thm.id,
            dict(thm.body, caption="Unrelated presentation revision"), thm.version)], "items:itm_thm")
        repeated = self.submit(group)
        self.assertEqual("already_saved", repeated["entries"][0]["status"])
        self.assertEqual(1, self.count())
        after_revision = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="independent",
            task_ids=[task["id"] for task in manifest["work"]["tasks"]])
        after_path = write_json(self.path("after-unrelated-revision.json"),
                               dict(separate, packet_id=after_revision["packet_id"]))
        repeated = returned_work.consume_returns(self.db, [self.entry(after_revision["packet_id"], after_path)])
        self.assertEqual("saved_terminal_return", repeated["entries"][0]["decision"], repeated)
        self.assertEqual(1, self.count())
        self.assertEqual(separate_path.read_bytes(), json.dumps(separate, ensure_ascii=False, indent=1).encode() + b"\n")

    def test_true_provenance_is_not_changed_to_match_old_attempt(self):
        group = self.group(max_packets=1)
        self.fill(group, partial=True)
        self.submit(group)
        changed = self.submit(group, exposure_note="Actual additional source-only context.")
        self.assertEqual("submit", changed["entries"][0]["decision"], changed)
        self.assertEqual(2, self.count())
        saved = self.db.work_submission(changed["entries"][0]["request_id"])
        envelope = json.loads(self.db.get_blob(saved["envelope_sha256"]))
        self.assertEqual("Actual additional source-only context.", envelope["exposure_note"])
        self.assertEqual(self.REVIEWER, envelope["reviewer"])

    def test_extended_source_context_allows_separately_authored_same_wording(self):
        extra = self.fx.source_root / "extra.txt"
        extra.write_text("A supplied neutral prerequisite.\n", encoding="utf-8")
        source_id = sources.capture_sources(self.db, files=["extra.txt"])["sources"][0]["id"]
        author = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 4, "request_id": self.fx.request_id(),
            "packet_id": author["packet_id"], "anchors": [{"id": "anc_extra", "expected_version": None,
                "source_id": source_id, "locator": locator(start=1, end=1)}]})
        group = self.group(max_packets=1)
        old_path = self.fill(group, partial=True)[0]
        first = self.submit(group)
        old_packet_id = group["packet_ids"][0]
        extended = controller.extend_work(self.db, packet_id=old_packet_id, request={
            "source_refs": [self.fx.pin(self.db, "anchors", "anc_extra")],
            "reason": "Deliver additional captured neutral source context."})
        old_manifest = self.db.packet(old_packet_id)["manifest"]
        self.assertEqual(old_manifest["work"]["tasks"], extended["manifest"]["work"]["tasks"])
        self.assertTrue(returned_work._fresh(self.db, old_manifest))
        self.assertTrue(returned_work._fresh(self.db, extended["manifest"]))
        # This fixture supplies a separate authored return for the extra context;
        # repeated wording alone does not establish that its context is unchanged.
        authored = dict(json.loads(old_path.read_bytes()), packet_id=extended["packet_id"])
        new_path = write_json(self.path("extended-return.json"), authored)
        result = returned_work.consume_returns(self.db, [self.entry(extended["packet_id"], new_path)])
        self.assertEqual("submit", result["entries"][0]["decision"], result)
        self.assertEqual("accepted", result["entries"][0]["state"], result)
        self.assertNotEqual(first["entries"][0]["request_id"], result["entries"][0]["request_id"])
        self.assertEqual(2, self.count())

    def test_changed_source_defers_old_assignment_without_rebinding_packet(self):
        group = self.group(max_packets=1)
        path = self.fill(group)[0]
        original = path.read_bytes()
        source = self.fx.source_root / "paper.tex"
        source.write_text(source.read_text(encoding="utf-8").replace("By induction on", "By a different induction on"),
                          encoding="utf-8")
        sources.capture_sources(self.db, files=["paper.tex"])
        result = self.submit(group)
        self.assertEqual("changed_context_requires_affected_work", result["entries"][0]["decision"], result)
        self.assertEqual(0, self.count())
        self.assertEqual(original, path.read_bytes())
        self.assertTrue(result["remaining_task_ids"])

    def test_current_question_can_reuse_wording_without_reusing_stale_support(self):
        fixture = self.fixture("primary").audit(independent_required=False)
        with fixture.open() as db:
            old = stage1.prepare_stage(db, audit_id=fixture.audit_id, stage=1, mode="primary",
                                       focus=R("items", "itm_lem"))
            def response(prepared):
                worker = deepcopy(prepared["scaffold"])
                worker["results"] = [row for row in worker["results"] if row["type"] == "source_fidelity"]
                for row in worker["results"]:
                    row.update(result="needs_attention", note="Synthetic source limitation.", evidence_refs=["anc_lem"])
                return worker
            old_path = write_json(self.path("old-primary.json"), response(old))
            entry = {"packet_id": old["packet_id"], "response_path": str(old_path), "reviewer": "actual primary"}
            first = returned_work.consume_returns(db, [entry])
            self.assertEqual("accepted", first["entries"][0]["state"], first)
            item, spec = db.head("items", "itm_lem"), db.head("target_specs", "tgt_lem")
            statement = dict(item.body["statement"], text="For every n >= 2, a_n <= 1.")
            fixture.apply(db, [edit("replace", "items", item.id, dict(item.body, statement=statement), item.version),
                edit("replace", "target_specs", spec.id, dict(spec.body,
                     statement_ref=dict(spec.body["statement_ref"], version=item.version + 1)), spec.version)],
                "items:itm_lem", mode="primary")
            current = stage1.prepare_stage(db, audit_id=fixture.audit_id, stage=1, mode="primary",
                                           focus=R("items", "itm_lem"))
            self.assertNotEqual(old["packet_id"], current["packet_id"])
            historical = returned_work.consume_returns(db, [entry])
            self.assertEqual("already_saved", historical["entries"][0]["status"])
            self.assertTrue(historical["entries"][0]["diagnostics"])
            new_path = write_json(self.path("current-primary.json"), response(current))
            # A separate current return may use identical words; its current
            # assignment is the distinction, not a prose novelty requirement.
            new = returned_work.consume_returns(db, [dict(entry, packet_id=current["packet_id"], response_path=str(new_path))])
            self.assertEqual("submit", new["entries"][0]["decision"], new)
            self.assertEqual("accepted", new["entries"][0]["state"], new)
            self.assertEqual(2, db.conn.execute("SELECT COUNT(*) FROM work_submissions").fetchone()[0])
            current_tasks = derive_work(db, audit_id=fixture.audit_id)["tasks"]
            self.assertEqual(sorted(task["id"] for task in current_tasks if task["required"]
                                   and task["state"] != "satisfied"), new["remaining_task_ids"])

    def test_received_recovers_exact_saved_bytes_even_after_current_completion(self):
        group = self.group(max_packets=1)
        path = self.fill(group, partial=True)[0]
        raw = path.read_bytes()
        packet_id = group["packet_ids"][0]
        envelope = controller.stage_submission_envelope(packet_id=packet_id, reviewer=self.REVIEWER,
            response_bytes=raw, exposure="source_only")
        saved_envelope = canonical_bytes(envelope)
        with mock.patch.object(controller, "_review_plan", side_effect=RuntimeError("interrupted processing")):
            interrupted = controller.submit_work(self.db, envelope_bytes=saved_envelope, response_bytes=raw)
        self.assertEqual("received", interrupted["state"], interrupted)
        # Another explicitly submitted whole return can fulfill current work.
        whole = canonical_bytes(self.response(packet_id))
        other_envelope = controller.stage_submission_envelope(packet_id=packet_id, reviewer=self.REVIEWER,
            response_bytes=whole, exposure="source_only")
        complete = controller.submit_work(self.db, envelope_bytes=canonical_bytes(other_envelope), response_bytes=whole)
        self.assertEqual("accepted", complete["state"], complete)
        self.assertFalse(complete["remaining_task_ids"])
        path.write_text(json.dumps(json.loads(raw), indent=4, sort_keys=True), encoding="utf-8")
        real_submit = returned_work.submit_work
        with mock.patch.object(returned_work, "submit_work", wraps=real_submit) as resumed:
            recovered = self.submit(group)
        self.assertEqual("recover_received", recovered["entries"][0]["decision"], recovered)
        resumed.assert_called_once_with(self.db, envelope_bytes=saved_envelope, response_bytes=raw)
        saved = self.db.work_submission(envelope["request_id"])
        self.assertNotEqual("received", saved["state"])
        self.assertEqual(raw, self.db.get_blob(saved["response_sha256"]))
        self.assertEqual(saved_envelope, self.db.get_blob(saved["envelope_sha256"]))
        self.assertEqual(2, self.count())

    def test_integration_correction_stays_outside_finite_submission(self):
        fixture = self.fixture("complete").complete()
        with fixture.open() as db:
            task = next(task for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]
                        if task["role"] == "coordinator")
            prepared = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", task_ids=[task["id"]], correct=True)
            before = db.conn.execute("SELECT COUNT(*) FROM work_submissions").fetchone()[0]
            response = deepcopy(prepared["scaffold"])
            for row in response["integrations"]:
                row.update(decision="unresolved", rationale="Keep the saved disagreement explicitly unresolved.")
            path = write_json(self.path("integration-correction.json"), response)
            result = returned_work.consume_returns(db, [self.entry(prepared["packet_id"], path)])
            self.assertEqual("use_existing_integration_route", result["entries"][0]["decision"])
            self.assertEqual(before, db.conn.execute("SELECT COUNT(*) FROM work_submissions").fetchone()[0])
            envelope = controller.stage_submission_envelope(packet_id=prepared["packet_id"],
                reviewer="coordinator", response_bytes=path.read_bytes())
            accepted = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=path.read_bytes())
            self.assertEqual("accepted", accepted["state"], accepted)


if __name__ == "__main__":
    import unittest
    unittest.main()
