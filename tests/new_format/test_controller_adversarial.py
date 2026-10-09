"""Adversarial controller integration: preserve evidence, exact authority and independent privacy."""
from __future__ import annotations

import copy
import json

from support import R, TempCase, edit, locator
from paper_core import acceptance, controller, packets, review, sources
from paper_core.canonical import canonical_bytes, digest
from paper_core.errors import InvalidRequest


class ControllerAdversarialTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def prepare(self, *, mode="primary", item="itm_lem", **kwargs):
        if mode == "independent":
            # These tests exercise saved-return authority and provenance before
            # primary completion, which is now an explicit bounded investigation.
            kwargs.update(exception_purpose="Exercise independent intake and correspondence protocol",
                          exception_limitations="The fixture's primary examination is unfinished; this "
                                                "investigation provides no audit completion or stage readiness.")
        result = controller.prepare_work(self.db, audit_id="aud_1", mode=mode,
                                         focus=R("items", item), **kwargs)
        self.assertTrue(result["prepared"], result)
        return result

    def envelope(self, packet, **changes):
        independent = packet["manifest"]["mode"] == "independent"
        body = {"contract_version": 3, "request_id": self.fx.request_id(),
                "packet_id": packet["packet_id"], "rebase_packet_id": None,
                "reviewer": "checker-A" if independent else "primary-1",
                "qualification_id": "qua_r1" if independent else None,
                "exposure": "source_only" if independent else None, "exposure_note": ""}
        return dict(body, **changes)

    def submit(self, packet, worker, **changes):
        envelope = self.envelope(packet, **changes)
        result = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                         response_bytes=canonical_bytes(worker))
        return result, envelope

    def independent_worker(self, packet, *, source_target=True):
        return {"packet_id": packet["packet_id"], "covered_targets": [R("items", "itm_lem")],
                "coverage_note": "Read the supplied lemma proof", "exposure_report": {"status": "none_known", "note": ""},
                "judgments": [{"target": ({"source_anchor_id": "anc_lem_proof", "description": "the lemma proof"}
                                             if source_target else R("items", "itm_lem")),
                    "kind": "composition" if source_target else "external_source", "state": "complete",
                    "outcome": "supported", "reasoning": "Source-based fixture judgment", "evidence_refs": ["anc_lem_proof"],
                    "conditions": [], "next_action": None, "supersedes": None}]}

    def one_primary(self, packet, kind):
        response = copy.deepcopy(packet["scaffold"])
        specs = {t["id"]: t for t in packet["manifest"]["work"]["tasks"]}
        selected = next(r for r in response["results"] if specs[r["task_id"]]["kind"] == kind)
        if selected["type"] == "check":
            selected.update(state="complete", outcome="supported", reasoning="Checked this explicit local inference")
        else:
            selected.update(result="matched", note="Compared source")
        response["results"] = [selected]
        return response

    def test_independent_pending_mapping_keeps_exact_response_without_credit(self):
        packet = self.prepare(mode="independent")
        worker = self.independent_worker(packet)
        before = len(self.db.heads("checks"))
        result, envelope = self.submit(packet, worker)
        self.assertEqual("needs_revision", result["state"], result)
        self.assertEqual(0, result["exit_code"])
        self.assertIsNotNone(result["committed_revision"])
        self.assertEqual(before, len(self.db.heads("checks")))
        stored = self.db.work_submission(envelope["request_id"])
        self.assertEqual(canonical_bytes(worker), self.db.get_blob(stored["response_sha256"]))
        self.assertEqual("needs_revision", self.db.head("responses", result["response_id"]).body["state"])
        self.assertEqual("map_saved_response", result["recovery"][0]["operation"])

    def test_partial_mapping_current_inspection_preserves_negative_work_and_receipt(self):
        packet = self.prepare(mode="independent")
        worker = self.independent_worker(packet)
        worker["judgments"][0].update(outcome="gap", reasoning="The written composition leaves a required inference unjustified.")
        worker["judgments"].append(dict(worker["judgments"][0], kind="derivation",
                                        reasoning="The local deduction has the same missing justification."))
        result, envelope = self.submit(packet, worker)
        original_receipt = self.db.work_submission(envelope["request_id"])["result"]
        original_bytes = canonical_bytes(worker)
        generic = self.fx.packet(self.db, "items:itm_lem", mode="primary")
        def map_row(index, target):
            return review.map_response(self.db, mapping={"contract_version": 4,
                "request_id": self.fx.request_id(), "packet_id": generic["packet_id"],
                "response_id": result["response_id"], "reviewer": "coordinator",
                "entries": [{"judgment_index": index, "target": target,
                             "rationale": "The source passage identifies this exact written inference."}]})
        map_row(0, R("arguments", "arg_lem"))
        partial = controller.inspect_work(self.db, request_id=envelope["request_id"])["current"]["response"]
        self.assertEqual([1], partial["pending_judgment_indexes"])
        self.assertEqual("needs_revision", partial["state"])
        self.assertEqual(0, partial["eligible_independent_check_count"])
        map_row(1, R("groups", "grp_lem"))
        before = self.db.max_revision()
        final = controller.inspect_work(self.db, response_id=result["response_id"])
        self.assertEqual("accepted", final["state"])
        self.assertEqual([], final["pending_judgment_indexes"])
        self.assertEqual({"gap"}, {check["outcome"] for check in final["checks"]})
        self.assertEqual(before, self.db.max_revision())
        from support import run_cli
        cli_view, _ = run_cli("work", "inspect", self.fx.path, "--response", result["response_id"], "--limit", "1")
        self.assertEqual(1, cli_view["details_limit"])
        self.assertEqual(1, len(cli_view["checks"]))
        self.assertTrue(cli_view["details_truncated"])
        self.assertEqual(before, self.db.max_revision())
        self.assertEqual(original_receipt, self.db.work_submission(envelope["request_id"])["result"])
        saved = self.db.head("responses", result["response_id"])
        self.assertEqual(original_bytes, self.db.get_blob(saved.body["original_blob"]))
        self.assertEqual(result, controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                                        response_bytes=original_bytes))

    def test_later_mapping_preserves_original_intake_receipt_and_replay(self):
        packet = self.prepare(mode="independent")
        worker = self.independent_worker(packet)
        result, envelope = self.submit(packet, worker)
        self.assertEqual("needs_revision", result["state"], result)
        generic = self.fx.packet(self.db, "items:itm_lem", mode="primary")
        mapping = {"contract_version": 3, "request_id": self.fx.request_id(), "packet_id": generic["packet_id"],
                   "response_id": result["response_id"], "entries": [{"judgment_index": 0,
                    "target": R("arguments", "arg_lem"), "rationale": "This is the registered source argument"}],
                   "reviewer": "coordinator"}
        mapped = review.map_response(self.db, mapping=mapping)
        self.assertEqual(mapped["receipt"], review.map_response(self.db, mapping=mapping)["receipt"])
        inspected = controller.inspect_work(self.db, request_id=envelope["request_id"])
        self.assertEqual("needs_revision", inspected["result"]["state"])
        self.assertEqual("accepted", inspected["current"]["response"]["state"])
        replay = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
        self.assertEqual(result, replay)

    def test_malformed_included_independent_judgment_stages_no_derived_records(self):
        packet = self.prepare(mode="independent")
        worker = self.independent_worker(packet, source_target=False)
        worker["judgments"].append(dict(worker["judgments"][0], reasoning=""))
        before = self.db.max_revision()
        result, envelope = self.submit(packet, worker)
        self.assertEqual("needs_revision", result["state"], result)
        self.assertTrue(result["stored"])
        self.assertEqual(before, self.db.max_revision())
        self.assertEqual([], self.db.heads("responses"))
        self.assertTrue(any("nonempty reasoning" in str(d) for d in result["diagnostics"]))
        self.assertEqual(canonical_bytes(worker), self.db.get_blob(self.db.work_submission(envelope["request_id"])["response_sha256"]))

    def test_wrong_independent_reviewer_is_rejected_before_intake(self):
        packet = self.prepare(mode="independent")
        result, envelope = self.submit(packet, self.independent_worker(packet), reviewer="another-reviewer")
        self.assertFalse(result["stored"])
        self.assertEqual("QUALIFICATION_INVALID", result["error"]["code"])
        self.assertEqual("verify_provenance", result["recovery"][0]["operation"])
        self.assertIsNone(self.db.work_submission(envelope["request_id"]))

    def test_wrong_envelope_with_extended_context_gets_pairing_advice_before_rebase_advice(self):
        original = self.prepare(mode="independent")
        extended = packets.extend_work_assignment(self.db, packet_id=original["packet_id"], request={
            "source_refs": [self.db.head("anchors", "anc_thm").pinned],
            "reason": "Additional neutral source examined by this worker"})
        worker = self.independent_worker(extended, source_target=False)
        raw = canonical_bytes(worker)
        envelope = self.envelope(original, rebase_packet_id=extended["packet_id"])
        result = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
        self.assertFalse(result["stored"])
        self.assertEqual("NEW_CONTEXT_RESPONSE_REQUIRED", result["error"]["code"])
        self.assertIsNone(self.db.work_submission(envelope["request_id"]))
        advice = result["recovery"][0]
        self.assertEqual("PACKET_MISMATCH", advice["reason_code"])
        self.assertEqual("inspect_assignment", advice["operation"])
        self.assertEqual(original["packet_id"], advice["envelope_packet_id"])
        self.assertEqual(extended["packet_id"], advice["worker_packet_id"])
        corrected = self.envelope(extended)
        accepted = controller.submit_work(self.db, envelope_bytes=canonical_bytes(corrected), response_bytes=raw)
        self.assertEqual("accepted", accepted["state"], accepted)
        self.assertEqual(raw, self.db.get_blob(self.db.work_submission(corrected["request_id"])["response_sha256"]))

    def test_coordinator_exposure_cannot_be_overridden_by_worker_self_report(self):
        packet = self.prepare(mode="independent")
        result, _ = self.submit(packet, self.independent_worker(packet, source_target=False),
                                exposure="compromised", exposure_note="Shared prior checking context")
        self.assertEqual("accepted", result["state"], result)
        response = self.db.head("responses", result["response_id"])
        self.assertEqual("compromised", response.body["exposure"])

    def test_rejected_attempt_does_not_count_compromised_successor_as_required_independence(self):
        packet = self.prepare(mode="independent")
        worker = self.independent_worker(packet)
        malformed = copy.deepcopy(worker)
        malformed["judgments"][0]["reasoning"] = ""
        rejected, envelope = self.submit(packet, malformed)
        self.assertEqual("needs_revision", rejected["state"])
        self.assertNotIn("response_id", rejected)
        successor, _ = self.submit(packet, worker, exposure="compromised", exposure_note="Shared primary reasoning")
        context = self.fx.packet(self.db, "items:itm_lem", mode="primary")
        review.map_response(self.db, mapping={"contract_version": 4,
            "request_id": self.fx.request_id(), "packet_id": context["packet_id"],
            "response_id": successor["response_id"], "reviewer": "coordinator",
            "entries": [{"judgment_index": 0, "target": R("arguments", "arg_lem"),
                         "rationale": "The preserved source judgment examines this written route."}]})
        self.assertEqual("accepted", self.db.head("responses", successor["response_id"]).body["state"])
        inspected = controller.inspect_work(self.db, request_id=envelope["request_id"])
        self.assertEqual(rejected, inspected["result"])
        self.assertEqual("CURRENT_ASSIGNED_WORK_REMAINS", inspected["current"]["recovery"][0]["reason_code"])
        self.assertGreater(inspected["current"]["remaining_task_count"], 0)

    def test_recovered_independent_worker_artifact_preserves_original_source_only_payload(self):
        packet = self.prepare(mode="independent")
        original = self.db.get_blob(self.db.packet(packet["packet_id"])["payload_sha256"])
        recovered = controller.inspect_work(self.db, packet_id=packet["packet_id"])
        paths = controller.write_artifacts(self.db, recovered, self.path("recovered"))
        self.assertEqual(["worker-packet.json", "response-scaffold.json", "worker-guidance.json"],
                         recovered["worker_delivery_files"])
        self.assertIn("submission-envelope-template.json", paths)
        from pathlib import Path
        delivered = b"\n".join(Path(paths[name]["path"]).read_bytes() for name in recovered["worker_delivery_files"])
        for forbidden in (b"qualification_id", b"draft_candidates", b"renewal_candidates", b"primary_opinions"):
            self.assertNotIn(forbidden, delivered)
        raw = Path(paths["worker-packet.json"]["path"]).read_bytes()
        self.assertGreater(len(raw.splitlines()), 1)
        self.assertEqual(json.loads(original), json.loads(raw))
        self.assertEqual(original, canonical_bytes(json.loads(raw)))
        self.assertEqual(digest(json.loads(original)), digest(json.loads(raw)))
        self.assertEqual(original, self.db.get_blob(self.db.packet(packet["packet_id"])["payload_sha256"]))
        worker = json.loads(raw)
        self.assertEqual([], packets.blinding_violations(worker))
        self.assertNotIn("_manifest", worker)
        for task in packet["manifest"]["work"]["tasks"]:
            self.assertNotIn(task["id"].encode(), raw)

    def test_generic_apply_cannot_bypass_assignment_task_scope(self):
        packet = self.prepare()
        batch = self.fx.batch([self.fx.check_edit("chk_unauthorized", R("groups", "grp_thm"), "derivation")],
                              packet["packet_id"])
        with self.assertRaises(InvalidRequest) as caught:
            acceptance.apply_batch(self.db, batch)
        self.assertEqual("WORK_SUBMIT_REQUIRED", caught.exception.code)
        self.assertIsNone(self.db.head("checks", "chk_unauthorized"))

    def test_central_work_validation_rejects_unassigned_coverage_argument(self):
        packet = self.prepare()
        body = {"argument_id": "arg_thm", "anchor_id": "anc_thm_proof", "start_offset": 0,
                "end_offset": 1, "classification": "structural", "claim_refs": [], "check_ids": [], "note": ""}
        with self.assertRaises(InvalidRequest) as caught:
            acceptance.accept(self.db, request_id=self.fx.request_id(), request_digest=digest(body),
                packet_id=packet["packet_id"], edits=[edit("create", "coverage", "cov_unassigned", body)], command="work_primary")
        self.assertIn("coverage argument is outside", str(caught.exception.records))
        self.assertIsNone(self.db.head("coverage", "cov_unassigned"))

    def test_central_work_validation_rejects_global_finding_without_global_task(self):
        packet = self.prepare()
        body = {"audit_id": "aud_1", "target": R("audits", "aud_1"), "category": "proof_gap",
                "description": "An unassigned paper-wide claim", "evidence_refs": [], "check_refs": [],
                "affected_uses": [], "impact_reason": "Paper-wide judgment", "lifecycle": "open", "resolution": None}
        with self.assertRaises(InvalidRequest) as caught:
            acceptance.accept(self.db, request_id=self.fx.request_id(), request_digest=digest(body),
                packet_id=packet["packet_id"], edits=[edit("create", "findings", "fnd_unassigned", body)], command="work_primary")
        self.assertIn("global finding needs an assigned global task", str(caught.exception.records))

    def test_scoped_reconciliation_accepts_argument_target_without_major_owner_bypass(self):
        self.fx.independent()
        packet = self.prepare(mode="reconcile")
        envelope = self.envelope(packet, reviewer="coordinator")
        worker = {"contract_version": 3, "request_id": envelope["request_id"], "packet_id": packet["packet_id"],
                  "edits": [self.fx.reconciliation_edit(self.db, "rec_work", "arg_lem", "chk_comp_lem",
                                                        self.fx.independent_checks["itm_lem"])]}
        result = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
        self.assertEqual("accepted", result["state"], result)
        self.assertIsNotNone(self.db.head("reconciliations", "rec_work"))

    def test_same_assignment_auxiliary_anchor_change_cannot_hide_behind_omitted_task(self):
        lemma = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "items", lemma.id,
            dict(lemma.body, passages=lemma.body["passages"] + [{"role": "evidence", "anchor_id": "anc_thm_proof"}]),
            lemma.version)])
        packet = self.prepare()
        worker = self.one_primary(packet, "derivation")
        worker["findings"] = [{"target": R("groups", "grp_lem"), "category": "inconclusive",
            "description": "The additional passage needs a coordinator decision", "evidence_refs": ["anc_thm_proof"],
            "related_task_ids": [], "existing_check_refs": [], "affected_uses": [],
            "impact_reason": "The local inference depends on this passage"}]
        anchor = self.db.head("anchors", "anc_thm_proof")
        fresh = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 3, "request_id": self.fx.request_id(),
            "packet_id": fresh["packet_id"], "anchors": [{"id": anchor.id, "expected_version": anchor.version,
                "source_id": self.fx.source_id, "locator": locator(start=8, end=10)}]})
        before = self.db.max_revision()
        result, _ = self.submit(packet, worker)
        self.assertEqual("conflict", result["state"], result)
        self.assertEqual(before, self.db.max_revision())

    def test_source_recapture_is_retained_conflict(self):
        packet = self.prepare()
        worker = self.one_primary(packet, "derivation")
        source = self.fx.source_root / "paper.tex"
        source.write_text(source.read_text() + "% changed captured source context\n", encoding="utf-8")
        sources.capture_sources(self.db, files=["paper.tex"])
        result, envelope = self.submit(packet, worker)
        self.assertEqual("conflict", result["state"], result)
        self.assertEqual("renew_affected_work", result["recovery"][0]["operation"])
        self.assertTrue(result["stored"])
        self.assertEqual(canonical_bytes(worker), self.db.get_blob(self.db.work_submission(envelope["request_id"])["response_sha256"]))

    def test_changed_audit_scope_does_not_relabel_old_work_as_current(self):
        packet = self.prepare()
        worker = self.one_primary(packet, "derivation")
        audit = self.db.head("audits", "aud_1")
        self.fx.apply(self.db, [edit("replace", "audits", audit.id,
            dict(audit.body, targets=[R("items", "itm_thm")]), audit.version)], mode="primary")
        result, _ = self.submit(packet, worker)
        self.assertEqual("conflict", result["state"], result)
        self.assertIn("audit scope", str(result["diagnostics"]))

    def test_report_path_only_change_keeps_mathematical_work_reusable(self):
        packet = self.prepare()
        audit = self.db.head("audits", "aud_1")
        self.fx.apply(self.db, [edit("replace", "audits", audit.id,
            dict(audit.body, report_path="reports/renamed.html"), audit.version)], mode="primary")
        result, _ = self.submit(packet, self.one_primary(packet, "derivation"))
        self.assertEqual("accepted", result["state"], result)

    def test_independent_extra_cited_anchor_is_a_consumed_input(self):
        self.fx.apply(self.db, [self.fx.item_edit("itm_definition", "definition", "Definition",
                                                "anc_thm", "anc_thm_proof")])
        packet = self.prepare(mode="independent")
        packet = packets.extend_work_assignment(self.db, packet_id=packet["packet_id"], request={
            "source_refs": [self.db.head("items", "itm_definition").pinned],
            "reason": "The independent reviewer needs this additional source definition."})
        self.assertIn("anc_thm", [ref["id"] for ref in packet["manifest"]["read_set"]])
        worker = self.independent_worker(packet, source_target=False)
        worker["judgments"][0]["evidence_refs"].append("anc_thm")
        anchor = self.db.head("anchors", "anc_thm")
        generic = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 3, "request_id": self.fx.request_id(),
            "packet_id": generic["packet_id"], "anchors": [{"id": anchor.id, "expected_version": anchor.version,
                "source_id": self.fx.source_id, "locator": locator(label="lem:a")}]})
        before = self.db.max_revision()
        result, envelope = self.submit(packet, worker)
        self.assertEqual("conflict", result["state"], result)
        self.assertEqual(before, self.db.max_revision())
        self.assertIsNone(result["committed_revision"])
        self.assertEqual([], self.db.heads("responses"))
        self.assertEqual(canonical_bytes(worker), self.db.get_blob(
            self.db.work_submission(envelope["request_id"])["response_sha256"]))

    def _upstream_proof_rebase(self, *, borrowed):
        use = self.db.head("uses", "use_lem_thm")
        if borrowed:
            self.fx.apply(self.db, [edit("replace", "uses", use.id, dict(use.body, type="proof_argument"), use.version)])
        view = controller.derive_work(self.db, audit_id="aud_1", focus=R("items", "itm_thm"))
        application = next(t for t in view["tasks"] if t["target"] == R("uses", "use_lem_thm")
                           and t["kind"] == "application" and t["role"] == "primary")
        kwargs = {"item": "itm_thm", "task_ids": [application["id"]], "allow_provisional": True}
        packet = self.prepare(**kwargs)
        worker = self.one_primary(packet, "application")
        lemma = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "items", lemma.id,
            dict(lemma.body, passages=lemma.body["passages"] + [{"role": "evidence", "anchor_id": "anc_thm_proof"}]),
            lemma.version)])
        fresh = self.prepare(**kwargs)
        result, _ = self.submit(packet, worker, rebase_packet_id=fresh["packet_id"])
        return result

    def test_explicit_borrowed_proof_change_requires_reconsideration_on_rebase(self):
        result = self._upstream_proof_rebase(borrowed=True)
        self.assertEqual("conflict", result["state"], result)

    def test_unconsumed_upstream_proof_change_keeps_local_implication_reusable(self):
        result = self._upstream_proof_rebase(borrowed=False)
        self.assertEqual("accepted", result["state"], result)

    def test_reconciliation_extra_evidence_is_pinned_to_the_coordinator_context(self):
        self.fx.independent()
        self.fx.apply(self.db, [edit("create", "findings", "fnd_extra_context", {
            "audit_id": "aud_1", "target": R("arguments", "arg_lem"), "category": "inconclusive",
            "description": "Compare this additional passage during reconciliation", "evidence_refs": ["anc_thm_proof"],
            "check_refs": [], "affected_uses": [], "impact_reason": "Relevant comparison context",
            "lifecycle": "open", "resolution": None})], mode="primary")
        packet = self.prepare(mode="reconcile")
        envelope = self.envelope(packet, reviewer="coordinator")
        entry = self.fx.reconciliation_edit(self.db, "rec_evidence", "arg_lem", "chk_comp_lem",
                                            self.fx.independent_checks["itm_lem"])
        entry["body"]["evidence_refs"] = ["anc_thm_proof"]
        worker = {"contract_version": 3, "request_id": envelope["request_id"], "packet_id": packet["packet_id"],
                  "edits": [entry]}
        anchor = self.db.head("anchors", "anc_thm_proof")
        generic = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 3, "request_id": self.fx.request_id(),
            "packet_id": generic["packet_id"], "anchors": [{"id": anchor.id, "expected_version": anchor.version,
                "source_id": self.fx.source_id, "locator": locator(start=8, end=10)}]})
        before = self.db.max_revision()
        result = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                        response_bytes=canonical_bytes(worker))
        self.assertEqual("conflict", result["state"], result)
        self.assertEqual(before, self.db.max_revision())


if __name__ == "__main__":
    import unittest
    unittest.main()
