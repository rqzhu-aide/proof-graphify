from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import Fixture, R, edit, node_available, run_cli
from paper_core import finalization, publish, stage1
from paper_core.errors import InvalidRequest, PublicationError


class V3DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, *, independent=True):
        return Fixture(self.root / "audit").audit(independent_required=independent)

    def test_explicit_empty_stage_never_selects_all_work(self):
        fixture = self.fixture()
        with fixture.open() as db:
            before = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            result = stage1.prepare_stage(db, audit_id="aud_1", task_ids=[])
            self.assertFalse(result["prepared"])
            self.assertEqual("no_selected_work", result["reason"])
            self.assertEqual(before, db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])
            empty = stage1.prepare_stage(db, audit_id="aud_1", stage=2, mode="primary")
            self.assertFalse(empty["prepared"])
            self.assertEqual("no_stage_work", empty["reason"])

    def test_unchanged_preparation_reuses_useful_assignment(self):
        fixture = self.fixture()
        with fixture.open() as db:
            first = stage1.prepare_stage(db, audit_id="aud_1")
            self.assertTrue(first["prepared"], first)
            count = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            again = stage1.prepare_stage(db, audit_id="aud_1")
            self.assertTrue(again["reused"])
            self.assertEqual(first["packet_id"], again["packet_id"])
            self.assertEqual(count, db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])

    def test_selected_cross_proof_question_is_primary_work_and_finishes_uncertain(self):
        fixture = self.fixture(independent=False).primary()
        with fixture.open() as db:
            audit = db.head("audits", "aud_1")
            fixture.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, global_tasks=[{
                "kind": "global_consistency", "applicability": "required",
                "reason": "Assess whether the shared sequence assumptions agree between the two results."
            }]), audit.version)], "audits:aud_1", mode="primary")
            status = stage1.stage_status(db, audit_id="aud_1")
            selected = [t for t in status["tasks"] if t["kind"] == "global_consistency"]
            self.assertEqual(1, len(selected))
            prepared = stage1.prepare_stage(db, audit_id="aud_1", task_ids=[selected[0]["id"]])
            self.assertTrue(prepared["prepared"], prepared)
            check = fixture.check_edit("chk_shared_assumptions", R("audits", "aud_1"),
                                       "global_consistency", outcome="inconclusive",
                                       evidence=["anc_lem", "anc_thm"])
            check["body"]["reasoning"] = "The supplied statements leave the shared monotonicity assumption ambiguous."
            fixture.apply(db, [check], "audits:aud_1", mode="primary")
            again = stage1.prepare_stage(db, audit_id="aud_1", task_ids=[selected[0]["id"]])
            self.assertFalse(again["prepared"], again)
            done = stage1.stage_status(db, audit_id="aud_1")
            self.assertNotIn(selected[0]["id"], done["remaining_task_ids"])

    def test_freeze_assesses_once_and_saves_same_revision_summary(self):
        fixture = self.fixture().primary()
        bundle = self.root / "frozen"
        original = finalization.derive_full
        with fixture.open(write=False) as db, mock.patch.object(finalization, "derive_full", wraps=original) as derive:
            with mock.patch("paper_core.queries.project", side_effect=AssertionError("recursive projection")):
                result = finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
            self.assertEqual(1, derive.call_count)
            self.assertEqual("working", result["kind"])
            self.assertFalse(result["process_complete"])
            repeated = finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
            self.assertTrue(repeated["reused"])
            self.assertEqual(1, derive.call_count)
        snapshot, receipt = finalization.load_finalization(bundle)
        summary = json.loads((bundle / finalization.SUMMARY_NAME).read_text(encoding="utf-8"))
        self.assertEqual(snapshot["revision"], summary["revision"])
        self.assertEqual(snapshot["projection"]["summary"], summary["summary"])
        self.assertEqual("coherent-proof-audit/1", receipt["producer"]["protocol_version"])
        self.assertTrue(any(b["code"] == "required_work" for b in receipt["finalization_blockers"]))

    def test_completed_gap_can_release_without_positive_support(self):
        fixture = self.fixture(independent=False).primary()
        with fixture.open() as db:
            check = db.head("checks", "chk_comp_thm")
            body = dict(check.body, outcome="gap", reasoning="Boundedness alone does not imply convergence.",
                        supersedes=check.pinned)
            fixture.apply(db, [edit("create", "checks", "chk_gap_thm", body)],
                          "items:itm_thm", mode="primary")
            result = finalization.finalize_audit(db, audit_id="aud_1", output=self.root / "gap")
        self.assertEqual("release", result["kind"])
        self.assertTrue(result["process_complete"])
        snapshot, _ = finalization.load_finalization(self.root / "gap")
        self.assertEqual(1, snapshot["projection"]["summary"]["factual"]["work"]["current_primary_outcomes"]["gap"])

    def test_pin_free_cli_integration_can_release_unresolved_disagreement(self):
        fixture = self.fixture().independent()
        for index in range(2):
            directory = self.root / f"integration-{index}"
            prepared, _ = run_cli("stage2", "prepare", fixture.path, "--audit", "aud_1",
                                  "--mode", "integration", "--out", directory)
            self.assertTrue(prepared["prepared"], prepared)
            scaffold = json.loads((directory / "response-scaffold.json").read_text(encoding="utf-8"))
            self.assertIn("integrations", scaffold)
            for row in scaffold["integrations"]:
                row["decision"] = "unresolved"
                row["rationale"] = "The opinions were compared once; uncertainty in the claimed limiting step remains."
            response = directory / "actual-integration.json"
            response.write_text(json.dumps(scaffold), encoding="utf-8")
            submitted, _ = run_cli("stage2", "integrate", fixture.path, "--packet", prepared["packet_id"],
                                  "--reviewer", "coordinator", "--response", response)
            self.assertEqual("accepted", submitted["state"], submitted)
        done, _ = run_cli("stage2", "prepare", fixture.path, "--audit", "aud_1", "--mode", "integration")
        self.assertFalse(done["prepared"])
        with fixture.open(write=False) as db:
            frozen = finalization.finalize_audit(db, audit_id="aud_1", output=self.root / "disagreement")
        self.assertEqual("release", frozen["kind"], frozen["finalization_blockers"])
        self.assertTrue(frozen["process_complete"])
        self.assertIn("disputed", frozen["status"]["independent"].values())
        self.assertFalse(frozen["finalization_blockers"])

    def test_missing_required_source_keeps_a_working_bundle(self):
        fixture = self.fixture(independent=False).primary()
        with fixture.open() as db:
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            from paper_core.sources import review_sources
            review_sources(db, batch=fixture.batch([edit("create", "source_issues", "iss_missing", {
                "source_id": fixture.source_id, "anchor_id": "anc_thm_proof", "category": "missing_source",
                "description": "A referenced continuation is unavailable.", "lifecycle": "open",
                "resolution": None, "reviewer": "coordinator"})], packet["packet_id"]))
            frozen = finalization.finalize_audit(db, audit_id="aud_1", output=self.root / "limited")
        self.assertEqual("working", frozen["kind"])
        self.assertFalse(frozen["representation_settled"])
        self.assertTrue(any(row["code"] == "source_limit" for row in frozen["finalization_blockers"]))

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_stage3_renders_frozen_revision_without_live_database(self):
        fixture = self.fixture().primary()
        bundle, output = self.root / "frozen", self.root / "report.html"
        with fixture.open() as db:
            frozen = finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
            paper = db.head("papers", fixture.paper_id)
            fixture.apply(db, [edit("replace", "papers", paper.id,
                                    dict(paper.body, title="Later title"), paper.version)])
        saved = {p.name: p.read_bytes() for p in bundle.iterdir()}
        fixture.path.rename(fixture.path.with_suffix(".saved"))
        with mock.patch("paper_core.assessment.derive_full", side_effect=AssertionError("live assessment")), \
             mock.patch("paper_core.storage.Database", side_effect=AssertionError("live database")):
            result = publish.publish_frozen(bundle, output=output)
        self.assertEqual(frozen["revision"], result["revision"])
        self.assertEqual(frozen["snapshot_sha256"], result["snapshot_sha256"])
        self.assertIn("Test paper", output.read_text(encoding="utf-8"))
        self.assertNotIn("Later title", output.read_text(encoding="utf-8"))
        self.assertEqual(saved, {p.name: p.read_bytes() for p in bundle.iterdir()})
        cli, _ = run_cli("stage3", "render", bundle, "--out", self.root / "retry.html")
        self.assertEqual(result["snapshot_sha256"], cli["snapshot_sha256"])

    def test_render_failure_preserves_science_and_prior_artifacts(self):
        fixture = self.fixture().primary()
        bundle, output = self.root / "frozen", self.root / "report.html"
        with fixture.open(write=False) as db:
            finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
        output.write_bytes(b"previous report")
        receipt = output.with_name(output.name + ".receipt.json")
        receipt.write_bytes(b"previous receipt")
        science = {p.name: p.read_bytes() for p in bundle.iterdir()}
        with mock.patch.object(publish, "render_payload", side_effect=PublicationError("renderer failed")):
            with self.assertRaises(PublicationError) as caught:
                publish.publish_frozen(bundle, output=output)
        self.assertTrue(caught.exception.records[-1]["prior_output_retained"])
        self.assertEqual(b"previous report", output.read_bytes())
        self.assertEqual(b"previous receipt", receipt.read_bytes())
        self.assertEqual(science, {p.name: p.read_bytes() for p in bundle.iterdir()})

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_release_convenience_uses_the_frozen_delivery_path(self):
        fixture = self.fixture().primary()
        bundle = self.root / "legacy-command"
        released, _ = run_cli("release", fixture.path, "--audit", "aud_1", "--out", bundle)
        self.assertTrue(released["delivery_complete"])
        self.assertEqual("working", released["kind"])
        self.assertEqual(released["snapshot_sha256"], released["publication"]["snapshot_sha256"])
        snapshot, receipt = finalization.load_finalization(bundle)
        self.assertEqual(snapshot["revision"], released["revision"])
        self.assertIn("export", receipt)

    def test_frozen_integrity_and_output_collisions_are_rejected(self):
        fixture = self.fixture().primary()
        bundle = self.root / "frozen"
        with fixture.open(write=False) as db:
            finalization.finalize_audit(db, audit_id="aud_1", output=bundle)
        for output in (fixture.path, fixture.source_root / "paper.tex", bundle / finalization.SNAPSHOT_NAME):
            with self.assertRaises(InvalidRequest):
                publish.publish_frozen(bundle, output=output)
        with (bundle / finalization.SNAPSHOT_NAME).open("ab") as stream:
            stream.write(b" ")
        with self.assertRaisesRegex(InvalidRequest, "hash does not match"):
            finalization.load_finalization(bundle)


if __name__ == "__main__":
    unittest.main()
