"""Record a new integration concern without another proof examination."""
from copy import deepcopy
import json

from support import R, TempCase, edit
from paper_core import assessment, controller, finalization, stage1, stage2
from paper_core.contract import WORK_FINDING, validate_shape


class IntegrationFindingTests(TempCase):
    def prepare(self, db, fixture, target="itm_thm", **kwargs):
        prepared = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile",
                                 focus=R("items", target), **kwargs)
        self.assertTrue(prepared["prepared"], prepared)
        response = deepcopy(prepared["scaffold"])
        for row in response["integrations"]:
            row.update(decision="agree", rationale="Compared the saved examinations and retained the material qualification.")
        return prepared, response

    def finding(self, prepared):
        row = deepcopy(prepared["worker_guidance"]["optional_finding_example"])
        row.update(category="proof_gap", description="The written argument leaves its joint premise unjustified.",
                   evidence_refs=["anc_thm_proof"], impact_reason="The conclusion remains conditional on this premise.")
        return row

    def submit(self, db, fixture, prepared, response, request_id=None):
        envelope = dict(prepared["submission_envelope_template"],
                        request_id=request_id or fixture.request_id(), reviewer="coordinator")
        return controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                      response_bytes=json.dumps(response).encode())

    def test_finding_and_integration_commit_together_without_new_checks_or_repeated_review(self):
        fixture = self.fixture().independent()
        with fixture.open() as db:
            originals = {(r.collection, r.id): (r.pinned, deepcopy(r.body))
                         for collection in ("checks", "responses") for r in db.heads(collection)}
            response_bytes = {r.id: db.get_blob(r.body["original_blob"]) for r in db.heads("responses")}
            before = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            prepared, response = self.prepare(db, fixture)
            finding = self.finding(prepared)
            # The ordinary route does not require callers to construct empty linking fields.
            del finding["existing_check_refs"], finding["affected_uses"]
            response["findings"] = [finding]
            request_id = fixture.request_id()
            result = self.submit(db, fixture, prepared, response, request_id)
            self.assertEqual("accepted", result["state"], result)
            pin = result["finding_refs"][0]
            saved = db.head("findings", pin["id"])
            reconciliation = next(r for r in db.heads("reconciliations")
                                  if r.body["target"] == R("arguments", "arg_thm"))
            self.assertEqual(saved.revision, reconciliation.revision)
            self.assertEqual(pin, saved.pinned)
            self.assertEqual(fixture.audit_id, saved.body["audit_id"])
            self.assertEqual("open", saved.body["lifecycle"])
            self.assertIsNone(saved.body["resolution"])
            self.assertEqual([], saved.body["affected_uses"])
            self.assertEqual(reconciliation.body["primary_checks"] + reconciliation.body["independent_checks"],
                             saved.body["check_refs"])
            self.assertTrue(saved.body["check_refs"])
            revision = db.max_revision()
            self.assertEqual(result, self.submit(db, fixture, prepared, response, request_id))
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(1, len(db.heads("findings")))
            other, unchanged = self.prepare(db, fixture, "itm_lem")
            self.assertEqual("accepted", self.submit(db, fixture, other, unchanged)["state"])
            after = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual({o["id"] for o in before["obligations"]}, {o["id"] for o in after["obligations"]})
            self.assertTrue(after["progress"]["process_complete"])
            self.assertNotEqual("available", after["support"]["items:itm_thm"])
            for (collection, identity), (original_pin, body) in originals.items():
                self.assertEqual(original_pin, db.head(collection, identity).pinned)
                self.assertEqual(body, db.head(collection, identity).body)
            for identity, raw in response_bytes.items():
                self.assertEqual(raw, db.get_blob(db.head("responses", identity).body["original_blob"]))
            self.assertFalse(stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile")["prepared"])
            frozen = finalization.finalize_audit(db, audit_id=fixture.audit_id, output=self.path("frozen"))
            self.assertEqual("release", frozen["kind"], frozen["finalization_blockers"])

    def test_empty_and_omitted_findings_keep_existing_integration_compatible(self):
        for omitted in (False, True):
            with self.subTest(omitted=omitted):
                fixture = self.fixture(str(omitted)).independent()
                with fixture.open() as db:
                    prepared, response = self.prepare(db, fixture)
                    self.assertEqual([], response["findings"])
                    if omitted:
                        del response["findings"]
                    result = self.submit(db, fixture, prepared, response)
                    self.assertEqual("accepted", result["state"], result)
                    self.assertEqual([], db.heads("findings"))

    def test_invalid_finding_keeps_integration_atomic_and_local(self):
        fixture = self.fixture().independent()
        with fixture.open() as db:
            prepared, response = self.prepare(db, fixture)
            for field, value in (("related_task_ids", []), ("related_task_ids", ["unassigned_task"]),
                                 ("target", R("arguments", "arg_lem")),
                                 ("evidence_refs", ["anc_unknown"]),
                                 ("affected_uses", ["use_unknown"]),
                                 ("existing_check_refs", [db.head("checks", "chk_comp_lem").pinned]),
                                 ("impact_reason", "")):
                with self.subTest(field=field, value=value):
                    finding = self.finding(prepared)
                    finding[field] = value
                    response["findings"] = [finding]
                    revision = db.max_revision()
                    result = self.submit(db, fixture, prepared, response)
                    self.assertIn(result["state"], ("needs_revision", "conflict"), result)
                    self.assertEqual(revision, db.max_revision())
                    self.assertEqual([], db.heads("findings"))
                    self.assertEqual([], db.heads("reconciliations"))

    def test_changed_claim_cannot_accept_a_finding_using_stale_integration(self):
        fixture = self.fixture().independent()
        with fixture.open() as db:
            prepared, response = self.prepare(db, fixture)
            response["findings"] = [self.finding(prepared)]
            item = db.head("items", "itm_thm")
            fixture.apply(db, [edit("replace", "items", item.id, dict(item.body,
                statement={"form": "verbatim", "text": "A materially different conclusion."}), item.version)])
            revision = db.max_revision()
            result = self.submit(db, fixture, prepared, response)
            self.assertIn(result["state"], ("needs_revision", "conflict"), result)
            self.assertEqual(revision, db.max_revision())
            self.assertEqual([], db.heads("findings"))
            self.assertEqual([], db.heads("reconciliations"))
            self.assertFalse(assessment.derive_assessment(db, audit_id=fixture.audit_id)["progress"]["process_complete"])

    def test_finding_category_preserves_its_scientific_effect_without_extra_work(self):
        for category, expected in (("presentation", "available"), ("inconclusive", "conditional")):
            with self.subTest(category=category):
                fixture = self.fixture(category).independent()
                with fixture.open() as db:
                    before = assessment.derive_assessment(db, audit_id=fixture.audit_id)
                    prepared, response = self.prepare(db, fixture)
                    row = self.finding(prepared)
                    row.update(category=category, affected_uses=["use_lem_thm"],
                               description="A restriction on this application needs explanation.")
                    response["findings"] = [row]
                    result = self.submit(db, fixture, prepared, response)
                    self.assertEqual("accepted", result["state"], result)
                    other, remaining = self.prepare(db, fixture, "itm_lem")
                    self.assertEqual("accepted", self.submit(db, fixture, other, remaining)["state"])
                    after = assessment.derive_assessment(db, audit_id=fixture.audit_id)
                    self.assertTrue(after["progress"]["process_complete"])
                    self.assertEqual(expected, after["support"]["items:itm_thm"])
                    self.assertEqual({o["id"] for o in before["obligations"]},
                                     {o["id"] for o in after["obligations"]})

    def test_affected_use_must_belong_to_related_integration_unit(self):
        fixture = self.fixture().independent()
        with fixture.open() as db:
            prepared, response = self.prepare(db, fixture, "itm_lem")
            row = self.finding(prepared)
            row.update(evidence_refs=["anc_lem_proof"], affected_uses=["use_lem_thm"])
            response["findings"] = [row]
            result = self.submit(db, fixture, prepared, response)
            self.assertEqual("needs_revision", result["state"], result)
            self.assertIn("affected_uses is outside", result["error"]["message"])
            self.assertEqual([], db.heads("findings"))
            self.assertEqual([], db.heads("reconciliations"))

    def test_finding_does_not_supply_missing_independent_review(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            prepared, response = self.prepare(db, fixture, allow_provisional=True)
            response["findings"] = [self.finding(prepared)]
            result = self.submit(db, fixture, prepared, response)
            self.assertEqual("accepted", result["state"], result)
            saved = db.head("findings", result["finding_refs"][0]["id"])
            self.assertTrue(all(db.head("checks", pin["id"]).body["role"] == "primary"
                                for pin in saved.body["check_refs"]))
            frozen = finalization.finalize_audit(db, audit_id=fixture.audit_id, output=self.path("working"))
            self.assertEqual("working", frozen["kind"])
            self.assertFalse(frozen["process_complete"])

    def test_primary_example_has_all_existing_fields_without_a_required_finding(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id)
            self.assertTrue(prepared["prepared"])
            self.assertEqual([], prepared["scaffold"]["findings"])
            example = prepared["worker_guidance"]["optional_finding_example"]
            self.assertEqual([], validate_shape(WORK_FINDING, example))
            self.assertEqual([], example["existing_check_refs"])
            self.assertEqual([], example["affected_uses"])
            self.assertTrue(all(tid in prepared["assigned_task_ids"] for tid in example["related_task_ids"]))


if __name__ == "__main__":
    import unittest
    unittest.main()
