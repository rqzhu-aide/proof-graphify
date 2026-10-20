"""Ordinary records and reuse of a derivation examined inside its owner."""
from copy import deepcopy
import json

from support import R, TempCase, edit
from paper_core import assessment, authoring, controller, review, stage1, stage2
from paper_core.work import derive_work
from paper_core.contract import INTERMEDIATE_KINDS
from paper_core.drafts import consolidate_drafts
from paper_core.errors import InvalidRequest


class GroupedRecordTests(TempCase):
    def grouped_fixture(self, name="grouped", grouped=True, private=False, consume=False):
        fixture = self.fixture(name).audit()
        with fixture.open() as db:
            definition = self.record_definition("shared", "equation", owner_id="itm_thm")
            if grouped:
                definition["argument_id"] = "arg_thm"
            if private:
                definition["conditions"] = ["Only in the selected local case."]
            authoring.create_record(db, definition)
            if consume:
                fixture.apply(db, [edit("create", "uses", "use_shared_" + suffix, {
                    "from": R("items", "itm_shared"), "to": R("items", "itm_" + suffix),
                    "type": "dependency", "group_id": "grp_" + suffix, "reason": "Use the shared local result.",
                    "needed_form": {"form": "verbatim", "text": definition["statement"]},
                    "substitutions": [], "evidence_refs": ["anc_" + suffix + "_proof"],
                    "regime": None, "uncertainty": None}) for suffix in ("thm", "lem")])
            packet = fixture.packet(db, mode="primary")
            review.compare(db, batch=fixture.batch([edit("create", "observations", "obs_thm", {
                    "target": R("items", "itm_thm"), "result": "matched", "reviewer": "source examiner",
                    "note": "Synthetic exact source comparison.", "evidence_refs": ["anc_thm"]})], packet["packet_id"]))
        return fixture

    @staticmethod
    def record_definition(key, kind, **extra):
        return dict(key=key, kind=kind, label=key, statement="The selected exact " + key + " statement.",
                    statement_anchors=["anc_lem"], proof_anchors=["anc_thm_proof"] if kind in INTERMEDIATE_KINDS else [],
                    source_matched=True, source_note="Synthetic exact source comparison and selected derivation.", **extra)

    def submit(self, db, fixture, prepared, independent=False, outcome="supported", extent="whole_unit", member=None):
        response = deepcopy(prepared["scaffold"])
        for row in response["judgments" if independent else "results"]:
            row.update(state="complete", outcome=outcome, reasoning="Synthetic located whole proof examination.",
                       extent=extent, omissions="Unexamined final case." if extent == "partial" else "")
        if member:
            target, kind, local_outcome = member
            response["judgments"].append({"target": {"source_anchor_id": "anc_thm_proof", "description": "Distinct local result."},
                "kind": kind, "state": "complete", "outcome": local_outcome,
                "reasoning": "Synthetic separate local concern retained with the whole-unit return.",
                "evidence_refs": ["anc_thm_proof"], "conditions": [], "next_action": None, "supersedes": None,
                **({"extent": "whole_unit", "omissions": ""} if kind == "composition" else {})})
        envelope = deepcopy(prepared["submission_envelope_template"])
        envelope.update(reviewer="independent examiner" if independent else "primary examiner", request_id=fixture.request_id())
        result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                        response_bytes=json.dumps(response).encode())
        self.assertEqual("accepted", result["state"], result)
        if member:
            packet = fixture.packet(db, mode="primary")
            review.map_response(db, mapping={"contract_version": 4, "request_id": fixture.request_id(),
                "packet_id": packet["packet_id"], "response_id": result["response_id"],
                "entries": [{"judgment_index": 1, "target": target, "rationale": "The selected source-local result."}],
                "reviewer": "coordinator"})
        return result

    def examine_owner(self, db, fixture, outcome="supported", extent="whole_unit", member=None):
        focus = R("items", "itm_thm")
        work = derive_work(db, audit_id=fixture.audit_id)
        tasks = {t["role"]: t["id"] for t in work["tasks"]
                 if t["target"] == R("arguments", "arg_thm") and t["kind"] == "composition"}
        primary = stage1.prepare_stage(db, audit_id=fixture.audit_id, task_ids=[tasks["primary"]])
        independent = stage2.prepare(db, audit_id=fixture.audit_id, task_ids=[tasks["independent"]])
        for prepared in (primary, independent):
            self.assertEqual([R("arguments", "arg_thm")], [t["target"] for t in prepared["manifest"]["work"]["tasks"]])
            anchors = {r["ref"]["id"] for r in prepared["packet"]["records"] if r["ref"]["collection"] == "anchors"}
            self.assertTrue({"anc_lem", "anc_thm", "anc_thm_proof"} <= anchors)
            self.assertNotIn("anc_lem_proof", anchors)
        self.submit(db, fixture, primary, outcome=outcome, extent=extent)
        self.submit(db, fixture, independent, independent=True, outcome=outcome, extent=extent, member=member)
        before = {c: len(db.heads(c)) for c in ("checks", "responses")}
        prepared = stage2.prepare(db, audit_id=fixture.audit_id, focus=focus, mode="reconcile")
        if extent == "partial":
            self.assertFalse(prepared["prepared"])
            return assessment.derive_full(db, audit_id=fixture.audit_id)
        for row in prepared["scaffold"]["integrations"]:
            row.update(decision="agree", rationale="Retain the saved examinations and all their limitations.")
        envelope = deepcopy(prepared["submission_envelope_template"])
        envelope.update(reviewer="coordinator", request_id=fixture.request_id())
        result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                        response_bytes=json.dumps(prepared["scaffold"]).encode())
        self.assertEqual("accepted", result["state"], result)
        self.assertEqual(before, {c: len(db.heads(c)) for c in before})
        return assessment.derive_full(db, audit_id=fixture.audit_id)

    def test_grouped_route_after_actual_examination_and_integration(self):
        fixture = self.grouped_fixture(consume=True)
        with fixture.open() as db:
            derivation, result = self.examine_owner(db, fixture)
            self.assertEqual("supported", derivation.local_basis.resolve(R("items", "itm_shared"), "derivation"))
            self.assertEqual("available", result["support"]["items:itm_shared"])
            self.assertEqual("established", result["assessments"]["items:itm_shared"]["label"])
            self.assertEqual("supported", derivation.local_basis.resolve(R("uses", "use_shared_thm"), "application"))
            self.assertEqual("open", derivation.local_basis.resolve(R("uses", "use_shared_lem"), "application"))
            self.assertIsNone(db.head("arguments", "arg_shared"))

    def test_ownership_application_and_delivered_proof_do_not_establish_child(self):
        fixture = self.grouped_fixture(grouped=False, consume=True)
        with fixture.open() as db:
            derivation, result = self.examine_owner(db, fixture)
            self.assertEqual("supported", derivation.local_basis.resolve(R("uses", "use_shared_thm"), "application"))
            self.assertEqual("open", derivation.local_basis.resolve(R("items", "itm_shared"), "derivation"))
            self.assertNotEqual("available", result["support"]["items:itm_shared"])

    def test_private_context_blocks_unconditional_reuse(self):
        fixture = self.grouped_fixture(private=True, consume=True)
        with fixture.open() as db:
            derivation, result = self.examine_owner(db, fixture)
            closure = derivation.support_closure
            self.assertTrue(closure.admissible("scp_shared", "scp_shared"))
            self.assertFalse(closure.admissible("scp_shared", "scp_plain"))
            self.assertEqual("available", result["support"]["items:itm_shared"])
            self.assertNotEqual("available", closure.value(closure.statement_key(R("items", "itm_shared"), "scp_plain")))

    def test_partial_and_adverse_owner_do_not_grant_child_support(self):
        for outcome, extent in (("gap", "whole_unit"), ("inconclusive", "whole_unit"), ("supported", "partial")):
            with self.subTest(outcome=outcome, extent=extent):
                fixture = self.grouped_fixture(name=outcome + extent)
                with fixture.open() as db:
                    derivation, result = self.examine_owner(db, fixture, outcome=outcome, extent=extent)
                    self.assertNotEqual("supported", derivation.local_basis.resolve(R("items", "itm_shared"), "derivation"))
                    self.assertNotEqual("available", result["support"]["items:itm_shared"])

    def test_adverse_independent_local_result_survives_grouped_credit(self):
        for collection, kind in (("items", "composition"), ("groups", "derivation")):
            for outcome in ("gap", "inconclusive"):
                with self.subTest(collection=collection, outcome=outcome):
                    fixture = self.grouped_fixture(name=collection + outcome)
                    with fixture.open() as db:
                        target = R(collection, "itm_shared" if collection == "items" else "grp_shared")
                        derivation, result = self.examine_owner(db, fixture, member=(target, kind, outcome))
                        self.assertNotEqual("supported", derivation.local_basis.resolve(target, kind))
                        self.assertNotEqual("available", result["support"]["items:itm_shared"])
                        self.assertTrue(any(c.body["outcome"] == outcome and c.body["target"] == target
                                            for c in db.heads("checks")))

    def test_ordinary_kinds_replay_and_explicit_separate_route(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            for kind in ("assumption", "definition") + INTERMEDIATE_KINDS:
                definition = self.record_definition(kind, kind, **({"owner_id": "itm_thm"} if kind in INTERMEDIATE_KINDS else {}))
                definition["proof_idea"] = "The source's local explanation for " + kind + "."
                created = authoring.create_record(db, definition)
                version = db.max_revision()
                self.assertTrue(authoring.create_record(db, definition)["reused"])
                self.assertEqual(version, db.max_revision())
                self.assertEqual(kind, db.head("items", created["unit"]["item"]).body["kind"])
                self.assertEqual(definition["proof_idea"], db.head("items", created["unit"]["item"]).body["proof_idea"])
                self.assertIsNone(created["unit"]["argument"])
            self.assertEqual(2, len(db.heads("arguments")))
            self.assertFalse(db.heads("checks"))
            for kind in INTERMEDIATE_KINDS:
                created = authoring.create_record(db, self.record_definition("separate_" + kind, kind,
                    owner_id="itm_thm", separate_examination=True, proof_complete=True,
                    proof_idea="The source derives this result in its separate argument."))
                self.assertIsNotNone(db.head("arguments", created["unit"]["argument"]))
                self.assertEqual("The source derives this result in its separate argument.",
                                 db.head("items", created["unit"]["item"]).body["proof_idea"])
            with self.assertRaises(InvalidRequest):
                authoring.create_record(db, self.record_definition("unowned", "equation"))

    def test_changed_grouped_claim_and_late_association_do_not_reuse_old_credit(self):
        for change in ("claim", "late_group"):
            with self.subTest(change=change):
                fixture = self.grouped_fixture(name=change, grouped=change != "late_group")
                with fixture.open() as db:
                    self.examine_owner(db, fixture)
                    if change == "claim":
                        item = db.head("items", "itm_shared")
                        body = deepcopy(item.body)
                        body["statement"]["text"] += " A materially stronger conclusion."
                        rows = [edit("replace", "items", item.id, body, item.version)]
                    else:
                        rows = [fixture.group_edit("grp_shared", "arg_thm", "itm_shared", "anc_thm_proof")]
                    fixture.apply(db, rows)
                    derivation, result = assessment.derive_full(db, audit_id=fixture.audit_id)
                    self.assertNotEqual("available", result["support"]["items:itm_shared"])
                    if change == "claim":
                        # The old pinned exact question is unchanged until its
                        # direct specification follows the corrected item.
                        spec = db.head("target_specs", "tgt_shared")
                        body = deepcopy(spec.body)
                        body["statement_ref"] = db.head("items", "itm_shared").pinned
                        body["fidelity_ref"] = None
                        fixture.apply(db, [edit("replace", "target_specs", spec.id, body, spec.version)])
                        derivation, result = assessment.derive_full(db, audit_id=fixture.audit_id)
                    self.assertNotEqual("supported", derivation.local_basis.resolve(R("groups", "grp_shared"), "derivation"))
                    self.assertNotEqual("available", result["support"]["items:itm_shared"])

    def test_explicit_local_success_survives_failed_owner_composition(self):
        fixture = self.grouped_fixture()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_local", R("groups", "grp_shared"), "derivation",
                evidence=["anc_thm_proof"])], mode="primary")
            derivation, result = self.examine_owner(db, fixture, outcome="gap",
                member=(R("groups", "grp_shared"), "derivation", "supported"))
            self.assertEqual("available", result["support"]["items:itm_shared"])
            self.assertEqual("defect", derivation.local_basis.resolve(R("arguments", "arg_thm"), "composition"))

    def test_adverse_derivation_remains_local_to_its_route(self):
        fixture = self.grouped_fixture()
        with fixture.open() as db:
            fixture.apply(db, [fixture.group_edit("grp_alternative", "arg_thm", "itm_shared", "anc_thm_proof")])
            derivation, result = self.examine_owner(db, fixture,
                member=(R("groups", "grp_shared"), "derivation", "gap"))
            self.assertEqual("defect", derivation.local_basis.resolve(R("groups", "grp_shared"), "derivation"))
            self.assertEqual("supported", derivation.local_basis.resolve(R("groups", "grp_alternative"), "derivation"))
            self.assertEqual("available", result["support"]["items:itm_shared"])

    def test_ready_draft_order_registers_owner_then_child_then_two_consuming_uses(self):
        fixture = self.fixture().anchors()
        def proposal(local, kind, anchor, proof=None, **extra):
            unit = {"statement_anchors": [anchor], "source_matched": True,
                    "source_note": "Selected exact source and local derivation."}
            if proof:
                unit.update(proof_anchors=[proof], proof_complete=True)
            return dict(local_id=local, kind=kind, label=local, statement="Exact " + local,
                source={"document": "paper.tex", "locator": local}, unit=unit, **extra)
        a = {"namespace": "a", "reviewer": "primary-a", "items": [
            proposal("setup", "assumption", "anc_lem"), proposal("a", "theorem", "anc_thm", "anc_thm_proof"),
            proposal("r", "equation", "anc_lem", "anc_thm_proof", owner="a", derivation_in="a")],
            "connections": [{"from": "setup", "to": "a", "reason": "Named setup."},
                {"from": "r", "to": "a", "reason": "Apply the shared result."}],
            "examinations": [{"target": "a", "outcome": "supported", "reasoning": "Preserved primary reasoning."}]}
        b = deepcopy(a)
        b.update(namespace="b", reviewer="primary-b")
        b["items"][1] = proposal("b", "theorem", "anc_lem", "anc_lem_proof")
        b["items"][2].update(owner={"namespace": "a", "local_id": "a"}, derivation_in={"namespace": "a", "local_id": "a"})
        b["connections"] = [{"from": "r", "to": "b", "reason": "A distinct application."}]
        b["examinations"] = [{"target": "b", "outcome": "gap", "reasoning": "Preserved disagreement."}]
        original = deepcopy([a, b])
        result = consolidate_drafts([a, b])
        self.assertEqual(original, result["source_drafts"])
        self.assertEqual(result["mapping"]["a"]["r"], result["mapping"]["b"]["r"])
        self.assertFalse(result["cyclic_items"])
        with fixture.open() as db:
            selected = []
            for identity in result["authoring_order"]:
                option = next(row for row in result["authoring"] if row["target"]["id"] == identity)
                self.assertTrue(option["authoring_shape_ready"], option["issues"])
                receipt = authoring.create_record(db, option["definition"])
                self.assertEqual(identity, receipt["unit"]["item"])
                selected.extend(option.get("deferred_connections", []))
            fixture.apply(db, selected)
            self.assertEqual(2, len(db.heads("arguments")))
            self.assertEqual(3, len(db.heads("groups")))
            self.assertEqual(2, len(db.heads("uses")))
            self.assertEqual({result["mapping"]["a"]["r"]["id"]}, {u.body["from"]["id"] for u in db.heads("uses")})
            self.assertFalse(db.heads("checks"))
            audit = authoring.create_audit(db)
            work = derive_work(db, audit_id=audit["audit_id"])
            self.assertEqual(2, sum(t["required"] and t["kind"] == "composition" and t["role"] == "primary"
                                    for t in work["tasks"]))
        self.assertEqual([a, b], original)
        private = deepcopy(b)
        private["items"][2]["unit"]["scope_id"] = "scp_private"
        distinct = consolidate_drafts([a, private])
        self.assertNotEqual(distinct["mapping"]["a"]["r"], distinct["mapping"]["b"]["r"])
