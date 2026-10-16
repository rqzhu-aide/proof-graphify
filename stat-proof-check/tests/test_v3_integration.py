"""Integrate saved unit/member opinions without another examination."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from support import R, TempCase, edit
from paper_core import assessment, assistance, controller, finalization, review, stage2
from paper_core.errors import InvalidRequest
from paper_core.work import derive_work


class CoherentIntegrationTests(TempCase):
    def prepared_fixture(self, primary="supported", name="paper", conditions=()):
        fixture = self.fixture(name).audit()
        with fixture.open() as db:
            checks = [fixture.check_edit(f"chk_comp_{name}", R("arguments", f"arg_{name}"),
                "composition", outcome=primary if name == "thm" else "supported",
                evidence=[f"anc_{name}_proof"]) for name in ("lem", "thm")]
            checks[1]["body"]["conditions"] = list(conditions)
            fixture.apply(db, checks, *fixture.ITEMS, mode="primary")
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            review.compare(db, batch=fixture.batch([edit("create", "observations", f"obs_{name}", {
                "target": R("items", f"itm_{name}"), "result": "matched", "reviewer": "primary",
                "note": "Exact source statement compared.", "evidence_refs": [f"anc_{name}"]})
                for name in ("lem", "thm")], packet["packet_id"]))
        return fixture

    def submit(self, db, fixture, prepared, response, *, independent=False):
        envelope = {"contract_version": 4, "request_id": fixture.request_id(),
            "packet_id": prepared["packet_id"], "rebase_packet_id": None,
            "reviewer": "separate reviewer" if independent else "coordinator", "qualification_id": None,
            "exposure": "source_only" if independent else None, "exposure_note": ""}
        result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
            response_bytes=json.dumps(response).encode())
        self.assertEqual("accepted", result["state"], result)
        return result

    def examine(self, db, fixture, outcome="supported", member=None):
        originals = []
        for name in ("lem", "thm"):
            prep = stage2.prepare(db, audit_id=fixture.audit_id, focus=R("items", f"itm_{name}"))
            response = prep["scaffold"]
            for row in response["judgments"]:
                row.update(state="complete", outcome=outcome if name == "thm" else "supported",
                           reasoning="Synthetic whole-unit source examination.")
            if member and name == "thm":
                collection, identity, kind, local_outcome = member
                response["judgments"].append({"target": {"source_anchor_id": "anc_thm_proof",
                    "description": "The distinct located local inference in this proof."}, "kind": kind,
                    "state": "complete", "outcome": local_outcome, "reasoning": "Synthetic distinct local judgment.",
                    "evidence_refs": ["anc_thm_proof"], "conditions": [], "next_action": None, "supersedes": None})
            result = self.submit(db, fixture, prep, response, independent=True)
            if member and name == "thm":
                packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
                review.map_response(db, mapping={"contract_version": 4, "request_id": fixture.request_id(),
                    "packet_id": packet["packet_id"], "response_id": result["response_id"],
                    "entries": [{"judgment_index": 1, "target": R(collection, identity),
                                 "rationale": "This existing local target is the source-located judgment."}],
                    "reviewer": "coordinator"})
            stored = db.head("responses", result["response_id"])
            originals.append((stored.pinned, deepcopy(stored.body), db.get_blob(stored.body["original_blob"])))
        return originals

    def integrate(self, db, fixture, decision="agree"):
        for _ in range(3):
            prep = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile")
            if not prep["prepared"]:
                return
            for row in prep["scaffold"]["integrations"]:
                task = next(t for t in prep["manifest"]["work"]["tasks"] if t["id"] == row["task_id"])
                row.update(decision=decision if task["target"] == R("arguments", "arg_thm") else "agree",
                    rationale="Compared the saved reasoning and adopted the stated conclusion; retain distinct local concerns.")
            self.submit(db, fixture, prep, prep["scaffold"])
        self.fail("integration repeated already performed work")

    def adoption(self, primary, independent, decision, expected):
        fixture = self.prepared_fixture(primary)
        with fixture.open() as db:
            originals = self.examine(db, fixture, independent)
            count = len(db.heads("checks"))
            self.integrate(db, fixture, decision)
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(result["progress"]["process_complete"])
            self.assertEqual(expected, result["assessments"]["items:itm_thm"]["label"])
            self.assertEqual(expected, result["assessments"]["arguments:arg_thm"]["label"])
            self.assertEqual("available" if expected == "supported" else "unavailable",
                             result["support"]["items:itm_thm"])
            self.assertEqual(count, len(db.heads("checks")))
            self.assertEqual(primary, db.head("checks", "chk_comp_thm").body["outcome"])
            rec = self.current_comparison(db)
            canonical = {"adopt_independent": "primary_revised", "adopt_primary": "independent_revised"}.get(decision, decision)
            self.assertEqual(canonical, rec.body["decision"])
            role = "independent" if canonical == "primary_revised" else "primary"
            self.assertTrue(rec.body["successor_checks"])
            self.assertTrue(all(db.version("checks", pin["id"], pin["version"]).body["role"] == role
                                for pin in rec.body["successor_checks"]))
            for pin, body, raw in originals:
                self.assertEqual(pin, db.head("responses", pin["id"]).pinned)
                self.assertEqual(body, db.head("responses", pin["id"]).body)
                self.assertEqual(raw, db.get_blob(body["original_blob"]))
            frozen = finalization.finalize_audit(db, audit_id=fixture.audit_id, output=self.path("frozen"))
            self.assertEqual("release", frozen["kind"])

    @staticmethod
    def current_comparison(db):
        return max((row for row in db.heads("reconciliations")
                    if row.body["target"] == R("arguments", "arg_thm")),
                   key=lambda row: (row.revision, row.id))

    @staticmethod
    def saved_records(db):
        return {collection: {row.id: (row.pinned, deepcopy(row.body),
                    db.get_blob(row.body["original_blob"]) if collection == "responses" else None)
                for row in db.heads(collection)}
                for collection in ("checks", "responses", "reconciliations", "findings")}

    def test_integration_task_mapping_preserves_native_opinions_and_unauthored_scaffold(self):
        conditions = ["The closing argument requires an additional restriction."]
        fixture = self.prepared_fixture(conditions=conditions)
        with fixture.open() as db:
            for name in ("lem", "thm"):
                prepared = stage2.prepare(db, audit_id=fixture.audit_id, focus=R("items", f"itm_{name}"))
                response = deepcopy(prepared["scaffold"])
                for row in response["judgments"]:
                    row.update(state="complete", outcome="gap" if name == "thm" else "supported",
                               reasoning="The saved source examination identifies its stated conclusion.")
                if name == "thm":
                    response["coverage_note"] = "Retain both distinct local premise concerns."
                    for description in ("The located joint inference.", "A separate unassigned premise."):
                        response["judgments"].append({"target": {"source_anchor_id": "anc_thm_proof",
                            "description": description}, "kind": "derivation", "state": "complete",
                            "outcome": "gap", "reasoning": description, "evidence_refs": ["anc_thm_proof"],
                            "conditions": ["This premise has not been established."], "next_action": None,
                            "supersedes": None})
                accepted = self.submit(db, fixture, prepared, response, independent=True)
                if name == "thm":
                    mapping_packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
                    review.map_response(db, mapping={"contract_version": 4, "request_id": fixture.request_id(),
                        "packet_id": mapping_packet["packet_id"], "response_id": accepted["response_id"],
                        "entries": [{"judgment_index": 1, "target": R("groups", "grp_thm"),
                                     "rationale": "This is the located joint inference."}], "reviewer": "coordinator"})
            saved, revision = self.saved_records(db), db.max_revision()
            prepared = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile",
                                      focus=R("items", "itm_thm"), allow_provisional=True)
            self.assertTrue(prepared["prepared"], prepared)
            native_guidance = assistance.coordinator_guidance(db, prepared["manifest"])
            candidates = prepared["coordinator_guidance"]["reconciliation_candidates"]
            self.assertEqual(native_guidance["reconciliation_candidates"],
                [{key: value for key, value in candidate.items() if key != "integration_task_ids"}
                 for candidate in candidates])
            tasks = {task["id"]: task for task in prepared["manifest"]["work"]["tasks"]}
            mapped_ids = [task_id for candidate in candidates for task_id in candidate.get("integration_task_ids", [])]
            self.assertCountEqual(tasks, mapped_ids)
            self.assertEqual(len(tasks), len(mapped_ids))
            native_scaffold = controller.response_scaffold(prepared["manifest"])
            for row in prepared["scaffold"]["integrations"]:
                matches = [candidate for candidate in candidates if row["task_id"] in candidate.get("integration_task_ids", [])]
                self.assertEqual(1, len(matches))
                self.assertEqual(tasks[row["task_id"]]["target"], matches[0]["target"])
                self.assertEqual("unresolved", row["decision"])
                self.assertEqual("", row["rationale"])
                self.assertTrue(all(disposition["rationale"] == "" for disposition in row.get("response_dispositions", [])))
            self.assertEqual(native_scaffold,
                dict(prepared["scaffold"], integrations=[{key: value for key, value in row.items()
                    if key != "response_dispositions"} for row in prepared["scaffold"]["integrations"]]))
            unit = next(candidate for candidate in candidates if candidate["target"] == R("arguments", "arg_thm"))
            self.assertEqual(conditions, unit["primary_opinions"][0]["conditions"])
            self.assertEqual("gap", unit["independent_opinions"][0]["outcome"])
            member = next(candidate for candidate in candidates if candidate["target"] == R("groups", "grp_thm"))
            self.assertFalse(member.get("integration_task_ids"))
            self.assertEqual("gap", member["independent_opinions"][0]["outcome"])
            self.assertEqual(member["independent_opinions"][0]["ref"], unit["required_other_opinions"][0]["ref"])
            self.assertTrue(unit["retained_concerns"])
            self.assertEqual([2], unit["retained_concerns"][0]["pending_judgments"])
            integration = next(row for row in prepared["scaffold"]["integrations"]
                               if row["task_id"] in unit["integration_task_ids"])
            self.assertEqual([{"response_id": accepted["response_id"], "judgment_indexes": [2], "rationale": ""}],
                             integration["response_dispositions"])
            exported = controller.write_artifacts(db, prepared, self.path("mapping-export"))
            self.assertEqual(prepared["coordinator_guidance"],
                json.loads(Path(exported["coordinator-guidance.json"]["path"]).read_text(encoding="utf-8")))
            self.assertEqual(prepared["scaffold"],
                json.loads(Path(exported["response-scaffold.json"]["path"]).read_text(encoding="utf-8")))
            self.assertEqual(saved, self.saved_records(db))
            self.assertEqual(revision, db.max_revision())

    def test_missing_or_ambiguous_integration_mapping_stops_before_export_and_keeps_saved_work(self):
        for count in (0, 2):
            with self.subTest(candidate_count=count):
                fixture = self.prepared_fixture(name=f"mapping-{count}")
                with fixture.open() as db:
                    self.examine(db, fixture, "gap")
                    saved, revision = self.saved_records(db), db.max_revision()
                    packets_before = {row["packet_id"] for row in db.conn.execute("SELECT packet_id FROM packets")}
                    native_guidance = assistance.coordinator_guidance
                    target = R("arguments", "arg_thm")
                    captured = {}

                    def broken_guidance(database, manifest, **kwargs):
                        guidance = native_guidance(database, manifest, **kwargs)
                        candidate = next(entry for entry in guidance["reconciliation_candidates"] if entry["target"] == target)
                        guidance["reconciliation_candidates"] = [entry for entry in guidance["reconciliation_candidates"]
                                                                  if entry["target"] != target]
                        guidance["reconciliation_candidates"].extend(deepcopy(candidate) for _ in range(count))
                        captured.update(packet_id=manifest["packet_id"], task_id=next(task["id"]
                            for task in manifest["work"]["tasks"] if task["target"] == target))
                        return guidance

                    output = self.path(f"mapping-error-{count}")
                    with patch.object(assistance, "coordinator_guidance", side_effect=broken_guidance), \
                            patch.object(controller, "write_artifacts", wraps=controller.write_artifacts) as writer:
                        with self.assertRaises(InvalidRequest) as caught:
                            prepared = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
                            controller.write_artifacts(db, prepared, output)
                    self.assertEqual("ASSISTANCE_MAPPING", caught.exception.code)
                    self.assertIn(captured["packet_id"], caught.exception.message)
                    self.assertIn(captured["task_id"], caught.exception.message)
                    self.assertIn(f"found {count}", caught.exception.message)
                    self.assertIn(target, caught.exception.records)
                    writer.assert_not_called()
                    self.assertFalse(output.exists())
                    packets_after = {row["packet_id"] for row in db.conn.execute("SELECT packet_id FROM packets")}
                    self.assertEqual({captured["packet_id"]}, packets_after - packets_before)
                    packet = db.packet(captured["packet_id"])
                    self.assertIsNotNone(db.get_blob(packet["payload_sha256"]))
                    self.assertEqual(saved, self.saved_records(db))
                    self.assertEqual(revision, db.max_revision())

    def test_mapping_shape_allows_shared_candidate_without_copying_its_science(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.examine(db, fixture, "gap")
            prepared = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
            # Only the assistance shape is under test; this extra task is not a native assignment.
            synthetic = deepcopy(prepared)
            task = synthetic["manifest"]["work"]["tasks"][0]
            other_task = dict(task, id=task["id"] + "_second")
            synthetic["manifest"]["work"]["tasks"].append(other_task)
            native_guidance = assistance.coordinator_guidance(db, prepared["manifest"])
            candidate = next(entry for entry in native_guidance["reconciliation_candidates"] if entry["target"] == task["target"])
            # Similar IDs in another collection or with a longer suffix must not redirect the exact target.
            decoys = [dict(deepcopy(candidate), target=R("items", task["target"]["id"])),
                      dict(deepcopy(candidate), target=R("arguments", task["target"]["id"] + "_similar"))]
            native_guidance["reconciliation_candidates"] = decoys + native_guidance["reconciliation_candidates"]
            with patch.object(assistance, "coordinator_guidance", return_value=deepcopy(native_guidance)):
                result = controller._assignment_assistance(db, synthetic)
            candidates = result["coordinator_guidance"]["reconciliation_candidates"]
            exact = next(entry for entry in candidates if entry["target"] == task["target"])
            self.assertEqual([task["id"], other_task["id"]], exact["integration_task_ids"])
            self.assertEqual(candidate, {key: value for key, value in exact.items() if key != "integration_task_ids"})
            self.assertFalse(any(entry.get("integration_task_ids") for entry in candidates[:2]))
            self.assertEqual(native_guidance["reconciliation_candidates"],
                [{key: value for key, value in entry.items() if key != "integration_task_ids"} for entry in candidates])
            self.assertTrue(all(row["decision"] == "unresolved" and row["rationale"] == ""
                                for row in result["scaffold"]["integrations"]))

    def test_adopt_independent_alias_selects_gap_and_stores_canonical_decision(self):
        self.adoption("supported", "gap", "adopt_independent", "defect")

    def test_adopt_independent_alias_selects_support_and_stores_canonical_decision(self):
        self.adoption("gap", "supported", "adopt_independent", "supported")

    def test_adopt_primary_alias_selects_gap_and_stores_canonical_decision(self):
        self.adoption("gap", "supported", "adopt_primary", "defect")

    def test_adopt_primary_alias_selects_support_and_stores_canonical_decision(self):
        self.adoption("supported", "gap", "adopt_primary", "supported")

    def test_adoption_aliases_accept_omitted_successor_checks(self):
        for decision, canonical, expected in (("adopt_independent", "primary_revised", "supported"),
                                               ("adopt_primary", "independent_revised", "defect")):
            with self.subTest(decision=decision):
                fixture = self.prepared_fixture("gap", name=decision)
                with fixture.open() as db:
                    self.examine(db, fixture)
                    prep = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
                    for row in prep["scaffold"]["integrations"]:
                        row.update(decision=decision, rationale="Adopt the selected saved whole-unit examination.")
                        row.pop("successor_checks", None)
                    self.submit(db, fixture, prep, prep["scaffold"])
                    self.integrate(db, fixture)
                    self.assertEqual(canonical, self.current_comparison(db).body["decision"])
                    result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
                    self.assertEqual(expected, result["assessments"]["items:itm_thm"]["label"])
                    self.assertTrue(result["progress"]["process_complete"])

    def test_alias_corrections_preserve_checks_response_bytes_history_and_open_concerns(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "findings", "fnd_open", {"audit_id": fixture.audit_id,
                "target": R("arguments", "arg_thm"), "category": "proof_gap",
                "description": "A distinct unresolved premise concern.",
                "evidence_refs": ["anc_thm_proof"], "check_refs": [], "affected_uses": [],
                "impact_reason": "The inference still requires this premise.", "lifecycle": "open",
                "resolution": None})], *fixture.ITEMS, mode="primary")
            self.examine(db, fixture, "gap", member=("groups", "grp_thm", "derivation", "inconclusive"))
            self.integrate(db, fixture, "independent_revised")
            original = self.saved_records(db)
            task_id = next(task["id"] for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]
                           if task["role"] == "coordinator" and task["target"] == R("arguments", "arg_thm"))
            for decision, canonical, role, outcome in (("adopt_independent", "primary_revised", "independent", "gap"),
                                                        ("adopt_primary", "independent_revised", "primary", "supported")):
                with self.subTest(decision=decision):
                    previous = self.current_comparison(db)
                    history = self.saved_records(db)["reconciliations"]
                    intakes = {row["request_id"]: db.work_submission(row["request_id"])
                               for row in db.work_submissions(audit_id=fixture.audit_id)}
                    original_bytes = {identity: (db.get_blob(row["envelope_sha256"]), db.get_blob(row["response_sha256"]))
                                      for identity, row in intakes.items()}
                    prep = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", task_ids=[task_id], correct=True)
                    self.assertTrue(prep["prepared"], prep)
                    for row in prep["scaffold"]["integrations"]:
                        row.update(decision=decision, rationale="Correct the saved selection and preserve all distinct concerns.")
                    accepted = self.submit(db, fixture, prep, prep["scaffold"])
                    intake = db.work_submission(accepted["request_id"])
                    self.assertEqual(json.dumps(prep["scaffold"]).encode(), db.get_blob(intake["response_sha256"]))
                    for identity, stored in intakes.items():
                        self.assertEqual(stored, db.work_submission(identity))
                        self.assertEqual(original_bytes[identity],
                            (db.get_blob(stored["envelope_sha256"]), db.get_blob(stored["response_sha256"])))
                    current = self.current_comparison(db)
                    self.assertEqual(previous.pinned, current.body["supersedes"])
                    self.assertEqual(canonical, current.body["decision"])
                    selected = [db.version("checks", pin["id"], pin["version"]).body
                                for pin in current.body["successor_checks"]]
                    self.assertTrue(selected)
                    self.assertTrue(all(check["role"] == role and check["outcome"] == outcome for check in selected))
                    saved = self.saved_records(db)
                    for collection in ("checks", "responses", "findings"):
                        self.assertEqual(original[collection], saved[collection])
                    for identity, record in history.items():
                        self.assertEqual(record, saved["reconciliations"][identity])
                    self.assertEqual(len(history) + 1, len(saved["reconciliations"]))
                    self.assertEqual("open", db.head("findings", "fnd_open").body["lifecycle"])
                    result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
                    self.assertTrue(result["progress"]["process_complete"])
                    self.assertNotEqual("available", result["support"]["items:itm_thm"])
                    self.assertNotEqual("green", result["assessments"]["groups:grp_thm"]["state"])

    def test_aliases_reject_nonempty_successors_without_scientific_commit(self):
        for decision in ("adopt_independent", "adopt_primary"):
            with self.subTest(decision=decision):
                fixture = self.prepared_fixture(name=decision)
                with fixture.open() as db:
                    self.examine(db, fixture, "gap")
                    prep = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
                    checks = {check.body["role"]: check.pinned for check in db.heads("checks")
                              if check.body["target"] == R("arguments", "arg_thm")}
                    saved, revision = self.saved_records(db), db.max_revision()
                    for role in ("primary", "independent"):
                        with self.subTest(pin_role=role):
                            response = deepcopy(prep["scaffold"])
                            for row in response["integrations"]:
                                row.update(decision=decision, rationale="Adopt the saved examination.", successor_checks=[checks[role]])
                            envelope = dict(prep["submission_envelope_template"], request_id=fixture.request_id(), reviewer="coordinator")
                            result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                                            response_bytes=json.dumps(response).encode())
                            self.assertEqual("needs_revision", result["state"], result)
                            self.assertIsNone(result.get("committed_revision"))
                            self.assertEqual(revision, db.max_revision())
                            self.assertEqual(saved, self.saved_records(db))
                    for row in prep["scaffold"]["integrations"]:
                        row.update(decision=decision, rationale="Adopt the saved examination with no explicit pins.")
                        row["successor_checks"] = []
                    self.submit(db, fixture, prep, prep["scaffold"])
                    self.assertEqual(revision + 1, db.max_revision())

    def test_canonical_decisions_preserve_explicit_saved_check_selection(self):
        for decision in ("primary_revised", "independent_revised"):
            for role, expected in (("primary", "supported"), ("independent", "defect")):
                with self.subTest(decision=decision, selected_role=role):
                    fixture = self.prepared_fixture(name=f"{decision}_{role}")
                    with fixture.open() as db:
                        self.examine(db, fixture, "gap")
                        selected = next(check.pinned for check in db.heads("checks")
                                        if check.body["target"] == R("arguments", "arg_thm") and check.body["role"] == role)
                        count = len(db.heads("checks"))
                        prep = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
                        for row in prep["scaffold"]["integrations"]:
                            row.update(decision=decision, rationale="Use the explicitly selected saved whole-unit examination.",
                                       successor_checks=[selected])
                        self.submit(db, fixture, prep, prep["scaffold"])
                        self.integrate(db, fixture)
                        rec = self.current_comparison(db)
                        self.assertEqual(decision, rec.body["decision"])
                        self.assertEqual([selected], rec.body["successor_checks"])
                        result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
                        self.assertTrue(result["progress"]["process_complete"])
                        self.assertEqual(expected, result["assessments"]["items:itm_thm"]["label"])
                        self.assertEqual(count, len(db.heads("checks")))

    def test_persistent_reconciliation_schema_rejects_adoption_aliases(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.examine(db, fixture, "gap")
            independent = next(check.id for check in db.heads("checks")
                               if check.body["role"] == "independent" and check.body["target"] == R("arguments", "arg_thm"))
            packet = fixture.packet(db, *fixture.ITEMS, mode="reconcile")
            saved, revision = self.saved_records(db), db.max_revision()
            for decision in ("adopt_independent", "adopt_primary"):
                with self.subTest(decision=decision):
                    row = fixture.reconciliation_edit(db, "rec_alias", "arg_thm", "chk_comp_thm", independent)
                    row["body"].update(decision=decision, successor_checks=[db.head("checks", independent).pinned])
                    with self.assertRaises(InvalidRequest) as caught:
                        review.reconcile(db, batch=fixture.batch([row], packet["packet_id"]))
                    self.assertTrue(any("decision" in error for error in caught.exception.records), caught.exception.records)
                    self.assertEqual(revision, db.max_revision())
                    self.assertEqual(saved, self.saved_records(db))

    def test_adopt_independent_gap_without_new_check_or_manual_pins(self):
        self.adoption("supported", "gap", "primary_revised", "defect")

    def test_adopt_independent_support_updates_basis_and_display(self):
        self.adoption("gap", "supported", "primary_revised", "supported")

    def test_retain_primary_support_without_new_check_or_manual_pins(self):
        self.adoption("supported", "gap", "independent_revised", "supported")

    def test_mapped_group_and_use_opinions_finish_in_the_unit(self):
        for collection, identity, kind in (("groups", "grp_thm", "derivation"),
                                            ("uses", "use_lem_thm", "application")):
            with self.subTest(kind=kind):
                fixture = self.prepared_fixture(name=kind)
                with fixture.open() as db:
                    self.examine(db, fixture, member=(collection, identity, kind, "supported"))
                    self.integrate(db, fixture)
                    result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
                    self.assertTrue(result["progress"]["process_complete"])
                    self.assertEqual("available", result["support"]["items:itm_thm"])
                    rec = next(r for r in db.heads("reconciliations") if r.body["target"] == R("arguments", "arg_thm"))
                    self.assertEqual(2, len(rec.body["independent_checks"]))

    def test_adoption_keeps_distinct_local_gap_and_uncertainty(self):
        for local_outcome in ("gap", "inconclusive"):
            with self.subTest(outcome=local_outcome):
                fixture = self.prepared_fixture(name=local_outcome)
                with fixture.open() as db:
                    self.examine(db, fixture, "gap", member=("groups", "grp_thm", "derivation", local_outcome))
                    self.integrate(db, fixture, "independent_revised")
                    result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
                    self.assertTrue(result["progress"]["process_complete"])
                    self.assertNotEqual("available", result["support"]["items:itm_thm"])
                    self.assertNotEqual("green", result["assessments"]["groups:grp_thm"]["state"])

    def test_unresolved_finishes_without_support(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.examine(db, fixture, "gap")
            self.integrate(db, fixture, "unresolved")
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(result["progress"]["process_complete"])
            self.assertEqual("disputed", result["assessments"]["items:itm_thm"]["label"])
            self.assertNotEqual("available", result["support"]["items:itm_thm"])

    def test_adoption_does_not_resolve_open_finding(self):
        fixture = self.prepared_fixture("gap")
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "findings", "fnd_open", {"audit_id": fixture.audit_id,
                "target": R("arguments", "arg_thm"), "category": "proof_gap",
                "description": "An unresolved independent premise concern.",
                "evidence_refs": ["anc_thm_proof"], "check_refs": [], "affected_uses": [],
                "impact_reason": "The inference still requires this premise.", "lifecycle": "open",
                "resolution": None})], *fixture.ITEMS, mode="primary")
            self.examine(db, fixture)
            self.integrate(db, fixture, "primary_revised")
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertNotEqual("available", result["support"]["items:itm_thm"])
            self.assertEqual("open", db.head("findings", "fnd_open").body["lifecycle"])

    def test_changed_claim_cannot_keep_adopted_support(self):
        fixture = self.prepared_fixture("gap")
        with fixture.open() as db:
            self.examine(db, fixture)
            self.integrate(db, fixture, "primary_revised")
            item = db.head("items", "itm_thm")
            body = deepcopy(item.body)
            body["statement"] = {"form": "verbatim", "text": "A different stronger conclusion."}
            fixture.apply(db, [edit("replace", "items", item.id, body, item.version)], *fixture.ITEMS, mode="primary")
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertNotEqual("available", result["support"]["items:itm_thm"])
            self.assertFalse(result["progress"]["process_complete"])

    def test_retaining_primary_inconclusive_replaces_only_the_whole_unit_gap(self):
        fixture = self.prepared_fixture("inconclusive")
        with fixture.open() as db:
            self.examine(db, fixture, "gap")
            self.integrate(db, fixture, "independent_revised")
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(result["progress"]["process_complete"])
            self.assertEqual("conditional", result["support"]["items:itm_thm"])
            self.assertNotEqual("defect", result["assessments"]["items:itm_thm"]["label"])

    def test_adopted_support_uses_its_own_conditions(self):
        conditions = ["A restriction not established by this proof."]
        fixture = self.prepared_fixture(conditions=conditions)
        with fixture.open() as db:
            original = db.head("checks", "chk_comp_thm")
            self.examine(db, fixture)
            self.integrate(db, fixture, "primary_revised")
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual("available", result["support"]["items:itm_thm"])
            self.assertEqual(conditions, db.head("checks", original.id).body["conditions"])

    def test_unit_reconciliation_rejects_another_units_opinion(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.examine(db, fixture)
            independent = {check.body["target"]["id"]: check for check in db.heads("checks")
                           if check.body["role"] == "independent"}
            row = fixture.reconciliation_edit(db, "rec_unrelated", "arg_thm", "chk_comp_thm",
                                               independent["arg_thm"].id)
            row["body"]["independent_checks"].append(independent["arg_lem"].pinned)
            packet = fixture.packet(db, *fixture.ITEMS, mode="reconcile")
            with self.assertRaises(InvalidRequest) as caught:
                review.reconcile(db, batch=fixture.batch([row], packet["packet_id"]))
            self.assertTrue(any("another audit or target" in error for error in caught.exception.records))

    def test_selected_saved_opinion_resolves_other_whole_unit_opinions(self):
        fixture = self.prepared_fixture("gap")
        with fixture.open() as db:
            self.examine(db, fixture, "gap")
            selected, _ = fixture.independent_round(db, "itm_thm", "arg_thm", "anc_thm_proof",
                judgment_target={"source_anchor_id": "anc_thm_proof", "description": "The full theorem proof."},
                reviewer="another separate reviewer")
            prep = stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile", focus=R("items", "itm_thm"))
            for row in prep["scaffold"]["integrations"]:
                row.update(decision="primary_revised", rationale="Compared all saved whole-unit opinions and adopt the identified supported opinion.",
                           successor_checks=[db.head("checks", selected).pinned])
            self.submit(db, fixture, prep, prep["scaffold"])
            self.integrate(db, fixture)
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(result["progress"]["process_complete"])
            self.assertEqual("available", result["support"]["items:itm_thm"])
            self.assertEqual("supported", result["assessments"]["items:itm_thm"]["label"])
            self.assertTrue(any(check.body["outcome"] == "gap" and check.body["role"] == "independent"
                                for check in db.heads("checks")))
