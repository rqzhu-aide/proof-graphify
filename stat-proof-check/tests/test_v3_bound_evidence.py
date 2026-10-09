"""Saved cited evidence can ground a use without enlarging its unit scope."""
from copy import deepcopy

import test_v3_external as external_tests
from support import R, TempCase, edit
from paper_core import assessment, sources
from paper_core.bindings import coherent_unit_inputs


class BoundEvidenceTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)
        self.db = self.fx.open()
        self.addCleanup(self.db.close)
        external_tests.ExternalResultTests.add_external(self)
        self.use = self.db.head("uses", "use_external_thm")
        body = deepcopy(self.use.body)
        body["evidence_refs"] = ["anc_thm_proof", "anc_external_statement"]
        self.fx.apply(self.db, [edit("replace", "uses", self.use.id, body, self.use.version)])

    def examine(self, *, evidence=None, extent="whole_unit", outcome="supported"):
        row = self.fx.check_edit("chk_bound", R("arguments", "arg_thm"), "composition",
            evidence=evidence if evidence is not None else ["anc_thm_proof", "anc_external_statement"],
            outcome=outcome)
        row["body"].update(extent=extent,
            omissions="The final inference has not been examined." if extent == "partial" else "",
            next_action="The stated inference lacks support." if outcome == "gap" else None)
        self.fx.apply(self.db, [row], *self.fx.ITEMS, mode="primary")
        return self.db.head("checks", row["id"])

    def basis(self):
        derivation, _ = assessment.derive_full(self.db, audit_id=self.fx.audit_id)
        return derivation.local_basis.resolve(self.use.ref, "application")

    def test_cited_bound_anchor_supports_use_without_enlarging_scientific_scope(self):
        check = self.examine()
        derivation, result = assessment.derive_full(self.db, audit_id=self.fx.audit_id)
        bound = derivation.snap.binding(check)["bindings"]
        scope = bound["coherent_scope"]
        self.assertNotIn("anc_external_statement", {r["id"] for r in scope["source_evidence_refs"]})
        self.assertIn("anc_external_statement", {r["ref"]["id"] for r in bound["records"]
            if r["ref"]["collection"] == "anchors"})
        current = coherent_unit_inputs(derivation.snap, "arg_thm")
        self.assertEqual(scope, {k: v for k, v in current.items() if k != "consumed_inputs"})
        self.assertEqual("supported", derivation.local_basis.resolve(self.use.ref, "application"))
        self.assertEqual("conditional", result["support"]["items:itm_external"])
        self.assertEqual(1, len(self.db.heads("checks")))

    def test_bound_but_uncited_external_anchor_gives_no_local_credit(self):
        check = self.examine(evidence=["anc_thm_proof"])
        bound = self.db.binding("checks", check.id, check.version)["bindings"]
        self.assertIn("anc_external_statement", {r["ref"]["id"] for r in bound["records"]
            if r["ref"]["collection"] == "anchors"})
        self.assertNotIn("anc_external_statement", check.body["evidence_refs"])
        self.assertEqual("open", self.basis())

    def test_partial_unit_gives_no_blanket_basis(self):
        self.examine(extent="partial")
        self.assertEqual("open", self.basis())

    def test_adverse_owner_gives_no_blanket_basis(self):
        self.examine(outcome="gap")
        self.assertEqual("open", self.basis())

    def test_changed_application_cannot_inherit_saved_basis(self):
        self.examine()
        self.assertEqual("supported", self.basis())
        detail = self.db.head("application_details", self.use.id)
        body = deepcopy(detail.body)
        body["needed_form"]["text"] = "A strictly stronger external conclusion."
        self.fx.apply(self.db, [edit("replace", "application_details", detail.id, body, detail.version)])
        self.assertEqual("open", self.basis())

    def test_changed_source_invalidates_saved_evidence(self):
        self.examine()
        self.assertEqual("supported", self.basis())
        path = self.fx.source_root / "cited-result.txt"
        path.write_text(path.read_text(encoding="utf-8") + "A materially stronger assertion.\n",
            encoding="utf-8")
        sources.capture_sources(self.db, files=["cited-result.txt"])
        self.assertEqual("open", self.basis())

    def test_adverse_local_finding_still_controls_the_use(self):
        self.examine()
        self.assertEqual("supported", self.basis())
        self.fx.apply(self.db, [edit("create", "findings", "fnd_bound", {
            "audit_id": self.fx.audit_id, "target": self.use.ref, "category": "proof_gap",
            "description": "The external theorem's hypothesis is not established here.",
            "evidence_refs": ["anc_thm_proof"], "check_refs": [], "affected_uses": [self.use.id],
            "impact_reason": "This application remains unsupported.",
            "lifecycle": "open", "resolution": None})])
        self.assertEqual("defect", self.basis())
