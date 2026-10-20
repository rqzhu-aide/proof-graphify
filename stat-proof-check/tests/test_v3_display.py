"""Whole-proof examination is visible without inventing local verdicts."""
from unittest.mock import patch

from support import R, TempCase, edit
from paper_core import assessment, projection, publish, review


class ExaminedDisplayTests(TempCase):
    def examined(self, name="paper", *, outcome="gap", extent="whole_unit", state="complete"):
        fixture = self.fixture(name).audit(independent_required=False)
        with fixture.open() as db:
            checks = [fixture.check_edit(f"chk_comp_{unit}", R("arguments", f"arg_{unit}"), "composition",
                                        outcome=outcome if unit == "thm" else "supported",
                                        evidence=[f"anc_{unit}_proof"]) for unit in ("lem", "thm")]
            checks[1]["body"].update(state=state, extent=extent,
                                     omissions="The final inference was not examined." if extent == "partial" else "")
            fixture.apply(db, checks, *fixture.ITEMS, mode="primary")
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            review.compare(db, batch=fixture.batch([
                edit("create", "observations", f"obs_{unit}", {
                    "target": R("items", f"itm_{unit}"), "result": "matched", "reviewer": "primary",
                    "note": "The complete statement matches the captured source.",
                    "evidence_refs": [f"anc_{unit}"]}) for unit in ("lem", "thm")], packet["packet_id"]))
        return fixture

    def derive(self, fixture):
        with fixture.open(write=False) as db:
            return assessment.derive_assessment(db, audit_id=fixture.audit_id)

    def projected(self, fixture):
        with fixture.open(write=False) as db:
            return projection.build_projection(db, audit_id=fixture.audit_id)

    def test_unsuccessful_whole_unit_is_examined_without_local_credit_or_new_work(self):
        for outcome, availability in (("gap", "unavailable"), ("inconclusive", "conditional")):
            with self.subTest(outcome=outcome):
                fixture = self.examined(outcome, outcome=outcome)
                result = self.derive(fixture)
                with patch.object(assessment._Derivation, "_examined_display", autospec=True,
                                  side_effect=lambda derivation, record, value: value):
                    prior_display = self.derive(fixture)
                for key in ("groups:grp_thm", "uses:use_lem_thm"):
                    value, previous = result["assessments"][key], prior_display["assessments"][key]
                    self.assertEqual(value["state"], "gray")
                    self.assertEqual(value["label"], "examined in proof")
                    self.assertIn("no separate local verdict", value["explanation"])
                    self.assertEqual(previous["label"], "unassessed")
                    self.assertEqual({k: v for k, v in value.items() if k not in ("label", "explanation", "local_label")},
                                     {k: v for k, v in previous.items() if k not in ("label", "explanation", "local_label")})
                for key in result.keys() - {"assessments"}:
                    self.assertEqual(result[key], prior_display[key], key)
                self.assertTrue(result["progress"]["process_complete"])
                self.assertEqual(result["support"]["items:itm_thm"], availability)
                self.assertEqual(result["judgments"]["checks:chk_comp_thm"]["outcome"], outcome)
                view = self.projected(fixture)
                connection = view["connections"][0]
                displayed = [connection["assessment"], connection["groups"][0]["assessment"],
                    connection["applications"][0]["assessment"],
                    view["details"]["item:itm_thm"]["reader"]["applications"][0]["assessment"]]
                for value in displayed:
                    self.assertEqual(value["label"], "examined in proof")
                    self.assertEqual(value["state"], "gray")
                    self.assertEqual(value["review_display"]["status"], "unassessed")
                with fixture.open(write=False) as db:
                    self.assertEqual(len(db.heads("checks")), 2)
                    self.assertEqual(len(db.heads("coverage")), 0)

    def test_partial_draft_stale_and_superseded_examinations_do_not_supply_label(self):
        for case in ("partial", "draft", "stale", "superseded"):
            with self.subTest(case=case):
                fixture = self.examined(case, extent="partial" if case == "partial" else "whole_unit",
                                        state="draft" if case == "draft" else "complete")
                with fixture.open() as db:
                    if case == "stale":
                        detail = db.head("application_details", "use_lem_thm")
                        fixture.apply(db, [edit("replace", "application_details", detail.id,
                            dict(detail.body, needed_form={"form": "verbatim", "text": "a uniform bound"}), detail.version)])
                    elif case == "superseded":
                        replacement = fixture.check_edit("chk_partial", R("arguments", "arg_thm"), "composition",
                            outcome="inconclusive", evidence=["anc_thm_proof"],
                            supersedes=fixture.pin(db, "checks", "chk_comp_thm"))
                        replacement["body"].update(extent="partial", omissions="The final inference remains unexamined.")
                        fixture.apply(db, [replacement], mode="primary")
                result = self.derive(fixture)
                for key in ("groups:grp_thm", "uses:use_lem_thm"):
                    self.assertEqual(result["assessments"][key]["label"], "unassessed")
                self.assertEqual(self.projected(fixture)["connections"][0]["assessment"]["label"], "unassessed")

    def test_new_scientific_content_at_an_examined_anchor_remains_unassessed(self):
        fixture = self.examined()
        before = self.derive(fixture)
        with fixture.open() as db:
            claim = fixture.item_edit("itm_new", "intermediate_result", "New assertion", "anc_thm_proof", "anc_thm_proof")
            claim["body"].update(owner_id="itm_thm", statement={"form": "verbatim", "text": "0 equals 1"})
            use = db.head("uses", "use_lem_thm")
            detail = db.head("application_details", use.id)
            fixture.apply(db, [claim, fixture.group_edit("grp_new", "arg_thm", "itm_new", "anc_thm_proof"),
                edit("create", "uses", "use_new", dict(use.body, to=R("items", "itm_new"))),
                edit("create", "application_details", "use_new", dict(detail.body, use_id="use_new", group_id="grp_new"))])
        result = self.derive(fixture)
        for key in ("groups:grp_new", "uses:use_new"):
            self.assertEqual(result["assessments"][key]["label"], "unassessed")
        self.assertEqual(result["assessments"]["groups:grp_thm"]["label"], "examined in proof")
        self.assertEqual(result["progress"]["required_obligations"], before["progress"]["required_obligations"])
        self.assertEqual(result["support"]["items:itm_new"], "conditional")
        connection = self.projected(fixture)["connections"][0]
        self.assertEqual(connection["assessment"]["label"], "unassessed")
        applications = {row["use_id"]: row["assessment"]["label"] for row in connection["applications"]}
        self.assertEqual(applications, {"use_lem_thm": "examined in proof", "use_new": "unassessed"})

    def test_summary_refinement_requires_registration_without_hiding_exact_members(self):
        for state in ("draft", "registered"):
            with self.subTest(state=state):
                fixture = self.examined(state)
                with fixture.open() as db:
                    body = dict(db.head("uses", "use_lem_thm").body, reason="Summary interpretation.")
                    fixture.apply(db, [edit("create", "uses", "use_summary", body),
                        edit("create", "connection_refinements", "ref_summary", {
                            "summary_use_id": "use_summary", "argument_id": "arg_thm",
                            "use_ids": ["use_lem_thm"], "state": state, "note": "Exact application mapping."})],
                        *fixture.ITEMS)
                view = self.projected(fixture)
                connection = view["connections"][0]
                expected = "unassessed" if state == "draft" else "examined in proof"
                self.assertEqual(connection["assessment"]["label"], expected)
                partitions = {row["group_id"]: row["assessment"]["label"] for row in connection["groups"]}
                self.assertEqual(partitions, {None: expected, "grp_thm": "examined in proof"})
                self.assertEqual(connection["applications"][0]["assessment"]["label"], "examined in proof")
                summaries = {row["use_ref"]["id"]: row["assessment"]["label"]
                    for row in view["details"]["item:itm_thm"]["reader"]["applications"]}
                self.assertEqual(summaries["use_summary"], "recorded connection")

    def test_examined_caption_passes_publication_acceptance_in_graph_and_index(self):
        fixture = self.examined()
        with fixture.open(write=False) as db:
            view = projection.build_projection(db, audit_id=fixture.audit_id)
            payload = publish.render_input(db, view, release=False, source_identity="examined-display-test")
        for mode in ("dag", "index"):
            with self.subTest(mode=mode):
                view["layout"]["mode"] = mode
                workdir = self.path("render-" + mode)
                workdir.mkdir()
                page, receipt = publish.render_payload(payload, workdir=workdir)
                self.assertEqual(receipt["python_acceptance"]["status"], "pass")
                self.assertIn(b"Examined in proof", page)
                self.assertIn(b"no separate local verdict", page)
                self.assertNotIn(b'class="proof-review-explanation">Included in the recorded proof examination', page)

    def test_aggregate_preserves_unknown_work_and_independent_qualifications(self):
        projector = object.__new__(projection._Projector)
        projector.refinements_by_use = {}
        constituent = {"role": "primary", "kind": "application", "required": True,
            "state": "missing", "substantive": False, "target": R("uses", "examined")}
        known = dict(assessment.reduce([constituent]), label="examined in proof",
            explanation="Included in the recorded proof examination; no separate local verdict.")
        projector.A = {"assessments": {"uses:examined": known}}
        independent = dict(constituent, role="independent", target=R("arguments", "review"),
            state="complete", freshness="current", outcome="supported")
        for label, constituents, indicator, expected in (
            ("empty", [], "not_required", "unassessed"),
            ("unknown hidden group", [constituent, dict(constituent, target=R("groups", "hidden"))], "not_required", "unassessed"),
            ("missing target", [dict(constituent, target=None)], "not_required", "unassessed"),
            ("review complete", [constituent, independent], "complete", "examined in proof"),
            ("review pending", [constituent, dict(independent, state="missing")], "pending", "examined in proof"),
            ("review disputed", [constituent, dict(independent, disputed=True)], "disputed", "disputed"),
            ("mixed primary", [constituent, dict(independent, role="primary")], "not_required", "partial")):
            with self.subTest(label=label):
                reduced = assessment.reduce(constituents, independent=indicator)
                result = projector.examined_aggregate(reduced, constituents, [])
                self.assertEqual(result["label"], expected)
                self.assertEqual({k: v for k, v in result.items() if k not in ("label", "explanation")},
                                 {k: v for k, v in reduced.items() if k not in ("label", "explanation")})

    def test_explicit_local_verdicts_take_precedence(self):
        for outcome, expected in (("supported", "green"), ("gap", "red")):
            with self.subTest(outcome=outcome):
                fixture = self.examined(outcome)
                with fixture.open() as db:
                    fixture.apply(db, [fixture.check_edit("chk_local", R("uses", "use_lem_thm"), "application",
                        outcome=outcome, evidence=["anc_thm_proof"])], mode="primary")
                result = self.derive(fixture)
                value = result["assessments"]["uses:use_lem_thm"]
                self.assertEqual(value["local_state"], expected)
                self.assertNotEqual(value["label"], "examined in proof")
                self.assertEqual(result["support"]["items:itm_thm"], "unavailable")

    def test_primary_and_actual_independent_response_outcomes_remain_unchanged(self):
        fixture = self.examined()
        with fixture.open() as db:
            check_id, _ = fixture.independent_round(db, "itm_thm", "arg_thm", "anc_thm_proof")
            records = [(r.collection, r.id, r.version, r.body) for r in db.records_at(db.max_revision())]
        result = self.derive(fixture)
        self.assertEqual(result["judgments"]["checks:chk_comp_thm"]["outcome"], "gap")
        self.assertEqual(result["judgments"][f"checks:{check_id}"]["outcome"], "supported")
        self.assertEqual(result["assessments"]["uses:use_lem_thm"]["label"], "examined in proof")
        with fixture.open(write=False) as db:
            self.assertEqual(records, [(r.collection, r.id, r.version, r.body) for r in db.records_at(db.max_revision())])


if __name__ == "__main__":
    import unittest
    unittest.main()
