"""Completion and contradiction counterexamples from the September 2026 audit."""
from __future__ import annotations

from support import R, TempCase, edit, node_available, run_cli
from paper_core.assessment import derive_assessment
from paper_core import queries


class CoverageGateTests(TempCase):
    def complete_with_coverage(self, transform):
        fixture = self.fixture()
        original = fixture.coverage_edits
        fixture.coverage_edits = lambda db: transform(original(db))
        fixture.complete()
        return fixture

    def assert_incomplete_coverage(self, fixture):
        with fixture.open(write=False) as db:
            result = derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(queries.validate_snapshot(db)["ok"], "unfinished work remains a valid draft")
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(any("proof coverage" in p for p in result["problems"]))
        # No missing reasoning is being confused with this separate coverage gate.
        self.assertEqual(result["progress"]["completed_current_obligations"], 13)

    def test_zero_coverage_cannot_complete_or_release_but_can_render(self):
        fixture = self.complete_with_coverage(lambda rows: [])
        self.assert_incomplete_coverage(fixture)
        payload, _ = run_cli("release", fixture.path, "--audit", fixture.audit_id,
                             "--out", self.path("release"), expect=2)
        self.assertEqual(payload["error"]["code"], "RELEASE_BLOCKED")
        if node_available():
            payload, _ = run_cli("checkpoint", fixture.path, "--audit", fixture.audit_id,
                                 "--out", self.path("working.html"))
            self.assertEqual(payload["state"], "published")

    def test_one_uncovered_character_is_not_hidden_by_completed_checks(self):
        def omit(rows):
            rows[0]["body"]["end_offset"] -= 1
            return rows
        self.assert_incomplete_coverage(self.complete_with_coverage(omit))

    def test_substantive_interval_without_responsible_checks_is_incomplete(self):
        def omit(rows):
            rows[0]["body"]["check_ids"] = []
            return rows
        self.assert_incomplete_coverage(self.complete_with_coverage(omit))

    def test_a_check_of_another_argument_cannot_cover_this_passage(self):
        def substitute(rows):
            rows[0]["body"]["check_ids"] = ["chk_der_thm"]
            return rows
        self.assert_incomplete_coverage(self.complete_with_coverage(substitute))

    def test_coverage_cannot_claim_a_statement_the_check_did_not_consume(self):
        def substitute(rows):
            rows[0]["body"]["claim_refs"] = [R("items", "itm_thm")]
            return rows
        self.assert_incomplete_coverage(self.complete_with_coverage(substitute))

    def test_structural_interval_needs_no_extra_claim_or_verdict(self):
        def split(rows):
            structural = dict(rows[0]["body"], end_offset=1, classification="structural",
                              claim_refs=[], check_ids=[], note="structural opening character")
            rows[0]["body"]["start_offset"] = 1
            return [*rows, edit("create", "coverage", "cov_structural", structural)]
        fixture = self.complete_with_coverage(split)
        with fixture.open(write=False) as db:
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["progress"]["required_obligations"], 13)

    def test_entire_structural_passage_does_not_invent_a_check(self):
        def structural(rows):
            rows[0]["body"].update(classification="structural", claim_refs=[], check_ids=[])
            return rows
        fixture = self.complete_with_coverage(structural)
        with fixture.open(write=False) as db:
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(len(result["judgments"]), 7)


class ContradictionTests(TempCase):
    def test_derivation_agreement_cannot_hide_composition_disagreement(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit(
                "chk_comp_gap", R("arguments", "arg_thm"), "composition", outcome="gap",
                evidence=["anc_thm_proof"], supersedes=fixture.pin(db, "checks", "chk_comp_thm"))],
                *fixture.ITEMS, mode="primary")
        fixture.independent()
        with fixture.open(write=False) as db:
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["independent"]["items:itm_thm"], "disputed")
        self.assertFalse(result["progress"]["process_complete"])

    def test_both_insertion_orders_are_disputed_until_explicit_supersession(self):
        for order in (("gap", "supported"), ("supported", "gap")):
            with self.subTest(order=order):
                fixture = self.fixture(name="-".join(order)).complete()
                with fixture.open() as db:
                    for index, outcome in enumerate(order):
                        fixture.apply(db, [fixture.check_edit(
                            f"chk_conflict_{index}", R("uses", "use_lem_thm"), "application",
                            outcome=outcome)], *fixture.ITEMS, mode="primary")
                    result = derive_assessment(db, audit_id=fixture.audit_id)
                    assessment = result["assessments"]["uses:use_lem_thm"]
                    self.assertEqual((assessment["state"], assessment["label"]), ("amber", "disputed"))
                    self.assertEqual(len(assessment["check_refs"]), 3)
                    self.assertFalse(result["progress"]["process_complete"])
                    self.assertTrue(assessment["missing_obligation_ids"])
                    gap_id = f"chk_conflict_{order.index('gap')}"
                    fixture.apply(db, [fixture.check_edit(
                        "chk_resolution", R("uses", "use_lem_thm"), "application",
                        supersedes=fixture.pin(db, "checks", gap_id))], *fixture.ITEMS, mode="primary")
                    resolved = derive_assessment(db, audit_id=fixture.audit_id)
                    self.assertEqual(resolved["assessments"]["uses:use_lem_thm"]["state"], "green")
                    self.assertTrue(resolved["progress"]["process_complete"])
                    self.assertEqual(resolved["judgments"][f"checks:{gap_id}"]["outcome"], "gap")
                    self.assertTrue(resolved["judgments"][f"checks:{gap_id}"]["superseded"])
