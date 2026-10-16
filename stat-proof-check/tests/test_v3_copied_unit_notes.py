"""Legacy helper notes are projected away without erasing authored caveats."""
from copy import deepcopy
from unittest.mock import patch

from support import R, TempCase, edit
from paper_core import acceptance, authoring, controller, packets, review, stage1
from paper_core.canonical import canonical_bytes, digest
from paper_core.errors import InvalidRequest
from paper_core.validation import State


class CopiedUnitNoteTests(TempCase):
    NOTE = "PRIMARY_NOTE: I believe the omitted argument has a gap."

    def unit(self, db, key="solo", *, legacy=False, complete=True, proved=False):
        definition = dict(key=key, kind="theorem", label="Theorem " + key,
            statement="The sequence $a_n$ converges.", statement_anchors=["anc_thm"],
            proof_anchors=["anc_thm_proof"] if proved else [], proof_complete=complete,
            source_matched=True, source_note=self.NOTE)
        if legacy:
            # Replay the exact old authoring behavior through the real transaction.
            with patch.object(authoring, "NO_PROOF_CUE", self.NOTE):
                return authoring.create_unit(db, definition)
        return authoring.create_unit(db, definition)

    def prepare(self, db, audit, focus=None):
        result = stage1.prepare_stage(db, audit_id=audit, stage=2, mode="independent",
            focus=focus, allow_provisional=True)
        self.assertTrue(result["prepared"], result)
        return result

    def old_packet(self, db, audit, focus=None):
        # Produce an immutable pre-correction payload with the old projection.
        native = packets._packet_record
        def legacy(record, mode, db=None):
            return native(record, mode)
        with patch.object(packets, "_packet_record", legacy):
            return self.prepare(db, audit, focus)

    def test_new_statement_only_keeps_original_observation_and_missing_source(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(db)
            self.assertEqual(packets.NO_PROOF_CUE, db.head("items", "itm_solo").body["uncertainty"])
            self.assertEqual(self.NOTE, db.head("observations", "obs_solo").body["note"])
            self.unit(db, "missing", complete=False)
            issue = db.head("source_issues", "iss_missing")
            self.assertEqual("open", issue.body["lifecycle"])
            self.assertEqual(self.NOTE, issue.body["description"])
            audit = authoring.create_audit(db, mode="focused", targets=[R("items", "itm_missing")])["audit_id"]
            blocked = stage1.prepare_stage(db, audit_id=audit, stage=2, mode="independent",
                allow_provisional=True)
            self.assertFalse(blocked["prepared"], blocked)

    def test_individual_and_grouped_replace_old_payload_then_reuse_clean(self):
        for grouped in (False, True):
            with self.subTest(grouped=grouped):
                fixture = self.fixture("grouped" if grouped else "individual").anchors()
                with fixture.open() as db:
                    self.unit(db, legacy=True)
                    self.unit(db, "proved", proved=True)
                    targets = [R("items", "itm_solo"), R("items", "itm_proved")]
                    audit = authoring.create_audit(db, mode="focused", targets=targets)["audit_id"]
                    focus = None if grouped else targets[0]
                    old = self.old_packet(db, audit, focus)
                    saved = deepcopy(db.packet(old["packet_id"]))
                    raw = db.get_blob(saved["payload_sha256"])
                    original = deepcopy(db.head("items", "itm_solo").body)
                    self.assertIn(self.NOTE.encode(), raw)
                    fresh = self.prepare(db, audit, focus)
                    self.assertFalse(fresh["reused"])
                    self.assertNotEqual(old["packet_id"], fresh["packet_id"])
                    self.assertNotIn(self.NOTE.encode(), canonical_bytes(fresh["packet"]))
                    self.assertEqual([], packets.copied_unit_notes_in_packet(db, fresh["packet"]))
                    again = self.prepare(db, audit, focus)
                    self.assertTrue(again["reused"])
                    self.assertEqual(fresh["packet_id"], again["packet_id"])
                    self.assertEqual(saved, db.packet(old["packet_id"]))
                    self.assertEqual(raw, db.get_blob(saved["payload_sha256"]))
                    self.assertEqual(original, db.head("items", "itm_solo").body)
                    self.assertEqual({"records": [], "relations": []},
                        packets.independent_context_changes(State(db, []), old["manifest"]))
                    proved = self.prepare(db, audit, targets[1])
                    repeated = self.prepare(db, audit, targets[1])
                    self.assertTrue(repeated["reused"])
                    self.assertEqual(proved["packet_id"], repeated["packet_id"])

    def test_context_extension_cannot_restore_blind_credit_to_exposed_parent(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(db, legacy=True)
            audit = authoring.create_audit(db, mode="focused", targets=[R("items", "itm_solo")])["audit_id"]
            old = self.old_packet(db, audit)
            stored = deepcopy(db.packet(old["packet_id"]))
            raw = db.get_blob(stored["payload_sha256"])
            request = {"source_refs": [db.head("anchors", "anc_lem").pinned],
                       "reason": "Read the adjacent captured setup."}
            revision = db.max_revision()
            count = db.conn.execute("SELECT count(*) FROM packets").fetchone()[0]
            with self.assertRaises(InvalidRequest) as refused:
                packets.extend_work_assignment(db, packet_id=old["packet_id"], request=request)
            self.assertEqual("WORK_CONTEXT_MODE", refused.exception.code)
            self.assertIn("fresh blind reviewer context", str(refused.exception))
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(count, db.conn.execute("SELECT count(*) FROM packets").fetchone()[0])
            self.assertEqual(stored, db.packet(old["packet_id"]))
            self.assertEqual(raw, db.get_blob(stored["payload_sha256"]))
            fresh = self.prepare(db, audit)
            extended = packets.extend_work_assignment(db, packet_id=fresh["packet_id"], request=request)
            self.assertEqual(fresh["packet_id"], extended["packet"]["extends"])
            self.assertEqual([], packets.copied_unit_notes_in_packet(db, extended["packet"]))

    def test_clean_packet_probe_avoids_version_reads_and_reuse_decodes_once(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(db)
            audit = authoring.create_audit(db, mode="focused", targets=[R("items", "itm_solo")])["audit_id"]
            fresh = self.prepare(db, audit)
            with patch.object(db, "version", wraps=db.version) as version_reads:
                self.assertEqual([], packets.copied_unit_notes_in_packet(db, fresh["packet"]))
            version_reads.assert_not_called()
            raw = db.get_blob(db.packet(fresh["packet_id"])["payload_sha256"])
            revision = db.max_revision()
            packet_count = db.conn.execute("SELECT count(*) FROM packets").fetchone()[0]
            native_loads = stage1.json.loads
            packet_decodes = []
            def counted_loads(value, *args, **kwargs):
                if value == raw:
                    packet_decodes.append(value)
                return native_loads(value, *args, **kwargs)
            with patch.object(stage1.json, "loads", side_effect=counted_loads):
                again = self.prepare(db, audit)
            self.assertEqual(1, len(packet_decodes))
            self.assertTrue(again["reused"])
            self.assertEqual(fresh["packet_id"], again["packet_id"])
            self.assertEqual(fresh["assigned_task_ids"], again["assigned_task_ids"])
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(packet_count, db.conn.execute("SELECT count(*) FROM packets").fetchone()[0])

    def test_equal_direct_authored_pair_is_not_helper_provenance(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(db, legacy=True)
            item = deepcopy(db.head("items", "itm_solo").body)
            item.update(scope_id=None, uncertainty="Captured source caveat: the sign is unclear.")
            observation = deepcopy(db.head("observations", "obs_solo").body)
            observation.update(target=R("items", "itm_imported"), note=item["uncertainty"])
            edits = [edit("create", "items", "itm_imported", item),
                     edit("create", "observations", "obs_imported", observation)]
            packet = fixture.packet(db)
            acceptance.accept(db, request_id="req_manual_source", request_digest=digest(edits),
                packet_id=packet["packet_id"], edits=edits, command="unit")
            imported = db.head("items", "itm_imported")
            self.assertEqual(imported.revision, db.head("observations", "obs_imported").revision)
            self.assertFalse(packets.copied_unit_note(db, imported, item["uncertainty"]))
            self.assertEqual(item["uncertainty"], packets._packet_record(imported, "independent", db)["body"]["uncertainty"])

    def test_later_observation_and_item_edits_use_original_copy_only(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(db, legacy=True)
            item = db.head("items", "itm_solo")
            observation = db.head("observations", "obs_solo")
            authoring.create_audit(db, mode="focused", targets=[item.ref])
            # Current writers keep observations immutable. Model an imported
            # historical later version to ensure detection still reads version 1.
            db.insert_version("observations", observation.id, 2, db.max_revision(),
                dict(observation.body, note="A later examiner opinion."))
            db.set_head("observations", observation.id, 2)
            self.assertTrue(packets.copied_unit_note(db, item, self.NOTE))
            caveat = "New source limitation: a quantifier is illegible."
            fixture.apply(db, [edit("replace", "items", item.id,
                dict(item.body, uncertainty=caveat), item.version)], "items:itm_solo")
            later = db.head("items", item.id)
            self.assertFalse(packets.copied_unit_note(db, later, caveat))
            self.assertEqual(caveat, packets._packet_record(later, "independent", db)["body"]["uncertainty"])
            fixture.apply(db, [edit("replace", "items", item.id,
                dict(later.body, uncertainty=self.NOTE), later.version)], "items:itm_solo")
            restored = db.head("items", item.id)
            self.assertFalse(packets.copied_unit_note(db, restored, self.NOTE))
            self.assertEqual(self.NOTE, packets._packet_record(restored, "independent", db)["body"]["uncertainty"])
            self.assertTrue(packets.copied_unit_note(db, db.version("items", item.id, 1), self.NOTE))

    def test_old_pinned_intake_is_compromised_after_clean_replacement(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            self.unit(db, legacy=True)
            audit = authoring.create_audit(db, mode="focused", targets=[R("items", "itm_solo")])["audit_id"]
            old = self.old_packet(db, audit)
            fresh = self.prepare(db, audit)
            worker = deepcopy(old["scaffold"])
            worker["coverage_note"] = "The supplied statement was examined."
            for row in worker["judgments"]:
                row.update(state="complete", outcome="gap", reasoning="No written proof was supplied.")
            submission = dict(contract_version=4, request_id=fixture.request_id(), packet_id=old["packet_id"],
                reviewer="independent checker", qualification_id=None, exposure="source_only", exposure_note="")
            original = canonical_bytes(worker)
            returned = review.submit_review(db, submission=submission, response_bytes=original)
            self.assertEqual("compromised", returned["exposure"])
            response = db.head("responses", returned["response_id"])
            self.assertIn("fresh blind context", response.body["exposure_note"])
            self.assertEqual(original, db.get_blob(response.body["original_blob"]))
            # A clean replacement cannot clear a worker's disclosed prior exposure.
            clean_worker = deepcopy(fresh["scaffold"])
            clean_worker["exposure_report"] = dict(status="possible_exposure", note="This context saw the old packet.")
            for row in clean_worker["judgments"]:
                row.update(state="complete", outcome="gap", reasoning="No written proof was supplied.")
            planned = review.plan_review_submission(db, submission=dict(submission,
                request_id=fixture.request_id(), packet_id=fresh["packet_id"]), response_bytes=canonical_bytes(clean_worker))
            self.assertEqual("compromised", planned["exposure"])
            self.assertEqual(response.body, db.version("responses", response.id, 1).body)


if __name__ == "__main__":
    import unittest
    unittest.main()
