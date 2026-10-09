"""Neutral source selection and immutable independent work-context recovery."""
import json
from unittest import mock

from support import R, TempCase, edit, locator
from test_work_packets import intermediate_edits, record_keys, selection, task
from test_review import entry, judgment, mapping_request, source_target, worker_response
from paper_core import controller, packets, review, sources, storage, WORK_CONTEXT_EXTENSION_FEATURE
from paper_core.canonical import canonical_bytes
from paper_core.errors import ConflictError, IncompatibleError, InvalidRequest


class ContextExtensionTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()

    def prepare(self, db, *, target="itm_thm", max_bytes=131072):
        selected = selection((task("independent_composition", R("arguments", "arg_" + target[4:]),
                                   "composition", role="independent"),))
        return packets.prepare_assignment(db, audit_id="aud_1", mode="independent", selection=selected,
                                          max_bytes=max_bytes)

    def request(self, db, *refs):
        return {"source_refs": [db.head(c, i).pinned for c, i in refs], "reason": "Exact neutral source is missing."}

    def counts(self, db):
        return (db.max_revision(), db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0],
                db.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0],
                db.conn.execute("SELECT value FROM metadata WHERE key='features'").fetchone()[0])

    def capture_extra(self, db, text="Additional neutral statement.", name="extra.tex", anchor="anc_extra"):
        (self.fx.source_root / name).write_text(text, encoding="utf-8")
        source = sources.capture_sources(db, files=[name])["sources"][0]["id"]
        authority = self.fx.packet(db)
        sources.anchor_sources(db, request={"contract_version": 4, "request_id": self.fx.request_id(),
            "packet_id": authority["packet_id"], "anchors": [{"id": anchor, "expected_version": None,
            "source_id": source, "locator": locator(start=1, end=1)}]})
        return source

    def test_internal_supplier_statement_without_supplier_proof(self):
        with self.fx.open() as db:
            result = self.prepare(db)
            keys = record_keys(result["packet"])
            self.assertIn(("items", "itm_lem"), keys)
            self.assertIn(("anchors", "anc_lem"), keys)
            self.assertNotIn(("anchors", "anc_lem_proof"), keys)
            self.assertNotIn(("arguments", "arg_lem"), keys)
            self.assertFalse(packets.blinding_violations(result["packet"]))

    def test_proof_ideas_stay_out_of_independent_assignments_and_neutral_extensions(self):
        with self.fx.open() as db:
            ideas = {identity: f"Authored proof outline for {identity}." for identity in ("itm_lem", "itm_thm")}
            edits = []
            for identity, idea in ideas.items():
                item = db.head("items", identity)
                edits.append(edit("replace", "items", identity, dict(item.body, proof_idea=idea), item.version))
            self.fx.apply(db, edits)
            original = self.prepare(db, target="itm_lem")
            extended = packets.extend_work_assignment(db, packet_id=original["packet_id"],
                request=self.request(db, ("items", "itm_thm")))
            for result in (original, extended, self.prepare(db)):
                raw = canonical_bytes(result["packet"])
                self.assertNotIn(b"proof_idea", raw)
                self.assertFalse(packets.blinding_violations(result["packet"]))
                self.assertEqual(result["size"]["worker_bytes"], len(raw))
                self.assertTrue(any(row["ref"]["collection"] == "items" for row in result["packet"]["records"]))
            for identity, idea in ideas.items():
                self.assertEqual(db.head("items", identity).body["proof_idea"], idea)

    def test_intermediate_context_extension_retains_private_target_and_passage_binding(self):
        with self.fx.open() as db:
            self.fx.apply(db, intermediate_edits(self.fx, origin="reconstruction"))
            self.capture_extra(db)
            original = self.prepare(db, target="itm_step")
            extended = packets.extend_work_assignment(db, packet_id=original["packet_id"],
                request=self.request(db, ("anchors", "anc_extra")))
            self.assertEqual(original["assigned_task_ids"], extended["assigned_task_ids"])
            self.assertEqual(R("arguments", "arg_step"), extended["manifest"]["work"]["tasks"][0]["target"])
            self.assertEqual(original["packet"]["targets"], extended["packet"]["targets"])
            self.assertIn(("anchors", "anc_extra"), record_keys(extended["packet"]))
            self.assertFalse(packets.blinding_violations(extended["packet"]))
            self.assertNotIn("itm_step", canonical_bytes(extended["packet"]).decode("utf-8"))
            selectors = extended["manifest"]["work"]["source_context_inputs"]
            self.assertTrue(any(row["ref"]["id"] == "arg_step" and row.get("source_passage_selection") == 1
                                for row in selectors))
            with self.assertRaises(InvalidRequest) as caught:
                controller._validate_rebase(original["manifest"], extended["manifest"])
            self.assertEqual("NEW_CONTEXT_RESPONSE_REQUIRED", caught.exception.code)
            worker = worker_response(extended["packet_id"],
                [judgment(source_target("anc_lem_proof", "The captured local argument"))],
                covered=[R("items", "itm_thm")])
            envelope = {"contract_version": 4, "request_id": self.fx.request_id(),
                "packet_id": extended["packet_id"], "rebase_packet_id": None,
                "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "source_only",
                "exposure_note": "Fresh source-only reviewer."}
            pending = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope),
                                             response_bytes=canonical_bytes(worker))
            private = self.fx.packet(db, "items:itm_thm", mode="reconcile")
            mapped = review.map_response(db, mapping=mapping_request(self.fx, private["packet_id"],
                pending["response_id"], [entry(0, R("arguments", "arg_step"))]))
            self.assertEqual("accepted", mapped["state"])

    def test_borrowed_argument_includes_its_proof(self):
        with self.fx.open() as db:
            use = db.head("uses", "use_lem_thm")
            self.fx.apply(db, [edit("replace", "uses", use.id, dict(use.body, type="proof_argument"), use.version)])
            self.assertIn(("anchors", "anc_lem_proof"), record_keys(self.prepare(db)["packet"]))

    def test_unrelated_background_does_not_enlarge_assignment(self):
        with self.fx.open() as db:
            before = self.prepare(db)
            self.fx.apply(db, [self.fx.item_edit(f"itm_background{i}", "definition", f"Definition {i}",
                                               "anc_lem", "anc_lem_proof") for i in range(100)])
            after = self.prepare(db)
            self.assertEqual(record_keys(before["packet"]), record_keys(after["packet"]))
            self.assertEqual(before["size"]["source_excerpt_bytes"], after["size"]["source_excerpt_bytes"])

    def test_source_setup_is_selected_and_privately_bound(self):
        with self.fx.open() as db:
            scope = db.head("scopes", "scp_plain")
            self.fx.apply(db, [self.fx.item_edit("itm_setup", "assumption", "Standing setup", "anc_lem", "anc_lem_proof"),
                edit("replace", "scopes", scope.id, dict(scope.body, assumptions=[R("items", "itm_setup")]), scope.version)])
            result = self.prepare(db)
            self.assertIn(("items", "itm_setup"), record_keys(result["packet"]))
            raw = canonical_bytes(result["packet"]).decode("utf-8")
            self.assertNotIn("source_context_inputs", raw)
            self.assertNotIn('"collection":"scopes"', raw)
            scope = db.head("scopes", "scp_plain")
            self.fx.apply(db, [edit("replace", "scopes", scope.id, dict(scope.body, conditions=["new condition"]), scope.version)])
            with self.assertRaises(ConflictError):
                packets.extend_work_assignment(db, packet_id=result["packet_id"],
                                               request=self.request(db, ("anchors", "anc_lem_proof")))

    def attach_exact_setup(self, db, target, anchor):
        self.fx.apply(db, [edit("create", "scopes", "scp_exact", {
            "argument_id": None, "parent_id": "scp_plain", "assumptions": [], "binders": [],
            "conditions": ["Exact target setup"], "evidence_refs": [anchor]})])
        spec = db.head("target_specs", "tgt_" + target[4:])
        self.fx.apply(db, [edit("replace", "target_specs", spec.id,
            dict(spec.body, scope_id="scp_exact"), spec.version)])

    def assert_exact_setup(self, prepared, anchor):
        self.assertIn(("anchors", anchor), record_keys(prepared["packet"]))
        bound = prepared["manifest"]["work"]["source_context_inputs"]
        self.assertTrue(any(row["ref"]["id"] == "scp_exact" for row in bound))
        self.assertFalse(packets.blinding_violations(prepared["packet"]))
        raw = canonical_bytes(prepared["packet"]).decode("utf-8")
        self.assertNotIn('"collection":"target_specs"', raw)
        self.assertNotIn('"collection":"scopes"', raw)
        self.assertNotIn("setup_digest", raw)

    def test_exact_target_only_setup_is_delivered_without_private_specification(self):
        with self.fx.open() as db:
            self.assertIsNone(db.head("items", "itm_lem").body["scope_id"])
            self.attach_exact_setup(db, "itm_lem", "anc_thm")
            prepared = self.prepare(db, target="itm_lem")
            self.assert_exact_setup(prepared, "anc_thm")
            self.assertFalse(prepared["packet"]["omitted"])

    def test_supplier_exact_setup_is_delivered_without_supplier_proof(self):
        with self.fx.open() as db:
            self.capture_extra(db)
            self.attach_exact_setup(db, "itm_lem", "anc_extra")
            prepared = self.prepare(db)
            self.assert_exact_setup(prepared, "anc_extra")
            self.assertNotIn(("anchors", "anc_lem_proof"), record_keys(prepared["packet"]))

    def test_context_extension_selects_exact_setup_and_keeps_its_relation(self):
        with self.fx.open() as db:
            original = self.prepare(db, target="itm_lem")
            self.attach_exact_setup(db, "itm_thm", "anc_thm_proof")
            extended = packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                                      request=self.request(db, ("items", "itm_thm")))
            self.assert_exact_setup(extended, "anc_thm_proof")
            guards = extended["manifest"]["work"]["source_context_relations"]
            self.assertTrue(any(row["relation"] == "target_specs_for_target" and row["key"] == R("items", "itm_thm")
                                for row in guards))

    def test_exact_setup_without_source_reports_missing_context(self):
        with self.fx.open() as db:
            self.attach_exact_setup(db, "itm_lem", "anc_thm")
            scope = db.head("scopes", "scp_exact")
            self.fx.apply(db, [edit("replace", "scopes", scope.id, dict(scope.body, evidence_refs=[]), scope.version)])
            prepared = self.prepare(db, target="itm_lem")
            self.assertTrue(any("no captured source passage" in row["reason"] for row in prepared["packet"]["omitted"]))

    def test_new_captured_source_and_chained_extensions_preserve_original_work(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            saved = db.packet(original["packet_id"])
            original_blob = db.get_blob(saved["payload_sha256"])
            self.assertNotIn(WORK_CONTEXT_EXTENSION_FEATURE, json.loads(db.metadata["features"]))
            self.capture_extra(db)
            request = self.request(db, ("anchors", "anc_extra"))
            extended = packets.extend_work_assignment(db, packet_id=original["packet_id"], request=request)
            self.assertTrue(extended["prepared"], extended)
            self.assertEqual(original["assigned_task_ids"], extended["assigned_task_ids"])
            self.assertEqual(original["manifest"]["work"]["tasks"], extended["manifest"]["work"]["tasks"])
            self.assertEqual(original["packet"]["targets"], extended["packet"]["targets"])
            self.assertEqual(original["packet"]["declared_scope"], extended["packet"]["declared_scope"])
            self.assertEqual(original_blob, db.get_blob(saved["payload_sha256"]))
            self.assertNotEqual(original["packet"]["source_context_digest"], extended["packet"]["source_context_digest"])
            self.assertNotIn(request["reason"], canonical_bytes(extended["packet"]).decode("utf-8"))
            self.assertIn(WORK_CONTEXT_EXTENSION_FEATURE, json.loads(db.metadata["features"]))
            chained = packets.extend_work_assignment(db, packet_id=extended["packet_id"],
                                                      request=self.request(db, ("anchors", "anc_lem_proof")))
            self.assertTrue(record_keys(extended["packet"]) < record_keys(chained["packet"]))
            self.assertEqual(extended["packet_id"], chained["packet"]["extends"])
            self.assertFalse(packets.blinding_violations(chained["packet"]))

    def test_request_is_strict_and_noop_additions_are_rejected_without_writes(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            good = self.request(db, ("anchors", "anc_lem_proof"))
            bad = [dict(good, other=True), dict(good, reason=" "), dict(good, source_refs=[]),
                   dict(good, source_refs=[{"collection": "anchors", "id": "anc_lem_proof"}]),
                   self.request(db, ("arguments", "arg_lem")),
                   dict(good, source_refs=[dict(good["source_refs"][0], version=True)]),
                   self.request(db, ("anchors", "anc_lem"))]
            for request in bad:
                with self.subTest(request=request):
                    before = self.counts(db)
                    with self.assertRaises(InvalidRequest):
                        packets.extend_work_assignment(db, packet_id=original["packet_id"], request=request)
                    self.assertEqual(before, self.counts(db))

    def test_stale_request_and_changed_delivered_statement_are_rejected(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            bad = self.request(db, ("anchors", "anc_lem_proof"))
            bad["source_refs"][0]["version"] += 1
            with self.assertRaises(ConflictError):
                packets.extend_work_assignment(db, packet_id=original["packet_id"], request=bad)
            target = db.head("items", "itm_thm")
            self.fx.apply(db, [edit("replace", "items", target.id,
                dict(target.body, statement={"form": "verbatim", "text": "Changed statement"}), target.version)])
            before = self.counts(db)
            with self.assertRaises(ConflictError):
                packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                               request=self.request(db, ("anchors", "anc_lem_proof")))
            self.assertEqual(before, self.counts(db))

    def test_changed_inference_membership_requires_renewed_assignment(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            use = db.head("uses", "use_lem_thm")
            detail = db.head("application_details", use.id)
            self.fx.apply(db, [self.fx.item_edit("itm_more", "assumption", "Extra hypothesis", "anc_lem", "anc_lem_proof"),
                              edit("create", "uses", "use_more", dict(use.body, **{"from": R("items", "itm_more")})),
                              edit("create", "application_details", "use_more", dict(detail.body, use_id="use_more"))])
            with self.assertRaises(ConflictError):
                packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                               request=self.request(db, ("anchors", "anc_lem_proof")))

    def test_historical_v2_packet_uses_bounded_scope_fallback(self):
        with self.fx.open() as db:
            build = packets._assignment_packet

            def historical(*args, **kwargs):
                manifest, packet = build(*args, **kwargs)
                manifest["work"].pop("source_context_inputs", None)
                manifest["work"].pop("source_context_relations", None)
                return manifest, packet

            with mock.patch.object(packets, "_assignment_packet", side_effect=historical):
                unchanged = self.prepare(db)
                changed = self.prepare(db)
            continued = packets.extend_work_assignment(db, packet_id=unchanged["packet_id"],
                                                       request=self.request(db, ("anchors", "anc_lem_proof")))
            self.assertTrue(continued["prepared"], continued)
            scope = db.head("scopes", "scp_plain")
            self.fx.apply(db, [edit("replace", "scopes", scope.id, dict(scope.body, conditions=["new private regime"]), scope.version)])
            for original in (changed, continued):
                with self.assertRaises(ConflictError):
                    packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                                   request=self.request(db, ("anchors", "anc_lem_proof")))

    def test_changed_captured_source_requires_new_assignment(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            path = self.fx.source_root / "paper.tex"
            path.write_text(path.read_text(encoding="utf-8") + "\n% revised source\n", encoding="utf-8")
            sources.capture_sources(db, files=["paper.tex"])
            before = self.counts(db)
            with self.assertRaises(ConflictError):
                packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                               request=self.request(db, ("anchors", "anc_lem_proof")))
            self.assertEqual(before, self.counts(db))

    def test_non_work_primary_and_route_provided_packets_are_rejected(self):
        with self.fx.open() as db:
            ordinary = self.fx.packet(db, "items:itm_thm", mode="independent")
            primary = controller.prepare_work(db, audit_id="aud_1", mode="primary", focus=R("items", "itm_lem"))
            self.fx.independent_round(db, "itm_thm", "arg_thm", "anc_thm_proof")
            route = packets.prepare_route_assignment(db, audit_id="aud_1", route_id="arg_thm")
            for prepared in (ordinary, primary, route):
                before = self.counts(db)
                with self.assertRaises(InvalidRequest) as error:
                    packets.extend_work_assignment(db, packet_id=prepared["packet_id"],
                                                   request=self.request(db, ("anchors", "anc_lem_proof")))
                self.assertEqual("WORK_CONTEXT_MODE", error.exception.code)
                self.assertEqual(before, self.counts(db))

    def test_old_response_cannot_rebase_to_added_preexisting_source(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            extended = packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                                      request=self.request(db, ("anchors", "anc_lem_proof")))
            self.assertEqual(original["packet"]["source_context_digest"], extended["packet"]["source_context_digest"])
            envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": original["packet_id"],
                "rebase_packet_id": extended["packet_id"], "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": ""}
            worker = worker_response(original["packet_id"], [], covered=[R("items", "itm_thm")])
            result = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
            self.assertEqual("needs_revision", result["state"], result)
            self.assertFalse(result["stored"], result)
            self.assertIn("new independent context requires a new response", str(result["diagnostics"]))

    def test_source_origin_reconstruction_is_not_context(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            created = self.fx.item_edit("itm_repair", "lemma", "Proposed repair", "anc_lem", "anc_lem_proof")
            created["body"]["origin"] = "reconstruction"
            created["body"]["statement"]["form"] = "synopsis"
            self.fx.apply(db, [created])
            with self.assertRaises(InvalidRequest):
                packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                               request=self.request(db, ("items", "itm_repair")))

    def test_overflow_persists_no_packet_or_feature(self):
        with self.fx.open() as db:
            original = self.prepare(db, max_bytes=16000)
            self.capture_extra(db, "A" * 20000)
            before = self.counts(db)
            result = packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                                   request=self.request(db, ("anchors", "anc_extra")))
            self.assertFalse(result["prepared"], result)
            self.assertEqual("OVERSIZED_CONTEXT", result["diagnostics"][0]["code"])
            self.assertEqual(before, self.counts(db))

    def test_persistence_failure_rolls_back_feature_and_packet(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            before = self.counts(db)
            with mock.patch.object(db, "insert_packet", side_effect=RuntimeError("injected persistence failure")):
                with self.assertRaises(RuntimeError):
                    packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                                   request=self.request(db, ("anchors", "anc_lem_proof")))
            self.assertEqual(before, self.counts(db))

    def test_old_core_rejects_feature_only_after_extension(self):
        with self.fx.open() as db:
            old_features = tuple(f for f in storage.SUPPORTED_FEATURES if f != WORK_CONTEXT_EXTENSION_FEATURE)
            with mock.patch.object(storage, "SUPPORTED_FEATURES", old_features):
                with self.fx.open(write=False):
                    pass
            original = self.prepare(db)
            packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                           request=self.request(db, ("anchors", "anc_lem_proof")))
            with mock.patch.object(storage, "SUPPORTED_FEATURES", old_features):
                with self.assertRaises(IncompatibleError):
                    self.fx.open(write=False)

    def test_received_intake_must_be_resolved_before_extension(self):
        with self.fx.open() as db:
            original = self.prepare(db)
            envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": original["packet_id"],
                "rebase_packet_id": None, "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": ""}
            worker = worker_response(original["packet_id"], [], covered=[R("items", "itm_thm")])
            # Public intake survives an interrupted acceptance as a received row.
            with mock.patch.object(controller, "accept_in_transaction", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
            self.assertEqual("received", db.work_submission(envelope["request_id"])["state"])
            with self.assertRaises(InvalidRequest) as error:
                packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                               request=self.request(db, ("anchors", "anc_lem_proof")))
            self.assertEqual("WORK_CONTEXT_PENDING", error.exception.code)

    def test_completed_inconclusive_can_extend_and_explicitly_succeed(self):
        from paper_core import review
        self.fx.primary()
        with self.fx.open() as db:
            original = controller.prepare_work(db, audit_id="aud_1", mode="independent", focus=R("items", "itm_lem"))
            envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": original["packet_id"],
                "rebase_packet_id": None, "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": "Fresh source-only review."}
            worker = worker_response(original["packet_id"], [judgment(source_target("anc_lem_proof", "Whole written argument"),
                outcome="inconclusive", reasoning="Missing the auxiliary source statement.")])
            first = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))
            authority = self.fx.packet(db, "items:itm_lem", mode="reconcile")
            mapped = review.map_response(db, mapping=mapping_request(self.fx, authority["packet_id"], first["response_id"],
                                         [entry(0, R("arguments", "arg_lem"))]))
            check_id = mapped["checks"][0]["check_id"]
            prior_check = db.head("checks", check_id)
            self.capture_extra(db)
            extended = packets.extend_work_assignment(db, packet_id=original["packet_id"],
                                                      request=self.request(db, ("anchors", "anc_extra")))
            self.assertEqual(original["assigned_task_ids"], extended["assigned_task_ids"])
            successor = judgment(source_target("anc_lem_proof", "Whole written argument"),
                                  reasoning="Examined the auxiliary statement and the full argument.",
                                  evidence=("anc_lem_proof", "anc_extra"))
            successor["supersedes"] = prior_check.pinned
            continued = worker_response(extended["packet_id"], [successor],
                                        exposure_note="Same reviewer continues its own prior source-only review.")
            new_envelope = dict(envelope, request_id=self.fx.request_id(), packet_id=extended["packet_id"],
                                exposure_note="Same reviewer continuing its own earlier response; no other judgments shown.")
            second = controller.submit_work(db, envelope_bytes=canonical_bytes(new_envelope), response_bytes=canonical_bytes(continued))
            self.assertIn("response_id", second, second)
            self.assertEqual("inconclusive", db.head("checks", check_id).body["outcome"])
            self.assertIn("Same reviewer", db.head("responses", second["response_id"]).body["exposure_note"])
            authority = self.fx.packet(db, "items:itm_lem", mode="reconcile")
            final = review.map_response(db, mapping=mapping_request(self.fx, authority["packet_id"], second["response_id"],
                                        [entry(0, R("arguments", "arg_lem"))]))
            saved = db.head("checks", final["checks"][0]["check_id"])
            self.assertEqual(prior_check.pinned, saved.body["supersedes"])
            self.assertEqual("inconclusive", db.version("checks", check_id, prior_check.version).body["outcome"])
            self.assertEqual(canonical_bytes(worker), db.get_blob(db.head("responses", first["response_id"]).body["original_blob"]))
            self.assertEqual(canonical_bytes(continued), db.get_blob(db.head("responses", second["response_id"]).body["original_blob"]))
