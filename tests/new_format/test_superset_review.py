"""Scientific scope and provenance across source-only and supplied-route review."""
import copy

from support import Fixture, R, TempCase, edit
from paper_core import controller, packets, review
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest


class SupersetReviewTests(TempCase):
    def envelope(self, fx, prepared, exposure="route_provided"):
        return {"contract_version": 4, "request_id": fx.request_id(),
                "packet_id": prepared["packet_id"], "rebase_packet_id": None,
                "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": exposure, "exposure_note": "Fresh context with the declared packet only."}

    def test_part_source_packet_does_not_expand_one_thousand_siblings(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            fx.apply(db, [edit("create", "parts", f"prt_{i}", {
                "item_id": "itm_lem", "label": f"Part {i}",
                "statement": {"form": "transcription", "text": f"Part {i} assertion"},
                "passages": [{"role": "statement", "anchor_id": "anc_lem"}],
                "scope_id": None, "origin": "source"}) for i in range(1000)])
            audit = db.head("audits", fx.audit_id)
            fx.apply(db, [edit("replace", "audits", audit.id,
                              dict(audit.body, targets=[R("parts", "prt_1")]), audit.version)], mode="primary")
            result = packets.get_packet(db, targets=[R("parts", "prt_1")], mode="independent")
            self.assertEqual([r["ref"]["id"] for r in result["records"] if r["ref"]["collection"] == "parts"],
                             ["prt_1"])
            self.assertLess(len(result["records"]), 15)
            self.assertFalse(packets.blinding_violations(result))

    def test_route_review_requires_preserved_initial_blind_response(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            with self.assertRaises(InvalidRequest) as caught:
                controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", route_id="arg_lem")
            self.assertEqual(caught.exception.code, "SOURCE_ONLY_REVIEW_REQUIRED")

    def test_route_packet_carries_derivation_without_primary_verdict(self):
        fx = self.fixture().independent()
        with fx.open() as db:
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="independent", route_id="arg_lem")
            self.assertTrue(prepared["prepared"], prepared)
            packet = prepared["packet"]
            self.assertEqual(packet["review_basis"], "route_provided")
            self.assertTrue(prepared["manifest"]["initial_response_refs"])
            self.assertTrue(packet["supplied_derivations"])
            self.assertFalse({"checks", "observations", "findings", "responses"} &
                             {r["ref"]["collection"] for r in packet["records"]})
            for derivation in packet["supplied_derivations"]:
                self.assertNotIn("outcome", derivation)
                self.assertNotIn("reviewer", derivation)
            bad = controller.submit_work(db, envelope_bytes=canonical_bytes(self.envelope(fx, prepared, "source_only")),
                                         response_bytes=canonical_bytes(prepared["scaffold"]))
            self.assertEqual(bad["error"]["code"], "REVIEW_BASIS_MISMATCH")
            worker = copy.deepcopy(prepared["scaffold"])
            worker["coverage_note"] = "Examined the exact supplied route and its conditions."
            for task in prepared["manifest"]["work"]["tasks"]:
                worker["judgments"].append({"target": task["target"], "kind": task["kind"], "state": "complete",
                    "outcome": "supported", "reasoning": "The supplied inference follows in this exact scope.",
                    "evidence_refs": ["anc_lem_proof"], "conditions": [], "next_action": None, "supersedes": None})
            raw = canonical_bytes(worker)
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes(self.envelope(fx, prepared)),
                                           response_bytes=raw)
            self.assertEqual(saved["state"], "accepted", saved)
            response = db.head("responses", saved["response_id"])
            self.assertEqual(response.body["exposure"], "route_provided")
            self.assertEqual(db.get_blob(response.body["original_blob"]), raw)

    def test_equivalent_routine_mapping_preserves_accepted_response(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            worker = {"packet_id": packet["packet_id"], "covered_targets": [R("items", "itm_lem")],
                "coverage_note": "The source inference at the proof passage was independently derived.",
                "exposure_report": {"status": "none_known", "note": ""},
                "judgments": [{"target": {"source_anchor_id": "anc_lem_proof", "description": "The local inference"},
                    "kind": "derivation", "state": "complete", "outcome": "supported", "reasoning": "Exact source inference.",
                    "evidence_refs": ["anc_lem_proof"], "conditions": [], "next_action": None, "supersedes": None}]}
            raw = canonical_bytes(worker)
            submitted = review.submit_review(db, submission={
                "contract_version": 4, "request_id": fx.request_id(), "packet_id": packet["packet_id"],
                "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "source_only", "exposure_note": ""},
                response_bytes=raw)
            def map_to(group):
                context = fx.packet(db, "items:itm_lem", mode="primary")
                return review.map_response(db, mapping={"contract_version": 4, "request_id": fx.request_id(),
                    "packet_id": context["packet_id"], "response_id": submitted["response_id"],
                    "entries": [{"judgment_index": 0, "target": R("groups", group),
                                 "rationale": "The same exact routine inference and source scope are represented here."}],
                    "reviewer": "coordinator"})
            map_to("grp_lem")
            before = db.head("responses", submitted["response_id"])
            fx.apply(db, [fx.group_edit("grp_equivalent", "arg_lem", "itm_lem", "anc_lem_proof")])
            reused = map_to("grp_equivalent")
            after = db.head("responses", submitted["response_id"])
            self.assertEqual(after.version, before.version)
            self.assertEqual(db.get_blob(after.body["original_blob"]), raw)
            check = db.head("checks", reused["checks"][0]["check_id"])
            self.assertEqual(check.body["reasoning"], worker["judgments"][0]["reasoning"])
            self.assertEqual(check.body["target"], R("groups", "grp_equivalent"))
