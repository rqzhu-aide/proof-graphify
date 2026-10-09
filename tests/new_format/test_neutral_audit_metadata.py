"""Neutral metadata preserves new mathematical bindings, never historical policy."""
import copy
from unittest.mock import patch

from support import Fixture, R, TempCase, edit
from paper_core import assessment, controller, review, sources, storage, work
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest


class SourceReuseMetadataTests(TempCase):
    def setup_premises(self, count=1, *, with_specs=True):
        self.sequence = getattr(self, "sequence", 0) + 1
        fx = self.fixture(f"paper-{self.sequence}").structure()
        db = fx.open()
        self.addCleanup(db.close)
        ids = [f"itm_setup_{n}" for n in range(count)]
        edits = [edit("create", "scopes", "scp_setup", {
            "argument_id": None, "parent_id": None,
            "assumptions": [R("items", iid) for iid in ids], "binders": [],
            "conditions": [], "evidence_refs": ["anc_lem"]})]
        for n, iid in enumerate(ids):
            row = Fixture.item_edit(iid, "assumption" if n == 0 else "definition",
                                    f"Premise {n}", "anc_lem", "anc_lem_proof")
            row["body"].update(scope_id="scp_setup", passages=[{"role": "statement", "anchor_id": "anc_lem"}])
            edits.append(row)
        # The source comparison of a consumer must keep the same setup current.
        theorem = db.head("items", "itm_thm")
        edits.append(edit("replace", "items", theorem.id, dict(theorem.body, scope_id="scp_setup"), theorem.version))
        fx.apply(db, edits)
        self.targets = ids + ["itm_thm"]
        if with_specs:
            fx.apply(db, [edit("create", "target_specs", "tgt_" + iid, self.spec(db, iid))
                          for iid in self.targets])
        self.fx, self.db = fx, db
        return fx, db

    def spec(self, db, iid):
        return {"target": R("items", iid), "statement_ref": db.head("items", iid).pinned,
                "statement": None, "scope_id": "scp_setup", "evidence_refs": ["anc_lem"],
                "state": "registered", "fidelity_ref": None}

    def compare(self, *, historical=False):
        fx, db = self.fx, self.db
        packet = fx.packet(db, mode="primary")
        batch = fx.batch([edit("create", "observations", "obs_" + iid, {
            "target": R("items", iid), "result": "matched", "reviewer": "fixture",
            "note": "Synthetic comparison of the source text and its complete setup.",
            "evidence_refs": ["anc_lem"]}) for iid in self.targets], packet["packet_id"])
        if historical:
            insert = db.insert_binding
            def historical_binding(collection, identifier, version, packet_id, binding):
                binding = dict(binding)
                binding.pop("semantic_memberships", None)
                return insert(collection, identifier, version, packet_id, binding)
            with patch.object(db, "insert_binding", side_effect=historical_binding):
                review.compare(db, batch=batch)
        else:
            review.compare(db, batch=batch)

    def attach(self):
        rows = []
        for iid in self.targets:
            old = self.db.head("target_specs", "tgt_" + iid)
            body = dict(old.body if old else self.spec(self.db, iid),
                        fidelity_ref=self.db.head("observations", "obs_" + iid).pinned)
            rows.append(edit("replace" if old else "create", "target_specs", "tgt_" + iid,
                             body, old.version if old else None))
        return self.fx.apply(self.db, rows)

    def freshness(self, iid="itm_setup_0"):
        return assessment.judgment_freshness(assessment.Snapshot(self.db, self.db.max_revision()),
            self.db.head("observations", "obs_" + iid), superseded=False)["freshness"]

    def test_self_premise_reference_attachment_preserves_comparison(self):
        self.setup_premises()
        self.compare()
        self.attach()
        self.assertTrue(all(self.freshness(iid) == "current" for iid in self.targets))

    def test_coherent_premise_and_consumer_reference_batch_preserves_comparisons(self):
        self.setup_premises(count=2)
        self.compare()
        originals = self.db.heads("observations")
        self.attach()
        self.assertEqual(originals, self.db.heads("observations"))
        self.assertTrue(all(self.freshness(iid) == "current" for iid in self.targets))
        for row in originals:
            semantic = self.db.binding("observations", row.id, row.version)["bindings"]["semantic_memberships"]
            self.assertEqual({"target_specs_for_target"}, {entry["relation"] for entry in semantic})

    def test_historical_comparison_keeps_strict_membership_policy(self):
        self.setup_premises()
        self.compare(historical=True)
        revision = self.db.max_revision()
        with self.assertRaises(InvalidRequest) as caught:
            self.attach()
        self.assertIn("current source examination", str(caught.exception.records))
        self.assertEqual(revision, self.db.max_revision())

    def test_new_specification_is_not_a_metadata_only_replacement(self):
        self.setup_premises(with_specs=False)
        self.compare()
        revision = self.db.max_revision()
        with self.assertRaises(InvalidRequest):
            self.attach()
        self.assertEqual(revision, self.db.max_revision())

    def test_changed_exact_premise_and_evidence_stale_comparisons(self):
        for field, value in (("statement", {"form": "transcription", "text": "A changed exact assertion"}),
                             ("evidence_refs", ["anc_lem", "anc_thm"])):
            with self.subTest(field=field):
                self.setup_premises()
                self.compare()
                spec = self.db.head("target_specs", "tgt_itm_setup_0")
                body = dict(spec.body, **{field: value})
                if field == "statement":
                    body["statement_ref"] = None
                self.fx.apply(self.db, [edit("replace", "target_specs", spec.id, body, spec.version)])
                self.assertNotEqual("current", self.freshness())
                self.assertNotEqual("current", self.freshness("itm_thm"))

    def test_changed_scope_and_consumed_source_stale_comparisons(self):
        self.setup_premises()
        self.compare()
        scope = self.db.head("scopes", "scp_setup")
        self.fx.apply(self.db, [edit("replace", "scopes", scope.id,
            dict(scope.body, conditions=["a new restriction"]), scope.version)])
        self.assertNotEqual("current", self.freshness())
        # Separate comparison after the scope change, then replace captured bytes.
        packet = self.fx.packet(self.db, mode="primary")
        review.compare(self.db, batch=self.fx.batch([edit("create", "observations", "obs_source", {
            "target": R("items", "itm_setup_0"), "result": "matched", "reviewer": "fixture",
            "note": "Synthetic renewed comparison.", "evidence_refs": ["anc_lem"]})], packet["packet_id"]))
        path = self.fx.source_root / "paper.tex"
        path.write_text(path.read_text(encoding="utf-8").replace("a_n", "b_n"), encoding="utf-8")
        sources.capture_sources(self.db, files=["paper.tex"])
        state = assessment.judgment_freshness(assessment.Snapshot(self.db, self.db.max_revision()),
            self.db.head("observations", "obs_source"), superseded=False)
        self.assertNotEqual("current", state["freshness"])


class QualificationMetadataTests(TempCase):
    def setup_audit(self, *, full=False):
        self.sequence = getattr(self, "sequence", 0) + 1
        fx = self.fixture(f"paper-{self.sequence}").audit(mode="full" if full else "focused")
        db = fx.open()
        self.addCleanup(db.close)
        audit = db.head("audits", fx.audit_id)
        body = dict(audit.body, qualification_id=None,
            targets=[] if full else audit.body["targets"], global_tasks=[dict(row,
            applicability="required" if row["kind"] != "method_interface" else "not_applicable")
            for row in audit.body["global_tasks"]])
        fx.apply(db, [edit("replace", "audits", audit.id, body, audit.version)], *fx.ITEMS, mode="primary")
        self.fx, self.db = fx, db

    def replace_audit(self, **changes):
        old = self.db.head("audits", self.fx.audit_id)
        self.fx.apply(self.db, [edit("replace", "audits", old.id, dict(old.body, **changes), old.version)],
                      *self.fx.ITEMS, mode="primary")

    def prepare_global_metadata_investigation(self):
        ids = [row["id"] for row in work.derive_work(self.db, audit_id=self.fx.audit_id)["tasks"]
               if row["target"] == R("audits", self.fx.audit_id) and row["required"]]
        return controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
            focus=R("audits", self.fx.audit_id), task_ids=ids,
            exception_purpose="Inspect global assignment freshness under audit metadata changes.",
            exception_limitations="Metadata binding investigation only; local proof work and review readiness are incomplete.")

    def save_globals(self, *, historical=False):
        rows = [self.fx.check_edit("chk_" + kind, R("audits", self.fx.audit_id), kind)
                for kind in ("global_consistency", "adversarial")]
        if historical:
            # Reproduce the historical full-audit binding at creation, without altering stored evidence.
            from paper_core.bindings import _Builder
            add = _Builder.add
            def old_facet(builder, collection, identifier, facet, **kwargs):
                return add(builder, collection, identifier, "full" if collection == "audits" else facet, **kwargs)
            with patch.object(_Builder, "add", old_facet):
                self.fx.apply(self.db, rows, "audits:" + self.fx.audit_id, mode="primary")
        else:
            self.fx.apply(self.db, rows, "audits:" + self.fx.audit_id, mode="primary")

    def freshness(self, kind="global_consistency"):
        return assessment.judgment_freshness(assessment.Snapshot(self.db, self.db.max_revision()),
            self.db.head("checks", "chk_" + kind), superseded=False)["freshness"]

    def test_qualification_attachment_preserves_saved_globals_for_focused_and_full_audits(self):
        for full in (False, True):
            with self.subTest(full=full):
                self.setup_audit(full=full)
                self.save_globals()
                before = self.db.binding("checks", "chk_global_consistency", 1)["bindings"]
                self.replace_audit(qualification_id="qua_r1")
                self.assertEqual("current", self.freshness())
                self.assertEqual("current", self.freshness("adversarial"))
                self.assertEqual(before, self.db.binding("checks", "chk_global_consistency", 1)["bindings"])

    def test_historical_full_audit_binding_remains_conservative(self):
        self.setup_audit()
        self.save_globals(historical=True)
        self.replace_audit(qualification_id="qua_r1")
        self.assertNotEqual("current", self.freshness())

    def test_new_global_check_can_consume_a_preexisting_audit_without_stored_proof_facet(self):
        insert = storage.Database.insert_facets
        def historical_facets(db, collection, identifier, version, facets):
            if collection == "audits":
                facets = {name: value for name, value in facets.items() if name != "proof"}
            return insert(db, collection, identifier, version, facets)
        with patch.object(storage.Database, "insert_facets", historical_facets):
            self.setup_audit()
        audit = self.db.head("audits", self.fx.audit_id)
        self.assertNotIn("proof", self.db.facets("audits", audit.id, audit.version))
        self.save_globals()
        self.assertEqual("current", self.freshness())
        self.replace_audit(qualification_id="qua_r1")
        self.assertEqual("current", self.freshness())

    def test_prepared_global_response_survives_qualification_attachment_unchanged(self):
        self.setup_audit()
        prepared = self.prepare_global_metadata_investigation()
        self.assertTrue(prepared["prepared"], prepared)
        response = copy.deepcopy(prepared["scaffold"])
        for row in response["results"]:
            row.update(state="complete", outcome="supported", reasoning="Synthetic global examination.", evidence_refs=[])
        raw = canonical_bytes(response)
        self.replace_audit(qualification_id="qua_r1")
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "fixture", "qualification_id": None,
            "exposure": None, "exposure_note": ""}
        receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
        self.assertEqual("accepted", receipt["state"], receipt)
        saved = self.db.work_submission(envelope["request_id"])
        self.assertEqual(raw, self.db.get_blob(saved["response_sha256"]))

    def local_response(self, prepared, variant):
        response = copy.deepcopy(prepared["scaffold"])
        for row in response["results"]:
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Synthetic source comparison.", evidence_refs=["anc_lem"])
            else:
                row.update(state="complete", outcome="supported", reasoning="Synthetic primary examination.",
                           evidence_refs=["anc_lem_proof"])
        if variant == "source_only":
            response["results"] = [r for r in response["results"] if r["type"] == "source_fidelity"]
        elif variant == "findings_only":
            response["results"] = []
            response["findings"] = [{"target": R("items", "itm_lem"), "category": "presentation",
                "description": "Clarify the notation.", "evidence_refs": ["anc_lem"],
                "related_task_ids": [], "existing_check_refs": [], "affected_uses": [],
                "impact_reason": "Readers need a consistent convention."}]
        elif variant == "coverage_only":
            response["results"] = []
            response["coverage"] = [{"argument_id": "arg_lem", "anchor_id": "anc_lem_proof",
                "start_offset": 0, "end_offset": 1, "classification": "structural",
                "claim_refs": [], "check_task_ids": [], "existing_check_refs": [], "replaces": None,
                "note": "Synthetic leading structural character, not the substantive proof."}]
        return response

    def test_prepared_local_primary_work_survives_qualification_change_with_original_bytes(self):
        for variant in ("source_only", "checks", "findings_only", "coverage_only"):
            for before, after in ((None, "qua_r1"), ("qua_r1", None)):
                with self.subTest(variant=variant, before=before, after=after):
                    self.setup_audit()
                    if before:
                        self.replace_audit(qualification_id=before)
                    prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
                                                       focus=R("items", "itm_lem"))
                    self.assertTrue(prepared["prepared"], prepared)
                    raw = canonical_bytes(self.local_response(prepared, variant))
                    self.replace_audit(qualification_id=after)
                    envelope = {"contract_version": 4, "request_id": self.fx.request_id(),
                        "packet_id": prepared["packet_id"], "rebase_packet_id": None, "reviewer": "fixture",
                        "qualification_id": None, "exposure": None, "exposure_note": ""}
                    receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                                     response_bytes=raw)
                    self.assertEqual("accepted", receipt["state"], receipt)
                    saved = self.db.work_submission(envelope["request_id"])
                    self.assertEqual(raw, self.db.get_blob(saved["response_sha256"]))

    def test_primary_qualification_neutrality_does_not_hide_changed_mathematics_or_scope(self):
        for change in ("source", "statement", "protocol", "scope"):
            with self.subTest(change=change):
                self.setup_audit()
                prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary",
                                                   focus=R("items", "itm_lem"))
                raw = canonical_bytes(self.local_response(prepared, "checks"))
                self.replace_audit(qualification_id="qua_r1")
                if change == "source":
                    path = self.fx.source_root / "paper.tex"
                    path.write_text(path.read_text(encoding="utf-8").replace("a_n", "b_n"), encoding="utf-8")
                    sources.capture_sources(self.db, files=["paper.tex"])
                elif change == "statement":
                    item = self.db.head("items", "itm_lem")
                    self.fx.apply(self.db, [edit("replace", "items", item.id,
                        dict(item.body, statement={"form": "verbatim", "text": "Changed assertion"}), item.version)])
                else:
                    self.replace_audit(**({"protocol_version": "item-audit/next"} if change == "protocol"
                                         else {"targets": [R("items", "itm_thm")]}))
                envelope = {"contract_version": 4, "request_id": self.fx.request_id(),
                    "packet_id": prepared["packet_id"], "rebase_packet_id": None, "reviewer": "fixture",
                    "qualification_id": None, "exposure": None, "exposure_note": ""}
                revision = self.db.max_revision()
                receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
                self.assertEqual("conflict", receipt["state"], receipt)
                self.assertEqual(revision, self.db.max_revision())

    def test_prepared_global_finding_preserves_only_qualification_neutrality(self):
        for changes, expected in (({"qualification_id": "qua_r1"}, "accepted"),
                                  ({"report_path": "another-report.html"}, "conflict"),
                                  ({"protocol_version": "item-audit/next"}, "conflict")):
            with self.subTest(changes=changes):
                self.setup_audit()
                prepared = self.prepare_global_metadata_investigation()
                self.assertTrue(prepared["prepared"], prepared)
                response = copy.deepcopy(prepared["scaffold"])
                for row in response["results"]:
                    row.update(state="complete", outcome="supported", reasoning="Synthetic global examination.",
                               evidence_refs=[])
                response["findings"] = [{"target": R("audits", self.fx.audit_id), "category": "presentation",
                    "description": "Clarify global notation.", "evidence_refs": [],
                    "related_task_ids": [response["results"][0]["task_id"]], "existing_check_refs": [],
                    "affected_uses": [], "impact_reason": "Readers need a consistent convention."}]
                raw = canonical_bytes(response)
                self.replace_audit(**changes)
                envelope = {"contract_version": 4, "request_id": self.fx.request_id(),
                    "packet_id": prepared["packet_id"], "rebase_packet_id": None, "reviewer": "fixture",
                    "qualification_id": None, "exposure": None, "exposure_note": ""}
                revision = self.db.max_revision()
                receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
                self.assertEqual(expected, receipt["state"], receipt)
                if expected == "conflict":
                    self.assertEqual(revision, self.db.max_revision())
                saved = self.db.work_submission(envelope["request_id"])
                self.assertEqual(raw, self.db.get_blob(saved["response_sha256"]))

    def test_historical_prepared_global_assignment_keeps_full_audit_guard(self):
        self.setup_audit()
        from paper_core.bindings import _Builder
        add = _Builder.add
        def old_facet(builder, collection, identifier, facet, **kwargs):
            return add(builder, collection, identifier, "full" if collection == "audits" else facet, **kwargs)
        with patch.object(_Builder, "add", old_facet):
            prepared = self.prepare_global_metadata_investigation()
        self.assertTrue(prepared["prepared"], prepared)
        response = copy.deepcopy(prepared["scaffold"])
        for row in response["results"]:
            row.update(state="complete", outcome="supported", reasoning="Synthetic global examination.", evidence_refs=[])
        self.replace_audit(qualification_id="qua_r1")
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "fixture", "qualification_id": None,
            "exposure": None, "exposure_note": ""}
        revision = self.db.max_revision()
        receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                         response_bytes=canonical_bytes(response))
        self.assertEqual("conflict", receipt["state"], receipt)
        self.assertEqual(revision, self.db.max_revision())

    def test_prepared_independent_assignment_keeps_qualification_configuration_guard(self):
        self.setup_audit()
        self.replace_audit(qualification_id="qua_r1")
        prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="independent",
            focus=R("items", "itm_lem"),
            exception_purpose="Inspect independent assignment guards when qualification configuration changes.",
            exception_limitations="Qualification freshness investigation only; primary proof work is incomplete.")
        self.assertTrue(prepared["prepared"], prepared)
        response = {"packet_id": prepared["packet_id"], "covered_targets": [R("items", "itm_lem")],
            "coverage_note": "Synthetic source examination.",
            "exposure_report": {"status": "none_known", "note": ""}, "judgments": [{
            "target": {"source_anchor_id": "anc_lem_proof", "description": "Whole written proof"},
            "kind": "composition", "state": "complete", "outcome": "supported",
            "reasoning": "Synthetic independent examination.", "evidence_refs": ["anc_lem_proof"],
            "conditions": [], "next_action": None, "supersedes": None}]}
        self.replace_audit(qualification_id=None)
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": self.db.head("qualifications", "qua_r1").body["reviewer"],
            "qualification_id": "qua_r1", "exposure": "source_only", "exposure_note": ""}
        receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                         response_bytes=canonical_bytes(response))
        self.assertEqual("conflict", receipt["state"], receipt)

    def test_prepared_reconciliation_keeps_qualification_configuration_guard(self):
        self.fx = self.fixture().independent()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)
        prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="reconcile",
                                           focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        response = copy.deepcopy(prepared["scaffold"])
        response["edits"] = [self.fx.reconciliation_edit(self.db, "rec_metadata", "arg_lem",
            "chk_comp_lem", self.fx.independent_checks["itm_lem"])]
        self.replace_audit(qualification_id=None)
        envelope = {"contract_version": 4, "request_id": response["request_id"], "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "fixture", "qualification_id": None,
            "exposure": None, "exposure_note": ""}
        receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope),
                                         response_bytes=canonical_bytes(response))
        self.assertEqual("conflict", receipt["state"], receipt)

    def test_other_audit_fields_and_consumed_statement_remain_consequential(self):
        changes = ({"report_path": "another-report.html"}, {"mode": "full"},
                   {"protocol_version": "item-audit/next"},
                   {"targets": [R("items", "itm_lem")]}, {"exclusions": [{"target": R("items", "itm_thm"),
                    "source_anchor_ids": [], "reason": "Excluded target", "consequence": "Limited audit"}]})
        for change in changes:
            with self.subTest(change=change):
                self.setup_audit()
                self.save_globals()
                self.replace_audit(**change)
                self.assertNotEqual("current", self.freshness())
        self.setup_audit()
        self.save_globals()
        item = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "items", item.id,
            dict(item.body, statement={"form": "verbatim", "text": "Changed source assertion"}), item.version)])
        self.assertNotEqual("current", self.freshness())

    def test_independent_qualification_gate_remains_separate(self):
        self.setup_audit()
        self.save_globals()
        before = work.derive_work(self.db, audit_id=self.fx.audit_id)
        self.assertIn("qualification_required", {row["code"] for row in before["coordinator_actions"]})
        qualified = self.db.head("qualifications", "qua_r1")
        review.record_qualification(self.db, receipt={"contract_version": 4,
            "request_id": self.fx.request_id(), "edits": [edit("create", "qualifications", "qua_unqualified",
            dict(qualified.body, qualified=False))], "blobs": []})
        self.replace_audit(qualification_id="qua_unqualified")
        self.assertEqual("current", self.freshness())
        blocked = work.derive_work(self.db, audit_id=self.fx.audit_id)
        self.assertIn("qualification_required", {row["code"] for row in blocked["coordinator_actions"]})
        review.record_qualification(self.db, receipt={"contract_version": 4,
            "request_id": self.fx.request_id(), "edits": [edit("create", "qualifications", "qua_other_protocol",
            dict(qualified.body, protocol_version="item-audit/next"))], "blobs": []})
        packet = self.fx.packet(self.db, "items:itm_lem", mode="independent")
        for qid, reviewer in (("qua_unqualified", qualified.body["reviewer"]), ("qua_r1", "another-reviewer"),
                              ("qua_other_protocol", qualified.body["reviewer"]), ("qua_missing", qualified.body["reviewer"])):
            with self.subTest(qualification=qid, reviewer=reviewer), self.assertRaises(InvalidRequest):
                review.submit_review(self.db, submission={"contract_version": 4,
                    "request_id": self.fx.request_id(), "packet_id": packet["packet_id"], "reviewer": reviewer,
                    "qualification_id": qid, "exposure": "source_only", "exposure_note": ""}, response_bytes=b"{}")

    def test_full_global_binds_implicit_statement_and_inventory(self):
        for change in ("statement", "add", "retire"):
            with self.subTest(change=change):
                self.setup_audit(full=True)
                extra = Fixture.item_edit("itm_extra", "assumption", "Extra premise", "anc_lem", "anc_lem_proof")
                if change == "retire":
                    self.fx.apply(self.db, [extra])
                self.save_globals()
                original_revision = self.db.max_revision()
                original = self.db.binding("checks", "chk_global_consistency", 1)
                if change == "statement":
                    item = self.db.head("items", "itm_lem")
                    edits = [edit("replace", "items", item.id,
                        dict(item.body, statement={"form": "verbatim", "text": "Changed assertion"}), item.version)]
                elif change == "add":
                    edits = [extra]
                else:
                    edits = [{"op": "retire", "collection": "items", "id": "itm_extra",
                              "expected_version": 1, "reason": "Remove this unused premise"}]
                self.fx.apply(self.db, edits)
                self.assertEqual("needs_review", self.freshness())
                self.assertEqual(original, self.db.binding("checks", "chk_global_consistency", 1))
                old = assessment.Snapshot(self.db, original_revision)
                self.assertEqual("current", assessment.judgment_freshness(old,
                    old.live("checks", "chk_global_consistency"), superseded=False)["freshness"])

    def test_full_global_exclusion_is_respected(self):
        self.setup_audit(full=True)
        self.replace_audit(exclusions=[{"target": R("items", "itm_thm"), "source_anchor_ids": [],
            "reason": "This theorem is outside this examination", "consequence": "No conclusion on it"}])
        self.save_globals()
        item = self.db.head("items", "itm_thm")
        self.fx.apply(self.db, [edit("replace", "items", item.id,
            dict(item.body, statement={"form": "verbatim", "text": "Excluded assertion changed"}), item.version)])
        self.assertEqual("current", self.freshness())

    def test_full_global_captures_new_implicit_part_in_same_batch(self):
        self.setup_audit(full=True)
        part = {"item_id": "itm_new", "label": "Part (i)",
            "statement": {"form": "verbatim", "text": "A newly registered subclaim"},
            "passages": [{"role": "statement", "anchor_id": "anc_lem"}], "scope_id": None, "origin": "source"}
        self.fx.apply(self.db, [
            Fixture.item_edit("itm_new", "lemma", "New lemma", "anc_lem", "anc_lem_proof"),
            edit("create", "parts", "prt_new", part),
            self.fx.check_edit("chk_global_consistency", R("audits", self.fx.audit_id), "global_consistency")],
            mode="primary")
        bound = self.db.binding("checks", "chk_global_consistency", 1)["bindings"]
        scope = next(row for row in bound["semantic_memberships"] if row["relation"] == "audit_scope")
        self.assertIn(["items", "itm_new"], scope["members"])
        self.assertIn(["parts", "prt_new"], scope["members"])
        self.assertEqual("current", self.freshness())
        self.fx.apply(self.db, [edit("replace", "parts", "prt_new",
            dict(part, statement={"form": "verbatim", "text": "The subclaim changed"}), 1)])
        self.assertEqual("needs_review", self.freshness())

    def test_full_global_preparation_includes_scope_and_rejects_inventory_addition(self):
        self.setup_audit(full=True)
        prepared = self.prepare_global_metadata_investigation()
        self.assertTrue(prepared["prepared"], prepared)
        supplied = {(r["collection"], r["id"]) for r in prepared["manifest"]["read_set"]}
        self.assertTrue({("items", "itm_lem"), ("items", "itm_thm")} <= supplied)
        response = copy.deepcopy(prepared["scaffold"])
        for row in response["results"]:
            row.update(state="complete", outcome="supported", reasoning="Synthetic global examination.", evidence_refs=[])
        raw = canonical_bytes(response)
        self.fx.apply(self.db, [Fixture.item_edit("itm_extra", "assumption", "New premise", "anc_lem", "anc_lem_proof")])
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "fixture", "qualification_id": None,
            "exposure": None, "exposure_note": ""}
        revision = self.db.max_revision()
        receipt = controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
        self.assertEqual("conflict", receipt["state"], receipt)
        self.assertEqual(revision, self.db.max_revision())
        self.assertIn("audit_scope", str(receipt))
        saved = self.db.work_submission(envelope["request_id"])
        self.assertEqual(raw, self.db.get_blob(saved["response_sha256"]))

    def test_historical_full_global_without_scope_requires_explicit_renewal(self):
        self.setup_audit(full=True)
        insert = self.db.insert_binding
        def historical_binding(collection, identifier, version, packet_id, binding):
            binding = copy.deepcopy(binding)
            for name in ("relations", "semantic_memberships"):
                binding[name] = [r for r in binding.get(name, []) if r["relation"] != "audit_scope"]
            return insert(collection, identifier, version, packet_id, binding)
        with patch.object(self.db, "insert_binding", side_effect=historical_binding):
            self.save_globals()
        before = self.db.binding("checks", "chk_global_consistency", 1)
        self.assertEqual("needs_review", self.freshness())
        self.replace_audit(qualification_id="qua_r1")
        self.assertEqual("needs_review", self.freshness())
        self.assertEqual(before, self.db.binding("checks", "chk_global_consistency", 1))
        derived = work.derive_work(self.db, audit_id=self.fx.audit_id)
        task = next(t for t in derived["tasks"] if t["kind"] == "global_consistency")
        self.assertNotEqual("satisfied", task["state"])
        self.assertIn("did not capture the full audit scope", task["recovery"]["next_action"])
        self.assertIn("explicit successors", task["recovery"]["next_action"])
        from paper_core import projection
        projected = projection.build_projection(self.db, audit_id=self.fx.audit_id)
        self.assertTrue(projected)

    def test_full_scope_feature_rejects_older_readers(self):
        self.setup_audit(full=True)
        self.save_globals()
        from paper_core import AUDIT_SCOPE_BINDING_FEATURE
        from paper_core.errors import IncompatibleError
        older = tuple(name for name in storage.SUPPORTED_FEATURES if name != AUDIT_SCOPE_BINDING_FEATURE)
        with patch.object(storage, "SUPPORTED_FEATURES", older), self.assertRaises(IncompatibleError):
            storage.Database(self.fx.path, write=False)

    def test_unbound_full_global_requires_renewal_in_work_and_projection(self):
        self.setup_audit(full=True)
        insert = self.db.insert_binding
        def omit_global_binding(collection, identifier, version, packet_id, binding):
            if collection == "checks":
                return None
            return insert(collection, identifier, version, packet_id, binding)
        with patch.object(self.db, "insert_binding", side_effect=omit_global_binding):
            self.save_globals()
        self.assertIsNone(self.db.binding("checks", "chk_global_consistency", 1))
        info = assessment.judgment_freshness(assessment.Snapshot(self.db, self.db.max_revision()),
            self.db.head("checks", "chk_global_consistency"), superseded=False)
        self.assertEqual("needs_review", info["freshness"])
        self.assertTrue(info["unbound"])
        derived = work.derive_work(self.db, audit_id=self.fx.audit_id)
        task = next(t for t in derived["tasks"] if t["kind"] == "global_consistency")
        self.assertNotEqual("satisfied", task["state"])
        self.assertIn("did not capture the full audit scope", task["recovery"]["next_action"])
        from paper_core import projection
        self.assertTrue(projection.build_projection(self.db, audit_id=self.fx.audit_id))

    def test_full_scope_prepare_preflights_only_structural_bodies(self):
        self.setup_audit(full=True)
        # A large historical judgment is not needed to select the audit's scope.
        check = self.fx.check_edit("chk_large", R("groups", "grp_lem"), "derivation")
        check["body"]["reasoning"] = "Historical examination. " * 20000
        self.fx.apply(self.db, [check], mode="primary")
        from paper_core.packets import _ContextLimit, _WorkState
        state = _WorkState(self.db, max_bytes=50000)
        self.assertTrue(state.relation_members("audit_scope", R("audits", self.fx.audit_id)))
        with self.assertRaises(_ContextLimit):
            _WorkState(self.db, max_bytes=100).relation_members("audit_scope", R("audits", self.fx.audit_id))
        with patch.object(assessment, "_scope_snapshot_sql", wraps=assessment._scope_snapshot_sql) as build:
            state = _WorkState(self.db, max_bytes=50000)
            state.relation_members("audit_scope", R("audits", self.fx.audit_id))
            state.relation_members("audit_scope", R("audits", self.fx.audit_id))
            self.assertEqual(1, build.call_count)
