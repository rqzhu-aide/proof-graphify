"""Contract-derived help remains uncommitted, scoped and free of invented judgments."""
import copy
import json
import unittest
from unittest.mock import patch

from support import Fixture, R, TempCase, edit
from paper_core import acceptance, assistance, contract, controller, review
from paper_core.assessment import derive_full
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest


class AssistanceTests(TempCase):
    def test_selected_authoring_shape_includes_required_nulls_without_scientific_defaults(self):
        result = assistance.authoring_template("items", packet_id="pkt_author")
        entry = result["template"]["edits"][0]
        body = entry["body"]
        item_schema = contract.BODY_SCHEMAS["items"]
        self.assertEqual(set(item_schema.fields) - set(item_schema.optional), set(body))
        self.assertIn("proof_idea", result["body_shape"]["optional_fields"])
        self.assertEqual("", body["kind"])
        self.assertEqual("", body["origin"])
        self.assertEqual({"form": "", "text": ""}, body["statement"])
        self.assertIsNone(body["uncertainty"])
        self.assertIsNone(body["owner_id"])
        self.assertIsNone(entry["expected_version"])
        self.assertNotEqual(entry["id"], assistance.authoring_template("items", packet_id="pkt_author")
                            ["template"]["edits"][0]["id"])
        self.assertTrue(contract.validate_body("items", body))
        self.assertEqual([], contract.validate_shape(contract.BATCH, result["template"]))
        self.assertNotIn("reconciliations", str(result["body_shape"]))

    def test_authoring_template_can_be_completed_through_public_acceptance(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            packet = fx.packet(db, f"papers:{fx.paper_id}")
            result = assistance.authoring_template("items", packet_id=packet["packet_id"])
            entry = result["template"]["edits"][0]
            entry["body"] = Fixture.item_edit(entry["id"], "assumption", "Assumption C", "anc_lem", "anc_lem_proof")["body"]
            before = db.max_revision()
            self.assertIsNone(db.head("items", entry["id"]))
            try:
                acceptance.apply_batch(db, result["template"])
            except InvalidRequest as exc:
                self.fail(str(exc.records))
            self.assertGreater(db.max_revision(), before)
            self.assertEqual(entry["body"], db.head("items", entry["id"]).body)

    def test_application_identity_and_nullable_not_optional_are_explicit(self):
        with self.assertRaisesRegex(InvalidRequest, "existing use ID"):
            assistance.authoring_template("application_details", packet_id="pkt_author")
        result = assistance.authoring_template("application_details", packet_id="pkt_author", record_id="use_source")
        entry = result["template"]["edits"][0]
        self.assertEqual(entry["id"], entry["body"]["use_id"])
        self.assertIn("needed_form", entry["body"])
        self.assertIsNone(entry["body"]["needed_form"])
        self.assertNotIn("scope_id", entry["body"])
        self.assertEqual(["scope_id"], result["body_shape"]["optional_fields"])
        self.assertTrue(result["body_shape"]["fields"]["needed_form"]["nullable"])

    def test_worker_guidance_is_role_specific_and_has_no_assignment_dependencies(self):
        with patch("paper_core.assessment.derive_full", side_effect=AssertionError("worker guidance reads no DB")):
            guidance = assistance.worker_guidance("independent")
        self.assertEqual(set(contract.JUDGMENT.fields), set(guidance["judgment_shape"]["fields"]))
        self.assertEqual({"source_anchor_id": "", "description": ""}, guidance["source_target_template"])
        self.assertEqual({kind: list(targets) for kind, targets in contract.CHECK_TARGETS.items()},
                         guidance["canonical_target_collections"])
        self.assertEqual(["arguments"], guidance["canonical_target_collections"]["composition"])
        self.assertEqual(["audits"], guidance["canonical_target_collections"]["adversarial"])
        self.assertEqual({"kind", "target"}, set(guidance["source_target_example"]))
        self.assertNotIn("outcome", str(guidance["source_target_example"]))
        text = canonical_bytes(guidance).decode("utf-8")
        for forbidden in ("draft_refs", "primary_checks", "qualification_id", "assigned_task_ids", "prerequisite_ids"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("row_shape", guidance)
        self.assertNotIn("judgment_shape", assistance.worker_guidance("primary"))
        self.assertEqual(set(contract.BODY_SCHEMAS["reconciliations"].fields),
                         set(assistance.worker_guidance("reconcile")["row_shape"]["fields"]))
        with self.assertRaises(InvalidRequest):
            assistance.worker_guidance("unknown")

    def test_guidance_distinguishes_controller_coverage_and_reconciliation_identity(self):
        guidance = assistance.worker_guidance("primary", composition=True)
        coverage = guidance["response_shape"]["fields"]["coverage"]["array_of"]["fields"]
        self.assertTrue({"check_task_ids", "existing_check_refs", "replaces"}.issubset(coverage))
        self.assertNotIn("check_ids", coverage)
        direct = assistance.authoring_template("coverage", packet_id="pkt_author")
        self.assertIn("check_ids", direct["body_shape"]["fields"])
        self.assertNotIn("replaces", direct["body_shape"]["fields"])
        self.assertIn("direct stored coverage uses check_ids", guidance["coverage_note"])
        self.assertIn("same ID in the submission envelope", assistance.worker_guidance("reconcile")["note"])

    def test_primary_templates_support_mixed_response_with_adverse_finding(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            guidance = prepared["worker_guidance"]
            worker = copy.deepcopy(prepared["scaffold"])
            self.assertEqual([], worker["coverage"])
            self.assertEqual([], worker["findings"])
            self.assertNotIn("task_table", worker)
            for row in worker["results"]:
                if row["type"] == "source_fidelity":
                    row.update(result="matched", note="Compared the stated target with its source.", evidence_refs=["anc_lem"])
                else:
                    row.update(state="complete", outcome="gap", reasoning="Synthetic examination identifies an unsupported base case.",
                               evidence_refs=["anc_lem_proof"])
            derivation = next(t for t in prepared["manifest"]["work"]["tasks"] if t["kind"] == "derivation")
            coverage = copy.deepcopy(guidance["coverage_row_template"])
            finding = copy.deepcopy(guidance["finding_row_template"])
            self.assertEqual("", coverage["classification"])
            self.assertIsNone(coverage["start_offset"])
            self.assertIsNone(coverage["replaces"])
            self.assertEqual("", finding["category"])
            self.assertEqual({"collection": "", "id": ""}, finding["target"])
            self.assertTrue(contract.validate_shape(contract.WORK_COVERAGE, coverage))
            self.assertTrue(contract.validate_shape(contract.WORK_FINDING, finding))
            coverage.update(argument_id="arg_lem", anchor_id="anc_lem_proof", start_offset=0,
                end_offset=len(db.head("anchors", "anc_lem_proof").body["excerpt"]), classification="substantive",
                claim_refs=[R("items", "itm_lem")], check_task_ids=[derivation["id"]], note="Examined the entire written route.")
            finding.update(target=R("groups", "grp_lem"), category="proof_gap", description="The base case is not established.",
                evidence_refs=["anc_lem_proof"], related_task_ids=[derivation["id"]], impact_reason="The induction needs this premise.")
            worker.update(coverage=[coverage], findings=[finding])
            self.assertEqual([], contract.validate_shape(contract.WORK_PRIMARY_RESPONSE, worker))
            envelope = dict(prepared["submission_envelope_template"], reviewer="primary-1")
            result = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
            self.assertEqual("accepted", result["state"], result)
            check_pin = result["record_map"][derivation["id"]]
            self.assertEqual("gap", db.head("checks", check_pin["id"]).body["outcome"])
            saved_finding = db.heads("findings")[0]
            self.assertEqual("proof_gap", saved_finding.body["category"])
            self.assertEqual([check_pin], saved_finding.body["check_refs"])
            self.assertEqual([check_pin["id"]], db.heads("coverage")[0].body["check_ids"])
            self.assertEqual([], guidance["finding_row_template"]["related_task_ids"])

    def test_primary_task_labels_keep_original_pins_after_source_labels_change(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            manifest = prepared["manifest"]
            before = canonical_bytes(manifest)
            table = assistance.primary_task_table(db, manifest)
            self.assertEqual([t["id"] for t in manifest["work"]["tasks"]], [r["task_id"] for r in table])
            self.assertEqual({"source_fidelity", "check"}, {r["result_type"] for r in table})
            labels = {r["target"]["id"]: r["target_label"] for r in table}
            self.assertEqual("Lemma 1", labels["itm_lem"])
            self.assertEqual("groups for Lemma 1", labels["grp_lem"])
            lemma = db.head("items", "itm_lem")
            fx.apply(db, [edit("replace", "items", lemma.id, dict(lemma.body, label="Changed later"), lemma.version)])
            with patch.object(db, "head", side_effect=AssertionError("must not read current labels")):
                self.assertEqual(table, assistance.primary_task_table(db, manifest))
                limited = copy.deepcopy(manifest)
                limited["read_set"] = [p for p in limited["read_set"] if p["id"] != "itm_lem"]
                limited_labels = {r["target"]["id"]: r["target_label"] for r in assistance.primary_task_table(db, limited)}
            self.assertEqual("items:itm_lem", limited_labels["itm_lem"])
            self.assertEqual("groups for items:itm_lem", limited_labels["grp_lem"])
            self.assertEqual(before, canonical_bytes(manifest))

    def test_primary_assignment_help_is_not_available_to_independent_or_reconciliation_roles(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            for mode in ("independent", "reconcile"):
                guidance = assistance.worker_guidance(mode)
                for key in ("task_table", "coverage_row_template", "finding_row_template"):
                    self.assertNotIn(key, guidance)
                manifest = copy.deepcopy(prepared["manifest"])
                manifest["mode"] = mode
                with patch.object(db, "version", side_effect=AssertionError("private data must not be read")):
                    with self.assertRaisesRegex(InvalidRequest, "primary work assignment"):
                        assistance.primary_task_table(db, manifest)
            self.assertNotIn("task_table", assistance.worker_guidance("primary"))

    def test_drafts_keep_distinct_owners_and_intended_predecessors(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            prior = Fixture.check_edit("chk_prior", R("groups", "grp_lem"), "derivation")
            fx.apply(db, [prior], "items:itm_lem", mode="primary")
            predecessor = fx.pin(db, "checks", "chk_prior")
            drafts = [Fixture.check_edit("chk_draft_a", R("groups", "grp_lem"), "derivation",
                       state="draft", reviewer="checker-a", supersedes=predecessor),
                      Fixture.check_edit("chk_draft_b", R("groups", "grp_lem"), "derivation",
                       state="draft", reviewer="checker-b")]
            drafts[0]["body"]["next_action"] = "Finish the induction step."
            drafts[1]["body"]["next_action"] = "Check the base case."
            fx.apply(db, drafts, "items:itm_lem", mode="primary")
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"])
            before = db.max_revision()
            result = assistance.coordinator_guidance(db, prepared["manifest"])
            by_owner = {row["reviewer"]: row for row in result["draft_candidates"]}
            self.assertEqual({"checker-a", "checker-b"}, set(by_owner))
            self.assertEqual(predecessor, by_owner["checker-a"]["supersedes"])
            self.assertIsNone(by_owner["checker-b"]["supersedes"])
            self.assertEqual("Check the base case.", by_owner["checker-b"]["next_action"])
            self.assertEqual(drafts[0]["body"]["reasoning"], by_owner["checker-a"]["reasoning"])
            self.assertEqual(drafts[0]["body"]["conditions"], by_owner["checker-a"]["conditions"])
            self.assertEqual("draft", by_owner["checker-a"]["state"])
            self.assertEqual(before, db.max_revision())
            limited = copy.deepcopy(prepared["manifest"])
            limited["read_set"] = [pin for pin in limited["read_set"] if pin["id"] != "chk_draft_b"]
            self.assertEqual(["checker-a"], [r["reviewer"] for r in assistance.coordinator_guidance(db, limited)["draft_candidates"]])
            # Historical draft pins retain their own prose after the head changes.
            draft = db.head("checks", "chk_draft_a")
            fx.apply(db, [edit("replace", "checks", draft.id,
                dict(draft.body, reasoning="A later draft has different reasoning."), draft.version)], mode="primary")
            historical = assistance.coordinator_guidance(db, prepared["manifest"])
            saved = next(row for row in historical["draft_candidates"] if row["ref"]["id"] == draft.id)
            self.assertEqual(draft.body["reasoning"], saved["reasoning"])

    def test_reconciliation_candidates_are_exact_and_require_an_authored_decision(self):
        fx = self.fixture().independent()
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            assessed = derive_full(db, audit_id=fx.audit_id)
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("reuse assessment")):
                result = assistance.coordinator_guidance(db, prepared["manifest"], assessed=assessed)
            candidate = next(row for row in result["reconciliation_candidates"] if row["target"] == R("arguments", "arg_lem"))
            self.assertTrue(candidate["has_both_roles"])
            self.assertEqual(["chk_comp_lem"], [pin["id"] for pin in candidate["primary_checks"]])
            self.assertEqual([fx.independent_checks["itm_lem"]], [pin["id"] for pin in candidate["independent_checks"]])
            for role in ("primary", "independent"):
                self.assertEqual(candidate[f"{role}_checks"], [op["ref"] for op in candidate[f"{role}_opinions"]])
                for opinion in candidate[f"{role}_opinions"]:
                    pin = opinion["ref"]
                    body = db.version("checks", pin["id"], pin["version"]).body
                    for field in ("state", "outcome", "reasoning", "conditions", "evidence_refs", "reviewer", "supersedes"):
                        self.assertEqual(body[field], opinion[field])
            self.assertTrue(all("row_template" not in entry for entry in result["reconciliation_candidates"]))
            row = result["reconciliation_row_template"]
            self.assertEqual("", row["decision"])
            self.assertEqual("", row["rationale"])
            self.assertEqual([], row["primary_checks"])
            self.assertEqual([], row["independent_checks"])
            self.assertTrue(contract.validate_body("reconciliations", row))
            row.update(target=candidate["target"], primary_checks=candidate["primary_checks"], independent_checks=candidate["independent_checks"],
                       decision="agree", rationale="Compared the exact composition under the same premises.", adjudicator="coordinator")
            review.reconcile(db, batch=fx.batch([edit("create", "reconciliations", "rec_guided", row)], prepared["packet_id"]))
            self.assertEqual(row, db.head("reconciliations", "rec_guided").body)
            with self.assertRaisesRegex(InvalidRequest, "current assessment"):
                assistance.coordinator_guidance(db, prepared["manifest"], assessed=assessed)

    def test_negative_renewal_retains_exact_opinion_and_changed_input_explanation(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            predecessor = fx.pin(db, "checks", "chk_comp_lem")
            negative = Fixture.check_edit("chk_negative", R("arguments", "arg_lem"), "composition",
                outcome="gap", supersedes=predecessor, evidence=["anc_lem_proof"])
            negative["body"].update(reasoning="The written induction omits the base case.",
                                     conditions=["The base case must be proved separately."])
            fx.apply(db, [negative], mode="primary")
            old = db.head("coverage", "cov_lem")
            fx.apply(db, [edit("replace", "coverage", old.id,
                dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            candidate = next(row for row in prepared["coordinator_guidance"]["renewal_candidates"]
                             if row["ref"]["id"] == "chk_negative")
            for field in ("state", "outcome", "reasoning", "conditions", "evidence_refs", "reviewer", "supersedes"):
                self.assertEqual(negative["body"][field], candidate[field])
            self.assertGreater(candidate["recovery"]["changed_count"], 0)
            self.assertTrue(all(row.get("outcome") is None for row in prepared["scaffold"]["results"]))
            self.assertNotIn(negative["body"]["reasoning"], str(prepared["worker_guidance"]))

    def test_conflicting_reconciliation_opinions_do_not_choose_a_decision(self):
        fx = self.fixture().independent()
        with fx.open() as db:
            negative = Fixture.check_edit("chk_disagreement", R("arguments", "arg_lem"), "composition",
                outcome="gap", supersedes=fx.pin(db, "checks", "chk_comp_lem"))
            negative["body"].update(reasoning="The induction step still lacks its base case.",
                                     conditions=["A valid base case is needed."])
            fx.apply(db, [negative], mode="primary")
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            guidance = prepared["coordinator_guidance"]
            candidate = next(row for row in guidance["reconciliation_candidates"] if row["target"] == R("arguments", "arg_lem"))
            self.assertTrue(candidate["has_both_roles"])
            self.assertEqual("gap", candidate["primary_opinions"][0]["outcome"])
            self.assertEqual(negative["body"]["conditions"], candidate["primary_opinions"][0]["conditions"])
            self.assertEqual("supported", candidate["independent_opinions"][0]["outcome"])
            self.assertEqual("", guidance["reconciliation_row_template"]["decision"])
            self.assertEqual("", guidance["reconciliation_row_template"]["rationale"])
            self.assertEqual([], prepared["scaffold"]["edits"])

    def test_primary_renewal_candidates_are_assigned_readable_and_currently_stale(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            old = db.head("coverage", "cov_lem")
            fx.apply(db, [edit("replace", "coverage", old.id,
                dict(old.body, end_offset=old.body["end_offset"] - 1), old.version)], mode="primary")
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            assessed = derive_full(db, audit_id=fx.audit_id)
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("reuse assessment")):
                result = assistance.coordinator_guidance(db, prepared["manifest"], assessed=assessed)
            candidates = result["renewal_candidates"]
            self.assertEqual([fx.pin(db, "checks", "chk_comp_lem")], [c["ref"] for c in candidates])
            self.assertEqual("primary-1", candidates[0]["reviewer"])
            self.assertEqual(prepared["assigned_task_ids"], [c["task_id"] for c in candidates])
            self.assertNotIn("renewal_candidates", prepared["worker_guidance"])
            self.assertTrue(all(r.get("supersedes") is None for r in prepared["scaffold"]["results"]))

            limited = copy.deepcopy(prepared["manifest"])
            limited["read_set"].remove(candidates[0]["ref"])
            self.assertNotIn("renewal_candidates", assistance.coordinator_guidance(db, limited, assessed=assessed))
            unrelated = copy.deepcopy(prepared["manifest"])
            unrelated["work"]["tasks"][0]["target"] = R("arguments", "arg_thm")
            self.assertNotIn("renewal_candidates", assistance.coordinator_guidance(db, unrelated, assessed=assessed))

            # Inspecting an old packet after an explicit successor must not offer
            # its superseded predecessor as though renewal were still needed.
            fx.apply(db, [Fixture.check_edit("chk_renewed", R("arguments", "arg_lem"), "composition",
                supersedes=candidates[0]["ref"])], mode="primary")
            inspected = controller.inspect_work(db, packet_id=prepared["packet_id"])
            self.assertNotIn("renewal_candidates", inspected["coordinator_guidance"])
            with self.assertRaisesRegex(InvalidRequest, "current assessment"):
                assistance.coordinator_guidance(db, prepared["manifest"], assessed=assessed)

    def test_normal_and_independent_guidance_add_no_renewal_inventory(self):
        fx = self.fixture().audit(independent_required=False)
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("no extra assessment")):
                normal = assistance.coordinator_guidance(db, prepared["manifest"])
            self.assertNotIn("renewal_candidates", normal)
            self.assertNotIn("renewal_note", normal)
            hidden = copy.deepcopy(prepared["manifest"])
            hidden["mode"] = "independent"
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("independent remains blind")):
                self.assertNotIn("renewal_candidates", assistance.coordinator_guidance(db, hidden))

    def test_changed_target_offers_historical_check_for_explicit_renewal(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            group = db.head("groups", "grp_lem")
            fx.apply(db, [edit("replace", "groups", group.id,
                dict(group.body, rationale="Revised explanation of the elementary estimate."), group.version)])
            _, assessed = derive_full(db, audit_id=fx.audit_id)
            self.assertEqual("historical", assessed["judgments"]["checks:chk_der_lem"]["freshness"])
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            candidates = {row["task_id"]: row for row in prepared["coordinator_guidance"]["renewal_candidates"]}
            self.assertIn(fx.pin(db, "checks", "chk_der_lem"), [c["ref"] for c in candidates.values()])
            worker = copy.deepcopy(prepared["scaffold"])
            for row in worker["results"]:
                row.update(state="complete", outcome="supported", evidence_refs=["anc_lem_proof"],
                           reasoning="Re-examined the changed local inference and its composition.",
                           supersedes=candidates[row["task_id"]]["ref"])
            envelope = {"contract_version": 4, "request_id": fx.request_id(), "packet_id": prepared["packet_id"],
                "rebase_packet_id": None, "reviewer": "primary-1", "qualification_id": None,
                "exposure": None, "exposure_note": ""}
            result = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
            self.assertEqual("accepted", result["state"], result)
            self.assertEqual([], result["remaining_task_ids"])

    def test_mapping_template_keeps_source_and_authorization_packets_distinct(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            source = fx.packet(db, "items:itm_lem", mode="independent")
            judgment = copy.deepcopy(assistance.worker_guidance("independent")["source_target_example"])
            judgment["target"].update(source_anchor_id="anc_lem_proof", description="Lemma proof composition")
            judgment.update(state="complete", outcome="supported",
                            reasoning="Induction establishes the claimed uniform bound.", evidence_refs=["anc_lem_proof"],
                            conditions=[], next_action=None, supersedes=None)
            worker = {"packet_id": source["packet_id"], "covered_targets": [R("items", "itm_lem")],
                      "coverage_note": "Examined the entire lemma proof.", "exposure_report": {"status": "none_known", "note": ""},
                      "judgments": [judgment]}
            raw = canonical_bytes(worker)
            submitted = review.submit_review(db, submission={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": source["packet_id"], "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": ""}, response_bytes=raw)
            self.assertEqual("needs_revision", submitted["state"])
            packet = fx.packet(db, "items:itm_lem", mode="primary")
            result = assistance.mapping_template(source_packet_id=source["packet_id"], mapping_packet_id=packet["packet_id"],
                response_id=submitted["response_id"], judgment_indexes=[0])
            mapping = result["template"]
            self.assertEqual(packet["packet_id"], mapping["packet_id"])
            self.assertNotEqual(result["source_packet_id"], mapping["packet_id"])
            self.assertEqual("", mapping["entries"][0]["rationale"])
            mapping["reviewer"] = "coordinator"
            mapping["entries"][0].update(target=R("arguments", "arg_lem"), rationale="The reviewed source passage is this exact argument.")
            mapped = review.map_response(db, mapping=mapping)
            self.assertEqual("accepted", mapped["state"])
            response = db.head("responses", submitted["response_id"])
            self.assertEqual(raw, db.get_blob(response.body["original_blob"]))
            with self.assertRaises(InvalidRequest):
                assistance.mapping_template(source_packet_id=source["packet_id"], mapping_packet_id=packet["packet_id"],
                    response_id=submitted["response_id"], judgment_indexes=[0, 0])

    def test_guided_route_and_local_opinions_survive_mapping_for_exact_reconciliation(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            source = fx.packet(db, "items:itm_lem", mode="independent")
            example = assistance.worker_guidance("independent")["source_target_example"]
            judgments = []
            for kind, description, outcome, reasoning in (
                ("composition", "The complete written induction route for the lemma", "gap",
                 "The base case and induction step were examined together. The route omits the base "
                 "condition and therefore does not establish the claimed uniform bound."),
                ("derivation", "The induction base in the lemma proof", "refuted",
                 "The unrestricted base value may be a_1 = 2, contradicting a_1 <= 1. "
                 "This counterexample must survive any correction of the route."),
            ):
                judgment = copy.deepcopy(example)
                judgment["target"].update(source_anchor_id="anc_lem_proof", description=description)
                judgment.update(kind=kind, state="complete", outcome=outcome, reasoning=reasoning,
                                evidence_refs=["anc_lem_proof"], conditions=[], next_action=None, supersedes=None)
                judgments.append(judgment)
            worker = {"packet_id": source["packet_id"], "covered_targets": [R("items", "itm_lem")],
                      "coverage_note": judgments[1]["reasoning"],
                      "exposure_report": {"status": "none_known", "note": ""}, "judgments": judgments}
            raw = canonical_bytes(worker)
            submitted = review.submit_review(db, submission={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": source["packet_id"], "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": ""}, response_bytes=raw)
            self.assertEqual("needs_revision", submitted["state"])
            saved_checks = []
            for index, target in enumerate((R("arguments", "arg_lem"), R("groups", "grp_lem"))):
                packet = fx.packet(db, "items:itm_lem", mode="primary")
                mapping = assistance.mapping_template(source_packet_id=source["packet_id"],
                    mapping_packet_id=packet["packet_id"], response_id=submitted["response_id"],
                    judgment_indexes=[index])["template"]
                mapping["reviewer"] = "coordinator"
                mapping["entries"][0].update(target=target, rationale="This exact inference occupies the reviewed proof passage.")
                mapped = review.map_response(db, mapping=mapping)
                self.assertEqual("needs_revision" if index == 0 else "accepted", mapped["state"])
                check = db.head("checks", mapped["checks"][0]["check_id"])
                self.assertEqual(target, check.body["target"])
                for field in ("kind", "outcome", "reasoning", "evidence_refs"):
                    self.assertEqual(judgments[index][field], check.body[field])
                saved_checks.append(check.id)
            response = db.head("responses", submitted["response_id"])
            self.assertEqual(raw, db.get_blob(response.body["original_blob"]))
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            guidance = prepared["coordinator_guidance"]
            candidates = {row["target"]["id"]: row for row in guidance["reconciliation_candidates"]}
            for target, check_id in zip(("arg_lem", "grp_lem"), saved_checks):
                row = candidates[target]
                self.assertEqual([check_id], [pin["id"] for pin in row["independent_checks"]])
                self.assertEqual(db.head("checks", check_id).body["reasoning"], row["independent_opinions"][0]["reasoning"])
            self.assertNotIn("arg_thm", candidates)
            self.assertEqual("", guidance["reconciliation_row_template"]["decision"])

    def test_compromised_opinion_is_not_offered_as_eligible_independent_evidence(self):
        fx = self.fixture().independent()
        with fx.open() as db:
            good_check = db.head("checks", fx.independent_checks["itm_lem"])
            good_response = db.head("responses", good_check.body["response_id"])
            worker = json.loads(db.get_blob(good_response.body["original_blob"]))
            packet = fx.packet(db, "items:itm_lem", mode="independent")
            worker["packet_id"] = packet["packet_id"]
            worker["exposure_report"] = {"status": "possible_exposure", "note": "Primary reasoning was visible."}
            submitted = review.submit_review(db, submission={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": packet["packet_id"], "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "compromised", "exposure_note": "Primary reasoning was visible."},
                response_bytes=canonical_bytes(worker))
            mapping_packet = fx.packet(db, "items:itm_lem", mode="primary")
            mapping = assistance.mapping_template(source_packet_id=packet["packet_id"], mapping_packet_id=mapping_packet["packet_id"],
                response_id=submitted["response_id"], judgment_indexes=[0])["template"]
            mapping["reviewer"] = "coordinator"
            mapping["entries"][0].update(target=R("arguments", "arg_lem"), rationale="Same source proof, with compromised exposure retained.")
            mapped = review.map_response(db, mapping=mapping)
            self.assertEqual("accepted", mapped["state"])
            bad_id = mapped["checks"][0]["check_id"]
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            guidance = assistance.coordinator_guidance(db, prepared["manifest"])
            eligible = [pin["id"] for row in guidance["reconciliation_candidates"] for pin in row["independent_checks"]]
            self.assertIn(good_check.id, eligible)
            self.assertNotIn(bad_id, eligible)
            recorded = [entry["ref"]["id"] for row in guidance["reconciliation_candidates"]
                        for entry in row["required_other_opinions"]]
            self.assertIn(bad_id, recorded)

    def test_revised_opinion_guidance_keeps_readable_history_separate_from_current_support(self):
        fx = self.fixture().independent()
        with fx.open() as db:
            prior = db.head("checks", fx.independent_checks["itm_lem"])
            original = db.head("responses", prior.body["response_id"])
            worker = json.loads(db.get_blob(original.body["original_blob"]))
            packet = fx.packet(db, "items:itm_lem", mode="independent")
            worker["packet_id"] = packet["packet_id"]
            worker["judgments"][0].update(supersedes=prior.pinned, reasoning="Explicitly renewed synthetic examination of the same proof.")
            submitted = review.submit_review(db, submission={"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": packet["packet_id"], "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": "Synthetic same-reviewer continuation."}, response_bytes=canonical_bytes(worker))
            authority = fx.packet(db, "items:itm_lem", mode="reconcile")
            mapping = assistance.mapping_template(source_packet_id=packet["packet_id"], mapping_packet_id=authority["packet_id"],
                response_id=submitted["response_id"], judgment_indexes=[0])["template"]
            mapping["reviewer"] = "coordinator"
            mapping["entries"][0].update(target=R("arguments", "arg_lem"), rationale="The renewed source judgment examines this exact argument.")
            mapped = review.map_response(db, mapping=mapping)
            successor = db.head("checks", mapped["checks"][0]["check_id"])
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            assessed = derive_full(db, audit_id=fx.audit_id)
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("reuse existing snapshot")):
                guidance = assistance.coordinator_guidance(db, prepared["manifest"], assessed=assessed)
            candidate = next(row for row in guidance["reconciliation_candidates"] if row["target"] == prior.body["target"])
            self.assertEqual([successor.pinned], candidate["independent_checks"])
            self.assertEqual([prior.pinned], [entry["ref"] for entry in candidate["required_other_opinions"]])
            self.assertTrue(candidate["required_other_opinions"][0]["superseded"])
            self.assertEqual(prior.body["reasoning"], candidate["required_other_opinions"][0]["reasoning"])
            self.assertIn(prior.pinned, prepared["manifest"]["read_set"])
            self.assertNotIn("missing_required_opinion_count", candidate)
            limited = copy.deepcopy(prepared["manifest"])
            limited["read_set"].remove(prior.pinned)
            limited_guidance = assistance.coordinator_guidance(db, limited, assessed=assessed)
            limited_row = next(row for row in limited_guidance["reconciliation_candidates"] if row["target"] == prior.body["target"])
            self.assertEqual([], limited_row["required_other_opinions"])
            self.assertEqual(1, limited_row["missing_required_opinion_count"])
            # Current eligible pins alone omit an opinion required by validation.
            row = copy.deepcopy(guidance["reconciliation_row_template"])
            row.update(target=candidate["target"], primary_checks=candidate["primary_checks"],
                independent_checks=candidate["independent_checks"], decision="independent_revised",
                successor_checks=[successor.pinned], rationale="The explicit successor replaces the earlier opinion.", adjudicator="coordinator")
            with self.assertRaises(InvalidRequest) as error:
                review.reconcile(db, batch=fx.batch([edit("create", "reconciliations", "rec_history", row)], prepared["packet_id"]))
            self.assertIn(prior.id, str(error.exception.records))
            row["independent_checks"] += [entry["ref"] for entry in candidate["required_other_opinions"]]
            review.reconcile(db, batch=fx.batch([edit("create", "reconciliations", "rec_history", row)], prepared["packet_id"]))
            self.assertEqual("independent_revised", db.head("reconciliations", "rec_history").body["decision"])


if __name__ == "__main__":
    unittest.main()
