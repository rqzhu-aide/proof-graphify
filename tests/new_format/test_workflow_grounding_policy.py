"""Written-route grounding and compatibility preparation share real prerequisites."""
from __future__ import annotations

import copy
from unittest import mock

from support import R, TempCase, edit, locator
from paper_core import assessment, controller, review, sources, stages, work
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest
from paper_core.semantics import anchors_overlap, target_source_resolution


class WorkflowGroundingTests(TempCase):
    def ungrounded(self, name, collection, identity, *, origin=None):
        fx = self.fixture(name).structure()
        with fx.open() as db:
            record = db.head(collection, identity)
            body = dict(record.body, evidence_refs=[])
            if origin is not None:
                body["origin"] = origin
            fx.apply(db, [edit("replace", collection, identity, body, record.version)], *fx.ITEMS)
        return fx.primary()

    def test_current_primary_examinations_do_not_replace_missing_record_grounding(self):
        for collection, identity in (("uses", "use_lem_thm"), ("groups", "grp_lem"),
                                     ("arguments", "arg_lem")):
            with self.subTest(target=identity):
                fx = self.ungrounded(identity, collection, identity)
                with fx.open() as db:
                    status = stages.stage_status(db, audit_id=fx.audit_id)
                    self.assertEqual(0, status["stage1"]["remaining_count"])
                    self.assertFalse(status["stage1"]["ready"])
                    blocker = next(row for row in status["stage1"]["blockers"]
                                   if row["code"] == "source_grounding_required")
                    self.assertEqual(R(collection, identity), blocker["target_ref"])
                    self.assertEqual("ground_source_record", blocker["next_action"]["operation"])
                    prepared = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="independent")
                    self.assertFalse(prepared["prepared"])
                    self.assertEqual("STAGE1_NOT_READY", prepared["reason_code"])

    def test_valid_current_source_links_settle_the_grounding_boundary(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            status = stages.stage_status(db, audit_id=fx.audit_id)
            self.assertTrue(status["stage1"]["source_grounding_settled"])
            self.assertTrue(status["stage1"]["ready"])
            prepared = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="independent")
            self.assertTrue(prepared["prepared"], prepared)

    def test_ready_subset_includes_real_supplier_grounding(self):
        fx = self.ungrounded("supplier", "groups", "grp_lem")
        with fx.open() as db:
            result = stages.prepare_stage(db, audit_id=fx.audit_id, stage=2, mode="independent",
                                          focus=R("items", "itm_thm"), ready_subset=True)
            self.assertFalse(result["prepared"])
            self.assertTrue(any(row.get("target_ref") == R("groups", "grp_lem")
                                and row["code"] == "source_grounding_required"
                                for row in result["boundary"]["blockers"]))

    def test_ready_subset_does_not_require_unrelated_route_grounding(self):
        fx = self.ungrounded("unrelated", "groups", "grp_thm")
        with fx.open() as db:
            ordinary = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="independent",
                                                   focus=R("items", "itm_lem"))
            self.assertFalse(ordinary["prepared"])
            result = stages.prepare_stage(db, audit_id=fx.audit_id, stage=2, mode="independent",
                                          focus=R("items", "itm_lem"), ready_subset=True)
            self.assertTrue(result["prepared"], result)
            self.assertTrue(result["boundary"]["source_grounding_settled"])

    def test_required_reconstructed_route_needs_no_fictional_manuscript_passage(self):
        fx = self.fixture().structure()
        with fx.open() as db:
            route = fx.argument_edit("arg_rebuilt", "itm_lem", "grp_rebuilt", "anc_lem_proof")
            route["body"].update(origin="reconstruction", evidence_refs=[])
            group = fx.group_edit("grp_rebuilt", "arg_rebuilt", "itm_lem", "anc_lem_proof")
            group["body"]["evidence_refs"] = []
            fx.apply(db, [route, group], *fx.ITEMS)
        fx.primary()
        with fx.open() as db:
            fx.apply(db, [fx.check_edit("chk_rebuilt_derivation", R("groups", "grp_rebuilt"), "derivation"),
                          fx.check_edit("chk_rebuilt_composition", R("arguments", "arg_rebuilt"), "composition")],
                     *fx.ITEMS, mode="primary")
            status = stages.stage_status(db, audit_id=fx.audit_id)
            self.assertTrue(status["stage1"]["ready"], status)
            self.assertFalse(any(row.get("target_ref") in (R("arguments", "arg_rebuilt"), R("groups", "grp_rebuilt"))
                                 for row in status["stage1"]["blockers"]))
            fx.independent_round(db, "itm_lem", "arg_lem", "anc_lem_proof")
            supplied = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", route_id="arg_rebuilt")
            self.assertTrue(supplied["prepared"], supplied)
            self.assertEqual("route_provided", supplied["review_basis"])
            # The written route still has its own source association requirement.
            written = db.head("groups", "grp_lem")
            fx.apply(db, [edit("replace", "groups", written.id, dict(written.body, evidence_refs=[]), written.version)],
                     *fx.ITEMS)
            status = stages.stage_status(db, audit_id=fx.audit_id)
            self.assertFalse(status["stage1"]["source_grounding_settled"])
            self.assertTrue(any(row.get("target_ref") == written.ref and row["code"] == "source_grounding_required"
                                for row in status["stage1"]["blockers"]))
            supplied_again = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", route_id="arg_rebuilt")
            self.assertTrue(supplied_again["prepared"], supplied_again)

    def test_optional_draft_route_is_not_a_new_grounding_requirement(self):
        fx = self.fixture().structure()
        with fx.open() as db:
            route = fx.argument_edit("arg_optional", "itm_lem", "grp_optional", "anc_lem_proof")
            route["body"].update(lifecycle="draft", evidence_refs=[])
            group = fx.group_edit("grp_optional", "arg_optional", "itm_lem", "anc_lem_proof")
            group["body"]["evidence_refs"] = []
            fx.apply(db, [route, group], *fx.ITEMS)
        fx.primary()
        with fx.open() as db:
            status = stages.stage_status(db, audit_id=fx.audit_id)
            self.assertTrue(status["stage1"]["ready"], status)

    def shared_page_fixture(self):
        """A broad captured excerpt contains both proofs; only lemma text is selected."""
        fx = self.fixture().audit()
        with fx.open() as db:
            packet = fx.packet(db)
            sources.anchor_sources(db, request={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": packet["packet_id"], "anchors": [{"id": "anc_shared", "expected_version": None,
                    "source_id": fx.source_id, "locator": locator(start=1, end=17)}]})
            item, argument = (db.head(collection, identity) for collection, identity in
                              (("items", "itm_lem"), ("arguments", "arg_lem")))
            fx.apply(db, [edit("replace", "items", item.id, dict(item.body, passages=[
                dict(passage, anchor_id="anc_shared") if passage["role"] == "proof" else passage
                for passage in item.body["passages"]]), item.version),
                edit("replace", "arguments", argument.id, dict(argument.body, evidence_refs=["anc_shared"]), argument.version)], *fx.ITEMS)
            text = db.head("anchors", "anc_shared").body["excerpt"]
            start = text.index(r"\begin{proof}")
            end = text.index(r"\end{proof}") + len(r"\end{proof}")
            packet = fx.packet(db)
            sources.review_sources(db, batch=fx.batch([edit("create", "source_reviews", "srv_shared", {
                "source_refs": [fx.pin(db, "sources", fx.source_id)],
                "anchor_refs": [fx.pin(db, "anchors", "anc_shared")], "purpose": "proof_boundary",
                "decision": "accepted", "rationale": "The complete lemma proof is the selected text in this broad capture.",
                "reviewer": "fixture", "proof_spans": [{"argument_ref": fx.pin(db, "arguments", "arg_lem"),
                    "anchor_ref": fx.pin(db, "anchors", "anc_shared"), "start_offset": start, "end_offset": end}]})],
                packet["packet_id"]))
            boundary = db.head("proof_boundaries", "bnd_lem")
            fx.apply(db, [edit("replace", "proof_boundaries", boundary.id, dict(boundary.body,
                anchor_refs=[fx.pin(db, "anchors", "anc_shared")],
                source_review_ref=fx.pin(db, "source_reviews", "srv_shared")), boundary.version)], *fx.ITEMS)
            coverage = fx.coverage_edits(db)
            coverage[0]["body"].update(anchor_id="anc_shared", start_offset=start, end_offset=end)
        with mock.patch.object(fx, "coverage_edits", return_value=coverage):
            fx.primary()
        return fx

    def test_written_argument_uses_its_own_certified_selection(self):
        fx = self.shared_page_fixture()
        with fx.open() as db:
            status = stages.stage_status(db, audit_id=fx.audit_id)
            self.assertEqual(0, status["stage1"]["remaining_count"])
            self.assertTrue(status["stage1"]["ready"], status)
            self.assertTrue(status["stage1"]["source_grounding_settled"])

    def test_source_backed_support_elsewhere_is_ready_and_maps_unchanged(self):
        fx = self.fixture()
        source_path = fx.source_root / "paper.tex"
        original = source_path.read_text(encoding="utf-8")
        support = "Auxiliary convergence calculation: Lemma 1 bounds the sequence; monotonicity gives convergence."
        source_path.write_text(original.replace(r"\end{document}", support + "\n" + r"\end{document}"), encoding="utf-8")
        fx.structure()
        with fx.open() as db:
            packet = fx.packet(db)
            sources.anchor_sources(db, request={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": packet["packet_id"], "anchors": [{"id": "anc_auxiliary", "expected_version": None,
                    "source_id": fx.source_id, "locator": locator(start=17, end=17)}]})
            group, use = db.head("groups", "grp_thm"), db.head("uses", "use_lem_thm")
            fx.apply(db, [edit("replace", "groups", group.id, dict(group.body, evidence_refs=["anc_auxiliary"],
                rationale="The auxiliary calculation supplies the convergence inference summarized in the main proof."), group.version),
                edit("replace", "uses", use.id, dict(use.body, evidence_refs=["anc_auxiliary"]), use.version)], *fx.ITEMS)
        fx.primary()
        with fx.open() as db:
            self.assertFalse(anchors_overlap(db.head("anchors", "anc_auxiliary").body,
                                             db.head("anchors", "anc_thm_proof").body))
            status = stages.stage_status(db, audit_id=fx.audit_id)
            self.assertTrue(status["stage1"]["ready"], status)
            prepared = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="independent",
                                                    focus=R("items", "itm_thm"))
            self.assertTrue(prepared["prepared"], prepared)
            # Include the auxiliary neutral source before the reviewer authors
            # the judgment. Mapping cannot supply unseen evidence afterward.
            neutral = controller.extend_work(db, packet_id=prepared["packet_id"], request={
                "source_refs": [fx.pin(db, "anchors", "anc_auxiliary")],
                "reason": "Read the manuscript's auxiliary convergence calculation before examining its inference."})
            worker = {"packet_id": neutral["packet_id"], "covered_targets": [R("items", "itm_thm")],
                "coverage_note": "Read the theorem and its source-backed auxiliary convergence calculation.",
                "exposure_report": {"status": "none_known", "note": ""}, "judgments": [
                    {"target": {"source_anchor_id": "anc_auxiliary", "description": "The auxiliary convergence inference"},
                     "kind": "derivation", "state": "complete", "outcome": "supported",
                     "reasoning": "Boundedness and monotonicity establish the stated convergence step.",
                     "evidence_refs": ["anc_auxiliary"], "conditions": [], "next_action": None, "supersedes": None},
                    {"target": {"source_anchor_id": "anc_auxiliary", "description": "The application of the bound"},
                     "kind": "application", "state": "complete", "outcome": "supported",
                     "reasoning": "Lemma 1 supplies the required bound for the convergence calculation.",
                     "evidence_refs": ["anc_auxiliary"], "conditions": [], "next_action": None, "supersedes": None}]}
            raw = canonical_bytes(worker)
            submitted = review.submit_review(db, submission={"contract_version": 4,
                "request_id": fx.request_id(), "packet_id": neutral["packet_id"],
                "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "source_only", "exposure_note": ""},
                response_bytes=raw)
            self.assertEqual("needs_revision", submitted["state"], submitted)
            packet = fx.packet(db, *fx.ITEMS, mode="primary")
            mapped = review.map_response(db, mapping={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": packet["packet_id"], "response_id": submitted["response_id"], "reviewer": "coordinator",
                "entries": [{"judgment_index": index, "target": target,
                             "rationale": "This source passage contains the canonical record's own inference."}
                            for index, target in enumerate((R("groups", "grp_thm"), R("uses", "use_lem_thm")))]})
            self.assertEqual("accepted", mapped["state"], mapped)
            self.assertEqual(raw, db.get_blob(db.head("responses", submitted["response_id"]).body["original_blob"]))
            for row in mapped["checks"]:
                check = db.head("checks", row["check_id"])
                judgment = worker["judgments"][row["judgment_index"]]
                self.assertEqual(judgment["reasoning"], check.body["reasoning"])
                self.assertEqual(judgment["evidence_refs"], check.body["evidence_refs"])

    def test_stale_explicit_selection_supplies_no_whole_capture_grounding_credit(self):
        fx = self.shared_page_fixture()
        with fx.open() as db:
            argument = db.head("arguments", "arg_lem")
            fx.apply(db, [fx.group_edit("grp_new_final", "arg_lem", "itm_lem", "anc_shared"),
                edit("replace", "arguments", argument.id,
                    dict(argument.body, final_group_id="grp_new_final"), argument.version)], *fx.ITEMS)
            status = stages.stage_status(db, audit_id=fx.audit_id)
            self.assertFalse(status["stage1"]["source_grounding_settled"])
            self.assertTrue(any(row["code"] == "source_grounding_boundary_unsettled"
                                and row["argument_ref"] == argument.ref for row in status["stage1"]["blockers"]))
            self.assertFalse(any(row["code"] == "source_grounding_outside_reviewed_proof"
                                 and row["argument_ref"] == argument.ref for row in status["stage1"]["blockers"]))

    def test_diagnostic_truncation_cannot_establish_grounding(self):
        fx = self.ungrounded("truncated", "uses", "use_lem_thm")
        with fx.open() as db:
            derived, assessed = assessment.derive_full(db, audit_id=fx.audit_id)
            full = work.build_work(derived, assessed, diagnostic_limit=None)
            result = stages.grounding_readiness(derived, assessed, full, diagnostic_limit=0)
            self.assertFalse(result["source_grounding_settled"])
            self.assertEqual([], result["blockers"])
            self.assertGreater(result["blocker_count"], 0)
            self.assertTrue(result["blockers_truncated"])

    def test_incomplete_supplied_facts_cannot_establish_grounding(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            derived, assessed = assessment.derive_full(db, audit_id=fx.audit_id)
            full = work.build_work(derived, assessed, diagnostic_limit=None)
            unknown = stages.grounding_readiness(derived, assessed, dict(full, tasks=full["tasks"][:1]))
            self.assertIsNone(unknown["source_grounding_settled"])

    def test_current_source_resolution_does_not_reuse_a_stale_source_version(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            self.assertTrue(target_source_resolution(db, R("groups", "grp_lem"))["anchors"])
            source_path = fx.source_root / "paper.tex"
            source_path.write_text(source_path.read_text(encoding="utf-8") + "\nChanged source.\n", encoding="utf-8")
            sources.capture_sources(db, files=["paper.tex"])
            resolved = target_source_resolution(db, R("groups", "grp_lem"))
            self.assertEqual([], resolved["anchors"])
            self.assertEqual([{"code": "stale_source", "anchor_id": "anc_lem_proof"}], resolved["issues"])

    def test_identical_extracted_text_on_different_pdf_pages_is_not_overlap(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            left = copy.deepcopy(db.head("anchors", "anc_lem_proof").body)
            left["locator"] = locator(page=1)
            right = dict(left, locator=locator(page=2))
            self.assertFalse(anchors_overlap(left, right))
            self.assertTrue(anchors_overlap(left, dict(left)))


class OrdinaryPreparationPolicyTests(TempCase):
    def require_global(self, fx, db):
        audit = db.head("audits", fx.audit_id)
        tasks = [dict(row) for row in audit.body["global_tasks"]]
        tasks[0].update(applicability="required", reason="Cross-result consistency needs examination.")
        fx.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, global_tasks=tasks), audit.version)],
                 *fx.ITEMS, mode="primary")
        return next(row for row in work.derive_work(db, audit_id=fx.audit_id)["tasks"]
                    if row["kind"] == "global_consistency")

    def test_implicit_primary_selection_is_local_even_when_global_work_is_pending(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            self.require_global(fx, db)
            result = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="primary")
            self.assertFalse(result["prepared"])
            self.assertEqual(1, result["stage"])
            self.assertEqual([], result["assigned_task_ids"])

    def test_explicit_global_selection_uses_both_stage_two_gates(self):
        for primary_done in (False, True):
            with self.subTest(primary_done=primary_done):
                fx = self.fixture(str(primary_done)).audit()
                if primary_done:
                    fx.primary()
                with fx.open() as db:
                    global_task = self.require_global(fx, db)
                    result = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="primary",
                                                          task_ids=[global_task["id"]])
                    self.assertFalse(result["prepared"])
                    self.assertEqual(2, result["stage"])
                    self.assertEqual("global", result["stage_mode"])
                    self.assertEqual("LOCAL_REVIEW_NOT_COMPLETE" if primary_done else "STAGE1_NOT_READY",
                                     result["reason_code"])

    def test_mixed_explicit_request_returns_precise_split_without_preparing_a_packet(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            global_task = self.require_global(fx, db)
            local_task = next(row for row in work.derive_work(db, audit_id=fx.audit_id)["tasks"]
                              if row["kind"] == "composition" and row["role"] == "primary")
            before = db.max_revision()
            result = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="primary",
                task_ids=[local_task["id"], global_task["id"]])
            self.assertFalse(result["prepared"])
            self.assertEqual("MIXED_STAGE_REQUEST", result["reason_code"])
            self.assertEqual([{"stage": 1, "mode": "primary", "task_ids": [local_task["id"]]},
                              {"stage": 2, "mode": "global", "task_ids": [global_task["id"]]}],
                             result["selection_diagnostics"][0]["split"])
            self.assertEqual(before, db.max_revision())
            self.assertNotIn("packet_id", result)

    def test_optional_global_and_empty_focused_local_selection_never_select_other_work(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            optional = next(row for row in work.derive_work(db, audit_id=fx.audit_id)["tasks"]
                            if row["kind"] == "global_consistency")
            result = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="primary", task_ids=[optional["id"]])
            self.assertFalse(result["prepared"])
            self.assertEqual("TASK_NOT_REQUIRED", result["reason_code"])
            empty = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="primary", focus=R("audits", fx.audit_id))
            self.assertFalse(empty["prepared"])
            self.assertEqual([], empty["assigned_task_ids"])

    def test_ordinary_and_explicit_preparation_share_one_assessment_and_selection(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            with mock.patch.object(stages, "derive_full", wraps=stages.derive_full) as derive:
                ordinary = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="primary",
                    focus=R("items", "itm_lem"), max_units=1)
                self.assertEqual(1, derive.call_count)
            explicit = stages.prepare_stage(db, audit_id=fx.audit_id, stage=1,
                focus=R("items", "itm_lem"), max_units=1)
            self.assertTrue(ordinary["prepared"], ordinary)
            self.assertEqual(explicit["assigned_task_ids"], ordinary["assigned_task_ids"])
            self.assertEqual(explicit["revision"], ordinary["revision"])

    def test_prior_valid_assignment_can_be_saved_and_mapped_when_new_preparation_is_blocked(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            view, assessed = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
            # Preserve an assignment made by the historical scheduling entry point.
            prior = controller.prepare_assessed_work(db, audit_id=fx.audit_id, mode="independent", view=view,
                assessed=assessed, focus=R("items", "itm_lem"))
            self.assertTrue(prior["prepared"], prior)
            current = stages.prepare_ordinary_work(db, audit_id=fx.audit_id, mode="independent")
            self.assertFalse(current["prepared"])
            worker = {"packet_id": prior["packet_id"], "covered_targets": [R("items", "itm_lem")],
                "coverage_note": "Examined the complete written lemma proof.",
                "exposure_report": {"status": "none_known", "note": ""},
                "judgments": [{"target": {"source_anchor_id": "anc_lem_proof", "description": "The written lemma proof"},
                    "kind": "composition", "state": "complete", "outcome": "gap", "reasoning": "The induction base case is absent.",
                    "evidence_refs": ["anc_lem_proof"], "conditions": [], "next_action": None, "supersedes": None}]}
            envelope = {"contract_version": 4, "request_id": fx.request_id(), "packet_id": prior["packet_id"],
                "rebase_packet_id": None, "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": ""}
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
            self.assertEqual("needs_revision", saved["state"], saved)
            packet = fx.packet(db, *fx.ITEMS, mode="primary")
            mapped = review.map_response(db, mapping={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": packet["packet_id"], "response_id": saved["response_id"], "entries": [
                    {"judgment_index": 0, "target": R("arguments", "arg_lem"),
                     "rationale": "The original source passage is the canonical written argument."}], "reviewer": "coordinator"})
            self.assertEqual("accepted", mapped["state"])
            self.assertEqual("gap", db.head("checks", mapped["checks"][0]["check_id"]).body["outcome"])
            self.assertEqual(canonical_bytes(worker), db.get_blob(db.head("responses", saved["response_id"]).body["original_blob"]))
