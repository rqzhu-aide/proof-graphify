"""Normal stage commands finish saved work without historical-pin or retry loops."""
from copy import deepcopy
import json

from support import R, TempCase, edit, run_cli, write_json
from paper_core import assessment, controller, finalization, stage1, stage2
import test_v3_integration as integration_helpers


class CompletionTests(TempCase):
    prepared_fixture = integration_helpers.CoherentIntegrationTests.prepared_fixture
    submit = integration_helpers.CoherentIntegrationTests.submit
    examine = integration_helpers.CoherentIntegrationTests.examine
    integrate = integration_helpers.CoherentIntegrationTests.integrate

    def review_unit(self, db, fixture, name, *, prepared=None, exposure="source_only", peripheral=False, partial=False, draft=False):
        prep = prepared or stage2.prepare(db, audit_id=fixture.audit_id, focus=R("items", f"itm_{name}"))
        self.assertTrue(prep["prepared"], prep)
        response = deepcopy(prep["scaffold"])
        for row in response["judgments"]:
            row.update(state="complete", outcome="supported", reasoning="Synthetic examination of the assigned question.")
            if partial:
                row.update(extent="partial", omissions="The final inference has not been examined.")
            if draft:
                row.update(state="draft", outcome=None, next_action="Continue the saved independent examination.")
        if peripheral:
            response["judgments"].append({"reasoning": "An unrelated notation remark without a mathematical assertion."})
        envelope = {"contract_version": 4, "request_id": fixture.request_id(), "packet_id": prep["packet_id"],
            "rebase_packet_id": None, "reviewer": "fresh separate reviewer", "qualification_id": None,
            "exposure": exposure, "exposure_note": "Actual review context declared for this synthetic test."}
        result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                        response_bytes=json.dumps(response).encode())
        self.assertEqual("accepted", result["state"], result)
        return prep, result

    def integrate_unit(self, db, fixture, name, *, prepared=None, dispose=True):
        prep = prepared or stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", f"itm_{name}"))
        self.assertTrue(prep["prepared"], prep)
        response = deepcopy(prep["scaffold"])
        for row in response["integrations"]:
            row.update(decision="agree", rationale="Compared the current saved reasoning and its conditions.")
            if not dispose:
                row.pop("response_dispositions", None)
            for disposition in row.get("response_dispositions", []):
                disposition["rationale"] = "This retained notation remark asserts no mathematical defect or missing premise."
        return prep, self.submit(db, fixture, prep, response)

    def correct_application(self, db, fixture):
        application = db.head("application_details", "use_lem_thm")
        body = deepcopy(application.body)
        body["needed_form"] = {"form": "verbatim", "text": "The bound needed at the selected deterministic index."}
        fixture.apply(db, [edit("replace", "application_details", application.id, body, application.version)],
                      *fixture.ITEMS, mode="primary")

    def new_primary(self, db, fixture, *, partial=False):
        prep = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_thm"))
        self.assertTrue(prep["prepared"], prep)
        response = deepcopy(prep["scaffold"])
        for row in response["results"]:
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Compared the source.", evidence_refs=["anc_thm"])
            else:
                row.update(state="complete", outcome="supported", reasoning="Examined the corrected supplier application.",
                           evidence_refs=["anc_thm_proof"])
                if partial:
                    row.update(extent="partial", omissions="The final inference has not been examined.")
        return self.submit(db, fixture, prep, response)

    def test_current_correction_integrates_once_without_historical_pins(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.examine(db, fixture)
            self.integrate(db, fixture)
            old = {record.id: deepcopy(record.body) for record in db.heads("checks")}
            self.correct_application(db, fixture)
            changed = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertFalse(changed["progress"]["process_complete"])
            self.assertNotEqual("available", changed["support"]["items:itm_thm"])
            self.new_primary(db, fixture)
            self.review_unit(db, fixture, "thm")
            count = len(db.heads("checks"))
            prep, result = self.integrate_unit(db, fixture, "thm")
            self.assertFalse(result["remaining_task_ids"], result)
            self.assertEqual(count, len(db.heads("checks")))
            self.assertFalse(stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile")["prepared"])
            assessed = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(assessed["progress"]["process_complete"])
            self.assertIn(assessed["judgments"]["checks:chk_comp_thm"]["freshness"], ("historical", "needs_review"))
            for identity, body in old.items():
                self.assertEqual(body, db.head("checks", identity).body)
            frozen = finalization.finalize_audit(db, audit_id=fixture.audit_id, output=self.path("frozen"))
            self.assertEqual("release", frozen["kind"])

    def test_historical_whole_unit_does_not_complete_current_partial_examinations(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.examine(db, fixture)
            self.integrate(db, fixture)
            self.correct_application(db, fixture)
            result = self.new_primary(db, fixture, partial=True)
            self.assertTrue(result["remaining_task_ids"])
            self.assertIn("partial examination", " ".join(result["next_actions"]))
            # Explicit provisional review examines the same limited source question.
            prep = stage2.prepare(db, audit_id=fixture.audit_id, focus=R("items", "itm_thm"), allow_provisional=True)
            self.review_unit(db, fixture, "thm", prepared=prep, partial=True)
            assessed = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            for role in ("primary", "independent"):
                task = next(o for o in assessed["obligations"] if o["target"] == R("arguments", "arg_thm")
                            and o["kind"] == "composition" and o["role"] == role)
                self.assertFalse(task["satisfied"], task)
            self.assertFalse(assessed["progress"]["process_complete"])
            self.assertNotEqual("available", assessed["support"]["items:itm_thm"])

    def test_remaining_disposition_refreshes_only_reconciliation_context(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.review_unit(db, fixture, "lem")
            self.review_unit(db, fixture, "thm", peripheral=True)
            self.integrate_unit(db, fixture, "lem")
            first, result = self.integrate_unit(db, fixture, "thm", dispose=False)
            self.assertTrue(result["remaining_task_ids"], result)
            count = len(db.heads("checks"))
            fresh = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
            self.assertFalse(fresh["reused"])
            self.assertNotEqual(first["packet_id"], fresh["packet_id"])
            again = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
            self.assertTrue(again["reused"])
            self.assertEqual(fresh["packet_id"], again["packet_id"])
            self.integrate_unit(db, fixture, "thm", prepared=again)
            self.assertEqual(count, len(db.heads("checks")))
            self.assertTrue(assessment.derive_assessment(db, audit_id=fixture.audit_id)["progress"]["process_complete"])

    def test_compromised_review_defers_until_explicit_fresh_context(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            prep, result = self.review_unit(db, fixture, "lem", exposure="compromised")
            tid = prep["assigned_task_ids"][0]
            self.assertIn(tid, result["remaining_task_ids"])
            self.assertIn("compromised exposure", " ".join(result["next_actions"]))
            other = stage2.prepare(db, audit_id=fixture.audit_id)
            self.assertTrue(other["prepared"], other)
            self.assertNotIn(tid, other["assigned_task_ids"])
            self.review_unit(db, fixture, "thm", prepared=other)
            deferred = stage2.prepare(db, audit_id=fixture.audit_id)
            self.assertFalse(deferred["prepared"], deferred)
            self.assertTrue(any(a["code"] == "independent_context_required" for a in deferred["coordinator_actions"]))
            explicit = stage2.prepare(db, audit_id=fixture.audit_id, task_ids=[tid])
            self.review_unit(db, fixture, "lem", prepared=explicit, draft=True)
            resumed = stage2.prepare(db, audit_id=fixture.audit_id)
            self.assertTrue(resumed["prepared"], resumed)
            self.assertIn(tid, resumed["assigned_task_ids"])
            self.review_unit(db, fixture, "lem", prepared=resumed)
            self.assertEqual("compromised", db.head("responses", result["response_id"]).body["exposure"])
            self.integrate(db, fixture)
            self.assertTrue(assessment.derive_assessment(db, audit_id=fixture.audit_id)["progress"]["process_complete"])

    def test_stage_cli_replay_is_transient_and_source_row_correction_is_local(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            prep = stage1.prepare_stage(db, audit_id=fixture.audit_id)
        response = deepcopy(prep["scaffold"])
        source = next(row for row in response["results"] if row["type"] == "source_fidelity")
        response["results"] = [{"type": "check", "task_id": source["task_id"], "state": "complete",
            "outcome": "supported", "reasoning": "Wrong variant for a source comparison.", "evidence_refs": ["anc_lem"],
            "conditions": [], "next_action": None, "replaces": None, "supersedes": None}]
        path = write_json(self.path("response.json"), response)
        args = ("stage1", "examine", fixture.path, "--packet", prep["packet_id"], "--reviewer", "primary", "--response", path)
        first, _ = run_cli(*args, expect=2)
        self.assertFalse(first["replayed"])
        self.assertIn("results/0/type", first["error"]["message"])
        self.assertIn("source_fidelity", " ".join(first["diagnostics"]))
        again, _ = run_cli(*args, expect=2)
        self.assertTrue(again["replayed"])
        self.assertEqual(first["request_id"], again["request_id"])
        with fixture.open() as db:
            self.assertEqual(1, db.conn.execute("SELECT COUNT(*) FROM work_submissions").fetchone()[0])
            stored = db.work_submission(first["request_id"])["result"]
            self.assertNotIn("replayed", stored)
            self.assertEqual(0, len(db.heads("checks")))
        source.update(result="matched", note="Compared the supplied source.", evidence_refs=["anc_lem"])
        response["results"] = [source]
        write_json(path, response)
        corrected, _ = run_cli(*args)
        self.assertFalse(corrected["replayed"])
        self.assertNotEqual(first["request_id"], corrected["request_id"])
        with fixture.open() as db:
            self.assertEqual(stored, db.work_submission(first["request_id"])["result"])
            self.assertEqual(0, len(db.heads("checks")))
        self.assertIn("stage1", prep["submission_command"])
        self.assertIn("stable request ID", prep["artifact_note"])
