"""Coverage recovery explains the existing eligibility rules without relaxing them."""
from unittest.mock import patch

from support import Fixture, R, TempCase, edit
from paper_core import assessment, controller, sources, work


class CoverageDiagnosticTests(TempCase):
    def replace(self, fx, db, collection, identifier, **changes):
        old = db.head(collection, identifier)
        fx.apply(db, [edit("replace", collection, identifier, dict(old.body, **changes), old.version)],
                 *fx.ITEMS, mode="primary")

    def result(self, fx, db):
        return assessment.derive_full(db, audit_id=fx.audit_id)[1]

    def row(self, result, code, coverage_id="cov_lem"):
        return next(row for row in result["coverage_diagnostics"] if row["code"] == code and
                    row.get("coverage_ref", {}).get("id") == coverage_id)

    def boundary_review(self, fx, db, source_refs, *, names=("lem", "thm"), anchor_refs=None):
        review = db.head("source_reviews", "srv_boundaries")
        review_id = "srv_" + fx.request_id()
        packet = fx.packet(db, *fx.ITEMS, mode="primary")
        sources.review_sources(db, batch=fx.batch([edit("create", "source_reviews", review_id,
            dict(review.body, source_refs=source_refs,
                 anchor_refs=review.body["anchor_refs"] if anchor_refs is None else anchor_refs))], packet["packet_id"]))
        boundaries = [db.head("proof_boundaries", f"bnd_{name}") for name in names]
        fx.apply(db, [edit("replace", "proof_boundaries", b.id, dict(b.body,
            source_review_ref=fx.pin(db, "source_reviews", review_id)), b.version) for b in boundaries],
            *fx.ITEMS, mode="primary")
        return review_id

    def test_missing_boundary_source_pin_names_evidence_and_recovers_without_new_tasks(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            before = self.result(fx, db)
            review_id = self.boundary_review(fx, db, [])
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary",
                                               focus=R("items", "itm_lem"))
            result = self.result(fx, db)
            detail = next(row for row in result["coverage_diagnostics"] if row["argument_ids"] == ["arg_lem"])
            self.assertEqual("boundary_source_pin", detail["code"])
            self.assertEqual("anc_lem_proof", detail["anchor_id"])
            self.assertEqual(fx.pin(db, "proof_boundaries", "bnd_lem"), detail["boundary_ref"])
            self.assertEqual(fx.pin(db, "source_reviews", review_id), detail["source_review_ref"])
            self.assertEqual(fx.pin(db, "sources", fx.source_id), detail["required_source_ref"])
            self.assertEqual([o["id"] for o in before["obligations"]], [o["id"] for o in result["obligations"]])
            # Changing the boundary basis still reopens its consumed evidence.
            self.assertNotEqual("current", result["judgments"]["checks:chk_comp_lem"]["freshness"])
            self.assertFalse(result["progress"]["process_complete"])
            action = next(a for a in prepared["coordinator_actions"] if a["code"] == "coverage_authoring")
            self.assertEqual(["arg_lem"], action["cause_groups"][0]["examples"][0]["argument_ids"])
            self.boundary_review(fx, db, [fx.pin(db, "sources", fx.source_id)])
            recovered = self.result(fx, db)
            self.assertNotIn("boundary_source_pin", {r["code"] for r in recovered["coverage_diagnostics"]})
            self.assertFalse(recovered["progress"]["process_complete"])

    def test_stale_boundary_inputs_are_not_diagnosed_as_missing_source_pins(self):
        for stale in ("source", "anchor"):
            with self.subTest(stale=stale):
                fx = self.fixture(stale).audit(independent_required=False).primary()
                with fx.open() as db:
                    self.boundary_review(fx, db, [])
                    if stale == "source":
                        path = fx.source_root / "paper.tex"
                        path.write_text(path.read_text(encoding="utf-8") + "% source change\n", encoding="utf-8")
                        sources.capture_sources(db, files=["paper.tex"])
                    else:
                        packet = fx.packet(db, *fx.ITEMS, mode="primary")
                        sources.anchor_sources(db, request={"contract_version": 3,
                            "request_id": fx.request_id(), "packet_id": packet["packet_id"], "anchors": [
                                {"id": f"anc_{name}_proof", "expected_version": 1, "source_id": fx.source_id,
                                 "locator": {"start_line": start, "end_line": end, "page": None, "label": None}}
                                for name, start, end in (("lem", 8, 9), ("thm", 14, 15))]})
                    result = self.result(fx, db)
                    self.assertFalse(result["progress"]["process_complete"])
                    self.assertNotIn("boundary_source_pin", {r["code"] for r in result["coverage_diagnostics"]})
                    self.assertTrue(any(p.startswith("proof boundary for ") for p in result["problems"]))

    def test_incomplete_boundary_does_not_add_causes_to_other_valid_argument(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            self.boundary_review(fx, db, [], names=("thm",))
            view, (_, result) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
            details = [r for r in result["coverage_diagnostics"] if r["code"] == "boundary_source_pin"]
            self.assertEqual([["arg_thm"]], [r["argument_ids"] for r in details])
            focused = work.derive_work(db, audit_id=fx.audit_id, focus=R("anchors", "anc_lem_proof"))
            self.assertNotIn("coverage_authoring", {a["code"] for a in focused["coordinator_actions"]})

    def test_boundary_causes_are_bounded_and_focused_before_sampling(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            packet = fx.packet(db, *fx.ITEMS, mode="primary")
            sources.anchor_sources(db, request={"contract_version": 3, "request_id": fx.request_id(),
                "packet_id": packet["packet_id"], "anchors": [
                    {"id": f"anc_extra_{i}", "expected_version": None, "source_id": fx.source_id,
                     "locator": {"start_line": 8, "end_line": 10, "page": None, "label": None}}
                    for i in range(104)]})
            extra = [fx.pin(db, "anchors", f"anc_extra_{i}") for i in range(104)]
            anchors = db.head("source_reviews", "srv_boundaries").body["anchor_refs"] + extra
            self.boundary_review(fx, db, [], anchor_refs=anchors)
            body = db.head("proof_boundaries", "bnd_lem").body
            self.replace(fx, db, "proof_boundaries", "bnd_lem", anchor_refs=body["anchor_refs"] + extra)
            view, (_, result) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
            self.assertEqual(100, len(result["coverage_diagnostics"]))
            self.assertTrue(result["coverage_diagnostics_truncated"])
            action = next(a for a in view["coordinator_actions"] if a["code"] == "coverage_authoring")
            group = next(g for g in action["cause_groups"] if g["code"] == "boundary_source_pin")
            self.assertEqual(106, group["count"])
            self.assertEqual(3, len(group["examples"]))
            self.assertTrue(group["examples_truncated"])
            for focus in (R("arguments", "arg_thm"), R("items", "itm_thm"), R("anchors", "anc_thm_proof")):
                focused = work.derive_work(db, audit_id=fx.audit_id, focus=focus)
                action = next(a for a in focused["coordinator_actions"] if a["code"] == "coverage_authoring")
                group = next(g for g in action["cause_groups"] if g["code"] == "boundary_source_pin")
                self.assertEqual(1 if focus["collection"] == "anchors" else 106, group["count"])
                self.assertEqual(["arg_thm"], group["examples"][0]["argument_ids"])

    def test_missing_rows_provide_spans_and_focused_recovery_without_new_tasks(self):
        with patch.object(Fixture, "coverage_edits", return_value=[]):
            fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            result = self.result(fx, db)
            self.assertTrue(all(o["satisfied"] for o in result["obligations"] if o["required"]))
            self.assertFalse(result["progress"]["process_complete"])
            self.assertEqual({"missing_coverage"}, {d["code"] for d in result["coverage_diagnostics"]})
            lemma = next(d for d in result["coverage_diagnostics"] if d["argument_ids"] == ["arg_lem"])
            self.assertEqual([[0, len(db.head("anchors", "anc_lem_proof").body["excerpt"])]], lemma["spans"])
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
            self.assertFalse(prepared["prepared"])
            action = next(a for a in prepared["coordinator_actions"] if a["code"] == "coverage_authoring")
            examples = [e for group in action["cause_groups"] for e in group["examples"]]
            self.assertEqual({"arg_lem"}, {aid for e in examples for aid in e["argument_ids"]})

    def test_intermediate_focus_keeps_own_route_coverage_without_selecting_route_tasks(self):
        with patch.object(Fixture, "coverage_edits", return_value=[]):
            fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            self.replace(fx, db, "items", "itm_lem", kind="claim", owner_id="itm_thm")
            view, (_, result) = work.derive_work(db, audit_id=fx.audit_id,
                focus=R("items", "itm_lem"), include_assessment=True)
        self.assertEqual({"arg_lem", "arg_thm"},
                         {aid for row in result["coverage_diagnostics"] for aid in row["argument_ids"]})
        self.assertEqual(["source_fidelity"], [task["kind"] for task in view["tasks"]])
        self.assertTrue(all(task["argument"] is None for task in view["tasks"]))
        self.assertEqual("satisfied", view["tasks"][0]["state"])
        self.assertEqual(1, len(view["units"]))
        self.assertEqual([view["tasks"][0]["id"]], view["units"][0]["obligation_ids"])
        self.assertEqual("satisfied", view["units"][0]["state"])
        action = next(a for a in view["coordinator_actions"] if a["code"] == "coverage_authoring")
        examples = [e for group in action["cause_groups"] for e in group["examples"]]
        self.assertEqual({"arg_lem"}, {aid for e in examples for aid in e["argument_ids"]})
        self.assertFalse(result["progress"]["process_complete"])

    def test_empty_claims_and_checks_are_distinct_repair_causes(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            self.replace(fx, db, "coverage", "cov_lem", claim_refs=[], check_ids=[])
            result = self.result(fx, db)
        self.row(result, "missing_claims")
        self.row(result, "missing_checks")
        self.assertFalse(result["progress"]["process_complete"])

    def test_wrong_argument_identifies_link_without_invalidating_current_check(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            self.replace(fx, db, "coverage", "cov_lem", check_ids=["chk_der_thm"])
            result = self.result(fx, db)
        detail = self.row(result, "wrong_argument")
        self.assertEqual("chk_der_thm", detail["check_ref"]["id"])
        self.assertEqual("arg_thm", detail["check_argument_id"])
        self.assertEqual("current", result["judgments"]["checks:chk_der_thm"]["freshness"])
        self.assertFalse(result["progress"]["process_complete"])

    def test_extra_stale_link_requires_explicit_successor_even_with_current_alternative(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            self.replace(fx, db, "coverage", "cov_lem", check_ids=["chk_der_lem", "chk_comp_lem"])
            cov = db.head("coverage", "cov_lem")
            fx.apply(db, [edit("create", "coverage", "cov_structural", dict(cov.body,
                end_offset=1, classification="structural", claim_refs=[], check_ids=[]))], *fx.ITEMS, mode="primary")
            stale = self.result(fx, db)
            detail = self.row(stale, "unusable_check")
            self.assertEqual("chk_comp_lem", detail["check_ref"]["id"])
            self.assertNotEqual("current", detail["freshness"])
            self.assertEqual("current", stale["judgments"]["checks:chk_der_lem"]["freshness"])
            self.assertFalse(stale["progress"]["process_complete"])
            # Satisfying the obligation with unrelated work cannot repair this link.
            fx.apply(db, [fx.check_edit("chk_alternative", R("arguments", "arg_lem"), "composition")],
                     *fx.ITEMS, mode="primary")
            unrelated = self.result(fx, db)
            obligation = next(o for o in unrelated["obligations"] if o["target"] == R("arguments", "arg_lem")
                              and o["kind"] == "composition" and o["role"] == "primary")
            self.assertTrue(obligation["satisfied"])
            self.row(unrelated, "unusable_check")
            # Keep the original coverage link and carry it through explicit succession.
            fx.apply(db, [fx.check_edit("chk_successor", R("arguments", "arg_lem"), "composition",
                                       supersedes=fx.pin(db, "checks", "chk_comp_lem"))], *fx.ITEMS, mode="primary")
            renewed = self.result(fx, db)
        self.assertEqual([], renewed["coverage_diagnostics"])
        self.assertTrue(renewed["progress"]["process_complete"])

    def test_disputed_obligation_is_distinct_from_check_freshness(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            fx.apply(db, [fx.check_edit("chk_disagreement", R("groups", "grp_lem"), "derivation", outcome="gap")],
                     *fx.ITEMS, mode="primary")
            result = self.result(fx, db)
        detail = self.row(result, "unsatisfied_obligation")
        self.assertEqual("chk_der_lem", detail["check_ref"]["id"])
        self.assertTrue(detail["obligation_id"])
        self.assertEqual("current", result["judgments"]["checks:chk_der_lem"]["freshness"])
        self.assertFalse(result["progress"]["process_complete"])

    def test_unconsumed_claim_names_the_missing_statement(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            self.replace(fx, db, "coverage", "cov_lem", claim_refs=[R("items", "itm_thm")])
            result = self.result(fx, db)
        self.assertEqual([R("items", "itm_thm")], self.row(result, "unconsumed_claims")["claim_refs"])
        self.assertEqual("current", result["judgments"]["checks:chk_der_lem"]["freshness"])
        self.assertFalse(result["progress"]["process_complete"])

    def test_repeated_causes_have_bounded_samples_and_accurate_counts(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            cov = db.head("coverage", "cov_lem")
            body = dict(cov.body, check_ids=[])
            fx.apply(db, [edit("replace", "coverage", cov.id, body, cov.version),
                          *[edit("create", "coverage", f"cov_missing_{i}", body) for i in range(104)]],
                     *fx.ITEMS, mode="primary")
            view, (_, result) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
        self.assertEqual(105, result["coverage_diagnostic_count"])
        self.assertEqual(100, len(result["coverage_diagnostics"]))
        self.assertTrue(result["coverage_diagnostics_truncated"])
        action = next(a for a in view["coordinator_actions"] if a["code"] == "coverage_authoring")
        group = next(g for g in action["cause_groups"] if g["code"] == "missing_checks")
        self.assertEqual(105, group["count"])
        self.assertEqual(3, len(group["examples"]))
        self.assertTrue(group["examples_truncated"])

    def test_valid_coverage_has_no_additional_recovery_or_changed_verdict(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            view, (_, result) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
        self.assertEqual([], result["coverage_diagnostics"])
        self.assertEqual([], result["problems"])
        self.assertTrue(result["progress"]["process_complete"])
        self.assertNotIn("coverage_authoring", {a["code"] for a in view["coordinator_actions"]})

    def test_redundant_ineligible_row_does_not_create_a_new_completion_gate(self):
        fx = self.fixture().audit(independent_required=False).primary()
        with fx.open() as db:
            cov = db.head("coverage", "cov_lem")
            fx.apply(db, [edit("create", "coverage", "cov_redundant", dict(cov.body, check_ids=[])),
                          fx.check_edit("chk_renewed", R("arguments", "arg_lem"), "composition",
                                        supersedes=fx.pin(db, "checks", "chk_comp_lem"))], *fx.ITEMS, mode="primary")
            view, (_, result) = work.derive_work(db, audit_id=fx.audit_id, include_assessment=True)
        self.assertEqual([], result["coverage_diagnostics"])
        self.assertTrue(result["progress"]["process_complete"])
        self.assertNotIn("coverage_authoring", {a["code"] for a in view["coordinator_actions"]})
