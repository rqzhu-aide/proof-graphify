"""Stage boundaries preserve scientific credit and current scope restrictions."""
from unittest.mock import patch

from support import Fixture, R, TempCase, edit, run_cli
from paper_core import assessment, cli, controller, queries, review, stages, work
from paper_core.errors import ConflictError, InvalidRequest


class StageTests(TempCase):
    def replace_audit(self, fixture, db, **changes):
        audit = db.head("audits", fixture.audit_id)
        fixture.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, **changes), audit.version)],
                      *fixture.ITEMS, mode="primary")

    def require_global(self, fixture, db):
        tasks = [dict(task) for task in db.head("audits", fixture.audit_id).body["global_tasks"]]
        tasks[0].update(applicability="required", reason="cross-result examination")
        self.replace_audit(fixture, db, global_tasks=tasks)

    def mismatch(self, fixture, db, target, *, anchor="anc_lem"):
        packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
        body = {"target": target, "result": "needs_attention", "reviewer": "primary-1",
                "note": "The recorded statement differs from the captured statement.", "evidence_refs": [anchor]}
        if target["collection"] == "target_specs":
            body["context_kind"] = "exact_target"
        review.compare(db, batch=fixture.batch([edit("create", "observations", fixture.request_id().replace("req_", "obs_"), body)],
                                               packet["packet_id"]))

    def unfinished(self, fixture, db, name):
        body = fixture.check_edit("chk_draft_" + name, R("groups", "grp_" + name), "derivation",
                                  state="draft", outcome=None, supersedes=fixture.pin(db, "checks", "chk_der_" + name))
        body["body"]["next_action"] = "Examine the remaining proof step."
        fixture.apply(db, [body], *fixture.ITEMS, mode="primary")

    def test_stage_one_never_dispatches_primary_role_globals(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        with fixture.open() as db:
            self.require_global(fixture, db)
            current = stages.stage_status(db, audit_id=fixture.audit_id)
            self.assertTrue(current["stage1"]["ready"])
            self.assertFalse(current["progress"]["process_complete"])
            no_work = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=1)
            self.assertFalse(no_work["prepared"])
            self.assertEqual(no_work["assigned_task_ids"], [])
            global_work = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="global")
            self.assertTrue(global_work["prepared"])
            self.assertEqual(global_work["mode"], "primary")
            packet_tasks = global_work["manifest"]["work"]["tasks"]
            self.assertEqual({row["kind"] for row in packet_tasks}, {"global_consistency"})
            self.assertEqual({row["role"] for row in packet_tasks}, {"primary"})

    def test_mathematical_gap_advances_but_unfinished_work_does_not(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_gap", R("groups", "grp_lem"), "derivation", outcome="gap",
                supersedes=fixture.pin(db, "checks", "chk_der_lem"))], *fixture.ITEMS, mode="primary")
            current = stages.stage_status(db, audit_id=fixture.audit_id)
            self.assertTrue(current["stage1"]["ready"])
            self.assertEqual(current["stage1"]["required_count"], current["stage1"]["completed_count"])
            self.unfinished(fixture, db, "thm")
            unfinished = stages.stage_status(db, audit_id=fixture.audit_id)
            self.assertFalse(unfinished["stage1"]["ready"])
            self.assertGreater(unfinished["stage1"]["remaining_count"], 0)

    def test_latest_item_and_exact_source_mismatches_block_without_rewriting_counts(self):
        for collection, identifier in (("items", "itm_lem"), ("target_specs", "tgt_lem")):
            with self.subTest(collection=collection):
                fixture = self.fixture(collection).complete()
                with fixture.open() as db:
                    self.mismatch(fixture, db, R(collection, identifier))
                    current = stages.stage_status(db, audit_id=fixture.audit_id)
                    self.assertTrue(current["progress"]["process_complete"])
                    self.assertEqual(current["stage1"]["required_count"], current["stage1"]["completed_count"])
                    self.assertFalse(current["representation_settled"])
                    self.assertFalse(current["stage2"]["finalization_ready"])
                    blocker = next(row for row in current["stage1"]["blockers"]
                                   if row["code"] == "source_representation_unsettled")
                    self.assertEqual(blocker["target_ref"], R(collection, identifier))
                    self.assertEqual(blocker["result"], "needs_attention")
                    self.assertEqual(blocker["next_action"]["operation"], "correct_and_compare_source")
                    self.assertNotIn("prepare", blocker["next_action"]["message"])
                    result = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                                                  focus=R("items", "itm_lem"), ready_subset=True)
                    self.assertFalse(result["prepared"])
                    self.assertEqual(result["reason_code"], "STAGE1_NOT_READY")

    def test_qualification_does_not_gate_stage_one(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.replace_audit(fixture, db, qualification_id=None)
            current = stages.stage_status(db, audit_id=fixture.audit_id)
            self.assertTrue(current["stage1"]["ready"])
            prepared = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent")
            self.assertFalse(prepared["prepared"])
            self.assertTrue(any(row["code"] == "qualification_required" for row in prepared["coordinator_actions"]))

    def test_only_explicit_ready_subset_can_review_a_ready_target(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.unfinished(fixture, db, "thm")
            ordinary = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                                             focus=R("items", "itm_lem"))
            self.assertFalse(ordinary["prepared"])
            self.assertEqual(ordinary["reason_code"], "STAGE1_NOT_READY")
            subset = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                                          focus=R("items", "itm_lem"), ready_subset=True)
            self.assertTrue(subset["prepared"])
            self.assertTrue(subset["scope_limited"])
            self.assertGreater(subset["outside_remaining_count"], 0)
            self.assertFalse(subset["stage_status"]["progress"]["process_complete"])
            self.assertEqual(subset["declared_scope"]["target_refs"], fixture.ITEM_REFS)
            with self.assertRaises(InvalidRequest):
                stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="global",
                                     focus=R("items", "itm_lem"), ready_subset=True)

    def test_ready_subset_retains_shared_prerequisite_and_scopes_mismatch(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.mismatch(fixture, db, R("items", "itm_thm"), anchor="anc_thm")
            ready = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                                         focus=R("items", "itm_lem"), ready_subset=True)
            self.assertTrue(ready["prepared"])
            self.mismatch(fixture, db, R("items", "itm_lem"))
            blocked = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                                           focus=R("items", "itm_thm"), ready_subset=True)
            self.assertFalse(blocked["prepared"])
            self.assertTrue(any(row.get("target_ref") == R("items", "itm_lem")
                                for row in blocked["boundary"]["blockers"]))

    def test_ready_subset_does_not_omit_unfinished_supplier_examination(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.unfinished(fixture, db, "lem")
            view = work.derive_work(db, audit_id=fixture.audit_id)
            supplier = next(row for row in view["tasks"] if row["target"] == R("groups", "grp_lem"))
            blocked = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                                           focus=R("items", "itm_thm"), ready_subset=True)
            self.assertFalse(blocked["prepared"])
            self.assertIn(supplier["id"], blocked["boundary"]["remaining_task_ids"])

    def test_assignment_filters_and_provisional_option_cannot_shrink_boundary(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.unfinished(fixture, db, "thm")
            view = work.derive_work(db, audit_id=fixture.audit_id)
            chosen = next(row for row in view["tasks"] if row["role"] == "independent" and row["owner"] == R("items", "itm_lem"))
            excluded = [row["id"] for row in view["tasks"] if row["state"] != "satisfied" and row["owner"] == R("items", "itm_thm")]
            result = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent",
                                          task_ids=[chosen["id"]], exclude_task_ids=excluded, allow_provisional=True)
            self.assertFalse(result["prepared"])
            self.assertEqual(result["reason_code"], "STAGE1_NOT_READY")

    def test_global_preparation_waits_for_local_review(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.require_global(fixture, db)
            result = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="global")
            self.assertFalse(result["prepared"])
            self.assertEqual(result["reason_code"], "LOCAL_REVIEW_NOT_COMPLETE")

    def test_not_required_request_has_direct_explanation_and_no_prerequisite_request(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            view = work.derive_work(db, audit_id=fixture.audit_id)
            task = next(row for row in view["tasks"] if row["kind"] == "global_consistency")
            result = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="global", task_ids=[task["id"]])
            self.assertEqual(result["reason_code"], "TASK_NOT_REQUIRED")
            row = result["task_selection"]["requests"][0]
            self.assertEqual(row["state"], "not_required")
            self.assertEqual(row["remaining_prerequisite_task_ids"], [])
            low_level = work.select_assignment(view, {"task_ids": [task["id"]]})
            self.assertFalse(low_level["prepared"])
            self.assertEqual(low_level["task_selection"]["requests"][0]["state"], "not_required")

    def test_not_required_request_does_not_select_unrelated_pending_local_work(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            view = work.derive_work(db, audit_id=fixture.audit_id)
            task = next(row for row in view["tasks"] if row["kind"] == "global_consistency")
            selected = work.select_assignment(view, {"task_ids": [task["id"]]})
            self.assertFalse(selected["prepared"])
            self.assertEqual(selected["assigned_task_ids"], [])
            self.assertEqual(selected["task_selection"]["requests"][0]["state"], "not_required")

    def test_candidate_allowlist_is_not_requested_seeds_and_never_splits_units(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            view = work.derive_work(db, audit_id=fixture.audit_id)
        self.assertFalse(work.select_assignment(view, {"candidate_task_ids": []})["prepared"])
        primary = {row["id"] for row in view["tasks"] if stages.task_stage(row) == "primary"}
        composition = next(row for row in view["tasks"] if row["target"] == R("arguments", "arg_lem") and row["role"] == "primary")
        selected = work.select_assignment(view, {"task_ids": [composition["id"]], "candidate_task_ids": primary, "max_units": 1})
        self.assertTrue(selected["prepared"])
        self.assertNotIn(composition["id"], selected["assigned_task_ids"])
        self.assertEqual(selected["tasks"][0]["kind"], "source_fidelity")
        group = next(unit for unit in view["units"] if len(unit["obligation_ids"]) > 1)
        allowed_member = group["obligation_ids"][0]
        split = work.select_assignment(view, {"candidate_task_ids": [allowed_member], "allow_provisional": True})
        self.assertFalse(split["prepared"])
        self.assertTrue(any(row["reason"] == "outside_stage_unit" for row in split["deferred"]))

    def test_unknown_analysis_and_triage_do_not_look_ready(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            current = stages.stage_status(db, audit_id=fixture.audit_id, limits={"max_records": 1})
            self.assertIsNone(current["stage1"]["ready"])
            self.assertFalse(current["analysis_complete"])
            self.assertIn("limit", current)
            self.replace_audit(fixture, db, mode="triage", independent_required=False)
            triage = stages.stage_status(db, audit_id=fixture.audit_id)
            self.assertFalse(triage["stage1"]["ready"])
            self.assertFalse(triage["stage2"]["ready_for_local_review"])
            self.assertFalse(triage["progress"]["process_complete"])

    def test_empty_focused_scope_and_no_required_tasks_are_not_completion(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.replace_audit(fixture, db, targets=[], independent_required=False)
            current = stages.stage_status(db, audit_id=fixture.audit_id)
            self.assertEqual(current["stage1"]["required_count"], 0)
            self.assertFalse(current["stage1"]["ready"])
            self.assertFalse(current["progress"]["process_complete"])
            self.assertTrue(any(row["code"] == "empty_scope" for row in current["stage1"]["blockers"]))

    def test_supplied_partial_work_facts_return_unknown_readiness(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            derived, result = assessment.derive_full(db, audit_id=fixture.audit_id)
            full = work.build_work(derived, result, diagnostic_limit=None)
            partial = dict(full, tasks=full["tasks"][:1])
            current = stages.assess_stages(derived, result, partial)
            self.assertIsNone(current["stage1"]["ready"])
            self.assertEqual(current["stage1"]["blockers"][0]["code"], "STAGE_FACTS_INCOMPLETE")

    def test_status_snapshot_and_focus_share_current_derivation_facts(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            revision = db.max_revision()
            self.unfinished(fixture, db, "thm")
            historical = stages.stage_status(db, audit_id=fixture.audit_id, stage=1, revision=revision,
                                             focus=R("items", "itm_lem"))
            current = stages.stage_status(db, audit_id=fixture.audit_id, stage=2, focus=R("items", "itm_lem"))
            self.assertTrue(historical["stage1"]["ready"])
            self.assertFalse(current["stage1"]["ready"])
            self.assertTrue(current["focus_status"]["ready"])
            self.assertEqual(historical["revision"], revision)

    def test_full_facts_survive_diagnostic_truncation_and_pagination(self):
        fixture = self.fixture().audit(mode="full").primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.item_edit(f"itm_extra_{i}", "theorem", f"Extra result {i}", "anc_thm", "anc_thm_proof")
                               for i in range(101)])
            page = work.list_work(db, audit_id=fixture.audit_id, limit=1)
            self.assertEqual(len(page["tasks"]), 1)
            self.assertTrue(page["diagnostics_truncated"])
            current = stages.stage_status(db, audit_id=fixture.audit_id)
            self.assertGreater(current["stage1"]["required_count"], 100)
            self.assertGreater(current["stage1"]["blocker_count"], 100)
            self.assertFalse(current["stage1"]["ready"])
            self.assertTrue(current["stage1"]["blockers_truncated"])
            derived, result = assessment.derive_full(db, audit_id=fixture.audit_id)
            full = work.build_work(derived, result, diagnostic_limit=None)
            summary = stages.assess_stages(derived, result, full)
            self.assertEqual(summary, current)

    def test_one_assessed_revision_and_existing_packet_revision_guard(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            with (patch.object(stages, "derive_full", wraps=stages.derive_full) as derived,
                  patch.object(controller, "derive_work", side_effect=AssertionError("must reuse assessment"))):
                result = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=1, focus=R("items", "itm_lem"))
                self.assertTrue(result["prepared"])
                self.assertEqual(derived.call_count, 1)
            original = controller.prepare_assignment
            def concurrent_edit(*args, **kwargs):
                item = db.head("items", "itm_lem")
                fixture.apply(db, [edit("replace", "items", item.id, dict(item.body, caption="Changed concurrently"), item.version)])
                return original(*args, **kwargs)
            with patch.object(controller, "prepare_assignment", side_effect=concurrent_edit), self.assertRaises(ConflictError):
                stages.prepare_stage(db, audit_id=fixture.audit_id, stage=1, focus=R("items", "itm_lem"))

    def test_cli_subset_size_retry_retains_focus_and_exception(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.unfinished(fixture, db, "thm")
            view = work.derive_work(db, audit_id=fixture.audit_id)
            chosen = next(row["id"] for row in view["tasks"] if row["role"] == "independent" and row["owner"] == R("items", "itm_lem"))
            excluded = next(row["id"] for row in view["tasks"] if row["kind"] == "source_fidelity" and row["target"] == R("items", "itm_lem"))
        result, _ = run_cli("stage2", "prepare", fixture.path, "--audit", fixture.audit_id, "--mode", "independent",
                            "--focus", "items:itm_lem", "--ready-subset", "--task", chosen, "--exclude-task", excluded,
                            "--allow-provisional", "--max-units", "1", "--max-bytes", "1", "--out", self.path("subset-assignment"))
        self.assertFalse(result["prepared"])
        command = result["preparation"]["size_action"]["command"]
        parsed = cli.build_parser().parse_args(command[1:])
        self.assertEqual(parsed.command, "stage2")
        self.assertEqual(parsed.mode, "independent")
        self.assertEqual(parsed.focus, "items:itm_lem")
        self.assertTrue(parsed.ready_subset)
        self.assertTrue(parsed.allow_provisional)
        self.assertEqual(parsed.task, [chosen])
        self.assertEqual(parsed.exclude_task, [excluded])
        self.assertEqual(parsed.max_units, 1)
        retry, _ = run_cli(*command[1:])
        self.assertTrue(retry["prepared"])
        self.assertTrue(retry["scope_limited"])
        self.assertFalse(retry["stage_status"]["progress"]["process_complete"])

    def test_cli_status_and_not_required_diagnostic_keep_canonical_completion(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            self.mismatch(fixture, db, R("items", "itm_lem"))
            view = work.derive_work(db, audit_id=fixture.audit_id)
            optional = next(row["id"] for row in view["tasks"] if row["kind"] == "global_consistency")
        status, _ = run_cli("status", fixture.path, "--audit", fixture.audit_id)
        self.assertTrue(status["process_complete"])
        self.assertFalse(status["stages"]["representation_settled"])
        stage_status, _ = run_cli("stage1", "status", fixture.path, "--audit", fixture.audit_id,
                                 "--focus", "items:itm_lem", "--snapshot", str(status["revision"]))
        self.assertEqual(status["stages"]["stage1"], stage_status["stage1"])
        selected, _ = run_cli("stage2", "prepare", fixture.path, "--audit", fixture.audit_id, "--mode", "global",
                             "--task", optional, "--out", self.path("unused-assignment"))
        self.assertFalse(selected["prepared"])
        self.assertEqual(selected["preparation"]["reason"], "not_required")
        self.assertTrue(selected["preparation"]["process_complete"])

    def test_optional_status_stage_limit_preserves_successful_canonical_assessment(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            derived = assessment.derive_full(db, audit_id=fixture.audit_id)
            limit = assessment.TraversalLimit("relations", 100, "stage prerequisite construction")
            with (patch.object(work, "build_work", side_effect=limit),
                  patch.object(queries, "derive_full", side_effect=AssertionError("reuse the supplied derivation"))):
                current = queries.status(db, audit_id=fixture.audit_id, derived=derived, include_stages=True)
            self.assertTrue(current["process_complete"])
            self.assertEqual(current["progress"], derived[1]["progress"])
            self.assertIsNone(current["stages"]["stage1"]["ready"])
            self.assertFalse(current["stages"]["analysis_complete"])
            self.assertEqual(current["stages"]["revision"], current["revision"])
            self.assertEqual(current["stages"]["limit"]["bound"], "relations")
