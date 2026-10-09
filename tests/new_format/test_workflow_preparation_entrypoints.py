"""Public preparation policy and private exceptional-investigation provenance."""
import json

from support import TempCase, edit, run_cli
from paper_core import controller, stages
from paper_core.errors import InvalidRequest


class PreparationEntryPointTests(TempCase):
    def test_legacy_independent_preparation_obeys_primary_readiness(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            before = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            ordinary = controller.prepare_work(db, audit_id=fixture.audit_id, mode="independent")
            explicit = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="independent")
            self.assertFalse(ordinary["prepared"])
            self.assertEqual(ordinary["reason_code"], explicit["reason_code"])
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0], before)

    def test_exception_is_persisted_privately_without_entering_worker_packet(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            result = controller.prepare_work(db, audit_id=fixture.audit_id, mode="independent",
                exception_purpose="Investigate an early disputed inference", exception_limitations="Primary work remains unfinished")
            self.assertTrue(result["prepared"], result)
            exception = result["preparation_exception"]
            stored = db.packet(result["packet_id"])["manifest"]
            self.assertEqual(stored["work"]["preparation_exception"], exception)
            self.assertNotIn("preparation_exception", json.dumps(result["packet"]))
            self.assertNotIn(exception["purpose"], json.dumps(result["packet"]))
            self.assertFalse(stages.stage_status(db, audit_id=fixture.audit_id)["stage1"]["ready"])

    def test_incomplete_exception_rejected_before_persisting_packet(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            before = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            for purpose, limits in (("reason", None), (None, "limit"), (" ", "limit")):
                with self.subTest(purpose=purpose), self.assertRaises(InvalidRequest):
                    controller.prepare_work(db, audit_id=fixture.audit_id, mode="primary",
                        exception_purpose=purpose, exception_limitations=limits)
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0], before)

    def test_global_selection_waits_for_local_review_through_both_interfaces(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            globals_ = [dict(row) for row in audit.body["global_tasks"]]
            globals_[0].update(applicability="required", reason="Cross-result reasoning")
            fixture.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, global_tasks=globals_), audit.version)],
                          *fixture.ITEMS, mode="primary")
            tasks = controller.derive_work(db, audit_id=fixture.audit_id)["tasks"]
            selected = [task["id"] for task in tasks if task["target"]["collection"] == "audits" and task["required"]]
            ordinary = controller.prepare_work(db, audit_id=fixture.audit_id, mode="primary", task_ids=selected)
            explicit = stages.prepare_stage(db, audit_id=fixture.audit_id, stage=2, mode="global")
            self.assertFalse(ordinary["prepared"])
            self.assertEqual(ordinary["reason_code"], explicit["reason_code"])

    def test_cli_retains_exception_in_receipt_and_saved_manifest(self):
        fixture = self.fixture().audit()
        out = fixture.root / "exception-assignment"
        result, _ = run_cli("work", "prepare", fixture.path, "--audit", fixture.audit_id,
            "--mode", "primary", "--focus", "items:itm_lem", "--out", out,
            "--exception-purpose", "Inspect a local representation", "--exception-limitations", "No completion claim")
        self.assertTrue(result["prepared"], result)
        self.assertEqual(result["preparation_exception"]["purpose"], "Inspect a local representation")
        with fixture.open() as db:
            self.assertEqual(db.packet(result["packet_id"])["manifest"]["work"]["preparation_exception"],
                             result["preparation_exception"])

    def test_size_retry_preserves_exception_scope_and_is_executable(self):
        fixture = self.fixture().audit()
        result, _ = run_cli("work", "prepare", fixture.path, "--audit", fixture.audit_id,
            "--mode", "independent", "--out", fixture.root / "retry-assignment", "--max-bytes", "1",
            "--exception-purpose", "Inspect a disputed step early",
            "--exception-limitations", "Primary work remains unfinished")
        self.assertFalse(result["prepared"])
        retry = result["preparation"]["size_action"]["command"]
        retried, _ = run_cli(*retry[1:])
        self.assertTrue(retried["prepared"], retried)
        self.assertEqual(retried["preparation_exception"]["purpose"], "Inspect a disputed step early")
        self.assertEqual(retried["preparation_exception"]["limitations"], "Primary work remains unfinished")
