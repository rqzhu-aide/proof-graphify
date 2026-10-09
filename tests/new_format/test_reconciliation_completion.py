"""Exact-target review rows jointly close a route without hiding unfinished review."""
from __future__ import annotations

from support import R, TempCase, edit, node_available, run_cli
from paper_core import assessment, review, work
from paper_core.canonical import canonical_bytes


TARGETS = [
    ("arguments", "arg_lem", "composition", "chk_comp_lem"),
    ("groups", "grp_lem", "derivation", "chk_der_lem"),
    ("arguments", "arg_thm", "composition", "chk_comp_thm"),
    ("groups", "grp_thm", "derivation", "chk_der_thm"),
    ("uses", "use_lem_thm", "application", "chk_app"),
]


class ReconciliationCompletionTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def independent(self, targets=TARGETS):
        packet = self.fx.packet(self.db, *self.fx.ITEMS, mode="independent")
        worker = {"packet_id": packet["packet_id"], "covered_targets": self.fx.ITEM_REFS,
            "coverage_note": "The listed source passages were examined independently.",
            "exposure_report": {"status": "none_known", "note": ""}, "judgments": []}
        for index, (collection, identifier, kind, _) in enumerate(targets):
            anchor = "anc_lem_proof" if identifier.endswith("lem") else "anc_thm_proof"
            worker["judgments"].append({"target": {"source_anchor_id": anchor,
                "description": f"Source examination {index}: {kind}"}, "kind": kind,
                "state": "complete", "outcome": "supported", "reasoning": "Checked this local source argument.",
                "evidence_refs": [anchor], "conditions": [], "next_action": None, "supersedes": None})
        result = review.submit_review(self.db, submission={"contract_version": 3,
            "request_id": self.fx.request_id(), "packet_id": packet["packet_id"], "reviewer": "checker-A",
            "qualification_id": "qua_r1", "exposure": "source_only", "exposure_note": ""},
            response_bytes=canonical_bytes(worker))
        self.assertEqual(result["state"], "needs_revision")
        mapping = self.fx.packet(self.db, *self.fx.ITEMS, mode="primary")
        mapped = review.map_response(self.db, mapping={"contract_version": 3,
            "request_id": self.fx.request_id(), "packet_id": mapping["packet_id"],
            "response_id": result["response_id"], "reviewer": "coordinator", "entries": [
                {"judgment_index": index, "target": R(collection, identifier),
                 "rationale": "The source passage and kind identify this exact registered examination."}
                for index, (collection, identifier, _, _) in enumerate(targets)]})
        self.assertEqual(mapped["state"], "accepted")
        return {(collection, identifier): row["check_id"]
                for (collection, identifier, _, _), row in zip(targets, mapped["checks"])}

    def reconcile(self, independent, targets=TARGETS, *, prefix="rec", decision="agree", supersedes=None):
        packet = self.fx.packet(self.db, *self.fx.ITEMS, mode="reconcile")
        edits = []
        for index, (collection, identifier, _, primary) in enumerate(targets):
            edits.append(edit("create", "reconciliations", f"{prefix}_{index}", {
                "audit_id": self.fx.audit_id, "target": R(collection, identifier),
                "primary_checks": [self.fx.pin(self.db, "checks", primary)],
                "independent_checks": [self.fx.pin(self.db, "checks", independent[(collection, identifier)])],
                "decision": decision, "rationale": "Compared the exact local examinations.",
                "evidence_refs": [], "successor_checks": [], "supersedes": supersedes,
                "adjudicator": "coordinator"}))
        review.reconcile(self.db, batch=self.fx.batch(edits, packet["packet_id"]))

    def status(self):
        return assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)

    def test_five_exact_target_rows_complete_two_result_reviews(self):
        independent = self.independent()
        self.reconcile(independent)
        status = self.status()
        self.assertEqual(status["independent"], {"items:itm_lem": "complete", "items:itm_thm": "complete"})
        self.assertTrue(status["progress"]["process_complete"])
        self.assertEqual(status["progress"]["required_obligations"],
                         status["progress"]["completed_current_obligations"])
        tasks = work.derive_work(self.db, audit_id=self.fx.audit_id)["tasks"]
        self.assertTrue(all(task["state"] == "satisfied" for task in tasks if task["required"]))

    def test_missing_exact_target_row_leaves_only_affected_result_pending(self):
        independent = self.independent()
        self.reconcile(independent, TARGETS[:-1])
        status = self.status()
        self.assertEqual(status["independent"]["items:itm_lem"], "complete")
        self.assertEqual(status["independent"]["items:itm_thm"], "pending")
        self.assertFalse(status["progress"]["process_complete"])
        self.reconcile(independent, [TARGETS[-1]], prefix="rec_last")
        self.assertTrue(self.status()["progress"]["process_complete"])

    def test_unresolved_exact_target_row_requires_explicit_successor(self):
        independent = self.independent()
        self.reconcile(independent, TARGETS[:-1])
        self.reconcile(independent, [TARGETS[-1]], prefix="rec_open", decision="unresolved")
        self.assertEqual(self.status()["independent"]["items:itm_thm"], "disputed")
        # A separate agreement cannot silently overwrite the unresolved row.
        self.reconcile(independent, [TARGETS[-1]], prefix="rec_separate")
        self.assertEqual(self.status()["independent"]["items:itm_thm"], "disputed")
        self.reconcile(independent, [TARGETS[-1]], prefix="rec_resolution",
                       supersedes=self.fx.pin(self.db, "reconciliations", "rec_open_0"))
        self.assertEqual(self.status()["independent"]["items:itm_thm"], "complete")

    def test_stale_reconciliation_row_cannot_supply_union_coverage(self):
        independent = self.independent()
        self.reconcile(independent)
        argument = self.db.head("arguments", "arg_thm")
        self.fx.apply(self.db, [edit("replace", "arguments", argument.id,
            dict(argument.body, label="Updated presentation of the same argument"), argument.version)])
        status = self.status()
        self.assertEqual(status["judgments"]["checks:" + independent[("arguments", "arg_thm")]]["freshness"], "current")
        self.assertEqual(status["independent"]["items:itm_lem"], "complete")
        self.assertEqual(status["independent"]["items:itm_thm"], "pending")

    def test_late_accepted_check_reopens_only_its_result(self):
        independent = self.independent()
        self.reconcile(independent)
        self.assertTrue(self.status()["progress"]["process_complete"])
        self.independent([TARGETS[-1]])
        status = self.status()
        self.assertEqual(status["independent"]["items:itm_lem"], "complete")
        self.assertEqual(status["independent"]["items:itm_thm"], "pending")
        self.assertFalse(status["progress"]["process_complete"])

    def primary_successor(self, *, outcome="gap", supersedes=True):
        check = self.fx.check_edit("chk_comp_lem_new", R("arguments", "arg_lem"), "composition",
            outcome=outcome, evidence=["anc_lem_proof"],
            supersedes=self.fx.pin(self.db, "checks", "chk_comp_lem") if supersedes else None)
        check["body"]["reasoning"] = "Re-examined the complete argument and recorded the current primary opinion."
        self.fx.apply(self.db, [check], *self.fx.ITEMS, mode="primary")
        return self.fx.pin(self.db, "checks", check["id"])

    def test_primary_successor_reopens_review_work_and_blocks_release_until_adjudicated(self):
        independent = self.independent()
        self.reconcile(independent)
        response = self.db.head("responses", self.db.head("checks", independent[("arguments", "arg_lem")]).body["response_id"])
        original = self.db.get_blob(response.body["original_blob"])
        self.primary_successor()

        status = self.status()
        self.assertEqual(status["independent"], {"items:itm_lem": "disputed", "items:itm_thm": "complete"})
        self.assertFalse(status["progress"]["process_complete"])
        self.assertEqual(status["assessments"]["items:itm_lem"]["state"], "red")
        tasks = work.derive_work(self.db, audit_id=self.fx.audit_id)["tasks"]
        reconciliation = next(t for t in tasks if t["kind"] == "reconciliation" and t["target"] == R("items", "itm_lem"))
        self.assertNotEqual(reconciliation["state"], "satisfied")
        self.assertTrue(all(t["state"] == "satisfied" for t in tasks if t["role"] == "independent"))
        refused, _ = run_cli("release", self.fx.path, "--audit", self.fx.audit_id,
                             "--out", self.work / "blocked", expect=2)
        self.assertEqual(refused["error"]["code"], "RELEASE_BLOCKED")
        self.assertFalse((self.work / "blocked").exists())

        # Explicit adjudication can close a negative audit without changing the
        # preserved independent opinion or commissioning another source reading.
        self.reconcile(independent, [("arguments", "arg_lem", "composition", "chk_comp_lem_new")],
                       prefix="rec_current", supersedes=self.fx.pin(self.db, "reconciliations", "rec_0"))
        status = self.status()
        self.assertTrue(status["progress"]["process_complete"])
        self.assertEqual(status["independent"]["items:itm_lem"], "complete")
        self.assertEqual(status["assessments"]["items:itm_lem"]["state"], "red")
        self.assertEqual(self.db.get_blob(response.body["original_blob"]), original)
        self.assertTrue(all(t["state"] == "satisfied" for t in work.derive_work(
            self.db, audit_id=self.fx.audit_id)["tasks"] if t["required"]))
        if node_available():
            released, _ = run_cli("release", self.fx.path, "--audit", self.fx.audit_id,
                                  "--out", self.work / "released")
            self.assertTrue(released["process_complete"])
            self.assertEqual(released["publication"]["state"], "published")

    def test_same_outcome_primary_successor_still_needs_current_comparison(self):
        independent = self.independent()
        self.reconcile(independent)
        self.primary_successor(outcome="supported")
        status = self.status()
        self.assertEqual(status["independent"], {"items:itm_lem": "pending", "items:itm_thm": "complete"})
        self.assertFalse(status["progress"]["process_complete"])

    def test_additional_primary_opinion_must_be_included_in_renewed_comparison(self):
        independent = self.independent()
        self.reconcile(independent)
        self.primary_successor(outcome="supported", supersedes=False)
        self.reconcile(independent, TARGETS[:1], prefix="rec_omits_late")
        self.assertEqual(self.status()["independent"]["items:itm_lem"], "pending")
        packet = self.fx.packet(self.db, *self.fx.ITEMS, mode="reconcile")
        row = self.fx.reconciliation_edit(self.db, "rec_both_primary", "arg_lem", "chk_comp_lem",
                                         independent[("arguments", "arg_lem")])
        row["body"]["primary_checks"].append(self.fx.pin(self.db, "checks", "chk_comp_lem_new"))
        review.reconcile(self.db, batch=self.fx.batch([row], packet["packet_id"]))
        self.assertTrue(self.status()["progress"]["process_complete"])

    def test_primary_revised_row_can_name_same_batch_opinion_only_as_successor(self):
        independent = self.independent()
        self.reconcile(independent)
        successor = self.fx.check_edit("chk_comp_lem_new", R("arguments", "arg_lem"), "composition",
            outcome="gap", evidence=["anc_lem_proof"], supersedes=self.fx.pin(self.db, "checks", "chk_comp_lem"))
        packet = self.fx.packet(self.db, *self.fx.ITEMS, mode="reconcile")
        row = self.fx.reconciliation_edit(self.db, "rec_primary_revised", "arg_lem", "chk_comp_lem",
                                         independent[("arguments", "arg_lem")])
        row["body"].update(decision="primary_revised",
                          successor_checks=[dict(R("checks", successor["id"]), version=1)],
                          supersedes=self.fx.pin(self.db, "reconciliations", "rec_0"))
        review.reconcile(self.db, batch=self.fx.batch([successor, row], packet["packet_id"]))
        status = self.status()
        self.assertEqual(status["independent"]["items:itm_lem"], "complete")
        self.assertTrue(status["progress"]["process_complete"])
        self.assertEqual(status["assessments"]["items:itm_lem"]["state"], "red")

    def test_all_stale_independent_evidence_cannot_complete_vacuously(self):
        independent = self.independent()
        self.reconcile(independent)
        lemma = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "items", lemma.id,
            dict(lemma.body, statement={"form": "verbatim", "text": "A changed mathematical conclusion."}),
            lemma.version)])
        status = self.status()
        lemma_checks = [status["judgments"]["checks:" + independent[(collection, identifier)]]
                        for collection, identifier, _, _ in TARGETS[:2]]
        self.assertTrue(all(row["freshness"] != "current" for row in lemma_checks))
        self.assertEqual(status["independent"]["items:itm_lem"], "pending")
        self.assertFalse(status["progress"]["process_complete"])

    def test_reconciled_local_checks_cannot_replace_missing_final_composition(self):
        targets = [row for row in TARGETS if row[2] != "composition"]
        independent = self.independent(targets)
        self.reconcile(independent, targets)
        status = self.status()
        self.assertEqual(status["independent"], {"items:itm_lem": "pending", "items:itm_thm": "pending"})
        self.assertFalse(status["progress"]["process_complete"])

    def test_new_written_route_requires_its_own_independent_review(self):
        independent = self.independent()
        self.reconcile(independent)
        self.fx.apply(self.db, [self.fx.argument_edit("arg_alternative", "itm_lem", "grp_alternative", "anc_lem_proof"),
            self.fx.group_edit("grp_alternative", "arg_alternative", "itm_lem", "anc_lem_proof")])
        status = self.status()
        self.assertEqual(status["independent"]["items:itm_lem"], "pending")
        required = [row for row in status["obligations"] if row["target"] == R("arguments", "arg_alternative")
                    and row["role"] == "independent"]
        self.assertEqual(len(required), 1)
        self.assertFalse(required[0]["satisfied"])


if __name__ == "__main__":
    import unittest
    unittest.main()
