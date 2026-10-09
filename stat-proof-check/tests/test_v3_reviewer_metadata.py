"""Provenance diagnostics preserve ordinary review and authored adverse work."""
from copy import deepcopy
import json

from support import R, TempCase, edit
from paper_core import controller, review, stage1, stage2
from paper_core.errors import InvalidRequest


class ReviewerMetadataTests(TempCase):
    @staticmethod
    def raw(value):
        return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def submit(self, db, fixture, prepared, response_bytes, **metadata):
        envelope = dict(prepared["submission_envelope_template"],
                        request_id=fixture.request_id(), reviewer="checker-A")
        envelope.update(metadata)
        return controller.submit_work(db, envelope_bytes=self.raw(envelope),
                                      response_bytes=response_bytes)

    def independent_response(self, db, fixture):
        prepared = stage2.prepare(db, audit_id=fixture.audit_id, focus=R("items", "itm_thm"))
        self.assertTrue(prepared["prepared"], prepared)
        response = deepcopy(prepared["scaffold"])
        response["coverage_note"] = "The complete supplied proof leaves a monotonicity premise unjustified."
        for row in response["judgments"]:
            row.update(state="complete", outcome="gap",
                       reasoning="Boundedness alone does not establish convergence, α remains unspecified.")
        return prepared, response

    def assert_original(self, db, receipt, original):
        submission = db.work_submission(receipt["request_id"])
        self.assertEqual(original, db.get_blob(submission["response_sha256"]))

    def test_primary_metadata_correction_keeps_identical_adverse_response(self):
        fixture = self.fixture().audit(independent_required=False)
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            response = deepcopy(prepared["scaffold"])
            for row in response["results"]:
                if row["type"] == "source_fidelity":
                    row.update(result="matched", note="Compared the supplied statement.", evidence_refs=["anc_lem"])
                else:
                    row.update(state="complete", outcome="gap", evidence_refs=["anc_lem_proof"],
                               reasoning="The induction step lacks a premise, α remains unspecified.")
            original = self.raw(response)
            revision = db.max_revision()
            for metadata in ({"qualification_id": "qua_absent"}, {"exposure": "source_only"}):
                with self.subTest(metadata=metadata):
                    failed = self.submit(db, fixture, prepared, original, **metadata)
                    self.assertEqual("needs_revision", failed["state"], failed)
                    self.assertEqual("INVALID_REQUEST", failed["error"]["code"])
                    self.assertEqual("primary/reconcile work requires qualification_id and exposure to be null",
                                     failed["error"]["message"])
                    self.assertEqual(revision, db.max_revision())
                    self.assertEqual([], db.heads("checks"))
            accepted = self.submit(db, fixture, prepared, original, qualification_id=None, exposure=None)
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assert_original(db, accepted, original)
            check = db.heads("checks")[0]
            self.assertEqual("gap", check.body["outcome"])
            self.assertEqual(next(r["reasoning"] for r in response["results"] if r["type"] == "check"),
                             check.body["reasoning"])
            self.assertEqual([], db.heads("qualifications"))
            self.assertEqual(original, self.raw(response))

    def test_ordinary_null_review_retains_original_and_source_only_exposure(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            prepared, response = self.independent_response(db, fixture)
            original = self.raw(response)
            revision = db.max_revision()
            wrong_basis = self.submit(db, fixture, prepared, original, exposure="route_provided")
            self.assertEqual("REVIEW_BASIS_MISMATCH", wrong_basis["error"]["code"])
            self.assertEqual(revision, db.max_revision())
            accepted = self.submit(db, fixture, prepared, original, qualification_id=None, exposure="source_only")
            self.assertEqual("accepted", accepted["state"], accepted)
            saved = db.head("responses", accepted["response_id"])
            self.assertIsNone(saved.body["qualification_id"])
            self.assertEqual("source_only", saved.body["exposure"])
            self.assertEqual(original, db.get_blob(saved.body["original_blob"]))
            self.assert_original(db, accepted, original)
            check = next(r for r in db.heads("checks") if r.body["response_id"] == saved.id)
            self.assertEqual("gap", check.body["outcome"])
            self.assertEqual(response["judgments"][0]["reasoning"], check.body["reasoning"])
            self.assertEqual([], db.heads("qualifications"))

    def test_reconcile_metadata_correction_keeps_original_review_and_open_concern(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            independent, response = self.independent_response(db, fixture)
            original_review = self.raw(response)
            reviewed = self.submit(db, fixture, independent, original_review)
            self.assertEqual("accepted", reviewed["state"], reviewed)
            saved = db.head("responses", reviewed["response_id"])
            saved_body = deepcopy(saved.body)
            prepared = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
            self.assertTrue(prepared["prepared"], prepared)
            integration = deepcopy(prepared["scaffold"])
            for row in integration["integrations"]:
                row.update(decision="unresolved", rationale="Retain the missing monotonicity premise and disagreement.")
            finding = deepcopy(prepared["worker_guidance"]["optional_finding_example"])
            finding.update(category="proof_gap", description=response["coverage_note"],
                           evidence_refs=["anc_thm_proof"], impact_reason="Convergence remains unsupported.")
            integration["findings"] = [finding]
            original = self.raw(integration)
            revision = db.max_revision()
            failed = self.submit(db, fixture, prepared, original, qualification_id="qua_absent", exposure="source_only")
            self.assertEqual("needs_revision", failed["state"], failed)
            self.assertEqual("INVALID_REQUEST", failed["error"]["code"])
            self.assertEqual("primary/reconcile work requires qualification_id and exposure to be null",
                             failed["error"]["message"])
            self.assertEqual(revision, db.max_revision())
            self.assertEqual([], db.heads("reconciliations"))
            self.assertEqual([], db.heads("findings"))
            accepted = self.submit(db, fixture, prepared, original, qualification_id=None, exposure=None)
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assert_original(db, accepted, original)
            self.assertEqual(saved_body, db.head("responses", saved.id).body)
            self.assertEqual(original_review, db.get_blob(saved_body["original_blob"]))
            self.assertEqual("unresolved", db.heads("reconciliations")[0].body["decision"])
            self.assertEqual(finding["description"], db.heads("findings")[0].body["description"])
            self.assertEqual("open", db.heads("findings")[0].body["lifecycle"])

    def test_invalid_claimed_qualifications_still_reject_without_mutation(self):
        # Synthetic calibration receipts use the real qualification API, without head lookup mocks.
        fixture = self.fixture().primary().qualification()
        with fixture.open() as db:
            passing = db.head("qualifications", "qua_r1")
            for identity, changes in (("qua_failed", {"qualified": False}),
                                      ("qua_other_protocol", {"protocol_version": "historical-proof-audit/1"})):
                body = dict(deepcopy(passing.body), **changes)
                if not body["qualified"]:
                    body["invalid_case_results"][0]["outcome"] = "fail"
                review.record_qualification(db, receipt={"contract_version": 4, "request_id": fixture.request_id(),
                    "edits": [edit("create", "qualifications", identity, body)], "blobs": []})
            prepared, response = self.independent_response(db, fixture)
            original = self.raw(response)
            claims = {r.id: deepcopy(r.body) for r in db.heads("qualifications")}
            revision = db.max_revision()
            checks = [(r.pinned, deepcopy(r.body)) for r in db.heads("checks")]
            for qualification_id, reviewer in (("qua_absent", "checker-A"), ("qua_failed", "checker-A"),
                                               ("qua_r1", "different reviewer"), ("qua_other_protocol", "checker-A")):
                with self.subTest(qualification_id=qualification_id, reviewer=reviewer):
                    rejected = self.submit(db, fixture, prepared, original,
                                           qualification_id=qualification_id, reviewer=reviewer)
                    self.assertEqual("needs_revision", rejected["state"], rejected)
                    self.assertEqual("QUALIFICATION_INVALID", rejected["error"]["code"])
                    self.assertIn("qualification_id=null when no calibration exists", rejected["error"]["message"])
                    self.assertIn("do not clear failed qualifications", rejected["error"]["message"])
                    self.assertEqual(revision, db.max_revision())
                    self.assertEqual(checks, [(r.pinned, r.body) for r in db.heads("checks")])
                    self.assertEqual([], db.heads("responses"))
                    self.assertEqual(claims, {r.id: r.body for r in db.heads("qualifications")})

    def test_historical_protocol_keeps_qualification_requirement_and_messages(self):
        fixture = self.fixture().audit().qualification()
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            historical = dict(audit.body, protocol_version="historical-proof-audit/1")
            # Current writers prohibit new historical audits. Build this disposable reader fixture
            # through storage, leaving the accepted coherent audit and qualification untouched.
            db.insert_version("audits", "aud_historical", 1, db.max_revision(), historical)
            db.set_head("audits", "aud_historical", 1)
            manifest = {"mode": "independent", "work": {"audit_id": "aud_historical", "mode": "independent"}}
            envelope = {"reviewer": "checker-A", "qualification_id": None, "exposure": "source_only", "exposure_note": ""}
            for qid, expected in ((None, "independent work needs a live qualification"),
                                  ("qua_r1", "reviewer qualification does not match this assignment")):
                with self.subTest(qualification_id=qid), self.assertRaises(InvalidRequest) as caught:
                    controller._provenance(db, dict(envelope, qualification_id=qid), manifest)
                self.assertEqual("QUALIFICATION_INVALID", caught.exception.code)
                self.assertEqual(expected, caught.exception.message)


if __name__ == "__main__":
    import unittest
    unittest.main()
