"""Exercise the shipped mathematical example without a private fixture dependency."""
import importlib.util

from support import PROOFCHECK, TempCase
from paper_core import acceptance, packets, storage
from paper_core.assessment import derive_full
from paper_core.ids import new_id
from paper_core.projection import build_projection

EXAMPLE = PROOFCHECK / "assets" / "examples" / "probability" / "build_example.py"
spec = importlib.util.spec_from_file_location("proofcheck_probability_example", EXAMPLE)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class ProbabilityExampleTests(TempCase):
    def test_example_records_full_primary_reasoning_but_no_independent_credit(self):
        result = example.build_example(self.work / "built")
        self.assertGreater(result["primary_submissions"], 0)
        self.assertFalse(result["progress"]["process_complete"])
        with storage.Database(result["database"]) as db:
            self.assertEqual([], db.heads("qualifications"))
            self.assertEqual([], db.heads("responses"))
            _, assessment = derive_full(db, audit_id=example.AUDIT)
            primary = [o for o in assessment["obligations"] if o["required"] and o["role"] == "primary"]
            self.assertTrue(primary)
            self.assertEqual([], [o for o in primary if not o["satisfied"]])
            self.assertEqual(8, len(db.heads("groups")))
            self.assertEqual(10, len(db.heads("application_details")))
            self.assertEqual({"anc_hoeffding_proof", "anc_ratio_proof"},
                             {pin["id"] for b in db.heads("proof_boundaries") for pin in b.body["anchor_refs"]})
            self.assertTrue(all("worked example" in c.body["reasoning"] for c in db.heads("checks")))
            projection = build_projection(db, audit_id=example.AUDIT)
            self.assertFalse(projection["summary"]["progress"]["process_complete"])
            self.assertIn("denominator", str(projection))
            self.assertIn("Specialize", db.head("items", "itm_ratio").body["proof_idea"])
        with self.assertRaisesRegex(ValueError, "never overwrites"):
            example.build_example(self.work / "built")

    def test_global_conditional_theorem_and_temporary_assumption_have_distinct_scope(self):
        result = example.build_example(self.work / "scopes")
        self.assertEqual({
            "conditional_theorem_in_event_scope": "available",
            "temporary_premise_inside_scope": "available",
            "temporary_premise_outside_scope": "unavailable",
            "denominator_inside_scope": "available",
            "denominator_outside_scope": "unavailable",
            "discharged_implication": "available"}, result["scope_examples"])

    def test_conditional_theorem_specialization_records_substitutions_and_local_hypotheses(self):
        result = example.build_example(self.work / "specializations")
        self.assertEqual({
            "conditional_theorem_in_consumer_scope": "available",
            "checked_x_application": "available", "checked_y_application": "available",
            "specialized_x_bound": "available", "specialized_y_bound": "available"},
            result["specialization_examples"])
        with storage.Database(result["database"]) as db:
            for use_id, coordinate in (("use_hx", "X"), ("use_hy", "Y")):
                detail = db.head("application_details", use_id)
                self.assertEqual([{"symbol": "Z_i", "value": coordinate + "_i"},
                                  {"symbol": "m", "value": "mu_" + coordinate},
                                  {"symbol": "u", "value": "t"}], detail.body["substitutions"])
                checks = [row for row in db.heads("checks") if row.body["kind"] == "application"
                          and row.body["target"] == example.ref("uses", use_id)]
                self.assertEqual(1, len(checks))
                self.assertIn("independ", checks[0].body["reasoning"].lower())
                self.assertIn("bounded", checks[0].body["reasoning"].lower())

    def test_missing_specialization_hypothesis_does_not_refute_general_theorem(self):
        result = example.build_example(self.work / "missing-hypothesis")
        with storage.Database(result["database"], write=True) as db:
            predecessor = next(row for row in db.heads("checks") if row.body["kind"] == "application"
                               and row.body["target"] == example.ref("uses", "use_hx"))
            # An authored negative probe of the recorded application, not a new scientific audit.
            body = dict(predecessor.body, outcome="gap", response_id=None, supersedes=predecessor.pinned,
                        reasoning="Negative interface probe: independence of the specialized X_i has not been established; "
                                  "the conditional supplier remains valid but this use cannot support the tail bound.")
            packet = packets.get_packet(db, targets=[example.ref("items", "itm_ratio")], mode="primary")
            acceptance.apply_batch(db, example.batch(packet["packet_id"],
                [example.create("checks", new_id("checks"), body)]))
            derivation, _ = derive_full(db, audit_id=example.AUDIT)
            self.assertEqual("available", derivation.support(example.ref("items", "itm_hoeffding"), "scp_global"))
            self.assertEqual("unavailable", derivation.use_support(db.head("uses", "use_hx")))
            self.assertEqual("unavailable", derivation.support(example.ref("items", "itm_x_tail"), "scp_global"))
            self.assertEqual("available", derivation.support(example.ref("items", "itm_y_tail"), "scp_global"))

    def test_supplier_confined_to_temporary_scope_cannot_support_outside_application(self):
        result = example.build_example(self.work / "scope-confusion")
        with storage.Database(result["database"], write=True) as db:
            spec = db.head("target_specs", "tgt_hoeffding")
            packet = packets.get_packet(db, targets=[example.ref("items", "itm_hoeffding")], mode="primary")
            acceptance.apply_batch(db, example.batch(packet["packet_id"], [{"op": "replace",
                "collection": "target_specs", "id": spec.id, "expected_version": spec.version,
                "body": dict(spec.body, scope_id="scp_event", fidelity_ref=None)}]))
            derivation, _ = derive_full(db, audit_id=example.AUDIT)
            self.assertEqual("unavailable", derivation.support(example.ref("items", "itm_hoeffding"), "scp_global"))
            self.assertEqual("unavailable", derivation.use_support(db.head("uses", "use_hx")))
            self.assertEqual("unavailable", derivation.support(example.ref("items", "itm_event"), "scp_global"))
