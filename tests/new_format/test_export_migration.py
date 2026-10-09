"""Behaviour tests for ``paper_core.export_import`` (implementation-handoff 5 and record-contract 7).

Three commands share this module because they share one promise: a database must be able to leave the
core and come back without losing a record body, and legacy data must arrive through the ordinary
acceptance engine rather than through hand-written rows. The export tests compare the snapshot against
records read back from SQLite, never against a literal, so a change in what the core stores fails here.
The migration and import tests pin the record population, the surviving evidence and the refusal paths,
and assert that a refused command wrote nothing at all.
"""
from __future__ import annotations

import base64
import json
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

import support
from support import OVERVIEW, OVERVIEW_EXAMPLE, R, TempCase, edit, sha

from paper_core import assessment, export_import, packets, projection, storage
from paper_core.canonical import digest
from paper_core.errors import IncompatibleError, InvalidRequest

LEGACY_OVERVIEW_FORMAT = "archify-paper-database-1"

# Counts of the shipped legacy fixtures, verified against the files by the manual validation pass.
OVERVIEW_COUNTS = {"sources": 1, "anchors": 21, "items": 6, "uses": 11, "groups": 0, "observations": 17}
# migrate_overview preserves observation created_at/input_snapshot/carried_from inside each note and
# reports that practice once; every legacy observation carries created_at and input_snapshot.
OBSERVATION_NOTE_LIMITATION = ("legacy observation fields created_at, input_snapshot and carried_from have no "
                               "contract-3 home; each observation preserves them in its note")
LEGACY_AUDIT_COUNTS = {"anchors": 4, "items": 2, "uses": 1, "audits": 1, "scopes": 1, "qualifications": 1,
                       "arguments": 2, "checks": 4, "responses": 2, "findings": 1, "identity_maps": 1}

# Files that must still be byte-identical after import_legacy has read the shipped reference audit.
LEGACY_AUDIT_SAMPLE_FILES = ("AUDIT_MANIFEST.json", "audit/04_local_checks/lem-growing-max.ledger.json",
                             "audit/04_local_checks/thm-main.ledger.json", "audit/06_reports/ISSUE_LOG.json")


def legacy_overview_runtime():
    """The proof-graphify runtime, imported only to build a legacy database to migrate."""
    scripts = str(OVERVIEW / "scripts")
    if scripts not in sys.path:
        # appended, never inserted: that folder ships its own paper_core that must not shadow shared/
        sys.path.append(scripts)
    import paper_database
    return paper_database


def plain_envelopes(records) -> list:
    """The record-contract envelope written out independently of ``export_import.envelope``."""
    return [{"collection": r.collection, "id": r.id, "version": r.version, "revision": r.revision,
             "retired": r.retired, "body": None if r.retired else r.body} for r in records]


def referenced_blobs(db) -> set:
    """Every blob hash the live head bodies of ``db`` refer to."""
    wanted = set()
    for record in db.heads("sources"):
        wanted.add(record.body["blob_sha256"])
    for record in db.heads("responses"):
        wanted.add(record.body["original_blob"])
    for record in db.heads("qualifications"):
        body = record.body
        wanted.add(body["evidence_blob"])
        wanted.update(case["response_blob"]
                      for case in body["valid_case_results"] + body["invalid_case_results"])
    for record in db.heads("identity_maps"):
        if record.body["source_blob"] is not None:
            wanted.add(record.body["source_blob"])
    return wanted


def source_identity_of(records) -> str:
    """The provenance digest re-derived from the live source records of one revision."""
    return digest(sorted([r.id, r.version, r.body["blob_sha256"]]
                         for r in records if r.collection == "sources" and not r.retired))


def binding_shape(binding) -> tuple:
    """A stored binding reduced to the facts a reviewer depends on: pinned refs and relation keys."""
    records = [(entry["ref"]["collection"], entry["ref"]["id"], entry["ref"]["version"], entry["facet"])
               for entry in binding["records"]]
    relations = [(entry["relation"], entry["key"]["collection"], entry["key"]["id"])
                 for entry in binding["relations"]]
    return records, relations


def legacy_tables(path) -> dict:
    """Every row of a legacy overview database, so a backup can be compared with its original."""
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("metadata", "source_blobs", "snapshots", "current_snapshot",
                              "observations", "builds")}
    finally:
        conn.close()


def extra_use_body() -> dict:
    """A second, retirable use between the two fixture items; ``uses`` is never packet-bound."""
    return {"from": R("items", "itm_lem"), "to": R("items", "itm_thm"), "type": "definition",
            "group_id": None, "reason": "mentioned in passing", "needed_form": None, "substitutions": [],
            "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None}


def draft_check_edit() -> dict:
    """A retirable primary check; ``checks`` is packet-bound, so its binding must travel with it."""
    return support.Fixture.check_edit("chk_draft", R("arguments", "arg_lem"), "composition",
                                      evidence=["anc_lem_proof"], outcome=None, state="draft")


class ExportSnapshotTest(TempCase):
    """``export_snapshot`` and ``write_export`` over the completed two-item audit database."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().complete()

    def read(self):
        db = storage.Database(self.fx.path)
        self.addCleanup(db.close)
        return db

    def test_envelope_exposes_exactly_the_record_contract_fields(self):
        """envelope() reports collection, id, version, revision, retired and the live body, nothing else."""
        db = self.read()
        record = db.head("items", "itm_lem")
        self.assertEqual(record.body["label"], "Lemma 1")
        envelope = export_import.envelope(record)
        self.assertEqual(sorted(envelope), ["body", "collection", "id", "retired", "revision", "version"])
        self.assertEqual(envelope, {"collection": "items", "id": "itm_lem", "version": 1,
                                    "revision": record.revision, "retired": False, "body": record.body})
        # both items were created by one batch, so the envelope revision is that commit, not a counter
        self.assertEqual(envelope["revision"], db.head("items", "itm_thm").revision)

    def test_envelope_drops_the_body_of_a_retired_record(self):
        """A tombstone envelope keeps its version and revision but never carries a body."""
        record = storage.Record("uses", "use_x", 3, 9, True, {"type": "dependency"})
        self.assertEqual(export_import.envelope(record),
                         {"collection": "uses", "id": "use_x", "version": 3, "revision": 9,
                          "retired": True, "body": None})

    def test_head_snapshot_mirrors_the_database(self):
        """The default export is the head revision and its record list equals records_at(head)."""
        db = self.read()
        top = db.max_revision()
        snapshot = export_import.export_snapshot(db)
        self.assertEqual(sorted(snapshot), ["bindings", "blobs", "contract_version", "paper_id",
                                            "provenance", "records", "revision", "storage_format"])
        self.assertEqual(snapshot["contract_version"], 4)
        self.assertEqual(snapshot["storage_format"], 4)
        self.assertEqual(snapshot["revision"], top)
        self.assertEqual(snapshot["paper_id"], self.fx.paper_id)
        self.assertEqual(snapshot["records"], plain_envelopes(db.records_at(top, include_retired=True)))
        self.assertEqual(sorted(snapshot["provenance"]),
                         ["core_version", "projection_version", "source_identity"])
        self.assertEqual(snapshot["provenance"]["core_version"], "2.3.9")
        self.assertEqual(snapshot["provenance"]["projection_version"], 2)
        self.assertNotIn("missing_blobs", snapshot["provenance"])

    def test_revision_none_is_exactly_the_head_revision(self):
        """Omitting revision exports head, and head differs from the revision before the last commit."""
        db = self.read()
        top = db.max_revision()
        self.assertEqual(export_import.export_snapshot(db),
                         export_import.export_snapshot(db, revision=top))
        earlier = export_import.export_snapshot(db, revision=top - 1)
        self.assertEqual(earlier["revision"], top - 1)
        self.assertNotEqual(earlier["records"], export_import.export_snapshot(db)["records"])

    def test_provenance_identifies_the_sources_of_that_revision(self):
        """source_identity digests id, version and blob hash of the live sources, so it moves with them."""
        db = self.read()
        top = db.max_revision()
        snapshot = export_import.export_snapshot(db)
        self.assertEqual(snapshot["provenance"]["source_identity"],
                         source_identity_of(db.records_at(top, include_retired=True)))
        self.assertEqual(len(snapshot["provenance"]["source_identity"]), 64)
        # revision 1 holds only the paper record, so the identity is the digest of an empty source list
        first = export_import.export_snapshot(db, revision=1)
        self.assertEqual(first["provenance"]["source_identity"], digest([]))
        self.assertNotEqual(first["provenance"]["source_identity"],
                            snapshot["provenance"]["source_identity"])

    def test_export_round_trips_every_record_body(self):
        """Each exported body is the body SQLite holds, and survives a JSON encode/decode unchanged."""
        db = self.read()
        snapshot = export_import.export_snapshot(db)
        by_key = {(entry["collection"], entry["id"]): entry for entry in snapshot["records"]}
        self.assertEqual(len(by_key), len(snapshot["records"]))
        stored = db.records_at(db.max_revision(), include_retired=True)
        self.assertEqual(set(by_key), {(record.collection, record.id) for record in stored})
        for record in stored:
            entry = by_key[(record.collection, record.id)]
            self.assertEqual(entry["version"], record.version)
            self.assertEqual(entry["body"], record.body)
        self.assertEqual(by_key[("items", "itm_lem")]["body"]["statement"],
                         {"form": "verbatim", "text": "Lemma 1 text"})
        self.assertEqual(json.loads(json.dumps(snapshot, ensure_ascii=False, allow_nan=False)), snapshot)

    def test_snapshot_is_ordered_and_deterministic(self):
        """Records, blobs and history come out in a fixed order, so two exports are byte-identical."""
        db = self.read()
        top = db.max_revision()
        first = export_import.export_snapshot(db, revision=top, history=True)
        second = export_import.export_snapshot(db, revision=top, history=True)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        keys = [(entry["collection"], entry["id"]) for entry in first["records"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual([entry["sha256"] for entry in first["blobs"]],
                         sorted(entry["sha256"] for entry in first["blobs"]))
        history_keys = [(entry["revision"], entry["collection"], entry["id"], entry["version"])
                        for entry in first["history"]]
        self.assertEqual(history_keys, sorted(history_keys))
        # the same snapshot written twice to different paths hashes the same, which is what diffing needs
        one = export_import.write_export(db, output=self.work / "out" / "a.json", revision=top, history=True)
        two = export_import.write_export(db, output=self.work / "out" / "b.json", revision=top, history=True)
        self.assertEqual(one["sha256"], two["sha256"])
        self.assertEqual((self.work / "out" / "a.json").read_bytes(),
                         (self.work / "out" / "b.json").read_bytes())

    def test_snapshot_carries_every_referenced_blob(self):
        """Source, response and qualification blobs travel with the export, sorted and base64 encoded."""
        db = self.read()
        snapshot = export_import.export_snapshot(db)
        wanted = referenced_blobs(db)
        self.assertEqual(len(wanted), 6)
        self.assertEqual([entry["sha256"] for entry in snapshot["blobs"]], sorted(wanted))
        for entry in snapshot["blobs"]:
            self.assertEqual(entry["encoding"], "base64")
            data = base64.b64decode(entry["data"])
            self.assertEqual(sha(data), entry["sha256"])
            self.assertEqual(data, db.get_blob(entry["sha256"]))
        source = db.heads("sources")[0]
        carried = {entry["sha256"]: base64.b64decode(entry["data"]) for entry in snapshot["blobs"]}
        self.assertEqual(carried[source.body["blob_sha256"]],
                         (self.fx.source_root / "paper.tex").read_bytes())

    def test_bindings_name_every_bound_live_record(self):
        """The export carries the stored packet binding of each bound record, keyed by its pinned ref."""
        db = self.read()
        top = db.max_revision()
        snapshot = export_import.export_snapshot(db)
        expected = {(r.collection, r.id, r.version)
                    for r in db.records_at(top, include_retired=True)
                    if not r.retired and db.binding(r.collection, r.id, r.version) is not None}
        self.assertEqual({(b["ref"]["collection"], b["ref"]["id"], b["ref"]["version"])
                          for b in snapshot["bindings"]}, expected)
        self.assertEqual({collection for collection, _, _ in expected},
                         {"checks", "observations", "reconciliations", "source_reviews"})
        for binding in snapshot["bindings"]:
            ref = binding["ref"]
            stored = db.binding(ref["collection"], ref["id"], ref["version"])
            self.assertEqual(binding["packet_id"], stored["packet_id"])
            self.assertEqual(binding["bindings"], stored["bindings"])
            self.assertEqual(sorted(set(binding["bindings"]) - {"semantic_memberships"}),
                             ["packet_id", "records", "relations", "source_context_digest"])
            if "semantic_memberships" in binding["bindings"]:
                self.assertIsInstance(binding["bindings"]["semantic_memberships"], list)
            self.assertEqual(binding["bindings"]["packet_id"], binding["packet_id"])
            self.assertIsNone(binding["bindings"]["source_context_digest"])

    def test_binding_of_the_lemma_observation_pins_its_whole_read_context(self):
        """obs_lem is bound to both lemma anchors and both lemma facets, plus the parts_of_item relation."""
        db = self.read()
        snapshot = export_import.export_snapshot(db)
        binding = next(b for b in snapshot["bindings"] if b["ref"]["id"] == "obs_lem")
        self.assertEqual(binding["ref"], {"collection": "observations", "id": "obs_lem", "version": 1})
        records, relations = binding_shape(binding["bindings"])
        self.assertEqual(records, [("anchors", "anc_lem", 1, "source"),
                                   ("anchors", "anc_lem", 1, "statement"),
                                   ("anchors", "anc_lem_proof", 1, "source"),
                                   ("anchors", "anc_lem_proof", 1, "statement"),
                                   ("items", "itm_lem", 1, "proof"),
                                   ("items", "itm_lem", 1, "statement"),
                                   ("sources", self.fx.source_id, 1, "source")])
        self.assertEqual(relations, [("parts_of_item", "items", "itm_lem")])
        digests = {entry["digest"] for entry in binding["bindings"]["records"]}
        self.assertEqual(len(digests), len(records))
        self.assertTrue(all(len(value) == 64 for value in digests))

    def test_history_adds_superseded_versions(self):
        """history=True appends every version up to the revision; the record list still holds only heads."""
        db = self.read()
        top = db.max_revision()
        snapshot = export_import.export_snapshot(db)
        with_history = export_import.export_snapshot(db, history=True)
        self.assertNotIn("history", snapshot)
        self.assertEqual({k: v for k, v in with_history.items() if k != "history"}, snapshot)
        self.assertEqual(with_history["history"],
                         plain_envelopes([v for v in db.all_versions() if v.revision <= top]))
        superseded = [v for v in db.all_versions() if v.version > 1]
        # the completed fixture supersedes exactly the two worker responses when the coordinator maps them
        self.assertEqual(sorted({(v.collection, v.version) for v in superseded}), [("responses", 2)])
        self.assertEqual(len(superseded), 2)
        self.assertGreater(len(with_history["history"]), len(with_history["records"]))
        for record in superseded:
            key = (record.collection, record.id)
            versions = [e["version"] for e in with_history["history"]
                        if (e["collection"], e["id"]) == key]
            self.assertEqual(versions, [1, 2])
            self.assertEqual([e["version"] for e in with_history["records"]
                              if (e["collection"], e["id"]) == key], [record.version])

    def test_history_stops_at_the_requested_revision(self):
        """An older export with history carries no version committed after that revision."""
        db = self.read()
        superseded = next(v for v in db.all_versions() if v.version > 1)
        before = superseded.revision - 1
        with_history = export_import.export_snapshot(db, revision=before, history=True)
        expected = plain_envelopes([v for v in db.all_versions() if v.revision <= before])
        self.assertEqual(with_history["history"], expected)
        self.assertEqual(len(with_history["history"]), len(expected))
        self.assertLess(len(with_history["history"]),
                        len(export_import.export_snapshot(db, history=True)["history"]))
        self.assertTrue(all(entry["revision"] <= before for entry in with_history["history"]))
        self.assertNotIn((superseded.collection, superseded.id, superseded.version),
                         {(e["collection"], e["id"], e["version"]) for e in with_history["history"]})

    def test_older_revision_exports_the_state_of_that_revision(self):
        """An export pinned before a record was replaced returns the earlier body, not the head body."""
        db = self.read()
        superseded = next(v for v in db.all_versions() if v.version > 1 and not v.retired)
        before = superseded.revision - 1
        early = export_import.export_snapshot(db, revision=before)
        self.assertEqual(early["revision"], before)
        self.assertTrue(all(entry["revision"] <= before for entry in early["records"]))
        entry = next(e for e in early["records"]
                     if (e["collection"], e["id"]) == (superseded.collection, superseded.id))
        previous = db.version(superseded.collection, superseded.id, superseded.version - 1)
        self.assertEqual(entry["version"], previous.version)
        self.assertEqual(entry["body"], previous.body)
        head_entry = next(e for e in export_import.export_snapshot(db)["records"]
                          if (e["collection"], e["id"]) == (superseded.collection, superseded.id))
        self.assertEqual(head_entry["version"], superseded.version)
        self.assertNotEqual(head_entry["body"], entry["body"])

    def test_older_revision_omits_records_created_later(self):
        """Records committed after the requested revision are absent from that export."""
        db = self.read()
        top = db.max_revision()
        early = export_import.export_snapshot(db, revision=1)
        self.assertEqual([e["collection"] for e in early["records"]], ["papers"])
        self.assertEqual(early["paper_id"], self.fx.paper_id)
        self.assertEqual(early["bindings"], [])
        self.assertEqual(early["blobs"], [])
        head_keys = {(e["collection"], e["id"]) for e in export_import.export_snapshot(db)["records"]}
        self.assertEqual(head_keys - {(e["collection"], e["id"]) for e in early["records"]},
                         {(r.collection, r.id) for r in db.records_at(top, include_retired=True)
                          if r.collection != "papers"})

    def test_revision_out_of_range_is_refused(self):
        """Anything that is not an integer in 1..head is REVISION_RANGE, booleans included."""
        db = self.read()
        top = db.max_revision()
        for bad in (0, -1, top + 1, "3", 1.5, True):
            with self.subTest(revision=bad):
                with self.assertRaises(InvalidRequest) as caught:
                    export_import.export_snapshot(db, revision=bad)
                self.assertEqual(caught.exception.code, "REVISION_RANGE")
                self.assertEqual(caught.exception.exit_code, 2)
                self.assertEqual(caught.exception.message, f"revision {bad!r} is not in 1..{top}")

    def test_write_export_writes_one_deterministic_file(self):
        """write_export creates the parent folder, leaves no staging file and reports the file digest."""
        db = self.read()
        top = db.max_revision()
        snapshot = export_import.export_snapshot(db, revision=top, history=True)
        output = self.work / "exports" / "deep" / "snapshot.json"
        result = export_import.write_export(db, output=output, revision=top, history=True)
        payload = output.read_bytes()
        self.assertEqual(result, {"output": str(output), "revision": top, "paper_id": self.fx.paper_id,
                                  "records": len(snapshot["records"]), "blobs": len(snapshot["blobs"]),
                                  "history": len(snapshot["history"]), "sha256": sha(payload),
                                  "missing_blobs": []})
        self.assertEqual(json.loads(payload.decode("utf-8")), snapshot)
        self.assertEqual([path.name for path in output.parent.iterdir()], ["snapshot.json"])
        self.assertTrue(payload.startswith(b'{\n "bindings"'), payload[:40])

    def test_write_export_at_an_older_revision_writes_that_revision(self):
        """A pinned older export holds the earlier record list on disk, not the head one."""
        db = self.read()
        superseded = next(v for v in db.all_versions() if v.version > 1)
        before = superseded.revision - 1
        snapshot = export_import.export_snapshot(db, revision=before)
        output = self.work / "exports" / "older.json"
        result = export_import.write_export(db, output=output, revision=before)
        written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written, snapshot)
        self.assertEqual(written["revision"], before)
        self.assertEqual(result["revision"], before)
        self.assertEqual(result["records"], len(snapshot["records"]))
        self.assertEqual(result["blobs"], len(snapshot["blobs"]))
        self.assertEqual(result["sha256"], sha(output.read_bytes()))
        head = export_import.export_snapshot(db)
        self.assertLess(len(written["records"]), len(head["records"]))
        self.assertNotEqual(written["records"], head["records"])

    def test_write_export_replaces_an_earlier_file_leaving_no_staging_copy(self):
        """Writing twice to one path replaces the content and never leaves a .tmp- file behind."""
        db = self.read()
        top = db.max_revision()
        output = self.work / "exports" / "snapshot.json"
        export_import.write_export(db, output=output, revision=1)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["revision"], 1)
        result = export_import.write_export(db, output=output, revision=top)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")),
                         export_import.export_snapshot(db, revision=top))
        self.assertEqual(sorted(path.name for path in output.parent.iterdir()), ["snapshot.json"])
        self.assertEqual(result["sha256"], sha(output.read_bytes()))

    def test_write_export_without_history_reports_none(self):
        """Without history the written file holds no history key and the receipt counts zero."""
        db = self.read()
        output = self.work / "exports" / "head.json"
        result = export_import.write_export(db, output=output)
        self.assertEqual(result["history"], 0)
        self.assertEqual(result["revision"], db.max_revision())
        written = json.loads(output.read_text(encoding="utf-8"))
        self.assertNotIn("history", written)
        self.assertEqual(written, export_import.export_snapshot(db))

    def test_write_export_refuses_a_bad_revision_before_touching_the_disk(self):
        """A rejected revision leaves neither the output file nor its parent folder behind."""
        db = self.read()
        output = self.work / "exports" / "never.json"
        with self.assertRaises(InvalidRequest) as caught:
            export_import.write_export(db, output=output, revision=db.max_revision() + 5)
        self.assertEqual(caught.exception.code, "REVISION_RANGE")
        self.assertFalse(output.exists())
        self.assertFalse(output.parent.exists())

    def test_export_reports_a_blob_the_store_has_lost(self):
        """A damaged blob store is reported in provenance instead of exporting a silent gap.

        The blob row is deleted directly on a throwaway copy: no public command can lose a blob, and
        the point of the test is what the export says when the store is damaged anyway.
        """
        damaged = self.work / "damaged.db"
        shutil.copy2(self.fx.path, damaged)
        with storage.Database(damaged, write=True) as db:
            lost = db.heads("sources")[0].body["blob_sha256"]
            db.conn.execute("DELETE FROM blobs WHERE sha256 = ?", (lost,))
            snapshot = export_import.export_snapshot(db)
            self.assertEqual(snapshot["provenance"]["missing_blobs"], [lost])
            self.assertNotIn(lost, {entry["sha256"] for entry in snapshot["blobs"]})
            self.assertEqual(len(snapshot["blobs"]), len(referenced_blobs(db)) - 1)
            result = export_import.write_export(db, output=self.work / "damaged.json")
            self.assertEqual(result["missing_blobs"], [lost])


class ExportTombstoneTest(TempCase):
    """Export of retired records: tombstones at head, the body and binding still at older revisions.

    One retired record is a ``use`` (never packet-bound) and the other a draft ``check`` (always bound),
    so the export has to drop a real binding rather than one that never existed.
    """

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().complete()
        with self.fx.open() as db:
            created = self.fx.apply(db, [edit("create", "uses", "use_gone", extra_use_body()),
                                         draft_check_edit()],
                                    *support.Fixture.ITEMS, mode="primary")
        with storage.Database(self.fx.path) as db:
            self.live_use = db.head("uses", "use_gone").body
            self.live_check = db.head("checks", "chk_draft").body
            self.live_binding = db.binding("checks", "chk_draft", 1)
        with self.fx.open() as db:
            retired = self.fx.apply(db, [
                {"op": "retire", "collection": "checks", "id": "chk_draft",
                 "expected_version": 1, "reason": "draft withdrawn"},
                {"op": "retire", "collection": "uses", "id": "use_gone",
                 "expected_version": 1, "reason": "the mention is not a dependency"}],
                *support.Fixture.ITEMS, mode="primary")
        self.live_revision = created["revision"]
        self.retire_revision = retired["revision"]

    def test_retired_records_export_as_tombstones(self):
        """At head both retired records are bodiless and no other record has lost its body."""
        with storage.Database(self.fx.path) as db:
            snapshot = export_import.export_snapshot(db)
        self.assertEqual([entry for entry in snapshot["records"] if entry["retired"]],
                         [{"collection": "checks", "id": "chk_draft", "version": 2,
                           "revision": self.retire_revision, "retired": True, "body": None},
                          {"collection": "uses", "id": "use_gone", "version": 2,
                           "revision": self.retire_revision, "retired": True, "body": None}])
        self.assertEqual([entry["id"] for entry in snapshot["records"] if entry["body"] is None],
                         ["chk_draft", "use_gone"])

    def test_a_tombstone_drops_the_binding_the_live_version_carried(self):
        """The retired draft check bound its consumed evidence; at head the export carries no binding for it."""
        records, relations = binding_shape(self.live_binding["bindings"])
        self.assertEqual(records, [("anchors", "anc_lem", 1, "statement"),
                                   ("anchors", "anc_lem_proof", 1, "proof"),
                                   ("anchors", "anc_lem_proof", 1, "source"),
                                   ("arguments", "arg_lem", 1, "proof"),
                                   ("coverage", "cov_lem", 1, "coverage"),
                                   ("groups", "grp_lem", 1, "inference"),
                                   ("items", "itm_lem", 1, "statement"),
                                   ("proof_boundaries", "bnd_lem", 1, "coverage"),
                                   ("scopes", "scp_plain", 1, "scope"),
                                   ("source_reviews", "srv_boundaries", 1, "source"),
                                   ("sources", self.fx.source_id, 1, "source"),
                                   ("target_specs", "tgt_lem", 1, "statement")])
        self.assertEqual([name for name, _, _ in relations],
                         ["coverage_in_argument", "groups_in_argument", "incoming_uses",
                          "parts_of_item", "scopes_in_argument", "target_specs_for_target", "uses_in_group"])
        with storage.Database(self.fx.path) as db:
            head = export_import.export_snapshot(db)
            early = export_import.export_snapshot(db, revision=self.live_revision)
            self.assertIsNone(db.binding("checks", "chk_draft", 2))
        self.assertEqual([b for b in head["bindings"] if b["ref"]["id"] == "chk_draft"], [])
        carried = [b for b in early["bindings"] if b["ref"]["id"] == "chk_draft"]
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["ref"], {"collection": "checks", "id": "chk_draft", "version": 1})
        self.assertEqual(carried[0]["bindings"], self.live_binding["bindings"])
        self.assertEqual(carried[0]["packet_id"], self.live_binding["packet_id"])

    def test_revision_before_the_retirement_still_holds_the_bodies(self):
        """Exporting the revision that created both records returns their live bodies, not tombstones."""
        with storage.Database(self.fx.path) as db:
            early = export_import.export_snapshot(db, revision=self.live_revision)
        entries = {e["id"]: e for e in early["records"] if e["id"] in ("use_gone", "chk_draft")}
        self.assertEqual(entries["use_gone"],
                         {"collection": "uses", "id": "use_gone", "version": 1,
                          "revision": self.live_revision, "retired": False, "body": self.live_use})
        self.assertEqual(entries["use_gone"]["body"]["type"], "definition")
        self.assertEqual(entries["chk_draft"],
                         {"collection": "checks", "id": "chk_draft", "version": 1,
                          "revision": self.live_revision, "retired": False, "body": self.live_check})
        self.assertEqual(entries["chk_draft"]["body"]["state"], "draft")
        self.assertIsNone(entries["chk_draft"]["body"]["outcome"])

    def test_history_keeps_both_the_live_version_and_the_tombstone(self):
        """The history of a retired record is its body followed by the bodiless retirement."""
        with storage.Database(self.fx.path) as db:
            with_history = export_import.export_snapshot(db, history=True)
        self.assertEqual([(e["version"], e["retired"], e["body"])
                          for e in with_history["history"] if e["id"] == "use_gone"],
                         [(1, False, self.live_use), (2, True, None)])
        self.assertEqual([(e["version"], e["retired"], e["body"])
                          for e in with_history["history"] if e["id"] == "chk_draft"],
                         [(1, False, self.live_check), (2, True, None)])


class OverviewMigrationTest(TempCase):
    """migrate_overview on the shipped representer-theorem overview (6 items, 11 uses, 21 anchors)."""

    def setUp(self):
        super().setUp()
        self.example = self.work / "overview-source"
        self.example.mkdir(parents=True)
        for name in ("overview.json", "proof.md"):
            shutil.copy2(OVERVIEW_EXAMPLE / name, self.example / name)
        self.legacy_json = json.loads((self.example / "overview.json").read_text(encoding="utf-8-sig"))
        self.legacy_path = self.work / "legacy" / "overview.db"
        self.legacy_path.parent.mkdir(parents=True)
        self.info = legacy_overview_runtime()._native_init_database(
            self.legacy_path, self.example / "overview.json", source_root=self.example)
        self.original = self.legacy_path.read_bytes()
        self.backup_path = self.work / "legacy" / "overview.backup.db"

    def migrate(self) -> dict:
        return export_import.migrate_overview(self.legacy_path, backup=self.backup_path)

    def test_fixture_is_the_documented_legacy_overview(self):
        """The shipped example still holds 6 items, 11 uses, 21 anchors and 17 observations."""
        self.assertEqual({name: len(self.legacy_json[name])
                          for name in ("items", "uses", "anchors", "observations")},
                         {"items": 6, "uses": 11, "anchors": 21, "observations": 17})
        self.assertEqual(self.info["items"], 6)
        self.assertEqual(self.info["uses"], 11)

    def test_new_core_refuses_a_legacy_overview_database(self):
        """Opening an unmigrated overview is INCOMPATIBLE, names the format and changes no byte."""
        for write in (False, True):
            with self.subTest(write=write):
                with self.assertRaises(IncompatibleError) as caught:
                    storage.Database(self.legacy_path, write=write)
                self.assertEqual(caught.exception.code, "INCOMPATIBLE")
                self.assertEqual(caught.exception.exit_code, 4)
                self.assertEqual(caught.exception.records,
                                 [{"format": LEGACY_OVERVIEW_FORMAT, "schema_version": None}])
                self.assertIn("migrate-overview", caught.exception.message)
        self.assertEqual(self.legacy_path.read_bytes(), self.original)

    def test_migration_rebuilds_the_database_in_place(self):
        """The migrated file is a format-3 database holding the legacy items, uses and anchors."""
        result = self.migrate()
        self.assertEqual(result["counts"], OVERVIEW_COUNTS)
        self.assertEqual(result["remapped"], [])
        self.assertEqual(result["limitations"], [])
        self.assertEqual(result["legacy"], {"format": LEGACY_OVERVIEW_FORMAT,
                                            "snapshot_id": self.info["snapshot_id"],
                                            "snapshots": 1, "builds": 0})
        self.assertEqual(result["database"], str(self.legacy_path))
        # The transactional cutover removes its temporary conversion file.
        self.assertEqual(sorted(path.name for path in self.legacy_path.parent.iterdir()),
                         ["overview.backup.db", "overview.db"])
        with storage.Database(self.legacy_path) as db:
            metadata = db.check_compatibility()
            self.assertEqual(metadata["storage_format"], "4")
            self.assertEqual(metadata["contract_version"], "4")
            self.assertEqual(result["revision"], db.max_revision())
            self.assertEqual(result["paper_id"], storage.paper_record(db).id)
            self.assertEqual(sorted(item.id for item in db.heads("items")),
                             sorted(item["id"] for item in self.legacy_json["items"]))
            self.assertEqual(sorted(use.id for use in db.heads("uses")),
                             sorted(use["id"] for use in self.legacy_json["uses"]))
            self.assertEqual(sorted(anchor.id for anchor in db.heads("anchors")),
                             sorted(anchor["id"] for anchor in self.legacy_json["anchors"]))
            self.assertEqual(len(db.heads("items")), 6)
            self.assertEqual(len(db.heads("uses")), 11)

    def test_migration_keeps_item_kinds_uses_and_the_paper_record(self):
        """Item kinds, use endpoints and the paper title and main items survive the migration."""
        self.migrate()
        with storage.Database(self.legacy_path) as db:
            items = {item.id: item.body for item in db.heads("items")}
            self.assertEqual({iid: body["kind"] for iid, body in items.items()},
                             {item["id"]: item["kind"] for item in self.legacy_json["items"]})
            self.assertEqual({iid: body["label"] for iid, body in items.items()},
                             {item["id"]: item["label"] for item in self.legacy_json["items"]})
            # an overview records a synopsis of each statement, never a verbatim transcription
            self.assertEqual({body["statement"]["form"] for body in items.values()}, {"synopsis"})
            uses = {use.id: use.body for use in db.heads("uses")}
            self.assertEqual({uid: (body["from"]["id"], body["to"]["id"], body["type"])
                              for uid, body in uses.items()},
                             {use["id"]: (use["from"], use["to"], use["type"])
                              for use in self.legacy_json["uses"]})
            paper = storage.paper_record(db)
            self.assertEqual(paper.body["title"], self.legacy_json["title"])
            self.assertEqual(paper.body["main_items"], self.legacy_json["main_items"])

    def test_migration_keeps_every_anchor_as_an_exact_line_span(self):
        """Each of the 21 anchors keeps its excerpt, its digest and its line span, with no limitation."""
        self.migrate()
        legacy = {anchor["id"]: anchor for anchor in self.legacy_json["anchors"]}
        with storage.Database(self.legacy_path) as db:
            anchors = {anchor.id: anchor.body for anchor in db.heads("anchors")}
            source = db.heads("sources")[0]
        self.assertEqual(set(anchors), set(legacy))
        self.assertEqual(len(anchors), 21)
        for aid, body in anchors.items():
            old = legacy[aid]
            with self.subTest(anchor=aid):
                self.assertEqual(body["method"], "exact_lines")
                self.assertIsNone(body["limitation"])
                self.assertEqual(body["source_id"], source.id)
                self.assertEqual(body["source_version"], source.version)
                self.assertEqual(body["excerpt"], old["excerpt"])
                self.assertEqual(body["excerpt_sha256"], old["excerpt_hash"])
                self.assertEqual((body["locator"]["start_line"], body["locator"]["end_line"]),
                                 (old["locator"]["start_line"], old["locator"]["end_line"]))

    def test_migration_keeps_use_targeted_observations(self):
        """All 17 comparison observations survive, including the 11 that judge a use rather than an item."""
        self.migrate()
        legacy = {obs["id"]: obs for obs in self.legacy_json["observations"]}
        with storage.Database(self.legacy_path) as db:
            observations = {obs.id: obs.body for obs in db.heads("observations")}
            live_uses = {use.id for use in db.heads("uses")}
            live_items = {item.id for item in db.heads("items")}
        self.assertEqual(set(observations), set(legacy))
        use_targeted = {oid for oid, body in observations.items()
                        if body["target"]["collection"] == "uses"}
        self.assertEqual(use_targeted, {oid for oid, obs in legacy.items()
                                        if obs["target"]["collection"] == "uses"})
        self.assertEqual(len(use_targeted), 11)
        self.assertEqual(len(observations) - len(use_targeted), 6)
        for oid, body in observations.items():
            self.assertEqual(body["target"]["id"], legacy[oid]["target"]["id"])
            self.assertEqual(body["result"], legacy[oid]["result"])
            self.assertEqual(body["reviewer"], legacy[oid]["reviewer"])
            # created_at and input_snapshot have no contract-3 field; the note carries them
            expected_note = (f"[legacy created_at {legacy[oid]['created_at']}] "
                             f"[legacy input_snapshot {legacy[oid]['input_snapshot']}] {legacy[oid]['note']}")
            self.assertEqual(body["note"], expected_note.strip())
            pool = live_uses if body["target"]["collection"] == "uses" else live_items
            self.assertIn(body["target"]["id"], pool)

    def test_migration_records_its_provenance(self):
        """One identity map covers every imported record and the legacy snapshot stays in metadata."""
        result = self.migrate()
        expected_entries = sum(OVERVIEW_COUNTS.values())
        with storage.Database(self.legacy_path) as db:
            maps = db.heads("identity_maps")
            self.assertEqual([record.id for record in maps], [result["identity_map"]])
            body = maps[0].body
            self.assertEqual(body["reason"], "import")
            self.assertEqual(body["reviewer"], "migrate-overview")
            self.assertEqual(len(body["entries"]), expected_entries)
            self.assertIn(self.info["snapshot_id"], body["note"])
            self.assertEqual({entry["old"].split(":", 1)[0] for entry in body["entries"]},
                             {name for name, count in OVERVIEW_COUNTS.items() if count})
            # the identity map keeps the whole legacy export, so the migration can be audited later
            carried = json.loads(db.get_blob(body["source_blob"]).decode("utf-8"))
            self.assertEqual(carried["format"], LEGACY_OVERVIEW_FORMAT)
            self.assertEqual(carried["snapshot_id"], self.info["snapshot_id"])
            self.assertEqual([obs["id"] for obs in carried["observations"]],
                             [obs["id"] for obs in self.legacy_json["observations"]])
            metadata = {row["key"]: row["value"]
                        for row in db.conn.execute("SELECT key, value FROM metadata")}
            source = db.heads("sources")[0]
            self.assertEqual(source.body["path"], "proof.md")
            self.assertEqual(source.body["capture_method"], "legacy_overview_import")
            self.assertEqual(source.body["media_type"], "text")
            self.assertEqual(db.get_blob(source.body["blob_sha256"]),
                             (self.example / "proof.md").read_bytes())
            snapshot = export_import.export_snapshot(db)
        self.assertEqual(metadata["legacy_overview_format"], LEGACY_OVERVIEW_FORMAT)
        self.assertEqual(metadata["legacy_overview_current_snapshot"], self.info["snapshot_id"])
        self.assertEqual(json.loads(metadata["legacy_overview_snapshot_ids"]), [self.info["snapshot_id"]])
        self.assertEqual(json.loads(metadata["legacy_overview_backup"]), result["backup"])
        self.assertNotIn("missing_blobs", snapshot["provenance"])
        self.assertEqual(len(snapshot["records"]), expected_entries + 3)  # paper, identity map, selection

    def test_backup_holds_the_original_legacy_database(self):
        """The backup written before the rebuild is row-for-row the database that was migrated."""
        result = self.migrate()
        pristine = self.work / "pristine.db"
        pristine.write_bytes(self.original)
        self.assertEqual(legacy_tables(self.backup_path), legacy_tables(pristine))
        self.assertEqual(result["backup"], {"path": str(self.backup_path),
                                            "sha256": sha(self.backup_path.read_bytes())})

    def test_second_migration_reports_already_migrated_and_writes_nothing(self):
        """Re-running the command on a migrated file is refused before any backup is taken."""
        self.migrate()
        migrated = self.legacy_path.read_bytes()
        second_backup = self.work / "legacy" / "second.backup.db"
        with self.assertRaises(InvalidRequest) as caught:
            export_import.migrate_overview(self.legacy_path, backup=second_backup)
        self.assertEqual(caught.exception.code, "ALREADY_MIGRATED")
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertFalse(second_backup.exists())
        self.assertEqual(self.legacy_path.read_bytes(), migrated)
        self.assertEqual(sorted(path.name for path in self.legacy_path.parent.iterdir()),
                         ["overview.backup.db", "overview.db"])

    def test_backup_collision_is_refused_and_the_legacy_file_is_untouched(self):
        """An existing backup path is never overwritten, and the legacy database stays readable."""
        self.backup_path.write_bytes(b"an earlier backup")
        with self.assertRaises(InvalidRequest) as caught:
            self.migrate()
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("refusing to overwrite", caught.exception.message)
        self.assertEqual(self.backup_path.read_bytes(), b"an earlier backup")
        self.assertEqual(self.legacy_path.read_bytes(), self.original)
        self.assertEqual(legacy_tables(self.legacy_path)["current_snapshot"],
                         [(1, self.info["snapshot_id"])])

    def test_missing_database_is_refused(self):
        """A path that is not a file is refused before a backup is created."""
        missing = self.work / "legacy" / "absent.db"
        with self.assertRaises(InvalidRequest) as caught:
            export_import.migrate_overview(missing, backup=self.backup_path)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("database not found", caught.exception.message)
        self.assertFalse(self.backup_path.exists())

    def test_a_file_that_is_not_a_database_is_refused(self):
        """Junk bytes are INCOMPATIBLE, not a crash, and leave no backup behind."""
        junk = self.work / "legacy" / "junk.db"
        junk.write_bytes(b"not a database at all")
        with self.assertRaises(IncompatibleError) as caught:
            export_import.migrate_overview(junk, backup=self.backup_path)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE")
        self.assertEqual(caught.exception.exit_code, 4)
        self.assertFalse(self.backup_path.exists())
        self.assertEqual(junk.read_bytes(), b"not a database at all")


class LegacyAuditImportTest(TempCase):
    """import_legacy on the shipped stat-paper-proofcheck v1.5 reference audit."""

    def setUp(self):
        super().setUp()
        self.folder = self.legacy_audit_copy()
        self.db_path = self.work / "imported.db"
        self.mapping_path = self.work / "mapping" / "identity.json"
        self.artifact_path = self.mapping_path.with_name("identity.import-artifact.json")

    def run_import(self) -> dict:
        return export_import.import_legacy(self.folder, db_path=self.db_path,
                                           mapping_path=self.mapping_path)

    def test_import_creates_the_documented_record_population(self):
        """The reference audit imports as 2 items, 2 arguments, 4 checks, 1 finding and 1 use."""
        result = self.run_import()
        self.assertEqual(result["counts"], LEGACY_AUDIT_COUNTS)
        self.assertEqual(result["remapped"], [])
        self.assertEqual(result["limitations"], [])
        with storage.Database(self.db_path) as db:
            counts = {collection: len(db.heads(collection))
                      for collection in sorted(set(LEGACY_AUDIT_COUNTS) | {"sources", "papers"})}
            self.assertEqual(counts, dict(LEGACY_AUDIT_COUNTS, sources=1, papers=1))
            self.assertEqual(sorted((item.id, item.body["kind"]) for item in db.heads("items")),
                             [("lem-growing-max", "lemma"), ("thm-main", "theorem")])
            self.assertEqual(sorted((item.id, tuple(item.body["aliases"]))
                                    for item in db.heads("items")),
                             [("lem-growing-max", ("lem:growing-max",)), ("thm-main", ("thm:main",))])
            self.assertEqual(storage.paper_record(db).body["main_items"],
                             ["lem-growing-max", "thm-main"])
            self.assertEqual(result["revision"], db.max_revision())

    def test_imported_audit_is_a_triage_audit_over_both_items(self):
        """The legacy audit becomes one triage audit under the legacy protocol, with no independence."""
        result = self.run_import()
        with storage.Database(self.db_path) as db:
            audits = db.heads("audits")
            self.assertEqual([audit.id for audit in audits], [result["audit_id"]])
            body = audits[0].body
        self.assertEqual(body["mode"], "triage")
        self.assertEqual(body["protocol_version"], export_import.LEGACY_AUDIT_PROTOCOL)
        self.assertEqual(body["protocol_version"], "stat-paper-proofcheck/1.5-ledger")
        self.assertIs(body["independent_required"], False)
        self.assertIsNone(body["qualification_id"])
        self.assertEqual(body["targets"], [R("items", "lem-growing-max"), R("items", "thm-main")])
        self.assertEqual(body["global_tasks"], [])

    def test_imported_checks_keep_the_primary_and_independent_roles(self):
        """Each ledger yields a primary composition check and a legacy challenger check, both refuted."""
        self.run_import()
        with storage.Database(self.db_path) as db:
            checks = db.heads("checks")
            arguments = {argument.id for argument in db.heads("arguments")}
            responses = {response.id for response in db.heads("responses")}
            self.assertEqual(len(checks), 4)
            by_role = {}
            for check in checks:
                by_role.setdefault(check.body["role"], []).append(check.body)
            self.assertEqual(sorted(by_role), ["independent", "primary"])
            for role, bodies in by_role.items():
                self.assertEqual(len(bodies), 2, role)
                for body in bodies:
                    self.assertEqual(body["kind"], "composition")
                    self.assertEqual(body["state"], "complete")
                    self.assertEqual(body["outcome"], "refuted")
                    self.assertEqual(body["protocol_version"], export_import.LEGACY_AUDIT_PROTOCOL)
                    self.assertEqual(body["target"]["collection"], "arguments")
                    self.assertIn(body["target"]["id"], arguments)
            # every argument is covered by exactly one check of each role
            self.assertEqual(sorted(body["target"]["id"] for body in by_role["primary"]),
                             sorted(arguments))
            self.assertEqual(sorted(body["target"]["id"] for body in by_role["independent"]),
                             sorted(arguments))
            self.assertEqual({body["reviewer"] for body in by_role["primary"]}, {"legacy-ledger"})
            self.assertEqual({body["reviewer"] for body in by_role["independent"]}, {"legacy-challenger"})
            self.assertEqual([body["response_id"] for body in by_role["primary"]], [None, None])
            self.assertEqual({body["response_id"] for body in by_role["independent"]}, responses)

    def test_the_legacy_qualification_is_marked_unqualified(self):
        """The challenger has no item-audit/1 calibration, so the imported qualification says so."""
        self.run_import()
        with storage.Database(self.db_path) as db:
            qualifications = db.heads("qualifications")
        self.assertEqual(len(qualifications), 1)
        body = qualifications[0].body
        self.assertEqual(body["reviewer"], "legacy-challenger")
        self.assertIs(body["qualified"], False)
        self.assertEqual(body["protocol_version"], export_import.LEGACY_AUDIT_PROTOCOL)
        self.assertEqual(body["profile"]["provider"], "legacy")
        self.assertEqual(body["profile"]["context_isolation"], "fresh_context_same_model")
        self.assertEqual(body["valid_case_results"], [])
        self.assertEqual(body["invalid_case_results"], [])
        self.assertEqual(body["limitations"],
                         ["legacy challenger; no item-audit/1 calibration cases exist"])

    def test_triage_keeps_historical_verdicts_without_current_correctness_credit(self):
        """Imported verdicts stay inspectable while triage makes no proof-correctness claim."""
        result = self.run_import()
        with storage.Database(self.db_path) as db:
            derived = assessment.derive_assessment(db, revision=db.max_revision(),
                                                   audit_id=result["audit_id"])
        public = {ref: projection.public_assessment(value)
                  for ref, value in derived["assessments"].items()}
        by_collection = {}
        for ref in public:
            by_collection.setdefault(ref.split(":", 1)[0], []).append(ref)
        self.assertEqual({name: len(refs) for name, refs in by_collection.items()},
                         {"items": 2, "arguments": 2, "uses": 1, "audits": 1})
        self.assertEqual(sorted(by_collection["items"]), ["items:lem-growing-max", "items:thm-main"])
        self.assertEqual(by_collection["uses"], ["uses:thm-main-D001"])
        expected = {ref: ("gray", "triage") for ref in public}
        self.assertEqual({ref: (value["state"], value["label"]) for ref, value in public.items()},
                         expected)
        self.assertEqual(derived["progress"],
                         {"completed_current_obligations": 0, "draft_checks": 0, "major_results": 2,
                          "process_complete": False, "required_obligations": 3, "source_unbound_items": 0})
        # Imported arguments remain drafts. Their recorded defects are visible,
        # but they do not invent registered proof routes for current completion.
        self.assertEqual(derived["problems"], [
            "register establishment for items:lem-growing-max: no exact registered proof route or local group",
            "register establishment for items:thm-main: no exact registered proof route or local group",
        ])

    def test_the_legacy_issue_becomes_one_finding(self):
        """The single issue-log entry imports as an open statement refutation citing both lemma checks."""
        self.run_import()
        with storage.Database(self.db_path) as db:
            findings = db.heads("findings")
            uses = db.heads("uses")
            arguments = {argument.id: argument.body for argument in db.heads("arguments")}
            checks = {check.id: check.body for check in db.heads("checks")}
        self.assertEqual(len(findings), 1)
        body = findings[0].body
        self.assertEqual(findings[0].id, "I-001")
        self.assertEqual(body["category"], "statement_refutation")
        self.assertEqual(body["lifecycle"], "open")
        self.assertEqual(body["target"], R("items", "lem-growing-max"))
        self.assertEqual(body["affected_uses"], [uses[0].id])
        self.assertIsNone(body["resolution"])
        # the finding cites the primary and the independent check of the lemma argument, in that order
        argument_id = next(aid for aid, argument in arguments.items()
                           if argument["target"] == R("items", "lem-growing-max"))
        by_role = {check["role"]: cid for cid, check in checks.items()
                   if check["target"]["id"] == argument_id}
        self.assertEqual(sorted(by_role), ["independent", "primary"])
        self.assertEqual(body["check_refs"],
                         [{"collection": "checks", "id": by_role["primary"], "version": 1},
                          {"collection": "checks", "id": by_role["independent"], "version": 1}])
        self.assertEqual(len(uses), 1)
        self.assertEqual(uses[0].id, "thm-main-D001")
        self.assertEqual(uses[0].body["from"], R("items", "lem-growing-max"))
        self.assertEqual(uses[0].body["to"], R("items", "thm-main"))
        self.assertEqual(uses[0].body["type"], "dependency")

    def test_import_writes_a_mapping_file_and_its_artifact(self):
        """The mapping file mirrors the stored identity map and names an artifact that exists on disk."""
        result = self.run_import()
        mapping = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        with storage.Database(self.db_path) as db:
            maps = db.heads("identity_maps")
            self.assertEqual(len(maps), 1)
            stored = maps[0]
        self.assertEqual(mapping["identity_map_id"], stored.id)
        self.assertEqual(mapping["entries"], stored.body["entries"])
        self.assertEqual(mapping["source_blob"], stored.body["source_blob"])
        self.assertEqual(mapping["reason"], "import")
        self.assertEqual(mapping["reviewer"], "import-legacy")
        self.assertEqual(mapping["import_artifact"], result["import_artifact"])
        self.assertEqual(mapping["import_artifact"]["path"], str(self.artifact_path))
        self.assertEqual(sha(self.artifact_path.read_bytes()), stored.body["source_blob"])
        artifact = json.loads(self.artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(artifact["kind"], "stat-paper-proofcheck-legacy-import")
        self.assertEqual(artifact["folder"], self.folder.name)

    def test_import_does_not_touch_the_legacy_folder(self):
        """The audit folder is read-only input: every file keeps its bytes."""
        before = {path.relative_to(self.folder).as_posix(): sha(path.read_bytes())
                  for path in sorted(self.folder.rglob("*")) if path.is_file()}
        self.run_import()
        after = {path.relative_to(self.folder).as_posix(): sha(path.read_bytes())
                 for path in sorted(self.folder.rglob("*")) if path.is_file()}
        self.assertEqual(before, after)
        # the comparison is only meaningful if the files the importer actually reads were in it
        for name in LEGACY_AUDIT_SAMPLE_FILES:
            self.assertIn(name, before)

    def test_re_running_the_import_is_refused_and_writes_no_second_mapping(self):
        """A second import into the same database path is refused; no mapping or artifact appears."""
        self.run_import()
        first = self.db_path.read_bytes()
        mapping = self.mapping_path.read_bytes()
        second_mapping = self.work / "mapping" / "again.json"
        with self.assertRaises(InvalidRequest) as caught:
            export_import.import_legacy(self.folder, db_path=self.db_path,
                                        mapping_path=second_mapping)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("refusing to overwrite", caught.exception.message)
        self.assertFalse(second_mapping.exists())
        self.assertFalse(second_mapping.with_name("again.import-artifact.json").exists())
        self.assertEqual(self.db_path.read_bytes(), first)
        self.assertEqual(self.mapping_path.read_bytes(), mapping)
        self.assertEqual(sorted(path.name for path in self.mapping_path.parent.iterdir()),
                         ["identity.import-artifact.json", "identity.json"])

    def test_an_existing_mapping_path_is_refused_before_the_database_is_created(self):
        """The mapping file is checked first, so a refused import leaves no half-built database."""
        self.run_import()
        other = self.work / "other.db"
        with self.assertRaises(InvalidRequest) as caught:
            export_import.import_legacy(self.folder, db_path=other, mapping_path=self.mapping_path)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("existing mapping file", caught.exception.message)
        self.assertFalse(other.exists())

    def test_a_missing_audit_folder_is_refused(self):
        """A folder that does not exist is refused before anything is written."""
        with self.assertRaises(InvalidRequest) as caught:
            export_import.import_legacy(self.work / "absent", db_path=self.db_path,
                                        mapping_path=self.mapping_path)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertIn("legacy audit folder not found", caught.exception.message)
        self.assertFalse(self.db_path.exists())
        self.assertFalse(self.mapping_path.exists())

    def test_imported_database_exports_with_every_blob(self):
        """The imported database is a complete export source: ledgers and responses travel with it."""
        self.run_import()
        with storage.Database(self.db_path) as db:
            snapshot = export_import.export_snapshot(db)
            carried = {entry["sha256"]: base64.b64decode(entry["data"]) for entry in snapshot["blobs"]}
            self.assertEqual(set(carried), referenced_blobs(db))
            self.assertNotIn("missing_blobs", snapshot["provenance"])
            self.assertEqual(snapshot["records"],
                             plain_envelopes(db.records_at(db.max_revision(), include_retired=True)))
            responses = db.heads("responses")
            self.assertEqual(len(responses), 2)
            for response in responses:
                blob = response.body["original_blob"]
                self.assertEqual(carried[blob], db.get_blob(blob))
                self.assertEqual(sha(carried[blob]), blob)
                self.assertEqual(response.body["state"], "accepted")
                self.assertEqual(response.body["exposure"], "source_only")


if __name__ == "__main__":
    unittest.main()
