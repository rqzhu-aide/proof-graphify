"""Exercise v3 authoring and policy boundaries through the actual writer."""
import json
import sqlite3
from contextlib import closing

from support import Fixture, TempCase, R
from paper_core import PROTOCOL_VERSION, packets
from paper_core.authoring import create_unit, create_audit
from paper_core.contract import validate_body
from paper_core.errors import IncompatibleError, InvalidRequest
from paper_core.storage import Database


class ContractTests(TempCase):
    def definition(self):
        return {"key": "one", "kind": "lemma", "label": "Lemma 1", "statement": "For every n, a_n <= 1.",
                "statement_anchors": ["anc_lem"], "proof_anchors": ["anc_lem_proof"],
                "proof_complete": True, "source_matched": True,
                "source_note": "The author examined the exact statement and full written proof."}

    def test_unit_authoring_is_atomic_and_idempotent(self):
        fixture = Fixture(self.path("unit")).anchors()
        with fixture.open() as db:
            result = create_unit(db, self.definition())
            revision = db.max_revision()
            again = create_unit(db, self.definition())
            self.assertTrue(again["reused"])
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.head("arguments", result["unit"]["argument"]).body["target"], R("items", "itm_one"))
            self.assertEqual(db.head("target_specs", "tgt_one").body["statement_ref"]["id"], "itm_one")
            self.assertEqual(len(db.heads("checks")), 0)
            self.assertEqual(len(db.heads("coverage")), 0)
            audit = create_audit(db, mode="focused", targets=[R("items", "itm_one")])
            body = db.head("audits", audit["audit_id"]).body
            self.assertEqual(body["protocol_version"], PROTOCOL_VERSION)
            self.assertEqual(body["global_tasks"], [])
            self.assertIsNone(body["qualification_id"])
            self.assertTrue(body["independent_required"])

    def test_optional_proof_idea_is_saved_without_review_credit_and_replays(self):
        fixture = Fixture(self.path("explanation")).anchors()
        with fixture.open() as db:
            definition = dict(self.definition(), proof_idea="The source proves the bound by induction.")
            result = create_unit(db, definition)
            item = db.head("items", result["unit"]["item"])
            self.assertEqual(definition["proof_idea"], item.body["proof_idea"])
            independent = packets._packet_record(item, "independent", db)
            self.assertNotIn("proof_idea", independent["body"])
            self.assertEqual([], packets.blinding_violations({"records": [independent]}))
            self.assertTrue(packets.blinding_violations({"records": [packets._packet_record(item, "primary", db)]}))
            revision = db.max_revision()
            self.assertTrue(create_unit(db, definition)["reused"])
            self.assertEqual(revision, db.max_revision())
            with self.assertRaises(InvalidRequest) as caught:
                create_unit(db, dict(definition, proof_idea="A different explanation."))
            self.assertEqual("UNIT_EXISTS", caught.exception.code)
            self.assertEqual(revision, db.max_revision())
            self.assertFalse(db.heads("checks"))
            self.assertFalse(db.heads("responses"))
            absent = dict(self.definition(), key="without_explanation")
            create_unit(db, absent)
            self.assertNotIn("proof_idea", db.head("items", "itm_without_explanation").body)
            revision = db.max_revision()
            for value in ("", "   ", None, 3, ["explanation"]):
                with self.subTest(value=value), self.assertRaises(InvalidRequest):
                    create_unit(db, dict(self.definition(), key="invalid_explanation", proof_idea=value))
                self.assertEqual(revision, db.max_revision())

    def test_bad_supplier_leaves_no_partial_unit(self):
        fixture = Fixture(self.path("bad")).anchors()
        with fixture.open() as db:
            definition = self.definition()
            definition["suppliers"] = [{"target": R("items", "itm_missing"), "reason": "needed",
                                        "needed_form": {"form": "verbatim", "text": "x > 0"}}]
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest):
                create_unit(db, definition)
            self.assertEqual(db.max_revision(), revision)
            self.assertIsNone(db.head("items", "itm_one"))

    def test_partial_extent_is_not_inferred_or_mislabeled(self):
        body = Fixture.check_edit("chk_a", R("arguments", "arg_a"), "composition")["body"]
        self.assertEqual(validate_body("checks", body), [])
        del body["extent"]
        self.assertTrue(validate_body("checks", body))
        body["extent"] = "partial"
        self.assertTrue(validate_body("checks", body))
        body["omissions"] = "The final supplement passage was unavailable."
        self.assertEqual(validate_body("checks", body), [])

    def test_new_feature_blocks_old_writer_and_old_protocol_is_read_only(self):
        fixture = Fixture(self.path("compat"))
        with fixture.open() as db:
            self.assertIn("coherent-examinations/1", json.loads(db.metadata["features"]))
        # Simulate historical metadata in a disposable fixture, never a saved audit.
        with closing(sqlite3.connect(fixture.path)) as conn:
            conn.execute("UPDATE metadata SET value='item-audit/1' WHERE key='protocol_version'")
            conn.commit()
        with self.assertRaises(IncompatibleError):
            Database(fixture.path, write=True)
        with Database(fixture.path) as db:
            self.assertEqual(db.metadata["protocol_version"], "item-audit/1")

    def test_malformed_unit_reports_a_local_error(self):
        fixture = Fixture(self.path("shape")).anchors()
        with fixture.open() as db:
            definition = self.definition()
            definition["suppliers"] = ["wrong shape"]
            with self.assertRaises(InvalidRequest):
                create_unit(db, definition)


if __name__ == "__main__":
    import unittest
    unittest.main()
