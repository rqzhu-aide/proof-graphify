"""Existing examination recovery preserves records and uses supported workflows."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from support import R, TempCase, edit
from test_review_display import CurrentFixture
from paper_core import PROTOCOL_VERSION, acceptance, assistance, review, sources
from paper_core.errors import ConflictError


class CheckTemplateRecoveryTests(TempCase):
    def test_immutable_sources_ignore_missing_stale_and_current_packets_without_planning(self):
        fx = CurrentFixture(self.path("immutable")).primary()
        with fx.open() as db:
            stale = fx.packet(db)
            paper = db.head("papers", fx.paper_id)
            fx.apply(db, [edit("replace", "papers", paper.id,
                              dict(paper.body, title="Corrected display title"), paper.version)])
            current_packet = fx.packet(db)
            before = db.max_revision()
            for collection, identifier in (("observations", "obs_lem"),
                                           ("observations", "obs_exact_lem"),
                                           ("source_reviews", "srv_boundaries")):
                saved = db.head(collection, identifier)
                for packet_id in ("pkt_missing", stale["packet_id"], current_packet["packet_id"]):
                    with self.subTest(collection=collection, identifier=identifier, packet=packet_id), \
                            patch.object(db, "packet", side_effect=AssertionError("no packet lookup")), \
                            patch("paper_core.assessment.derive_full", side_effect=AssertionError("no assessment")):
                        with self.assertRaises(ConflictError) as caught:
                            assistance.authoring_template(collection, packet_id=packet_id, record_id=identifier, db=db)
                    error = caught.exception
                    self.assertEqual("ASSISTANCE_SOURCE_WORKFLOW", error.code)
                    self.assertEqual([saved.pinned], error.records)
                    target = R("items", "itm_lem") if identifier == "obs_lem" else R("papers", fx.paper_id)
                    self.assertEqual([target], error.retry["targets"])
                    self.assertEqual(f"get DB --target {target['collection']}:{target['id']} --mode author --out PACKET.json",
                                     error.retry["packet_command"])
                    self.assertEqual(f"template DB --collection {collection} --packet PACKET_ID --out TEMPLATE.json",
                                     error.retry["command"])
                    self.assertNotIn("--id", error.retry["command"])
                    self.assertIn("emitted template member", error.message)
                    self.assertIn("reuse adequate saved source inspection", error.message)
                    self.assertIn("available current author packet", error.message)
                    self.assertNotIn("supersedes", str(error.retry))
                    self.assertEqual(saved, db.head(collection, identifier))
            self.assertEqual(before, db.max_revision())

    def test_non_get_observation_targets_use_paper_fallback_without_ownership_search(self):
        for collection in ("uses", "target_specs"):
            record = SimpleNamespace(id="obs_saved", version=1, retired=False,
                pinned=dict(R("observations", "obs_saved"), version=1), body={"target": R(collection, "saved")})
            db = Mock()
            db.head.return_value = record
            db.heads.return_value = [SimpleNamespace(ref=R("papers", "pap_saved"))]
            with self.assertRaises(ConflictError) as caught:
                assistance.authoring_template("observations", packet_id="pkt_missing", record_id=record.id, db=db)
            self.assertEqual([R("papers", "pap_saved")], caught.exception.retry["targets"])
            db.packet.assert_not_called()
            db.heads.assert_called_once_with("papers")
            self.assertEqual(2, len(db.mock_calls))

    def test_successors_submit_through_existing_routes_and_only_selected_boundary_is_repinned(self):
        fx = CurrentFixture(self.path("successors")).primary()
        with fx.open() as db:
            old_observation = db.head("observations", "obs_lem")
            packet = fx.packet(db, "items:itm_lem")
            result = assistance.authoring_template("observations", packet_id=packet["packet_id"], db=db)
            row = result["template"]["edits"][0]
            row["body"] = dict(old_observation.body, note="Corrected source-comparison note.")
            review.compare(db, batch=result["template"])
            self.assertEqual("create", row["op"])
            self.assertEqual(old_observation, db.head("observations", old_observation.id))
            self.assertEqual(row["body"], db.head("observations", row["id"]).body)

            old_review = db.head("source_reviews", "srv_boundaries")
            packet = fx.packet(db)
            result = assistance.authoring_template("source_reviews", packet_id=packet["packet_id"], db=db)
            row = result["template"]["edits"][0]
            row["body"] = dict(old_review.body, rationale="Corrected rationale for the same inspected proof boundaries.")
            sources.review_sources(db, batch=result["template"])
            self.assertEqual(old_review, db.head("source_reviews", old_review.id))
            new_review = db.head("source_reviews", row["id"])
            other = db.head("proof_boundaries", "bnd_thm")
            packet = fx.packet(db, "items:itm_lem")
            result = assistance.authoring_template("proof_boundaries", packet_id=packet["packet_id"], record_id="bnd_lem", db=db)
            result["template"]["edits"][0]["body"]["source_review_ref"] = new_review.pinned
            acceptance.apply_batch(db, result["template"])
            self.assertEqual(new_review.pinned, db.head("proof_boundaries", "bnd_lem").body["source_review_ref"])
            self.assertEqual(other, db.head("proof_boundaries", "bnd_thm"))

    def test_unresolved_source_review_remains_editable_and_normal_stale_packet_is_rejected(self):
        fx = CurrentFixture(self.path("unresolved")).audit()
        with fx.open() as db:
            packet = fx.packet(db)
            original = db.head("source_reviews", "srv_boundaries")
            body = dict(original.body, decision="unresolved", rationale="A source boundary remains uncertain.")
            sources.review_sources(db, batch=fx.batch([edit("create", "source_reviews", "srv_open", body)], packet["packet_id"]))
            with self.assertRaises(ConflictError) as caught:
                assistance.authoring_template("source_reviews", packet_id=packet["packet_id"], record_id="srv_open", db=db)
            self.assertEqual("ASSISTANCE_PACKET", caught.exception.code)
            packet = fx.packet(db)
            result = assistance.authoring_template("source_reviews", packet_id=packet["packet_id"], record_id="srv_open", db=db)
            result["template"]["edits"][0]["body"]["rationale"] = "Clarified unresolved boundary rationale."
            sources.review_sources(db, batch=result["template"])
            self.assertEqual(2, db.head("source_reviews", "srv_open").version)

    def test_completed_coherent_check_has_conditional_integration_guidance_without_planning(self):
        fx = CurrentFixture(self.path("coherent")).primary()
        with fx.open() as db:
            check = db.head("checks", "chk_comp_lem")
            before = db.max_revision()
            with patch.object(db, "packet", side_effect=AssertionError("no replacement packet lookup")), \
                    patch("paper_core.assessment.derive_full", side_effect=AssertionError("no assessment")):
                with self.assertRaises(ConflictError) as caught:
                    assistance.authoring_template("checks", packet_id="pkt_old", record_id=check.id, db=db)
            error = caught.exception
            self.assertEqual("ASSISTANCE_CHECK_WORKFLOW", error.code)
            self.assertEqual([check.pinned], error.records)
            self.assertEqual({"command": f"stage2 status DB --audit {fx.audit_id}",
                "check_ref": check.pinned, "audit_id": fx.audit_id, "target": check.body["target"],
                "protocol_version": PROTOCOL_VERSION, "reviewer": check.body["reviewer"]}, error.retry)
            for text in ("If integration is pending", "ordinary integration", "--correct only when",
                         "explicit coordinator task IDs", "does not establish the integration status",
                         "Changed or stale scientific inputs", "adequate saved reasoning",
                         "does not repair a missing or partial examination"):
                self.assertIn(text, error.message)
            self.assertNotIn("get DB", error.message)
            self.assertNotIn("--mode author", str(error.retry))
            self.assertEqual(before, db.max_revision())
            self.assertEqual(check, db.head("checks", check.id))

    def test_legacy_completed_check_keeps_batch_reconciliation_route(self):
        check = SimpleNamespace(id="chk_saved", version=1, retired=False,
            ref=R("checks", "chk_saved"), pinned=dict(R("checks", "chk_saved"), version=1),
            body={"audit_id": "aud_legacy", "protocol_version": PROTOCOL_VERSION,
                  "role": "primary", "state": "complete", "reviewer": "saved-primary",
                  "target": R("arguments", "arg_saved")})
        db = Mock()
        db.head.side_effect = [check, SimpleNamespace(body={"protocol_version": "item-audit/1"})]
        with self.assertRaises(ConflictError) as caught:
            assistance.authoring_template("checks", packet_id="pkt_old", record_id=check.id, db=db)
        error = caught.exception
        self.assertEqual("work list DB --audit aud_legacy", error.retry["command"])
        self.assertEqual("item-audit/1", error.retry["protocol_version"])
        self.assertIn("work prepare --mode reconcile", error.message)
        self.assertIn("work submit", error.message)
        self.assertIn("returned batch scaffold", error.message)
        self.assertNotIn("--correct", error.message)
        self.assertNotIn("pin-free", error.message)

    def test_independent_draft_stays_in_assigned_submission_workflow(self):
        check = SimpleNamespace(id="chk_independent", version=1, retired=False,
            ref=R("checks", "chk_independent"),
            pinned=dict(R("checks", "chk_independent"), version=1),
            body={"audit_id": "aud_saved", "protocol_version": "item-audit/1",
                  "role": "independent", "state": "draft", "reviewer": "saved-reviewer",
                  "target": R("arguments", "arg_saved")})
        db = Mock()
        db.head.side_effect = [check, SimpleNamespace(body={"protocol_version": PROTOCOL_VERSION})]
        with self.assertRaises(ConflictError) as caught:
            assistance.authoring_template("checks", packet_id="pkt_old", record_id=check.id, db=db)
        error = caught.exception
        self.assertIn("independent draft remains unfinished", error.message)
        self.assertIn("assigned review-response and submission workflow", error.message)
        self.assertIn("not completed integration evidence", error.message)
        self.assertNotIn("ordinary integration", error.message)
        self.assertNotIn("--correct", error.message)
        self.assertEqual(PROTOCOL_VERSION, error.retry["protocol_version"])
        self.assertEqual("saved-reviewer", error.retry["reviewer"])
        db.packet.assert_not_called()
        db.heads.assert_not_called()
        self.assertEqual(2, len(db.mock_calls))

    def test_primary_draft_retry_uses_permitted_paper_primary_packet_and_remains_editable(self):
        fx = CurrentFixture(self.path("draft")).audit(independent_required=False)
        with fx.open() as db:
            draft = fx.check_edit("chk_draft", R("arguments", "arg_lem"), "composition",
                                  state="draft", outcome=None)
            fx.apply(db, [draft], "items:itm_lem", mode="primary")
            author = fx.packet(db, mode="author")
            with self.assertRaises(ConflictError) as caught:
                assistance.authoring_template("checks", packet_id=author["packet_id"], record_id="chk_draft", db=db)
            retry = caught.exception.retry
            self.assertEqual("ASSISTANCE_PACKET", caught.exception.code)
            self.assertEqual("primary", retry["mode"])
            self.assertEqual([R("papers", fx.paper_id)], retry["targets"])
            primary = fx.packet(db, f"papers:{fx.paper_id}", mode=retry["mode"])
            result = assistance.authoring_template("checks", packet_id=primary["packet_id"],
                                                  record_id="chk_draft", db=db)
            replacement = result["template"]["edits"][0]
            self.assertEqual("replace", replacement["op"])
            replacement["body"]["reasoning"] += " Saved draft clarification."
            acceptance.apply_batch(db, result["template"])
            self.assertEqual(2, db.head("checks", "chk_draft").version)
            self.assertEqual("draft", db.head("checks", "chk_draft").body["state"])

    def test_source_record_replacement_keeps_existing_author_route(self):
        fx = CurrentFixture(self.path("source")).audit()
        with fx.open() as db:
            packet = fx.packet(db, "items:itm_lem", mode="author")
            result = assistance.authoring_template("items", packet_id=packet["packet_id"], record_id="itm_lem", db=db)
            result["template"]["edits"][0]["body"]["caption"] = "Clarified caption"
            acceptance.apply_batch(db, result["template"])
            self.assertEqual("Clarified caption", db.head("items", "itm_lem").body["caption"])

    def test_finding_replacement_keeps_existing_reconcile_route(self):
        fx = CurrentFixture(self.path("finding")).primary()
        with fx.open() as db:
            fx.apply(db, [edit("create", "findings", "fnd_saved", {
                "audit_id": fx.audit_id, "target": R("groups", "grp_lem"),
                "category": "proof_gap", "lifecycle": "open", "description": "A saved concern.",
                "evidence_refs": ["anc_lem_proof"], "check_refs": [], "affected_uses": [],
                "impact_reason": "The proof requires clarification.", "resolution": None})],
                *fx.ITEMS, mode="primary")
            with self.assertRaises(ConflictError) as caught:
                assistance.authoring_template("findings", packet_id="pkt_missing", record_id="fnd_saved", db=db)
            self.assertEqual("reconcile", caught.exception.retry["mode"])
            packet = fx.packet(db, mode="reconcile")
            result = assistance.authoring_template("findings", packet_id=packet["packet_id"], record_id="fnd_saved", db=db)
            result["template"]["edits"][0]["body"]["description"] = "Clarified saved concern."
            review.reconcile(db, batch=result["template"])
            self.assertEqual("Clarified saved concern.", db.head("findings", "fnd_saved").body["description"])
