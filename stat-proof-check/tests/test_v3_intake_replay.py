"""Historical intake receipts stay immutable after continuation or local repair.

The round-two intake fixtures use synthetic judgments to test workflow mechanics.
"""
from copy import deepcopy
import json

from support import R, TempCase, run_cli, sha, write_json
from paper_core import stage1
from paper_core.assessment import derive_assessment


class IntakeReplayTests(TempCase):
    def prepare(self, fixture, name, *, stage=1, mode="primary"):
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id, stage=stage,
                mode=mode, focus=R("items", "itm_" + name))
        self.assertTrue(prepared["prepared"], prepared)
        return prepared

    def primary_response(self, prepared, name, *, outcome="gap", partial=False, supersedes=None):
        response = deepcopy(prepared["scaffold"])
        for row in response["results"]:
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Synthetic comparison with the supplied statement.",
                           evidence_refs=["anc_" + name])
            else:
                row.update(state="complete", outcome=outcome,
                    reasoning="Synthetic adverse proof examination for intake mechanics.",
                    evidence_refs=["anc_" + name + "_proof"],
                    extent="partial" if partial else "whole_unit",
                    omissions="The induction step has not yet been examined." if partial else "")
                if supersedes:
                    row.update(replaces=None, supersedes=supersedes)
        return response

    def submit_args(self, fixture, prepared, path, *, independent=False):
        return ("stage2" if independent else "stage1", "review" if independent else "examine",
            fixture.path, "--packet", prepared["packet_id"], "--reviewer",
            "synthetic independent" if independent else "synthetic primary", "--response", path,
            *(("--exposure", "source_only") if independent else ()))

    def snapshot(self, fixture):
        with fixture.open(write=False) as db:
            submissions = {row["request_id"]: db.work_submission(row["request_id"])
                           for row in db.work_submissions(audit_id=fixture.audit_id)}
            saved = {
                "revision": db.max_revision(),
                "checks": {row.id: (row.pinned, row.body) for row in db.heads("checks")},
                "responses": {row.id: (row.pinned, row.body, db.get_blob(row.body["original_blob"]))
                              for row in db.heads("responses")},
                "submissions": submissions,
                "original_bytes": {key: db.get_blob(row["response_sha256"])
                                   for key, row in submissions.items()},
                "packets": db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0],
            }
        saved["database_sha256"] = sha(fixture.path.read_bytes())
        return saved

    def status(self, fixture, name, *, stage=1):
        return run_cli("stage" + str(stage), "status", fixture.path, "--audit", fixture.audit_id,
                       "--focus", "items:itm_" + name)[0]

    def assert_historical_receipt(self, original, replay):
        self.assertTrue(replay["replayed"], replay)
        for key, value in original.items():
            if key not in {"replayed", "next_actions"}:
                self.assertEqual(value, replay[key], key)
        guidance = " ".join(replay["next_actions"])
        self.assertIn("historical saved receipt", guidance)
        self.assertIn("saves no new work", guidance)
        self.assertIn("not current unfinished work", guidance)
        self.assertIn("current stage status", guidance)
        self.assertNotIn("Correct the named row", guidance)

    def test_partial_then_successor_then_old_replay_keeps_current_completion(self):
        fixture = self.fixture().audit(independent_required=False)
        prepared = self.prepare(fixture, "lem")
        path = write_json(self.path("partial.json"), self.primary_response(prepared, "lem", partial=True))
        args = self.submit_args(fixture, prepared, path)
        first, _ = run_cli(*args)
        self.assertEqual("accepted", first["state"], first)
        self.assertFalse(first["replayed"])
        self.assertTrue(first["remaining_task_ids"])
        before = self.snapshot(fixture)
        partial_pin, partial_body = next(iter(before["checks"].values()))
        self.assertEqual("partial", partial_body["extent"])
        self.assertEqual("gap", partial_body["outcome"])
        self.assertEqual(path.read_bytes(), before["original_bytes"][first["request_id"]])
        self.assertNotIn("replayed", before["submissions"][first["request_id"]]["result"])
        current_partial = self.status(fixture, "lem")
        self.assertTrue(current_partial["remaining_task_ids"])
        replay, _ = run_cli(*args)
        self.assert_historical_receipt(first, replay)
        self.assertEqual(before, self.snapshot(fixture))
        self.assertEqual(current_partial, self.status(fixture, "lem"))

        followup = self.prepare(fixture, "lem")
        continuation = self.primary_response(followup, "lem", supersedes=partial_pin)
        for row in continuation["results"]:
            if row["type"] == "check":
                row["reasoning"] = "Examined the remaining induction step; missing base and recurrence leave a gap."
        corrected = write_json(self.path("successor.json"), continuation)
        final, _ = run_cli(*self.submit_args(fixture, followup, corrected))
        self.assertEqual("accepted", final["state"], final)
        self.assertFalse(final["remaining_task_ids"])
        with fixture.open(write=False) as db:
            self.assertEqual(partial_body, db.version("checks", partial_pin["id"], partial_pin["version"]).body)
            self.assertTrue(all(row.body["outcome"] == "gap" for row in db.heads("checks")))
            assessment = derive_assessment(db, audit_id=fixture.audit_id)
            self.assertNotEqual("available", assessment["support"]["items:itm_lem"])
            # The unrelated theorem is unfinished, even though this local examination is done.
            self.assertFalse(assessment["progress"]["process_complete"])
        current_done = self.status(fixture, "lem")
        self.assertFalse(current_done["remaining_task_ids"])
        after_successor = self.snapshot(fixture)
        self.assertEqual(before["submissions"][first["request_id"]],
                         after_successor["submissions"][first["request_id"]])
        replay, _ = run_cli(*args)
        self.assert_historical_receipt(first, replay)
        self.assertTrue(replay["remaining_task_ids"])
        self.assertEqual(after_successor, self.snapshot(fixture))
        self.assertEqual(current_done, self.status(fixture, "lem"))

    def test_repaired_return_preserves_other_packet_and_old_rejection_replays_historically(self):
        fixture = self.fixture().audit()
        accepted_prep = self.prepare(fixture, "lem")
        accepted_path = write_json(self.path("accepted.json"),
            self.primary_response(accepted_prep, "lem", outcome="supported"))
        accepted, _ = run_cli(*self.submit_args(fixture, accepted_prep, accepted_path))
        self.assertEqual("accepted", accepted["state"], accepted)
        self.assertFalse(accepted["remaining_task_ids"])
        accepted_saved = self.snapshot(fixture)

        prepared = self.prepare(fixture, "thm")
        worker = self.primary_response(prepared, "thm")
        wrong = deepcopy(worker)
        wrong["exposure"] = "source_only"
        path = write_json(self.path("original-wrong.json"), wrong)
        original_bytes = path.read_bytes()
        args = self.submit_args(fixture, prepared, path)
        rejected, _ = run_cli(*args, expect=2)
        self.assertEqual("needs_revision", rejected["state"], rejected)
        self.assertFalse(rejected["replayed"])
        self.assertIn("exposure", json.dumps(rejected))
        self.assertIn("Correct the named row", " ".join(rejected["next_actions"]))
        rejected_saved = self.snapshot(fixture)
        self.assertEqual(original_bytes, rejected_saved["original_bytes"][rejected["request_id"]])
        self.assertTrue(self.status(fixture, "thm")["remaining_task_ids"])

        # This exact diagnosed administrative field is the only repair. Scientific rows survive.
        repaired = deepcopy(prepared["scaffold"])
        self.assertEqual({"exposure"}, set(wrong) - set(repaired))
        for key in repaired:
            repaired[key] = deepcopy(wrong[key])
        self.assertEqual(worker, repaired)
        repaired_path = write_json(self.path("repaired.json"), repaired)
        correction, _ = run_cli(*self.submit_args(fixture, prepared, repaired_path))
        self.assertEqual("accepted", correction["state"], correction)
        self.assertFalse(correction["remaining_task_ids"])
        self.assertNotEqual(rejected["request_id"], correction["request_id"])
        self.assertEqual(original_bytes, path.read_bytes())
        corrected_saved = self.snapshot(fixture)
        for request_id in (accepted["request_id"], rejected["request_id"]):
            self.assertEqual(rejected_saved["submissions"][request_id],
                             corrected_saved["submissions"][request_id])
            self.assertEqual(rejected_saved["original_bytes"][request_id],
                             corrected_saved["original_bytes"][request_id])
        for check_id, check in accepted_saved["checks"].items():
            self.assertEqual(check, corrected_saved["checks"][check_id])
        self.assertEqual(rejected_saved["responses"], corrected_saved["responses"])
        self.assertEqual(rejected_saved["packets"], corrected_saved["packets"])
        self.assertEqual(len(rejected_saved["checks"]) + 1, len(corrected_saved["checks"]))
        self.assertEqual(accepted_path.read_bytes(), corrected_saved["original_bytes"][accepted["request_id"]])
        current_done = self.status(fixture, "thm")
        self.assertFalse(current_done["remaining_task_ids"])
        replay, _ = run_cli(*args, expect=2)
        self.assert_historical_receipt(rejected, replay)
        self.assertEqual(corrected_saved, self.snapshot(fixture))
        self.assertEqual(current_done, self.status(fixture, "thm"))

    def test_accepted_stage2_replay_preserves_review_and_current_tasks(self):
        fixture = self.fixture().audit().primary()
        prepared = self.prepare(fixture, "thm", stage=2, mode="independent")
        worker = deepcopy(prepared["scaffold"])
        worker["coverage_note"] = "Synthetic separate review for intake mechanics."
        worker["exposure_report"] = {"status": "none_known", "note": "Synthetic fixture provenance."}
        for row in worker["judgments"]:
            row.update(state="complete", outcome="gap", reasoning="Synthetic independent adverse judgment.")
        path = write_json(self.path("independent.json"), worker)
        args = self.submit_args(fixture, prepared, path, independent=True)
        first, _ = run_cli(*args)
        self.assertEqual("accepted", first["state"], first)
        self.assertFalse(first["replayed"])
        self.assertFalse(first["remaining_task_ids"])
        current = self.status(fixture, "thm", stage=2)
        for task_id in prepared["assigned_task_ids"]:
            task = next(row for row in current["tasks"] if row["id"] == task_id)
            self.assertEqual("satisfied", task["state"])
        before = self.snapshot(fixture)
        self.assertIn(path.read_bytes(), [row[2] for row in before["responses"].values()])
        self.assertEqual(path.read_bytes(), before["original_bytes"][first["request_id"]])
        self.assertNotIn("replayed", before["submissions"][first["request_id"]]["result"])
        replay, _ = run_cli(*args)
        self.assert_historical_receipt(first, replay)
        self.assertEqual(before, self.snapshot(fixture))
        self.assertEqual(current, self.status(fixture, "thm", stage=2))
