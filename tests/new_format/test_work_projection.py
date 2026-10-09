"""The version-2 worklist navigates existing reader obligations, never adds graph nodes."""
from support import Fixture, R, TempCase, edit
from paper_core import projection, work


class WorkProjectionTests(TempCase):
    def test_every_required_work_row_opens_its_exact_owner_obligation(self):
        fixture = Fixture(self.path("fixture")).audit()
        with fixture.open() as db:
            view = projection.build_projection(db, audit_id=fixture.audit_id)
            derived = work.derive_work(db, audit_id=fixture.audit_id)
        self.assertEqual(view["projection_version"], 2)
        self.assertEqual(view["worklist"]["revision"], view["snapshot_revision"])
        self.assertEqual({task["id"] for task in view["worklist"]["tasks"]},
                         {task["id"] for task in derived["tasks"]})
        for task in view["worklist"]["tasks"]:
            if not task["required"]:
                continue
            with self.subTest(kind=task["kind"], role=task["role"]):
                location = task["location"]
                self.assertIsNotNone(location)
                self.assertEqual(location["obligation_id"], task["id"])
                self.assertEqual(location["detail_key"], "item:" + task["owner"]["id"])
                section = next(s for s in view["details"][location["detail_key"]]["sections"]
                               if s["key"] == location["section_key"])
                self.assertIn(task["id"], section["obligation_ids"])
                if task["kind"] == "source_fidelity":
                    self.assertEqual(location["section_key"], "sources")
                if task["role"] in ("independent", "coordinator"):
                    self.assertEqual(location["section_key"], "review")

    def test_hidden_group_work_keeps_only_major_graph_nodes(self):
        fixture = Fixture(self.path("fixture")).audit()
        with fixture.open() as db:
            body = dict(db.head("items", "itm_thm").body, kind="intermediate_result",
                        label="Hidden bound", caption="Hidden bound", owner_id="itm_thm")
            fixture.apply(db, [edit("create", "items", "itm_hidden", body),
                fixture.group_edit("grp_hidden", "arg_thm", "itm_hidden", "anc_thm_proof")])
            view = projection.build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual({node["id"] for node in view["nodes"]}, {"itm_lem", "itm_thm"})
        row = next(t for t in view["worklist"]["tasks"] if t["target"] == R("groups", "grp_hidden"))
        self.assertIn("Hidden bound", row["label"])
        self.assertEqual(row["location"]["detail_key"], "item:itm_thm")
        self.assertEqual(row["location"]["section_key"], "derivations")

    def test_required_global_work_has_a_reader_location_without_a_graph_node(self):
        fixture = Fixture(self.path("fixture")).audit(independent_required=False)
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            globals = [dict(task, applicability="required", reason="Check notation across the paper")
                       if task["kind"] == "global_consistency" else task for task in audit.body["global_tasks"]]
            fixture.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, global_tasks=globals), audit.version)],
                          *fixture.ITEMS, mode="primary")
            view = projection.build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual({node["id"] for node in view["nodes"]}, {"itm_lem", "itm_thm"})
        task = next(t for t in view["worklist"]["tasks"] if t["kind"] == "global_consistency")
        self.assertEqual(task["location"]["detail_key"], "audit:aud_1")
        self.assertEqual(task["location"]["obligation_id"], task["id"])

    def test_negative_upstream_is_not_a_duplicate_downstream_defect(self):
        fixture = Fixture(self.path("fixture")).primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_gap", R("groups", "grp_lem"), "derivation",
                outcome="gap", supersedes=fixture.pin(db, "checks", "chk_der_lem"))], *fixture.ITEMS, mode="primary")
            view = projection.build_projection(db, audit_id=fixture.audit_id)
        row = next(t for t in view["worklist"]["tasks"] if t["target"] == R("uses", "use_lem_thm"))
        self.assertEqual(row["outcome"], "supported")
        self.assertNotEqual(row["dependency_support"], "available")
        self.assertEqual(row["state"], "satisfied")

    def test_overview_and_complete_audit_have_honest_worklist_states(self):
        fixture = Fixture(self.path("fixture")).complete()
        with fixture.open() as db:
            overview = projection.build_projection(db)
            audited = projection.build_projection(db, audit_id=fixture.audit_id)
        self.assertIsNone(overview["worklist"])
        self.assertTrue(audited["worklist"]["analysis_complete"])
        self.assertTrue(all(t["state"] == "satisfied" for t in audited["worklist"]["tasks"] if t["required"]))
        self.assertTrue(audited["summary"]["progress"]["process_complete"])
