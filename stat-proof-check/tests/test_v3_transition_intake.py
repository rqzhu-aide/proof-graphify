"""Returned subsets and replay do not discard work or strand other assignments."""
from copy import deepcopy
import json

from support import PROOFCHECK, R, TempCase, edit, run_wrapper, write_json
from paper_core import assessment, assistance, controller, packets, review, stage1
from paper_core.errors import ConflictError


class TransitionIntakeTests(TempCase):
    def prepare_fixture(self, *, matched):
        fixture = self.fixture().anchors()
        for key, statement, proof in (("alpha", "anc_lem", "anc_lem_proof"),
                                      ("beta", "anc_thm", "anc_thm_proof")):
            definition = {"key": key, "kind": "lemma", "label": key,
                "statement": "Synthetic claim " + key, "statement_anchors": [statement],
                "proof_anchors": [proof], "proof_complete": True,
                "source_matched": matched, "source_note": "Synthetic source comparison."}
            run_wrapper(PROOFCHECK, "stage1", "add-unit", fixture.path,
                        "--input", write_json(self.path(key + ".json"), definition))
        audit, _ = run_wrapper(PROOFCHECK, "stage1", "scope", fixture.path, "--mode", "full")
        fixture.audit_id = audit["audit_id"]
        return fixture

    def submit(self, db, fixture, prepared, response, *, request_id=None):
        envelope = dict(prepared["submission_envelope_template"],
                        reviewer="synthetic primary", request_id=request_id or fixture.request_id())
        raw = json.dumps(response).encode()
        return controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(), response_bytes=raw), raw

    def test_usable_adverse_subset_preserves_rejected_original_and_unfinished_math(self):
        fixture = self.prepare_fixture(matched=False)
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id,
                focus=R("items", "itm_alpha"), allow_provisional=True, max_units=10)
            response = deepcopy(prepared["scaffold"])
            for row in response["results"]:
                if row["type"] == "source_fidelity":
                    row.update(result="needs_attention", note="Retain this adverse source comparison.")
                else:
                    row.update(state="complete", outcome="gap", reasoning="A material missing inference.")
                    del row["conditions"]
                    math_id = row["task_id"]
            rejected, original = self.submit(db, fixture, prepared, response)
            self.assertEqual("needs_revision", rejected["state"])
            subset = deepcopy(response)
            subset["results"] = [row for row in response["results"] if row["type"] == "source_fidelity"]
            self.assertEqual(2, len(subset["results"]))
            accepted, _ = self.submit(db, fixture, prepared, subset)
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assertIn(math_id, accepted["remaining_task_ids"])
            self.assertFalse(db.heads("checks"))
            saved = db.work_submission(rejected["request_id"])
            self.assertEqual(original, db.get_blob(saved["response_sha256"]))
            current = stage1.stage_status(db, audit_id=fixture.audit_id)
            self.assertIn(math_id, current["remaining_task_ids"])

    def test_replay_defers_only_unchanged_work_and_reused_packet_allows_continuation(self):
        fixture = self.prepare_fixture(matched=True)
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_alpha"))
            response = deepcopy(prepared["scaffold"])
            for row in response["results"]:
                self.assertEqual("check", row["type"])
                row.update(state="complete", outcome="inconclusive", reasoning="Examined the first part.",
                           extent="partial", omissions="The final inference remains unexamined.")
            accepted, _ = self.submit(db, fixture, prepared, response)
            self.assertTrue(accepted["remaining_task_ids"])
            revision = db.max_revision()
            replay, _ = self.submit(db, fixture, prepared, response, request_id=accepted["request_id"])
            self.assertEqual(accepted, replay)
            self.assertEqual(revision, db.max_revision())
            other = stage1.prepare_stage(db, audit_id=fixture.audit_id,
                                         exclude_task_ids=prepared["assigned_task_ids"])
            self.assertTrue(other["prepared"])
            self.assertTrue(set(other["assigned_task_ids"]).isdisjoint(prepared["assigned_task_ids"]))
            reused = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_alpha"))
            self.assertTrue(reused["reused"])
            self.assertEqual(prepared["packet_id"], reused["packet_id"])
            for row in response["results"]:
                row.update(outcome="supported", reasoning="Now examined the remaining inference.",
                           extent="whole_unit", omissions="")
            completed, _ = self.submit(db, fixture, reused, response)
            self.assertEqual("accepted", completed["state"], completed)
            self.assertFalse(completed["remaining_task_ids"])

    def test_finding_template_uses_reconcile_scope_and_preserves_other_concerns(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            body = {"audit_id": fixture.audit_id, "target": R("arguments", "arg_thm"),
                "category": "proof_gap", "description": "A particular saved concern.",
                "evidence_refs": ["anc_thm_proof"], "check_refs": [], "affected_uses": [],
                "impact_reason": "This concern affects the written inference.",
                "lifecycle": "open", "resolution": None}
            fixture.apply(db, [edit("create", "findings", "fnd_wording", body),
                               edit("create", "findings", "fnd_other", dict(body,
                                    description="A distinct concern that remains open."))], mode="primary")
            original = db.head("findings", "fnd_wording")
            other = db.head("findings", "fnd_other")
            opinions = {collection: [(row.pinned, deepcopy(row.body)) for row in db.heads(collection)]
                        for collection in ("checks", "responses", "reconciliations")}
            packet = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="reconcile")
            # This allowance is for finding disposition, not structural editing.
            with self.assertRaises(ConflictError):
                assistance.authoring_template("items", packet_id=packet["packet_id"],
                                               record_id="itm_thm", db=db)
            unrelated = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="reconcile")
            with self.assertRaises(ConflictError):
                assistance.authoring_template("findings", packet_id=unrelated["packet_id"],
                                               record_id=original.id, db=db)
            response = assistance.authoring_template("findings", packet_id=packet["packet_id"],
                                                     record_id=original.id, db=db)
            replacement = response["template"]["edits"][0]
            self.assertEqual(original.version, replacement["expected_version"])
            self.assertEqual(original.body, replacement["body"])
            replacement["body"].update(category="presentation",
                description="Clarify the wording of this already examined inference.",
                impact_reason="The saved adopted reasoning addresses the mathematical concern.")
            review.reconcile(db, batch=response["template"])
            current = db.head("findings", original.id)
            self.assertEqual("presentation", current.body["category"])
            self.assertEqual("open", current.body["lifecycle"])
            self.assertEqual(original.body, db.version("findings", original.id, original.version).body)
            self.assertEqual(other.pinned, db.head("findings", other.id).pinned)
            self.assertEqual(other.body, db.head("findings", other.id).body)
            self.assertEqual(opinions, {collection: [(row.pinned, row.body) for row in db.heads(collection)]
                                      for collection in opinions})
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(result["progress"]["process_complete"])
            self.assertNotEqual("available", result["support"]["items:itm_thm"])
            with self.assertRaises(ConflictError):
                assistance.authoring_template("findings", packet_id=packet["packet_id"],
                                               record_id=original.id, db=db)
