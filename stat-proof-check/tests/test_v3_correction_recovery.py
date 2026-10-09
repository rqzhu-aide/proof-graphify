"""CLI correction feedback is factual, bounded, and preserves saved review work."""
from copy import deepcopy
import json

from support import PROOFCHECK, R, TempCase, edit, run_wrapper, write_json
from paper_core import assessment, authoring, contract, controller, review, stage2
from paper_core.correction_feedback import compact_receipt, sync_current


MINUS = "For every x, B(x) = A(x) - C(x)."
PLUS = "For every x, B(x) = A(x) + C(x)."


class CorrectionRecoveryTests(TempCase):
    def authored(self, *, statement=MINUS, name="paper"):
        fixture = self.fixture(name).anchors()
        with fixture.open() as db:
            authoring.create_unit(db, self.definition("claim", statement))
        return fixture

    @staticmethod
    def definition(key, statement):
        return {"key": key, "kind": "lemma", "label": key, "statement": statement,
                "statement_anchors": ["anc_lem"], "proof_anchors": ["anc_lem_proof"],
                "proof_complete": True, "source_matched": True,
                "source_note": "Synthetic source comparison.", "aliases": [key + " alias"]}

    def cli(self, fixture, expected, *options, expect=0, item="itm_claim"):
        return run_wrapper(PROOFCHECK, "stage1", "correct-claim", fixture.path,
                           "--item", item, "--expected-version", expected, *options, expect=expect)[0]

    def correction(self, fixture, expected, payload):
        path = write_json(fixture.root / "correction.json", payload)
        return self.cli(fixture, expected, "--correction", path)

    @staticmethod
    def saved_work(db):
        return {collection: [(row.pinned, deepcopy(row.body)) for row in db.heads(collection)]
                for collection in contract.BODY_SCHEMAS if collection not in ("items", "target_specs")}

    @staticmethod
    def generic_correction(fixture, *, text=PLUS):
        with fixture.open() as db:
            item = db.head("items", "itm_claim")
            body = deepcopy(item.body)
            body["statement"]["text"] = text
            body["passages"][0]["anchor_id"] = "anc_thm"
            body["aliases"].append("Later alias")
            body["caption"] = "Later caption"
            body["proof_idea"] = "Preserve the author's description."
            fixture.apply(db, [edit("replace", "items", item.id, body, item.version)])
            return db.head("items", item.id)

    def test_explicit_correction_and_replay_describe_original_saved_change(self):
        fixture = self.authored()
        payload = {"statement": PLUS, "statement_anchors": ["anc_thm"]}
        result = self.correction(fixture, 1, payload)
        self.assertEqual("itm_claim", result["item_id"])
        self.assertFalse(result["reused"])
        self.assertFalse(result["unchanged"])
        self.assertNotIn("receipt_kind", result)
        self.assertEqual({"items", "target_specs"}, {p["collection"] for p in result["receipt"]["changed"]})
        change = result["actual_change"]
        for side, expected, version in (("before", MINUS, 1), ("after", PLUS, 2)):
            self.assertEqual(expected, change[side]["statement_excerpt"]["text"])
            self.assertEqual(expected, change[side]["exact_statement_excerpt"]["text"])
            self.assertEqual(version, change[side]["item"]["version"])
            self.assertFalse(change[side]["statement_excerpt"]["truncated"])
        saved = fixture.path.read_bytes()
        replay = self.correction(fixture, 1, payload)
        self.assertTrue(replay["reused"])
        self.assertEqual(result["receipt"], replay["receipt"])
        self.assertEqual(change, replay["actual_change"])
        self.assertEqual(saved, fixture.path.read_bytes())
        with fixture.open(write=False) as db:
            self.assertEqual(MINUS, db.version("items", "itm_claim", 1).body["statement"]["text"])

    def test_sync_changes_only_stale_target_and_replays_without_mutation(self):
        fixture = self.authored()
        current = self.generic_correction(fixture)
        with fixture.open(write=False) as db:
            saved_work = self.saved_work(db)
        result = self.cli(fixture, current.version, "--sync-current")
        self.assertEqual(["target_specs"], [p["collection"] for p in result["receipt"]["changed"]])
        before, after = (result["actual_change"][side] for side in ("before", "after"))
        self.assertEqual(current.pinned, before["item"])
        self.assertEqual(before["item"], after["item"])
        self.assertEqual(before["statement_excerpt"], after["statement_excerpt"])
        self.assertEqual(PLUS, before["statement_excerpt"]["text"])
        self.assertEqual(MINUS, before["exact_statement_excerpt"]["text"])
        self.assertEqual(PLUS, after["exact_statement_excerpt"]["text"])
        self.assertEqual(["anc_lem"], before["exact_evidence_refs"])
        self.assertEqual(["anc_thm"], after["exact_evidence_refs"])
        with fixture.open(write=False) as db:
            self.assertEqual(current.body, db.head("items", current.id).body)
            self.assertEqual(saved_work, self.saved_work(db))
            self.assertEqual(current.pinned, db.head("target_specs", "tgt_claim").body["statement_ref"])
        saved = fixture.path.read_bytes()
        replay = self.cli(fixture, current.version, "--sync-current")
        self.assertTrue(replay["reused"])
        self.assertEqual(result["actual_change"], replay["actual_change"])
        self.assertEqual(result["receipt"], replay["receipt"])
        self.assertEqual(saved, fixture.path.read_bytes())

    def test_aligned_noop_keeps_fidelity_and_database_bytes(self):
        fixture = self.authored()
        with fixture.open() as db:
            spec = db.head("target_specs", "tgt_claim")
            body = deepcopy(spec.body)
            body["fidelity_ref"] = db.head("observations", "obs_claim").pinned
            fixture.apply(db, [edit("replace", "target_specs", spec.id, body, spec.version)], mode="primary")
        saved = fixture.path.read_bytes()
        result = self.cli(fixture, 1, "--sync-current")
        self.assertTrue(result["unchanged"])
        self.assertFalse(result["reused"])
        self.assertIsNone(result["receipt"])
        self.assertEqual(result["actual_change"]["before"], result["actual_change"]["after"])
        self.assertEqual(body["fidelity_ref"], result["actual_change"]["after"]["fidelity_ref"])
        self.assertEqual(saved, fixture.path.read_bytes())

    def test_sync_preserves_interleaved_saved_statement_and_proof_passages(self):
        fixture = self.authored()
        with fixture.open() as db:
            item = db.head("items", "itm_claim")
            body = deepcopy(item.body)
            body["statement"]["text"] = PLUS
            body["passages"].append({"role": "statement", "anchor_id": "anc_thm"})
            fixture.apply(db, [edit("replace", "items", item.id, body, item.version)])
            current = db.head("items", item.id)
        result = self.cli(fixture, current.version, "--sync-current")
        self.assertEqual(["target_specs"], [p["collection"] for p in result["receipt"]["changed"]])
        with fixture.open(write=False) as db:
            self.assertEqual(current.pinned, db.head("items", current.id).pinned)
            self.assertEqual(current.body, db.head("items", current.id).body)
            self.assertEqual(["anc_lem", "anc_thm"], db.head("target_specs", "tgt_claim").body["evidence_refs"])

    def test_long_prefix_sign_change_is_visible_in_bounded_excerpts(self):
        prefix = "Shared setup sentence. " * 500
        fixture = self.authored(statement=prefix + MINUS)
        result = self.correction(fixture, 1, {"statement": prefix + PLUS})
        self.assertLess(len(json.dumps(result)), 4000)
        for side, full, suffix in (("before", prefix + MINUS, MINUS), ("after", prefix + PLUS, PLUS)):
            for field in ("statement_excerpt", "exact_statement_excerpt"):
                excerpt = result["actual_change"][side][field]
                self.assertIn(suffix, excerpt["text"])
                self.assertGreater(excerpt["offset"], 240)
                self.assertLessEqual(len(excerpt["text"]), 240)
                self.assertTrue(excerpt["truncated"])
                self.assertEqual(len(full), excerpt["characters"])
                self.assertEqual(full[excerpt["offset"]:excerpt["offset"] + 240], excerpt["text"])
        replay = self.correction(fixture, 1, {"statement": prefix + PLUS})
        self.assertEqual(result["actual_change"], replay["actual_change"])

    def test_local_input_errors_leave_no_partial_mutation(self):
        fixture = self.authored()
        correction = write_json(fixture.root / "valid.json", {"statement": PLUS})
        missing = write_json(fixture.root / "missing.json", {"statement_anchors": ["anc_missing"]})
        invalid = write_json(fixture.root / "invalid.json", {"source_matched": True})
        for item, version, options in (
                ("itm_claim", 1, ()),
                ("itm_claim", 1, ("--sync-current", "--correction", correction)),
                ("itm_missing", 1, ("--sync-current",)),
                ("wrong", 1, ("--sync-current",)),
                ("itm_claim", 0, ("--sync-current",)),
                ("itm_claim", 1, ("--correction", missing)),
                ("itm_claim", 1, ("--correction", invalid))):
            with self.subTest(item=item, version=version, options=options):
                saved = fixture.path.read_bytes()
                result = self.cli(fixture, version, *options, item=item, expect=2)
                if result:
                    self.assertNotEqual("INTERNAL", result["error"]["code"])
                self.assertEqual(saved, fixture.path.read_bytes())
        self.generic_correction(fixture)
        saved = fixture.path.read_bytes()
        conflict = self.cli(fixture, 1, "--sync-current", expect=3)
        self.assertEqual("CLAIM_CORRECTION_CONFLICT", conflict["error"]["code"])
        self.assertEqual(saved, fixture.path.read_bytes())

    def test_distinct_target_or_multiple_routes_keep_local_guidance(self):
        for distinct in (False, True):
            fixture = self.authored(name="distinct" if distinct else "multiple_routes")
            with fixture.open() as db:
                spec = db.head("target_specs", "tgt_claim")
                if not distinct:
                    argument = deepcopy(db.head("arguments", "arg_claim").body)
                    argument["final_group_id"] = "grp_second"
                    group = deepcopy(db.head("groups", "grp_claim").body)
                    group["argument_id"] = "arg_second"
                    fixture.apply(db, [edit("create", "arguments", "arg_second", argument),
                                       edit("create", "groups", "grp_second", group)])
                else:
                    body = deepcopy(spec.body)
                    body.update(statement_ref=None, statement={"form": "verbatim", "text": "A distinct exact claim."})
                    fixture.apply(db, [edit("replace", "target_specs", spec.id, body, spec.version)])
            saved = fixture.path.read_bytes()
            result = self.cli(fixture, 1, "--sync-current", expect=2)
            self.assertEqual("CLAIM_CORRECTION_ADVANCED", result["error"]["code"])
            self.assertIn("template --id", result["error"]["message"])
            self.assertEqual(saved, fixture.path.read_bytes())

    def test_connected_sync_preserves_reviews_findings_and_affected_freshness(self):
        fixture = self.authored()
        with fixture.open() as db:
            for key in ("consumer", "other"):
                definition = self.definition(key, "The consequence follows." if key == "consumer" else "An unrelated claim.")
                definition.update(statement_anchors=["anc_thm"], proof_anchors=["anc_thm_proof"])
                if key == "consumer":
                    definition["suppliers"] = [{"target": R("items", "itm_claim"), "reason": "Apply the claim.",
                        "needed_form": {"form": "verbatim", "text": MINUS}, "evidence_refs": ["anc_thm_proof"]}]
                authoring.create_unit(db, definition)
            audit = authoring.create_audit(db, mode="focused", targets=[R("items", "itm_" + key)
                                            for key in ("claim", "consumer", "other")])["audit_id"]
            for key in ("claim", "consumer", "other"):
                fixture.apply(db, [fixture.check_edit("chk_" + key, R("arguments", "arg_" + key), "composition",
                    audit_id=audit, evidence=["anc_lem_proof" if key == "claim" else "anc_thm_proof"])],
                    "items:itm_" + key, mode="primary")
            fixture.apply(db, [fixture.check_edit("chk_application", R("uses", "use_consumer_1"), "application",
                audit_id=audit, evidence=["anc_thm_proof"])], "items:itm_consumer", mode="primary")
            prepared = stage2.prepare(db, audit_id=audit, focus=R("items", "itm_claim"))
            response = prepared["scaffold"]
            for row in response["judgments"]:
                row.update(state="complete", outcome="supported", reasoning="Synthetic independent source examination.")
            submitted = controller.submit_work(db, envelope_bytes=json.dumps({
                "contract_version": 4, "request_id": fixture.request_id(), "packet_id": prepared["packet_id"],
                "rebase_packet_id": None, "reviewer": "separate reviewer", "qualification_id": None,
                "exposure": "source_only", "exposure_note": ""}).encode(), response_bytes=json.dumps(response).encode())
            self.assertEqual("accepted", submitted["state"], submitted)
            independent = next(row.id for row in db.heads("checks")
                               if row.body["response_id"] == submitted["response_id"])
            packet = fixture.packet(db, "items:itm_claim", mode="reconcile")
            review.reconcile(db, batch=fixture.batch([fixture.reconciliation_edit(
                db, "rec_claim", "arg_claim", "chk_claim", independent, audit_id=audit)], packet["packet_id"]))
            fixture.apply(db, [edit("create", "findings", "fnd_claim", {"audit_id": audit,
                "target": R("items", "itm_claim"), "category": "presentation", "lifecycle": "open",
                "description": "The transcribed sign needs correction.", "evidence_refs": ["anc_lem"],
                "check_refs": [db.head("checks", "chk_claim").pinned], "affected_uses": ["use_consumer_1"],
                "impact_reason": "The consumer uses this bound.", "resolution": None})],
                "items:itm_claim", mode="primary")
            initial = assessment.derive_assessment(db, audit_id=audit)
            saved_work = self.saved_work(db)
            self.assertTrue(saved_work["responses"])
            self.assertTrue(saved_work["reconciliations"])
            self.assertTrue(saved_work["findings"])
        current = self.generic_correction(fixture)
        with fixture.open() as db:
            before = assessment.derive_assessment(db, audit_id=audit)
            result = compact_receipt(db, sync_current(db, current.id, current.version))
            after = assessment.derive_assessment(db, audit_id=audit)
            self.assertEqual(saved_work, self.saved_work(db))
            self.assertEqual(current.body, db.head("items", current.id).body)
            self.assertFalse(result["unchanged"])
        for name in ("claim", "consumer", "application"):
            self.assertEqual("current", initial["judgments"]["checks:chk_" + name]["freshness"])
            self.assertNotEqual("current", before["judgments"]["checks:chk_" + name]["freshness"])
            self.assertNotEqual("current", after["judgments"]["checks:chk_" + name]["freshness"])
        self.assertEqual("current", after["judgments"]["checks:chk_other"]["freshness"])
        self.assertEqual(initial["support"]["items:itm_other"], after["support"]["items:itm_other"])
        self.assertNotEqual("available", after["support"]["items:itm_consumer"])
        self.assertLess(sum(o["satisfied"] for o in after["obligations"] if o["kind"] == "source_fidelity"),
                        sum(o["satisfied"] for o in initial["obligations"] if o["kind"] == "source_fidelity"))
