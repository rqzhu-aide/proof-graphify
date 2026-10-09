"""One bounded CLI lifecycle; all examiner and qualification data are synthetic."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import R, edit, locator, node_available, run_cli, write_json
from test_cli import AUDIT, _CliPaper, _audit_body, _qualification_receipt, _structure_edits
from paper_core import cli, controller, storage


class TargetedLifecycle(_CliPaper):
    """Reuse CLI fixture authoring shapes, then exercise saved assignment assistance."""

    def call(self, name, *arguments, expect=0):
        result, stderr = run_cli(*arguments, expect=expect)
        self.steps[name] = result
        write_json(self.work / f"receipt-{name}.json", {
            "arguments": [str(value) for value in arguments], "exit_code": expect,
            "result": result, "stderr": stderr})
        return result

    def get(self, *targets, mode="primary", name=None):
        self.counter += 1
        name = name or f"context-{self.counter}-{mode}"
        output = self.work / f"{name}.json"
        arguments = ["get", self.db]
        for target in targets:
            arguments.extend(["--target", target])
        receipt = self.call(name, *arguments, "--mode", mode, "--out", output)
        return receipt, json.loads(output.read_text(encoding="utf-8"))

    def author(self):
        receipt = self.call("init", "init", self.db, "--source-root", self.source_root,
                            "--title", "Synthetic targeted workflow: focused negative audit")
        self.paper_id = receipt["paper_id"]
        capture = self.call("capture", "source", "capture", self.db, "--files",
                            self.json_file("files.json", ["paper.tex"]))
        self.source_id = capture["sources"][0]["id"]
        packet, _ = self.get(f"papers:{self.paper_id}", mode="author")
        anchors = [{"id": name, "expected_version": None, "source_id": self.source_id, "locator": loc}
            for name, loc in (("anc_lem", locator(label="lem:a")), ("anc_lem_proof", locator(start=8, end=10)),
                              ("anc_thm", locator(label="thm:b")), ("anc_thm_proof", locator(start=14, end=16)))]
        self.call("anchors", "source", "anchor", self.db, "--request", self.json_file("anchors.json", {
            "contract_version": 4, "request_id": self.request_id(), "packet_id": packet["packet_id"], "anchors": anchors}))
        packet, _ = self.get(f"papers:{self.paper_id}", mode="author")
        self.call("structure", "apply", self.db, "--batch",
                  self.json_file("structure.json", self.batch(_structure_edits(), packet["packet_id"])))
        packet, _ = self.get("items:itm_lem")
        source_review = edit("create", "source_reviews", "srv_boundaries", {
            "purpose": "proof_boundary", "source_refs": [self.pin("sources", self.source_id)],
            "anchor_refs": [self.pin("anchors", "anc_lem_proof")], "decision": "accepted",
            "reviewer": "coordinator", "rationale": "Synthetic fixture scope is the complete captured lemma proof only."})
        self.call("boundary-review", "source", "review", self.db, "--request",
                  self.json_file("boundary-review.json", self.batch([source_review], packet["packet_id"])))
        packet, _ = self.get("items:itm_lem")
        body = dict(_audit_body(self.paper_id), targets=[R("items", "itm_lem")], qualification_id=None,
            exclusions=[{"target": R("items", "itm_thm"), "source_anchor_ids": ["anc_thm_proof"],
                "reason": "The theorem is outside this bounded software fixture.",
                "consequence": "This run makes no assessment of the theorem proof."}])
        records = [edit("create", "audits", AUDIT, body),
            edit("create", "target_specs", "tgt_lem", {
                "target": R("items", "itm_lem"), "statement_ref": self.pin("items", "itm_lem"),
                "statement": None, "scope_id": None, "evidence_refs": ["anc_lem"],
                "state": "registered", "fidelity_ref": None}),
            edit("create", "proof_boundaries", "bnd_lem", {
                "target": R("items", "itm_lem"), "argument_ids": ["arg_lem"],
                "anchor_refs": [self.pin("anchors", "anc_lem_proof")],
                "source_review_ref": self.pin("source_reviews", "srv_boundaries"), "state": "complete"})]
        self.call("audit", "apply", self.db, "--batch", self.json_file("audit.json", self.batch(records, packet["packet_id"])))

    @staticmethod
    def read(directory, name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    def primary(self):
        blocked = self.work / "blocked-output"
        blocked.write_text("Preserve this existing user file.", encoding="utf-8")
        failed = self.call("packet-export-interrupted", "work", "prepare", self.db,
            "--audit", AUDIT, "--mode", "primary", "--focus", "items:itm_lem", "--out", blocked, expect=2)
        packet_id = next(record["packet_id"] for record in failed["error"]["records"]
                         if isinstance(record, dict) and "packet_id" in record)
        with storage.Database(self.db) as db:
            packet_count = db.conn.execute("SELECT count(*) FROM packets").fetchone()[0]
        destination = self.work / "primary-assignment"
        recovered = self.call("packet-recovered", "work", "inspect", self.db,
                              "--packet", packet_id, "--out", destination)
        self.call("packet-reused", "work", "inspect", self.db, "--packet", packet_id, "--out", destination)
        with storage.Database(self.db) as db:
            assert packet_count == db.conn.execute("SELECT count(*) FROM packets").fetchone()[0]
        assert blocked.read_text(encoding="utf-8") == "Preserve this existing user file."
        manifest = self.read(destination, "coordinator-manifest.json")
        worker = self.read(destination, "response-scaffold.json")
        tasks = {task["id"]: task for task in manifest["work"]["tasks"]}
        derivation = next(task for task in tasks.values() if task["kind"] == "derivation")
        for row in worker["results"]:
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Synthetic fixture comparison of the registered statement.", evidence_refs=["anc_lem"])
            else:
                row.update(state="complete", outcome="gap", reasoning="Synthetic negative examination: the written induction omits its base case and induction step.",
                           evidence_refs=["anc_lem_proof"])
        with storage.Database(self.db) as db:
            end = len(db.head("anchors", "anc_lem_proof").body["excerpt"])
        worker["coverage"] = [{"argument_id": "arg_lem", "anchor_id": "anc_lem_proof", "start_offset": 0,
            "end_offset": end, "classification": "substantive", "claim_refs": [R("items", "itm_lem")],
            "check_task_ids": [derivation["id"]], "existing_check_refs": [], "replaces": None,
            "note": "The synthetic negative derivation check covers the complete captured lemma proof."}]
        envelope = self.read(destination, "submission-envelope-template.json")
        assert envelope["request_id"] == recovered["initial_request_id"]
        envelope["reviewer"] = "primary-1"
        envelope_path = self.json_file("primary-submission.json", envelope)
        worker_path = self.json_file("primary-response.json", worker)
        # Inject only the interruption. The command's native intake remains real.
        with patch.object(controller, "accept_in_transaction", side_effect=RuntimeError("synthetic interruption after durable intake")):
            interrupted = cli.cmd_work_submit(argparse.Namespace(db=str(self.db), submission=str(envelope_path), response=str(worker_path)))
        assert interrupted["state"] == "received" and interrupted["stored"]
        write_json(self.work / "receipt-intake-interrupted.json", interrupted)
        self.steps["intake-interrupted"] = interrupted
        inspection = self.call("intake-recovered", "work", "inspect", self.db,
            "--request", envelope["request_id"], "--out", self.work / "recovered-intake")
        assert inspection["state"] == "received"
        for name, original in (("submission-envelope.json", envelope_path), ("worker-response.json", worker_path)):
            assert (self.work / "recovered-intake" / name).read_bytes() == original.read_bytes()
        accepted = self.call("primary-accepted", "work", "submit", self.db,
            "--submission", envelope_path, "--response", worker_path)
        assert accepted["state"] == "accepted", accepted
        replay = self.call("primary-exact-replay", "work", "submit", self.db,
            "--submission", envelope_path, "--response", worker_path)
        assert accepted == replay

    def complete(self):
        qualification = _qualification_receipt(self.request_id())
        body = qualification["edits"][0]["body"]
        body["profile"].update(provider="synthetic", model="software-fixture")
        body["limitations"] = ["Synthetic software fixture only. This is not genuine reviewer qualification evidence."]
        self.call("synthetic-qualification", "qualification", "record", self.db,
                  "--receipt", self.json_file("synthetic-qualification.json", qualification))
        packet, _ = self.get("items:itm_lem")
        with storage.Database(self.db) as db:
            audit = db.head("audits", AUDIT)
        self.call("attach-qualification", "apply", self.db, "--batch", self.json_file("attach-qualification.json",
            self.batch([edit("replace", "audits", AUDIT, dict(audit.body, qualification_id="qua_r1"), audit.version)], packet["packet_id"])))
        destination = self.work / "independent-assignment"
        prepared = self.call("independent-prepare", "work", "prepare", self.db,
            "--audit", AUDIT, "--mode", "independent", "--focus", "items:itm_lem", "--out", destination)
        assert prepared["prepared"], prepared
        assert "submission-envelope-template.json" not in prepared["worker_delivery_files"]
        assert "coordinator-guidance.json" not in prepared["worker_delivery_files"]
        worker = self.read(destination, "response-scaffold.json")
        worker.update(coverage_note="Synthetic independent source-only examination of the complete captured lemma proof.", judgments=[{
            "kind": "composition", "target": {"source_anchor_id": "anc_lem_proof", "description": "The full written lemma proof."},
            "state": "complete", "outcome": "gap", "reasoning": "Synthetic independent negative opinion: neither the induction base case nor its inductive implication is written.",
            "evidence_refs": ["anc_lem_proof"], "conditions": [], "next_action": None, "supersedes": None}])
        envelope = self.read(destination, "submission-envelope-template.json")
        envelope.update(reviewer="checker-A", qualification_id="qua_r1", exposure="source_only",
                        exposure_note="Synthetic software test of source-only provenance.")
        envelope_path, worker_path = self.json_file("independent-submission.json", envelope), self.json_file("independent-response.json", worker)
        original = worker_path.read_bytes()
        saved = self.call("independent-submit", "work", "submit", self.db,
                         "--submission", envelope_path, "--response", worker_path)
        assert saved["state"] == "needs_revision" and saved["pending"], saved
        authority, _ = self.get("items:itm_lem")
        mapping_path = self.work / "mapping-template.json"
        self.call("mapping-template", "review", "mapping-template", self.db,
            "--response", saved["response_id"], "--packet", authority["packet_id"], "--out", mapping_path)
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))["template"]
        mapping["reviewer"] = "coordinator"
        mapping["entries"][0].update(target=R("arguments", "arg_lem"), rationale="The independently examined source passage is exactly the registered lemma argument.")
        self.call("independent-mapped", "review", "map", self.db, "--response", saved["response_id"],
                  "--mapping", self.json_file("mapping.json", mapping))
        with storage.Database(self.db) as db:
            response = db.head("responses", saved["response_id"])
            assert db.get_blob(response.body["original_blob"]) == original
        destination = self.work / "reconcile-assignment"
        prepared = self.call("reconcile-prepare", "work", "prepare", self.db,
            "--audit", AUDIT, "--mode", "reconcile", "--focus", "items:itm_lem", "--out", destination)
        self.call("reconcile-inspect", "work", "inspect", self.db, "--packet", prepared["packet_id"], "--out", destination)
        guidance = self.read(destination, "coordinator-guidance.json")
        candidate = next(row for row in guidance["reconciliation_candidates"] if row["target"] == R("arguments", "arg_lem"))
        assert candidate["has_both_roles"]
        assert {op["outcome"] for role in ("primary", "independent") for op in candidate[f"{role}_opinions"]} == {"gap"}
        row = copy.deepcopy(guidance["reconciliation_row_template"])
        assert row["decision"] == row["rationale"] == ""
        row.update(target=candidate["target"], primary_checks=candidate["primary_checks"],
            independent_checks=candidate["independent_checks"], decision="agree",
            rationale="Compared the actual synthetic opinions: both identify the same missing induction base case and inductive implication, on the same written argument, without added conditions.", adjudicator="coordinator")
        worker = self.read(destination, "response-scaffold.json")
        worker["edits"] = [edit("create", "reconciliations", "rec_explicit", row)]
        envelope = self.read(destination, "submission-envelope-template.json")
        assert worker["request_id"] == envelope["request_id"] == prepared["initial_request_id"]
        envelope["reviewer"] = "coordinator"
        saved = self.call("reconcile-submit", "work", "submit", self.db,
            "--submission", self.json_file("reconcile-submission.json", envelope),
            "--response", self.json_file("reconcile-response.json", worker))
        assert saved["state"] == "accepted", saved

    def run(self):
        self.author()
        self.primary()
        incomplete = self.call("incomplete-status", "status", self.db, "--audit", AUDIT)
        assert not incomplete["process_complete"]
        self.call("incomplete-work", "work", "list", self.db, "--audit", AUDIT)
        self.call("incomplete-checkpoint", "checkpoint", self.db, "--audit", AUDIT,
                  "--out", self.root / "incomplete.html")
        self.call("incomplete-release-refused", "release", self.db, "--audit", AUDIT,
                  "--out", self.root / "refused-release", expect=2)
        self.call("incomplete-backup", "backup", self.db, "--out", self.root / "incomplete.db")
        self.complete()
        complete = self.call("complete-status", "status", self.db, "--audit", AUDIT)
        assert complete["process_complete"], complete
        self.call("validate", "validate", self.db)
        self.call("complete-work", "work", "list", self.db, "--audit", AUDIT)
        self.call("complete-checkpoint", "checkpoint", self.db, "--audit", AUDIT,
                  "--out", self.root / "complete.html")
        self.call("release", "release", self.db, "--audit", AUDIT, "--out", self.root / "release")
        with storage.Database(self.db) as db:
            judgments = [{"id": record.id, "role": record.body["role"], "outcome": record.body["outcome"]}
                         for record in db.heads("checks")]
        assert len(judgments) == 3 and all(row["outcome"] == "gap" for row in judgments)
        result = {"synthetic_only": True, "qualification_is_real": False,
            "complete_database": str(self.db.resolve()), "complete_report": str((self.root / "complete.html").resolve()),
            "incomplete_database": str((self.root / "incomplete.db").resolve()), "incomplete_report": str((self.root / "incomplete.html").resolve()),
            "release": str((self.root / "release").resolve()), "command_receipts": len(self.steps),
            "complete": complete["process_complete"], "incomplete": incomplete["process_complete"], "judgments": judgments,
            "scope": "Focused lemma only; the theorem proof is explicitly excluded.",
            "recoveries": ["Saved packet recovered after real artifact I/O failure without another packet.",
                "Injected processing interruption retained original intake; CLI inspection and exact replay completed it."]}
        write_json(self.root / "summary.json", result)
        return result


@unittest.skipUnless(node_available(), "rendering lifecycle reports needs shared node")
class TargetedWorkflowTests(unittest.TestCase):
    def test_native_cli_recovers_and_completes_negative_focused_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            result = TargetedLifecycle(directory).run()
            self.assertTrue(result["complete"])
            self.assertFalse(result["incomplete"])
            self.assertEqual(3, len(result["judgments"]))
            self.assertFalse(result["qualification_is_real"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--artifacts":
        print(json.dumps(TargetedLifecycle(Path(sys.argv[2])).run(), indent=2))
    else:
        unittest.main()
