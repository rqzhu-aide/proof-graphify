"""Generated role guidance preserves native exports, returned judgments and coverage.

Synthetic examinations test mechanics, not mathematical accuracy or model behavior.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from support import R, TempCase
from paper_core import assessment, controller, packets, stage1
from paper_core.contract import WORK_PRIMARY_RESPONSE, WORKER_RESPONSE, validate_shape
from paper_core.ids import COLLECTIONS
from paper_core.validation import State
from paper_core.work import derive_work


class PreparationGuidanceTests(TempCase):
    def prepare(self, name, mode="primary"):
        fixture = self.fixture(name).audit()
        if mode == "independent":
            fixture.primary()
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id,
                stage=1 if mode == "primary" else 2, mode=mode, focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        return fixture, prepared

    @staticmethod
    def raw(value):
        return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    def authored(self, prepared, *, outcome="gap", extent="whole_unit", omissions="", reasoning=None):
        response = deepcopy(prepared["scaffold"])
        reasoning = reasoning or "Every supplied line was examined; the induction lacks a premise, α is unspecified."
        if prepared["mode"] == "independent":
            response["coverage_note"] = "Synthetic separate-context examination; retain this prerequisite uncertainty."
            response["exposure_report"] = {"status": "none_known", "note": "Synthetic source-only fixture."}
            rows = response["judgments"]
        else:
            rows = response["results"]
        for row in rows:
            if row.get("type") == "source_fidelity":
                row.update(result="matched", note="Compared the captured statement and exact setup.",
                           evidence_refs=["anc_lem"])
            else:
                row.update(state="complete", outcome=outcome, reasoning=reasoning,
                           conditions=["The supplied induction requires its stated base case."])
                if prepared["mode"] == "primary":
                    row["evidence_refs"] = ["anc_lem_proof"]
                if "extent" in row:
                    row.update(extent=extent, omissions=omissions)
        return response

    def submit(self, db, prepared, response):
        original = self.raw(response)
        envelope = controller.stage_submission_envelope(packet_id=prepared["packet_id"],
            reviewer="synthetic " + prepared["mode"], response_bytes=original,
            exposure="source_only" if prepared["mode"] == "independent" else None,
            exposure_note="Actual source-only provenance for this synthetic fixture.")
        receipt = controller.submit_work(db, envelope_bytes=self.raw(envelope), response_bytes=original)
        stored = db.work_submission(receipt["request_id"])
        self.assertEqual(original, db.get_blob(stored["response_sha256"]))
        self.assertEqual(original, self.raw(response))
        return receipt

    @staticmethod
    def judgment_snapshot(db):
        # A malformed independent return may create a pending raw response,
        # while scientific judgments remain unchanged.
        return {kind: [(row.pinned, deepcopy(row.body)) for row in db.heads(kind)]
                for kind in ("checks", "observations", "coverage", "findings", "reconciliations")}

    def assert_saved_judgment(self, db, prepared, response, *, extent, omissions, outcome):
        authored = next(row for row in response.get("results", response.get("judgments", []))
                        if "reasoning" in row)
        saved = [row for row in db.heads("checks") if row.body["role"] == prepared["mode"]]
        self.assertTrue(saved)
        for row in saved:
            for field in ("reasoning", "conditions"):
                self.assertEqual(authored[field], row.body[field])
            self.assertEqual(outcome, row.body["outcome"])
            self.assertEqual(extent, row.body["extent"])
            self.assertEqual(omissions, row.body["omissions"])
        if prepared["mode"] == "independent":
            self.assertTrue(any(db.get_blob(row.body["original_blob"]) == self.raw(response)
                                for row in db.heads("responses")))
            self.assertTrue(any(row.body["coverage_note"] == response["coverage_note"]
                                for row in db.heads("responses")))

    def composition_only(self, db, fixture):
        first = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
        source = self.authored(first)
        source["results"] = [row for row in source["results"] if row["type"] == "source_fidelity"]
        self.assertTrue(source["results"])
        self.assertEqual("accepted", self.submit(db, first, source)["state"])
        prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        self.assertEqual(["check"], [row["type"] for row in prepared["scaffold"]["results"]])
        return prepared

    @staticmethod
    def science_snapshot(db):
        return {kind: [(row.pinned, deepcopy(row.body), row.retired) for row in db.heads(kind)]
                for kind in COLLECTIONS}

    def test_partial_primary_refreshes_old_packet_and_explicit_successor_advances_own_work(self):
        fixture = self.fixture("partial-renewal").audit()
        with fixture.open() as db:
            first = self.composition_only(db, fixture)
            original_packet = deepcopy(db.packet(first["packet_id"]))
            original_payload = db.get_blob(original_packet["payload_sha256"])
            question = packets.neutral_question(State(db, []), first["manifest"]["work"]["tasks"][0])
            response = self.authored(first, extent="partial", outcome="gap",
                omissions="The supplied closing inference has not been examined.",
                reasoning="The examined induction lacks its base premise; the closing inference remains unread.")
            accepted = self.submit(db, first, response)
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assertEqual(first["assigned_task_ids"], accepted["remaining_task_ids"])
            predecessor = next(row for row in db.heads("checks") if row.body["role"] == "primary")
            self.assertNotIn(predecessor.pinned, first["manifest"]["read_set"])
            prior_body = deepcopy(predecessor.body)
            # A completed independent return isolates readiness of the primary obligation and its integration.
            independent = stage1.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                focus=R("items", "itm_lem"), allow_provisional=True)
            self.assertTrue(independent["prepared"], independent)
            self.assertEqual("accepted", self.submit(db, independent, self.authored(independent))["state"])
            before_science, revision = self.science_snapshot(db), db.max_revision()
            before_tasks = {row["id"]: row for row in derive_work(db, audit_id=fixture.audit_id)["tasks"]}
            fresh = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
            self.assertFalse(fresh["reused"], fresh)
            self.assertNotEqual(first["packet_id"], fresh["packet_id"])
            self.assertEqual(first["assigned_task_ids"], fresh["assigned_task_ids"])
            self.assertEqual(question, packets.neutral_question(State(db, []), fresh["manifest"]["work"]["tasks"][0]))
            self.assertIn(predecessor.pinned, fresh["manifest"]["read_set"])
            candidates = fresh["coordinator_guidance"]["renewal_candidates"]
            self.assertEqual([predecessor.pinned], [row["ref"] for row in candidates])
            for field in ("outcome", "reasoning", "conditions", "extent", "omissions"):
                self.assertEqual(prior_body[field], candidates[0][field])
            self.assertEqual("partial", db.head("checks", predecessor.id).body["extent"])
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError(
                    "reuse the current preparation assessment")):
                again = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
            self.assertTrue(again["reused"], again)
            self.assertEqual(fresh["packet_id"], again["packet_id"])
            self.assertEqual(before_science, self.science_snapshot(db))
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(original_packet, db.packet(first["packet_id"]))
            self.assertEqual(original_payload, db.get_blob(original_packet["payload_sha256"]))
            successor = self.authored(again, outcome="gap",
                reasoning="The closing inference is now examined; the induction still lacks its base premise.")
            successor["results"][0]["supersedes"] = predecessor.pinned
            saved = self.submit(db, again, successor)
            self.assertEqual("accepted", saved["state"], saved)
            self.assertFalse(saved["remaining_task_ids"], saved)
            after_tasks = {row["id"]: row for row in derive_work(db, audit_id=fixture.audit_id)["tasks"]}
            self.assertEqual(set(before_tasks), set(after_tasks))
            own_reconciliation = next(row for row in after_tasks.values()
                if row["target"] == predecessor.body["target"] and row["action"] == "reconcile")
            changed_states = {tid for tid in before_tasks if before_tasks[tid]["state"] != after_tasks[tid]["state"]}
            self.assertEqual({first["assigned_task_ids"][0], own_reconciliation["id"]}, changed_states)
            self.assertEqual("ready", own_reconciliation["state"])
            self.assertEqual("satisfied", after_tasks[first["assigned_task_ids"][0]]["state"])
            self.assertEqual("unavailable", after_tasks[first["assigned_task_ids"][0]]["dependency_support"])
            self.assertEqual(prior_body, db.head("checks", predecessor.id).body)
            intake = db.work_submission(accepted["request_id"])
            self.assertEqual(self.raw(response), db.get_blob(intake["response_sha256"]))
            self.assertEqual(original_packet, db.packet(first["packet_id"]))

    def test_partial_renewal_inventory_keeps_only_assigned_unsuperseded_primary_candidates(self):
        fixture = self.fixture("partial-inventory").audit()
        with fixture.open() as db:
            first = self.composition_only(db, fixture)
            rows = [fixture.check_edit(cid, R("arguments", target), "composition", outcome="gap",
                                      evidence=["anc_lem_proof" if target == "arg_lem" else "anc_thm_proof"])
                    for cid, target in (("chk_old", "arg_lem"), ("chk_other", "arg_lem"),
                                        ("chk_unrelated", "arg_thm"))]
            for row in rows:
                row["body"].update(extent="partial", omissions="The closing supplied inference remains unread.")
            fixture.apply(db, rows, *fixture.ITEMS, mode="primary")
            old = db.head("checks", "chk_old")
            successor = fixture.check_edit("chk_successor", old.body["target"], "composition", outcome="gap",
                evidence=["anc_lem_proof"], supersedes=old.pinned)
            successor["body"].update(extent="partial", omissions="The closing supplied inference remains unread.")
            fixture.apply(db, [successor], *fixture.ITEMS, mode="primary")
            refreshed = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
            self.assertNotEqual(first["packet_id"], refreshed["packet_id"])
            self.assertEqual({"chk_other", "chk_successor"},
                {row["ref"]["id"] for row in refreshed["coordinator_guidance"]["renewal_candidates"]})
            self.assertTrue(all(row["task_id"] == first["assigned_task_ids"][0]
                for row in refreshed["coordinator_guidance"]["renewal_candidates"]))

    def test_independent_partial_continuation_reuses_source_only_packet_and_preserves_response(self):
        fixture, first = self.prepare("independent-continuation", "independent")
        response = self.authored(first, outcome="gap", extent="partial",
            omissions="The supplied closing inference remains unread.")
        with fixture.open() as db:
            accepted = self.submit(db, first, response)
            self.assertEqual("accepted", accepted["state"], accepted)
            original_packet = deepcopy(db.packet(first["packet_id"]))
            saved_responses = {row.id: deepcopy(row.body) for row in db.heads("responses")}
            snapshot = self.science_snapshot(db)
            again = stage1.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                focus=R("items", "itm_lem"))
            self.assertTrue(again["reused"], again)
            self.assertEqual(first["packet_id"], again["packet_id"])
            self.assertNotIn("renewal_candidates", again["coordinator_guidance"])
            self.assertEqual(snapshot, self.science_snapshot(db))
            self.assertTrue(all(row["supersedes"] is None for row in again["scaffold"]["judgments"]))
            self.assertEqual("accepted", self.submit(db, again, self.authored(again))["state"])
            self.assertEqual(original_packet, db.packet(first["packet_id"]))
            for identity, body in saved_responses.items():
                self.assertEqual(body, db.head("responses", identity).body)
                self.assertEqual(self.raw(response), db.get_blob(body["original_blob"]))
            task = next(row for row in assessment.derive_assessment(db, audit_id=fixture.audit_id)["obligations"]
                if row["role"] == "independent" and row["target"] == R("arguments", "arg_lem"))
            self.assertTrue(task["satisfied"], task)

    def test_actual_role_exports_preserve_native_packet_scaffold_and_source_only_boundary(self):
        for mode in ("primary", "independent"):
            with self.subTest(mode=mode):
                fixture, prepared = self.prepare("exports-" + mode, mode)
                with fixture.open() as db:
                    saved = db.packet(prepared["packet_id"])
                    payload = db.get_blob(saved["payload_sha256"])
                    manifest = deepcopy(saved["manifest"])
                    scaffold = controller.response_scaffold(manifest)
                    files = controller.write_artifacts(db, prepared, self.path("export-" + mode))
                    delivered = {name: json.loads(Path(row["path"]).read_text(encoding="utf-8"))
                                 for name, row in files.items()}
                    self.assertEqual(prepared["worker_guidance"], delivered["worker-guidance.json"])
                    self.assertEqual(scaffold, delivered["response-scaffold.json"])
                    self.assertEqual(json.loads(payload), delivered["worker-packet.json"])
                    self.assertEqual(manifest, delivered["coordinator-manifest.json"])
                    self.assertEqual(payload, db.get_blob(saved["payload_sha256"]))
                    self.assertEqual(manifest, db.packet(prepared["packet_id"])["manifest"])
                guidance = delivered["worker-guidance.json"]
                self.assertIn("examination_note", guidance)
                if mode == "independent":
                    self.assertIn("judgment_shape", guidance)
                    self.assertNotIn("response_shape", guidance)
                    self.assertNotIn("optional_finding_example", guidance)
                    self.assertNotIn("authoring_note", guidance)
                    self.assertNotIn("coordinator-guidance.json", prepared["worker_delivery_files"])
                    for name in prepared["worker_delivery_files"]:
                        self.assertNotIn("checked against the source", Path(files[name]["path"]).read_text(encoding="utf-8"))
                    self.assertIn("question_id", scaffold["judgments"][0])
                else:
                    self.assertIn("optional_finding_example", guidance)
                    self.assertTrue(all(row["type"] in ("source_fidelity", "check") for row in scaffold["results"]))

    def test_source_fidelity_only_export_has_no_composition_instructions(self):
        fixture = self.fixture("source-only").audit()
        with fixture.open() as db:
            status = stage1.stage_status(db, audit_id=fixture.audit_id)
            tasks = [row["id"] for row in status["tasks"] if row["action"] == "compare_source"
                     and row["target"] == R("items", "itm_lem")]
            self.assertTrue(tasks)
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id, task_ids=tasks)
            self.assertTrue(prepared["prepared"], prepared)
            files = controller.write_artifacts(db, prepared, self.path("source-only-export"))
        guidance = json.loads(Path(files["worker-guidance.json"]["path"]).read_text(encoding="utf-8"))
        self.assertNotIn("examination_note", guidance)
        self.assertTrue(all(row["type"] == "source_fidelity" for row in prepared["scaffold"]["results"]))

    def test_examined_gap_native_returns_finish_without_reexamining_or_changing_judgments(self):
        for mode in ("primary", "independent"):
            with self.subTest(mode=mode):
                fixture, prepared = self.prepare("gap-" + mode, mode)
                response = self.authored(prepared)
                original = deepcopy(response)
                self.assertEqual([], validate_shape(WORKER_RESPONSE if mode == "independent"
                                                    else WORK_PRIMARY_RESPONSE, response))
                with fixture.open() as db:
                    receipt = self.submit(db, prepared, response)
                    self.assertEqual("accepted", receipt["state"], receipt)
                    self.assertEqual([], receipt["remaining_task_ids"])
                    self.assert_saved_judgment(db, prepared, response, extent="whole_unit", omissions="", outcome="gap")
                    remaining = stage1.prepare_stage(db, audit_id=fixture.audit_id, mode=mode,
                        stage=1 if mode == "primary" else 2, focus=R("items", "itm_lem"))
                    self.assertFalse(remaining["prepared"], remaining)
                self.assertEqual(original, response)

    def test_unread_material_stays_partial_and_pending_with_original_reasoning(self):
        cases = (("continuation", "The supplied closing paragraph remains unexamined."),
                 ("unreadable", "The necessary quantifier in the supplied proof remains unreadable."))
        for mode in ("primary", "independent"):
            for name, limitation in cases:
                with self.subTest(mode=mode, limitation=name):
                    fixture, prepared = self.prepare(mode + "-" + name, mode)
                    response = self.authored(prepared, outcome="inconclusive", extent="partial",
                                             omissions=limitation, reasoning=limitation)
                    with fixture.open() as db:
                        receipt = self.submit(db, prepared, response)
                        self.assertEqual("accepted", receipt["state"], receipt)
                        self.assertTrue(receipt["remaining_task_ids"])
                        diagnostic = " ".join(row["message"] for row in receipt["diagnostics"])
                        self.assertIn("judgment recorded", diagnostic)
                        self.assertIn("coverage", diagnostic)
                        self.assertIn("partial", diagnostic)
                        action = " ".join(receipt["next_actions"])
                        self.assertIn("omissions", action)
                        self.assertIn("unexamined", action)
                        self.assertIn("explicitly", action)
                        self.assert_saved_judgment(db, prepared, response, extent="partial",
                                                  omissions=limitation, outcome="inconclusive")

    def test_literal_no_omission_prose_is_rejected_and_preserved_without_automatic_correction(self):
        for mode in ("primary", "independent"):
            with self.subTest(mode=mode):
                fixture, prepared = self.prepare("none-material-" + mode, mode)
                response = self.authored(prepared, omissions="None material; all supplied material was examined.")
                with fixture.open() as db:
                    before = self.judgment_snapshot(db)
                    receipt = self.submit(db, prepared, response)
                    self.assertEqual("needs_revision", receipt["state"], receipt)
                    self.assertEqual(before, self.judgment_snapshot(db))
                    diagnostic = json.dumps(receipt["diagnostics"], ensure_ascii=False)
                    if mode == "independent":
                        saved = db.head("responses", receipt["response_id"])
                        self.assertEqual("needs_revision", saved.body["state"])
                        self.assertTrue(saved.body["pending_judgments"])
                        diagnostic += " ".join(saved.body["intake_diagnostics"])
                    self.assertIn("omissions", diagnostic)
                    self.assertIn("unexamined", diagnostic)
                    self.assertIn("reasoning/findings", diagnostic)
                    self.assertIn("whole_unit", diagnostic)
                    row = next(row for row in response.get("results", response.get("judgments", []))
                               if "reasoning" in row)
                    self.assertEqual("whole_unit", row["extent"])
                    self.assertEqual("None material; all supplied material was examined.", row["omissions"])

    def test_assessed_external_unavailability_can_finish_inconclusive(self):
        for mode in ("primary", "independent"):
            with self.subTest(mode=mode):
                fixture, prepared = self.prepare("external-" + mode, mode)
                response = self.authored(prepared, outcome="inconclusive",
                    reasoning="All supplied attribution was examined. The unavailable cited source cannot establish the uniform bound.")
                with fixture.open() as db:
                    receipt = self.submit(db, prepared, response)
                    self.assertEqual("accepted", receipt["state"], receipt)
                    self.assertEqual([], receipt["remaining_task_ids"])
                    self.assert_saved_judgment(db, prepared, response, extent="whole_unit",
                                              omissions="", outcome="inconclusive")

    def test_primary_gap_and_finding_category_are_distinct_native_fields(self):
        fixture, prepared = self.prepare("primary-finding")
        response = self.authored(prepared)
        check = next(row for row in response["results"] if row["type"] == "check")
        response["findings"] = [{"target": R("arguments", "arg_lem"), "category": "proof_gap",
            "description": "The induction has no supplied inductive premise.", "evidence_refs": ["anc_lem_proof"],
            "related_task_ids": [check["task_id"]], "existing_check_refs": [], "affected_uses": [],
            "impact_reason": "The supplied argument cannot establish its claimed induction."}]
        with fixture.open() as db:
            receipt = self.submit(db, prepared, response)
            self.assertEqual("accepted", receipt["state"], receipt)
            self.assert_saved_judgment(db, prepared, response, extent="whole_unit", omissions="", outcome="gap")
            self.assertEqual(1, len(db.heads("findings")))
            self.assertEqual("proof_gap", db.heads("findings")[0].body["category"])
            self.assertEqual(response["findings"][0]["description"], db.heads("findings")[0].body["description"])

    def test_malformed_native_types_are_retained_without_outcome_or_coverage_normalization(self):
        for mode in ("primary", "independent"):
            variants = ("finding-as-outcome", "list-omissions")
            if mode == "independent":
                variants += ("primary-findings",)
            for variant in variants:
                with self.subTest(mode=mode, variant=variant):
                    fixture, prepared = self.prepare(mode + "-" + variant, mode)
                    response = self.authored(prepared)
                    row = next(row for row in response.get("results", response.get("judgments", []))
                               if "reasoning" in row)
                    if variant == "finding-as-outcome":
                        row["outcome"] = "proof_gap"
                    elif variant == "list-omissions":
                        row["omissions"] = ["Keep this adverse unfinished passage."]
                    else:
                        response["findings"] = []
                    original = deepcopy(response)
                    with fixture.open() as db:
                        before = self.judgment_snapshot(db)
                        receipt = self.submit(db, prepared, response)
                        self.assertEqual("needs_revision", receipt["state"], receipt)
                        self.assertEqual(before, self.judgment_snapshot(db))
                        if mode == "independent" and variant != "primary-findings":
                            self.assertTrue(any(row.body.get("pending_judgments") for row in db.heads("responses")))
                        if variant == "primary-findings":
                            self.assertTrue(any(row.body["state"] == "needs_revision"
                                and db.get_blob(row.body["original_blob"]) == self.raw(response)
                                for row in db.heads("responses")))
                    self.assertEqual(original, response)
