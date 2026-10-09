"""Local draft consolidation preserves science and assists ordinary authoring."""
from copy import deepcopy
import unittest

from support import Fixture, TempCase, edit
from paper_core import stage2
from paper_core.authoring import create_audit, create_unit
from paper_core.drafts import consolidate_drafts
from paper_core.errors import InvalidRequest


def item(local_id="one", statement="For every n, a_n <= 1.", **extra):
    return dict(local_id=local_id, kind="lemma", label="Lemma 1", statement=statement,
                source={"document": "paper.tex", "locator": "Lemma 1, lines 5-7"}, **extra)


def bundle(namespace="worker-a", **extra):
    return dict(namespace=namespace, reviewer=namespace, items=[item()], **extra)


class DraftTests(TempCase):
    def test_shared_claim_distinct_consumers_and_conflicting_opinions(self):
        a = bundle(examinations=[{"target": "one", "outcome": "supported", "reasoning": "Source argument works."}])
        b = bundle("worker-b", examinations=[{"target": "one", "outcome": "gap", "reasoning": "A step is missing."}])
        for draft, statement in ((a, "Sequence b converges."), (b, "Sequence c converges.")):
            draft["items"].append(item("consumer", statement))
            draft["connections"] = [{"from": "one", "to": "consumer", "reason": "Uses the bound."}]
        original = deepcopy([a, b])
        result = consolidate_drafts([a, b])
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["mapping"]["worker-a"]["one"], result["mapping"]["worker-b"]["one"])
        self.assertNotEqual(result["mapping"]["worker-a"]["consumer"], result["mapping"]["worker-b"]["consumer"])
        self.assertEqual(len(result["connections"]), 2)
        self.assertEqual([r["examination"] for r in result["examinations"]],
                         [a["examinations"][0], b["examinations"][0]])
        self.assertEqual([a, b], original)
        self.assertNotIn("reasoning", str(result["items"]))
        self.assertNotIn("outcome", str(result["items"]))

    def test_repeated_inputs_and_order_are_idempotent(self):
        a, b = bundle(), bundle("worker-b")
        self.assertEqual(consolidate_drafts([a, b]), consolidate_drafts([b, a, a]))
        self.assertEqual(consolidate_drafts([a, b])["source_drafts"], [a, b])
        changed = deepcopy(a)
        changed["items"][0]["statement"] = "Different conclusion."
        with self.assertRaisesRegex(InvalidRequest, "namespace"):
            consolidate_drafts([a, changed])

    def test_same_label_and_page_are_not_equivalence(self):
        variants = [bundle(f"worker-{n}") for n in range(5)]
        variants[1]["items"][0]["statement"] = "For positive n, a_n <= 1."
        variants[2]["items"][0]["context"] = "Only in Case II."
        variants[3]["items"][0]["source"]["document"] = "supplement.tex"
        variants[4]["items"][0]["unit"] = {"conditions": ["Assume n > 0."]}
        self.assertEqual(len(consolidate_drafts(variants)["items"]), 5)

    def test_partial_drafts_and_missing_local_references_survive(self):
        a = bundle(connections=[{"from": "not-yet-supplied", "to": "one", "reason": "Needed premise."}],
                   examinations=[{"target": "one", "extent": "partial", "reasoning": "Available part checked."}])
        result = consolidate_drafts([a])
        self.assertEqual(result["source_drafts"], [a])
        self.assertEqual(len(result["unresolved_references"]), 1)
        self.assertFalse(result["authoring"][0]["authoring_shape_ready"])
        self.assertEqual(result["examinations"][0]["examination"], a["examinations"][0])
        self.assertIn("unresolved", result["connections"][0]["proposal"]["from"])

    def test_named_assumption_is_context_without_a_proof_duty(self):
        a = bundle()
        assumption = item("A1", "X is integrable.")
        assumption["kind"] = "assumption"
        a["items"].append(assumption)
        a["connections"] = [{"from": "A1", "to": "one", "reason": "Under Assumption A1."}]
        result = consolidate_drafts([a])
        edge = result["connections"][0]["proposal"]
        self.assertEqual(edge["type"], "context")
        option = next(r for r in result["authoring"] if r["origin"]["local_id"] == "A1")
        self.assertEqual(option["command"], "template")
        self.assertEqual(option["body"]["kind"], "assumption")
        theorem = next(r for r in result["authoring"] if r["origin"]["local_id"] == "one")
        self.assertNotIn("suppliers", theorem["definition"])
        self.assertEqual(len(theorem["context"]), 1)
        self.assertTrue(any("captured statement/setup" in issue for issue in theorem["issues"]))

    def test_named_context_source_reaches_review_without_private_scope_or_proof_task(self):
        fixture = Fixture(self.path("context-authoring")).anchors()
        a = bundle()
        a["items"][0].update(statement="Under A1, the sequence converges.", context="Under the named assumption A1.",
            unit={"statement_anchors": ["anc_thm"], "proof_anchors": ["anc_thm_proof"],
                  "source_matched": True, "proof_complete": True, "source_note": "The source refers to A1."})
        assumption = item("A1", "The sequence is bounded and monotone.", unit={"statement_anchors": ["anc_lem"]})
        assumption["kind"] = "assumption"
        a["items"].append(assumption)
        a["connections"] = [{"from": "A1", "to": "one", "reason": "Under Assumption A1."}]
        original = deepcopy(a)
        result = consolidate_drafts([a])
        consumer = next(row for row in result["authoring"] if row["origin"]["local_id"] == "one")
        setup = next(row for row in result["authoring"] if row["origin"]["local_id"] == "A1")
        self.assertTrue(consumer["authoring_shape_ready"], consumer["issues"])
        self.assertEqual(["anc_thm", "anc_lem"], consumer["definition"]["statement_anchors"])
        self.assertEqual(original["items"][0]["statement"], consumer["definition"]["statement"])
        self.assertEqual(original["items"][0]["context"], consumer["source_context"])
        self.assertEqual(original, a)
        self.assertNotIn("suppliers", consumer["definition"])
        self.assertNotIn("assumptions", consumer["definition"])
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "items", setup["record_id"], setup["body"])])
            created = create_unit(db, consumer["definition"])
            audit = create_audit(db)
            packet = stage2.prepare(db, audit_id=audit["audit_id"])
            refs = {(row["ref"]["collection"], row["ref"]["id"]) for row in packet["packet"]["records"]}
            self.assertIn(("anchors", "anc_lem"), refs)
            self.assertIn(("anchors", "anc_thm"), refs)
            self.assertEqual([], db.heads("uses"))
            self.assertEqual(1, len(db.heads("arguments")))
            self.assertEqual(created["unit"]["argument"], packet["manifest"]["work"]["tasks"][0]["target"]["id"])
            self.assertEqual(1, stage2.stage_status(db, audit_id=audit["audit_id"], stage=2, mode="independent")["required"])

    def test_cross_namespace_refs_and_duplicate_connections_keep_origins(self):
        a, b = bundle(), bundle("worker-b")
        a["items"].append(item("two", "Sequence b converges."))
        edge = {"from": {"namespace": "worker-a", "local_id": "one"},
                "to": {"namespace": "worker-a", "local_id": "two"}, "reason": "Apply Lemma 1."}
        a["connections"] = [deepcopy(edge)]
        b["connections"] = [deepcopy(edge)]
        result = consolidate_drafts([a, b])
        self.assertEqual(len(result["connections"]), 1)
        self.assertEqual(len(result["connections"][0]["origins"]), 2)
        self.assertFalse(result["unresolved_references"])
        order = result["authoring_order"]
        self.assertLess(order.index(result["mapping"]["worker-a"]["one"]["id"]),
                        order.index(result["mapping"]["worker-a"]["two"]["id"]))

    def test_real_add_unit_accepts_prepared_definitions_without_mapping_code(self):
        fixture = Fixture(self.path("draft-authoring")).anchors()
        a = bundle()
        a["items"].append(item("two", "Sequence b converges."))
        for record in a["items"]:
            record["unit"] = {"statement_anchors": ["anc_lem"], "proof_anchors": ["anc_lem_proof"],
                              "source_matched": True, "proof_complete": True,
                              "source_note": "Worker compared the supplied statement and proof."}
        a["connections"] = [{"from": "one", "to": "two", "reason": "Uses the bound."}]
        with fixture.open() as db:
            revision = db.max_revision()
            result = consolidate_drafts([a])
            self.assertEqual(db.max_revision(), revision)
            for identity in result["authoring_order"]:
                option = next(r for r in result["authoring"] if r["target"]["id"] == identity)
                self.assertTrue(option["authoring_shape_ready"], option["issues"])
                authored = create_unit(db, option["definition"])
                self.assertEqual(authored["unit"]["item"], identity)
            self.assertEqual(len(db.heads("uses")), 1)
            self.assertEqual(len(db.heads("checks")), 0)
            self.assertEqual(len(db.heads("responses")), 0)

    def test_cycles_and_intermediate_owner_remain_local_authoring_choices(self):
        a = bundle()
        a["items"].append(item("two", "Sequence b converges."))
        a["connections"] = [{"from": "one", "to": "two", "reason": "A uses B."},
                            {"from": "two", "to": "one", "reason": "B uses A."}]
        result = consolidate_drafts([a])
        self.assertEqual(len(result["cyclic_items"]), 2)
        self.assertFalse(result["authoring_order"])
        a = bundle()
        equation = item("eq12", "x = y.", owner="one")
        equation["kind"] = "equation"
        a["items"].append(equation)
        result = consolidate_drafts([a])
        option = next(r for r in result["authoring"] if r["origin"]["local_id"] == "eq12")
        self.assertEqual(option["body"]["owner_id"], result["mapping"]["worker-a"]["one"]["id"])


if __name__ == "__main__":
    unittest.main()
