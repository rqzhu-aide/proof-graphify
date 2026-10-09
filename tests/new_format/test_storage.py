"""Behaviour tests for ``paper_core.storage`` and ``schema.sql`` (implementation-handoff 4.1, 9).

Everything here goes through the real public API: fixtures are built by ``support.Fixture`` stages,
writes go through ``acceptance.apply_batch`` or the storage writer methods, and the only raw SQL is the
deliberate tampering used to prove that the schema's triggers, CHECK constraints and foreign keys refuse
it. Incompatible databases are built by rewriting or deleting one metadata value on a copy of a real
database, never by hand-crafting a file.
"""
from __future__ import annotations

import json
import importlib.util
import pathlib
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import support
from support import CORE, HANDOFF, Fixture, R, TempCase, edit
from paper_core import (CONTRACT_VERSION, CORE_VERSION, DEFAULT_FEATURES, LEGACY_OVERVIEW_FORMAT, PACKET_VERSION,
                        PROJECTION_VERSION, PROTOCOL_VERSION, STORAGE_FORMAT, SUPPORTED_FEATURES,
                        acceptance, packets, storage)
from paper_core.canonical import digest
from paper_core.errors import ConflictError, IncompatibleError, InvalidRequest, SourceUnavailable

METADATA_KEYS = ["contract_version", "core_version", "created_at", "features", "packet_version",
                 "projection_version", "protocol_version", "storage_format"]
METADATA_KEYS = sorted(METADATA_KEYS + ["generation"])
TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"


# -- module-local helpers ---------------------------------------------------------------------------
def structure_log(fixture: Fixture) -> list:
    """The entire append-only log of a freshly structured fixture: (revision, collection, id, version).

    Each fixture stage is exactly one commit, so the revision column also pins that init, capture,
    anchoring and structuring each allocate one revision and land their records together.
    """
    return [(1, "papers", fixture.paper_id, 1),
            (2, "sources", fixture.source_id, 1),
            (3, "anchors", "anc_lem", 1),
            (3, "anchors", "anc_lem_proof", 1),
            (3, "anchors", "anc_thm", 1),
            (3, "anchors", "anc_thm_proof", 1),
            (4, "application_details", "use_lem_thm", 1),
            (4, "arguments", "arg_lem", 1),
            (4, "arguments", "arg_thm", 1),
            (4, "groups", "grp_lem", 1),
            (4, "groups", "grp_thm", 1),
            (4, "items", "itm_lem", 1),
            (4, "items", "itm_thm", 1),
            (4, "scopes", "scp_plain", 1),
            (4, "uses", "use_lem_thm", 1)]


def structure_heads(fixture: Fixture) -> list:
    """The same records as ``heads()`` orders them: by collection, then id."""
    return sorted((collection, id, version) for _, collection, id, version in structure_log(fixture))


def retire(collection: str, id: str, version: int, reason: str = "no longer needed") -> dict:
    """A retire edit; the batch schema is closed, so a retire carries a reason and never a body."""
    return {"op": "retire", "collection": collection, "id": id, "expected_version": version, "reason": reason}


def spare_item(id: str, label: str) -> dict:
    """A standalone reconstructed assumption that nothing else in the fixture references."""
    return edit("create", "items", id, {
        "kind": "assumption", "label": label, "caption": label,
        "statement": {"form": "synopsis", "text": label.lower()}, "passages": [], "aliases": [],
        "uncertainty": None, "origin": "reconstruction", "owner_id": None, "scope_id": None})


def spare_use(id: str, source_item: str, target_item: str) -> dict:
    """An ungrouped dependency edge, the one record kind the fixture can retire without orphaning a proof."""
    return edit("create", "uses", id, {
        "from": R("items", source_item), "to": R("items", target_item), "type": "dependency",
        "group_id": None, "reason": "spare edge", "needed_form": None, "substitutions": [],
        "evidence_refs": [], "regime": None, "uncertainty": None})


def bump_caption(fixture: Fixture, db, caption: str) -> int:
    """Append one new version of ``items:itm_lem`` through the acceptance path; return the new revision."""
    head = db.head("items", "itm_lem")
    fixture.apply(db, [edit("replace", "items", "itm_lem", dict(head.body, caption=caption),
                            expected=head.version)], "items:itm_lem")
    return db.max_revision()


def race(fixture: Fixture) -> dict:
    """Two write connections read ``items:itm_lem`` at one version; the first commits, the second retries.

    Returns the winner's receipt, the loser's ConflictError, the revision and versions both writers read,
    and whether the loser's connection was left inside a transaction.
    """
    first = storage.Database(fixture.path, write=True)
    second = storage.Database(fixture.path, write=True)
    try:
        packet_first = packets.get_packet(first, targets=[R("items", "itm_lem")], mode="author")
        packet_second = packets.get_packet(second, targets=[R("items", "itm_lem")], mode="author")
        head_first = first.head("items", "itm_lem")
        head_second = second.head("items", "itm_lem")
        before = first.max_revision()
        winner = acceptance.apply_batch(first, {
            "contract_version": 3, "request_id": "req_race_first", "packet_id": packet_first["packet_id"],
            "edits": [edit("replace", "items", "itm_lem", dict(head_first.body, caption="first writer"),
                           expected=head_first.version)]})
        loser = None
        try:
            acceptance.apply_batch(second, {
                "contract_version": 3, "request_id": "req_race_second", "packet_id": packet_second["packet_id"],
                "edits": [edit("replace", "items", "itm_lem", dict(head_second.body, caption="second writer"),
                               expected=head_second.version)]})
        except ConflictError as exc:
            loser = exc
        return {"winner": winner, "loser": loser, "before": before,
                "first_version": head_first.version, "second_version": head_second.version,
                "first_base": packet_first["base_revision"], "second_base": packet_second["base_revision"],
                "loser_in_transaction": second.conn.in_transaction}
    finally:
        first.close()
        second.close()


class StorageCase(TempCase):
    """Shared scaffolding: a structured fixture and an assertion that a raw write is refused wholesale."""

    def structured(self, name="paper", **kwargs) -> Fixture:
        return self.fixture(name, **kwargs).structure()

    def coherent_fixture(self):
        """Reuse the current audit fixture for binding tests, leaving historical policy fixtures intact."""
        spec = importlib.util.spec_from_file_location(
            "coherent_storage_test_support", support.PROOFCHECK / "tests" / "support.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.Fixture(self.path("coherent-paper"))

    def assert_write_refused(self, fixture: Fixture, action, fragment: str):
        """Run ``action`` in one transaction, assert it aborts with ``fragment``, and that nothing landed."""
        with fixture.open() as db:
            before_revision = db.max_revision()
            before_versions = [(r.collection, r.id, r.version) for r in db.all_versions()]
            before_heads = [(r.collection, r.id, r.version) for r in db.heads(include_retired=True)]
            db.begin_immediate()
            try:
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    action(db)
                    db.commit()
            finally:
                db.rollback()
            self.assertIn(fragment, str(caught.exception))
        with fixture.open(write=False) as db:
            self.assertEqual(db.max_revision(), before_revision)
            self.assertEqual([(r.collection, r.id, r.version) for r in db.all_versions()], before_versions)
            self.assertEqual([(r.collection, r.id, r.version) for r in db.heads(include_retired=True)],
                             before_heads)

    def broken_copy(self, fixture: Fixture, key: str, value: str, name: str):
        """Copy a healthy database and rewrite one metadata value through ``set_metadata``."""
        target = self.work / f"{name}.db"
        shutil.copyfile(fixture.path, target)
        with storage.Database(target, write=True) as db:
            db.begin_immediate()
            db.set_metadata(key, value)
            db.commit()
        return target

    def stripped_copy(self, fixture: Fixture, key: str, name: str):
        """Copy a healthy database and delete one metadata row; metadata is the one mutable table."""
        target = self.work / f"{name}.db"
        shutil.copyfile(fixture.path, target)
        raw = sqlite3.connect(str(target))
        try:
            raw.execute("DELETE FROM metadata WHERE key = ?", (key,))
            raw.commit()
        finally:
            raw.close()
        return target


# -- initialize -------------------------------------------------------------------------------------
class InitializeTests(StorageCase):
    def source_dir(self):
        root = self.path("src")
        root.mkdir(exist_ok=True)
        (root / "paper.tex").write_text(support.PAPER_TEX, encoding="utf-8")
        return root

    def test_initialize_returns_the_path_paper_id_revision_and_creation_receipt(self):
        """initialize() reports revision 1, a pap_ identifier, and a receipt creating exactly that paper."""
        target = self.work / "fresh.db"
        info = storage.initialize(target, source_root=self.source_dir(), title="Fresh paper")
        self.assertEqual(sorted(info), ["database", "paper_id", "receipt", "revision"])
        self.assertEqual(info["database"], str(target))
        self.assertEqual(info["revision"], 1)
        self.assertTrue(info["paper_id"].startswith("pap_"), info["paper_id"])
        self.assertTrue(target.is_file())
        self.assertEqual(sorted(info["receipt"]), ["changed", "rebased_from", "request_id", "revision",
                                                   "warnings"])
        self.assertEqual(info["receipt"]["revision"], 1)
        self.assertIsNone(info["receipt"]["rebased_from"])
        self.assertEqual(info["receipt"]["warnings"], [])
        self.assertEqual(info["receipt"]["changed"],
                         [{"collection": "papers", "id": info["paper_id"], "version": 1, "op": "create"}])

    def test_a_fresh_database_records_this_core_s_format_contract_and_features(self):
        """Initialization requires the default features, not unused optional capabilities."""
        info = storage.initialize(self.work / "fresh.db", source_root=self.source_dir(), title="Fresh paper")
        self.assertEqual(info["revision"], 1)
        with storage.Database(self.work / "fresh.db") as db:
            self.assertEqual(sorted(db.metadata), METADATA_KEYS)
            self.assertEqual(db.metadata["storage_format"], "4")
            self.assertEqual(db.metadata["contract_version"], "4")
            self.assertEqual(db.metadata["protocol_version"], "coherent-proof-audit/1")
            self.assertEqual(db.metadata["packet_version"], "2")
            self.assertEqual(db.metadata["projection_version"], "2")
            self.assertEqual(db.metadata["core_version"], CORE_VERSION)
            features = json.loads(db.metadata["features"])
            self.assertEqual(features, list(DEFAULT_FEATURES))
            self.assertEqual(features[0], "records/3")
            self.assertIn("independent-review/1", features)
            self.assertRegex(db.metadata["created_at"], TIMESTAMP)
        # the literals above are the on-disk format; they must keep agreeing with the constants the core ships
        self.assertEqual((STORAGE_FORMAT, CONTRACT_VERSION, PACKET_VERSION, PROJECTION_VERSION), (4, 4, 2, 2))
        self.assertEqual(PROTOCOL_VERSION, "coherent-proof-audit/1")

    def test_the_only_record_is_the_paper_with_the_resolved_source_root(self):
        """The single seeded head is the paper, holding the title and the source root as a resolved POSIX path."""
        root = self.source_dir()
        info = storage.initialize(self.work / "fresh.db", source_root=root, title="Fresh paper")
        with storage.Database(self.work / "fresh.db") as db:
            heads = db.heads()
            self.assertEqual([(r.collection, r.id, r.version) for r in heads],
                             [("papers", info["paper_id"], 1)])
            paper = heads[0]
            self.assertFalse(paper.retired)
            self.assertEqual(paper.revision, 1)
            self.assertEqual(paper.body, {"title": "Fresh paper", "source_root": root.resolve().as_posix(),
                                          "main_items": [], "report_paths": []})
            self.assertEqual(paper.ref, {"collection": "papers", "id": info["paper_id"]})
            self.assertEqual(paper.pinned, {"collection": "papers", "id": info["paper_id"], "version": 1})
            self.assertEqual(paper.key, ("papers", info["paper_id"]))

    def test_the_root_commit_has_no_parent_no_base_and_stores_the_receipt(self):
        """Revision 1 is the root commit: parent and base are NULL and the stored receipt is the returned one."""
        root = self.source_dir()
        info = storage.initialize(self.work / "fresh.db", source_root=root, title="Fresh paper")
        with storage.Database(self.work / "fresh.db") as db:
            row = db.commit_row(1)
            self.assertIsNone(row["parent_revision"])
            self.assertIsNone(row["base_revision"])
            self.assertEqual(row["request_digest"], digest({"command": "init", "title": "Fresh paper",
                                                            "source_root": root.resolve().as_posix()}))
            self.assertRegex(row["created_at"], TIMESTAMP)
            self.assertEqual(json.loads(row["receipt_json"]), info["receipt"])
            self.assertEqual(row["request_id"], info["receipt"]["request_id"])
            self.assertEqual(db.commit_by_request(row["request_id"]), row)
            self.assertIsNone(db.commit_row(2))
            self.assertIsNone(db.commit_by_request("req_never_used"))

    def test_the_paper_version_carries_the_full_facet_and_no_references(self):
        """A new paper indexes one 'full' facet digest of its body and contributes no reference rows."""
        info = storage.initialize(self.work / "fresh.db", source_root=self.source_dir(), title="Fresh paper")
        with storage.Database(self.work / "fresh.db") as db:
            paper = storage.paper_record(db)
            self.assertEqual(db.facets("papers", info["paper_id"], 1), {"full": digest(paper.body)})
            self.assertEqual(db.refs_from("papers", info["paper_id"], 1), [])
            self.assertEqual(db.live_referrers("papers", info["paper_id"]), [])
            self.assertEqual(db.blob_hashes(), [])
            self.assertEqual(db.publications(), [])

    def test_initialize_refuses_to_overwrite_an_existing_file(self):
        """An occupied path raises InvalidRequest and the existing bytes are left untouched."""
        target = self.path("occupied.db")
        target.write_bytes(b"precious bytes")
        with self.assertRaises(InvalidRequest) as caught:
            storage.initialize(target, source_root=self.source_dir(), title="Fresh paper")
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("refusing to overwrite", str(caught.exception))
        self.assertEqual(target.read_bytes(), b"precious bytes")

    def test_initialize_rejects_a_blank_title_and_leaves_no_file(self):
        """A whitespace-only title raises InvalidRequest before any file is created."""
        target = self.work / "blank.db"
        with self.assertRaises(InvalidRequest) as caught:
            storage.initialize(target, source_root=self.source_dir(), title="   ")
        self.assertIn("title must be nonempty text", str(caught.exception))
        self.assertFalse(target.exists())

    def test_initialize_rejects_a_source_root_that_is_not_a_directory(self):
        """A missing source root raises SOURCE_UNAVAILABLE and leaves no database behind."""
        target = self.work / "nosrc.db"
        with self.assertRaises(SourceUnavailable) as caught:
            storage.initialize(target, source_root=self.work / "absent", title="Fresh paper")
        self.assertEqual(caught.exception.code, "SOURCE_UNAVAILABLE")
        self.assertIn("source root is not a directory", str(caught.exception))
        self.assertFalse(target.exists())


# -- opening ----------------------------------------------------------------------------------------
class OpenTests(StorageCase):
    def test_database_opens_read_only_by_default(self):
        """storage.Database(path) defaults to write=False and SQLite refuses writes on that connection."""
        fixture = self.structured()
        with storage.Database(fixture.path) as db:
            self.assertFalse(db.write)
            with self.assertRaises(sqlite3.OperationalError) as caught:
                db.put_blob(b"not allowed")
            self.assertIn("readonly", str(caught.exception))
            self.assertNotIn(support.sha(b"not allowed"), db.blob_hashes())

    def test_a_read_only_connection_refuses_metadata_writes_too(self):
        """The read-only guard covers every write path, not just blobs, and the stored value never moves."""
        fixture = self.structured()
        with storage.Database(fixture.path, write=False) as db:
            db.begin_immediate()
            with self.assertRaises(sqlite3.OperationalError) as caught:
                db.set_metadata("core_version", "9.9.9")
            self.assertIn("readonly", str(caught.exception))
            db.rollback()
        with fixture.open(write=False) as db:
            self.assertEqual(db.metadata["core_version"], CORE_VERSION)
            self.assertNotIn("9.9.9", db.metadata.values())

    def test_a_read_only_connection_still_reads_every_committed_record(self):
        """Read-only opening is a write restriction only: every structured head is visible and ordered."""
        fixture = self.structured()
        with storage.Database(fixture.path, write=False) as db:
            self.assertEqual([(r.collection, r.id, r.version) for r in db.heads()], structure_heads(fixture))
            self.assertEqual([r.id for r in db.heads("items")], ["itm_lem", "itm_thm"])

    def test_a_write_connection_commits_data_a_later_reader_sees(self):
        """A blob committed through write=True is readable byte-for-byte from a separate read-only open."""
        fixture = self.structured()
        with fixture.open() as db:
            self.assertTrue(db.write)
            before = db.blob_hashes()
            db.begin_immediate()
            sha = db.put_blob(b"committed payload")
            db.commit()
        with fixture.open(write=False) as db:
            self.assertEqual(db.get_blob(sha), b"committed payload")
            self.assertEqual(db.blob_hashes(), sorted(before + [sha]))

    def test_the_acceptance_path_refuses_a_read_only_database(self):
        """apply_batch on a read-only Database raises InvalidRequest and adds no revision."""
        fixture = self.structured()
        with fixture.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="author")
            head = db.head("items", "itm_lem")
            before = db.max_revision()
        with storage.Database(fixture.path, write=False) as db:
            with self.assertRaises(InvalidRequest) as caught:
                acceptance.apply_batch(db, {
                    "contract_version": 3, "request_id": "req_read_only", "packet_id": packet["packet_id"],
                    "edits": [edit("replace", "items", "itm_lem", dict(head.body, caption="nope"),
                                   expected=head.version)]})
            self.assertIn("read-only", str(caught.exception))
            self.assertEqual(db.max_revision(), before)
            self.assertIsNone(db.commit_by_request("req_read_only"))
            self.assertEqual(db.head("items", "itm_lem").body, head.body)

    def test_opening_a_missing_path_raises_invalid_request(self):
        """A path with no file raises InvalidRequest rather than creating a database."""
        missing = self.work / "absent.db"
        with self.assertRaises(InvalidRequest) as caught:
            storage.Database(missing)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("database not found", str(caught.exception))
        self.assertFalse(missing.exists())

    def test_opening_a_directory_raises_invalid_request(self):
        """A directory is not a file, so it is rejected by the same not-found guard."""
        folder = self.path("adirectory")
        folder.mkdir()
        with self.assertRaises(InvalidRequest) as caught:
            storage.Database(folder)
        self.assertIn("database not found", str(caught.exception))

    def test_opening_a_file_that_is_not_a_database_raises_incompatible(self):
        """Bytes that are not SQLite fail the compatibility probe with INCOMPATIBLE, not a raw sqlite3 error."""
        junk = self.path("junk.db")
        junk.write_bytes(b"this is not a database at all")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(junk)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE")
        self.assertIn("is not a proofcheck database", str(caught.exception))

    def test_opening_a_sqlite_file_without_a_metadata_table_raises_incompatible(self):
        """A perfectly valid SQLite file that is some other application's is refused by name, not by crash."""
        stranger = self.path("stranger.db")
        raw = sqlite3.connect(str(stranger))
        try:
            raw.execute("CREATE TABLE notes (body TEXT)")
            raw.commit()
        finally:
            raw.close()
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(stranger)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE")
        self.assertIn("is not a proofcheck database", str(caught.exception))
        self.assertIn("no such table: metadata", str(caught.exception))


# -- compatibility ----------------------------------------------------------------------------------
class CompatibilityTests(StorageCase):
    def test_check_compatibility_accepts_current_storage_format_and_returns_the_metadata_table(self):
        """A current-format database opens and check_compatibility returns every metadata row it finds."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            rows = {row["key"]: row["value"] for row in db.conn.execute("SELECT key, value FROM metadata")}
            self.assertEqual(sorted(rows), METADATA_KEYS)
            self.assertEqual(db.check_compatibility(), rows)
            self.assertEqual(db.metadata, rows)
            self.assertEqual(db.metadata["storage_format"], "4")
            self.assertEqual(db.metadata["contract_version"], "4")

    def test_check_compatibility_re_reads_while_the_open_time_mapping_stays_frozen(self):
        """db.metadata is the snapshot taken at open; check_compatibility goes back to the table."""
        fixture = self.structured()
        with fixture.open() as db:
            db.begin_immediate()
            db.set_metadata("last_export", "2026-09-14")
            db.commit()
            self.assertNotIn("last_export", db.metadata)
            self.assertEqual(db.check_compatibility()["last_export"], "2026-09-14")
            self.assertEqual(sorted(db.check_compatibility()), sorted(METADATA_KEYS + ["last_export"]))

    def test_a_future_storage_format_is_rejected_and_names_the_readable_formats(self):
        """Recording storage_format 4 makes the open fail with INCOMPATIBLE naming the formats this core reads."""
        fixture = self.structured()
        broken = self.broken_copy(fixture, "storage_format", "5", "future_format")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(broken)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE")
        self.assertIn("unsupported storage_format '5'", str(caught.exception))
        self.assertIn("this core reads [2, 3, 4]", str(caught.exception))

    def test_an_older_storage_format_is_rejected_as_well(self):
        """Formats 2 and 3 are readable, so format 1 is refused rather than silently upgraded."""
        fixture = self.structured()
        broken = self.broken_copy(fixture, "storage_format", "1", "old_format")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(broken)
        self.assertIn("unsupported storage_format '1'", str(caught.exception))

    def test_a_non_numeric_storage_format_is_rejected(self):
        """storage_format is compared as digits, so a non-numeric value is refused rather than coerced."""
        fixture = self.structured()
        broken = self.broken_copy(fixture, "storage_format", "2.0", "odd_format")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(broken)
        self.assertIn("unsupported storage_format '2.0'", str(caught.exception))

    def test_a_database_with_no_storage_format_entry_is_rejected(self):
        """A metadata table that never records the format is refused; the message reports the absent value."""
        fixture = self.structured()
        broken = self.stripped_copy(fixture, "storage_format", "no_format")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(broken)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE")
        self.assertIn("unsupported storage_format None", str(caught.exception))

    def test_a_future_contract_version_is_rejected(self):
        """A contract_version other than this core's raises INCOMPATIBLE naming the required version."""
        fixture = self.structured()
        broken = self.broken_copy(fixture, "contract_version", str(CONTRACT_VERSION + 1), "future_contract")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(broken)
        self.assertIn(f"unsupported contract_version '{CONTRACT_VERSION + 1}'", str(caught.exception))
        self.assertIn(f"requires {CONTRACT_VERSION}", str(caught.exception))

    def test_a_required_feature_this_core_lacks_is_rejected_by_name(self):
        """A feature outside SUPPORTED_FEATURES blocks the open and the message names the missing feature."""
        fixture = self.structured()
        features = json.dumps(list(SUPPORTED_FEATURES) + ["time-travel/9"])
        broken = self.broken_copy(fixture, "features", features, "extra_feature")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(broken)
        self.assertIn("unsupported features ['time-travel/9']", str(caught.exception))

    def test_a_features_entry_that_is_not_a_json_list_is_rejected(self):
        """Unparseable or non-list features metadata is a compatibility failure, not a silent empty list."""
        fixture = self.structured()
        for value, name in (("not json at all", "features_garbage"), ('{"records/3": true}', "features_object")):
            broken = self.broken_copy(fixture, "features", value, name)
            with self.assertRaises(IncompatibleError) as caught:
                storage.Database(broken)
            self.assertIn("features entry is not a JSON list", str(caught.exception))

    def test_a_database_that_records_no_features_still_opens(self):
        """No features entry means the database requires nothing beyond the contract, so it stays readable."""
        fixture = self.structured()
        plain = self.stripped_copy(fixture, "features", "no_features")
        with storage.Database(plain) as db:
            self.assertNotIn("features", db.metadata)
            self.assertEqual([r.id for r in db.heads("items")], ["itm_lem", "itm_thm"])

    def test_a_legacy_overview_database_is_rejected_with_the_migration_hint(self):
        """The legacy overview format is named explicitly, points at migrate-overview, and reports its markers."""
        fixture = self.structured()
        broken = self.broken_copy(fixture, "format", LEGACY_OVERVIEW_FORMAT, "legacy_overview")
        with self.assertRaises(IncompatibleError) as caught:
            storage.Database(broken)
        self.assertIn(LEGACY_OVERVIEW_FORMAT, str(caught.exception))
        self.assertIn("migrate-overview", str(caught.exception))
        self.assertEqual(caught.exception.records, [{"format": LEGACY_OVERVIEW_FORMAT, "schema_version": None}])

    def test_breaking_a_copy_leaves_the_original_database_openable(self):
        """The tampering used by these tests is confined to the copy; the source database still opens fully."""
        fixture = self.structured()
        self.broken_copy(fixture, "storage_format", "4", "isolated")
        self.stripped_copy(fixture, "storage_format", "isolated_stripped")
        with fixture.open(write=False) as db:
            self.assertEqual(db.metadata["storage_format"], "4")
            self.assertEqual([(r.collection, r.id, r.version) for r in db.heads()], structure_heads(fixture))


# -- history ----------------------------------------------------------------------------------------
class HistoryTests(StorageCase):
    def history(self):
        """Structured fixture plus two further versions of items:itm_lem; returns (fixture, revisions)."""
        fixture = self.structured()
        with fixture.open() as db:
            base = db.max_revision()
            second = bump_caption(fixture, db, "Lemma 1 v2")
            third = bump_caption(fixture, db, "Lemma 1 v3")
        return fixture, (base, second, third)

    def test_max_revision_advances_by_exactly_one_per_commit(self):
        """Each accepted batch allocates the next revision and every revision has a commit row."""
        fixture, (base, second, third) = self.history()
        self.assertEqual((base, second, third), (4, 5, 6))
        with fixture.open(write=False) as db:
            self.assertEqual(db.max_revision(), third)
            for revision in range(1, third + 1):
                row = db.commit_row(revision)
                self.assertIsNotNone(row, f"revision {revision} has no commit row")
                self.assertEqual(row["parent_revision"], None if revision == 1 else revision - 1)
            self.assertIsNone(db.commit_row(third + 1))

    def test_head_returns_the_newest_version_and_none_for_an_unknown_record(self):
        """head() follows record_heads to the latest version; an unknown id is None, not an error."""
        fixture, (_, _, third) = self.history()
        with fixture.open(write=False) as db:
            head = db.head("items", "itm_lem")
            self.assertEqual((head.version, head.revision, head.body["caption"]), (3, third, "Lemma 1 v3"))
            self.assertFalse(head.retired)
            self.assertIsNone(db.head("items", "itm_absent"))
            self.assertIsNone(db.head("findings", "fnd_absent"))

    def test_version_returns_the_exact_historical_body(self):
        """Every superseded version stays readable by number; a version that was never written is None."""
        fixture, (base, second, _) = self.history()
        with fixture.open(write=False) as db:
            first = db.version("items", "itm_lem", 1)
            self.assertEqual((first.version, first.revision, first.body["caption"]), (1, base, "Lemma 1"))
            self.assertEqual(db.version("items", "itm_lem", 2).body["caption"], "Lemma 1 v2")
            self.assertEqual(db.version("items", "itm_lem", 2).revision, second)
            self.assertIsNone(db.version("items", "itm_lem", 4))
            self.assertIsNone(db.version("items", "itm_lem", 0))

    def test_latest_at_resolves_the_version_live_at_a_given_revision(self):
        """latest_at walks back to the newest version at or before a revision, and is None before creation."""
        fixture, (base, second, third) = self.history()
        with fixture.open(write=False) as db:
            self.assertIsNone(db.latest_at("items", "itm_lem", 0))
            self.assertIsNone(db.latest_at("items", "itm_lem", base - 1))
            self.assertEqual(db.latest_at("items", "itm_lem", base).version, 1)
            self.assertEqual(db.latest_at("items", "itm_lem", base).body["caption"], "Lemma 1")
            self.assertEqual(db.latest_at("items", "itm_lem", second).version, 2)
            self.assertEqual(db.latest_at("items", "itm_lem", second).body["caption"], "Lemma 1 v2")
            self.assertEqual(db.latest_at("items", "itm_lem", third).version, 3)
            self.assertEqual(db.latest_at("items", "itm_lem", third + 100).version, 3)
            self.assertIsNone(db.latest_at("items", "itm_absent", third))

    def test_heads_filters_by_collection_and_orders_by_collection_then_id(self):
        """heads() returns one row per live record, sorted by collection then id, filterable per collection."""
        fixture, _ = self.history()
        with fixture.open(write=False) as db:
            self.assertEqual([(r.collection, r.id) for r in db.heads()],
                             [(collection, id) for collection, id, _ in structure_heads(fixture)])
            self.assertEqual([(r.collection, r.id) for r in db.heads("anchors")],
                             [("anchors", "anc_lem"), ("anchors", "anc_lem_proof"),
                              ("anchors", "anc_thm"), ("anchors", "anc_thm_proof")])
            self.assertEqual(db.heads("findings"), [])
            self.assertEqual([r.version for r in db.heads("items")], [3, 1])

    def test_records_at_reconstructs_the_snapshot_of_an_earlier_revision(self):
        """records_at pins every record to the version live at that revision; revision 0 is the empty snapshot."""
        fixture, (base, second, third) = self.history()
        with fixture.open(write=False) as db:
            self.assertEqual(db.records_at(0), [])
            self.assertEqual([(r.collection, r.id, r.version) for r in db.records_at(1)],
                             [("papers", fixture.paper_id, 1)])
            self.assertEqual([(r.collection, r.id, r.version) for r in db.records_at(base)],
                             structure_heads(fixture))
            self.assertEqual({(r.collection, r.id): r.version for r in db.records_at(second)}[("items", "itm_lem")], 2)
            self.assertEqual([r.id for r in db.records_at(third, "items")], ["itm_lem", "itm_thm"])
            self.assertEqual([(r.collection, r.id, r.version) for r in db.records_at(third + 50)],
                             [(r.collection, r.id, r.version) for r in db.heads()])

    def test_versions_since_is_exclusive_and_supports_limit_and_offset(self):
        """versions_since(n) yields only versions from revisions strictly after n, in revision order, paged."""
        fixture, (base, second, third) = self.history()
        log = structure_log(fixture) + [(second, "items", "itm_lem", 2), (third, "items", "itm_lem", 3)]
        with fixture.open(write=False) as db:
            self.assertEqual([(r.revision, r.collection, r.id, r.version) for r in
                              db.versions_since(0, limit=100, offset=0)], log)
            self.assertEqual([(r.revision, r.collection, r.id, r.version) for r in
                              db.versions_since(2, limit=100, offset=0)], log[2:])
            self.assertEqual([(r.collection, r.id, r.version, r.revision) for r in
                              db.versions_since(base, limit=100, offset=0)],
                             [("items", "itm_lem", 2, second), ("items", "itm_lem", 3, third)])
            self.assertEqual([r.version for r in db.versions_since(base, limit=1, offset=0)], [2])
            self.assertEqual([r.version for r in db.versions_since(base, limit=100, offset=1)], [3])
            self.assertEqual(db.versions_since(base, limit=100, offset=5), [])
            self.assertEqual(db.versions_since(third, limit=100, offset=0), [])
            self.assertEqual(db.versions_since(third + 1000, limit=100, offset=0), [])

    def test_count_versions_since_matches_the_rows_versions_since_returns(self):
        """The count used for paging agrees with the listing at every boundary, including out-of-range."""
        fixture, (base, _, third) = self.history()
        with fixture.open(write=False) as db:
            for revision in (0, 1, base, third, third + 1000):
                self.assertEqual(db.count_versions_since(revision),
                                 len(db.versions_since(revision, limit=1000, offset=0)),
                                 f"mismatch at revision {revision}")
            self.assertEqual(db.count_versions_since(0), len(db.all_versions()))
            self.assertEqual(db.count_versions_since(0), 17)
            self.assertEqual(db.count_versions_since(1), 16)
            self.assertEqual(db.count_versions_since(base), 2)
            self.assertEqual(db.count_versions_since(third), 0)
            self.assertEqual(db.count_versions_since(third + 1000), 0)

    def test_versions_of_lists_every_version_of_one_record_in_order(self):
        """versions_of returns the record's whole history ascending; an unknown record yields an empty list."""
        fixture, (base, second, third) = self.history()
        with fixture.open(write=False) as db:
            history = db.versions_of("items", "itm_lem")
            self.assertEqual([(r.version, r.revision) for r in history],
                             [(1, base), (2, second), (3, third)])
            self.assertEqual([r.body["caption"] for r in history], ["Lemma 1", "Lemma 1 v2", "Lemma 1 v3"])
            self.assertEqual([r.version for r in db.versions_of("items", "itm_thm")], [1])
            self.assertEqual(db.versions_of("items", "itm_absent"), [])

    def test_all_versions_is_the_whole_log_in_revision_then_collection_then_id_order(self):
        """all_versions replays every version ever written, in write order, one row per version."""
        fixture, (_, second, third) = self.history()
        with fixture.open(write=False) as db:
            rows = db.all_versions()
            self.assertEqual([(r.revision, r.collection, r.id, r.version) for r in rows],
                             structure_log(fixture) + [(second, "items", "itm_lem", 2),
                                                       (third, "items", "itm_lem", 3)])
            self.assertEqual(len(rows), len(db.heads()) + 2)
            self.assertTrue(all(row.body is not None for row in rows))


# -- references -------------------------------------------------------------------------------------
class ReferenceTests(StorageCase):
    def retired_fixture(self):
        """Structured fixture with a spare item, a spare use pointing at it, and that use retired."""
        fixture = self.structured()
        with fixture.open() as db:
            fixture.apply(db, [spare_item("itm_spare", "Spare")])
            fixture.apply(db, [spare_use("use_spare", "itm_spare", "itm_lem")])
            live = db.max_revision()
            head = db.head("uses", "use_spare")
            fixture.apply(db, [retire("uses", "use_spare", head.version, "superseded")])
            return fixture, live, db.max_revision()

    def test_refs_from_records_every_reference_field_of_a_version(self):
        """A use's reference rows name each pointing field by body-relative JSON Pointer and its target."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            self.assertEqual(db.refs_from("uses", "use_lem_thm", 1), [
                {"field_path": "/evidence_refs/0", "target_collection": "anchors",
                 "target_id": "anc_thm_proof", "target_version": None},
                {"field_path": "/from", "target_collection": "items", "target_id": "itm_lem",
                 "target_version": None},
                {"field_path": "/to", "target_collection": "items", "target_id": "itm_thm",
                 "target_version": None}])
            self.assertEqual([row["field_path"] for row in db.refs_from("items", "itm_thm", 1)],
                             ["/passages/0/anchor_id", "/passages/1/anchor_id"])
            self.assertEqual([row["field_path"] for row in db.refs_from("arguments", "arg_lem", 1)],
                             ["/evidence_refs/0", "/final_group_id", "/scope_id", "/target"])

    def test_an_anchor_reference_pins_the_source_version_while_body_links_stay_unpinned(self):
        """Anchors record the exact source version they were cut from; ordinary body links carry no version."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            self.assertEqual(db.refs_from("anchors", "anc_lem", 1),
                             [{"field_path": "/source_id", "target_collection": "sources",
                               "target_id": fixture.source_id, "target_version": 1}])
            self.assertEqual([row["target_version"] for row in db.refs_from("items", "itm_lem", 1)],
                             [None, None])
            self.assertEqual(db.live_referrers("sources", fixture.source_id),
                             [{"owner_collection": "anchors", "owner_id": anchor, "owner_version": 1,
                               "field_path": "/source_id", "target_version": 1}
                              for anchor in ("anc_lem", "anc_lem_proof", "anc_thm", "anc_thm_proof")])

    def test_refs_from_is_empty_for_a_version_that_holds_no_references(self):
        """A body with no links contributes no rows, and neither does a version that was never written."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            self.assertEqual(db.refs_from("scopes", "scp_plain", 1), [])
            self.assertEqual(db.refs_from("uses", "use_lem_thm", 7), [])
            self.assertEqual(db.refs_from("uses", "use_absent", 1), [])

    def test_live_referrers_reports_every_live_head_pointing_at_a_record(self):
        """The lemma is referenced by its argument, its group and the dependency edge, each with its field."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            self.assertEqual(db.live_referrers("items", "itm_lem"), [
                {"owner_collection": "arguments", "owner_id": "arg_lem", "owner_version": 1,
                 "field_path": "/target", "target_version": None},
                {"owner_collection": "groups", "owner_id": "grp_lem", "owner_version": 1,
                 "field_path": "/conclusion", "target_version": None},
                {"owner_collection": "uses", "owner_id": "use_lem_thm", "owner_version": 1,
                 "field_path": "/from", "target_version": None}])
            self.assertEqual(db.live_referrers("anchors", "anc_lem"),
                             [{"owner_collection": "items", "owner_id": "itm_lem", "owner_version": 1,
                               "field_path": "/passages/0/anchor_id", "target_version": None}])
            self.assertEqual(db.live_referrers("items", "itm_absent"), [])

    def test_live_referrers_follows_the_head_when_a_record_gains_a_version(self):
        """A referrer is reported at its head version only, so superseded versions stop appearing."""
        fixture = self.structured()
        with fixture.open() as db:
            head = db.head("uses", "use_lem_thm")
            fixture.apply(db, [edit("replace", "uses", "use_lem_thm", dict(head.body, reason="restated"),
                                    expected=head.version)], "items:itm_thm")
            referrers = db.live_referrers("items", "itm_lem")
            self.assertEqual([(r["owner_id"], r["owner_version"]) for r in referrers],
                             [("arg_lem", 1), ("grp_lem", 1), ("use_lem_thm", 2)])
            self.assertEqual([row["field_path"] for row in db.refs_from("uses", "use_lem_thm", 1)],
                             ["/evidence_refs/0", "/from", "/to"])
            self.assertIn("/group_id", [row["field_path"] for row in db.refs_from("application_details", "use_lem_thm", 1)])

    def test_live_referrers_drops_a_referrer_once_it_is_retired(self):
        """Retiring the edge removes it from the target's live referrers even though its rows stay in history."""
        fixture, live, _ = self.retired_fixture()
        with fixture.open(write=False) as db:
            self.assertEqual(db.live_referrers("items", "itm_spare"), [])
            self.assertEqual([row["field_path"] for row in db.refs_from("uses", "use_spare", 1)],
                             ["/from", "/to"])
            self.assertEqual(db.refs_from("uses", "use_spare", 2), [])
            self.assertEqual(db.max_revision(), live + 1)
            self.assertEqual([r["owner_id"] for r in db.live_referrers("items", "itm_lem")],
                             ["arg_lem", "grp_lem", "use_lem_thm"])

    def test_retiring_a_record_appends_a_tombstone_version_and_keeps_history(self):
        """Retirement appends version 2 with a null body and the digest of null; version 1 stays intact."""
        fixture, _, retired_at = self.retired_fixture()
        with fixture.open(write=False) as db:
            head = db.head("uses", "use_spare")
            self.assertEqual((head.version, head.revision), (2, retired_at))
            self.assertTrue(head.retired)
            self.assertIsNone(head.body)
            history = db.versions_of("uses", "use_spare")
            self.assertEqual([(r.version, r.retired) for r in history], [(1, False), (2, True)])
            self.assertEqual(history[0].body["reason"], "spare edge")
            self.assertEqual(db.facets("uses", "use_spare", 2), {})
            row = db.conn.execute("SELECT body_digest FROM record_versions WHERE collection = 'uses' "
                                  "AND id = 'use_spare' AND version = 2").fetchone()
            self.assertEqual(row["body_digest"], digest(None))

    def test_heads_hides_retired_records_unless_they_are_requested(self):
        """heads() and records_at() are live-only by default and expose tombstones with include_retired."""
        fixture, _, retired_at = self.retired_fixture()
        with fixture.open(write=False) as db:
            self.assertEqual([r.id for r in db.heads("uses")], ["use_lem_thm"])
            self.assertEqual([(r.id, r.retired) for r in db.heads("uses", include_retired=True)],
                             [("use_lem_thm", False), ("use_spare", True)])
            self.assertEqual([r.id for r in db.records_at(retired_at, "uses")], ["use_lem_thm"])
            self.assertEqual([r.id for r in db.records_at(retired_at, "uses", include_retired=True)],
                             ["use_lem_thm", "use_spare"])

    def test_records_at_before_the_retirement_still_shows_the_record_live(self):
        """A snapshot taken before the tombstone sees the edge with its original body."""
        fixture, live, _ = self.retired_fixture()
        with fixture.open(write=False) as db:
            snapshot = {r.id: r for r in db.records_at(live, "uses")}
            self.assertEqual(sorted(snapshot), ["use_lem_thm", "use_spare"])
            self.assertFalse(snapshot["use_spare"].retired)
            self.assertEqual(snapshot["use_spare"].version, 1)
            self.assertEqual(snapshot["use_spare"].body["reason"], "spare edge")


# -- facets, bindings, packets, publications, blobs ---------------------------------------------------
class IndexTests(StorageCase):
    def test_facets_expose_the_per_facet_digests_of_a_version(self):
        """Each collection indexes its own facets and 'full' is always the canonical digest of the body."""
        fixture = self.structured()
        # collection -> (id, every facet name it indexes, one facet that must be narrower than 'full')
        expected = [("items", "itm_lem", ["full", "proof", "statement"], "statement"),
                    ("arguments", "arg_lem", ["full", "proof"], "proof"),
                    ("groups", "grp_lem", ["full", "inference"], "inference"),
                    ("uses", "use_lem_thm", ["application", "full"], "application")]
        with fixture.open(write=False) as db:
            for collection, id, names, narrow in expected:
                head = db.head(collection, id)
                facets = db.facets(collection, id, head.version)
                self.assertEqual(sorted(facets), names, collection)
                self.assertEqual(facets["full"], digest(head.body), collection)
                self.assertEqual(sorted({len(value) for value in facets.values()}), [64], collection)
                # a narrow facet covers part of the body, so its digest cannot be the whole-body digest
                self.assertNotEqual(facets[narrow], facets["full"], f"{collection}/{narrow}")
                self.assertNotEqual(facets[narrow], digest(head.body), f"{collection}/{narrow}")
            item_facets = db.facets("items", "itm_lem", 1)
            self.assertNotEqual(item_facets["statement"], item_facets["proof"])

    def test_facets_are_empty_for_a_version_that_was_never_written(self):
        """A facet lookup for an unknown version or record returns an empty mapping, not an error."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            self.assertEqual(db.facets("items", "itm_lem", 9), {})
            self.assertEqual(db.facets("items", "itm_absent", 1), {})

    def test_facets_change_only_where_the_body_changed(self):
        """Editing the caption changes the full digest while the statement facet digest stays put."""
        fixture = self.structured()
        with fixture.open() as db:
            before = db.facets("items", "itm_lem", 1)
            bump_caption(fixture, db, "Lemma 1 restated")
            after = db.facets("items", "itm_lem", 2)
            self.assertEqual(sorted(after), sorted(before))
            self.assertNotEqual(after["full"], before["full"])
            self.assertEqual(after["statement"], before["statement"])
            self.assertEqual(after["proof"], before["proof"])

    def test_packet_round_trips_its_manifest_payload_and_base_revision(self):
        """A packet issued by packets.get_packet is readable back with its manifest and its payload blob."""
        fixture = self.structured()
        with fixture.open() as db:
            issued = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            row = db.packet(issued["packet_id"])
            self.assertEqual(sorted(row), ["base_revision", "created_at", "manifest", "mode", "packet_id",
                                           "packet_version", "payload_sha256"])
            self.assertEqual(row["packet_id"], issued["packet_id"])
            self.assertEqual(row["packet_version"], PACKET_VERSION)
            self.assertEqual(row["mode"], "primary")
            self.assertEqual(row["base_revision"], db.max_revision())
            self.assertRegex(row["created_at"], TIMESTAMP)
            self.assertEqual(row["manifest"]["mode"], "primary")
            self.assertEqual(row["manifest"]["targets"], [{"collection": "items", "id": "itm_lem"}])
            self.assertEqual(row["manifest"]["base_revision"], row["base_revision"])
            self.assertTrue(db.has_blob(row["payload_sha256"]))
            self.assertEqual(support.sha(db.get_blob(row["payload_sha256"])), row["payload_sha256"])

    def test_packet_is_none_for_an_unknown_identifier(self):
        """An unknown packet id reads as None so callers can raise PACKET_UNKNOWN themselves."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            self.assertIsNone(db.packet("pkt_never_issued"))

    def test_binding_pins_the_packet_and_evidence_digests_of_a_check(self):
        """A primary check stores its packet id and evidence pinned to versions whose facet digests still match."""
        fixture = self.coherent_fixture().primary()
        with fixture.open(write=False) as db:
            binding = db.binding("checks", "chk_comp_lem", 1)
            self.assertEqual(sorted(binding), ["bindings", "packet_id"])
            self.assertEqual(binding["packet_id"], binding["bindings"]["packet_id"])
            self.assertIsNotNone(db.packet(binding["packet_id"]))
            records = binding["bindings"]["records"]
            self.assertTrue(records)
            for entry in records:
                ref = entry["ref"]
                self.assertEqual(db.facets(ref["collection"], ref["id"], ref["version"])[entry["facet"]],
                                 entry["digest"], entry)
            # Coherent examinations pin the consumed proof passage itself.
            self.assertIn(("anchors", "anc_lem_proof", "proof"),
                          {(e["ref"]["collection"], e["ref"]["id"], e["facet"]) for e in records})

    def test_binding_is_absent_for_unbound_collections_and_unknown_versions(self):
        """Only bound collections carry evidence bindings; everything else reads None."""
        fixture = self.coherent_fixture().primary()
        with fixture.open(write=False) as db:
            self.assertIsNone(db.binding("items", "itm_lem", 1))
            self.assertIsNone(db.binding("arguments", "arg_lem", 1))
            self.assertIsNone(db.binding("checks", "chk_comp_lem", 9))
            self.assertIsNotNone(db.binding("observations", "obs_lem", 1))

    def test_publications_read_back_whole_and_filter_by_revision(self):
        """Recorded publications keep their kind, state, artifact hash and receipt, and list per revision."""
        fixture = self.structured()
        with fixture.open() as db:
            revision = db.max_revision()
            db.begin_immediate()
            artifact = db.put_blob(b"<html>report</html>")
            db.insert_publication("pub_working", revision, "working", "published", "reports/audit.html",
                                  artifact, {"kind": "working"})
            db.insert_publication("pub_failed", revision, "release", "failed", "reports/audit.html",
                                  None, {"kind": "release"})
            db.commit()
            rows = db.publications()
            self.assertEqual(sorted(r["id"] for r in rows), ["pub_failed", "pub_working"])
            working = next(r for r in rows if r["id"] == "pub_working")
            self.assertEqual(working["kind"], "working")
            self.assertEqual(working["state"], "published")
            self.assertEqual(working["revision"], revision)
            self.assertEqual(working["output_path"], "reports/audit.html")
            self.assertEqual(working["artifact_sha256"], artifact)
            self.assertEqual(json.loads(working["receipt_json"]), {"kind": "working"})
            self.assertRegex(working["created_at"], TIMESTAMP)
            self.assertIsNone(next(r for r in rows if r["id"] == "pub_failed")["artifact_sha256"])
            self.assertEqual(sorted(r["id"] for r in db.publications(revision=revision)),
                             ["pub_failed", "pub_working"])
            self.assertEqual(db.publications(revision=1), [])
            self.assertEqual(db.publications(revision=revision + 99), [])

    def test_publications_are_ordered_by_creation_time_then_id(self):
        """Listing order is created_at first and id only as the tie-break, never insertion order.

        insert_publication stamps created_at from the clock, so two inserts may or may not share a
        millisecond. To make the ordering observable rather than a race, the timestamps are restated
        afterwards to fixed values: publications carry no immutability trigger, unlike record versions.
        """
        fixture = self.structured()
        stamps = {"pub_a": "2026-01-01T00:00:00.300Z", "pub_b": "2026-01-01T00:00:00.100Z",
                  "pub_c": "2026-01-01T00:00:00.100Z", "pub_d": "2026-01-01T00:00:00.200Z"}
        with fixture.open() as db:
            revision = db.max_revision()
            db.begin_immediate()
            for id in ("pub_a", "pub_b", "pub_c", "pub_d"):
                db.insert_publication(id, revision, "working", "built", f"{id}.html", None, {"id": id})
            for id, created_at in stamps.items():
                db.conn.execute("UPDATE publications SET created_at = ? WHERE id = ?", (created_at, id))
            db.commit()
            rows = db.publications()
            # pub_b/pub_c share a millisecond and break the tie by id; pub_a sorts last despite inserting first
            self.assertEqual([r["id"] for r in rows], ["pub_b", "pub_c", "pub_d", "pub_a"])
            self.assertEqual([r["created_at"] for r in rows],
                             ["2026-01-01T00:00:00.100Z", "2026-01-01T00:00:00.100Z",
                              "2026-01-01T00:00:00.200Z", "2026-01-01T00:00:00.300Z"])
            self.assertEqual([r["id"] for r in db.publications(revision=revision)],
                             ["pub_b", "pub_c", "pub_d", "pub_a"])


class BlobTests(StorageCase):
    def test_put_blob_is_content_addressed_and_idempotent(self):
        """put_blob returns the sha256 of the bytes and storing the same bytes twice adds one row."""
        fixture = self.structured()
        with fixture.open() as db:
            before = db.blob_hashes()
            db.begin_immediate()
            first = db.put_blob(b"evidence transcript")
            second = db.put_blob(b"evidence transcript")
            db.commit()
            self.assertEqual(first, support.sha(b"evidence transcript"))
            self.assertEqual(first, second)
            self.assertNotIn(first, before)
            self.assertEqual(db.blob_hashes(), sorted(before + [first]))
            self.assertEqual(db.get_blob(first), b"evidence transcript")

    def test_storing_the_same_hash_again_never_overwrites_the_stored_bytes(self):
        """put_blob is INSERT OR IGNORE, so a second write of known content leaves the first bytes in place."""
        fixture = self.structured()
        with fixture.open() as db:
            db.begin_immediate()
            sha = db.put_blob(b"original payload")
            db.conn.execute("INSERT OR IGNORE INTO blobs (sha256, content) VALUES (?, ?)", (sha, b"impostor"))
            db.commit()
            self.assertEqual(db.get_blob(sha), b"original payload")
            self.assertEqual(db.blob_hashes().count(sha), 1)

    def test_get_blob_round_trips_exact_bytes_including_binary_and_empty(self):
        """Blobs are byte-exact: binary payloads and the empty payload come back unchanged."""
        fixture = self.structured()
        payloads = [b"", b"\x00\x01\x02\xff", "unicode ✓ body".encode("utf-8")]
        with fixture.open() as db:
            before = db.blob_hashes()
            db.begin_immediate()
            hashes = [db.put_blob(data) for data in payloads]
            db.commit()
            for data, sha in zip(payloads, hashes):
                self.assertEqual(db.get_blob(sha), data)
                self.assertIsInstance(db.get_blob(sha), bytes)
                self.assertTrue(db.has_blob(sha))
            self.assertEqual(db.blob_hashes(), sorted(set(before) | set(hashes)))

    def test_a_hash_that_was_never_stored_reads_as_missing(self):
        """has_blob is False and get_blob is None for an unknown digest rather than raising."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            absent = support.sha(b"never stored")
            self.assertFalse(db.has_blob(absent))
            self.assertIsNone(db.get_blob(absent))
            self.assertNotIn(absent, db.blob_hashes())

    def test_a_rolled_back_blob_is_not_visible(self):
        """Blobs are written inside the caller's transaction, so a rollback discards them."""
        fixture = self.structured()
        with fixture.open() as db:
            before = db.blob_hashes()
            db.begin_immediate()
            sha = db.put_blob(b"rolled back")
            db.rollback()
            self.assertFalse(db.has_blob(sha))
            self.assertIsNone(db.get_blob(sha))
            self.assertEqual(db.blob_hashes(), before)


# -- maintenance ------------------------------------------------------------------------------------
class MaintenanceTests(StorageCase):
    def test_integrity_reports_no_violations_on_a_healthy_database(self):
        """A database built through the public API passes both PRAGMA checks with no foreign key violations."""
        fixture = self.coherent_fixture().complete()
        with fixture.open(write=False) as db:
            self.assertEqual(db.integrity(), {"foreign_key_violations": [], "integrity": ["ok"]})

    def test_integrity_names_the_table_of_an_orphaned_reference(self):
        """integrity() is a real check: a reference row smuggled in with foreign keys off is reported."""
        fixture = self.structured()
        raw = sqlite3.connect(str(fixture.path))
        try:
            raw.execute("PRAGMA foreign_keys = OFF")
            raw.execute("""INSERT INTO record_refs (owner_collection, owner_id, owner_version, field_path,
                           target_collection, target_id, target_version)
                           VALUES ('items', 'itm_lem', 1, '/ghost', 'items', 'itm_ghost', NULL)""")
            raw.commit()
        finally:
            raw.close()
        with fixture.open(write=False) as db:
            report = db.integrity()
            self.assertEqual(report["integrity"], ["ok"])
            self.assertEqual([(row["table"], row["parent"]) for row in report["foreign_key_violations"]],
                             [("record_refs", "record_heads")])

    def test_backup_writes_a_readable_copy_at_the_same_head_revision(self):
        """backup() reports the destination, its sha256 and the revision, and the copy opens with the same heads."""
        fixture = self.structured()
        destination = self.work / "backup.db"
        with fixture.open(write=False) as db:
            result = db.backup(destination)
            expected_heads = [(r.collection, r.id, r.version) for r in db.heads()]
            revision = db.max_revision()
        self.assertEqual(sorted(result), ["backup", "revision", "sha256"])
        self.assertEqual(result["backup"], str(destination))
        self.assertEqual(result["revision"], revision)
        self.assertEqual(result["sha256"], support.sha(destination.read_bytes()))
        with storage.Database(destination) as copy:
            self.assertEqual(copy.max_revision(), revision)
            self.assertEqual([(r.collection, r.id, r.version) for r in copy.heads()], expected_heads)
            self.assertEqual(copy.metadata["storage_format"], "4")
            self.assertEqual(copy.integrity(), {"foreign_key_violations": [], "integrity": ["ok"]})
            self.assertEqual(storage.paper_record(copy).id, fixture.paper_id)

    def test_backup_creates_nested_parent_directories_without_changing_source(self):
        fixture = self.structured()
        destination = self.work / "missing" / "nested" / "backup.db"
        before = fixture.path.read_bytes()
        with fixture.open(write=False) as db:
            result = db.backup(destination)
            revision = db.max_revision()
        self.assertEqual(before, fixture.path.read_bytes())
        with storage.Database(destination) as copied:
            self.assertEqual(revision, copied.max_revision())
            self.assertEqual(result["sha256"], support.sha(destination.read_bytes()))

    def test_backup_rejects_non_directory_parent_with_actionable_error(self):
        fixture = self.structured()
        parent = self.path("parent-file")
        parent.write_bytes(b"keep parent")
        before = fixture.path.read_bytes()
        with fixture.open(write=False) as db:
            with self.assertRaises(InvalidRequest) as caught:
                db.backup(parent / "backup.db")
        self.assertEqual("BACKUP_PATH_INVALID", caught.exception.code)
        self.assertIn("not a directory", str(caught.exception))
        self.assertEqual(b"keep parent", parent.read_bytes())
        self.assertEqual(before, fixture.path.read_bytes())

    def test_backup_creation_permission_failure_is_actionable_and_preserves_source(self):
        fixture = self.structured()
        destination = self.path("denied.db")
        before = fixture.path.read_bytes()
        with fixture.open(write=False) as db:
            for owner, operation in ((storage.os, "open"), (storage.Path, "mkdir")):
                with self.subTest(operation=operation):
                    with patch.object(owner, operation, side_effect=PermissionError("fixture denied")):
                        with self.assertRaises(InvalidRequest) as caught:
                            db.backup(destination)
                    self.assertEqual("BACKUP_PATH_INVALID", caught.exception.code)
                    self.assertIn("destination path and permissions", str(caught.exception))
                    self.assertFalse(destination.exists())
                    self.assertEqual(before, fixture.path.read_bytes())

    def test_the_backup_is_a_detached_copy_not_a_second_handle(self):
        """Writing to the copy never reaches the source database, and the source keeps its own revision."""
        fixture = self.structured()
        destination = self.work / "detached.db"
        with fixture.open(write=False) as db:
            revision = db.backup(destination)["revision"]
        with storage.Database(destination, write=True) as copy:
            copy.begin_immediate()
            sha = copy.put_blob(b"only in the copy")
            copy.commit()
            self.assertTrue(copy.has_blob(sha))
        with fixture.open(write=False) as db:
            self.assertFalse(db.has_blob(sha))
            self.assertEqual(db.max_revision(), revision)

    def test_backup_refuses_to_overwrite_an_existing_destination(self):
        """An occupied destination raises InvalidRequest and its bytes are left alone."""
        fixture = self.structured()
        destination = self.path("taken.db")
        destination.write_bytes(b"do not clobber")
        with fixture.open(write=False) as db:
            with self.assertRaises(InvalidRequest) as caught:
                db.backup(destination)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("refusing to overwrite", str(caught.exception))
        self.assertEqual(destination.read_bytes(), b"do not clobber")

    def test_metadata_is_cached_at_open_and_set_metadata_upserts(self):
        """set_metadata inserts then replaces one key, and the value is visible to the next open."""
        fixture = self.structured()
        with fixture.open() as db:
            self.assertNotIn("probe_key", db.metadata)
            db.begin_immediate()
            db.set_metadata("probe_key", "one")
            db.set_metadata("probe_key", "two")
            db.commit()
            self.assertNotIn("probe_key", db.metadata)
            rows = db.conn.execute("SELECT value FROM metadata WHERE key = 'probe_key'").fetchall()
            self.assertEqual([row["value"] for row in rows], ["two"])
        with fixture.open(write=False) as db:
            self.assertEqual(db.metadata["probe_key"], "two")
            self.assertEqual(db.metadata["core_version"], CORE_VERSION)

    def test_paper_record_returns_the_single_paper_head(self):
        """paper_record resolves the one live paper and its body carries the fixture's title."""
        fixture = self.structured()
        with fixture.open(write=False) as db:
            paper = storage.paper_record(db)
            self.assertEqual(paper.collection, "papers")
            self.assertEqual(paper.id, fixture.paper_id)
            self.assertEqual(paper.version, 1)
            self.assertEqual(paper.body["title"], "Test paper")

    def test_paper_record_raises_when_there_is_not_exactly_one_paper(self):
        """A second live paper head makes paper_record raise INCOMPATIBLE rather than picking one."""
        fixture = self.structured()
        with fixture.open() as db:
            db.begin_immediate()
            db.insert_version("papers", "pap_second", 1, db.max_revision(),
                              {"title": "Second", "source_root": ".", "main_items": [], "report_paths": []})
            db.set_head("papers", "pap_second", 1)
            db.commit()
            self.assertEqual(len(db.heads("papers")), 2)
            with self.assertRaises(IncompatibleError) as caught:
                storage.paper_record(db)
            self.assertEqual(caught.exception.code, "INCOMPATIBLE")
            self.assertIn("expected exactly one paper record, found 2", str(caught.exception))


# -- append-only guarantees and schema constraints ----------------------------------------------------
class AppendOnlyTests(StorageCase):
    def test_updating_a_record_version_row_is_refused_by_the_trigger(self):
        """A direct UPDATE against record_versions aborts with 'record versions are immutable'."""
        fixture = self.structured()
        with fixture.open() as db:
            before = db.head("items", "itm_lem").body
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                db.conn.execute("UPDATE record_versions SET body_json = '{}' "
                                "WHERE collection = 'items' AND id = 'itm_lem'")
            self.assertIn("record versions are immutable", str(caught.exception))
        with fixture.open(write=False) as db:
            self.assertEqual(db.head("items", "itm_lem").body, before)

    def test_even_a_no_op_update_of_a_version_row_is_refused(self):
        """The trigger fires BEFORE UPDATE, so rewriting a column with its own value is refused as well."""
        fixture = self.structured()
        with fixture.open() as db:
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                db.conn.execute("UPDATE record_versions SET retired = retired WHERE collection = 'items'")
            self.assertIn("record versions are immutable", str(caught.exception))
            self.assertEqual([(r.collection, r.id, r.version) for r in db.all_versions()],
                             [(c, i, v) for _, c, i, v in structure_log(fixture)])

    def test_deleting_a_record_version_row_is_refused_by_the_trigger(self):
        """A direct DELETE against record_versions aborts and the whole log survives."""
        fixture = self.structured()
        with fixture.open() as db:
            before = len(db.all_versions())
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                db.conn.execute("DELETE FROM record_versions WHERE collection = 'items'")
            self.assertIn("record versions are immutable", str(caught.exception))
        with fixture.open(write=False) as db:
            self.assertEqual(len(db.all_versions()), before)
            self.assertEqual([r.id for r in db.heads("items")], ["itm_lem", "itm_thm"])

    def test_commits_are_immutable_against_update_and_delete(self):
        """The commit log refuses both rewriting a receipt and dropping a revision."""
        fixture = self.structured()
        with fixture.open() as db:
            before = db.commit_row(1)
            for statement in ("UPDATE commits SET receipt_json = '{}' WHERE revision = 1",
                              "DELETE FROM commits WHERE revision = 1"):
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    db.conn.execute(statement)
                self.assertIn("commits are immutable", str(caught.exception))
        with fixture.open(write=False) as db:
            self.assertEqual(db.commit_row(1), before)

    def test_a_record_may_carry_only_one_version_per_revision(self):
        """The UNIQUE(collection, id, revision) constraint stops a second version landing in one commit."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture,
            lambda db: db.insert_version("items", "itm_lem", 9, db.max_revision(), {"kind": "lemma"}),
            "UNIQUE constraint failed")

    def test_a_version_must_belong_to_an_existing_revision(self):
        """record_versions.revision is a foreign key onto commits, so an unknown revision is refused."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture,
            lambda db: db.insert_version("items", "itm_ghost", 1, 9999, {"kind": "lemma"}),
            "FOREIGN KEY constraint failed")

    def test_record_versions_rejects_a_collection_outside_the_contract(self):
        """The collection CHECK keeps unknown collections out of the log entirely."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture,
            lambda db: db.insert_version("bogus", "bog_1", 1, db.max_revision(), {"a": 1}),
            "CHECK constraint failed")

    def test_a_version_row_must_agree_with_itself_about_being_retired(self):
        """A tombstone carries no body, a live version carries valid JSON, and version numbers start at 1."""
        fixture = self.structured()
        insert = ("INSERT INTO record_versions (collection, id, version, revision, retired, body_json, "
                  "body_digest) VALUES ('items', 'itm_zzz', ?, ?, ?, ?, ?)")
        for label, version, retired, body in (("retired with a body", 1, 1, "{}"),
                                              ("live without a body", 1, 0, None),
                                              ("body that is not JSON", 1, 0, "not json"),
                                              ("version zero", 0, 0, "{}")):
            with self.subTest(label):
                self.assert_write_refused(
                    fixture,
                    lambda db, v=version, r=retired, b=body: db.conn.execute(
                        insert, (v, db.max_revision(), r, b, "a" * 64)),
                    "CHECK constraint failed")

    def test_a_head_must_point_at_a_version_that_exists(self):
        """record_heads carries a deferred foreign key, so a head into nowhere is refused at commit."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture, lambda db: db.set_head("items", "itm_ghost", 1), "FOREIGN KEY constraint failed")

    def test_record_facets_rejects_an_unknown_facet_name(self):
        """Only the eight contract facets may be indexed, and each digest must be 64 characters."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture, lambda db: db.insert_facets("items", "itm_lem", 1, {"bogus": "a" * 64}),
            "CHECK constraint failed")
        self.assert_write_refused(
            fixture, lambda db: db.insert_facets("items", "itm_lem", 1, {"scope": "short"}),
            "CHECK constraint failed")

    def test_record_refs_requires_the_target_record_to_exist(self):
        """A reference row onto a record that was never written fails the deferred foreign key at commit."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture,
            lambda db: db.insert_refs("items", "itm_lem", 1, [{"field_path": "/ghost",
                                                               "target_collection": "items",
                                                               "target_id": "itm_ghost",
                                                               "target_version": None}]),
            "FOREIGN KEY constraint failed")

    def test_packets_reject_a_mode_outside_the_four_review_modes(self):
        """packets.mode is constrained to author, primary, independent and reconcile."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture,
            lambda db: db.insert_packet("pkt_bad", db.max_revision(), "bogus", {"mode": "bogus", "packet_version": 2},
                                        db.put_blob(b"payload")),
            "CHECK constraint failed")

    def test_packets_must_declare_supported_packet_versions(self):
        """packet_version is limited to 1 and 2 by the schema, so a packet from a newer protocol cannot be stored."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture,
            lambda db: db.conn.execute(
                """INSERT INTO packets (packet_id, packet_version, base_revision, mode, manifest_json,
                   payload_sha256, created_at) VALUES ('pkt_v3', 3, ?, 'author', '{}', ?, '2026-01-01')""",
                (db.max_revision(), db.put_blob(b"payload"))),
            "CHECK constraint failed")

    def test_publications_reject_unknown_kinds_states_and_artifacts(self):
        """publications constrain kind and state, and the artifact hash must reference a stored blob."""
        fixture = self.structured()
        for kind, state, artifact, fragment in (
                ("bogus", "built", None, "CHECK constraint failed"),
                ("working", "bogus", None, "CHECK constraint failed"),
                ("working", "built", "f" * 64, "FOREIGN KEY constraint failed")):
            with self.subTest(kind=kind, state=state):
                self.assert_write_refused(
                    fixture,
                    lambda db, k=kind, s=state, a=artifact: db.insert_publication(
                        "pub_bad", db.max_revision(), k, s, "out.html", a, {"n": 1}),
                    fragment)

    def test_run_events_constrain_the_stage_and_the_elapsed_time(self):
        """run_events accepts only the named stages and refuses a negative elapsed_ms."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture, lambda db: db.insert_run_event("evt_bad", "run_1", "bogus", "t", 1, {"n": 1}),
            "CHECK constraint failed")
        self.assert_write_refused(
            fixture, lambda db: db.insert_run_event("evt_bad", "run_1", "command", "t", -1, {"n": 1}),
            "CHECK constraint failed")
        with fixture.open() as db:
            db.begin_immediate()
            db.insert_run_event("evt_ok", "run_1", "command", "2026-01-01T00:00:00.000Z", 12, {"n": 1})
            db.commit()
            rows = [dict(row) for row in db.conn.execute("SELECT * FROM run_events")]
            self.assertEqual([(r["id"], r["stage"], r["elapsed_ms"]) for r in rows],
                             [("evt_ok", "command", 12)])
            self.assertEqual(json.loads(rows[0]["details_json"]), {"n": 1})

    def test_blobs_reject_a_hash_that_is_not_a_sha256(self):
        """The blobs primary key is CHECKed to be 64 characters so a truncated digest cannot be stored."""
        fixture = self.structured()
        self.assert_write_refused(
            fixture,
            lambda db: db.conn.execute("INSERT INTO blobs (sha256, content) VALUES ('abc', ?)", (b"x",)),
            "CHECK constraint failed")

    def test_editing_a_record_appends_a_version_and_leaves_the_old_one_readable(self):
        """The public write path never mutates: version 1's body is still exactly what was first written."""
        fixture = self.structured()
        with fixture.open() as db:
            original = db.head("items", "itm_lem").body
            revision = bump_caption(fixture, db, "Lemma 1 restated")
            self.assertEqual(db.version("items", "itm_lem", 1).body, original)
            self.assertEqual(db.version("items", "itm_lem", 1).revision, revision - 1)
            self.assertEqual(db.head("items", "itm_lem").body["caption"], "Lemma 1 restated")
            self.assertNotEqual(db.head("items", "itm_lem").body, original)
            self.assertEqual(len(db.versions_of("items", "itm_lem")), 2)
            self.assertEqual(db.facets("items", "itm_lem", 1)["full"], digest(original))


# -- optimistic concurrency -------------------------------------------------------------------------
class OptimisticConcurrencyTests(StorageCase):
    def test_two_writers_at_one_version_produce_one_commit_and_one_conflict(self):
        """Both writers read itm_lem at the same version and base revision; only the first commits."""
        fixture = self.structured()
        outcome = race(fixture)
        self.assertEqual(outcome["first_version"], 1)
        self.assertEqual(outcome["second_version"], 1)
        self.assertEqual(outcome["first_base"], outcome["before"])
        self.assertEqual(outcome["second_base"], outcome["before"])
        self.assertEqual(outcome["winner"]["revision"], outcome["before"] + 1)
        self.assertEqual(outcome["winner"]["changed"],
                         [{"collection": "items", "id": "itm_lem", "version": 2, "op": "replace"}])
        self.assertIsInstance(outcome["loser"], ConflictError)
        self.assertEqual(outcome["loser"].code, "CONFLICT")
        self.assertEqual(outcome["loser"].exit_code, 3)

    def test_the_conflict_names_the_expected_and_actual_versions(self):
        """The loser's error reports the record it read, the version it expected and the version it found."""
        fixture = self.structured()
        outcome = race(fixture)
        record = outcome["loser"].records[0]
        self.assertEqual(record["changed"], [{"ref": {"collection": "items", "id": "itm_lem"},
                                              "expected_version": 1,
                                              "actual_version": 2,
                                              "retired": False}])
        self.assertEqual(record["changed_relations"], [])
        self.assertFalse(record["source_context_changed"])

    def test_the_conflict_hands_back_the_command_that_refreshes_the_packet(self):
        """A conflict is actionable: it carries the get command, targets and mode needed to rebase."""
        fixture = self.structured()
        outcome = race(fixture)
        retry = outcome["loser"].retry
        self.assertEqual(retry["targets"], [{"collection": "items", "id": "itm_lem"}])
        self.assertEqual(retry["mode"], "author")
        self.assertIn("--target items:itm_lem", retry["command"])
        self.assertIn("--mode author", retry["command"])

    def test_the_losing_writer_wrote_nothing_at_all(self):
        """After the conflict there is no commit, no version and no open transaction for the loser."""
        fixture = self.structured()
        outcome = race(fixture)
        self.assertFalse(outcome["loser_in_transaction"])
        with fixture.open(write=False) as db:
            self.assertEqual(db.max_revision(), outcome["before"] + 1)
            self.assertIsNotNone(db.commit_by_request("req_race_first"))
            self.assertIsNone(db.commit_by_request("req_race_second"))
            head = db.head("items", "itm_lem")
            self.assertEqual(head.version, 2)
            self.assertEqual(head.body["caption"], "first writer")
            self.assertEqual([r.body["caption"] for r in db.versions_of("items", "itm_lem")],
                             ["Lemma 1", "first writer"])
            self.assertEqual(db.integrity(), {"foreign_key_violations": [], "integrity": ["ok"]})

    def test_the_loser_succeeds_once_it_refreshes_its_packet(self):
        """The conflict is recoverable: a fresh packet at the new head commits the same edit."""
        fixture = self.structured()
        outcome = race(fixture)
        with fixture.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="author")
            head = db.head("items", "itm_lem")
            receipt = acceptance.apply_batch(db, {
                "contract_version": 3, "request_id": "req_race_second_retry",
                "packet_id": packet["packet_id"],
                "edits": [edit("replace", "items", "itm_lem", dict(head.body, caption="second writer"),
                               expected=head.version)]})
            self.assertEqual(receipt["revision"], outcome["before"] + 2)
            self.assertEqual(db.head("items", "itm_lem").version, 3)
            self.assertEqual(db.head("items", "itm_lem").body["caption"], "second writer")
            self.assertEqual([r.body["caption"] for r in db.versions_of("items", "itm_lem")],
                             ["Lemma 1", "first writer", "second writer"])

    def test_a_stale_expected_version_conflicts_even_inside_a_current_packet(self):
        """The per-edit version guard is checked in its own right, not only through the packet's pins.

        The packet here is issued moments before the batch, so every pin it carries is still current; the
        only thing wrong is the version the edit claims to be replacing.
        """
        fixture = self.structured()
        with fixture.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="author")
            head = db.head("items", "itm_lem")
            self.assertEqual(head.version, 1)
            before = db.max_revision()
            self.assertEqual(packet["base_revision"], before)
            with self.assertRaises(ConflictError) as caught:
                acceptance.apply_batch(db, {
                    "contract_version": 3, "request_id": "req_stale", "packet_id": packet["packet_id"],
                    "edits": [edit("replace", "items", "itm_lem", dict(head.body, caption="stale write"),
                                   expected=7)]})
            self.assertEqual(caught.exception.code, "CONFLICT")
            self.assertEqual(caught.exception.records[0]["changed"],
                             [{"ref": {"collection": "items", "id": "itm_lem"},
                               "expected_version": 7, "actual_version": 1, "retired": False}])
            self.assertEqual(db.max_revision(), before)
            self.assertIsNone(db.commit_by_request("req_stale"))
            self.assertEqual([r.version for r in db.versions_of("items", "itm_lem")], [1])
            self.assertEqual(db.head("items", "itm_lem").body, head.body)

    def test_replaying_an_identical_batch_returns_the_stored_receipt_without_a_new_revision(self):
        """Idempotency is anchored in the commit log: the same request id and digest replays the same receipt."""
        fixture = self.structured()
        with fixture.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="author")
            head = db.head("items", "itm_lem")
            batch = {"contract_version": 3, "request_id": "req_replay", "packet_id": packet["packet_id"],
                     "edits": [edit("replace", "items", "itm_lem", dict(head.body, caption="once"),
                                    expected=head.version)]}
            first = acceptance.apply_batch(db, batch)
            revision = db.max_revision()
            second = acceptance.apply_batch(db, batch)
            self.assertEqual(second, first)
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(len(db.versions_of("items", "itm_lem")), 2)
            stored = db.commit_by_request("req_replay")
            self.assertEqual(stored["revision"], first["revision"])
            self.assertEqual(json.loads(stored["receipt_json"]), first)


class NormativeDdlTests(unittest.TestCase):
    """The shipped DDL is the handoff's DDL (implementation-handoff 1, 2).

    Handoff section 2 gives ``handoff/schema.sql`` ownership of the physical SQL definition, and
    section 1 calls it executable specification material. ``shared/paper_core/schema.sql`` is the copy
    the core actually executes. Nothing else in the lane would notice the two drifting apart: the core
    would keep passing against its own altered tables while silently leaving the owning document
    behind. Compare the bytes.
    """

    SHIPPED = CORE / "schema.sql"
    NORMATIVE = HANDOFF / "schema.sql"

    def test_both_files_are_present(self):
        """Guards the comparison below: a missing file must fail loudly, not compare equal."""
        self.assertTrue(self.NORMATIVE.is_file(), self.NORMATIVE)
        self.assertTrue(self.SHIPPED.is_file(), self.SHIPPED)
        self.assertGreater(self.NORMATIVE.stat().st_size, 1000)

    def test_prior_handoff_ddl_remains_a_real_supported_migration_baseline(self):
        """The historical handoff remains schema 3; maintained SQL now owns schema 4."""
        self.assertIn("('storage_format', '3')", self.NORMATIVE.read_text(encoding="utf-8"))
        self.assertIn("('storage_format', '4')", self.SHIPPED.read_text(encoding="utf-8"))
        self.assertIn("CREATE VIEW proof_applications", self.SHIPPED.read_text(encoding="utf-8"))

    def test_the_shipped_ddl_really_is_what_builds_a_database(self):
        """Pins the comparison to the executed file: every object it declares exists in a new database."""
        declared = set(re.findall(r"CREATE(?:\s+UNIQUE)?\s+(?:TABLE|VIEW|INDEX|TRIGGER)"
                                  r"(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)",
                                  self.SHIPPED.read_text(encoding="utf-8"), re.IGNORECASE))
        self.assertGreater(len(declared), 10)
        root = pathlib.Path(tempfile.mkdtemp())
        try:
            path = root / "ddl.db"
            storage.initialize(path, source_root=root, title="DDL check")
            conn = sqlite3.connect(str(path))
            try:
                built = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
            finally:
                conn.close()
        finally:
            support.rmtree_force(root)
        self.assertEqual(sorted(declared - built), [])


if __name__ == "__main__":
    unittest.main()
