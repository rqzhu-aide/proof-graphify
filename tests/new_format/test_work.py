"""User-visible graph scope, coherent assignments and bounded work enumeration."""
from unittest.mock import patch

from support import Fixture, R, TempCase, edit
from paper_core import assessment, validation, work
from paper_core.errors import InvalidRequest


class WorkTests(TempCase):
    def fixture(self, **kwargs):
        return Fixture(self.path("fixture")).audit(independent_required=False, **kwargs)

    def derive(self, fixture, **kwargs):
        with fixture.open() as db:
            return work.derive_work(db, audit_id=fixture.audit_id, **kwargs)

    def task(self, result, collection, identifier, kind, role="primary"):
        return next(t for t in result["tasks"] if t["target"] == R(collection, identifier)
                    and t["kind"] == kind and t["role"] == role)

    def replace(self, fixture, db, collection, identifier, **changes):
        record = db.head(collection, identifier)
        fixture.apply(db, [edit("replace", collection, identifier, dict(record.body, **changes), record.version)],
                      *fixture.ITEMS, mode="primary" if collection == "audits" else "author")

    def intermediate(self, identifier="itm_step"):
        return edit("create", "items", identifier, {
            "kind": "intermediate_result", "label": "Local bound", "caption": "Local bound",
            "statement": {"form": "verbatim", "text": "The local bound holds."},
            "passages": [], "aliases": [], "uncertainty": None, "origin": "reconstruction",
            "owner_id": "itm_thm", "scope_id": "scp_plain"})

    def add_local_step(self, fixture, db):
        fixture.apply(db, [self.intermediate(),
            fixture.group_edit("grp_step", "arg_thm", "itm_step", "anc_thm_proof"),
            edit("create", "uses", "use_step_thm", {
                "from": R("items", "itm_step"), "to": R("items", "itm_thm"), "type": "dependency",
                "group_id": "grp_thm", "reason": "applied as stated", "needed_form": None,
                "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None,
                "uncertainty": None})])

    def test_focused_target_closes_over_actual_supplier(self):
        fixture = self.fixture()
        with fixture.open() as db:
            self.replace(fixture, db, "audits", fixture.audit_id, targets=[R("items", "itm_thm")])
            result = work.derive_work(db, audit_id=fixture.audit_id)
        self.task(result, "arguments", "arg_lem", "composition")
        application = self.task(result, "uses", "use_lem_thm", "application")
        lemma = self.task(result, "arguments", "arg_lem", "composition")
        self.assertIn(lemma["id"], application["waiting_on"])

    def test_full_inventory_growth_cannot_be_hidden_by_old_target_list(self):
        fixture = self.fixture(mode="full")
        with fixture.open() as db:
            fixture.apply(db, [fixture.item_edit("itm_new", "theorem", "New result", "anc_thm", "anc_thm_proof")])
            result = work.derive_work(db, audit_id=fixture.audit_id)
        new = self.task(result, "items", "itm_new", "composition")
        self.assertEqual(new["state"], "needs_coordinator")
        self.assertFalse(result["progress"]["process_complete"])

    def test_parent_is_not_established_by_child_argument(self):
        fixture = self.fixture()
        with fixture.open() as db:
            item = self.intermediate()
            arg = db.head("arguments", "arg_thm")
            group = db.head("groups", "grp_thm")
            use = db.head("uses", "use_lem_thm")
            boundary = db.head("proof_boundaries", "bnd_thm")
            fixture.apply(db, [item,
                edit("replace", "arguments", arg.id, dict(arg.body, target=R("items", "itm_step")), arg.version),
                edit("replace", "groups", group.id, dict(group.body, conclusion=R("items", "itm_step")), group.version),
                edit("replace", "proof_boundaries", boundary.id, dict(boundary.body, target=R("items", "itm_step")), boundary.version),
                edit("replace", "uses", use.id, dict(use.body, to=R("items", "itm_step")), use.version)])
            result = work.derive_work(db, audit_id=fixture.audit_id)
        self.assertEqual(self.task(result, "items", "itm_thm", "composition")["state"], "needs_coordinator")

    def test_local_intermediate_waits_for_its_group_not_parent_composition(self):
        fixture = self.fixture()
        with fixture.open() as db:
            self.add_local_step(fixture, db)
            result = work.derive_work(db, audit_id=fixture.audit_id)
        application = self.task(result, "uses", "use_step_thm", "application")
        group = self.task(result, "groups", "grp_step", "derivation")
        parent = self.task(result, "arguments", "arg_thm", "composition")
        self.assertIn(group["id"], application["prerequisite_ids"])
        self.assertNotIn(parent["id"], application["prerequisite_ids"])
        self.assertFalse(any(a["code"] == "register_establishment" for a in result["coordinator_actions"]))
        self.assertEqual(result["progress"]["major_results"], 2)

    def test_source_fidelity_group_and_composition_share_one_assignment(self):
        fixture = self.fixture()
        result = self.derive(fixture)
        selection = work.select_assignment(result, {"mode": "primary", "focus": R("items", "itm_lem")})
        self.assertEqual(selection["context"]["argument"], R("arguments", "arg_lem"))
        self.assertEqual([task["kind"] for task in selection["tasks"]],
                         ["source_fidelity", "source_fidelity", "derivation", "composition"])
        self.assertEqual(len(selection["units"]), 4)

    def test_group_contracts_application_and_derivation_without_self_wait(self):
        fixture = Fixture(self.path("fixture")).primary()
        with fixture.open() as db:
            self.add_local_step(fixture, db)
            result = work.derive_work(db, audit_id=fixture.audit_id)
        application = self.task(result, "uses", "use_step_thm", "application")
        group = self.task(result, "groups", "grp_thm", "derivation")
        unit = next(u for u in result["units"] if application["id"] in u["obligation_ids"])
        self.assertIn(group["id"], unit["obligation_ids"])
        self.assertNotIn(unit["id"], unit["predecessor_unit_ids"])
        selection = work.select_assignment(result, {"mode": "primary", "focus": R("items", "itm_thm")})
        self.assertIn(self.task(result, "groups", "grp_step", "derivation")["id"], selection["assigned_task_ids"])
        self.assertIn(application["id"], selection["assigned_task_ids"])
        self.assertIn(self.task(result, "arguments", "arg_thm", "composition")["id"], selection["assigned_task_ids"])

    def test_completed_negative_supplier_is_examined_but_support_remains_qualified(self):
        fixture = Fixture(self.path("fixture")).primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_gap", R("groups", "grp_lem"), "derivation",
                outcome="gap", supersedes=fixture.pin(db, "checks", "chk_der_lem"))], *fixture.ITEMS, mode="primary")
            result = work.derive_work(db, audit_id=fixture.audit_id)
        lower = self.task(result, "groups", "grp_lem", "derivation")
        higher = self.task(result, "uses", "use_lem_thm", "application")
        self.assertEqual(lower["state"], "satisfied")
        self.assertEqual(lower["outcome"], "gap")
        self.assertNotEqual(higher["dependency_support"], "available")

    def test_no_inputs_still_requires_derivation_and_composition(self):
        fixture = self.fixture()
        result = self.derive(fixture, focus=R("items", "itm_lem"))
        self.task(result, "groups", "grp_lem", "derivation")
        self.task(result, "arguments", "arg_lem", "composition")
        self.assertFalse(result["progress"]["process_complete"])

    def test_actual_task_cycle_remains_visible_after_contraction(self):
        fixture = self.fixture()
        with fixture.open() as db:
            self.add_local_step(fixture, db)
            fixture.apply(db, [edit("create", "uses", "use_cycle", {
                "from": R("items", "itm_thm"), "to": R("items", "itm_step"), "type": "dependency",
                "group_id": "grp_step", "reason": "recorded self dependency", "needed_form": None,
                "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})])
            result = work.derive_work(db, audit_id=fixture.audit_id)
        cycle = self.task(result, "uses", "use_cycle", "application")
        unit = next(u for u in result["units"] if cycle["id"] in u["obligation_ids"])
        self.assertTrue(unit["cyclic"])
        self.assertEqual(unit["state"], "waiting")
        self.assertTrue(any(a["code"] == "ordering_cycle" for a in result["coordinator_actions"]))
        regular = work.select_assignment(result, {"task_ids": [cycle["id"]]})
        self.assertNotIn(cycle["id"], regular["assigned_task_ids"])
        provisional = work.select_assignment(result, {"task_ids": [cycle["id"]], "allow_provisional": True})
        self.assertIn(cycle["id"], provisional["assigned_task_ids"])
        self.assertTrue(provisional["conditional_on_task_ids"])

    def test_already_assigned_group_member_defers_whole_group_and_dependents(self):
        fixture = self.fixture()
        result = self.derive(fixture)
        group = self.task(result, "groups", "grp_lem", "derivation")
        composition = self.task(result, "arguments", "arg_lem", "composition")
        selection = work.select_assignment(result, {"focus": R("items", "itm_lem"),
                                                    "exclude_task_ids": [group["id"]]})
        self.assertNotIn(group["id"], selection["assigned_task_ids"])
        self.assertNotIn(composition["id"], selection["assigned_task_ids"])
        self.assertTrue(any(d["reason"] == "already_assigned" for d in selection["deferred"]))

    def test_independent_review_does_not_wait_for_primary_checks(self):
        fixture = Fixture(self.path("fixture")).audit()
        result = self.derive(fixture)
        task = self.task(result, "arguments", "arg_lem", "composition", "independent")
        self.assertEqual(task["state"], "ready")
        self.assertEqual(task["prerequisite_ids"], [])
        selected = work.select_assignment(result, {"mode": "independent", "task_ids": [task["id"]]})
        self.assertEqual(selected["assigned_task_ids"], [task["id"]])

    def test_scoped_assumption_stops_only_that_uses_establishment(self):
        fixture = self.fixture()
        with fixture.open() as db:
            scope = edit("create", "scopes", "scp_local", {"argument_id": "arg_thm", "parent_id": "scp_plain",
                "assumptions": [R("items", "itm_lem")], "binders": [], "conditions": [], "evidence_refs": []})
            group = db.head("groups", "grp_thm")
            fixture.apply(db, [scope, edit("replace", "groups", group.id,
                dict(group.body, scope_id="scp_local"), group.version)])
            self.replace(fixture, db, "audits", fixture.audit_id, targets=[R("items", "itm_thm")])
            result = work.derive_work(db, audit_id=fixture.audit_id)
            status = assessment.derive_assessment(db, audit_id=fixture.audit_id)
        application = self.task(result, "uses", "use_lem_thm", "application")
        self.assertFalse(any(t["target"] == R("arguments", "arg_lem") for t in result["tasks"]))
        self.assertTrue(all(next(t for t in result["tasks"] if t["id"] == p)["kind"] == "source_fidelity"
                            for p in application["prerequisite_ids"]))
        self.assertFalse(any("anc_lem_proof" in message for message in status["problems"]),
                         "An explicitly assumed statement must not secretly require its proof coverage.")

    def test_record_and_relation_caps_return_no_partial_graph(self):
        fixture = self.fixture()
        for limits in ({"max_records": 1}, {"max_relations": 1}):
            with self.subTest(limits=limits):
                result = self.derive(fixture, limits=limits)
                self.assertFalse(result["analysis_complete"])
                self.assertFalse(result["progress"]["process_complete"])
                self.assertEqual(result["tasks"], [])
                self.assertEqual(result["units"], [])
                self.assertFalse(work.select_assignment(result, {})["prepared"])

    def test_page_cursor_pins_snapshot_across_concurrent_edits(self):
        fixture = self.fixture()
        with fixture.open() as db:
            first = work.list_work(db, audit_id=fixture.audit_id, limit=2)
            self.replace(fixture, db, "items", "itm_lem", caption="Cosmetic edit")
            second = work.list_work(db, audit_id=fixture.audit_id, limit=2, cursor=first["next_cursor"])
            self.assertEqual(first["revision"], second["revision"])
            self.assertFalse({t["id"] for t in first["tasks"]} & {t["id"] for t in second["tasks"]})
            with self.assertRaises(InvalidRequest):
                work.list_work(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"),
                               cursor=first["next_cursor"])

    def test_full_inventory_over_one_hundred_tasks_and_fresh_listing_after_write(self):
        fixture = self.fixture(mode="full")
        with fixture.open() as db:
            fixture.apply(db, [fixture.item_edit(f"itm_extra_{i}", "theorem", f"Extra result {i}",
                                                "anc_thm", "anc_thm_proof") for i in range(101)])
            expected = work.derive_work(db, audit_id=fixture.audit_id)
            self.assertGreater(len(expected["tasks"]), 100)
            first = work.list_work(db, audit_id=fixture.audit_id, limit=100)
            self.assertEqual(100, len(first["tasks"]))
            self.assertIsNotNone(first["next_cursor"])

            fixture.apply(db, [fixture.item_edit("itm_added_later", "theorem", "Later result",
                                                "anc_thm", "anc_thm_proof")])
            rows = list(first["tasks"])
            cursor = first["next_cursor"]
            while cursor is not None:
                page = work.list_work(db, audit_id=fixture.audit_id, limit=100, cursor=cursor)
                self.assertEqual(first["revision"], page["revision"])
                rows.extend(page["tasks"])
                cursor = page["next_cursor"]
            self.assertEqual([task["id"] for task in expected["tasks"]], [task["id"] for task in rows])
            self.assertFalse(any(task["target"] == R("items", "itm_added_later") for task in rows))

            fresh = work.list_work(db, audit_id=fixture.audit_id, focus=R("items", "itm_added_later"))
            self.assertGreater(fresh["revision"], first["revision"])
            remaining = self.task(fresh, "items", "itm_added_later", "composition")
            self.assertEqual("needs_coordinator", remaining["state"])
            self.assertFalse(fresh["progress"]["process_complete"])

    def test_assignment_limits_are_units_not_record_count(self):
        fixture = self.fixture()
        result = self.derive(fixture)
        one = work.select_assignment(result, {"max_units": 1})
        self.assertEqual(len(one["units"]), 1)
        for cap in (0, 11, True):
            with self.subTest(cap=cap), self.assertRaises(InvalidRequest):
                work.select_assignment(result, {"max_units": cap})

    def test_unknown_tasks_are_not_silently_ignored(self):
        fixture = self.fixture()
        with self.assertRaises(InvalidRequest):
            work.select_assignment(self.derive(fixture), {"task_ids": ["obl_nonexistent"]})

    def test_status_uses_same_effective_scope_and_completion(self):
        fixture = self.fixture()
        with fixture.open() as db:
            self.replace(fixture, db, "audits", fixture.audit_id, targets=[R("items", "itm_thm")])
            status = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            result = work.derive_work(db, audit_id=fixture.audit_id)
        self.assertEqual(result["progress"], status["progress"])
        self.assertEqual({t["id"] for t in result["tasks"]}, {o["id"] for o in status["obligations"]})

    def test_satisfied_tasks_are_not_reassigned(self):
        fixture = Fixture(self.path("fixture")).primary()
        result = self.derive(fixture)
        selection = work.select_assignment(result, {"mode": "primary"})
        self.assertFalse(selection["prepared"])
        self.assertEqual(selection["assigned_task_ids"], [])

    def test_partial_group_save_retains_context_without_reassigning_completed_member(self):
        fixture = self.fixture()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_only_app", R("uses", "use_lem_thm"), "application")],
                          *fixture.ITEMS, mode="primary")
            result = work.derive_work(db, audit_id=fixture.audit_id)
        app = self.task(result, "uses", "use_lem_thm", "application")
        derivation = self.task(result, "groups", "grp_thm", "derivation")
        unit = next(unit for unit in result["units"] if app["id"] in unit["obligation_ids"])
        self.assertNotIn(app["id"], unit["pending_obligation_ids"])
        self.assertIn(derivation["id"], unit["pending_obligation_ids"])
        chosen = work.select_assignment(result, {"task_ids": [derivation["id"]], "allow_provisional": True})
        self.assertIn(derivation["id"], chosen["assigned_task_ids"])
        self.assertNotIn(app["id"], chosen["assigned_task_ids"])
        selected = next(t for t in chosen["tasks"] if t["id"] == derivation["id"])
        self.assertEqual(selected["prerequisite_judgment_refs"], app["judgment_refs"])

    def test_saved_draft_retains_its_next_action_and_is_not_completion(self):
        fixture = self.fixture()
        with fixture.open() as db:
            draft = fixture.check_edit("chk_draft", R("groups", "grp_lem"), "derivation",
                                       state="draft", outcome=None)
            draft["body"]["next_action"] = "Examine the induction step at n+1."
            fixture.apply(db, [draft], *fixture.ITEMS, mode="primary")
            result = work.derive_work(db, audit_id=fixture.audit_id)
        task = self.task(result, "groups", "grp_lem", "derivation")
        self.assertEqual(task["draft_refs"], [{"collection": "checks", "id": "chk_draft", "version": 1}])
        self.assertEqual(task["next_action"], draft["body"]["next_action"])
        self.assertNotEqual(task["state"], "satisfied")

    def test_many_applications_are_one_unit_not_many_model_assignments(self):
        fixture = Fixture(self.path("fixture")).primary()
        with fixture.open() as db:
            edits = []
            for number in range(12):
                premise = f"itm_premise_{number}"
                body = self.intermediate(premise)["body"]
                body.update(kind="assumption", owner_id=None)
                edits.append(edit("create", "items", premise, body))
                edits.append(edit("create", "uses", f"use_premise_{number}", {
                    "from": R("items", premise), "to": R("items", "itm_thm"), "type": "dependency",
                    "group_id": "grp_thm", "reason": "joint premise", "needed_form": None,
                    "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None}))
            with patch.object(validation, "extract_refs", wraps=validation.extract_refs) as extracted:
                fixture.apply(db, edits)
                # Count structural work instead of asserting a machine-specific
                # time limit. Reference extraction must not rescan the whole
                # submitted batch for each changed endpoint.
                self.assertLess(extracted.call_count, 10 * len(edits))
            result = work.derive_work(db, audit_id=fixture.audit_id)
        chosen = work.select_assignment(result, {"focus": R("items", "itm_thm"), "max_units": 5})
        self.assertGreater(len(chosen["tasks"]), 10)
        self.assertLessEqual(len(chosen["units"]), 5)
        self.assertEqual(len([unit for unit in chosen["units"] if unit["kind"] == "group"]), 1)

    def test_missing_establishment_cannot_be_bypassed_by_provisional_composition(self):
        fixture = self.fixture()
        with fixture.open() as db:
            fixture.apply(db, [self.intermediate(), edit("create", "uses", "use_missing", {
                "from": R("items", "itm_step"), "to": R("items", "itm_thm"), "type": "dependency",
                "group_id": "grp_thm", "reason": "not established", "needed_form": None,
                "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})])
            result = work.derive_work(db, audit_id=fixture.audit_id)
        composition = self.task(result, "arguments", "arg_thm", "composition")
        self.assertEqual(composition["state"], "needs_coordinator")
        selected = work.select_assignment(result, {"task_ids": [composition["id"]], "allow_provisional": True})
        self.assertNotIn(composition["id"], selected["assigned_task_ids"])

    def test_long_chain_analysis_is_iterative_and_grows_one_local_assignment(self):
        fixture = self.fixture()
        with fixture.open() as db:
            edits = []
            for number in range(1050):
                iid, gid = f"itm_step_{number}", f"grp_step_{number}"
                edits.extend([self.intermediate(iid), fixture.group_edit(gid, "arg_thm", iid, "anc_thm_proof")])
                if number:
                    edits.append(edit("create", "uses", f"use_chain_{number}", {
                        "from": R("items", f"itm_step_{number-1}"), "to": R("items", iid), "type": "dependency",
                        "group_id": gid, "reason": "previous local result", "needed_form": None,
                        "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None}))
            fixture.apply(db, edits)
            result = work.derive_work(db, audit_id=fixture.audit_id)
        self.assertTrue(result["analysis_complete"])
        self.assertFalse(any(a["code"] == "ordering_cycle" for a in result["coordinator_actions"]))
        selected = work.select_assignment(result, {"focus": R("arguments", "arg_thm"), "max_units": 5})
        self.assertEqual(len(selected["units"]), 5)
