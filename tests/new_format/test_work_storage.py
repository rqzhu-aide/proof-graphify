"""Controller storage boundaries: durable input, atomic receipts and explicit migration."""
from __future__ import annotations

import json
import sqlite3
from unittest import mock

import support
from support import R, TempCase, edit
from paper_core import acceptance, export_import, packets, storage
from paper_core.canonical import canonical_bytes, digest
from paper_core.errors import ConflictError, IncompatibleError, InvalidRequest


class WorkStorageTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit(independent_required=False)

    def intake(self, db, request="req_work", packet=None, response=b"{malformed", envelope=b'{"request_id":"req_work"}'):
        if packet is None:
            packet = self.fx.packet(db, "items:itm_lem")
        kwargs = dict(request_id=request, request_digest=digest({"request": request, "response": response.hex()}),
                      packet_id=packet["packet_id"], audit_id="aud_1", role="primary",
                      envelope_bytes=envelope, response_bytes=response)
        db.begin_immediate()
        try:
            row = db.insert_work_submission(**kwargs)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return row, kwargs

    @staticmethod
    def result(row, state, receipt=None):
        return {"request_id": row["request_id"], "packet_id": row["packet_id"], "stored": True,
                "state": state, "committed_revision": None if receipt is None else receipt["revision"],
                "receipt": receipt, "record_map": {}, "remaining_task_ids": [], "diagnostics": [], "next_actions": []}

    def mathematical_accept(self, db, row):
        old = db.head("items", "itm_lem")
        return acceptance.accept_in_transaction(
            db, request_id=row["request_id"], request_digest=row["request_digest"], packet_id=row["packet_id"],
            edits=[edit("replace", "items", old.id, dict(old.body, caption="Saved controller reasoning"),
                        expected=old.version)], command="apply",
            receipt_context={"packet_id": row["packet_id"], "acceptance_packet_id": row["packet_id"]})

    def test_intake_retains_exact_original_bytes_without_a_revision(self):
        with self.fx.open() as db:
            before = db.max_revision()
            row, kwargs = self.intake(db)
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(row["state"], "received")
            self.assertIsNone(row["result"])
            self.assertEqual(db.get_blob(row["response_sha256"]), kwargs["response_bytes"])
            self.assertEqual(db.get_blob(row["envelope_sha256"]), kwargs["envelope_bytes"])
            self.assertIsNone(db.commit_by_request(row["request_id"]))

    def test_exact_intake_retry_preserves_first_envelope_and_rejects_changed_digest(self):
        with self.fx.open() as db:
            first, kwargs = self.intake(db)
            db.begin_immediate()
            replay = db.insert_work_submission(**dict(kwargs, envelope_bytes=b'{ "request_id": "req_work" }'))
            self.assertEqual(replay, first)
            with self.assertRaises(InvalidRequest) as caught:
                db.insert_work_submission(**dict(kwargs, request_digest="f" * 64))
            self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")
            db.rollback()

    def test_existing_noncontroller_commit_request_cannot_be_adopted(self):
        with self.fx.open() as db:
            old = db.commit_row(1)
            with self.assertRaises(InvalidRequest) as caught:
                self.intake(db, request=old["request_id"])
            self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_intake_requires_explicit_caller_transaction(self):
        with self.fx.open() as db:
            packet = self.fx.packet(db, "items:itm_lem")
            with self.assertRaises(InvalidRequest):
                db.insert_work_submission(request_id="req_no_transaction", request_digest="a" * 64,
                                          packet_id=packet["packet_id"], audit_id="aud_1", role="primary",
                                          envelope_bytes=b"{}", response_bytes=b"{}")

    def test_crash_before_math_commit_retains_received_input_only(self):
        with self.fx.open() as db:
            row, _ = self.intake(db)
            before = db.max_revision()
            db.begin_immediate()
            receipt = self.mathematical_accept(db, row)
            result = self.result(row, "accepted", receipt)
            db.finalize_work_submission(row["request_id"], state="accepted", result=result,
                                        committed_revision=receipt["revision"])
            db.rollback()
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.work_submission(row["request_id"])["state"], "received")
            self.assertEqual(db.head("items", "itm_lem").version, 1)

    def test_commit_and_terminal_receipt_are_atomic_and_retry_leaves_caller_transaction_open(self):
        with self.fx.open() as db:
            row, _ = self.intake(db)
            db.begin_immediate()
            receipt = self.mathematical_accept(db, row)
            result = self.result(row, "accepted", receipt)
            db.finalize_work_submission(row["request_id"], state="accepted", result=result,
                                        committed_revision=receipt["revision"])
            db.commit()
            stored = db.work_submission(row["request_id"])
            self.assertEqual(stored["result"]["receipt"], json.loads(db.commit_by_request(row["request_id"])["receipt_json"]))
            db.begin_immediate()
            replay = acceptance.accept_in_transaction(db, request_id=row["request_id"],
                request_digest=row["request_digest"], packet_id="pkt_no_longer_needed", edits=[], command="apply")
            self.assertEqual(replay, receipt)
            self.assertTrue(db.conn.in_transaction)
            self.assertEqual(db.finalize_work_submission(row["request_id"], state="conflict",
                                                         result={}), stored)
            db.rollback()

    def test_finalization_cannot_link_a_different_mathematical_receipt(self):
        with self.fx.open() as db:
            row, _ = self.intake(db)
            db.begin_immediate()
            receipt = self.mathematical_accept(db, row)
            invalid = self.result(row, "accepted", dict(receipt, warnings=["invented"]))
            with self.assertRaises(InvalidRequest) as caught:
                db.finalize_work_submission(row["request_id"], state="accepted", result=invalid,
                                            committed_revision=receipt["revision"])
            self.assertEqual(caught.exception.code, "SUBMISSION_INTEGRITY")
            db.rollback()

    def test_rejected_input_can_finalize_without_a_mathematical_commit(self):
        with self.fx.open() as db:
            row, _ = self.intake(db)
            before = db.max_revision()
            db.begin_immediate()
            result = self.result(row, "needs_revision")
            db.finalize_work_submission(row["request_id"], state="needs_revision", result=result)
            db.commit()
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.work_submission(row["request_id"])["result"], result)

    def test_sql_prevents_terminal_update_delete_and_input_rewrite(self):
        with self.fx.open() as db:
            row, _ = self.intake(db)
            for sql in ("DELETE FROM work_submissions", "UPDATE work_submissions SET role='independent'",
                        "UPDATE work_submissions SET request_digest='" + "b" * 64 + "'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.conn.execute(sql)
            db.begin_immediate()
            db.finalize_work_submission(row["request_id"], state="conflict", result=self.result(row, "conflict"))
            db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                db.conn.execute("UPDATE work_submissions SET result_json='{}'")

    def test_history_is_bounded_metadata_with_stable_keyset_continuation(self):
        with self.fx.open() as db:
            for index in range(3):
                self.intake(db, request=f"req_history_{index}")
            first = db.work_submissions(audit_id="aud_1", limit=2)
            self.assertEqual(len(first), 2)
            self.assertNotIn("result", first[0])
            self.assertNotIn("response_sha256", first[0])
            rest = db.work_submissions(audit_id="aud_1", limit=2,
                                       after=[first[-1]["received_at"], first[-1]["request_id"]])
            self.assertEqual(len(rest), 1)
            self.assertNotIn(rest[0]["request_id"], [r["request_id"] for r in first])
            with self.assertRaises(InvalidRequest):
                db.work_submissions(limit=101)

    def test_backup_preserves_input_and_receipts_while_math_export_omits_intake_only_blobs(self):
        with self.fx.open() as db:
            received, kwargs = self.intake(db, response=b"unique unfinished work")
            rejected, _ = self.intake(db, request="req_bad", response=b"unique invalid work")
            db.begin_immediate()
            db.finalize_work_submission(rejected["request_id"], state="needs_revision",
                                        result=self.result(rejected, "needs_revision"))
            db.commit()
            exported = export_import.export_snapshot(db)
            self.assertNotIn(received["response_sha256"], [b["sha256"] for b in exported["blobs"]])
            backup = self.path("recovered.db")
            db.backup(backup)
        with storage.Database(backup, write=True) as copied:
            self.assertEqual(copied.work_submission(received["request_id"]), received)
            self.assertEqual(copied.get_blob(received["response_sha256"]), kwargs["response_bytes"])
            self.assertEqual(copied.work_submission(rejected["request_id"])["state"], "needs_revision")
            copied.begin_immediate()
            receipt = self.mathematical_accept(copied, received)
            copied.finalize_work_submission(received["request_id"], state="accepted",
                result=self.result(received, "accepted", receipt), committed_revision=receipt["revision"])
            copied.commit()

    def test_insert_packet_uses_manifest_version_not_current_emission_default(self):
        with self.fx.open() as db:
            generic = self.fx.packet(db, "items:itm_lem")
            manifest = dict(db.packet(generic["packet_id"])["manifest"], packet_id="pkt_historical", packet_version=1)
            db.begin_immediate()
            db.insert_packet("pkt_historical", manifest["base_revision"], manifest["mode"], manifest,
                             db.put_blob(canonical_bytes(manifest)))
            db.commit()
            self.assertEqual(db.packet("pkt_historical")["packet_version"], 1)

    def test_task_freshness_hook_cannot_be_used_on_an_ordinary_packet(self):
        with self.fx.open() as db:
            packet = self.fx.packet(db, "items:itm_lem")
            db.begin_immediate()
            with self.assertRaises(InvalidRequest):
                acceptance.accept_in_transaction(db, request_id="req_hook", request_digest="a" * 64,
                    packet_id=packet["packet_id"], edits=[], command="apply",
                    freshness_validator=lambda db, manifest, plan: dict(manifest, read_set=[]))
            self.assertTrue(db.conn.in_transaction)
            db.rollback()

    def test_task_hook_cannot_change_identity_even_by_mutating_its_argument(self):
        with self.fx.open() as db:
            generic = self.fx.packet(db, "items:itm_lem", mode="primary")
            manifest = dict(db.packet(generic["packet_id"])["manifest"], packet_id="pkt_work_guard",
                            work={"audit_id": "aud_1", "tasks": []})
            db.begin_immediate()
            db.insert_packet(manifest["packet_id"], manifest["base_revision"], "primary", manifest,
                             db.put_blob(canonical_bytes(manifest)))
            db.commit()

            def invalid_hook(db, supplied, plan):
                supplied["source_context_digest"] = "f" * 64
                supplied["read_set"] = []
                return supplied

            db.begin_immediate()
            with self.assertRaises(InvalidRequest) as caught:
                acceptance.accept_in_transaction(db, request_id="req_bad_hook", request_digest="a" * 64,
                    packet_id=manifest["packet_id"], edits=[], command="work_primary",
                    freshness_validator=invalid_hook)
            self.assertIn("changed packet identity", str(caught.exception))
            self.assertEqual(db.packet(manifest["packet_id"])["manifest"], manifest)
            db.rollback()

    def test_generic_apply_cannot_use_a_prepared_work_packet(self):
        with self.fx.open() as db:
            generic = self.fx.packet(db, "items:itm_lem", mode="primary")
            manifest = dict(db.packet(generic["packet_id"])["manifest"], packet_id="pkt_work_only",
                            work={"audit_id": "aud_1", "tasks": []})
            db.begin_immediate()
            db.insert_packet(manifest["packet_id"], manifest["base_revision"], "primary", manifest,
                             db.put_blob(canonical_bytes(manifest)))
            db.commit()
            with self.assertRaises(InvalidRequest) as caught:
                acceptance.apply_batch(db, self.fx.batch([], manifest["packet_id"]))
            self.assertEqual(caught.exception.code, "WORK_SUBMIT_REQUIRED")


class MigrationTests(TempCase):
    def legacy(self):
        """Materialize genuine native-2 tables and inline legacy use bodies."""
        with mock.patch.object(packets, "PACKET_VERSION", 1):
            fixture = self.fixture().structure()
        ddl = (support.HANDOFF / "schema.sql").read_text(encoding="utf-8")
        start, end = ddl.index("-- The operational intake index"), ddl.index("CREATE TABLE publications (")
        ddl = (ddl[:start] + ddl[end:]).replace("('storage_format', '3')", "('storage_format', '2')")
        ddl = ddl.replace("packet_version IN (1, 2)", "packet_version = 1")
        path = self.path("legacy-native2.db")
        prior = sqlite3.connect(path)
        try:
            prior.executescript(ddl)
            prior.execute("PRAGMA foreign_keys=OFF")
            prior.execute("ATTACH DATABASE ? AS seeded", (str(fixture.path),))
            for table, in prior.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='metadata'").fetchall():
                where = " WHERE collection != 'application_details'" if table in ("record_versions", "record_heads", "record_facets") else ""
                if table in ("record_refs", "evidence_bindings"):
                    where = " WHERE owner_collection != 'application_details'"
                if table == "record_versions":
                    for row in prior.execute("SELECT * FROM seeded.record_versions" + where).fetchall():
                        values = list(row)
                        if values[0] == "uses" and values[5] is not None:
                            body = json.loads(values[5])
                            body.update(group_id="grp_thm", needed_form={"form": "synopsis", "text": "A bound on a_n"}, substitutions=[])
                            values[5], values[6] = canonical_bytes(body).decode(), digest(body)
                        prior.execute("INSERT INTO record_versions VALUES (?,?,?,?,?,?,?)", values)
                else:
                    prior.execute(f"INSERT INTO {table} SELECT * FROM seeded.{table}{where}")
            prior.execute("INSERT INTO record_refs VALUES ('uses','use_lem_thm',1,'/group_id','groups','grp_thm',NULL)")
            prior.execute("INSERT OR IGNORE INTO metadata SELECT * FROM seeded.metadata WHERE key!='generation'")
            prior.execute("UPDATE metadata SET value='1' WHERE key IN ('packet_version','projection_version')")
            prior.execute("UPDATE metadata SET value=? WHERE key='features'", (json.dumps(["records/3", "packets/1", "audits/1", "independent-review/1", "projection/1"]),))
            prior.commit()
        finally:
            prior.close()
        fixture.path = path
        return fixture

    def test_native2_reads_and_exports_actual_format_but_cannot_be_opened_for_write(self):
        fx = self.legacy()
        with storage.Database(fx.path) as db:
            self.assertEqual(export_import.export_snapshot(db)["storage_format"], 2)
            self.assertEqual(export_import.export_snapshot(db)["contract_version"], 3)
            self.assertEqual(db.work_submissions(), [])
            self.assertIsNone(db.work_submission("req_none"))
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(fx.path, write=True)
        self.assertEqual(caught.exception.code, "MIGRATION_REQUIRED")

    def test_migration_preserves_history_receipts_packet1_payloads_and_backup(self):
        fx = self.legacy()
        with storage.Database(fx.path) as old:
            records = old.all_versions()
            commits = [dict(row) for row in old.conn.execute("SELECT * FROM commits ORDER BY revision")]
            packet_rows = [dict(row) for row in old.conn.execute("SELECT * FROM packets ORDER BY packet_id")]
            blobs = {sha: old.get_blob(sha) for sha in old.blob_hashes()}
        backup = self.path("before.db")
        result = storage.migrate_database(fx.path, backup=backup)
        self.assertTrue(result["migrated"])
        with storage.Database(fx.path, write=True) as updated:
            self.assertEqual(updated.metadata["storage_format"], "4")
            self.assertNotIn("work-context-extension/1", json.loads(updated.metadata["features"]))
            self.assertEqual([r for r in updated.all_versions() if r.revision <= records[-1].revision], records)
            self.assertNotIn("group_id", updated.head("uses", "use_lem_thm").body)
            self.assertEqual(updated.head("application_details", "use_lem_thm").body["group_id"], "grp_thm")
            self.assertEqual([dict(row) for row in updated.conn.execute("SELECT * FROM commits WHERE revision<=? ORDER BY revision", (commits[-1]["revision"],))], commits)
            self.assertEqual([dict(row) for row in updated.conn.execute("SELECT * FROM packets ORDER BY packet_id")], packet_rows)
            self.assertTrue(all(row["packet_version"] == 1 for row in packet_rows))
            self.assertEqual({sha: updated.get_blob(sha) for sha in updated.blob_hashes()}, blobs)
            self.assertEqual(updated.integrity(), {"foreign_key_violations": [], "integrity": ["ok"]})
            self.assertIsNotNone(updated.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='packets_work_audit'").fetchone())
            new = fx.packet(updated, "items:itm_lem")
            self.assertEqual(updated.packet(new["packet_id"])["packet_version"], 2)
        with storage.Database(backup) as retained:
            self.assertEqual(retained.metadata["storage_format"], "2")
            self.assertEqual(retained.all_versions(), records)

    def test_already_current_does_not_create_backup_or_revision(self):
        fx = self.fixture()
        backup = self.path("unused.db")
        result = storage.migrate_database(fx.path, backup=backup)
        self.assertFalse(result["migrated"])
        self.assertFalse(backup.exists())

    def test_existing_backup_is_never_overwritten(self):
        fx = self.legacy()
        backup = self.path("existing.db")
        backup.write_bytes(b"keep me")
        with self.assertRaises(InvalidRequest):
            storage.migrate_database(fx.path, backup=backup)
        self.assertEqual(backup.read_bytes(), b"keep me")
        with storage.Database(fx.path) as db:
            self.assertEqual(db.metadata["storage_format"], "2")

    def test_failure_after_packet_rebuild_rolls_back_schema_and_keeps_backup(self):
        fx = self.legacy()
        backup = self.path("untouched.db")
        original = storage._schema_statements

        def fail_work(text):
            if "CREATE TABLE work_submissions" in text:
                raise RuntimeError("injected migration interruption")
            return original(text)

        with mock.patch.object(storage, "_schema_statements", fail_work), self.assertRaises(RuntimeError):
            storage.migrate_database(fx.path, backup=backup)
        with storage.Database(fx.path) as db:
            self.assertEqual(db.metadata["storage_format"], "2")
            schema = db.conn.execute("SELECT sql FROM sqlite_master WHERE name='packets'").fetchone()[0]
            self.assertIn("packet_version = 1", schema)
            self.assertIsNone(db.conn.execute("SELECT name FROM sqlite_master WHERE name='packets_v3'").fetchone())
        self.assertTrue(backup.exists())

    def test_concurrent_operational_change_during_backup_aborts_even_without_new_revision(self):
        fx = self.legacy()
        real_open = storage._open

        class RacingConnection(sqlite3.Connection):
            def backup(self, target, *args, **kwargs):
                super().backup(target, *args, **kwargs)
                other = sqlite3.connect(str(fx.path))
                other.execute("INSERT INTO metadata VALUES ('concurrent_operational_note', 'changed')")
                other.commit()
                other.close()

        def open_racing(path, *, write):
            if path == fx.path:
                conn = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True,
                                       autocommit=True, factory=RacingConnection)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                return conn
            return real_open(path, write=write)

        with mock.patch.object(storage, "_open", open_racing), self.assertRaises(ConflictError):
            storage.migrate_database(fx.path, backup=self.path("concurrent-backup.db"))
        with storage.Database(fx.path) as db:
            self.assertEqual(db.metadata["storage_format"], "2")


if __name__ == "__main__":
    import unittest
    unittest.main()
