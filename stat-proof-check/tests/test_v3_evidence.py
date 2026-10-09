"""Observable evidence, neutral question and separable intake behavior."""
from __future__ import annotations

import copy
import json

from support import R, TempCase, edit, locator
from paper_core import assessment, controller, packets, review, sources
from paper_core.bindings import binding_changes, coherent_unit_inputs, task_binding_changes
from paper_core.errors import InvalidRequest
from paper_core.validation import State


class EvidenceTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def prepare(self, targets, kinds=None, mode="independent"):
        kinds = kinds or ["composition"] * len(targets)
        tasks = [{"id": f"task_{i}", "target": target, "kind": kind, "role": mode,
                  "action": "check", "prerequisite_ids": [], "draft_refs": []}
                 for i, (target, kind) in enumerate(zip(targets, kinds))]
        return packets.prepare_assignment(self.db, audit_id=self.fx.audit_id, mode=mode,
            selection={"revision": self.db.max_revision(), "units": [{"id": f"unit_{i}",
                "task_ids": [task["id"]]} for i, task in enumerate(tasks)], "tasks": tasks})

    def submit(self, prepared, worker):
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(),
                    "packet_id": prepared["packet_id"], "rebase_packet_id": None,
                    "reviewer": "actual independent route", "qualification_id": None,
                    "exposure": "source_only", "exposure_note": "Actual separate source-only context."}
        raw = json.dumps(worker, ensure_ascii=False).encode("utf-8")
        result = controller.submit_work(self.db, envelope_bytes=json.dumps(envelope).encode(), response_bytes=raw)
        return result, raw

    def test_exact_local_questions_remain_distinct_and_map_without_pins(self):
        changes = []
        for i in range(3):
            item = self.fx.item_edit(f"itm_local_{i}", "equation", f"Local bound {i}", "anc_thm_proof", "anc_thm_proof")
            item["body"].update(owner_id="itm_thm", statement={"form": "transcription", "text": f"a_{i} <= 1"})
            changes.extend([item, self.fx.argument_edit(f"arg_local_{i}", f"itm_local_{i}", f"grp_local_{i}", "anc_thm_proof"),
                            self.fx.group_edit(f"grp_local_{i}", f"arg_local_{i}", f"itm_local_{i}", "anc_thm_proof")])
        self.fx.apply(self.db, changes)
        prepared = self.prepare([R("arguments", f"arg_local_{i}") for i in range(3)])
        self.assertEqual([], packets.blinding_violations(prepared["packet"]))
        self.assertEqual([f"a_{i} <= 1" for i in range(3)], [row["question"] for row in prepared["packet"]["assignments"]])
        self.assertEqual(3, len({row["question_id"] for row in prepared["packet"]["assignments"]}))
        worker = controller.response_scaffold(prepared["manifest"])
        for row in worker["judgments"]:
            row.update(state="complete", outcome="supported", reasoning="The exact assigned bound follows from its displayed assumptions.")
        result, raw = self.submit(prepared, worker)
        self.assertEqual("accepted", result["state"], result)
        self.assertEqual([], result["pending"])
        response = self.db.head("responses", result["response_id"])
        self.assertIsNone(response.body["qualification_id"])
        self.assertEqual(raw, self.db.get_blob(response.body["original_blob"]))
        checks = [record for record in self.db.heads("checks") if record.body["response_id"] == response.id]
        self.assertEqual({f"arg_local_{i}" for i in range(3)}, {check.body["target"]["id"] for check in checks})
        self.assertTrue(all(check.body["extent"] == "whole_unit" for check in checks))

    def test_hidden_supplier_chain_and_cycle_reach_statement_without_its_proof(self):
        changes = []
        for name in ("one", "two"):
            item = self.fx.item_edit(f"itm_hidden_{name}", "equation", name, "anc_thm_proof", "anc_thm_proof")
            item["body"]["owner_id"] = "itm_thm"
            changes.append(item)
        for name, supplier, target, group in (
            ("supply", "itm_lem", "itm_hidden_one", None),
            ("hop", "itm_hidden_one", "itm_hidden_two", None),
            ("cycle", "itm_hidden_two", "itm_hidden_one", None),
            ("consume", "itm_hidden_two", "itm_thm", "grp_thm")):
            changes.append(edit("create", "uses", f"use_{name}", {"from": R("items", supplier), "to": R("items", target),
                "type": "dependency", "reason": "written premise", "evidence_refs": ["anc_thm_proof"],
                "regime": None, "uncertainty": None}))
            if group:
                changes.append(edit("create", "application_details", f"use_{name}", {
                    "use_id": f"use_{name}", "group_id": group, "scope_id": "scp_plain",
                    "needed_form": {"form": "transcription", "text": "two text"},
                    "substitutions": [], "state": "registered"}))
        self.fx.apply(self.db, changes)
        use = self.db.head("uses", "use_lem_thm")
        self.fx.apply(self.db, [{"op": "retire", "collection": "uses", "id": use.id,
            "expected_version": use.version, "reason": "chain replaces the direct premise"}])
        prepared = self.prepare([R("arguments", "arg_thm")])
        records = {(row["ref"]["collection"], row["ref"]["id"]) for row in prepared["packet"]["records"]}
        self.assertIn(("anchors", "anc_lem"), records)
        self.assertNotIn(("anchors", "anc_lem_proof"), records)
        self.assertFalse(any(collection == "items" and "hidden" in identity for collection, identity in records))

    def test_valid_return_survives_malformed_and_adverse_peripheral_rows(self):
        prepared = self.prepare([R("arguments", "arg_thm")])
        worker = controller.response_scaffold(prepared["manifest"])
        worker["judgments"][0].update(state="complete", outcome="gap", reasoning="Boundedness alone does not establish convergence.")
        worker["judgments"].append({"target": {"source_anchor_id": "anc_thm_proof", "description": "extra concern"},
                                    "reasoning": "The missing monotonicity assumption is material."})
        adverse = copy.deepcopy(worker["judgments"][0])
        adverse.pop("question_id")
        adverse["target"]["description"] = "The independent prerequisite has a separate gap."
        adverse["reasoning"] = "A separate prerequisite could fail."
        worker["judgments"].append(adverse)
        result, raw = self.submit(prepared, worker)
        self.assertEqual("accepted", result["state"], result)
        response = self.db.head("responses", result["response_id"])
        self.assertEqual([1, 2], response.body["pending_judgments"])
        self.assertIn("missing monotonicity", response.body["coverage_note"])
        self.assertIn("separate prerequisite", response.body["coverage_note"])
        self.assertEqual(raw, self.db.get_blob(response.body["original_blob"]))
        checks = [r for r in self.db.heads("checks") if r.body["response_id"] == response.id]
        self.assertEqual(1, len(checks))
        self.assertEqual("gap", checks[0].body["outcome"])

    def test_consumer_gets_shared_source_statement_and_only_explicitly_borrowed_proof(self):
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={
            "contract_version": 4, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
            "anchors": [{"id": identity, "expected_version": None, "source_id": self.fx.source_id,
                         "locator": locator(start=line, end=line)}
                        for identity, line in (("anc_shared_statement", 6), ("anc_shared_proof", 9))]})
        item = self.fx.item_edit("itm_shared", "equation", "PRIVATE_COORDINATOR_CAPTION",
                                 "anc_shared_statement", "anc_shared_proof")
        item["body"]["owner_id"] = "itm_lem"
        use = edit("create", "uses", "use_shared_thm", {
            "from": R("items", "itm_shared"), "to": R("items", "itm_thm"), "type": "dependency",
            "group_id": "grp_thm", "reason": "Applies the shared bound.",
            "needed_form": {"form": "verbatim", "text": "The stated bound."}, "substitutions": [],
            "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})
        self.fx.apply(self.db, [item, use])
        for borrowed in (False, True):
            if borrowed:
                saved = self.db.head("uses", "use_shared_thm")
                self.fx.apply(self.db, [edit("replace", "uses", saved.id,
                    dict(saved.body, type="proof_argument"), saved.version)])
            prepared = self.prepare([R("arguments", "arg_thm")])
            records = {(row["ref"]["collection"], row["ref"]["id"]) for row in prepared["packet"]["records"]}
            self.assertIn(("anchors", "anc_shared_statement"), records)
            self.assertEqual(borrowed, ("anchors", "anc_shared_proof") in records)
            self.assertNotIn(("anchors", "anc_lem_proof"), records)
            self.assertNotIn(("items", "itm_shared"), records)
            self.assertNotIn("PRIVATE_COORDINATOR_CAPTION", json.dumps(prepared["packet"]))
            self.assertEqual([], packets.blinding_violations(prepared["packet"]))
        # The ordinary consumer's primary examination also consumes an
        # explicitly borrowed proof, even when its reasoning cites only its
        # own proof passage. Changing the borrowed passage must affect it.
        self.fx.apply(self.db, [self.fx.check_edit("chk_borrowed", R("arguments", "arg_thm"),
            "composition", evidence=["anc_thm_proof"])], mode="primary")
        before = assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)
        self.assertEqual("current", before["judgments"]["checks:chk_borrowed"]["freshness"])
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={
            "contract_version": 4, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
            "anchors": [{"id": "anc_shared_proof", "expected_version": 1, "source_id": self.fx.source_id,
                         "locator": locator(start=6, end=6)}]})
        after = assessment.derive_assessment(self.db, audit_id=self.fx.audit_id)
        self.assertNotEqual("current", after["judgments"]["checks:chk_borrowed"]["freshness"])

    def test_partial_extent_and_omissions_are_preserved(self):
        prepared = self.prepare([R("arguments", "arg_thm")])
        worker = controller.response_scaffold(prepared["manifest"])
        worker["judgments"][0].update(state="complete", outcome="inconclusive", reasoning="Only the first application was examined.",
            extent="partial", omissions="The convergence inference remains unexamined.")
        result, _ = self.submit(prepared, worker)
        self.assertEqual("accepted", result["state"], result)
        check = next(r for r in self.db.heads("checks") if r.body["response_id"] == result["response_id"])
        self.assertEqual("partial", check.body["extent"])
        self.assertEqual(worker["judgments"][0]["omissions"], check.body["omissions"])

    def test_binding_ignores_coverage_rows_and_cosmetic_labels(self):
        self.fx.primary()
        check = self.db.head("checks", "chk_comp_thm")
        binding = self.db.binding("checks", check.id, check.version)["bindings"]
        self.assertIn("coherent_scope", binding)
        argument = self.db.head("arguments", "arg_thm")
        coverage = self.db.head("coverage", "cov_thm")
        self.fx.apply(self.db, [edit("replace", "arguments", argument.id, dict(argument.body, label="Renamed route"), argument.version),
            edit("replace", "coverage", coverage.id, dict(coverage.body, note="Explanatory annotation"), coverage.version)])
        self.assertEqual({"records": [], "relations": []}, binding_changes(State(self.db, []), binding))
        scope = self.db.head("scopes", "scp_plain")
        self.fx.apply(self.db, [edit("replace", "scopes", scope.id, dict(scope.body, conditions=["n is fixed"]), scope.version)])
        self.assertTrue(binding_changes(State(self.db, []), binding)["records"])

    def test_new_internal_detail_reuses_basis_but_changed_application_reopens_it(self):
        self.fx.primary()
        check = self.db.head("checks", "chk_comp_thm")
        binding = self.db.binding("checks", check.id, check.version)["bindings"]
        target = self.db.head("items", "itm_thm")
        item = self.fx.item_edit("itm_detail", "equation", "Equivalent explanatory conclusion", "anc_thm_proof", "anc_thm_proof")
        item["body"].update(owner_id="itm_thm", statement=target.body["statement"])
        use = self.db.head("uses", "use_lem_thm")
        application_detail = self.db.head("application_details", use.id)
        self.fx.apply(self.db, [item,
            self.fx.group_edit("grp_detail", "arg_thm", "itm_detail", "anc_thm_proof"),
            edit("create", "uses", "use_detail", dict(use.body, to=R("items", "itm_detail"))),
            edit("create", "application_details", "use_detail", dict(application_detail.body,
                use_id="use_detail", group_id="grp_detail"))])
        self.assertEqual({"records": [], "relations": []}, binding_changes(State(self.db, []), binding))
        changed = dict(application_detail.body, needed_form={"form": "transcription", "text": "Uniformly over a data-dependent optimizer"})
        self.fx.apply(self.db, [edit("replace", "application_details", application_detail.id, changed, application_detail.version)])
        changes = binding_changes(State(self.db, []), binding)
        self.assertTrue(any(row["facet"] == "examined_application" for row in changes["records"]))

    def test_application_question_names_required_form_and_substitution(self):
        detail = self.db.head("application_details", "use_lem_thm")
        self.fx.apply(self.db, [edit("replace", "application_details", detail.id,
            dict(detail.body, needed_form={"form": "transcription", "text": "a_7 <= 1"},
                 substitutions=[{"symbol": "n", "value": "7"}]), detail.version)])
        prepared = self.prepare([R("uses", "use_lem_thm")], ["application"])
        question = prepared["packet"]["assignments"][0]["question"]
        self.assertIn("a_7 <= 1", question)
        self.assertIn("Substitutions", question)
        self.assertNotIn("Theorem 1 text", question)

    def test_material_existing_group_and_final_route_change_reopen_unit(self):
        self.fx.primary()
        check = self.db.head("checks", "chk_comp_thm")
        binding = self.db.binding("checks", check.id, check.version)["bindings"]
        group = self.db.head("groups", "grp_thm")
        self.fx.apply(self.db, [edit("create", "scopes", "scp_case", {"argument_id": "arg_thm", "parent_id": "scp_plain",
            "assumptions": [], "binders": [], "conditions": ["n is positive"], "evidence_refs": ["anc_thm_proof"]}),
            edit("replace", "groups", group.id, dict(group.body, kind="cases", case_scope_ids=["scp_case"]), group.version)])
        changes = binding_changes(State(self.db, []), binding)["records"]
        self.assertTrue(any(row["facet"] == "examined_inference" for row in changes))
        self.assertTrue(any(row["facet"] == "final_inference" for row in changes))

    def test_source_only_local_question_rejects_a_proposed_reconstruction(self):
        argument = self.db.head("arguments", "arg_thm")
        self.fx.apply(self.db, [edit("replace", "arguments", argument.id,
            dict(argument.body, origin="reconstruction"), argument.version)])
        with self.assertRaisesRegex(InvalidRequest, "proposed reconstruction"):
            self.prepare([R("arguments", "arg_thm")])

    def test_supplied_reconstruction_has_visible_route_scaffold_and_actual_basis(self):
        self.fx.independent()
        route = self.fx.argument_edit("arg_proposed", "itm_thm", "grp_proposed", "anc_thm_proof")
        route["body"]["origin"] = "reconstruction"
        self.fx.apply(self.db, [route, self.fx.group_edit("grp_proposed", "arg_proposed", "itm_thm", "anc_thm_proof"),
            self.fx.check_edit("chk_proposed", R("arguments", "arg_proposed"), "composition",
                evidence=["anc_thm_proof"])], mode="primary")
        prepared = packets.prepare_route_assignment(self.db, audit_id=self.fx.audit_id, route_id="arg_proposed")
        self.assertEqual("route_provided", prepared["manifest"]["review_basis"])
        worker = controller.response_scaffold(prepared["manifest"])
        self.assertEqual(1, len(worker["judgments"]))
        self.assertEqual(R("arguments", "arg_proposed"), worker["judgments"][0]["target"])
        task = prepared["manifest"]["work"]["tasks"][0]
        self.assertEqual({"records": [], "relations": []},
            task_binding_changes(State(self.db, []), task, packet=prepared["manifest"]))
        worker["judgments"][0].update(state="complete", outcome="gap", reasoning="The provided reconstruction has a missing premise.")
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "actual supplied-route reviewer", "qualification_id": None,
            "exposure": "route_provided", "exposure_note": "Reviewer received the explicitly supplied reconstruction."}
        result = controller.submit_work(self.db, envelope_bytes=json.dumps(envelope).encode(), response_bytes=json.dumps(worker).encode())
        self.assertEqual("accepted", result["state"], result)
        self.assertEqual("route_provided", self.db.head("responses", result["response_id"]).body["exposure"])

    def test_multisource_selection_preserves_complete_excerpts_and_continuation(self):
        (self.fx.source_root / "supplement.tex").write_text("Other proof.\nRemaining case: apply the lemma.\nFooter.\n", encoding="utf-8")
        captured = sources.capture_sources(self.db, files=["supplement.tex"])
        source_id = captured["sources"][0]["id"]
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 4, "request_id": self.fx.request_id(),
            "packet_id": packet["packet_id"], "anchors": [{"id": "anc_continuation", "expected_version": None,
            "source_id": source_id, "locator": locator(start=1, end=3)}]})
        proof = self.db.head("anchors", "anc_thm_proof")
        continuation = self.db.head("anchors", "anc_continuation")
        refs = [proof.pinned, continuation.pinned]
        source_review = {"source_refs": [self.fx.pin(self.db, "sources", self.fx.source_id), self.fx.pin(self.db, "sources", source_id)],
            "anchor_refs": refs, "purpose": "proof_boundary", "decision": "accepted", "rationale": "Located main proof and supplement continuation.",
            "reviewer": "source reader", "proof_spans": [{"argument_ref": self.fx.pin(self.db, "arguments", "arg_thm"),
                "anchor_ref": pin, "start_offset": 0 if pin == proof.pinned else len("Other proof.\n"),
                "end_offset": len(proof.body["excerpt"]) if pin == proof.pinned else len(continuation.body["excerpt"]) - len("\nFooter.")}
                for pin in refs]}
        packet = self.fx.packet(self.db)
        sources.review_sources(self.db, batch=self.fx.batch([edit("create", "source_reviews", "srv_multi", source_review)], packet["packet_id"]))
        boundary = self.db.head("proof_boundaries", "bnd_thm")
        self.fx.apply(self.db, [edit("replace", "proof_boundaries", boundary.id,
            dict(boundary.body, anchor_refs=refs, source_review_ref=self.fx.pin(self.db, "source_reviews", "srv_multi")), boundary.version)])
        prepared = self.prepare([R("arguments", "arg_thm")])
        assignment = prepared["packet"]["assignments"][0]
        self.assertEqual(2, len(assignment["selected_passages"]))
        captured_excerpt = next(row["body"]["excerpt"] for row in prepared["packet"]["records"] if row["ref"]["id"] == "anc_continuation")
        self.assertIn("Other proof.", captured_excerpt)
        inputs = coherent_unit_inputs(State(self.db, []), "arg_thm")
        self.assertIn("anc_continuation", [ref["id"] for ref in inputs["source_evidence_refs"]])
        global_packet = self.prepare([R("audits", self.fx.audit_id)], ["global_consistency"], mode="primary")
        global_records = {(row["ref"]["collection"], row["ref"]["id"]) for row in global_packet["packet"]["records"]}
        self.assertIn(("anchors", "anc_continuation"), global_records)
        self.assertIn(("anchors", "anc_thm_proof"), global_records)
        global_task = global_packet["manifest"]["work"]["tasks"][0]
        self.assertEqual(2, len(global_task["coherent_scopes"]))
        self.assertEqual({"records": [], "relations": []},
            task_binding_changes(State(self.db, []), global_task, packet=global_packet["manifest"]))
        boundary = self.db.head("proof_boundaries", "bnd_thm")
        with self.assertRaises(InvalidRequest):
            self.fx.apply(self.db, [edit("replace", "proof_boundaries", boundary.id,
                dict(boundary.body, anchor_refs=[proof.pinned]), boundary.version)])
