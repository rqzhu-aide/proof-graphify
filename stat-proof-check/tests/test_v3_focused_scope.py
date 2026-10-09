"""Focused audits examine necessary internal results without expanding to a paper."""
from copy import deepcopy
import json

from support import R, TempCase, edit
from paper_core import assessment, authoring, controller, stage1


class FocusedScopeTests(TempCase):
    def unit(self, fixture, db, name, suppliers=(), kind="lemma"):
        anchor = "thm" if name == "thm" else "lem"
        return authoring.create_unit(db, {
            "key": name, "kind": kind, "label": name,
            "statement": "The sequence a_n converges." if anchor == "thm" else "For every n, a_n <= 1.",
            "statement_anchors": [f"anc_{anchor}"], "proof_anchors": [f"anc_{anchor}_proof"],
            "source_matched": True, "proof_complete": True,
            "source_note": "Synthetic fixture records the supplied statement and proof boundary.",
            "suppliers": [{"target": R("items", f"itm_{supplier}"), "reason": "Necessary supplied premise.",
                           "needed_form": {"form": "transcription", "text": "For every n, a_n <= 1."}}
                          for supplier in suppliers]})

    def focused(self, db, exclusions=()):
        return authoring.create_audit(db, mode="focused", targets=[R("items", "itm_thm")],
                                     exclusions=exclusions)["audit_id"]

    def compositions(self, db, audit_id):
        result = assessment.derive_assessment(db, audit_id=audit_id)
        return {role: {row["target"]["id"] for row in result["obligations"]
                       if row["required"] and row["kind"] == "composition" and row["role"] == role}
                for role in ("primary", "independent")}

    def test_transitive_internal_results_receive_primary_and_independent_work(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(fixture, db, "base")
            self.unit(fixture, db, "lem", ["base"])
            self.unit(fixture, db, "thm", ["lem"], kind="theorem")
            self.unit(fixture, db, "unrelated", kind="theorem")
            audit_id = self.focused(db)
            expected = {"arg_base", "arg_lem", "arg_thm"}
            self.assertEqual({"primary": expected, "independent": expected}, self.compositions(db, audit_id))
            for role, number in (("primary", 1), ("independent", 2)):
                status = stage1.stage_status(db, audit_id=audit_id, stage=number, mode=role)
                self.assertEqual(expected, {row["target"]["id"] for row in status["tasks"]
                                            if row["required"] and row["kind"] == "composition"})

    def test_context_and_external_results_do_not_receive_proof_examinations(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            for name, kind in (("assumed", "assumption"), ("defined", "definition"), ("external", "external_result")):
                row = fixture.item_edit(f"itm_{name}", kind, name, "anc_lem", "anc_lem_proof")
                fixture.apply(db, [row])
            self.unit(fixture, db, "thm", ["assumed", "defined", "external"], kind="theorem")
            audit_id = self.focused(db)
            self.assertEqual({"primary": {"arg_thm"}, "independent": {"arg_thm"}},
                             self.compositions(db, audit_id))
            result = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertTrue(any(row["kind"] == "external_source" and row["target"] == R("items", "itm_external")
                                for row in result["obligations"]))

    def test_scoped_assumption_does_not_commission_its_proof(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(fixture, db, "lem")
            self.unit(fixture, db, "thm", ["lem"], kind="theorem")
            scope = db.head("scopes", "scp_thm")
            fixture.apply(db, [edit("replace", "scopes", scope.id,
                dict(scope.body, assumptions=[R("items", "itm_lem")]), scope.version)])
            audit_id = self.focused(db)
            self.assertEqual({"primary": {"arg_thm"}, "independent": {"arg_thm"}},
                             self.compositions(db, audit_id))

    def test_borrowed_intermediate_keeps_its_supplier_without_its_parent_theorem(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(fixture, db, "base")
            self.unit(fixture, db, "parent", kind="theorem")
            local = fixture.item_edit("itm_local", "intermediate_result", "Borrowed local bound", "anc_lem", "anc_lem_proof")
            local["body"].update(owner_id="itm_parent", scope_id="scp_parent")
            group = fixture.group_edit("grp_local", "arg_parent", "itm_local", "anc_lem_proof")
            group["body"]["scope_id"] = "scp_parent"
            fixture.apply(db, [local, group, edit("create", "uses", "use_local_base", {
                "from": R("items", "itm_base"), "to": R("items", "itm_local"), "type": "dependency",
                "reason": "The local bound uses this lemma.", "group_id": "grp_local",
                "needed_form": {"form": "transcription", "text": "For every n, a_n <= 1."},
                "substitutions": [], "evidence_refs": ["anc_lem_proof"], "regime": None, "uncertainty": None})])
            self.unit(fixture, db, "thm", ["local"], kind="theorem")
            audit_id = self.focused(db)
            expected = {"arg_base", "arg_thm"}
            self.assertEqual({"primary": expected, "independent": expected}, self.compositions(db, audit_id))

    def test_explicit_exclusion_stops_prerequisite_expansion(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(fixture, db, "base")
            self.unit(fixture, db, "lem", ["base"])
            self.unit(fixture, db, "thm", ["lem"], kind="theorem")
            audit_id = self.focused(db, exclusions=[{"target": R("items", "itm_lem"), "source_anchor_ids": [],
                "reason": "The caller explicitly excluded this lemma.", "consequence": "Its proof is not examined."}])
            self.assertEqual({"primary": {"arg_thm"}, "independent": {"arg_thm"}},
                             self.compositions(db, audit_id))

    def test_exact_theorem_part_gets_its_own_examination_without_parent_expansion(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(fixture, db, "parent", kind="theorem")
            self.unit(fixture, db, "thm", kind="theorem")
            part = R("parts", "par_result")
            route = fixture.argument_edit("arg_result", "unused", "grp_result", "anc_lem_proof")
            route["body"].update(target=part, scope_id="scp_parent")
            group = fixture.group_edit("grp_result", "arg_result", "unused", "anc_lem_proof")
            group["body"].update(conclusion=part, scope_id="scp_parent")
            fixture.apply(db, [edit("create", "parts", part["id"], {
                "item_id": "itm_parent", "label": "Theorem part (i)",
                "statement": {"form": "transcription", "text": "For every n, a_n <= 1."},
                "passages": [{"role": "statement", "anchor_id": "anc_lem"},
                             {"role": "proof", "anchor_id": "anc_lem_proof"}],
                "scope_id": "scp_parent", "origin": "source"}), route, group,
                edit("create", "uses", "use_result_thm", {
                    "from": part, "to": R("items", "itm_thm"), "type": "dependency",
                    "reason": "The theorem invokes this exact subclaim.", "group_id": "grp_thm",
                    "needed_form": {"form": "transcription", "text": "For every n, a_n <= 1."},
                    "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})])
            audit_id = self.focused(db)
            expected = {"arg_result", "arg_thm"}
            self.assertEqual({"primary": expected, "independent": expected}, self.compositions(db, audit_id))

    def test_ungrouped_intermediate_chain_reaches_its_internal_prerequisite(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(fixture, db, "base")
            self.unit(fixture, db, "parent", kind="theorem")
            local = fixture.item_edit("itm_local", "intermediate_result", "Borrowed local bound", "anc_lem", "anc_lem_proof")
            local["body"].update(owner_id="itm_parent", scope_id="scp_parent")
            fixture.apply(db, [local, edit("create", "uses", "use_local_base", {
                "from": R("items", "itm_base"), "to": R("items", "itm_local"), "type": "dependency",
                "reason": "The local bound uses this lemma.", "group_id": None,
                "needed_form": {"form": "transcription", "text": "For every n, a_n <= 1."},
                "substitutions": [], "evidence_refs": ["anc_lem_proof"], "regime": None, "uncertainty": None})])
            self.unit(fixture, db, "thm", ["local"], kind="theorem")
            audit_id = self.focused(db)
            expected = {"arg_base", "arg_thm"}
            self.assertEqual({"primary": expected, "independent": expected}, self.compositions(db, audit_id))

    def test_dependency_cycle_remains_finite_and_does_not_block_examination(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(fixture, db, "lem")
            self.unit(fixture, db, "thm", ["lem"], kind="theorem")
            fixture.apply(db, [edit("create", "uses", "use_cycle", {
                "from": R("items", "itm_thm"), "to": R("items", "itm_lem"), "type": "dependency",
                "reason": "The lemma also invokes the theorem.", "group_id": "grp_lem",
                "needed_form": {"form": "transcription", "text": "The sequence a_n converges."},
                "substitutions": [], "evidence_refs": ["anc_lem_proof"], "regime": None, "uncertainty": None})])
            audit_id = self.focused(db)
            expected = {"arg_lem", "arg_thm"}
            self.assertEqual({"primary": expected, "independent": expected}, self.compositions(db, audit_id))
            examined = set()
            for _ in range(2):
                prepared = stage1.prepare_stage(db, audit_id=audit_id)
                self.assertTrue(prepared["prepared"], prepared)
                again = stage1.prepare_stage(db, audit_id=audit_id)
                self.assertEqual(prepared["packet_id"], again["packet_id"])
                self.assertTrue(again["reused"])
                response = deepcopy(prepared["scaffold"])
                evidence = [row["id"] for row in prepared["manifest"]["read_set"] if row["collection"] == "anchors"]
                for row in response["results"]:
                    row.update(state="complete", outcome="gap", reasoning="The written route relies on an unfounded circular premise.",
                               evidence_refs=evidence)
                envelope = dict(prepared["submission_envelope_template"], request_id=fixture.request_id(), reviewer="primary")
                result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(), response_bytes=json.dumps(response).encode())
                self.assertEqual("accepted", result["state"], result)
                examined.update(task["target"]["id"] for task in prepared["manifest"]["work"]["tasks"])
            self.assertEqual(expected, examined)
            self.assertFalse(stage1.prepare_stage(db, audit_id=audit_id)["prepared"])


if __name__ == "__main__":
    import unittest
    unittest.main()
