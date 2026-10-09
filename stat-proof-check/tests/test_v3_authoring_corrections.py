"""Local authoring corrections preserve identity, history, and scientific freshness."""
from copy import deepcopy

from support import R, TempCase, edit
from paper_core import acceptance, assessment, assistance, authoring, contract
from paper_core.errors import ConflictError, InvalidRequest
from paper_core.semantics import exact_statement


class AuthoringCorrectionTests(TempCase):
    def authored(self, *, written=True, name="paper"):
        fixture = self.fixture(name).anchors()
        with fixture.open() as db:
            authoring.create_unit(db, {
                "key": "claim", "kind": "lemma", "label": "Lemma 1",
                "statement": "For every x, the displayed lower bound is nonpositive.",
                "statement_anchors": ["anc_lem"],
                "proof_anchors": ["anc_lem_proof"] if written else [],
                "proof_complete": written, "source_matched": True,
                "source_note": "Located source statement and proof." if written else "The proof is unavailable.",
                "aliases": ["source lemma"]})
        return fixture

    def test_current_template_preserves_optional_body_and_named_create(self):
        fixture = self.authored()
        with fixture.open() as db:
            fixture.apply(db, [fixture.item_edit("itm_external", "external_result", "Cited result", "anc_lem", "anc_lem_proof")])
            item = db.head("items", "itm_external")
            body = deepcopy(item.body)
            body["proof_idea"] = "Preserve this optional author description."
            fixture.apply(db, [edit("replace", "items", item.id, body, item.version)])
            packet = fixture.packet(db, "items:itm_external")
            result = assistance.authoring_template("items", packet_id=packet["packet_id"],
                                                   record_id=item.id, db=db)
            entry = result["template"]["edits"][0]
            self.assertEqual("replace", entry["op"])
            self.assertEqual(2, entry["expected_version"])
            self.assertEqual(body, entry["body"])
            entry["body"]["passages"][0]["anchor_id"] = "anc_thm"
            receipt = acceptance.apply_batch(db, result["template"])
            self.assertEqual(3, receipt["changed"][0]["version"])
            self.assertEqual(body, db.version("items", item.id, 2).body)
            self.assertEqual(body["proof_idea"], db.head("items", item.id).body["proof_idea"])
            # A shared use ID absent only from application_details remains a create.
            fixture.apply(db, [edit("create", "uses", "use_claim", {
                "from": R("items", item.id), "to": R("items", "itm_claim"), "type": "dependency",
                "reason": "Source connection awaiting application detail.", "evidence_refs": ["anc_lem"],
                "regime": None, "uncertainty": None})])
            packet = fixture.packet(db)
            named = assistance.authoring_template("application_details", packet_id=packet["packet_id"],
                                                   record_id="use_claim", db=db)["template"]["edits"][0]
            self.assertEqual("create", named["op"])
            self.assertIsNone(named["expected_version"])
            self.assertEqual("use_claim", named["body"]["use_id"])
            self.assertIn("create", assistance.authoring_template("items", packet_id=packet["packet_id"], db=db)["note"])

    def test_template_rejects_stale_or_unauthorized_packet_and_retired_identity(self):
        fixture = self.authored()
        with fixture.open() as db:
            old = fixture.packet(db, "items:itm_claim")
            scope = db.head("scopes", "scp_claim")
            changed = deepcopy(scope.body)
            changed["conditions"] = ["The source setup now includes a boundedness condition."]
            fixture.apply(db, [edit("replace", "scopes", scope.id, changed, scope.version)])
            with self.assertRaises(ConflictError) as stale:
                assistance.authoring_template("items", packet_id=old["packet_id"], record_id="itm_claim", db=db)
            self.assertEqual("ASSISTANCE_PACKET", stale.exception.code)
            self.assertIn("--target items:itm_claim --mode author", stale.exception.retry["command"])
            authoring.create_audit(db, mode="focused", targets=[R("items", "itm_claim")])
            independent = fixture.packet(db, "items:itm_claim", mode="independent")
            with self.assertRaises(ConflictError):
                assistance.authoring_template("items", packet_id=independent["packet_id"], record_id="itm_claim", db=db)
            packet = fixture.packet(db, "items:itm_claim")
            self.assertEqual("replace", assistance.authoring_template("items", packet_id=packet["packet_id"],
                record_id="itm_claim", db=db)["template"]["edits"][0]["op"])
            fixture.apply(db, [fixture.item_edit("itm_unused", "external_result", "Unused citation", "anc_thm", "anc_thm_proof")])
            packet = fixture.packet(db)
            acceptance.apply_batch(db, fixture.batch([{"op": "retire", "collection": "items", "id": "itm_unused",
                "expected_version": 1, "reason": "Withdrawn unused identity."}], packet["packet_id"]))
            with self.assertRaises(InvalidRequest) as retired:
                assistance.authoring_template("items", packet_id=packet["packet_id"], record_id="itm_unused", db=db)
            self.assertEqual("ASSISTANCE_RETIRED", retired.exception.code)

    def test_invalid_operation_names_replace_without_relaxing_edit_shape(self):
        fixture = self.authored()
        with fixture.open() as db:
            packet = fixture.packet(db)
            revision = db.max_revision()
            invalid = fixture.batch([edit("update", "items", "itm_claim", {}, 1)], packet["packet_id"])
            with self.assertRaises(InvalidRequest) as caught:
                acceptance.apply_batch(db, invalid)
            self.assertIn("/edits/0/op: must be one of ['create', 'replace', 'retire']", caught.exception.records)
            self.assertFalse(any("must be 'create'" in error for error in caught.exception.records))
            invalid["edits"][0]["op"] = "replace"
            invalid["edits"][0]["guess"] = True
            del invalid["edits"][0]["body"]
            errors = contract.validate_shape(contract.BATCH, invalid)
            self.assertIn("/edits/0/body: missing required field", errors)
            self.assertIn("/edits/0/guess: unknown field", errors)
            self.assertEqual(revision, db.max_revision())

    def test_paired_correction_updates_exact_text_without_inheriting_math_or_fidelity(self):
        fixture = self.authored()
        with fixture.open() as db:
            audit = authoring.create_audit(db, mode="focused", targets=[R("items", "itm_claim")])["audit_id"]
            check = fixture.check_edit("chk_claim", R("arguments", "arg_claim"), "composition",
                                       audit_id=audit, evidence=["anc_lem_proof"])
            check["body"].update(extent="whole_unit", omissions="")
            fixture.apply(db, [check], "items:itm_claim", mode="primary")
            spec = db.head("target_specs", "tgt_claim")
            spec_body = deepcopy(spec.body)
            spec_body["fidelity_ref"] = db.head("observations", "obs_claim").pinned
            fixture.apply(db, [edit("replace", "target_specs", spec.id, spec_body, spec.version)],
                          "items:itm_claim", mode="primary")
            before = {collection: [(r.pinned, deepcopy(r.body)) for r in db.heads(collection)]
                      for collection in ("scopes", "arguments", "groups", "proof_boundaries", "source_reviews",
                                         "observations", "checks", "responses", "reconciliations", "source_issues")}
            result = authoring.correct_claim(db, "itm_claim", 1, {
                "statement": "For every x, the displayed lower bound is nonnegative.",
                "statement_anchors": ["anc_thm"]})
            self.assertFalse(result["reused"])
            self.assertEqual({("items", "itm_claim"), ("target_specs", "tgt_claim")},
                             {(r["collection"], r["id"]) for r in result["receipt"]["changed"]})
            item = db.head("items", "itm_claim")
            spec = db.head("target_specs", "tgt_claim")
            self.assertEqual(item.body["statement"], exact_statement(db, item.ref))
            self.assertEqual("verbatim", item.body["statement"]["form"])
            self.assertEqual(item.pinned, spec.body["statement_ref"])
            self.assertEqual(["anc_thm"], spec.body["evidence_refs"])
            self.assertIsNone(spec.body["fidelity_ref"])
            self.assertIn({"role": "proof", "anchor_id": "anc_lem_proof"}, item.body["passages"])
            self.assertEqual(["source lemma"], item.body["aliases"])
            self.assertIn("nonpositive", db.version("items", item.id, 1).body["statement"]["text"])
            for collection, saved in before.items():
                self.assertEqual(saved, [(r.pinned, r.body) for r in db.heads(collection)], collection)
            assessed = assessment.derive_assessment(db, audit_id=audit)
            self.assertNotEqual("current", assessed["judgments"]["checks:chk_claim"]["freshness"])
            self.assertNotEqual("available", assessed["support"]["items:itm_claim"])
            fidelity = [o for o in assessed["obligations"] if o["kind"] == "source_fidelity"]
            self.assertTrue(fidelity)
            self.assertFalse(any(o["satisfied"] for o in fidelity))

    def test_statement_only_correction_is_idempotent_and_noop_preserves_fidelity(self):
        fixture = self.authored(written=False)
        with fixture.open() as db:
            spec = db.head("target_specs", "tgt_claim")
            body = deepcopy(spec.body)
            body["fidelity_ref"] = db.head("observations", "obs_claim").pinned
            fixture.apply(db, [edit("replace", "target_specs", spec.id, body, spec.version)], mode="primary")
            original = db.head("items", "itm_claim")
            revision = db.max_revision()
            noop = authoring.correct_claim(db, original.id, original.version,
                                           {"statement": original.body["statement"]["text"]})
            self.assertTrue(noop["unchanged"])
            self.assertIsNone(noop["receipt"])
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(body, db.head("target_specs", spec.id).body)
            correction = {"statement": "The corrected exact statement with its original hypotheses."}
            result = authoring.correct_claim(db, original.id, original.version, correction)
            revision = db.max_revision()
            replay = authoring.correct_claim(db, original.id, original.version, correction)
            self.assertTrue(replay["reused"])
            self.assertEqual(result["receipt"], replay["receipt"])
            self.assertEqual(revision, db.max_revision())
            self.assertEqual([], db.heads("arguments"))
            self.assertEqual([], db.heads("checks"))
            self.assertEqual(original.body["passages"], db.head("items", original.id).body["passages"])
            item = db.head("items", original.id)
            body = deepcopy(item.body)
            body["caption"] = "A later accepted local edit."
            fixture.apply(db, [edit("replace", "items", item.id, body, item.version)])
            revision = db.max_revision()
            with self.assertRaises(ConflictError) as caught:
                authoring.correct_claim(db, original.id, original.version, correction)
            self.assertEqual("CLAIM_CORRECTION_CONFLICT", caught.exception.code)
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(body, db.head("items", item.id).body)

    def test_prior_generic_text_edit_syncs_direct_spec_without_rewriting_item_or_fidelity(self):
        fixture = self.authored()
        with fixture.open() as db:
            audit = authoring.create_audit(db, mode="focused", targets=[R("items", "itm_claim")])["audit_id"]
            spec = db.head("target_specs", "tgt_claim")
            observation = db.head("observations", "obs_claim")
            item = db.head("items", "itm_claim")
            corrected_body = deepcopy(item.body)
            corrected_body["statement"]["text"] = "For every x, the displayed lower bound is nonnegative."
            fixture.apply(db, [edit("replace", "items", item.id, corrected_body, item.version)])
            current = db.head("items", item.id)
            self.assertNotEqual(current.body["statement"], exact_statement(db, current.ref))
            correction = {"statement": corrected_body["statement"]["text"]}
            result = authoring.correct_claim(db, item.id, current.version, correction)
            self.assertEqual(["target_specs"], [r["collection"] for r in result["receipt"]["changed"]])
            self.assertEqual(current.pinned, db.head("items", item.id).pinned)
            self.assertEqual(current.body["statement"], exact_statement(db, current.ref))
            self.assertIsNone(db.head("target_specs", spec.id).body["fidelity_ref"])
            self.assertEqual(observation.body, db.head("observations", observation.id).body)
            self.assertEqual(1, len(db.heads("observations")))
            self.assertEqual([], db.heads("checks"))
            assessed = assessment.derive_assessment(db, audit_id=audit)
            self.assertFalse(any(o["satisfied"] for o in assessed["obligations"] if o["kind"] == "source_fidelity"))
            revision = db.max_revision()
            self.assertEqual(result["receipt"], authoring.correct_claim(db, item.id, current.version, correction)["receipt"])
            self.assertEqual(revision, db.max_revision())

    def test_anchor_only_transcription_and_local_rejections_write_no_partial_pair(self):
        fixture = self.authored()
        with fixture.open() as db:
            item = db.head("items", "itm_claim")
            body = deepcopy(item.body)
            body["statement"]["form"] = "transcription"
            spec = db.head("target_specs", "tgt_claim")
            spec_body = deepcopy(spec.body)
            spec_body["statement_ref"]["version"] = 2
            fixture.apply(db, [edit("replace", "items", item.id, body, item.version),
                               edit("replace", "target_specs", spec.id, spec_body, spec.version)])
            corrected = authoring.correct_claim(db, item.id, 2, {"statement_anchors": ["anc_thm"]})
            self.assertIsNotNone(corrected["receipt"])
            current = db.head("items", item.id)
            self.assertEqual(body["statement"], current.body["statement"])
            # A prior generic passage edit may already have fixed the item, but
            # its paired exact source selection still needs the requested edit.
            changed = deepcopy(current.body)
            changed["passages"][0]["anchor_id"] = "anc_lem"
            fixture.apply(db, [edit("replace", "items", item.id, changed, current.version)])
            current = db.head("items", item.id)
            paired = authoring.correct_claim(db, item.id, current.version, {"statement_anchors": ["anc_lem"]})
            self.assertEqual(["target_specs"], [r["collection"] for r in paired["receipt"]["changed"]])
            self.assertEqual(current.pinned, db.head("target_specs", spec.id).body["statement_ref"])
            self.assertEqual(["anc_lem"], db.head("target_specs", spec.id).body["evidence_refs"])
            self.assertEqual(current.version, db.head("items", item.id).version)
            self.assertTrue(authoring.correct_claim(db, item.id, current.version, {"statement_anchors": ["anc_lem"]})["reused"])
            later = deepcopy(current.body)
            later["caption"] = "Later item metadata."
            fixture.apply(db, [edit("replace", "items", item.id, later, current.version)])
            with self.assertRaises(ConflictError):
                authoring.correct_claim(db, item.id, current.version, {"statement_anchors": ["anc_lem"]})
            current = db.head("items", item.id)
            revision = db.max_revision()
            for payload in ({}, {"statement_anchors": []}, {"source_matched": True},
                            {"statement": "Changed", "statement_anchors": ["anc_missing"]}):
                with self.subTest(payload=payload), self.assertRaises(InvalidRequest):
                    authoring.correct_claim(db, item.id, current.version, payload)
                self.assertEqual(revision, db.max_revision())
                self.assertEqual(current.body, db.head("items", item.id).body)
            with self.assertRaises(ConflictError):
                authoring.correct_claim(db, item.id, 1, {"statement": "A different later request."})
            spec = db.head("target_specs", spec.id)
            advanced = deepcopy(spec.body)
            advanced.update(statement_ref=None, statement={"form": "verbatim", "text": "A deliberately distinct exact target."})
            fixture.apply(db, [edit("replace", "target_specs", spec.id, advanced, spec.version)])
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                authoring.correct_claim(db, item.id, current.version, {"statement": "Another correction."})
            self.assertEqual("CLAIM_CORRECTION_ADVANCED", caught.exception.code)
            self.assertIn(spec.id, str(caught.exception.records))
            self.assertIn("template --id", caught.exception.message)
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(current.body, db.head("items", item.id).body)
