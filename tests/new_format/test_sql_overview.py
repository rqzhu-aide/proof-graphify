"""Common-store continuation and offline native conversion regressions."""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
import unittest
from unittest import mock

from support import OVERVIEW, TempCase, write_json

sys.path.insert(0, str(OVERVIEW / "scripts"))
import paper_database as overview_cli
import paper_records
from paper_core import acceptance, contract, export_import, overview, packets, sources, storage
from paper_core.canonical import digest
from paper_core.errors import IncompatibleError, InvalidRequest


class SQLOverviewTest(TempCase):
    def setUp(self):
        super().setUp()
        # This lane integrates both adapters against the maintained shared core.
        # Installed-package selection is tested separately in the overview's
        # test_standalone_packaging.py using clean subprocesses and copied bundles.
        core = mock.patch.object(overview_cli, "_common_core", return_value=(
            overview, storage.Database, storage.initialize, storage.paper_record))
        core.start()
        self.addCleanup(core.stop)
        self.source = self.path("paper.tex")
        self.source.write_text("Lemma A: x is nonnegative.\nTheorem T: x+1 is positive.\nUse Lemma A in T.\n", encoding="utf-8")
        self.seed = write_json(self.path("seed.json"), {
            "schema_version": 3, "title": "Selected paper", "scope": "Two statements", "main_items": ["T"],
            "source": {"title": "Paper", "file": "paper.tex"},
            "items": [{"id": identity, "kind": kind, "label": identity, "caption": identity,
                       "statement": {"text": statement, "form": "synopsis"},
                       "source": {"start_line": line, "end_line": line}}
                      for identity, kind, statement, line in (("A", "lemma", "x is nonnegative", 1),
                                                               ("T", "theorem", "x+1 is positive", 2))],
            "uses": [{"id": "uAT", "from": "A", "to": "T", "reason": "Add one to the bound",
                      "source": {"start_line": 3, "end_line": 3}}]})
        self.db = self.path("paper.db")

    def create(self, native=False, audit=False):
        if audit:
            # This test adds audit-owned extensions. Start a fresh audit store
            # explicitly rather than promoting an overview database's protocol.
            data = overview_cli._normalize_dataset(self.seed, (), self.work)
            storage.initialize(self.db, source_root=self.work, title=data["title"], workflow="audit")
            with storage.Database(self.db, write=True, write_scope="overview") as db:
                db.begin_immediate()
                overview.update(db, {"observations": []}, data, profile="focused")
                db.commit()
            return {"snapshot_id": paper_records.snapshot_digest(data)}
        init = overview_cli._native_init_database if native else overview_cli.init_database
        return init(self.db, self.seed, focused=True)

    def compare(self, result="matched"):
        data = overview_cli.export_snapshot(self.db)
        return overview_cli.compare_records(self.db, {"expected_snapshot": data["snapshot_id"],
            "targets": [{"collection": "items", "id": "T"}, {"collection": "uses", "id": "uAT"}],
            "reviewer": "reader", "result": result, "note": "Compared saved statements and their incoming contribution"})

    def test_proof_idea_seed_capture_refresh_and_portable_reimport(self):
        seed = json.loads(self.seed.read_text(encoding="utf-8"))
        idea = "Use Lemma A to bound x below by zero. Adding one makes the conclusion strict."
        seed["items"][1]["proof_idea"] = idea
        write_json(self.seed, seed)
        self.create()
        self.compare()
        before = overview_cli.export_snapshot(self.db)
        with storage.Database(self.db) as db:
            self.assertEqual(db.head("items", "T").body["proof_idea"], idea)
            exported = export_import.export_snapshot(db)
            row = next(r for r in exported["records"] if r["collection"] == "items" and r["id"] == "T")
            self.assertEqual(row["body"]["proof_idea"], idea)
        captured = write_json(self.path("captured-idea.json"), before)
        portable = self.path("portable-idea.db")
        overview_cli.init_database(portable, captured, focused=True, source_root=self.work)
        self.assertEqual(overview_cli.export_snapshot(portable), before)
        self.assertEqual(overview_cli.get_packet(portable, "T")["target_fidelity"], "matched")
        self.source.write_text(self.source.read_text(encoding="utf-8") + "% source revision\n", encoding="utf-8")
        overview_cli.refresh_database(self.db, before["snapshot_id"])
        after = overview_cli.export_snapshot(self.db)
        self.assertEqual(after["items"][1]["proof_idea"], idea)
        self.assertEqual(after["observations"], before["observations"])
        self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "stale")
        self.assertEqual(overview_cli.export_snapshot(self.db, before["snapshot_id"]), before)

    def test_proof_idea_edit_and_omission_preserve_audit_extensions_and_history(self):
        self.create(audit=True)
        with storage.Database(self.db, write=True) as db:
            item = db.head("items", "T")
            scope = {"argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
                     "conditions": ["x is nonnegative"], "evidence_refs": []}
            edits = [{"op": "create", "collection": "scopes", "id": "scope-T", "expected_version": None, "body": scope},
                     {"op": "replace", "collection": "items", "id": "T", "expected_version": item.version,
                      "body": dict(item.body, scope_id="scope-T")}]
            packet = packets.get_packet(db, targets=[storage.paper_record(db).ref, item.ref], mode="author")
            acceptance.apply_batch(db, {"contract_version": 4, "request_id": "scope-extension",
                "packet_id": packet["packet_id"], "edits": edits})
        self.compare()
        before = overview_cli.export_snapshot(self.db)
        item = dict(before["items"][1], proof_idea="Apply the lower bound. Then add one.")
        overview_cli.apply_edits(self.db, {"expected_snapshot": before["snapshot_id"], "edits": [
            {"collection": "items", "op": "upsert", "id": "T", "record": item}]})
        added = overview_cli.export_snapshot(self.db)
        self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "stale")
        self.assertEqual(overview_cli.export_snapshot(self.db, before["snapshot_id"]), before)
        self.compare()
        del item["proof_idea"]
        item["caption"] = "Positive after adding one"
        overview_cli.apply_edits(self.db, {"expected_snapshot": added["snapshot_id"], "edits": [
            {"collection": "items", "op": "upsert", "id": "T", "record": item}]})
        after = overview_cli.export_snapshot(self.db)
        self.assertNotIn("proof_idea", after["items"][1])
        self.assertEqual(len(after["observations"]), 4)
        retained = overview_cli.get_packet(self.db, "T", added["snapshot_id"])
        self.assertEqual(retained["item"]["proof_idea"], added["items"][1]["proof_idea"])
        self.assertEqual(retained["target_fidelity"], "matched")
        with storage.Database(self.db) as db:
            current = db.head("items", "T").body
            self.assertNotIn("proof_idea", current)
            self.assertEqual((current["scope_id"], current["origin"]), ("scope-T", "source"))
            self.assertEqual(db.head("scopes", "scope-T").body, scope)
            historical = export_import.export_snapshot(db, history=True)["history"]
            self.assertTrue(any(r["collection"] == "items" and r["id"] == "T" and "proof_idea" in r["body"]
                                for r in historical))

    def test_shared_proof_idea_change_stales_own_and_downstream_comparisons(self):
        self.create(audit=True)
        data = overview_cli.export_snapshot(self.db)
        overview_cli.compare_records(self.db, {"expected_snapshot": data["snapshot_id"],
            "targets": [{"collection": c, "id": row["id"]} for c in ("items", "uses") for row in data[c]],
            "reviewer": "reader", "note": "Compared the saved statements and contribution"})
        before = overview_cli.export_snapshot(self.db)
        with storage.Database(self.db, write=True) as db:
            item = db.head("items", "A")
            edits = [{"op": "replace", "collection": "items", "id": "A", "expected_version": item.version,
                      "body": dict(item.body, proof_idea="Apply the hypothesis to obtain the lower bound.")}]
            packet = packets.get_packet(db, targets=[item.ref], mode="author")
            acceptance.apply_batch(db, {"contract_version": 4, "request_id": "shared-idea",
                "packet_id": packet["packet_id"], "edits": edits})
        after = overview_cli.export_snapshot(self.db)
        self.assertIn("proof_idea", after["items"][0])
        self.assertEqual(after["observations"], before["observations"])
        self.assertEqual(set(paper_records.fidelity_by_row(after).values()), {"stale"})
        for collection in ("items", "uses"):
            for row in after[collection]:
                self.assertNotEqual(paper_records.target_digest(before, collection, row["id"]),
                                    paper_records.target_digest(after, collection, row["id"]))
                self.assertEqual(paper_records.target_digest(after, collection, row["id"]),
                                 export_import._overview_target_digest(after, collection, row["id"]))
        changes = overview_cli.changes_database(self.db, before["snapshot_id"])
        self.assertIn("T", [r["id"] for r in changes["potentially_affected"]])
        self.assertEqual(changes["reuse_candidates"], [])

    def test_proof_idea_native_migration_retains_field_and_current_comparison(self):
        seed = json.loads(self.seed.read_text(encoding="utf-8"))
        seed["items"][1]["proof_idea"] = "Use Lemma A for nonnegativity. Add one to finish."
        write_json(self.seed, seed)
        self.create(native=True)
        self.compare()
        before = overview_cli.export_snapshot(self.db)
        export_import.migrate_overview(self.db, backup=self.path("idea-native-backup.db"))
        self.assertEqual(overview_cli.export_snapshot(self.db), before)
        self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "matched")
        with storage.Database(self.db) as db:
            self.assertEqual(db.head("items", "T").body["proof_idea"], seed["items"][1]["proof_idea"])

    def test_optional_proof_idea_shared_contract_is_nonempty_text(self):
        self.create()
        with storage.Database(self.db) as db:
            original = db.head("items", "T").body
        self.assertEqual(contract.validate_body("items", original), [])
        self.assertEqual(contract.validate_body("items", dict(original, proof_idea="Use the saved lower bound.")), [])
        for value in (None, "", " \t\n", 1, [], {}):
            with self.subTest(value=value):
                errors = contract.validate_body("items", dict(original, proof_idea=value))
                self.assertTrue(errors)
                self.assertTrue(all("proof_idea" in error for error in errors))

    def test_init_and_ordinary_continuation(self):
        info = self.create()
        with storage.Database(self.db) as db:
            self.assertEqual(db.metadata["storage_format"], "4")
            self.assertEqual(db.head("overview_selections", overview.SELECTION_ID).body["main_item_ids"], ["T"])
        self.compare()
        packet = overview_cli.get_packet(self.db, "T")
        self.assertEqual(packet["target_fidelity"], "matched")
        item = copy.deepcopy(packet["item"])
        item["caption"] = "New caption"
        updated = overview_cli.apply_edits(self.db, {"expected_snapshot": packet["expected_snapshot"],
            "edits": [{"collection": "items", "op": "upsert", "id": "T", "record": item}]})
        self.assertNotEqual(info["snapshot_id"], updated["snapshot_id"])
        changes = overview_cli.changes_database(self.db, info["snapshot_id"])
        self.assertEqual(changes["to_snapshot"], updated["snapshot_id"])
        self.assertTrue(overview_cli.validate_database(self.db)["valid"])
        self.assertIn("counts", overview_cli.candidates_database(self.db))
        overview_cli.export_database(self.db, self.path("overview.json"))
        overview_cli.backup_database(self.db, self.path("backup.db"))
        with storage.Database(self.path("backup.db")) as backup:
            self.assertEqual(backup.head("items", "T").body["caption"], "New caption")
        with self.assertRaisesRegex(overview_cli.DatabaseError, "outside focused"):
            overview_cli.scaffold_audits(self.db, self.path("audits"))

    def test_unselected_audit_content_does_not_expand_selection_or_comparison(self):
        self.create(audit=True)
        self.compare()
        with storage.Database(self.db, write=True) as db:
            item = copy.deepcopy(db.head("items", "A").body)
            item.update(label="U", caption="Unselected", statement={"text": "Unused", "form": "synopsis"})
            source = db.heads("sources")[0]
            source_body = dict(source.body, path="audit-only.txt")
            edits = [{"op": "create", "collection": "items", "id": "U", "expected_version": None, "body": item},
                     {"op": "create", "collection": "sources", "id": "audit-source", "expected_version": None, "body": source_body}]
            acceptance.accept(db, request_id="add-audit", request_digest=digest(edits), packet_id=None, edits=edits, command="import")
        data = overview_cli.export_snapshot(self.db)
        self.assertEqual([i["id"] for i in data["items"]], ["A", "T"])
        self.assertEqual(len(data["source_revision"]["files"]), 1)
        self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "matched")
        overview_cli.apply_edits(self.db, {"expected_snapshot": data["snapshot_id"], "edits": [
            {"op": "remove", "collection": "uses", "id": "uAT"}]})
        with storage.Database(self.db) as db:
            self.assertIsNotNone(db.head("uses", "uAT"))
            self.assertIsNotNone(db.head("items", "U"))

    def test_native_migration_preserves_exact_broad_observations_and_root(self):
        self.create(native=True)
        self.compare()
        self.compare("needs_attention")
        before = overview_cli.export_snapshot(self.db)
        receipt = export_import.migrate_overview(self.db, backup=self.path("native-backup.db"))
        after = overview_cli.export_snapshot(self.db)
        self.assertEqual(before, after)
        self.assertEqual(receipt["counts"]["observations"], 4)
        self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "needs_attention")
        with storage.Database(self.db) as db:
            self.assertEqual(storage.paper_record(db).body["source_root"], self.work.resolve().as_posix())

    def test_native_archive_is_retained_through_acceptance_and_reselection(self):
        self.create(native=True)
        self.compare("needs_attention")
        original = overview_cli.export_snapshot(self.db)
        overview_cli.apply_edits(self.db, {"expected_snapshot": original["snapshot_id"], "edits": [
            {"op": "remove", "collection": "uses", "id": "uAT"},
            {"op": "remove", "collection": "items", "id": "T"}], "set": {"main_items": ["A"]}})
        native = overview_cli.export_snapshot(self.db)
        export_import.migrate_overview(self.db, backup=self.path("archive-native-backup.db"))
        self.assertEqual(overview_cli.export_snapshot(self.db), native)
        with storage.Database(self.db, write=True, write_scope="overview") as db:
            self.assertEqual(db.heads("observations"), [])
            selected = db.head("overview_selections", overview.SELECTION_ID)
            body = copy.deepcopy(selected.body)
            body["native_context"]["archived_observations"] = []
            edits = [{"op": "replace", "collection": "overview_selections", "id": selected.id,
                      "expected_version": selected.version, "body": body}]
            with self.assertRaisesRegex(InvalidRequest, "overview field boundary"):
                acceptance.accept(db, request_id="drop-native-archive", request_digest=digest(edits),
                                  packet_id=None, edits=edits, command="overview")
            self.assertEqual(overview.project(db)[0]["observations"], original["observations"])
        data = overview_cli.export_snapshot(self.db)
        restored = overview_cli.apply_edits(self.db, {"expected_snapshot": data["snapshot_id"], "edits": [
            {"op": "upsert", "collection": "items", "id": "T", "record": next(r for r in original["items"] if r["id"] == "T")},
            {"op": "upsert", "collection": "uses", "id": "uAT", "record": original["uses"][0]}],
            "set": {"main_items": original["main_items"]}})
        reselected = overview_cli.export_snapshot(self.db)
        self.assertEqual(reselected["observations"], original["observations"])
        item = dict(reselected["items"][0], caption="Clearer retained caption")
        overview_cli.apply_edits(self.db, {"expected_snapshot": restored["snapshot_id"], "edits": [
            {"op": "upsert", "collection": "items", "id": item["id"], "record": item}]})
        self.assertEqual(overview_cli.export_snapshot(self.db)["observations"], original["observations"])
        with storage.Database(self.db) as db:
            self.assertEqual(db.heads("observations"), [])
            self.assertEqual(db.head("overview_selections", overview.SELECTION_ID).body["native_context"]["archived_observations"],
                             original["observations"])

    def test_full_record_edit_preserves_application_and_rejects_endpoint_contradiction(self):
        self.create(audit=True)
        ref = lambda identity: {"collection": "items", "id": identity}
        bodies = [("scopes", "scope-T", {"argument_id": None, "parent_id": None, "assumptions": [ref("A")],
                    "binders": [], "conditions": [], "evidence_refs": []}),
                  ("arguments", "arg-T", {"target": ref("T"), "label": "Written proof", "origin": "source",
                    "scope_id": "scope-T", "final_group_id": "group-T", "evidence_refs": [], "lifecycle": "registered"}),
                  ("groups", "group-T", {"argument_id": "arg-T", "conclusion": ref("T"), "kind": "joint", "scope_id": "scope-T",
                    "case_scope_ids": [], "discharges": [], "rationale": "Add one", "evidence_refs": []}),
                  ("application_details", "uAT", {"use_id": "uAT", "group_id": "group-T", "needed_form": {"text": "x >= 0", "form": "synopsis"},
                    "substitutions": [], "scope_id": "scope-T", "state": "registered"}),
                  ("target_specs", "spec-T", {"target": ref("T"), "statement_ref": None, "statement": {"text": "For x >= 0, x+1 > 0", "form": "synopsis"},
                    "scope_id": "scope-T", "evidence_refs": [], "state": "registered", "fidelity_ref": None})]
        edits = [{"op": "create", "collection": c, "id": identity, "expected_version": None, "body": b} for c, identity, b in bodies]
        with storage.Database(self.db, write=True) as db:
            acceptance.accept(db, request_id="add-application", request_digest=digest(edits), packet_id=None, edits=edits, command="import")
        data = overview_cli.export_snapshot(self.db)
        item = next(i for i in data["items"] if i["id"] == "T")
        item["caption"] = "Readable caption"
        overview_cli.apply_edits(self.db, {"expected_snapshot": data["snapshot_id"], "edits": [
            {"collection": "items", "op": "upsert", "id": "T", "record": item}]})
        with storage.Database(self.db) as db:
            for collection, identity, body in bodies:
                self.assertEqual(db.head(collection, identity).body, body)
                self.assertEqual(db.head(collection, identity).version, 1)
        data = overview_cli.export_snapshot(self.db)
        changed_use = copy.deepcopy(data["uses"][0])
        changed_use["from"] = "T"
        changed_use["to"] = "A"
        with self.assertRaisesRegex(overview_cli.DatabaseError, "conclusion"):
            overview_cli.apply_edits(self.db, {"expected_snapshot": data["snapshot_id"], "edits": [
                {"collection": "uses", "op": "upsert", "id": "uAT", "record": changed_use}]})

    def test_compatibility_scaffold_and_reconcile_preserve_rich_records(self):
        seed = json.loads(self.seed.read_text(encoding="utf-8"))
        seed["items"].append({"id": "C", "kind": "equation", "owner": "T", "label": "C", "caption": "Intermediate",
            "statement": {"text": "x+1 >= 1", "form": "synopsis"}, "source": {"start_line": 3, "end_line": 3}})
        seed["uses"][0]["group"] = {"id": "legacy-joint", "kind": "joint"}
        write_json(self.seed, seed)
        overview_cli.init_database(self.db, self.seed)
        data = overview_cli.export_snapshot(self.db)
        self.assertEqual(next(i for i in data["items"] if i["id"] == "C")["owner"], "T")
        self.assertEqual(data["uses"][0]["group"], {"id": "legacy-joint", "kind": "joint"})
        scaffold = overview_cli.scaffold_audits(self.db, self.path("scaffold"))
        self.assertTrue(scaffold["audits"])
        for path in self.path("scaffold").glob("*.json"):
            audit = json.loads(path.read_text(encoding="utf-8"))
            audit["dismissed"] = [{"id": identity, "note": "Not used in this fixture"}
                                   for identity in audit["candidates_considered"]]
            write_json(path, audit)
        reconciliation = overview_cli.reconcile_audits(self.db, self.path("scaffold"))
        self.assertTrue(reconciliation["audits"])
        # The retained utility produces review proposals; it cannot synthesize
        # reviewed source comparison or audit checks from its scaffolds.
        with storage.Database(self.db) as db:
            self.assertEqual(db.heads("checks"), [])
            self.assertEqual(db.heads("application_details"), [])

    def test_render_records_common_build_receipt(self):
        self.create()
        self.compare()
        output = self.path("overview.html")
        receipt = overview_cli.render_database(self.db, output)
        self.assertTrue(output.is_file())
        self.assertTrue(receipt["build_recorded"])
        with storage.Database(self.db) as db:
            self.assertTrue(any(key.startswith("overview_build:") for key in db.metadata))

    def test_captured_export_import_does_not_recertify_stale_comparisons(self):
        self.create(native=True)
        self.compare()
        data = overview_cli.export_snapshot(self.db)
        item = next(i for i in data["items"] if i["id"] == "T")
        item["statement"]["text"] = "A changed conclusion"
        overview_cli.apply_edits(self.db, {"expected_snapshot": data["snapshot_id"], "edits": [
            {"collection": "items", "op": "upsert", "id": "T", "record": item}]})
        exported = overview_cli.export_snapshot(self.db)
        seed = write_json(self.path("captured.json"), exported)
        common = self.path("reimported.db")
        overview_cli.init_database(common, seed, focused=True, source_root=self.work)
        self.assertEqual(overview_cli.get_packet(common, "T")["target_fidelity"], "stale")
        with storage.Database(common) as db:
            self.assertTrue(all(o.body["context_data"]["applicable_on_import"] is False for o in db.heads("observations")))

    def test_source_captured_by_proofcheck_can_be_refreshed_through_overview(self):
        self.create(audit=True)
        self.compare()
        self.source.write_text("Lemma A: x is strictly positive.\nTheorem T: x+1 exceeds one.\nUse Lemma A in T.\n", encoding="utf-8")
        with storage.Database(self.db, write=True) as db:
            sources.capture_sources(db, files=["paper.tex"])
        with self.assertRaisesRegex(overview_cli.DatabaseError, "--expected-snapshot") as caught:
            overview_cli.get_packet(self.db, "T")
        expected = str(caught.exception).split("--expected-snapshot ", 1)[1].split(".", 1)[0]
        overview_cli.refresh_database(self.db, expected)
        after = overview_cli.export_snapshot(self.db)
        self.assertIn("strictly positive", after["anchors"][0]["excerpt"])
        self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "stale")

    def test_supplemental_text_page_stales_overview_without_replacing_line_evidence(self):
        seed = json.loads(self.seed.read_text(encoding="utf-8"))
        seed["items"][1]["source"]["page"] = 4
        write_json(self.seed, seed)
        for native in (False, True):
            with self.subTest(native_migration=native):
                self.db = self.path(f"supplemental-{native}.db")
                self.create(native=native)
                self.compare()
                before = overview_cli.export_snapshot(self.db)
                if native:
                    export_import.migrate_overview(self.db, backup=self.path("supplemental-backup.db"))
                    self.assertEqual(overview_cli.export_snapshot(self.db), before)
                anchor = next(a for a in before["anchors"] if a["locator"].get("page") == 4)
                with storage.Database(self.db) as db:
                    original = db.head("anchors", anchor["id"])
                    self.assertIsNone(original.body["locator"]["page"])
                    self.assertEqual(original.body["method"], "exact_lines")
                overview_cli.refresh_database(self.db, before["snapshot_id"],
                    anchor_locations={anchor["id"]: {"locator": dict(anchor["locator"], page=5)}})
                after = overview_cli.export_snapshot(self.db)
                self.assertEqual(next(a for a in after["anchors"] if a["id"] == anchor["id"])["locator"]["page"], 5)
                self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "stale")
                with storage.Database(self.db) as db:
                    current = db.head("anchors", anchor["id"])
                    self.assertEqual((current.version, current.body), (original.version, original.body))

    def test_native_preopened_writer_cannot_commit_after_cutover(self):
        self.create(native=True)
        writer = sqlite3.connect(self.db)
        self.addCleanup(writer.close)
        writer.execute("SELECT value FROM metadata WHERE key='format'").fetchone()
        before = overview_cli.export_snapshot(self.db)
        export_import.migrate_overview(self.db, backup=self.path("native-backup.db"))
        with self.assertRaises(sqlite3.OperationalError):
            writer.execute("INSERT INTO observations(id,snapshot_id,payload) VALUES (?,?,?)", ("late", before["snapshot_id"], "{}"))
            writer.commit()
        with storage.Database(self.db) as db:
            self.assertEqual(db.metadata["storage_format"], "4")

    def test_moved_root_keeps_provenance_and_requires_explicit_refresh(self):
        self.create(native=True)
        absent_root = self.path("original-location")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("UPDATE metadata SET value=? WHERE key='source_root'", (str(absent_root),))
            connection.commit()
        finally:
            connection.close()
        export_import.migrate_overview(self.db, backup=self.path("native-backup.db"))
        with storage.Database(self.db) as db:
            self.assertEqual(storage.paper_record(db).body["source_root"], absent_root.as_posix())
        data = overview_cli.export_snapshot(self.db)
        with self.assertRaises((overview_cli.DatabaseError, paper_records.RecordError)):
            overview_cli.refresh_database(self.db, data["snapshot_id"])
        overview_cli.refresh_database(self.db, data["snapshot_id"], source_root=self.work)
        with storage.Database(self.db) as db:
            self.assertEqual(storage.paper_record(db).body["source_root"], self.work.as_posix())

    def test_wal_migration_keeps_committed_observations(self):
        self.create(native=True)
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        finally:
            connection.close()
        self.compare()
        before = overview_cli.export_snapshot(self.db)
        export_import.migrate_overview(self.db, backup=self.path("native-backup.db"))
        self.assertEqual(before, overview_cli.export_snapshot(self.db))

    def test_busy_writer_refuses_conversion_without_losing_observation(self):
        self.create(native=True)
        writer = sqlite3.connect(self.db)
        writer.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(IncompatibleError) as caught:
                export_import.migrate_overview(self.db, backup=self.path("native-backup.db"))
            self.assertEqual(caught.exception.code, "DATABASE_BUSY")
        finally:
            writer.rollback()
            writer.close()
        self.compare()
        self.assertEqual(len(overview_cli.export_snapshot(self.db)["observations"]), 2)

    def test_failed_conversion_preserves_original(self):
        self.create(native=True)
        before = overview_cli.export_snapshot(self.db)
        with mock.patch.object(export_import, "_overview_edits", side_effect=RuntimeError("conversion failed")):
            with self.assertRaisesRegex(RuntimeError, "conversion failed"):
                export_import.migrate_overview(self.db, backup=self.path("native-backup.db"))
        self.assertEqual(overview_cli.export_snapshot(self.db), before)

    def test_refresh_and_reviewed_reuse(self):
        self.create()
        self.compare()
        before = overview_cli.export_snapshot(self.db)
        changed = overview_cli.apply_edits(self.db, {"expected_snapshot": before["snapshot_id"], "edits": [], "set": {"scope": "Selected statements only"}})
        reused = overview_cli.compare_records(self.db, {"expected_snapshot": changed["snapshot_id"],
            "targets": [{"collection": "items", "id": "T"}], "reviewer": "reader", "note": "Reviewed scope change",
            "reuse_from": before["snapshot_id"], "changes_reviewed": True})
        self.assertEqual(reused["reused"], 1)
        self.source.write_text(self.source.read_text(encoding="utf-8") + "A new remark.\n", encoding="utf-8")
        refreshed = overview_cli.refresh_database(self.db, changed["snapshot_id"])
        self.assertNotEqual(refreshed["snapshot_id"], changed["snapshot_id"])
        self.assertEqual(overview_cli.get_packet(self.db, "T")["target_fidelity"], "stale")


if __name__ == "__main__":
    unittest.main()
