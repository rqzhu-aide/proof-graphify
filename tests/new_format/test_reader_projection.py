"""Reader contexts preserve exact targets, local assumptions and recorded inference routes."""
from copy import deepcopy

from support import R, TempCase, edit
from paper_core import assessment, projection, sources


def scope(identity, *, parent=None, assumptions=(), conditions=(), argument=None):
    return edit("create", "scopes", identity, {"argument_id": argument, "parent_id": parent,
        "assumptions": list(assumptions), "binders": [], "conditions": list(conditions), "evidence_refs": []})


def exact(identity, target, *, statement=None, pin=None, scope_id=None, state="registered"):
    return edit("create", "target_specs", identity, {"target": target, "statement_ref": pin,
        "statement": statement, "scope_id": scope_id, "state": state, "evidence_refs": [], "fidelity_ref": None})


def blocked_premise_fixture(fixture, *, alternative=False):
    """Synthetic judgments: the application is examined, but its supplier is private."""
    fixture.audit(independent_required=False)
    with fixture.open() as db:
        edits = [scope("scp_supplier", parent="scp_plain", conditions=["x > 0"])]
        for collection, identity in (("target_specs", "tgt_lem"), ("arguments", "arg_lem"), ("groups", "grp_lem")):
            row = db.head(collection, identity)
            edits.append(edit("replace", collection, identity, dict(row.body, scope_id="scp_supplier"), row.version))
        fixture.apply(db, edits, *fixture.ITEMS)
    fixture.primary()
    if alternative:
        with fixture.open() as db:
            fixture.apply(db, [
                fixture.argument_edit("arg_alternative", "itm_thm", "grp_alternative", "anc_thm_proof"),
                fixture.group_edit("grp_alternative", "arg_alternative", "itm_thm", "anc_thm_proof"),
                fixture.check_edit("chk_alternative_der", R("groups", "grp_alternative"), "derivation"),
                fixture.check_edit("chk_alternative_comp", R("arguments", "arg_alternative"), "composition")
            ], *fixture.ITEMS, mode="primary")
    return fixture


def cyclic_premise_fixture(fixture):
    """Examined local implications cannot establish two mutually dependent claims."""
    fixture.audit(independent_required=False)
    with fixture.open() as db:
        original = db.head("uses", "use_lem_thm").body
        fixture.apply(db, [edit("create", "uses", "use_cycle", dict(original,
            **{"from": R("items", "itm_thm"), "to": R("items", "itm_lem"), "group_id": "grp_lem",
               "needed_form": {"form": "verbatim", "text": "Theorem 1 text"}}))], *fixture.ITEMS)
    fixture.primary()
    with fixture.open() as db:
        fixture.apply(db, [fixture.check_edit("chk_cycle", R("uses", "use_cycle"), "application")],
                      *fixture.ITEMS, mode="primary")
    return fixture


class ReaderProjectionTests(TempCase):
    def project(self, fixture, *, audit_id=None):
        with fixture.open(write=False) as db:
            dataset, report = projection.project(db, audit_id=audit_id)
        # The fixtures deliberately include incomplete or stale proof work. Reader construction
        # must add no structural problem to those existing mathematical audit limitations.
        self.assertEqual(report["problems"], dataset["summary"]["limitations"])
        pins = {(row["ref"]["collection"], row["ref"]["id"], row["ref"]["version"]) for row in dataset["records"]}
        def check_pins(value):
            if isinstance(value, dict):
                if set(value) == {"collection", "id", "version"}:
                    self.assertIn((value["collection"], value["id"], value["version"]), pins)
                for child in value.values():
                    check_pins(child)
            elif isinstance(value, list):
                for child in value:
                    check_pins(child)
        for detail in dataset["details"].values():
            check_pins(detail.get("reader"))
        return dataset

    def test_historical_exact_statement_and_current_strategy_are_separately_pinned(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            old = db.head("items", "itm_thm")
            body = deepcopy(old.body)
            body["statement"] = {"form": "synopsis", "text": "A newer, shorter summary."}
            body["proof_idea"] = "Use the lemma's bound, then apply monotone convergence."
            fixture.apply(db, [edit("replace", "items", old.id, body, old.version)], *fixture.ITEMS)
        dataset = self.project(fixture, audit_id=fixture.audit_id)
        reader = dataset["details"]["item:itm_thm"]["reader"]
        target = reader["targets"][0]
        self.assertEqual(target["exact_state"], "registered")
        self.assertEqual(target["statement_ref"], {"collection": "items", "id": "itm_thm", "version": 1})
        self.assertEqual(reader["strategy_ref"]["version"], 2)
        self.assertEqual(target["target_ref"]["version"], 2)
        self.assertEqual(target["assessment"], next(n["assessment"] for n in dataset["nodes"] if n["id"] == "itm_thm"))
        bodies = {(r["ref"]["collection"], r["ref"]["id"], r["ref"]["version"]): r["body"] for r in dataset["records"]}
        self.assertEqual(bodies[("items", "itm_thm", 1)]["statement"]["text"], "Theorem 1 text")
        self.assertEqual(bodies[("items", "itm_thm", 2)]["proof_idea"], body["proof_idea"])

    def test_target_scope_ancestry_includes_named_premises_but_null_scope_stays_empty(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            assumption = fixture.item_edit("itm_assumption", "assumption", "Assumption A", "anc_lem", "anc_lem_proof")
            current = db.head("items", "itm_thm")
            fixture.apply(db, [assumption,
                scope("scp_parent", assumptions=[R("items", "itm_assumption")], conditions=["n is positive"]),
                scope("scp_target", parent="scp_parent", conditions=["The sequence is monotone"]),
                edit("replace", "items", current.id, dict(current.body, scope_id="scp_target"), current.version),
                exact("tgt_null", R("items", "itm_thm"), statement={"form": "transcription", "text": "Exact null-context claim"}),
                exact("tgt_scoped", R("items", "itm_lem"), statement={"form": "transcription", "text": "Exact scoped claim"}, scope_id="scp_target")])
        dataset = self.project(fixture)
        theorem = dataset["details"]["item:itm_thm"]["reader"]["targets"][0]
        lemma = dataset["details"]["item:itm_lem"]["reader"]["targets"][0]
        self.assertEqual(theorem["scope_chain"], [])
        self.assertEqual(theorem["statement_ref"]["id"], "tgt_null")
        self.assertEqual([row["scope_ref"]["id"] for row in lemma["scope_chain"]], ["scp_target", "scp_parent"])
        self.assertEqual(lemma["scope_chain"][1]["assumption_refs"][0]["id"], "itm_assumption")
        refs = dataset["details"]["item:itm_lem"]["record_refs"]
        self.assertIn({"collection": "items", "id": "itm_assumption", "version": 1}, refs)
        self.assertIn({"collection": "anchors", "id": "anc_lem", "version": 1}, refs)

    def test_missing_and_draft_targets_preserve_fallback_context_without_claiming_exactness(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            item = db.head("items", "itm_thm")
            fixture.apply(db, [scope("scp_fallback", conditions=["Recorded setup only"]),
                edit("replace", "items", item.id, dict(item.body, scope_id="scp_fallback"), item.version),
                exact("tgt_draft", R("items", "itm_lem"), statement={"form": "transcription", "text": "Draft claim"}, state="draft")])
        dataset = self.project(fixture)
        theorem = dataset["details"]["item:itm_thm"]["reader"]["targets"][0]
        lemma = dataset["details"]["item:itm_lem"]["reader"]["targets"][0]
        self.assertEqual(theorem["exact_state"], "missing")
        self.assertEqual(theorem["scope_chain"][0]["scope_ref"]["id"], "scp_fallback")
        self.assertEqual(lemma["exact_state"], "draft")
        self.assertEqual(lemma["statement_ref"]["collection"], "items")
        self.assertEqual(lemma["scope_chain"], [])

    def test_same_owner_chain_is_linked_while_unconnected_subsidiary_stays_separate(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            edits = []
            for name in ("linked", "side"):
                item = fixture.item_edit(f"itm_{name}", "intermediate_result", name, "anc_thm", "anc_thm_proof")
                item["body"]["owner_id"] = "itm_thm"
                edits.extend([item, fixture.argument_edit(f"arg_{name}", f"itm_{name}", f"grp_{name}", "anc_thm_proof"),
                    fixture.group_edit(f"grp_{name}", f"arg_{name}", f"itm_{name}", "anc_thm_proof"),
                    exact(f"tgt_{name}", R("items", f"itm_{name}"), statement={"form": "transcription", "text": name})])
                use = dict(db.head("uses", "use_lem_thm").body, to=R("items", f"itm_{name}"),
                    group_id=f"grp_{name}", needed_form={"form": "verbatim", "text": "Lemma 1 text"}, substitutions=[])
                edits.append(edit("create", "uses", f"use_to_{name}", use))
            use = dict(db.head("uses", "use_lem_thm").body, **{"from": R("items", "itm_linked")},
                group_id="grp_thm", needed_form={"form": "transcription", "text": "linked"}, substitutions=[])
            edits.append(edit("create", "uses", "use_internal", use))
            fixture.apply(db, edits, *fixture.ITEMS)
        dataset = self.project(fixture)
        detail = dataset["details"]["item:itm_thm"]
        apps = {row["use_ref"]["id"]: row for row in detail["reader"]["applications"]}
        self.assertEqual(apps["use_to_linked"]["relation"], "linked_intermediate")
        self.assertEqual(apps["use_to_side"]["relation"], "subsidiary")
        self.assertEqual(apps["use_internal"]["relation"], "target")
        self.assertEqual(apps["use_to_linked"]["reaches_target_refs"][0]["id"], "itm_thm")
        self.assertEqual(apps["use_to_side"]["reaches_target_refs"], [])
        self.assertFalse(any("use_internal" in edge["primary_use_ids"] for edge in dataset["connections"]))
        self.assertEqual([row["target_ref"]["id"] for row in detail["reader"]["targets"]], ["itm_thm"])
        statement = next(section for section in detail["sections"] if section["kind"] == "statement")
        self.assertFalse(any(ref["id"] in ("tgt_linked", "tgt_side") for ref in statement["record_refs"]))

    def test_parallel_routes_keep_scope_case_and_refinement_contexts(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            alternative = fixture.argument_edit("arg_repair", "itm_thm", "grp_repair", "anc_thm_proof")
            alternative["body"]["origin"] = "proposed_repair"
            group = fixture.group_edit("grp_repair", "arg_repair", "itm_thm", "anc_thm_proof")
            group["body"].update(kind="cases", case_scope_ids=["scp_positive", "scp_negative"], discharges=["scp_positive", "scp_negative"])
            original = db.head("uses", "use_lem_thm").body
            fixture.apply(db, [alternative, group,
                scope("scp_positive", parent="scp_plain", conditions=["x > 0"], argument="arg_repair"),
                scope("scp_negative", parent="scp_plain", conditions=["x <= 0"], argument="arg_repair"),
                edit("create", "uses", "use_repair", dict(original, reason="Apply the bound on the positive branch.", regime="x > 0")),
                edit("create", "application_details", "use_repair", {"use_id": "use_repair", "group_id": "grp_repair",
                    "scope_id": "scp_positive", "needed_form": {"form": "verbatim", "text": "Lemma 1 text"}, "substitutions": [], "state": "registered"}),
                edit("create", "uses", "use_summary", dict(original, reason="The lemma supplies boundedness.")),
                edit("create", "connection_refinements", "ref_summary", {"summary_use_id": "use_summary", "argument_id": "arg_thm",
                    "use_ids": ["use_lem_thm"], "state": "registered", "note": "Exact application"})], *fixture.ITEMS)
        dataset = self.project(fixture)
        reader = dataset["details"]["item:itm_thm"]["reader"]
        apps = {row["use_ref"]["id"]: row for row in reader["applications"]}
        self.assertEqual(len(apps), 3)
        self.assertEqual(apps["use_repair"]["scope_chain"][0]["scope_ref"]["id"], "scp_positive")
        self.assertEqual(apps["use_lem_thm"]["scope_chain"][0]["scope_ref"]["id"], "scp_plain")
        self.assertEqual(apps["use_summary"]["refined_use_refs"], [apps["use_lem_thm"]["use_ref"]])
        self.assertEqual(apps["use_lem_thm"]["summary_use_refs"], [apps["use_summary"]["use_ref"]])
        self.assertEqual(apps["use_summary"]["assessment"]["label"], "recorded connection")
        repair = next(row for row in reader["arguments"] if row["argument_ref"]["id"] == "arg_repair")
        self.assertEqual([row["scope_ref"]["id"] for row in repair["groups"][0]["case_scopes"]], ["scp_positive", "scp_negative"])
        self.assertEqual([ref["id"] for ref in repair["groups"][0]["discharged_scope_refs"]], ["scp_positive", "scp_negative"])

    def test_mismatched_draft_group_does_not_invent_a_route_or_inherit_its_setup(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            edits = []
            for name in ("linked", "side"):
                item = fixture.item_edit(f"itm_{name}", "intermediate_result", name, "anc_thm", "anc_thm_proof")
                item["body"]["owner_id"] = "itm_thm"
                edits.extend([item, fixture.argument_edit(f"arg_{name}", f"itm_{name}", f"grp_{name}", "anc_thm_proof"),
                    fixture.group_edit(f"grp_{name}", f"arg_{name}", f"itm_{name}", "anc_thm_proof")])
            group = db.head("groups", "grp_thm")
            use = dict(db.head("uses", "use_lem_thm").body,
                **{"from": R("items", "itm_linked"), "to": R("items", "itm_side")})
            edits.extend([scope("scp_unrelated", conditions=["This setup belongs to the theorem inference"]),
                edit("replace", "groups", group.id, dict(group.body, scope_id="scp_unrelated"), group.version),
                edit("create", "uses", "use_draft", use),
                edit("create", "application_details", "use_draft", {"use_id": "use_draft", "group_id": "grp_thm",
                    "scope_id": None, "needed_form": None, "substitutions": [], "state": "draft"})])
            fixture.apply(db, edits, *fixture.ITEMS)
        dataset = self.project(fixture)
        reader = dataset["details"]["item:itm_thm"]["reader"]
        argument = next(row for row in reader["arguments"] if row["argument_ref"]["id"] == "arg_linked")
        application = next(row for row in reader["applications"] if row["use_ref"]["id"] == "use_draft")
        self.assertEqual(argument["relation"], "subsidiary")
        self.assertEqual(argument["reaches_target_refs"], [])
        self.assertEqual(application["relation"], "unassociated")
        self.assertEqual(application["reaches_target_refs"], [])
        self.assertIsNone(application["argument_ref"])
        self.assertEqual(application["scope_chain"], [])
        self.assertEqual(application["group_ref"]["id"], "grp_thm")
        self.assertEqual(application["application_ref"]["id"], "use_draft")
        self.assertEqual(application["to_ref"]["id"], "itm_side")

    def test_part_audit_does_not_promote_part_assessment_to_whole_statement(self):
        fixture = self.fixture().audit(independent_required=False)
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            fixture.apply(db, [edit("create", "parts", "prt_first", {"item_id": "itm_thm", "label": "(i)",
                "statement": {"form": "transcription", "text": "First assertion only"}, "passages": [], "scope_id": None, "origin": "source"}),
                exact("tgt_part", R("parts", "prt_first"), statement={"form": "transcription", "text": "Exact first assertion"}),
                edit("replace", "audits", audit.id, dict(audit.body, targets=[R("parts", "prt_first")]), audit.version)], *fixture.ITEMS, mode="primary")
        dataset = self.project(fixture, audit_id=fixture.audit_id)
        rows = dataset["details"]["item:itm_thm"]["reader"]["targets"]
        self.assertEqual(rows[0]["assessment"]["label"], "unassessed")
        self.assertEqual(rows[0]["assessment"]["check_refs"], [])
        self.assertEqual(rows[1]["target_ref"]["id"], "prt_first")
        self.assertNotEqual(rows[1]["assessment"]["label"], "outside scope")

    def test_null_argument_provenance_group_keeps_cases_and_discharges_with_its_recipient(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            fixture.apply(db, [scope("scp_provenance_positive", conditions=["x > 0"]),
                scope("scp_provenance_negative", conditions=["x <= 0"]),
                edit("create", "groups", "grp_provenance", {"argument_id": None, "conclusion": R("items", "itm_thm"),
                    "kind": "cases", "scope_id": None, "case_scope_ids": ["scp_provenance_positive", "scp_provenance_negative"],
                    "discharges": ["scp_provenance_positive", "scp_provenance_negative"],
                    "rationale": "A recorded partition, without an inspected argument.", "evidence_refs": ["anc_thm_proof"]})])
        dataset = self.project(fixture)
        reader = dataset["details"]["item:itm_thm"]["reader"]
        self.assertEqual(len(reader["provenance_groups"]), 1)
        group = reader["provenance_groups"][0]
        self.assertEqual(group["group_ref"]["id"], "grp_provenance")
        self.assertEqual(group["scope_chain"], [])
        self.assertEqual([entry["scope_ref"]["id"] for entry in group["case_scopes"]],
                         ["scp_provenance_positive", "scp_provenance_negative"])
        self.assertEqual([ref["id"] for ref in group["discharged_scope_refs"]],
                         ["scp_provenance_positive", "scp_provenance_negative"])
        self.assertEqual(dataset["details"]["item:itm_lem"]["reader"]["provenance_groups"], [])
        self.assertFalse(any(group["group_ref"]["id"] == "grp_provenance"
                             for argument in reader["arguments"] for group in argument["groups"]))
        self.assertEqual(reader["targets"][0]["assessment"]["label"], "unassessed")

    def test_open_findings_on_owned_steps_and_source_limits_are_prominent_but_history_is_retained(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            finding = {"audit_id": fixture.audit_id, "target": R("groups", "grp_thm"), "category": "proof_gap",
                "lifecycle": "open", "description": "The final transition is not justified.",
                "evidence_refs": ["anc_thm_proof"], "check_refs": [], "affected_uses": [],
                "impact_reason": "The issue concerns the recorded theorem argument.", "resolution": None}
            fixture.apply(db, [edit("create", "findings", "fnd_open", finding),
                edit("create", "findings", "fnd_resolved", dict(finding, lifecycle="resolved", resolution="Historical correction."))], *fixture.ITEMS)
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            sources.review_sources(db, batch=fixture.batch([edit("create", "source_issues", "sis_formula", {
                "source_id": fixture.source_id, "anchor_id": "anc_thm_proof", "category": "locator_limit",
                "description": "The source formula is unreadable.", "lifecycle": "open", "resolution": None,
                "reviewer": "fixture"})], packet["packet_id"]))
        dataset = self.project(fixture, audit_id=fixture.audit_id)
        detail = dataset["details"]["item:itm_thm"]
        self.assertEqual([ref["id"] for ref in detail["reader"]["finding_refs"]], ["fnd_open"])
        self.assertEqual([ref["id"] for ref in detail["reader"]["source_limit_refs"]], ["sis_formula"])
        self.assertIn("fnd_resolved", [ref["id"] for ref in detail["record_refs"]])

    def test_audit_findings_and_repairs_keep_their_audit_and_lifecycle(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            fixture.apply(db, [edit("create", "audits", "aud_other", dict(audit.body, report_path="reports/other.html"))])
            finding = {"audit_id": fixture.audit_id, "target": R("audits", fixture.audit_id), "category": "presentation",
                "lifecycle": "open", "description": "Notation switches across sections.", "evidence_refs": ["anc_thm"],
                "check_refs": [], "affected_uses": [], "impact_reason": "The notation governs the manuscript.", "resolution": None}
            fixture.apply(db, [edit("create", "findings", "fnd_audit", finding),
                edit("create", "findings", "fnd_other", dict(finding, audit_id="aud_other", target=R("audits", "aud_other"))),
                edit("create", "repairs", "rep_audit", {"finding_id": "fnd_audit", "kind": "source_revision_proposal",
                    "description": "Define the notation before use.", "supported_form": None, "argument_id": None,
                    "added_conditions": [], "evidence_refs": ["anc_lem"]})], mode="primary")
        original = self.project(fixture, audit_id=fixture.audit_id)
        detail = original["details"]["audit:" + fixture.audit_id]
        refs = {ref["id"] for ref in detail["record_refs"]}
        self.assertTrue({"fnd_audit", "rep_audit", "anc_thm", "anc_lem"}.issubset(refs))
        self.assertNotIn("fnd_other", {r["ref"]["id"] for r in original["records"]})
        other = self.project(fixture, audit_id="aud_other")
        self.assertIn("fnd_other", {r["ref"]["id"] for r in other["records"]})
        self.assertNotIn("fnd_audit", {r["ref"]["id"] for r in other["records"]})
        with fixture.open() as db:
            current = db.head("findings", "fnd_audit")
            fixture.apply(db, [edit("replace", "findings", current.id, dict(current.body,
                lifecycle="resolved", resolution="The author defined the notation."), current.version)], mode="primary")
        resolved = self.project(fixture, audit_id=fixture.audit_id)
        self.assertEqual(resolved["summary"]["findings"]["open"], 0)
        self.assertEqual(resolved["summary"]["findings"]["resolved"], 1)
        location = next(row for row in resolved["record_locations"] if row["ref"]["id"] == "fnd_audit")
        self.assertEqual(location["ref"]["version"], 2)
        self.assertEqual(location["detail_key"], "audit:" + fixture.audit_id)
        self.assertIn("rep_audit", {r["id"] for r in resolved["details"][location["detail_key"]]["record_refs"]})

    def test_satisfied_application_keeps_its_pinned_blocking_context_without_changing_assessment(self):
        fixture = blocked_premise_fixture(self.fixture())
        with fixture.open(write=False) as db:
            _, before = assessment.derive_full(db, audit_id=fixture.audit_id)
        dataset = self.project(fixture, audit_id=fixture.audit_id)
        reader = dataset["details"]["item:itm_thm"]["reader"]
        application = reader["applications"][0]
        explanation = application["support_explanation"]
        self.assertEqual(application["assessment"]["local_label"], "supported")
        self.assertEqual(explanation["code"], "scope_unavailable")
        self.assertEqual(explanation["target_ref"]["id"], "itm_lem")
        self.assertEqual(explanation["blocking_scope_ref"]["id"], "scp_supplier")
        self.assertEqual(explanation["active_scope_ref"]["id"], "scp_plain")
        self.assertEqual([row["id"] for row in explanation["path_refs"]], ["use_lem_thm", "itm_lem"])
        task = next(row for row in dataset["worklist"]["tasks"] if row["kind"] == "application")
        self.assertEqual(task["state"], "satisfied")
        self.assertEqual(task["support_explanation"]["message"], explanation["message"])
        self.assertEqual(reader["targets"][0]["support_explanation"]["code"], explanation["code"])
        self.assertEqual(dataset["connections"][0]["applications"][0]["support_explanation"], explanation)
        self.assertEqual(reader["targets"][0]["assessment"], projection.public_assessment(before["assessments"]["items:itm_thm"]))
        self.assertEqual(dataset["summary"]["progress"], before["progress"])

    def test_available_alternative_does_not_inherit_another_routes_blocker(self):
        fixture = blocked_premise_fixture(self.fixture(), alternative=True)
        reader = self.project(fixture, audit_id=fixture.audit_id)["details"]["item:itm_thm"]["reader"]
        self.assertEqual(reader["targets"][0]["assessment"]["availability"], "available")
        self.assertIsNone(reader["targets"][0]["support_explanation"])
        self.assertEqual(reader["applications"][0]["support_explanation"]["code"], "scope_unavailable")

    def test_bounded_and_cyclic_explanations_retain_the_last_requirement(self):
        fixture = cyclic_premise_fixture(self.fixture())
        dataset = self.project(fixture, audit_id=fixture.audit_id)
        for identity in ("itm_lem", "itm_thm"):
            explanation = dataset["details"][f"item:{identity}"]["reader"]["targets"][0]["support_explanation"]
            self.assertEqual(explanation["code"], "explanation_truncated")
            self.assertEqual(explanation["target_ref"], explanation["path_refs"][-1])
        with fixture.open(write=False) as db:
            derivation, _ = assessment.derive_full(db, audit_id=fixture.audit_id)
            explanation = derivation.support_closure.explain(("use", "use_cycle"), limit=10)
        self.assertEqual(explanation["code"], "unfounded_cycle")
        self.assertEqual(explanation["target"], explanation["path"][-1])
