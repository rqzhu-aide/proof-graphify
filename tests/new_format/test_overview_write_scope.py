"""Protocol and normalized-field permissions for ordinary overview writers."""
import copy
from contextlib import closing
import json
import sqlite3
import sys
from unittest import mock

from support import OVERVIEW, TempCase, write_json
sys.path.insert(0, str(OVERVIEW / "scripts"))
import paper_database as overview_cli
from paper_core import acceptance, overview, storage
from paper_core import COHERENT_EXAMINATIONS_FEATURE, OVERVIEW_PROTOCOL_VERSION, PROTOCOL_VERSION
from paper_core.canonical import digest
from paper_core.errors import IncompatibleError, InvalidRequest


class OverviewWriteScopeTests(TempCase):
    def setUp(self):
        super().setUp()
        core = mock.patch.object(overview_cli, "_common_core", return_value=(
            overview, storage.Database, storage.initialize, storage.paper_record))
        core.start()
        self.addCleanup(core.stop)
        self.path("paper.txt").write_text("A is nonnegative.\nA plus one is positive.\nAdd one.\n", encoding="utf-8")
        self.seed = write_json(self.path("seed.json"), {
            "schema_version": 3, "title": "Selected statements", "scope": "Two results", "main_items": ["T"],
            "source": {"title": "Paper", "file": "paper.txt"},
            "items": [{"id": name, "kind": kind, "label": name, "caption": name,
                       "statement": {"form": "synopsis", "text": text},
                       "source": {"start_line": line, "end_line": line}}
                      for name, kind, text, line in (("A", "lemma", "A is nonnegative", 1),
                                                    ("T", "theorem", "A plus one is positive", 2))],
            "uses": [{"id": "u", "from": "A", "to": "T", "reason": "Add one",
                      "source": {"start_line": 3, "end_line": 3}}]})
        self.db_path = self.path("selected.db")
        overview_cli.init_database(self.db_path, self.seed, focused=True)

    def replace(self, db, collection, identity, **fields):
        head = db.head(collection, identity)
        return {"op": "replace", "collection": collection, "id": identity, "expected_version": head.version,
                "body": dict(head.body, **fields)}

    def reject(self, edits, *, command="overview"):
        with storage.Database(self.db_path, write=True, write_scope="overview") as db:
            before = [(r.collection, r.id, r.version, r.body) for r in db.all_versions()]
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                acceptance.accept(db, request_id="denied", request_digest=digest(edits), packet_id=None,
                                  edits=edits, command=command)
            self.assertEqual(caught.exception.code, "WRITE_SCOPE")
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual([(r.collection, r.id, r.version, r.body) for r in db.all_versions()], before)
            self.assertFalse(db.conn.in_transaction)

    def test_initialization_has_one_protocol_and_no_coherent_feature_requirement(self):
        with storage.Database(self.db_path) as db:
            self.assertEqual(db.metadata["protocol_version"], OVERVIEW_PROTOCOL_VERSION)
            self.assertNotIn(COHERENT_EXAMINATIONS_FEATURE, json.loads(db.metadata["features"]))
            self.assertFalse(any("overview_protocol" in key for key in db.metadata))
        with self.assertRaises(IncompatibleError):
            storage.Database(self.db_path, write=True)

    def test_supported_protocol_matrix_keeps_historical_protocol_labels(self):
        for protocol in ("item-audit/1", OVERVIEW_PROTOCOL_VERSION, PROTOCOL_VERSION, "unknown/1"):
            with self.subTest(protocol=protocol):
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.execute("UPDATE metadata SET value=? WHERE key='protocol_version'", (protocol,))
                    conn.commit()
                if protocol == "unknown/1":
                    with self.assertRaises(IncompatibleError):
                        storage.Database(self.db_path, write=True, write_scope="overview")
                else:
                    data = overview_cli.export_snapshot(self.db_path)
                    overview_cli.apply_edits(self.db_path, {"expected_snapshot": data["snapshot_id"], "edits": [],
                        "set": {"scope": "Selected statements in " + protocol}})
                    with storage.Database(self.db_path) as db:
                        self.assertEqual(db.metadata["protocol_version"], protocol)
                if protocol != PROTOCOL_VERSION:
                    with self.assertRaises(IncompatibleError):
                        storage.Database(self.db_path, write=True)
                else:
                    with storage.Database(self.db_path, write=True):
                        pass

    def test_unknown_scope_and_workflow_are_rejected_before_creating_a_file(self):
        missing = self.path("unknown.db")
        with self.assertRaises(InvalidRequest):
            storage.initialize(missing, source_root=self.work, title="Unknown", workflow="other")
        self.assertFalse(missing.exists())
        with self.assertRaises(InvalidRequest):
            storage.Database(missing, write_scope="other")

    def test_legacy_common_formats_remain_readable_and_unwritable(self):
        for fmt in (2, 3):
            with self.subTest(storage_format=fmt):
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.execute("UPDATE metadata SET value=? WHERE key='storage_format'", (str(fmt),))
                    conn.execute("UPDATE metadata SET value='3' WHERE key='contract_version'")
                    conn.commit()
                with storage.Database(self.db_path) as db:
                    self.assertEqual(db.metadata["storage_format"], str(fmt))
                for scope in ("overview", "audit"):
                    with self.assertRaises(IncompatibleError) as caught:
                        storage.Database(self.db_path, write=True, write_scope=scope)
                    self.assertEqual(caught.exception.code, "MIGRATION_REQUIRED")

    def test_unknown_feature_and_incompatible_contract_are_rejected(self):
        for field, value in (("features", '["unknown/1"]'), ("contract_version", "99")):
            with self.subTest(field=field):
                with closing(sqlite3.connect(self.db_path)) as conn:
                    original = conn.execute("SELECT value FROM metadata WHERE key=?", (field,)).fetchone()[0]
                    conn.execute("UPDATE metadata SET value=? WHERE key=?", (value, field))
                    conn.commit()
                try:
                    for scope in ("audit", "overview"):
                        with self.assertRaises(IncompatibleError):
                            storage.Database(self.db_path, write=True, write_scope=scope)
                finally:
                    with closing(sqlite3.connect(self.db_path)) as conn:
                        conn.execute("UPDATE metadata SET value=? WHERE key=?", (original, field))
                        conn.commit()

    def test_reading_an_audit_store_does_not_create_a_selection(self):
        fresh = self.path("audit.db")
        storage.initialize(fresh, source_root=self.work, title="Fresh audit")
        with storage.Database(fresh) as db:
            with self.assertRaises(InvalidRequest):
                overview.project(db)
            self.assertEqual(db.max_revision(), 1)
            self.assertEqual(db.heads("overview_selections"), [])

    def test_protocol_and_generation_are_rechecked_under_the_writer_lock(self):
        for field, value in (("protocol_version", "unknown/1"), ("generation", "new-generation"),
                             ("features", '["unknown/1"]')):
            with self.subTest(field=field):
                with storage.Database(self.db_path, write=True, write_scope="overview") as db:
                    db.begin_immediate()
                    db.conn.execute("UPDATE metadata SET value=? WHERE key=?", (value, field))
                    try:
                        with self.assertRaises(IncompatibleError):
                            acceptance.accept_in_transaction(db, request_id="changed-meta", request_digest="x",
                                packet_id=None, edits=[], command="overview")
                    finally:
                        db.rollback()

    def test_other_commands_and_metadata_writes_are_unavailable(self):
        for command in ("import", "source_capture", "qualification", "apply", "work_primary"):
            with self.subTest(command=command):
                self.reject([], command=command)
        with storage.Database(self.db_path, write=True, write_scope="overview") as db:
            db.begin_immediate()
            try:
                for key in ("protocol_version", "features", "overview_build:arbitrary"):
                    with self.subTest(key=key), self.assertRaises(InvalidRequest):
                        db.set_metadata(key, "arbitrary")
            finally:
                db.rollback()

    def test_existing_nonoverview_fields_and_authoring_profile_are_protected(self):
        with storage.Database(self.db_path) as db:
            paper = storage.paper_record(db)
            source = db.heads("sources")[0]
            edits = [self.replace(db, "items", "A", origin="proposed_repair"),
                     self.replace(db, "items", "A", scope_id="audit-scope"),
                     self.replace(db, "papers", paper.id, report_paths=["changed.html"]),
                     self.replace(db, "papers", paper.id, source_root=self.path("elsewhere").as_posix()),
                     self.replace(db, "sources", source.id, capture_method="changed"),
                     self.replace(db, "sources", source.id, limitation="changed"),
                     self.replace(db, "overview_selections", overview.SELECTION_ID, authoring_profile="compatibility")]
        for entry in edits:
            with self.subTest(collection=entry["collection"], body=entry["body"]):
                self.reject([entry])

    def test_application_normalization_cannot_bypass_the_overview_boundary(self):
        with storage.Database(self.db_path) as db:
            entry = self.replace(db, "uses", "u", group_id=None,
                needed_form={"form": "synopsis", "text": "An exact application"}, substitutions=[])
        self.reject([entry])
        with storage.Database(self.db_path) as db:
            self.assertEqual(db.heads("application_details"), [])

    def test_selection_archive_cannot_shadow_an_immutable_comparison(self):
        data = overview_cli.export_snapshot(self.db_path)
        overview_cli.compare_records(self.db_path, {"basis": "source_text", "expected_snapshot": data["snapshot_id"],
            "targets": [{"collection": "items", "id": "T"}], "reviewer": "reader",
            "result": "needs_attention", "note": "The selected statement needs attention."})
        current = overview_cli.export_snapshot(self.db_path)
        original = current["observations"][0]
        forged = dict(original, result="matched")
        with storage.Database(self.db_path) as db:
            selection = db.head("overview_selections", overview.SELECTION_ID)
            context = dict(selection.body["native_context"], archived_observations=[forged])
            entry = self.replace(db, "overview_selections", overview.SELECTION_ID, native_context=context)
        self.reject([entry])
        # Even a historical selection with a duplicate archive cannot override
        # the original canonical source comparison on read.
        with storage.Database(self.db_path) as db:
            body = dict(selection.body, native_context=context)
            archived_selection = storage.Record(selection.collection, selection.id, selection.version,
                selection.revision, selection.retired, body)
            read_records = db.records_at
            def historical(revision, collection=None):
                return [archived_selection] if collection == "overview_selections" else read_records(revision, collection)
            with mock.patch.object(db, "records_at", side_effect=historical):
                projected, _ = overview.project(db)
                self.assertEqual(projected["observations"][0], original)

    def test_collection_whitelist_does_not_authorize_unselected_or_formal_records(self):
        with storage.Database(self.db_path) as db:
            body = copy.deepcopy(db.head("items", "A").body)
            edits = [{"op": "create", "collection": "items", "id": "unselected", "body": body}]
        self.reject(edits)
        self.reject([{"op": "create", "collection": "groups", "id": "formal", "body": {}}])

    def test_focused_selection_cannot_create_a_proof_step_through_acceptance(self):
        with storage.Database(self.db_path) as db:
            body = dict(db.head("items", "A").body, kind="equation", owner_id="T")
            selected = db.head("overview_selections", overview.SELECTION_ID)
            selection = dict(selected.body, item_ids=selected.body["item_ids"] + ["step"])
            edits = [{"op": "create", "collection": "items", "id": "step", "body": body},
                     self.replace(db, "overview_selections", overview.SELECTION_ID, **selection)]
        self.reject(edits)

    def test_receipts_are_canonical_immutable_and_idempotent(self):
        receipt = {"input_snapshot": "actual", "source_status": {"current": True}, "output": "page.html"}
        with storage.Database(self.db_path, write=True, write_scope="overview") as db:
            with self.assertRaises(InvalidRequest):
                overview.record_build_receipt(db, receipt)
            db.begin_immediate()
            key = overview.record_build_receipt(db, receipt)
            self.assertEqual(overview.record_build_receipt(db, dict(reversed(list(receipt.items())))), key)
            self.assertEqual(db.conn.execute("SELECT count(*) FROM metadata WHERE key LIKE 'overview_build:%'").fetchone()[0], 1)
            db.commit()
            db.begin_immediate()
            db.conn.execute("UPDATE metadata SET value='different historical bytes' WHERE key=?", (key,))
            try:
                with self.assertRaises(InvalidRequest):
                    overview.record_build_receipt(db, receipt)
            finally:
                db.rollback()

    def test_failed_receipt_preserves_delivered_html_and_reports_the_error(self):
        output = self.path("overview.html")
        def render(data, source_root, destination, **kwargs):
            destination.write_text("<html>Delivered overview</html>", encoding="utf-8")
            return {"output": str(destination), "snapshot_id": data["snapshot_id"], "warnings": []}
        with mock.patch("proof_overview._render_validated_dataset", side_effect=render), \
                mock.patch.object(overview, "record_build_receipt", side_effect=InvalidRequest("receipt unavailable")):
            result = overview_cli.render_database(self.db_path, output)
        self.assertTrue(output.is_file())
        self.assertFalse(result["build_recorded"])
        self.assertIn("receipt unavailable", result["build_record_error"])
