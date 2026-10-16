"""Optional severity survives intake and edits without changing mathematical freshness."""
from copy import deepcopy

from support import R, TempCase, edit
from paper_core import assistance, contract, controller, review
from paper_core.bindings import binding_changes
from paper_core.canonical import canonical_bytes, digest
from paper_core.errors import ConflictError
from paper_core.refs import facet_digests
from paper_core.validation import State


class FindingSeverityTests(TempCase):
    def body(self, **changes):
        body = {"audit_id": "aud_1", "target": R("arguments", "arg_thm"),
                "category": "presentation", "lifecycle": "open",
                "description": "The tuning sentence reverses the displayed relationship.",
                "evidence_refs": ["anc_thm_proof"], "check_refs": [],
                "affected_uses": [], "impact_reason": "Correcting the sentence preserves the bound.",
                "resolution": None}
        return dict(body, **changes)

    def worker_finding(self, target, task_id, **changes):
        return {"target": target, "category": "presentation",
                "description": "The tuning sentence reverses the displayed relationship.",
                "evidence_refs": [], "related_task_ids": [task_id], "existing_check_refs": [],
                "affected_uses": [], "impact_reason": "Correcting the sentence preserves the bound.",
                **changes}

    def submit(self, db, fx, prepared, response):
        envelope = dict(prepared["submission_envelope_template"], reviewer="severity-test",
                        request_id=fx.request_id())
        return controller.submit_work(db, envelope_bytes=canonical_bytes(envelope),
                                      response_bytes=canonical_bytes(response))

    def test_optional_and_valid_enum_in_all_finding_shapes(self):
        bodies = [(contract.BODY_SCHEMAS["findings"], self.body()),
                  (contract.WORK_FINDING, self.worker_finding(R("arguments", "arg_thm"), "task_test")),
                  (controller.INTEGRATION_FINDING,
                   self.worker_finding(R("arguments", "arg_thm"), "task_test"))]
        for schema, body in bodies:
            self.assertEqual([], contract.validate_shape(schema, body))
            for severity in ("minor", "moderate", "severe"):
                self.assertEqual([], contract.validate_shape(schema, dict(body, severity=severity)))
            for severity in ("critical", "", None, 1):
                errors = contract.validate_shape(schema, dict(body, severity=severity))
                self.assertTrue(any("severity" in error for error in errors), errors)

    def test_blank_templates_and_examples_do_not_assign_rating(self):
        blank = assistance.authoring_template("findings", packet_id="pkt_example")
        self.assertNotIn("severity", blank["template"]["edits"][0]["body"])
        self.assertIn("severity", blank["body_shape"]["optional_fields"])
        for role in ("primary", "reconcile"):
            guidance = assistance.worker_guidance(role)
            self.assertNotIn("severity", guidance["optional_finding_example"])
        self.assertNotIn("severity", assistance.worker_guidance("independent")["judgment_shape"]["fields"])

    def test_primary_submission_preserves_explicit_and_omitted_rating(self):
        for severity in (None, "minor", "moderate", "severe"):
            with self.subTest(severity=severity):
                fx = self.fixture("primary_" + str(severity)).audit(independent_required=False)
                with fx.open() as db:
                    prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="primary",
                                                       focus=R("items", "itm_thm"))
                    self.assertTrue(prepared["prepared"], prepared)
                    response = deepcopy(prepared["scaffold"])
                    for row in response["results"]:
                        if row["type"] == "source_fidelity":
                            row.update(result="matched", note="Compared the supplied text.", evidence_refs=[])
                        else:
                            row.update(state="complete", outcome="supported", reasoning="Examined the supplied mathematics.")
                    task = next(t for t in prepared["manifest"]["work"]["tasks"] if t["kind"] == "composition")
                    finding = self.worker_finding(task["target"], task["id"])
                    if severity is not None:
                        finding["severity"] = severity
                    response["findings"] = [finding]
                    result = self.submit(db, fx, prepared, response)
                    self.assertEqual("accepted", result["state"], result)
                    saved = db.heads("findings")[0]
                    self.assertEqual(severity, saved.body.get("severity"))
                    self.assertEqual(severity is not None, "severity" in saved.body)
                    self.assertTrue(saved.body["check_refs"])

    def test_reconciliation_persists_rating_without_new_examination(self):
        fx = self.fixture().independent()
        with fx.open() as db:
            original = {r.id: (r.pinned, deepcopy(r.body)) for r in db.heads("checks")}
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile",
                                               focus=R("items", "itm_thm"))
            self.assertTrue(prepared["prepared"], prepared)
            response = deepcopy(prepared["scaffold"])
            for row in response["integrations"]:
                row.update(decision="agree", rationale="Retain the saved examination with the local correction.")
            task = prepared["manifest"]["work"]["tasks"][0]
            finding = self.worker_finding(task["target"], task["id"], severity="moderate")
            del finding["existing_check_refs"], finding["affected_uses"]
            response["findings"] = [finding]
            result = self.submit(db, fx, prepared, response)
            self.assertEqual("accepted", result["state"], result)
            self.assertEqual("moderate", db.heads("findings")[0].body["severity"])
            self.assertEqual(original, {r.id: (r.pinned, r.body) for r in db.heads("checks")})

    def test_edit_round_trip_preserves_fields_and_version_guards(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            body = self.body(severity="minor", check_refs=[db.head("checks", "chk_comp_thm").pinned])
            fx.apply(db, [edit("create", "findings", "fnd_rating", body)], "items:itm_thm", mode="primary")
            packet = fx.packet(db, "items:itm_thm", mode="reconcile")
            template = assistance.authoring_template("findings", packet_id=packet["packet_id"],
                                                     record_id="fnd_rating", db=db)
            entry = template["template"]["edits"][0]
            self.assertEqual(body, entry["body"])
            self.assertEqual("fnd_rating", entry["id"])
            entry["body"]["severity"] = "severe"
            review.reconcile(db, batch=template["template"])
            saved = db.head("findings", "fnd_rating")
            self.assertEqual(dict(body, severity="severe"), saved.body)
            self.assertEqual(2, saved.version)
            self.assertEqual(body, db.version("findings", saved.id, 1).body)
            with self.assertRaises(ConflictError):
                assistance.authoring_template("findings", packet_id=packet["packet_id"], record_id=saved.id, db=db)
            stale = deepcopy(template["template"])
            stale["request_id"] = fx.request_id()
            with self.assertRaises(ConflictError):
                review.reconcile(db, batch=stale)

    def test_rating_changes_storage_digest_but_only_scientific_changes_stale_binding(self):
        fx = self.fixture().primary()
        with fx.open() as db:
            body = self.body()
            fx.apply(db, [edit("create", "findings", "fnd_rating", body)], "items:itm_thm", mode="primary")
            finding = db.head("findings", "fnd_rating")
            self.assertEqual(digest(body), facet_digests("findings", body)["full"])
            binding = {"records": [{"ref": finding.pinned, "facet": "full", "digest": digest(body)}], "relations": []}
            packet = fx.packet(db, "items:itm_thm", mode="reconcile")
            review.reconcile(db, batch=fx.batch(
                [edit("replace", "findings", finding.id, dict(body, severity="minor"), 1)], packet["packet_id"]))
            self.assertEqual({"records": [], "relations": []}, binding_changes(State(db, []), binding))
            rows = db.conn.execute("SELECT body_digest FROM record_versions WHERE collection='findings' AND id=? ORDER BY version", (finding.id,)).fetchall()
            self.assertEqual([digest(body), digest(dict(body, severity="minor"))], [row[0] for row in rows])
            for changes in ({"description": "An actual different claim fails."},
                            {"category": "proof_gap"}, {"impact_reason": "The main rate changes."},
                            {"evidence_refs": ["anc_thm"]}, {"target": R("items", "itm_thm")},
                            {"resolution": "The issue was corrected.", "lifecycle": "resolved"}):
                changed = dict(body, severity="minor", **changes)
                self.assertNotEqual(digest(body), facet_digests("findings", changed)["full"])
            current = db.head("findings", finding.id)
            packet = fx.packet(db, "items:itm_thm", mode="reconcile")
            review.reconcile(db, batch=fx.batch([edit("replace", "findings", finding.id,
                dict(current.body, description="An actual different claim fails."), current.version)], packet["packet_id"]))
            self.assertEqual("full", binding_changes(State(db, []), binding)["records"][0]["facet"])
