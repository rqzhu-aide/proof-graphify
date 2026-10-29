"""Issue display preserves scoped logical evidence, review level and history."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

from support import Fixture, R, TempCase, edit
from paper_core import PROTOCOL_VERSION, review
from paper_core.assessment import derive_full, reduce
from paper_core.projection import build_projection


class CurrentFixture(Fixture):
    """Use shared source fixtures with current whole-unit examination records."""

    def apply(self, db, edits, *targets, mode="author"):
        adapted = []
        for row in edits:
            row = dict(row)
            body = dict(row["body"])
            if row["collection"] in ("checks", "audits"):
                body["protocol_version"] = PROTOCOL_VERSION
            if row["collection"] == "checks" and body["kind"] == "composition":
                body.update(extent="whole_unit", omissions="")
            row["body"] = body
            adapted.append(row)
        return super().apply(db, adapted, *targets, mode=mode)


class ReviewDisplayTests(TempCase):
    def fixture(self, name="paper"):
        return CurrentFixture(self.path(name))

    def add_finding(self, fixture, db, ident="fnd_1", **changes):
        body = {"audit_id": fixture.audit_id, "target": R("groups", "grp_lem"),
                "category": "proof_gap", "lifecycle": "open", "description": "A local step needs correction.",
                "evidence_refs": ["anc_lem_proof"], "check_refs": [], "affected_uses": [],
                "impact_reason": "The same conclusion has an apparent valid correction.", "resolution": None}
        body.update(changes)
        targets = [f"{body['target']['collection']}:{body['target']['id']}"] if body["target"]["collection"] == "audits" else fixture.ITEMS
        fixture.apply(db, [edit("create", "findings", ident, body)], *targets, mode="primary")

    @staticmethod
    def node(view, ident="itm_lem"):
        return next(n for n in view["nodes"] if n["id"] == ident)["assessment"]

    def test_initial_supported_examination_is_checked_with_review_pending(self):
        fixture = self.fixture().primary()
        with fixture.open(write=False) as db:
            view = build_projection(db, audit_id=fixture.audit_id)
        row = self.node(view)
        self.assertEqual(row["review_display"]["status"], "checked")
        self.assertEqual(row["independent_review"], "pending")
        self.assertIn("Initial review", row["review_display"]["explanation"])

    def linked_composition(self, fixture, db, severity="minor"):
        old = fixture.pin(db, "checks", "chk_comp_lem")
        fixture.apply(db, [fixture.check_edit("chk_refuted", R("arguments", "arg_lem"), "composition",
            outcome="refuted", evidence=["anc_lem_proof"], supersedes=old)], *fixture.ITEMS, mode="primary")
        self.add_finding(fixture, db, severity=severity, category="statement_refutation",
            target=R("items", "itm_lem"), check_refs=[fixture.pin(db, "checks", "chk_refuted")])
        derivation, result = derive_full(db, audit_id=fixture.audit_id)
        obligation = next(o for o in result["obligations"] if o["target"] == R("arguments", "arg_lem")
                          and o["kind"] == "composition" and o["role"] == "primary")
        return derivation, result, obligation

    def test_composition_keeps_saved_claim_finding_severity_and_scientific_fields(self):
        def scientific(value):
            if isinstance(value, dict):
                return {k: scientific(v) for k, v in value.items() if k != "review_display"}
            if isinstance(value, list):
                return [scientific(v) for v in value]
            return value

        for severity in ("minor", "moderate", "severe"):
            with self.subTest(severity=severity):
                fixture = self.fixture(severity).primary()
                with fixture.open() as db:
                    d, result, obligation = self.linked_composition(fixture, db, severity)
                    self.assertTrue(obligation["satisfied"])
                    self.assertEqual(obligation["outcome"], "refuted")
                    self.assertEqual(obligation["freshness"], "current")
                    display = obligation["assessment"]["review_display"]
                    self.assertEqual(display["status"], severity)
                    self.assertEqual(display["finding_refs"], ["fnd_1"])
                    with patch.object(type(d), "_composition_display_findings", return_value=[]):
                        _, before = derive_full(db, audit_id=fixture.audit_id)
                    self.assertEqual(scientific(result), scientific(before))
                    for original, corrected in zip(before["obligations"], result["obligations"]):
                        if corrected["kind"] != "composition":
                            self.assertEqual(original, corrected)

    def test_composition_extra_findings_require_exact_claim_and_current_usable_pin(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            d, _, obligation = self.linked_composition(fixture, db)
            finding = d.review_display.findings["fnd_1"]
            pin = finding.body["check_refs"][0]
            saved = deepcopy(obligation)
            cases = [
                ("exact", finding.body["target"], [pin], True),
                ("supplier", R("items", "itm_thm"), [pin], False),
                ("audit", R("audits", fixture.audit_id), [pin], False),
                ("sibling route", R("arguments", "arg_thm"), [pin], False),
                ("sibling check", finding.body["target"], [dict(pin, id="chk_comp_thm")], False),
                ("other version", finding.body["target"], [dict(pin, version=pin["version"] + 1)], False),
                ("other collection", finding.body["target"], [dict(pin, collection="observations")], False),
            ]
            for name, target, refs, accepted in cases:
                with self.subTest(scope=name):
                    d.review_display.findings["fnd_1"] = replace(finding, body=dict(finding.body,
                        target=target, check_refs=refs))
                    self.assertEqual(d._composition_display_findings(obligation), ["fnd_1"] if accepted else [])
            d.review_display.findings["fnd_1"] = finding
            # Both supported reducer reference shapes identify the same saved finding.
            obligation["assessment"]["finding_refs"] = ["fnd_1"]
            self.assertEqual(d._composition_display_findings(obligation), ["fnd_1"])
            obligation = deepcopy(saved)
            argument = d.snap.get(obligation["target"])
            original_get = d.snap.get
            part = R("parts", "prt_exact")
            with patch.object(d.snap, "get", side_effect=lambda ref: replace(argument,
                    body=dict(argument.body, target=part)) if ref == obligation["target"] else original_get(ref)):
                for target in (part, R("items", "itm_lem"), R("parts", "prt_sibling")):
                    with self.subTest(part=target):
                        d.review_display.findings["fnd_1"] = replace(finding, body=dict(finding.body, target=target))
                        self.assertEqual(d._composition_display_findings(obligation),
                                         ["fnd_1"] if target == part else [])
            d.review_display.findings["fnd_1"] = finding
            info = d.judgment_info(d.snap.get(pin))
            for changes in ({"state": "draft"}, {"freshness": "needs_review"}, {"superseded": True}):
                with self.subTest(check=changes), patch.object(d, "judgment_info", return_value=dict(info, **changes)):
                    self.assertEqual(d._composition_display_findings(obligation), [])
            with patch.object(d, "judgment_info", return_value=dict(info, role="independent")), \
                    patch.object(d, "independent_usable", return_value=False):
                self.assertEqual(d._composition_display_findings(obligation), [])
            for kind in ("source_fidelity", "derivation", "reconciliation"):
                self.assertEqual(d._composition_display_findings(dict(obligation, kind=kind)), [])
            self.assertEqual(obligation, saved)

    def test_linked_composition_finding_keeps_lifecycle_freshness_and_dispute_rules(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            d, _, obligation = self.linked_composition(fixture, db)
            finding = d.review_display.findings["fnd_1"]
            def display():
                d.review_display.displays.clear()
                return d.review_display.assessment(obligation["assessment"], targets=[obligation["target"]],
                    finding_ids=d._composition_display_findings(obligation))
            d.review_display.findings["fnd_1"] = replace(finding, body=dict(finding.body, lifecycle="resolved"))
            self.assertEqual(display()["finding_refs"], [])
            d.review_display.findings["fnd_1"] = finding
            with patch("paper_core.assessment.judgment_freshness", return_value={"freshness": "needs_review"}):
                self.assertEqual(display()["finding_refs"], [])
            with patch.object(d.review_display, "_disputed", return_value=True):
                self.assertEqual(display()["status"], "unresolved")
                self.assertEqual(display()["finding_refs"], ["fnd_1"])

    def test_highest_current_severity_with_unrated_and_inconclusive_notes(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.add_finding(fixture, db, "fnd_minor", severity="minor")
            self.add_finding(fixture, db, "fnd_moderate", severity="moderate")
            self.add_finding(fixture, db, "fnd_unrated")
            self.add_finding(fixture, db, "fnd_unknown", category="inconclusive", severity="severe")
            view = build_projection(db, audit_id=fixture.audit_id)
        row = self.node(view)["review_display"]
        self.assertEqual(row["status"], "moderate")
        self.assertEqual(row["unrated_count"], 1)
        self.assertEqual(len(row["finding_refs"]), 4)
        self.assertIn("unresolved", row["explanation"])
        self.assertEqual(view["finding_displays"]["fnd_unknown"]["status"], "unresolved")
        self.assertEqual(view["summary"]["findings"]["current_by_review_status"],
                         {"severe": 0, "moderate": 1, "minor": 1, "unresolved": 1, "unrated": 1})
        self.assertEqual(view["details"]["item:itm_lem"]["review_display"], row)
        self.assertEqual(view["details"]["item:itm_lem"]["reader"]["targets"][0]["assessment"]["review_display"], row)

    def test_resolved_superseded_and_stale_findings_do_not_color_current_work(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.add_finding(fixture, db, "fnd_resolved", severity="severe", lifecycle="resolved", resolution="Corrected.")
            self.add_finding(fixture, db, "fnd_old", severity="severe", lifecycle="superseded", resolution="Replaced.")
            self.add_finding(fixture, db, "fnd_current", severity="minor")
            view = build_projection(db, audit_id=fixture.audit_id)
            self.assertEqual(view["summary"]["findings"]["current_by_review_status"],
                             {"severe": 0, "moderate": 0, "minor": 1, "unresolved": 0, "unrated": 0})
            derivation, result = derive_full(db, audit_id=fixture.audit_id)
            original = derivation.review_display.finding("fnd_current")
            self.assertEqual(original["status"], "minor")
            self.assertEqual(derivation.review_display.finding("fnd_resolved")["status"], "historical")
            self.assertEqual(derivation.review_display.finding("fnd_old")["status"], "historical")
            derivation.review_display.displays.pop("fnd_current")
            with patch("paper_core.assessment.judgment_freshness", return_value={"freshness": "needs_review"}):
                self.assertEqual(derivation.review_display.finding("fnd_current")["status"], "historical")

    def test_unrated_issue_remains_neutral_without_changing_supported_logic(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.add_finding(fixture, db, category="presentation")
            view = build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(self.node(view)["state"], "green")
        self.assertEqual(self.node(view)["review_display"]["status"], "unrated")

    def test_supplier_and_global_findings_do_not_paint_unaffected_use_or_result(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.add_finding(fixture, db, severity="severe", target=R("items", "itm_lem"))
            self.add_finding(fixture, db, "fnd_global", severity="severe", target=R("audits", fixture.audit_id))
            view = build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(self.node(view)["review_display"]["status"], "severe")
        self.assertEqual(self.node(view, "itm_thm")["review_display"]["status"], "dependency")
        self.assertEqual(self.node(view, "itm_thm")["review_display"]["finding_refs"], [])
        self.assertIn(view["connections"][0]["assessment"]["review_display"]["status"], ("dependency", "unresolved"))
        self.assertEqual(view["connections"][0]["assessment"]["review_display"]["finding_refs"], [])
        self.assertEqual(view["summary"]["review_display"]["status"], "severe")

    def test_explicit_affected_use_scopes_finding_to_edge_and_its_owner(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.add_finding(fixture, db, severity="minor", affected_uses=["use_lem_thm"])
            view = build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(self.node(view, "itm_thm")["review_display"]["status"], "minor")
        self.assertEqual(view["connections"][0]["assessment"]["review_display"]["status"], "minor")
        self.assertEqual(view["summary"]["findings"]["current_by_review_status"]["minor"], 1)

    def test_auxiliary_citation_keeps_owner_warning_without_painting_supported_consumer(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            auxiliary = fixture.item_edit("itm_aux", "intermediate_result", "Unused auxiliary bound",
                                          "anc_lem_proof", "anc_lem_proof")
            auxiliary["body"]["owner_id"] = "itm_lem"
            fixture.apply(db, [auxiliary,
                fixture.group_edit("grp_aux", "arg_lem", "itm_aux", "anc_lem_proof")], *fixture.ITEMS)
        fixture.primary()
        with fixture.open() as db:
            before = build_projection(db, audit_id=fixture.audit_id)
            self.add_finding(fixture, db, severity="moderate", target=R("items", "itm_aux"),
                             check_refs=[fixture.pin(db, "checks", "chk_comp_lem")])
            view = build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(self.node(view)["availability"], "available")
        self.assertEqual(self.node(view)["review_display"]["status"], "moderate")
        self.assertEqual(self.node(view, "itm_thm")["availability"], "available")
        self.assertEqual(self.node(view, "itm_thm")["review_display"]["status"], "checked")
        connection = view["connections"][0]["assessment"]
        self.assertEqual(connection["review_display"], before["connections"][0]["assessment"]["review_display"])
        self.assertEqual(connection["review_display"]["finding_refs"], [])

    def test_application_group_issue_colors_its_edge_without_owner_overreach(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.add_finding(fixture, db, severity="minor", category="presentation",
                             target=R("groups", "grp_thm"))
            self.add_finding(fixture, db, "fnd_owner", severity="severe", category="presentation",
                             target=R("arguments", "arg_thm"))
            view = build_projection(db, audit_id=fixture.audit_id)
        connection = view["connections"][0]
        self.assertEqual(connection["assessment"]["review_display"]["status"], "minor")
        self.assertEqual(connection["assessment"]["review_display"]["finding_refs"], ["fnd_1"])
        self.assertEqual(connection["groups"][0]["assessment"]["review_display"]["status"], "minor")
        self.assertEqual(self.node(view, "itm_thm")["review_display"]["status"], "severe")

    def test_old_check_link_does_not_make_current_open_finding_historical(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            old = fixture.pin(db, "checks", "chk_der_lem")
            self.add_finding(fixture, db, severity="minor", check_refs=[old])
            fixture.apply(db, [fixture.check_edit("chk_der_lem_new", R("groups", "grp_lem"), "derivation",
                supersedes=old)], *fixture.ITEMS, mode="primary")
            view = build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(view["finding_displays"]["fnd_1"]["status"], "minor")

    def test_disputed_finding_does_not_neutralize_separate_rated_issue(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            self.add_finding(fixture, db, severity="severe")
            self.add_finding(fixture, db, "fnd_certain", severity="minor")
            derivation, _ = derive_full(db, audit_id=fixture.audit_id)
            derivation.review_display.displays.clear()
            with patch.object(derivation.review_display, "_disputed", side_effect=lambda f: f.id == "fnd_1"):
                value = derivation.review_display.assessment(reduce([]), owners=["itm_lem"])
            self.assertEqual(value["status"], "minor")
            self.assertIn("unresolved", value["explanation"])

    def test_reconciled_evidence_does_not_hide_another_disputed_target(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_thm_gap", R("groups", "grp_thm"),
                "derivation", outcome="gap")], *fixture.ITEMS, mode="primary")
            lemma = fixture.pin(db, "checks", "chk_der_lem")
            theorem = fixture.pin(db, "checks", "chk_der_thm")
            gap = fixture.pin(db, "checks", "chk_thm_gap")

            def reconcile(ident, target, checks, successors=()):
                packet = fixture.packet(db, *fixture.ITEMS, mode="reconcile")
                body = {"audit_id": fixture.audit_id, "target": target,
                        "primary_checks": checks, "independent_checks": [],
                        "successor_checks": list(successors),
                        "decision": "primary_revised" if successors else "agree",
                        "rationale": "Synthetic integration retains the selected examination.",
                        "evidence_refs": [], "supersedes": None, "adjudicator": "fixture"}
                review.reconcile(db, batch=fixture.batch(
                    [edit("create", "reconciliations", ident, body)], packet["packet_id"]))

            reconcile("rec_lemma", R("groups", "grp_lem"), [lemma])
            for ident, refs in (("fnd_ab", [lemma, theorem]), ("fnd_ba", [theorem, lemma])):
                self.add_finding(fixture, db, ident, severity="severe",
                                 target=R("groups", "grp_thm"), check_refs=refs)
            view = build_projection(db, audit_id=fixture.audit_id)
            for ident in ("fnd_ab", "fnd_ba"):
                with self.subTest(finding=ident, stage="disputed"):
                    self.assertEqual(view["finding_displays"][ident]["status"], "unresolved")

            # A completed integration must also suppress the now-settled raw conflict.
            reconcile("rec_theorem", R("groups", "grp_thm"), [theorem], [gap])
            view = build_projection(db, audit_id=fixture.audit_id)
            for ident in ("fnd_ab", "fnd_ba"):
                with self.subTest(finding=ident, stage="settled"):
                    self.assertEqual(view["finding_displays"][ident]["status"], "severe")

    def test_dependency_and_unexamined_empty_findings_are_neutral(self):
        fixture = self.fixture().primary()
        with fixture.open(write=False) as db:
            derivation, _ = derive_full(db, audit_id=fixture.audit_id)
            pending = reduce([])
            self.assertEqual(derivation.review_display.assessment(pending)["status"], "unassessed")
            pending.update(state="amber", label="conditional", availability="conditional", local_state="green")
            self.assertEqual(derivation.review_display.assessment(pending)["status"], "dependency")

    def test_triage_derives_neutral_summary_and_group_display_after_demotion(self):
        fixture = self.fixture().audit(mode="triage").primary()
        with fixture.open(write=False) as db:
            view = build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(view["summary"]["review_display"]["status"], "unassessed")
        assessments = [node["assessment"] for node in view["nodes"]]
        for connection in view["connections"]:
            assessments.append(connection["assessment"])
            assessments.extend(group["assessment"] for group in connection["groups"])
        self.assertTrue(assessments)
        for row in assessments:
            self.assertEqual(row["state"], "gray")
            self.assertEqual(row["label"], "triage")
            self.assertEqual(row["review_display"]["status"], "unassessed")
        with fixture.open() as db:
            self.add_finding(fixture, db, severity="minor", category="presentation",
                             target=R("groups", "grp_thm"))
            view = build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(view["summary"]["review_display"]["status"], "minor")
        self.assertEqual(view["connections"][0]["assessment"]["review_display"]["status"], "minor")
        self.assertEqual(view["connections"][0]["groups"][0]["assessment"]["review_display"]["status"], "minor")

    def test_overview_never_acquires_audit_display(self):
        fixture = self.fixture().structure()
        with fixture.open(write=False) as db:
            view = build_projection(db)
        self.assertNotIn("finding_displays", view)
        self.assertNotIn("review_display", view["summary"])
        self.assertTrue(all("review_display" not in n["assessment"] for n in view["nodes"]))
        for connection in view["connections"]:
            self.assertNotIn("review_display", connection["assessment"])
            for group in connection["groups"]:
                self.assertNotIn("review_display", group["assessment"])
