"""Integrate saved unit/member opinions without another examination."""
from copy import deepcopy
import json

from support import R, TempCase, edit
from paper_core import assessment, controller, finalization, review, stage2
from paper_core.errors import InvalidRequest


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
            for pin, body, raw in originals:
                self.assertEqual(pin, db.head("responses", pin["id"]).pinned)
                self.assertEqual(body, db.head("responses", pin["id"]).body)
                self.assertEqual(raw, db.get_blob(body["original_blob"]))
            frozen = finalization.finalize_audit(db, audit_id=fixture.audit_id, output=self.path("frozen"))
            self.assertEqual("release", frozen["kind"])

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
