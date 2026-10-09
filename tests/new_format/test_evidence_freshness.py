"""Selective freshness follows consumed statement context and borrowed proof content."""
from __future__ import annotations

import unittest

import support
from support import R, TempCase, edit, locator

from paper_core import acceptance, assessment, sources
from paper_core.refs import facet_digests


class ConsumedEvidenceTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()

    def freshness(self, db, check_id="chk_evidence"):
        return assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()),
                                             db.head("checks", check_id), superseded=False)

    def check(self, db):
        # These tests intentionally revise setup before commissioning a new
        # check. Normalize the exact target to that setup, as an author must.
        updates=[]
        for spec in db.heads('target_specs'):
            pin=spec.body['statement_ref']
            if pin:
                current=db.head(pin['collection'],pin['id'])
                prior=db.version(pin['collection'],pin['id'],pin['version'])
                if facet_digests(current.collection,current.body)['statement'] != facet_digests(prior.collection,prior.body)['statement']:
                    updates.append(edit('replace','target_specs',spec.id,
                        dict(spec.body,statement_ref=current.pinned,scope_id=current.body.get('scope_id')),spec.version))
        if updates:
            self.fx.apply(db,updates)
        packet = self.fx.packet(db, "items:itm_thm", mode="primary")
        acceptance.apply_batch(db, self.fx.batch(
            [self.fx.check_edit("chk_evidence", R("uses", "use_lem_thm"), "application")], packet["packet_id"]))
        binding = db.binding("checks", "chk_evidence", 1)["bindings"]
        read_set = {(r["collection"], r["id"], r["version"]) for r in packet["read_set"]}
        consumed = {(e["ref"]["collection"], e["ref"]["id"], e["ref"]["version"])
                    for e in binding["records"]}
        self.assertLessEqual(consumed, read_set, "the worker must receive all consumed evidence")
        guards = {(g["relation"], g["key"]["collection"], g["key"]["id"]) for g in packet["membership_guards"]}
        consumed_relations = {(g["relation"], g["key"]["collection"], g["key"]["id"])
                              for g in binding["relations"]}
        self.assertLessEqual(consumed_relations, guards)
        self.assertEqual("current", self.freshness(db)["freshness"])

    def reanchor(self, db, anchor_id, loc):
        anchor = db.head("anchors", anchor_id)
        packet = self.fx.packet(db, "items:itm_lem")
        sources.anchor_sources(db, request={"contract_version": 3, "request_id": self.fx.request_id(),
            "packet_id": packet["packet_id"], "anchors": [{"id": anchor_id,
                "expected_version": anchor.version, "source_id": self.fx.source_id, "locator": loc}]})

    def assert_changed(self, db, collection, id, facet):
        result = self.freshness(db)
        self.assertEqual("needs_review", result["freshness"])
        self.assertIn((collection, id, facet), [(entry["ref"]["collection"], entry["ref"]["id"], entry["facet"])
                                              for entry in result["changes"]["records"]])

    def test_changed_supplier_scope_conditions_require_review(self):
        with self.fx.open() as db:
            lemma = db.head("items", "itm_lem")
            scope = {"argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
                     "conditions": ["x > 0"], "evidence_refs": []}
            self.fx.apply(db, [edit("create", "scopes", "scp_supplier", scope),
                edit("replace", "items", lemma.id, dict(lemma.body, scope_id="scp_supplier"), lemma.version)])
            self.check(db)
            self.fx.apply(db, [edit("replace", "scopes", "scp_supplier", dict(scope, conditions=["x > 1"]), 1)],
                          "items:itm_lem")
            self.assert_changed(db, "scopes", "scp_supplier", "scope")

    def test_scope_assumption_context_cycles_bind_source_evidence_once(self):
        """An assumption may be declared in the same scope that names it."""
        with self.fx.open() as db:
            lemma = db.head("items", "itm_lem")
            assumption = self.fx.item_edit("itm_assumption", "assumption", "Assumption", "anc_lem_proof", "anc_thm_proof")
            assumption["body"]["scope_id"] = "scp_supplier"
            scope = {"argument_id": None, "parent_id": None, "assumptions": [R("items", "itm_assumption")],
                     "binders": [], "conditions": [], "evidence_refs": []}
            self.fx.apply(db, [assumption, edit("create", "scopes", "scp_supplier", scope),
                edit("replace", "items", lemma.id, dict(lemma.body, scope_id="scp_supplier"), lemma.version)])
            self.check(db)
            self.reanchor(db, "anc_lem_proof", locator(start=6, end=6))
            self.assert_changed(db, "anchors", "anc_lem_proof", "statement")

    def test_scope_evidence_excerpt_requires_review(self):
        with self.fx.open() as db:
            lemma = db.head("items", "itm_lem")
            scope = {"argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
                     "conditions": [], "evidence_refs": ["anc_lem_proof"]}
            self.fx.apply(db, [edit("create", "scopes", "scp_supplier", scope),
                edit("replace", "items", lemma.id, dict(lemma.body, scope_id="scp_supplier"), lemma.version)])
            self.check(db)
            self.reanchor(db, "anc_lem_proof", locator(start=6, end=6))
            self.assert_changed(db, "anchors", "anc_lem_proof", "statement")

    def part_supplier(self, db, *, borrowed=False):
        lemma = db.head("items", "itm_lem")
        use = db.head("uses", "use_lem_thm")
        scope = {"argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
                 "conditions": ["x > 0"], "evidence_refs": []}
        self.fx.apply(db, [edit("create", "scopes", "scp_supplier", scope),
            edit("replace", "items", lemma.id, dict(lemma.body, scope_id="scp_supplier"), lemma.version),
            edit("create", "parts", "prt_supplier", {"item_id": lemma.id, "label": "(i)",
                "statement": {"form": "verbatim", "text": "The first conclusion."},
                "passages": [{"role": "statement", "anchor_id": "anc_lem"}],
                "scope_id": None, "origin": "source"}),
            edit("replace", "uses", use.id, dict(use.body, **{"from": R("parts", "prt_supplier"),
                "type": "proof_argument" if borrowed else "dependency"}), use.version)])
        packet = self.fx.packet(db, "items:itm_thm", mode="primary")
        refs = {(entry["ref"]["collection"], entry["ref"]["id"]) for entry in packet["records"]}
        self.assertIn(("scopes", "scp_supplier"), refs)
        self.assertIn(("anchors", "anc_lem_proof"), refs)
        return scope

    def test_supplier_part_inherits_parent_statement_context(self):
        with self.fx.open() as db:
            scope = self.part_supplier(db)
            self.check(db)
            self.fx.apply(db, [edit("replace", "scopes", "scp_supplier", dict(scope, conditions=["x > 1"]), 1)],
                          "items:itm_lem")
            self.assert_changed(db, "scopes", "scp_supplier", "scope")

    def test_borrowed_part_without_separate_proof_binds_parent_proof_excerpt(self):
        with self.fx.open() as db:
            self.part_supplier(db, borrowed=True)
            self.check(db)
            self.reanchor(db, "anc_lem_proof", locator(start=6, end=6))
            self.assert_changed(db, "anchors", "anc_lem_proof", "proof")

    def test_changed_borrowed_proof_excerpt_requires_review(self):
        with self.fx.open() as db:
            use = db.head("uses", "use_lem_thm")
            self.fx.apply(db, [edit("replace", "uses", use.id, dict(use.body, type="proof_argument"), use.version)],
                          "items:itm_thm")
            self.check(db)
            self.reanchor(db, "anc_lem_proof", locator(start=6, end=6))
            self.assert_changed(db, "anchors", "anc_lem_proof", "proof")

    def test_ordinary_dependency_keeps_local_check_when_only_supplier_proof_changes(self):
        with self.fx.open() as db:
            self.check(db)
            self.reanchor(db, "anc_lem_proof", locator(start=6, end=6))
            self.assertEqual("current", self.freshness(db)["freshness"])
            lemma = db.head("items", "itm_lem")
            passages = [dict(p, anchor_id="anc_thm_proof") if p["role"] == "proof" else p
                        for p in lemma.body["passages"]]
            self.fx.apply(db, [edit("replace", "items", lemma.id, dict(lemma.body, passages=passages), lemma.version)],
                          "items:itm_lem")
            self.assertEqual("current", self.freshness(db)["freshness"])

    def test_changed_supplier_statement_excerpt_requires_review(self):
        with self.fx.open() as db:
            self.check(db)
            self.reanchor(db, "anc_lem", locator(start=6, end=6))
            self.assert_changed(db, "anchors", "anc_lem", "statement")

    def test_changed_statement_passage_membership_requires_review(self):
        with self.fx.open() as db:
            self.check(db)
            lemma = db.head("items", "itm_lem")
            passages = [dict(p, anchor_id="anc_thm") if p["role"] == "statement" else p
                        for p in lemma.body["passages"]]
            self.fx.apply(db, [edit("replace", "items", lemma.id, dict(lemma.body, passages=passages), lemma.version)],
                          "items:itm_lem")
            self.assert_changed(db, "items", "itm_lem", "statement")

    def test_exact_statement_relocation_and_labels_preserve_local_check(self):
        with self.fx.open() as db:
            self.check(db)
            old_excerpt = db.head("anchors", "anc_lem").body["excerpt"]
            self.reanchor(db, "anc_lem", locator(start=5, end=7))
            self.assertEqual(old_excerpt, db.head("anchors", "anc_lem").body["excerpt"])
            lemma = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", lemma.id,
                dict(lemma.body, label="Renumbered lemma", caption="New heading"), lemma.version)], "items:itm_lem")
            self.assertEqual("current", self.freshness(db)["freshness"])


if __name__ == "__main__":
    unittest.main()
