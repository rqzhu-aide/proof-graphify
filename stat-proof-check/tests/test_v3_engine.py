"""Scientific counterexamples for the coherent examination engine."""
from copy import deepcopy
import json

from support import Fixture, R, TempCase, edit
from paper_core import assessment, review


class CoherentEngineTests(TempCase):
    def fixture(self, *, independent=False, mode="focused"):
        fixture = Fixture(self.path("case"))
        fixture.audit(independent_required=independent, mode=mode)
        return fixture

    def primary_units(self, fixture, *, outcomes=None, extent="whole_unit"):
        outcomes = outcomes or {}
        with fixture.open() as db:
            edits = []
            for name in ("lem", "thm"):
                row = fixture.check_edit(f"chk_comp_{name}", R("arguments", f"arg_{name}"), "composition",
                                         outcome=outcomes.get(name, "supported"), evidence=[f"anc_{name}_proof"])
                row["body"].update(extent=extent, omissions="The final combination is omitted." if extent == "partial" else "")
                edits.append(row)
            fixture.apply(db, edits, *fixture.ITEMS, mode="primary")
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            review.compare(db, batch=fixture.batch([
                edit("create", "observations", f"obs_{name}", {
                    "target": R("items", f"itm_{name}"), "result": "matched", "reviewer": "primary",
                    "note": "The full stored statement and its hypotheses match the captured source.",
                    "evidence_refs": [f"anc_{name}"]}) for name in ("lem", "thm")], packet["packet_id"]))

    def result(self, fixture):
        with fixture.open(write=False) as db:
            return assessment.derive_assessment(db, audit_id="aud_1")

    def test_one_unit_examination_supports_local_reasoning_without_edge_checks(self):
        f = self.fixture()
        self.primary_units(f)
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"], result["problems"])
        self.assertEqual(result["support"], {"items:itm_lem": "available", "items:itm_thm": "available"})
        self.assertEqual(result["coverage_diagnostics"], [])
        self.assertEqual(result["assessments"]["uses:use_lem_thm"]["local_state"], "green")
        with f.open(write=False) as db:
            self.assertEqual(len(db.records_at(db.max_revision(), collection="coverage")), 0)
            self.assertEqual(len(db.records_at(db.max_revision(), collection="checks")), 2)

    def test_same_exact_statement_reuses_one_source_match(self):
        f = self.fixture()
        self.primary_units(f)
        result = self.result(f)
        exact = [o for o in result["obligations"] if o["target"]["collection"] == "target_specs"]
        self.assertTrue(all(o["satisfied"] for o in exact))
        self.assertEqual({r["id"] for o in exact for r in o["check_refs"]}, {"obs_lem", "obs_thm"})

    def test_exact_target_with_lost_hypothesis_cannot_reuse_synopsis(self):
        f = self.fixture()
        with f.open() as db:
            spec = db.head("target_specs", "tgt_lem")
            body = deepcopy(spec.body)
            body.update(statement_ref=None, statement={"form": "verbatim", "text": "Lemma 1 text without its hypotheses"})
            f.apply(db, [edit("replace", "target_specs", spec.id, body, spec.version)], *f.ITEMS, mode="primary")
        self.primary_units(f)
        result = self.result(f)
        self.assertFalse(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_lem"], "conditional")
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")

    def test_inconclusive_whole_unit_finishes_work_without_positive_support(self):
        f = self.fixture()
        self.primary_units(f, outcomes={"thm": "inconclusive"})
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_lem"], "available")
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")

    def test_partial_unit_preserves_performed_work_and_omission(self):
        f = self.fixture()
        self.primary_units(f, extent="partial")
        result = self.result(f)
        self.assertFalse(result["progress"]["process_complete"])
        compositions = [o for o in result["obligations"] if o["kind"] == "composition"]
        self.assertTrue(all(o["performed"] for o in compositions))
        self.assertTrue(all(not o["satisfied"] for o in compositions))
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")

    def test_missing_review_cannot_finish_full_promised_work(self):
        f = self.fixture(independent=True)
        self.primary_units(f)
        result = self.result(f)
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(any(o["kind"] == "reconciliation" and o["state"] == "missing" for o in result["obligations"]))

    def test_routine_internal_detail_and_child_route_do_not_create_required_jobs(self):
        f = self.fixture(mode="full")
        self.primary_units(f)
        before = self.result(f)
        with f.open() as db:
            detail = f.item_edit("itm_detail", "intermediate_result", "Equivalent displayed conclusion", "anc_thm", "anc_thm_proof")
            detail["body"]["owner_id"] = "itm_thm"
            detail["body"]["statement"] = deepcopy(db.head("items", "itm_thm").body["statement"])
            group = f.group_edit("grp_detail", "arg_thm", "itm_detail", "anc_thm_proof")
            child = f.argument_edit("arg_detail", "itm_detail", "grp_child", "anc_thm_proof")
            child_group = f.group_edit("grp_child", "arg_detail", "itm_detail", "anc_thm_proof")
            duplicate_use = edit("create", "uses", "use_detail", {
                "from": R("items", "itm_lem"), "to": R("items", "itm_detail"), "type": "dependency",
                "group_id": "grp_detail", "needed_form": {"form": "verbatim", "text": "Lemma 1 text"},
                "substitutions": [], "reason": "applied as stated", "evidence_refs": ["anc_thm_proof"],
                "regime": None, "uncertainty": None})
            f.apply(db, [detail, group, child, child_group, duplicate_use], *f.ITEMS, mode="primary")
        after = self.result(f)
        self.assertEqual(before["progress"]["required_obligations"], after["progress"]["required_obligations"])
        self.assertTrue(after["progress"]["process_complete"], after["problems"])
        self.assertEqual(after["support"]["items:itm_detail"], "available")
        self.assertFalse(any(o["required"] and o["target"] == R("arguments", "arg_detail") for o in after["obligations"]))

    def test_local_good_application_survives_failed_joint_conclusion(self):
        f = self.fixture()
        self.primary_units(f, outcomes={"thm": "gap"})
        with f.open() as db:
            f.apply(db, [f.check_edit("chk_local_application", R("uses", "use_lem_thm"), "application",
                                     evidence=["anc_thm_proof"])], *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["assessments"]["uses:use_lem_thm"]["local_state"], "green")
        self.assertEqual(result["support"]["items:itm_thm"], "unavailable")
        self.assertEqual(result["assessments"]["arguments:arg_thm"]["state"], "red")

    def test_material_local_defect_beats_supported_whole_unit(self):
        f = self.fixture()
        self.primary_units(f)
        with f.open() as db:
            f.apply(db, [f.check_edit("chk_bad_application", R("uses", "use_lem_thm"), "application",
                                     outcome="gap", evidence=["anc_thm_proof"])], *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_thm"], "unavailable")

    def test_auxiliary_finding_citation_preserves_unaffected_conclusion_and_consumer(self):
        for affected_use in (False, True):
            with self.subTest(affected_use=affected_use):
                f = Fixture(self.path(f"auxiliary_{affected_use}"))
                f.audit(independent_required=False)
                with f.open() as db:
                    auxiliary = f.item_edit("itm_aux", "intermediate_result", "Unused auxiliary bound",
                                            "anc_lem_proof", "anc_lem_proof")
                    auxiliary["body"]["owner_id"] = "itm_lem"
                    f.apply(db, [auxiliary, f.group_edit("grp_aux", "arg_lem", "itm_aux", "anc_lem_proof")],
                            *f.ITEMS, mode="primary")
                    f.apply(db, [edit("create", "target_specs", "tgt_aux", {
                        "target": R("items", "itm_aux"), "statement_ref": f.pin(db, "items", "itm_aux"),
                        "statement": None, "scope_id": None, "evidence_refs": ["anc_lem_proof"],
                        "state": "registered", "fidelity_ref": None})], *f.ITEMS, mode="primary")
                    packet = f.packet(db, *f.ITEMS, mode="primary")
                    review.compare(db, batch=f.batch([edit("create", "observations", "obs_aux", {
                        "target": R("target_specs", "tgt_aux"), "result": "matched", "reviewer": "primary",
                        "note": "The exact auxiliary assertion matches the captured source.",
                        "evidence_refs": ["anc_lem_proof"], "context_kind": "exact_target"})], packet["packet_id"]))
                self.primary_units(f)
                with f.open() as db:
                    citation = f.pin(db, "checks", "chk_comp_lem")
                    f.apply(db, [edit("create", "findings", "fnd_aux", {
                        "audit_id": "aud_1", "target": R("items", "itm_aux"),
                        "category": "proof_gap", "lifecycle": "open",
                        "description": "The unused auxiliary bound has a gap.",
                        "evidence_refs": ["anc_lem_proof"], "check_refs": [citation],
                        "affected_uses": ["use_lem_thm"] if affected_use else [],
                        "impact_reason": "The auxiliary assertion fails; its use is affected only when declared.",
                        "resolution": None})], *f.ITEMS, mode="primary")
                    derivation, result = assessment.derive_full(db, audit_id="aud_1")
                    self.assertEqual(derivation.local_basis.local_finding(R("items", "itm_aux")), "defect")
                    self.assertEqual(derivation.support(R("items", "itm_aux")), "unavailable")
                    self.assertIsNone(derivation.local_basis.local_finding(R("arguments", "arg_lem")))
                    self.assertEqual(derivation.local_basis.resolve(R("arguments", "arg_lem"), "composition"),
                                     "supported")
                    self.assertEqual(result["support"]["items:itm_lem"], "available")
                    self.assertEqual(derivation.local_basis.local_finding(R("uses", "use_lem_thm")),
                                     "defect" if affected_use else None)
                    self.assertEqual(result["support"]["items:itm_thm"],
                                     "unavailable" if affected_use else "available")
                    finding = db.head("findings", "fnd_aux")
                    self.assertEqual(finding.body["check_refs"], [citation])
                    self.assertEqual(finding.body["lifecycle"], "open")

    def test_conflicting_current_primary_summaries_give_no_blanket_basis(self):
        f = self.fixture()
        self.primary_units(f)
        with f.open() as db:
            f.apply(db, [f.check_edit("chk_second_composition", R("arguments", "arg_thm"), "composition",
                                     outcome="gap", evidence=["anc_thm_proof"])], *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")
        self.assertEqual(result["assessments"]["items:itm_thm"]["label"], "disputed")

    def test_changed_application_cannot_inherit_old_unit_basis(self):
        f = self.fixture()
        self.primary_units(f)
        with f.open() as db:
            application = db.head("application_details", "use_lem_thm")
            body = deepcopy(application.body)
            body["needed_form"] = {"form": "verbatim", "text": "the bound also holds at a data-dependent optimizer"}
            f.apply(db, [edit("replace", "application_details", application.id, body, application.version)], *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")
        self.assertFalse(result["progress"]["process_complete"])

    def test_unfounded_cycle_never_gains_support_from_composition_labels(self):
        f = self.fixture()
        with f.open() as db:
            f.apply(db, [edit("create", "uses", "use_cycle", {
                "from": R("items", "itm_thm"), "to": R("items", "itm_lem"), "type": "dependency",
                "group_id": "grp_lem", "needed_form": {"form": "verbatim", "text": "Theorem 1 text"},
                "substitutions": [], "reason": "the lemma depends on the theorem",
                "evidence_refs": ["anc_lem_proof"], "regime": None, "uncertainty": None})], *f.ITEMS, mode="primary")
        self.primary_units(f)
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"], {"items:itm_lem": "conditional", "items:itm_thm": "conditional"})

    def test_joint_premises_are_required_together(self):
        f = self.fixture()
        with f.open() as db:
            premise = f.item_edit("itm_condition", "assumption", "Additional premise", "anc_thm", "anc_thm_proof")
            f.apply(db, [premise, edit("create", "uses", "use_condition", {
                "from": R("items", "itm_condition"), "to": R("items", "itm_thm"), "type": "dependency",
                "group_id": "grp_thm", "needed_form": {"form": "verbatim", "text": "Additional premise text"},
                "substitutions": [], "reason": "both the lemma and this premise are needed",
                "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})], mode="primary")
        self.primary_units(f)
        result = self.result(f)
        self.assertEqual(result["support"]["items:itm_lem"], "available")
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")
        self.assertEqual(result["assessments"]["uses:use_condition"]["local_state"], "green")

    def test_alternative_route_establishes_target_but_preserves_written_gap(self):
        f = self.fixture()
        with f.open() as db:
            alternative = f.argument_edit("arg_alternative", "itm_thm", "grp_alternative", "anc_thm_proof")
            alternative["body"]["origin"] = "reconstruction"
            group = f.group_edit("grp_alternative", "arg_alternative", "itm_thm", "anc_thm_proof")
            f.apply(db, [alternative, group], *f.ITEMS, mode="primary")
        self.primary_units(f, outcomes={"thm": "gap"})
        with f.open() as db:
            f.apply(db, [f.check_edit("chk_alternative", R("arguments", "arg_alternative"), "composition",
                                     evidence=["anc_thm_proof"])], *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_thm"], "available")
        self.assertEqual(result["assessments"]["arguments:arg_thm"]["state"], "red")

    def test_missing_case_remains_unestablished_under_whole_unit_label(self):
        f = self.fixture()
        with f.open() as db:
            group = db.head("groups", "grp_thm")
            body = deepcopy(group.body)
            body.update(kind="cases", case_scope_ids=["scp_case"], discharges=["scp_case"])
            f.apply(db, [edit("create", "scopes", "scp_case", {
                "argument_id": "arg_thm", "parent_id": "scp_plain", "assumptions": [], "binders": [],
                "conditions": ["the second case occurs"], "evidence_refs": ["anc_thm_proof"]}),
                edit("replace", "groups", group.id, body, group.version)], *f.ITEMS, mode="primary")
        self.primary_units(f)
        result = self.result(f)
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")

    def test_application_cannot_leak_a_private_assumption_scope(self):
        f = self.fixture()
        with f.open() as db:
            private = f.item_edit("itm_private", "intermediate_result", "Private conclusion", "anc_thm_proof", "anc_thm_proof")
            private["body"].update(owner_id="itm_thm", scope_id="scp_private")
            group = f.group_edit("grp_private", "arg_thm", "itm_private", "anc_thm_proof")
            group["body"]["scope_id"] = "scp_private"
            f.apply(db, [edit("create", "scopes", "scp_private", {
                "argument_id": "arg_thm", "parent_id": "scp_plain", "assumptions": [], "binders": [],
                "conditions": ["a temporary event holds"], "evidence_refs": ["anc_thm_proof"]}),
                private, group, edit("create", "uses", "use_private", {
                    "from": R("items", "itm_private"), "to": R("items", "itm_thm"), "type": "dependency",
                    "group_id": "grp_thm", "needed_form": {"form": "verbatim", "text": "Private conclusion text"},
                    "substitutions": [], "reason": "reuse the branch conclusion outside its branch",
                    "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})], *f.ITEMS, mode="primary")
        self.primary_units(f)
        result = self.result(f)
        self.assertEqual(result["support"]["items:itm_thm"], "unavailable")

    def test_full_scope_detects_an_unexamined_new_major_result(self):
        f = self.fixture(mode="full")
        self.primary_units(f)
        with f.open() as db:
            f.apply(db, [f.item_edit("itm_new", "theorem", "New theorem", "anc_thm", "anc_thm_proof")],
                    mode="primary")
        result = self.result(f)
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(any(o["target"] == R("items", "itm_new") and o["kind"] == "composition"
                            and o["required"] and not o["satisfied"] for o in result["obligations"]))

    def test_new_false_claim_at_old_anchor_gets_no_blanket_credit(self):
        f = self.fixture()
        self.primary_units(f)
        before = self.result(f)
        with f.open() as db:
            false = f.item_edit("itm_false", "intermediate_result", "False new assertion", "anc_thm_proof", "anc_thm_proof")
            false["body"].update(owner_id="itm_thm", statement={"form": "verbatim", "text": "0 equals 1"})
            f.apply(db, [false, f.group_edit("grp_false", "arg_thm", "itm_false", "anc_thm_proof")], *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertEqual(before["progress"]["required_obligations"], result["progress"]["required_obligations"])
        self.assertEqual(result["support"]["items:itm_false"], "conditional")

    def test_optional_local_derivation_preserves_internal_result_in_failed_proof(self):
        f = self.fixture()
        with f.open() as db:
            local = f.item_edit("itm_local", "intermediate_result", "Valid internal bound", "anc_thm_proof", "anc_thm_proof")
            local["body"]["owner_id"] = "itm_thm"
            group = f.group_edit("grp_local", "arg_thm", "itm_local", "anc_thm_proof")
            f.apply(db, [local, group], *f.ITEMS, mode="primary")
        self.primary_units(f, outcomes={"thm": "gap"})
        with f.open() as db:
            f.apply(db, [f.check_edit("chk_local", R("groups", "grp_local"), "derivation",
                                     evidence=["anc_thm_proof"])], *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_local"], "available")
        self.assertEqual(result["support"]["items:itm_thm"], "unavailable")
        self.assertEqual(result["assessments"]["groups:grp_local"]["state"], "green")

    def test_material_finding_against_written_route_beats_favorable_summary(self):
        f = self.fixture()
        self.primary_units(f)
        with f.open() as db:
            f.apply(db, [edit("create", "findings", "fnd_gap", {
                "audit_id": "aud_1", "target": R("items", "itm_thm"), "category": "proof_gap", "lifecycle": "open",
                "description": "The written conclusion does not follow from the bound.", "evidence_refs": ["anc_thm_proof"],
                "check_refs": [f.pin(db, "checks", "chk_comp_thm")], "affected_uses": [],
                "impact_reason": "This concerns the final composition of the written theorem proof.", "resolution": None})],
                    *f.ITEMS, mode="primary")
        result = self.result(f)
        self.assertEqual(result["support"]["items:itm_thm"], "unavailable")
        self.assertTrue(result["progress"]["process_complete"])

    def test_unresolved_integration_finishes_work_and_retains_disagreement(self):
        f = self.fixture(independent=True)
        self.primary_units(f)
        with f.open() as db:
            ids = {name: f.independent_round(db, f"itm_{name}", f"arg_{name}", f"anc_{name}_proof")[0]
                   for name in ("lem", "thm")}
            edits = [f.reconciliation_edit(db, f"rec_{name}", f"arg_{name}", f"chk_comp_{name}", ids[name])
                     for name in ("lem", "thm")]
            edits[1]["body"].update(decision="unresolved", rationale="The two examinations were integrated; the final implication remains undecided.")
            packet = f.packet(db, *f.ITEMS, mode="reconcile")
            review.reconcile(db, batch=f.batch(edits, packet["packet_id"]))
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"], result["problems"])
        self.assertEqual(result["independent"]["items:itm_thm"], "disputed")
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")

    def test_actual_adverse_independent_response_is_retained_in_completed_disagreement(self):
        f = self.fixture(independent=True)
        self.primary_units(f)
        with f.open() as db:
            lemma_check = f.independent_round(db, "itm_lem", "arg_lem", "anc_lem_proof")[0]
            packet = f.packet(db, "items:itm_thm", mode="independent")
            worker = {"packet_id": packet["packet_id"], "covered_targets": [R("items", "itm_thm")],
                "coverage_note": "The complete theorem proof was examined from source.",
                "exposure_report": {"status": "none_known", "note": ""},
                "judgments": [{"target": {"source_anchor_id": "anc_thm_proof", "description": "the written theorem proof"},
                    "kind": "composition", "state": "complete", "outcome": "gap",
                    "reasoning": "Boundedness does not establish the claimed convergence without the needed monotonicity premise.",
                    "evidence_refs": ["anc_thm_proof"], "conditions": [], "next_action": None,
                    "supersedes": None, "extent": "whole_unit", "omissions": ""}]}
            response = review.submit_review(db, submission={"contract_version": 3, "request_id": f.request_id(),
                "packet_id": packet["packet_id"], "reviewer": "independent", "qualification_id": None,
                "exposure": "source_only", "exposure_note": ""}, response_bytes=json.dumps(worker).encode())
            if response.get("checks"):
                theorem_check = response["checks"][0]["check_id"]
            else:
                mapping_packet = f.packet(db, *f.ITEMS, mode="primary")
                mapped = review.map_response(db, mapping={"contract_version": 3, "request_id": f.request_id(),
                    "packet_id": mapping_packet["packet_id"], "response_id": response["response_id"],
                    "entries": [{"judgment_index": 0, "target": R("arguments", "arg_thm"),
                                 "rationale": "The located theorem proof is this argument."}], "reviewer": "coordinator"})
                theorem_check = mapped["checks"][0]["check_id"]
            rows = [f.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem", lemma_check),
                    f.reconciliation_edit(db, "rec_thm", "arg_thm", "chk_comp_thm", theorem_check)]
            rows[1]["body"].update(decision="unresolved", rationale="Both original examinations were compared; the claimed premise remains disputed.")
            integration_packet = f.packet(db, *f.ITEMS, mode="reconcile")
            review.reconcile(db, batch=f.batch(rows, integration_packet["packet_id"]))
        result = self.result(f)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")
        self.assertEqual(result["judgments"][f"checks:{theorem_check}"]["outcome"], "gap")
        self.assertEqual(result["assessments"]["items:itm_thm"]["label"], "disputed")


if __name__ == "__main__":
    import unittest
    unittest.main()
