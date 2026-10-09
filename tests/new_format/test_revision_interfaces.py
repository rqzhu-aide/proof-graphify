"""Public CLI delivery and portable coordinator I/O for the 2.2 revision."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support import Fixture, REPO, R, run_cli, write_json
from paper_core import controller, review
from paper_core.canonical import canonical_bytes
from paper_core.contract import JUDGMENT, validate_shape


class RevisionInterfacesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fx = Fixture(self.tmp.name).audit(independent_required=False)

    def test_prepare_cli_delivers_shapes_without_dumping_them_to_stdout(self):
        result, _ = run_cli("work", "prepare", self.fx.path, "--audit", self.fx.audit_id,
                            "--mode", "primary", "--focus", "items:itm_lem", "--out", self.root / "assignment")
        self.assertTrue(result["prepared"], result)
        self.assertNotIn("worker_guidance", result)
        self.assertNotIn("coordinator_guidance", result)
        self.assertNotIn("submission_envelope_template", result)
        self.assertEqual(set(result["files"]), {
            "worker-packet.json", "response-scaffold.json", "worker-guidance.json",
            "coordinator-manifest.json", "coordinator-guidance.json", "submission-envelope-template.json"})
        self.assertEqual(result["worker_delivery_files"], [
            "worker-packet.json", "response-scaffold.json", "worker-guidance.json"])
        self.assertNotIn("submission-envelope-template.json", result["worker_delivery_files"])
        guide = json.loads((self.root / "assignment/worker-guidance.json").read_text(encoding="utf-8"))
        self.assertEqual(set(result["assigned_task_ids"]), {row["task_id"] for row in guide["task_table"]})
        self.assertTrue(all(row["target_label"] for row in guide["task_table"]))

    def test_authoring_template_is_uncommitted_and_does_not_overwrite(self):
        with self.fx.open() as db:
            packet = self.fx.packet(db, "items:itm_lem", mode="author")
            before = db.max_revision()
        out = self.root / "item.json"
        result, _ = run_cli("template", self.fx.path, "--packet", packet["packet_id"],
                            "--collection", "items", "--out", out)
        template = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(template["template"]["edits"][0]["body"]["statement"]["text"], "")
        original = out.read_bytes()
        rejected, _ = run_cli("template", self.fx.path, "--packet", packet["packet_id"],
                              "--collection", "items", "--out", out, expect=2)
        self.assertEqual(rejected["error"]["code"], "OUTPUT_CONFLICT")
        self.assertEqual(out.read_bytes(), original)
        with self.fx.open() as db:
            self.assertEqual(db.max_revision(), before)

    def test_bad_shape_names_alternatives_and_actual_representation(self):
        errors = validate_shape(JUDGMENT, {"target": "itm_lem"})
        target_error = next(error for error in errors if "/target:" in error)
        self.assertIn("source_anchor_id", target_error)
        self.assertIn("collection", target_error)
        self.assertIn("got str", target_error)

    def test_template_cannot_recreate_a_missing_registered_source(self):
        with self.fx.open() as db:
            packet = self.fx.packet(db, "items:itm_lem", mode="author")
            source = db.head("sources", self.fx.source_id)
            source_path = self.fx.source_root / source.body["path"]
        source_path.unlink()
        rejected, _ = run_cli("template", self.fx.path, "--packet", packet["packet_id"],
                              "--collection", "items", "--out", source_path, expect=2)
        self.assertEqual(rejected["error"]["code"], "OUTPUT_CONFLICT")
        self.assertFalse(source_path.exists())

    def test_mapping_cli_selects_pending_unseen_ids_and_omits_already_mapped_rows(self):
        with self.fx.open() as db:
            original = self.fx.packet(db, "items:itm_lem", mode="independent")
            worker = {"packet_id": original["packet_id"], "covered_targets": [R("items", "itm_lem")],
                      "coverage_note": "Synthetic complete source examination.",
                      "exposure_report": {"status": "none_known", "note": ""},
                      "judgments": [{"target": R("arguments", "arg_lem"), "kind": "composition",
                                     "state": "complete", "outcome": "inconclusive", "reasoning": "Synthetic test limitation.",
                                     "evidence_refs": ["anc_lem_proof"], "conditions": [],
                                     "next_action": None, "supersedes": None}]}
            saved = review.submit_review(db, submission={"contract_version": 4, "request_id": self.fx.request_id(),
                "packet_id": original["packet_id"], "reviewer": "checker-A", "qualification_id": "qua_r1",
                "exposure": "source_only", "exposure_note": "Synthetic test"}, response_bytes=canonical_bytes(worker))
            mapping_packet = self.fx.packet(db, "items:itm_lem", mode="primary")
        help_path = self.root / "mapping.json"
        run_cli("review", "mapping-template", self.fx.path, "--response", saved["response_id"],
                "--packet", mapping_packet["packet_id"], "--out", help_path)
        result = json.loads(help_path.read_text(encoding="utf-8"))
        mapping = result["template"]
        self.assertEqual([row["judgment_index"] for row in mapping["entries"]], [0])
        mapping.update(reviewer="coordinator")
        mapping["entries"][0].update(target=R("arguments", "arg_lem"), rationale="This is the exact source proof route.")
        with self.fx.open() as db:
            review.map_response(db, mapping=mapping)
            current = self.fx.packet(db, "items:itm_lem", mode="primary")
        second = self.root / "mapped.json"
        run_cli("review", "mapping-template", self.fx.path, "--response", saved["response_id"],
                "--packet", current["packet_id"], "--out", second)
        self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["template"]["entries"], [])

    def test_utf8_helper_under_cp1252_parent(self):
        helper = REPO / "stat-proof-check/scripts/audit_io.py"
        child = self.root / "child.py"
        child.write_text("import json\nprint(json.dumps({'text': 'α ∫ β 中文'}, ensure_ascii=False))\n",
                         encoding="utf-8")
        parent = self.root / "parent.py"
        parent.write_text(
            "import sys, json\n"
            f"sys.path.insert(0, {str(helper.parent)!r})\n"
            "from audit_io import run_audit, write_json, read_json\n"
            f"result = run_audit({str(child)!r})\n"
            f"path = write_json({str(self.root / 'unicode.json')!r}, result['result'])\n"
            "assert read_json(path)['text'] == 'α ∫ β 中文'\n"
            "print(json.dumps({'encoding': sys.stdout.encoding, 'result': read_json(path)}))\n",
            encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", parent], capture_output=True,
                                env=dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp1252"),
                                check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("cp1252"))
        payload = json.loads(result.stdout.decode("cp1252"))
        self.assertEqual(payload["encoding"], "cp1252")
        self.assertEqual(payload["result"]["text"], "α ∫ β 中文")


if __name__ == "__main__":
    unittest.main()
