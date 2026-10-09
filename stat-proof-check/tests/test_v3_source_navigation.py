"""Optional public source navigation does not change examination evidence."""
from copy import deepcopy
import json
import unittest

from support import R, TempCase, locator, run_cli
from paper_core import controller, review_groups, sources, stage2
from paper_core.source_navigation import build_source_navigation


class SourceNavigationTests(unittest.TestCase):
    def packet(self):
        def record(collection, identity, version, body):
            return {"ref": {"collection": collection, "id": identity, "version": version}, "body": body}

        return {"packet_id": "pkt_navigation", "assignments": [{"anchor_refs": [
            {"collection": "anchors", "id": "anc_assigned", "version": 1}]}], "records": [
            record("sources", "src_first", 1, {"path": "old-paper.pdf", "blob_sha256": "old-hash",
                "limitation": "Original version has a missing page.", "private_extra": "PRIVATE_OPINION"}),
            record("sources", "src_first", 2, {"path": "revised-paper.pdf", "blob_sha256": "new-hash", "limitation": None}),
            record("sources", "src_second", 1, {"path": "another-paper.pdf", "blob_sha256": "other-hash", "limitation": None}),
            record("anchors", "anc_assigned", 1, {"source_id": "src_first", "source_version": 2,
                "locator": locator(page=1), "limitation": "An important symbol needs comparison.", "excerpt": "PRIVATE_OPINION"}),
            record("anchors", "anc_prerequisite", 3, {"source_id": "src_second", "source_version": 1,
                "locator": locator(page=1), "limitation": None}),
            record("anchors", "anc_original", 1, {"source_id": "src_first", "source_version": 1,
                "locator": locator(page=1), "limitation": None}),
            record("checks", "chk_private", 1, {"reasoning": "PRIVATE_OPINION", "outcome": "supported"})]}

    def test_all_public_anchors_keep_source_versions_and_page_identity_without_opinions(self):
        packet = self.packet()
        before = deepcopy(packet)
        result = build_source_navigation(packet)
        rows = {row["anchor_id"]: row for row in result["anchors"]}
        self.assertEqual({"anc_assigned", "anc_prerequisite", "anc_original"}, set(rows))
        self.assertEqual(("src_first", 2, "revised-paper.pdf", "new-hash"), tuple(
            rows["anc_assigned"][key] for key in ("source_id", "source_version", "source_path", "source_sha256")))
        self.assertEqual("old-paper.pdf", rows["anc_original"]["source_path"])
        self.assertEqual("Original version has a missing page.", rows["anc_original"]["source_limitation"])
        self.assertEqual("An important symbol needs comparison.", rows["anc_assigned"]["anchor_limitation"])
        self.assertEqual(("src_second", 1, "another-paper.pdf", 3), tuple(
            rows["anc_prerequisite"][key] for key in ("source_id", "source_version", "source_path", "anchor_version")))
        self.assertEqual({1}, {row["locator"]["page"] for row in result["anchors"]})
        self.assertNotIn("PRIVATE_OPINION", json.dumps(result))
        self.assertEqual(before, packet)
        result["anchors"][0]["locator"]["page"] = 9
        self.assertEqual(before, packet)

    def test_missing_exact_source_version_does_not_guess_a_different_capture(self):
        packet = self.packet()
        packet["records"][3]["body"]["source_version"] = 7
        row = next(row for row in build_source_navigation(packet)["anchors"] if row["anchor_id"] == "anc_assigned")
        self.assertEqual(7, row["source_version"])
        self.assertIsNone(row["source_path"])
        self.assertIsNone(row["source_sha256"])
        self.assertEqual(locator(page=1), row["locator"])


class SourceNavigationDeliveryTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def navigation(self, directory):
        return json.loads((directory / "source-navigation.json").read_text(encoding="utf-8"))

    def bindings(self):
        return [tuple(row) for row in self.db.conn.execute("SELECT * FROM evidence_bindings ORDER BY owner_collection, owner_id, owner_version")]

    def test_prepare_reexport_and_reuse_include_prerequisite_without_mutating_packet_or_bindings(self):
        prepared = stage2.prepare(self.db, audit_id=self.fx.audit_id, focus=R("items", "itm_thm"))
        packet, manifest = deepcopy(prepared["packet"]), deepcopy(prepared["manifest"])
        stored = self.db.packet(prepared["packet_id"])
        original_bytes = self.db.get_blob(stored["payload_sha256"])
        revision, bindings = self.db.max_revision(), self.bindings()
        assignment_ids = {pin["id"] for row in packet["assignments"] for pin in row["anchor_refs"]}
        rows = {row["anchor_id"] for row in prepared["source_navigation"]["anchors"]}
        self.assertIn("anc_lem", rows)
        self.assertNotIn("anc_lem", assignment_ids)
        self.assertEqual({row["ref"]["id"] for row in packet["records"] if row["ref"]["collection"] == "anchors"}, rows)
        self.assertIn("source-navigation.json", prepared["worker_delivery_files"])
        exported = controller.write_artifacts(self.db, prepared, self.path("normal"))
        self.assertIn("source-navigation.json", exported)
        reopened = controller.inspect_work(self.db, packet_id=prepared["packet_id"])
        controller.write_artifacts(self.db, reopened, self.path("reexport"))
        reused = stage2.prepare(self.db, audit_id=self.fx.audit_id, focus=R("items", "itm_thm"))
        self.assertTrue(reused["reused"])
        self.assertEqual(prepared["source_navigation"], reused["source_navigation"])
        self.assertEqual(self.navigation(self.path("normal")), self.navigation(self.path("reexport")))
        self.assertEqual(packet, prepared["packet"])
        self.assertEqual(manifest, prepared["manifest"])
        self.assertEqual(original_bytes, self.db.get_blob(stored["payload_sha256"]))
        self.assertEqual(revision, self.db.max_revision())
        self.assertEqual(bindings, self.bindings())

    def test_group_delivery_and_resume_name_the_generated_public_index(self):
        group = review_groups.prepare_group(self.db, audit_id=self.fx.audit_id, output=self.path("group"), max_packets=2)
        resumed = review_groups.reexport_group(self.db, audit_id=self.fx.audit_id,
            index_path=group["group_index"], output=self.path("resumed"))
        self.assertEqual(group["packet_ids"], resumed["packet_ids"])
        for result in (group, resumed):
            delivery = json.loads(self.path(result["reviewer_delivery"]).read_text(encoding="utf-8"))
            for row in delivery["packets"]:
                indices = [self.path(path) for path in row["files"] if path.endswith("source-navigation.json")]
                self.assertEqual(1, len(indices))
                self.assertTrue(indices[0].is_file())
                self.assertFalse(any("coordinator" in path for path in row["files"]))

    def test_extension_indexes_new_context_and_keeps_old_packet_unchanged(self):
        extra = self.fx.source_root / "extra.txt"
        extra.write_text("A supplied prerequisite.\n", encoding="utf-8")
        sid = sources.capture_sources(self.db, files=["extra.txt"])["sources"][0]["id"]
        author = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 4, "request_id": self.fx.request_id(),
            "packet_id": author["packet_id"], "anchors": [{"id": "anc_extra", "expected_version": None,
                "source_id": sid, "locator": locator(start=1, end=1)}]})
        prepared = stage2.prepare(self.db, audit_id=self.fx.audit_id, focus=R("items", "itm_thm"))
        before = deepcopy(prepared["packet"])
        original_binding = self.bindings()
        extended = controller.extend_work(self.db, packet_id=prepared["packet_id"], request={
            "source_refs": [self.fx.pin(self.db, "anchors", "anc_extra")], "reason": "Deliver additional neutral source context."})
        controller.write_artifacts(self.db, extended, self.path("extended"))
        rows = self.navigation(self.path("extended"))["anchors"]
        self.assertIn("anc_extra", {row["anchor_id"] for row in rows})
        self.assertNotIn("anc_extra", {row["anchor_id"] for row in prepared["source_navigation"]["anchors"]})
        self.assertEqual(before, prepared["packet"])
        self.assertEqual(before["assignments"], extended["packet"]["assignments"])
        self.assertEqual(original_binding, self.bindings())

    def test_primary_cli_exports_navigation_without_expanding_compact_output(self):
        fx = self.fixture("primary-cli").audit()
        result, _ = run_cli("stage1", "prepare", fx.path, "--audit", fx.audit_id, "--out", self.path("primary"))
        self.assertTrue(result["prepared"], result)
        self.assertNotIn("source_navigation", result)
        self.assertIn("source-navigation.json", result["files"])
        self.assertIn("source-navigation.json", result["worker_delivery_files"])
        self.assertEqual(result["packet_id"], self.navigation(self.path("primary"))["packet_id"])


if __name__ == "__main__":
    unittest.main()
