"""Generic mapping preserves controller review provenance without relaxing generic OCC."""
from __future__ import annotations

import hashlib
from unittest import mock

from support import R, TempCase, edit, locator
from paper_core import assessment, bindings, controller, projection, queries, review, sources, work
from paper_core.canonical import canonical_bytes
from paper_core.errors import ConflictError


class WorkOriginBindingTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def pending(self, *, work_origin=True, exposure="source_only", extra_judgment=False):
        if work_origin:
            prepared = controller.prepare_work(self.db, audit_id="aud_1", mode="independent",
                                                focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            packet = prepared["packet"]
        else:
            packet = self.fx.packet(self.db, "items:itm_lem", mode="independent")
        worker = {"packet_id": packet["packet_id"], "covered_targets": [R("items", "itm_lem")],
            "coverage_note": "Read the source proof", "exposure_report": {"status": "none_known", "note": ""},
            "judgments": [{"target": {"source_anchor_id": "anc_lem_proof", "description": "The proof argument"},
                "kind": "composition", "state": "complete", "outcome": "supported", "reasoning": "Source-based examination",
                "evidence_refs": ["anc_lem_proof"], "conditions": [], "next_action": None, "supersedes": None}]}
        if extra_judgment:
            worker["judgments"].append(dict(worker["judgments"][0], kind="derivation"))
        submission = {"contract_version": 3, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
                      "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": exposure,
                      "exposure_note": "Possible primary exposure" if exposure == "compromised" else ""}
        if work_origin:
            envelope = dict(submission, rebase_packet_id=None)
            submitted = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                                 response_bytes=canonical_bytes(worker))
        else:
            submitted = review.submit_review(self.db, submission=submission, response_bytes=canonical_bytes(worker))
        self.assertEqual("needs_revision", submitted["state"], submitted)
        mapping_packet = self.fx.packet(self.db, "items:itm_lem", mode="primary")
        self.assertNotIn("work", mapping_packet)
        request = {"contract_version": 3, "request_id": self.fx.request_id(), "packet_id": mapping_packet["packet_id"],
                   "response_id": submitted["response_id"], "entries": [{"judgment_index": 0,
                    "target": R("arguments", "arg_lem"), "rationale": "This argument has the reviewed source passage"}],
                   "reviewer": "coordinator"}
        return request

    def mapped(self, *, historical_binding=False, historical_coverage=False, **kwargs):
        request = self.pending(**kwargs)
        if historical_binding:
            # Freeze the historical stored shape explicitly. Merely changing a
            # current packet's version would still produce contract-4 bindings.
            insert = self.db.insert_binding
            def insert_historical(collection, identifier, version, packet_id, binding):
                original_shape = dict(binding)
                original_shape.pop("semantic_memberships", None)
                return insert(collection, identifier, version, packet_id, original_shape)
            with mock.patch.object(self.db, "insert_binding", side_effect=insert_historical):
                mapped = review.map_response(self.db, mapping=request)
        elif historical_coverage:
            # Reproduce the previous writer, retaining its exact stored bindings.
            with mock.patch.object(bindings, "_without_coordinator_coverage", side_effect=lambda binding: binding):
                mapped = review.map_response(self.db, mapping=request)
        else:
            mapped = review.map_response(self.db, mapping=request)
        self.assertEqual("accepted", mapped["state"])
        check_id = mapped["checks"][0]["check_id"]
        self.assertEqual("current", self.freshness(check_id)["freshness"])
        return check_id

    def freshness(self, check_id):
        snap = assessment.Snapshot(self.db, self.db.max_revision())
        return assessment.judgment_freshness(snap, self.db.head("checks", check_id), superseded=False)

    def coverage_progress(self):
        old = self.db.head("coverage", "cov_lem")
        successor = self.fx.check_edit("chk_successor", R("groups", "grp_lem"), "derivation",
            supersedes=self.fx.pin(self.db, "checks", "chk_der_lem"))
        self.fx.apply(self.db, [successor,
            edit("replace", "coverage", old.id, dict(old.body, check_ids=["chk_successor"], note="Linked corrected primary review"),
                 old.version)], mode="primary")

    def test_work_origin_mapping_survives_check_link_and_note_only_coverage_edit(self):
        check_id = self.mapped()
        stored = self.db.binding("checks", check_id, 1)["bindings"]
        self.assertIn("semantic_memberships", stored)
        self.assertEqual([], [r for r in stored["records"] if r["ref"]["collection"] == "checks"])
        self.coverage_progress()
        self.assertEqual("current", self.freshness(check_id)["freshness"])

    def assert_coverage_incomplete(self):
        derived = assessment.derive_assessment(self.db, audit_id="aud_1")
        self.assertFalse(derived["progress"]["process_complete"])
        self.assertTrue(derived["coverage_diagnostics"])

    def test_work_origin_mapping_survives_coverage_span_changes(self):
        check_id = self.mapped()
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
        changed = self.freshness(check_id)
        self.assertEqual("current", changed["freshness"])
        self.assert_coverage_incomplete()

    def test_work_origin_mapping_survives_coverage_claim_changes(self):
        check_id = self.mapped()
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, claim_refs=[R("items", "itm_thm")]), old.version)], mode="primary")
        self.assertEqual("current", self.freshness(check_id)["freshness"])
        self.assert_coverage_incomplete()

    def test_new_work_binding_omits_only_coordinator_coverage(self):
        check_id = self.mapped()
        stored = self.db.binding("checks", check_id, 1)["bindings"]
        self.assertFalse(any(row["ref"]["collection"] == "coverage" for row in stored["records"]))
        for field in ("relations", "semantic_memberships"):
            self.assertFalse(any(row["relation"] == "coverage_in_argument" for row in stored[field]))
        self.assertTrue(any(row["ref"]["collection"] == "proof_boundaries" and row["facet"] == "coverage"
                            for row in stored["records"]))
        self.assertTrue(any(row["ref"]["collection"] == "source_reviews" for row in stored["records"]))
        boundary = self.db.head("proof_boundaries", "bnd_lem")
        self.fx.apply(self.db, [edit("replace", "proof_boundaries", boundary.id,
            dict(boundary.body, state="unresolved"), boundary.version)], mode="primary")
        self.assertNotEqual("current", self.freshness(check_id)["freshness"])

    def test_added_and_retired_coverage_do_not_renew_independent_examination(self):
        check_id = self.mapped()
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [{"op": "retire", "collection": "coverage", "id": old.id,
            "expected_version": old.version, "reason": "Replace coordinator accounting"}], mode="primary")
        self.assertEqual("current", self.freshness(check_id)["freshness"])
        self.assert_coverage_incomplete()
        self.fx.apply(self.db, [edit("create", "coverage", "cov_replacement", old.body)], mode="primary")
        self.assertEqual("current", self.freshness(check_id)["freshness"])
        self.assertNotEqual("current", self.freshness("chk_comp_lem")["freshness"])

    def test_historical_coverage_recovery_agrees_across_readers_without_writes(self):
        check_id = self.mapped(historical_coverage=True)
        check = self.db.head("checks", check_id)
        stored = self.db.binding("checks", check_id, 1)
        self.assertTrue(any(row["ref"]["collection"] == "coverage" for row in stored["bindings"]["records"]))
        before_coverage = self.db.max_revision()
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
        frozen = (self.db.max_revision(), hashlib.sha256(self.db.path.read_bytes()).hexdigest())
        snap = assessment.Snapshot(self.db, self.db.max_revision())
        self.assertTrue(bindings.binding_changes(snap, stored["bindings"])["records"])
        self.assertEqual("current", self.freshness(check_id)["freshness"])
        validated = queries.validate_snapshot(self.db)
        self.assertNotIn(check_id, [row["ref"]["id"] for row in validated["stale_bindings"]])
        changed = queries.changes(self.db, since=before_coverage)
        self.assertNotIn(check_id, [row["ref"]["id"] for row in changed["affected_checks"]])
        tasks = work.derive_work(self.db, audit_id="aud_1")["tasks"]
        independent = next(row for row in tasks if row["role"] == "independent" and row["target"] == check.body["target"])
        self.assertEqual("satisfied", independent["state"])
        status = queries.status(self.db, audit_id="aud_1")
        self.assertFalse(status["process_complete"])
        self.assertTrue(status["coverage_diagnostics"])
        projected, _ = projection.project(self.db, audit_id="aud_1")
        self.assertFalse(projected["summary"]["progress"]["process_complete"])
        self.assertEqual(stored, self.db.binding("checks", check_id, 1))
        self.assertEqual(frozen, (self.db.max_revision(), hashlib.sha256(self.db.path.read_bytes()).hexdigest()))

    def test_missing_original_packet_does_not_recover_historical_coverage(self):
        check_id = self.mapped(historical_coverage=True)
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
        with mock.patch.object(self.db, "packet", return_value=None):
            self.assertEqual("needs_review", self.freshness(check_id)["freshness"])

    def test_missing_original_response_does_not_recover_historical_coverage(self):
        check_id = self.mapped(historical_coverage=True)
        response = self.db.head("responses", self.db.head("checks", check_id).body["response_id"])
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
        has_blob = self.db.has_blob
        with mock.patch.object(self.db, "has_blob", side_effect=lambda sha:
                               False if sha == response.body["original_blob"] else has_blob(sha)):
            self.assertEqual("needs_review", self.freshness(check_id)["freshness"])

    def test_coverage_recovery_does_not_add_provenance_gates_without_coverage_drift(self):
        for historical in (False, True):
            with self.subTest(historical_coverage=historical):
                self.fx = self.fixture(f"provenance-{historical}").primary()
                self.db = self.fx.open()
                self.addCleanup(self.db.close)
                check_id = self.mapped(historical_coverage=historical)
                # The correction must not reclassify an already-current judgment
                # when it grants no exemption from the saved binding.
                with mock.patch.object(self.db, "packet", return_value=None):
                    self.assertEqual("current", self.freshness(check_id)["freshness"])

    def test_audit_qualification_change_does_not_change_original_review_qualification(self):
        check_id = self.mapped(historical_coverage=True)
        old = self.db.head("coverage", "cov_lem")
        audit = self.db.head("audits", "aud_1")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version),
            edit("replace", "audits", audit.id, dict(audit.body, qualification_id=None), audit.version)], mode="primary")
        self.assertEqual("current", self.freshness(check_id)["freshness"])

    def test_historical_coverage_recovery_keeps_changed_setup_stale(self):
        check_id = self.mapped(historical_coverage=True)
        stored = self.db.binding("checks", check_id, 1)
        self.assertEqual(1, stored["bindings"]["neutral_setup_validated"])
        old = self.db.head("coverage", "cov_lem")
        scope = self.db.head("scopes", "scp_plain")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version),
            edit("replace", "scopes", scope.id, dict(scope.body, conditions=["New unreviewed condition"]), scope.version)], mode="primary")
        changed = self.freshness(check_id)
        self.assertEqual("needs_review", changed["freshness"])
        self.assertTrue(any(row["ref"]["id"] == scope.id for row in changed["changes"]["records"]))
        self.assertIn(check_id, [row["ref"]["id"] for row in queries.validate_snapshot(self.db)["stale_bindings"]])
        self.assertEqual(stored, self.db.binding("checks", check_id, 1))

    def test_compromised_review_keeps_coverage_binding_and_no_credit(self):
        check_id = self.mapped(exposure="compromised")
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
        self.assertEqual("needs_review", self.freshness(check_id)["freshness"])

    def test_partially_mapped_review_keeps_coverage_binding_and_no_credit(self):
        mapping = self.pending(extra_judgment=True)
        mapped = review.map_response(self.db, mapping=mapping)
        self.assertEqual("needs_revision", mapped["state"])
        check_id = mapped["checks"][0]["check_id"]
        old = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [edit("replace", "coverage", old.id,
            dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
        self.assertEqual("needs_review", self.freshness(check_id)["freshness"])
        tasks = work.derive_work(self.db, audit_id="aud_1")["tasks"]
        self.assertTrue(all(row["state"] != "satisfied" for row in tasks if row["role"] == "independent"))

    def test_work_origin_mapping_stales_when_reviewed_proof_excerpt_changes(self):
        check_id = self.mapped()
        anchor = self.db.head("anchors", "anc_lem_proof")
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 3, "request_id": self.fx.request_id(),
            "packet_id": packet["packet_id"], "anchors": [{"id": anchor.id, "expected_version": anchor.version,
                "source_id": self.fx.source_id, "locator": locator(start=6, end=6)}]})
        changed = self.freshness(check_id)
        self.assertEqual("needs_review", changed["freshness"])
        self.assertTrue(any(r["ref"]["id"] == "anc_lem_proof" for r in changed["changes"]["records"]))

    def test_current_generic_origin_uses_semantic_memberships(self):
        check_id = self.mapped(work_origin=False)
        self.assertIn("semantic_memberships", self.db.binding("checks", check_id, 1)["bindings"])
        self.coverage_progress()
        self.assertEqual("current", self.freshness(check_id)["freshness"])

    def test_stored_historical_binding_keeps_strict_membership_behavior(self):
        check_id = self.mapped(work_origin=False, historical_binding=True)
        self.assertNotIn("semantic_memberships", self.db.binding("checks", check_id, 1)["bindings"])
        self.coverage_progress()
        self.assertEqual("needs_review", self.freshness(check_id)["freshness"])

    def test_work_origin_does_not_relax_mapping_packets_transaction_conflict_checks(self):
        request = self.pending()
        lemma = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "items", lemma.id, dict(lemma.body, caption="Updated caption"), lemma.version)])
        before = self.db.max_revision()
        with self.assertRaises(ConflictError):
            review.map_response(self.db, mapping=request)
        self.assertEqual(before, self.db.max_revision())
        self.assertEqual("needs_revision", self.db.head("responses", request["response_id"]).body["state"])


if __name__ == "__main__":
    import unittest
    unittest.main()
