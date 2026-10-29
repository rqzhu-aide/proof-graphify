"""A few reviewer contexts can receive distinct ordinary proof packets."""
from __future__ import annotations

import copy
import json
from unittest import mock

from support import R, TempCase, edit
from paper_core import controller, review_groups, sources, stage2
from paper_core.errors import InvalidRequest
from paper_core.work import derive_work


class ReviewGroupTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def tasks(self):
        return [t for t in derive_work(self.db, audit_id=self.fx.audit_id)["tasks"] if t["role"] == "independent"]

    def prepare(self, name, **kwargs):
        return review_groups.prepare_group(self.db, audit_id=self.fx.audit_id, output=self.path(name), **kwargs)

    def submit(self, packet_id, *, partial=False, malformed=False):
        packet = controller.inspect_work(self.db, packet_id=packet_id)
        response = copy.deepcopy(packet["scaffold"])
        response["coverage_note"] = "The assigned source question was independently examined."
        response["exposure_report"] = {"status": "none_known", "note": "One separate context for this group."}
        for row in response["judgments"]:
            row.update(state="complete", outcome="supported", reasoning="The stated assumptions establish the supplied conclusion.",
                       extent="partial" if partial else "whole_unit", omissions="The last inference remains." if partial else "")
        if malformed:
            response["judgments"][0]["state"] = "invalid"
        raw = json.dumps(response).encode()
        envelope = dict(packet["submission_envelope_template"], request_id=self.fx.request_id(),
                        reviewer="one independent group reviewer", exposure="source_only")
        return controller.submit_work(self.db, envelope_bytes=json.dumps(envelope).encode(), response_bytes=raw), raw

    def test_distinct_groups_reuse_saved_membership_and_keep_worker_delivery_neutral(self):
        revision = self.db.max_revision()
        first = self.prepare("a", max_packets=1)
        second = self.prepare("b", max_packets=1, exclude_groups=[first["group_index"]])
        self.assertEqual(1, len(first["packets"]))
        self.assertEqual(1, len(second["packets"]))
        self.assertFalse(set(first["assigned_task_ids"]) & set(second["assigned_task_ids"]))
        self.assertEqual({t["id"] for t in self.tasks()}, set(first["assigned_task_ids"] + second["assigned_task_ids"]))
        self.assertEqual(revision, self.db.max_revision())
        count = self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        again = self.prepare("a", max_packets=1)
        self.assertTrue(again["reused"])
        self.assertEqual(first["packet_ids"], again["packet_ids"])
        self.assertEqual(count, self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])
        delivery = json.loads(self.path("a", review_groups.DELIVERY_NAME).read_text(encoding="utf-8"))
        self.assertIn("Do not read coordinator files or primary opinions.", delivery["instructions"])
        self.assertIn("Do not read other reviewers' responses outside your explicitly assigned source-only "
                      "continuation lineage.", delivery["instructions"])
        self.assertIn("re-exporting files does not request a repeated examination", delivery["instructions"])
        worker = delivery["packets"][0]
        self.assertEqual({"labels", "files", "sources", "response_path"}, set(worker))
        self.assertTrue(worker["sources"])
        self.assertFalse(any("coordinator" in path or "submission-envelope" in path for path in worker["files"]))
        self.assertTrue(all(self.path(path).is_file() for path in worker["files"]))
        with self.assertRaisesRegex(InvalidRequest, "different selection"):
            self.prepare("a", max_packets=2)

    def test_explicit_selection_empty_satisfied_and_excluded_never_add_filler(self):
        ids = [t["id"] for t in self.tasks()]
        empty = self.prepare("empty", task_ids=[])
        self.assertFalse(empty["prepared"])
        selected = self.prepare("selected", task_ids=[ids[0]], max_packets=5)
        self.assertEqual([ids[0]], selected["assigned_task_ids"])
        result, _ = self.submit(selected["packet_ids"][0])
        self.assertFalse(result["remaining_task_ids"], result)
        satisfied = self.prepare("satisfied", task_ids=[ids[0]], max_packets=5)
        self.assertFalse(satisfied["prepared"])
        self.assertEqual([{"task_id": ids[0], "reason": "satisfied"}], satisfied["unassigned"])
        excluded = self.prepare("excluded", task_ids=[ids[1]], exclude_task_ids=[ids[1]])
        self.assertFalse(excluded["prepared"])
        self.assertEqual("excluded", excluded["unassigned"][0]["reason"])

    def test_mixed_unavailable_and_ready_units_do_not_create_global_barrier(self):
        packet = self.fx.packet(self.db, *self.fx.ITEMS, mode="primary")
        sources.review_sources(self.db, batch=self.fx.batch([edit("create", "source_issues", "iss_group_missing", {
            "source_id": self.fx.source_id, "anchor_id": "anc_lem_proof", "category": "missing_source",
            "description": "The promised continuation is unavailable.", "lifecycle": "open",
            "resolution": None, "reviewer": "coordinator"})], packet["packet_id"]))
        group = self.prepare("mixed", task_ids=[t["id"] for t in self.tasks()])
        self.assertEqual(1, len(group["packets"]), group)
        self.assertEqual(["needs_coordinator"], [row["reason"] for row in group["unassigned"]])
        self.assertEqual(2, len(group["remaining_task_ids"]))

    def test_oversized_first_unit_is_skipped_without_cutting_it(self):
        # Remove the supplier connection so the long lemma is independent of the other proof.
        use = self.db.head("uses", "use_lem_thm")
        lemma = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [{"op": "retire", "collection": "uses", "id": use.id,
            "expected_version": use.version, "reason": "Independent fixture units."},
            edit("replace", "items", lemma.id, dict(lemma.body,
                statement={"form": "verbatim", "text": "A long source statement. " * 3000}), lemma.version)])
        # The pinned exact question also receives the long source statement.
        spec = self.db.head("target_specs", "tgt_lem")
        current = self.db.head("items", "itm_lem")
        self.fx.apply(self.db, [edit("replace", "target_specs", spec.id,
            dict(spec.body, statement_ref=current.pinned), spec.version)])
        group = self.prepare("oversized", max_bytes=24000)
        self.assertEqual(1, len(group["packets"]), group)
        self.assertEqual(["oversized_context"], [row["reason"] for row in group["unassigned"]])
        self.assertTrue(group["diagnostics"])
        self.assertGreater(group["diagnostics"][0]["measured_or_lower_bound_bytes"], 24000)
        self.assertTrue(group["diagnostics"][0]["largest_contributors"])
        delivery = json.loads(self.path("oversized", review_groups.DELIVERY_NAME).read_text(encoding="utf-8"))
        self.assertNotIn("diagnostics", delivery)
        packet = self.db.packet(group["packet_ids"][0])["manifest"]
        self.assertEqual("arg_thm", packet["work"]["tasks"][0]["target"]["id"])

    def test_export_interruption_preserves_saved_ids_and_resumes_only_membership(self):
        real_export = review_groups.write_artifacts
        calls = []

        def interrupt(db, result, directory):
            calls.append(result["packet_id"])
            if len(calls) == 2:
                raise OSError("Interrupted child export")
            return real_export(db, result, directory)

        with mock.patch.object(review_groups, "write_artifacts", side_effect=interrupt):
            with self.assertRaises(InvalidRequest) as caught:
                self.prepare("interrupted", max_packets=2)
        index = self.path("interrupted", review_groups.INDEX_NAME)
        self.assertEqual(calls, [row["packet_id"] for row in json.loads(index.read_text(encoding="utf-8"))["packets"]])
        self.assertEqual(calls, caught.exception.records[-1]["packet_ids"])
        first_response = self.path("interrupted", calls[0], "response.json")
        first_response.write_bytes(b"preserved unfinished response")
        count = self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        resumed = review_groups.reexport_group(self.db, audit_id=self.fx.audit_id,
            index_path=index, output=self.path("recovered"))
        self.assertEqual(calls, resumed["packet_ids"])
        self.assertEqual(count, self.db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])
        self.assertEqual(b"preserved unfinished response", first_response.read_bytes())
        self.assertTrue(all(self.path("recovered", identity, "worker-packet.json").exists() for identity in calls))
        self.assertEqual([str(first_response)], resumed["packets"][0]["prior_response_paths"])
        self.assertEqual([str(first_response)], resumed["response_file_locations"][0]["existing_paths"])
        delivery_text = self.path("recovered", review_groups.DELIVERY_NAME).read_text(encoding="utf-8")
        self.assertNotIn(str(first_response), delivery_text)
        self.assertNotIn("preserved unfinished response", delivery_text)
        self.assertIn("not a new dispatch instruction", json.loads(delivery_text)["instructions"])

        # A second re-export still points the coordinator to the original return.
        chained = review_groups.reexport_group(self.db, audit_id=self.fx.audit_id,
            index_path=resumed["group_index"], output=self.path("recovered-again"))
        self.assertEqual(calls, chained["packet_ids"])
        self.assertEqual([str(first_response)], chained["response_file_locations"][0]["existing_paths"])
        self.assertEqual([str(first_response), resumed["packets"][0]["response_path"]],
                         chained["packets"][0]["prior_response_paths"])
        reopened = review_groups.reexport_group(self.db, audit_id=self.fx.audit_id,
            index_path=chained["group_index"], output=self.path("recovered-again"))
        self.assertEqual(chained["packets"], reopened["packets"])

    def test_index_write_failure_reports_already_persisted_packet(self):
        with mock.patch.object(review_groups, "_write_json", side_effect=OSError("index disk error")):
            with self.assertRaises(InvalidRequest) as caught:
                self.prepare("index-failure")
        ids = caught.exception.records[-1]["packet_ids"]
        self.assertEqual(1, len(ids))
        self.assertIsNotNone(self.db.packet(ids[0]))
        prepared = stage2.prepare(self.db, audit_id=self.fx.audit_id)
        self.assertEqual(ids[0], prepared["packet_id"])
        self.assertTrue(prepared["reused"])

    def test_group_exclusions_use_saved_manifests_not_edited_index_task_ids(self):
        first = self.prepare("original", max_packets=1)
        index = json.loads(self.path("original", review_groups.INDEX_NAME).read_text(encoding="utf-8"))
        index["packets"][0]["assigned_task_ids"] = ["not_a_real_task"]
        path = self.path("edited-index.json")
        path.write_text(json.dumps(index), encoding="utf-8")
        second = self.prepare("remaining", exclude_groups=[path])
        self.assertFalse(set(first["assigned_task_ids"]) & set(second["assigned_task_ids"]))
        index["audit_id"] = "aud_other"
        path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(InvalidRequest):
            self.prepare("wrong-audit", exclude_groups=[path])

    def test_completed_partial_and_failed_returns_remain_separable(self):
        group = self.prepare("responses", max_packets=2)
        good, partial = group["packet_ids"]
        completed, raw = self.submit(good)
        self.assertFalse(completed["remaining_task_ids"], completed)
        failed, _ = self.submit(partial, malformed=True)
        self.assertTrue(failed.get("pending") or failed["state"] != "accepted" or failed["remaining_task_ids"], failed)
        unfinished, _ = self.submit(partial, partial=True)
        self.assertTrue(unfinished["remaining_task_ids"], unfinished)
        response = self.db.head("responses", completed["response_id"])
        self.assertEqual(raw, self.db.get_blob(response.body["original_blob"]))
        guidance = self.path("responses", good, "coordinator-guidance.json").read_bytes()
        reopened = self.prepare("responses", max_packets=2)
        self.assertEqual(group["packet_ids"], reopened["packet_ids"])
        self.assertEqual(unfinished["remaining_task_ids"], reopened["remaining_task_ids"])
        self.assertEqual(guidance, self.path("responses", good, "coordinator-guidance.json").read_bytes())
        pending = self.prepare("continuation")
        self.assertEqual(group["packets"][1]["assigned_task_ids"], pending["assigned_task_ids"])
        reexport = review_groups.reexport_group(self.db, audit_id=self.fx.audit_id,
            index_path=group["group_index"], output=self.path("response-reexport"))
        self.assertEqual(group["packet_ids"], reexport["packet_ids"])
        self.assertEqual(unfinished["remaining_task_ids"], reexport["remaining_task_ids"])
        delivery = json.loads(self.path("response-reexport", review_groups.DELIVERY_NAME).read_text(encoding="utf-8"))
        self.assertIn("re-exporting files does not request a repeated examination", delivery["instructions"])
        self.assertIn("current remaining_task_ids", reexport["continuation_note"])


if __name__ == "__main__":
    import unittest
    unittest.main()
