"""Selective external-result work and bounded source packets through real APIs."""
from support import R, TempCase, edit, locator
from paper_core import assessment, finalization, packets, review, sources, work


class ExternalResultTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def add_external(self, *, available=True, borrowed=False):
        statement_anchor, proof_anchor, scope_id = "anc_thm_proof", None, None
        if available:
            (self.fx.source_root / "cited-result.txt").write_text(
                "Assume uniform integrability.\nThe sequence converges in mean.\n"
                "Proof: a long auxiliary argument referring to another publication.\n", encoding="utf-8")
            captured = sources.capture_sources(self.db, files=["cited-result.txt"])
            source_id = captured["sources"][0]["id"]
            packet = self.fx.packet(self.db)
            sources.anchor_sources(self.db, request={"contract_version": 4,
                "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
                "anchors": [{"id": f"anc_external_{name}", "expected_version": None,
                    "source_id": source_id, "locator": locator(start=line, end=line)}
                    for name, line in (("setup", 1), ("statement", 2), ("proof", 3))]})
            statement_anchor, proof_anchor, scope_id = "anc_external_statement", "anc_external_proof", "scp_external"
        external = self.fx.item_edit("itm_external", "external_result", "Cited convergence theorem",
                                     statement_anchor, proof_anchor or statement_anchor)
        external["body"].update(statement={"form": "transcription", "text": "The sequence converges in mean."},
            scope_id=scope_id, passages=[{"role": "statement", "anchor_id": statement_anchor}] +
                ([{"role": "proof", "anchor_id": proof_anchor}] if proof_anchor else []))
        edits = [external, edit("create", "target_specs", "tgt_external", {
            "target": R("items", "itm_external"), "statement_ref": None,
            "statement": external["body"]["statement"], "scope_id": scope_id,
            "evidence_refs": [statement_anchor], "state": "registered", "fidelity_ref": None})]
        if scope_id:
            edits.append(edit("create", "scopes", scope_id, {"argument_id": None, "parent_id": None,
                "assumptions": [], "binders": [], "conditions": ["uniform integrability"],
                "evidence_refs": ["anc_external_setup"]}))
        for name in ("lem", "thm"):
            edits.append(edit("create", "uses", f"use_external_{name}", {
                "from": R("items", "itm_external"), "to": R("items", f"itm_{name}"),
                "type": "proof_argument" if borrowed else "dependency", "group_id": f"grp_{name}",
                "reason": "uses the cited convergence result", "needed_form": {
                    "form": "transcription", "text": "The sequence converges in mean."},
                "substitutions": [], "evidence_refs": [f"anc_{name}_proof"],
                "regime": None, "uncertainty": None}))
        self.fx.apply(self.db, edits)
        return statement_anchor

    def prepare(self, target, kind, *, mode="primary"):
        task = {"id": "task_selected", "target": target, "kind": kind, "role": mode,
                "action": "check", "prerequisite_ids": [], "draft_refs": []}
        return packets.prepare_assignment(self.db, audit_id=self.fx.audit_id, mode=mode,
            selection={"revision": self.db.max_revision(), "units": [{"id": "unit_selected",
                "task_ids": [task["id"]]}], "tasks": [task]})

    @staticmethod
    def anchors(prepared):
        return {row["ref"]["id"] for row in prepared["packet"]["records"]
                if row["ref"]["collection"] == "anchors"}

    def record_external_check(self, anchor, *, outcome="inconclusive"):
        packet = self.fx.packet(self.db, "items:itm_external", mode="primary")
        review.compare(self.db, batch=self.fx.batch([edit("create", "observations", "obs_external", {
            "target": R("items", "itm_external"), "result": "matched", "reviewer": "primary",
            "note": "The recorded result matches the captured passage; publication validation is separate.",
            "evidence_refs": [anchor]})], packet["packet_id"]))
        check = self.fx.check_edit("chk_external", R("items", "itm_external"), "external_source",
            outcome=outcome, evidence=[anchor])
        check["body"]["reasoning"] = ("The cited publication could not be obtained with available tools. "
            "Its stated result remains unverified." if outcome == "inconclusive" else
            "The captured theorem states the result under the recorded assumptions.")
        self.fx.apply(self.db, [check], "items:itm_external", mode="primary")

    def test_routine_fact_in_reasoning_does_not_create_external_work(self):
        group = self.db.head("groups", "grp_thm")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, rationale="The displayed estimate is a routine use of Cauchy-Schwarz."), group.version)])
        self.fx.primary()
        result = assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)
        self.assertTrue(result["progress"]["process_complete"], result["problems"])
        self.assertFalse(any(row["kind"] == "external_source" for row in result["obligations"]))
        self.assertFalse(any(row.body["kind"] == "external_result" for row in self.db.heads("items")))

    def test_source_verification_selects_statement_and_setup_without_external_proof(self):
        self.add_external()
        prepared = self.prepare(R("items", "itm_external"), "external_source")
        self.assertTrue(prepared["prepared"], prepared)
        anchors = self.anchors(prepared)
        self.assertIn("anc_external_statement", anchors)
        self.assertIn("anc_external_setup", anchors)
        self.assertNotIn("anc_external_proof", anchors)
        consumed = prepared["manifest"]["work"]["tasks"][0]["consumed_inputs"]
        self.assertFalse(any(row["ref"] == self.fx.pin(self.db, "anchors", "anc_external_proof") for row in consumed))
        for mode in ("primary", "independent"):
            with self.subTest(mode=mode):
                consumer = self.prepare(R("arguments", "arg_thm"), "composition", mode=mode)
                self.assertIn("anc_external_statement", self.anchors(consumer))
                self.assertIn("anc_external_setup", self.anchors(consumer))
                self.assertNotIn("anc_external_proof", self.anchors(consumer))

    def test_actual_proof_borrowing_keeps_external_passage_for_both_examiners(self):
        self.add_external(borrowed=True)
        for mode in ("primary", "independent"):
            with self.subTest(mode=mode):
                prepared = self.prepare(R("arguments", "arg_thm"), "composition", mode=mode)
                self.assertTrue(prepared["prepared"], prepared)
                self.assertIn("anc_external_proof", self.anchors(prepared))
                if mode == "independent":
                    self.assertEqual([], packets.blinding_violations(prepared["packet"]))

    def test_one_external_result_is_reused_but_applications_can_differ(self):
        anchor = self.add_external()
        self.fx.primary()
        self.record_external_check(anchor, outcome="supported")
        self.fx.apply(self.db, [
            self.fx.check_edit("chk_external_lem", R("uses", "use_external_lem"), "application",
                outcome="supported", evidence=["anc_lem_proof"]),
            self.fx.check_edit("chk_external_thm", R("uses", "use_external_thm"), "application",
                outcome="gap", evidence=["anc_thm_proof"])], *self.fx.ITEMS, mode="primary")
        result = assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)
        external = [row for row in result["obligations"] if row["kind"] == "external_source"]
        self.assertEqual(1, len(external))
        self.assertEqual(R("items", "itm_external"), external[0]["target"])
        self.assertTrue(external[0]["satisfied"])
        self.assertEqual("available", result["support"]["items:itm_external"])
        self.assertEqual("green", result["assessments"]["uses:use_external_lem"]["local_state"])
        self.assertEqual("red", result["assessments"]["uses:use_external_thm"]["local_state"])
        self.assertTrue(result["progress"]["process_complete"], result["problems"])

    def test_unavailable_external_publication_finishes_without_claiming_support_or_reassigning(self):
        anchor = self.add_external(available=False)
        self.fx.primary()
        self.record_external_check(anchor)
        result = assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)
        self.assertTrue(result["progress"]["process_complete"], result["problems"])
        self.assertEqual("conditional", result["support"]["items:itm_external"])
        self.assertEqual("conditional", result["support"]["items:itm_thm"])
        view = work.derive_work(self.db, audit_id=self.fx.audit_id)
        external = [row for row in view["tasks"] if row["kind"] == "external_source"]
        self.assertEqual(1, len(external))
        self.assertEqual("satisfied", external[0]["state"])
        self.assertEqual("inconclusive", external[0]["outcome"])
        self.assertFalse(any(row["state"] != "satisfied" for row in view["tasks"] if row["required"]))
        frozen = finalization.finalize_audit(self.db, audit_id=self.fx.audit_id, output=self.path("external-limited"))
        self.assertEqual("release", frozen["kind"], frozen["finalization_blockers"])
        self.assertEqual("conditional", frozen["status"]["assessments"]["items:itm_external"]["availability"])

    def test_external_limitation_does_not_hide_a_missing_supplied_proof_passage(self):
        anchor = self.add_external(available=False)
        self.fx.primary()
        self.record_external_check(anchor)
        packet = self.fx.packet(self.db, *self.fx.ITEMS, mode="primary")
        sources.review_sources(self.db, batch=self.fx.batch([edit("create", "source_issues", "iss_missing", {
            "source_id": self.fx.source_id, "anchor_id": "anc_thm_proof", "category": "missing_source",
            "description": "The provided paper's proof continuation was not captured.", "lifecycle": "open",
            "resolution": None, "reviewer": "coordinator"})], packet["packet_id"]))
        result = assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(result["source_limits"])
        view = work.derive_work(self.db, audit_id=self.fx.audit_id)
        self.assertTrue(any(row["code"] == "source_attention" for row in view["coordinator_actions"]))
