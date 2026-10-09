"""Retained incomplete reviews neither earn credit nor block corrected accepted reviews."""
from __future__ import annotations

from support import R, TempCase
from paper_core import review
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest


class ReconciliationRecoveryTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def pending_response(self, *, judgments=1):
        packet = self.fx.packet(self.db, "items:itm_lem", mode="independent")
        worker = {"packet_id": packet["packet_id"], "covered_targets": [R("items", "itm_lem")],
            "coverage_note": "Source-based checking attempt", "exposure_report": {"status": "none_known", "note": ""},
            "judgments": [{"target": {"source_anchor_id": "anc_lem_proof", "description": f"Proof claim {i}"},
                "kind": "composition", "state": "complete", "outcome": "supported",
                "reasoning": "Independent source-based judgment", "evidence_refs": ["anc_lem_proof"],
                "conditions": [], "next_action": None, "supersedes": None} for i in range(judgments)]}
        raw = canonical_bytes(worker)
        result = review.submit_review(self.db, submission={"contract_version": 3,
            "request_id": self.fx.request_id(), "packet_id": packet["packet_id"], "reviewer": "checker-A",
            "qualification_id": "qua_r1", "exposure": "source_only", "exposure_note": ""}, response_bytes=raw)
        self.assertEqual("needs_revision", result["state"])
        return result, raw

    def reconcile(self, id, check_ids):
        packet = self.fx.packet(self.db, "items:itm_lem", mode="reconcile")
        entry = self.fx.reconciliation_edit(self.db, id, "arg_lem", "chk_comp_lem", check_ids[0])
        entry["body"]["independent_checks"] = [self.fx.pin(self.db, "checks", cid) for cid in check_ids]
        return review.reconcile(self.db, batch=self.fx.batch([entry], packet["packet_id"]))

    def test_pending_original_survives_corrected_accepted_review_and_reconciliation(self):
        pending, raw = self.pending_response()
        original = self.db.head("responses", pending["response_id"])
        self.fx.independent()
        corrected = self.fx.independent_checks["itm_lem"]
        self.reconcile("rec_corrected", [corrected])
        retained = self.db.head("responses", pending["response_id"])
        self.assertEqual(original.pinned, retained.pinned)
        self.assertEqual("needs_revision", retained.body["state"])
        self.assertEqual(raw, self.db.get_blob(retained.body["original_blob"]))
        self.assertEqual([], [c for c in self.db.heads("checks") if c.body["response_id"] == retained.id])
        stored = self.db.head("reconciliations", "rec_corrected")
        self.assertEqual([corrected], [r["id"] for r in stored.body["independent_checks"]])

    def test_listed_partially_mapped_check_cannot_gain_credit_from_pending_response(self):
        pending, _ = self.pending_response(judgments=2)
        packet = self.fx.packet(self.db, "items:itm_lem", mode="primary")
        mapped = review.map_response(self.db, mapping={"contract_version": 3,
            "request_id": self.fx.request_id(), "packet_id": packet["packet_id"], "response_id": pending["response_id"],
            "entries": [{"judgment_index": 0, "target": R("arguments", "arg_lem"),
                         "rationale": "The first source judgment describes this argument"}], "reviewer": "coordinator"})
        self.assertEqual("needs_revision", mapped["state"])
        partial_check = mapped["checks"][0]["check_id"]
        self.fx.independent()
        before = self.db.max_revision()
        with self.assertRaises(InvalidRequest) as caught:
            self.reconcile("rec_pending_check", [self.fx.independent_checks["itm_lem"], partial_check])
        self.assertIn("independent response that is not accepted", str(caught.exception.records))
        self.assertEqual(before, self.db.max_revision())
        self.assertIsNone(self.db.head("reconciliations", "rec_pending_check"))
        self.assertEqual("needs_revision", self.db.head("responses", pending["response_id"]).body["state"])

    def test_accepted_late_review_still_cannot_be_omitted(self):
        self.fx.independent()
        first = self.fx.independent_checks["itm_lem"]
        late, _ = self.fx.independent_round(self.db, "itm_lem", "arg_lem", "anc_lem_proof",
            judgment_target={"source_anchor_id": "anc_lem_proof", "description": "A later accepted examination"})
        with self.assertRaises(InvalidRequest) as caught:
            self.reconcile("rec_omitted", [first])
        self.assertIn(f"independent check {late}", str(caught.exception.records))
        self.assertIn("is not listed", str(caught.exception.records))
        self.assertIsNone(self.db.head("reconciliations", "rec_omitted"))
        self.reconcile("rec_both", [first, late])
        self.assertEqual({first, late}, {r["id"] for r in self.db.head("reconciliations", "rec_both").body["independent_checks"]})


if __name__ == "__main__":
    import unittest
    unittest.main()
