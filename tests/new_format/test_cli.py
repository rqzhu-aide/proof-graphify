"""The command surface and exit-code contract of ``paper_core.cli`` (implementation-handoff 5).

Every command runs in a real subprocess, so the process exit code, the single JSON object on stdout
and the diagnostics on stderr are pinned exactly as an operator sees them. The expensive two-item
audit database is built once for the whole module *through the CLI itself* and snapshotted at two
stages; tests that mutate it copy the file first, and every failure path runs on its own throwaway
database so a refusal can be shown to have written nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import support
from support import (CLI_ENV, GLOBAL_TASKS, OVERVIEW, OVERVIEW_EXAMPLE, PAPER_TEX, R, TempCase, edit, locator,
                     node_available, rmtree_force, run_cli, sha, write_json)
from paper_core import storage
from paper_core.bundle import MANIFEST_NAME, build_manifest, bundle_files, manifest_text
from paper_core.cli import build_parser
from paper_core.ids import PREFIXES

ITEMS = ("items:itm_lem", "items:itm_thm")
AUDIT = "aud_1"
PRIMARY_CHECKS = ("chk_comp_lem", "chk_comp_thm", "chk_der_lem", "chk_der_thm", "chk_app")

# Every leaf command the CLI offers, and the ones that do not carry the wrapper's --run-id option.
LEAF_COMMANDS = {
    "init", "attach", "migrate-overview", "source capture", "source anchor", "source review", "source diagnostics", "ids", "get",
    "apply", "compare", "review submit", "review map", "review reconcile", "qualification record", "changes",
    "status", "validate", "checkpoint", "release", "export", "backup", "import-legacy", "telemetry record",
    "telemetry summary", "version", "migrate", "work list", "work prepare", "work submit", "work inspect",
    "template", "review mapping-template", "work extend", "stage1 status", "stage1 prepare",
    "stage2 status", "stage2 prepare", "stage2 finalize", "stage3 build"}
NO_DATABASE_COMMANDS = {"ids", "version", "stage3 build"}
TELEMETRY_COMMANDS = {"telemetry record", "telemetry summary"}
TOP_LEVEL_COMMANDS = {name.split(" ")[0] for name in LEAF_COMMANDS}


def help_commands(stdout: str) -> set:
    """The command names argparse lists in the COMMAND block of ``--help``."""
    lines, collecting, found = stdout.splitlines(), False, set()
    for line in lines:
        if line.startswith("positional arguments:"):
            collecting = True
            continue
        if collecting:
            if line and not line.startswith(" "):
                break
            match = re.match(r"^ {4}(\S+)", line)
            if match:
                found.add(match.group(1))
    return found - {"COMMAND"}


# -- the shared CLI-built database --------------------------------------------------------------------
class _CliPaper:
    """Builds the two-item audit database with the command line and keeps every receipt it printed."""

    def __init__(self, root):
        self.root = Path(root)
        self.work = self.root / "build"
        self.work.mkdir(parents=True, exist_ok=True)
        self.source_root = self.root / "src"
        self.source_root.mkdir(parents=True, exist_ok=True)
        (self.source_root / "paper.tex").write_text(PAPER_TEX, encoding="utf-8")
        self.db = self.work / "paper.db"
        self.snapshots = {}
        self.steps = {}
        self.counter = 0

    # -- plumbing --------------------------------------------------------------------------------
    def request_id(self) -> str:
        self.counter += 1
        return f"req_cli_{self.counter}"

    def json_file(self, name, payload) -> Path:
        return write_json(self.work / name, payload)

    def batch(self, edits, packet_id) -> dict:
        return {"contract_version": 3, "request_id": self.request_id(), "packet_id": packet_id, "edits": edits}

    def get(self, *targets, mode="primary", name=None):
        """Run ``get --out`` and return ``(printed summary, packet written to disk)``."""
        self.counter += 1
        name = name or f"pkt_{self.counter}_{mode}.json"
        arguments = [self.db]
        for target in targets:
            arguments += ["--target", target]
        summary, _ = run_cli("get", *arguments, "--mode", mode, "--out", self.work / name)
        packet = json.loads((self.work / name).read_text(encoding="utf-8"))
        return summary, packet

    def pin(self, collection, id) -> dict:
        with storage.Database(self.db) as db:
            return {"collection": collection, "id": id, "version": db.head(collection, id).version}

    def snapshot(self, name) -> Path:
        target = self.root / f"{name}.db"
        shutil.copy2(self.db, target)
        self.snapshots[name] = target
        return target

    # -- stages ----------------------------------------------------------------------------------
    def build(self):
        step = self.steps
        step["init"], _ = run_cli("init", self.db, "--source-root", self.source_root, "--title", "CLI slice")
        self.paper_id = step["init"]["paper_id"]
        step["capture"], _ = run_cli("source", "capture", self.db, "--files",
                                     self.json_file("files.json", ["paper.tex"]))
        self.source_id = step["capture"]["sources"][0]["id"]
        author, _ = self.get(f"papers:{self.paper_id}", mode="author", name="pkt_author_anchor.json")
        step["anchors"], _ = run_cli("source", "anchor", self.db, "--request", self.json_file("anchors.json", {
            "contract_version": 3, "request_id": self.request_id(), "packet_id": author["packet_id"], "anchors": [
                {"id": "anc_lem", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(label="lem:a")},
                {"id": "anc_lem_proof", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(start=8, end=10)},
                {"id": "anc_thm", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(label="thm:b")},
                {"id": "anc_thm_proof", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(start=14, end=16)}]}))
        author, _ = self.get(f"papers:{self.paper_id}", mode="author", name="pkt_author_structure.json")
        step["structure"], _ = run_cli("apply", self.db, "--batch", self.json_file(
            "structure.json", self.batch(_structure_edits(), author["packet_id"])))
        step["status_overview"], _ = run_cli("status", self.db)
        step["validate_overview"], _ = run_cli("validate", self.db)
        step["qualification"], _ = run_cli("qualification", "record", self.db, "--receipt",
                                           self.json_file("qual.json", _qualification_receipt(self.request_id())))
        review_id = "srv_boundaries"
        source_review = edit("create", "source_reviews", review_id, {
            "purpose": "proof_boundary", "source_refs": [self.pin("sources", self.source_id)],
            "anchor_refs": [self.pin("anchors", "anc_lem_proof"), self.pin("anchors", "anc_thm_proof")],
            "decision": "accepted", "reviewer": "coordinator", "rationale": "Synthetic complete proof boundary fixture."})
        primary, _ = self.get(*ITEMS, name="pkt_boundary_review.json")
        step["boundary_review"], _ = run_cli("source", "review", self.db, "--request",
            self.json_file("boundary-review.json", self.batch([source_review], primary["packet_id"])))
        primary, _ = self.get(*ITEMS, name="pkt_audit.json")
        exact_records = []
        for name in ("lem", "thm"):
            exact_records.extend([
                edit("create", "target_specs", "tgt_" + name, {
                    "target": R("items", "itm_" + name), "statement_ref": self.pin("items", "itm_" + name),
                    "statement": None, "scope_id": None, "evidence_refs": ["anc_" + name],
                    "state": "registered", "fidelity_ref": None}),
                edit("create", "proof_boundaries", "bnd_" + name, {
                    "target": R("items", "itm_" + name), "argument_ids": ["arg_" + name],
                    "anchor_refs": [self.pin("anchors", "anc_" + name + "_proof")],
                    "source_review_ref": {"collection": "source_reviews", "id": review_id, "version": 1},
                    "state": "complete"})])
        step["audit"], _ = run_cli("apply", self.db, "--batch", self.json_file("audit.json", self.batch(
            [edit("create", "audits", AUDIT, _audit_body(self.paper_id)), *exact_records], primary["packet_id"])))
        primary, check_packet = self.get(*ITEMS, name="pkt_checks.json")
        anchor_lengths = {r["ref"]["id"]: len(r["body"]["excerpt"]) for r in check_packet["records"]
                          if r["ref"]["collection"] == "anchors"}
        coverage = [edit("create", "coverage", f"cov_{name}", {
            "argument_id": f"arg_{name}", "anchor_id": f"anc_{name}_proof",
            "start_offset": 0, "end_offset": anchor_lengths[f"anc_{name}_proof"],
            "classification": "substantive", "claim_refs": [R("items", f"itm_{name}")],
            "check_ids": [f"chk_der_{name}"], "note": "The derivation covers this captured proof."})
            for name in ("lem", "thm")]
        step["checks"], _ = run_cli("apply", self.db, "--batch", self.json_file(
            "checks.json", self.batch(coverage + _check_edits(), primary["packet_id"])))
        primary, self.compare_packet = self.get(*ITEMS, name="pkt_compare.json")
        self.compare_batch = self.json_file("observations.json", self.batch(_observation_edits(),
                                                                            primary["packet_id"]))
        step["compare"], _ = run_cli("compare", self.db, "--packet", primary["packet_id"], "--batch",
                                     self.compare_batch)
        step["status_primary"], _ = run_cli("status", self.db, "--audit", AUDIT)
        self.snapshot("primary")
        step["independent_lem"] = self.independent_round(
            "itm_lem", {"source_anchor_id": "anc_lem_proof", "description": "the proof of the lemma"}, "arg_lem",
            "anc_lem_proof")
        step["independent_thm"] = self.independent_round("itm_thm", R("arguments", "arg_thm"), "arg_thm",
                                                         "anc_thm_proof")
        step["status_independent"], _ = run_cli("status", self.db, "--audit", AUDIT)
        reconcile, _ = self.get(*ITEMS, mode="reconcile", name="pkt_reconcile.json")
        step["reconcile"], _ = run_cli("review", "reconcile", self.db, "--batch", self.json_file(
            "reconciliations.json", self.batch([
                self.reconciliation("rec_lem", "arg_lem", "chk_comp_lem", step["independent_lem"]["check_id"]),
                self.reconciliation("rec_thm", "arg_thm", "chk_comp_thm", step["independent_thm"]["check_id"])],
                reconcile["packet_id"])))
        step["status_complete"], _ = run_cli("status", self.db, "--audit", AUDIT)
        self.complete_revision = step["status_complete"]["revision"]
        self.snapshot("complete")
        return self

    def independent_round(self, item_id, judgment_target, argument_id, anchor) -> dict:
        """One blinded packet, one preserved worker response, one coordinator mapping."""
        summary, packet = self.get(f"items:{item_id}", mode="independent", name=f"pkt_ind_{item_id}.json")
        worker = {"packet_id": summary["packet_id"], "covered_targets": [R("items", item_id)],
                  "coverage_note": "read the statement and proof from the source",
                  "exposure_report": {"status": "none_known", "note": ""},
                  "judgments": [{"target": judgment_target, "kind": "composition", "state": "complete",
                                 "outcome": "supported", "reasoning": "independent reading of the proof",
                                 "evidence_refs": [anchor], "conditions": [], "next_action": None,
                                 "supersedes": None}]}
        response = self.work / f"worker_{item_id}.json"
        response.write_bytes(json.dumps(worker).encode("utf-8"))
        submitted, _ = run_cli("review", "submit", self.db, "--submission", self.json_file(f"sub_{item_id}.json", {
            "contract_version": 3, "request_id": self.request_id(), "packet_id": summary["packet_id"],
            "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "source_only",
            "exposure_note": ""}), "--response", response)
        mapping_packet, _ = self.get(*ITEMS, name=f"pkt_map_{item_id}.json")
        mapped, _ = run_cli("review", "map", self.db, "--response", submitted["response_id"], "--mapping",
                            self.json_file(f"map_{item_id}.json", {
                                "contract_version": 3, "request_id": self.request_id(),
                                "packet_id": mapping_packet["packet_id"], "response_id": submitted["response_id"],
                                "entries": [{"judgment_index": 0, "target": R("arguments", argument_id),
                                             "rationale": "the proof passage is this argument"}],
                                "reviewer": "coord"}))
        return {"packet": packet, "submitted": submitted, "mapped": mapped,
                "check_id": mapped["checks"][0]["check_id"]}

    def reconciliation(self, rid, argument_id, primary_check, independent_check) -> dict:
        return edit("create", "reconciliations", rid, {
            "audit_id": AUDIT, "target": R("arguments", argument_id),
            "primary_checks": [self.pin("checks", primary_check)],
            "independent_checks": [self.pin("checks", independent_check)],
            "decision": "agree", "rationale": "adjudicated", "evidence_refs": [], "successor_checks": [],
            "supersedes": None, "adjudicator": "coord"})


def _structure_edits() -> list:
    def item(iid, kind, label, anchor, proof):
        return edit("create", "items", iid, {
            "kind": kind, "label": label, "caption": label,
            "statement": {"form": "verbatim", "text": label + " text"},
            "passages": [{"role": "statement", "anchor_id": anchor}, {"role": "proof", "anchor_id": proof}],
            "aliases": [], "uncertainty": None, "origin": "source", "owner_id": None, "scope_id": None})

    def argument(aid, target, final, anchor):
        return edit("create", "arguments", aid, {
            "target": R("items", target), "label": f"Proof of {target}", "origin": "source",
            "scope_id": "scp_plain", "final_group_id": final, "evidence_refs": [anchor],
            "lifecycle": "registered"})

    def group(gid, aid, conclusion, anchor):
        return edit("create", "groups", gid, {
            "argument_id": aid, "conclusion": R("items", conclusion), "kind": "joint", "scope_id": "scp_plain",
            "case_scope_ids": [], "discharges": [], "rationale": "one step", "evidence_refs": [anchor]})

    return [
        item("itm_lem", "lemma", "Lemma 1", "anc_lem", "anc_lem_proof"),
        item("itm_thm", "theorem", "Theorem 1", "anc_thm", "anc_thm_proof"),
        edit("create", "scopes", "scp_plain", {"argument_id": None, "parent_id": None, "assumptions": [],
                                               "binders": [], "conditions": [], "evidence_refs": []}),
        argument("arg_lem", "itm_lem", "grp_lem", "anc_lem_proof"),
        argument("arg_thm", "itm_thm", "grp_thm", "anc_thm_proof"),
        group("grp_lem", "arg_lem", "itm_lem", "anc_lem_proof"),
        group("grp_thm", "arg_thm", "itm_thm", "anc_thm_proof"),
        edit("create", "uses", "use_lem_thm", {
            "from": R("items", "itm_lem"), "to": R("items", "itm_thm"), "type": "dependency",
            "group_id": "grp_thm", "reason": "applied as stated",
            "needed_form": {"form": "verbatim", "text": "Lemma 1 text"}, "substitutions": [],
            "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})]


def _qualification_receipt(request_id) -> dict:
    evidence, case_ok, case_bad = b"calibration transcript", b'{"case":"valid-1"}', b'{"case":"invalid-1"}'
    import base64
    return {"contract_version": 3, "request_id": request_id,
            "edits": [edit("create", "qualifications", "qua_r1", {
                "reviewer": "checker-A",
                "profile": {"provider": "anthropic", "model": "claude-fable-5-1", "effort": "high", "tools": [],
                            "context_isolation": "fresh session, source only"},
                "protocol_version": "item-audit/1",
                "valid_case_results": [{"case_id": "valid-1", "response_blob": sha(case_ok), "outcome": "pass"}],
                "invalid_case_results": [{"case_id": "invalid-1", "response_blob": sha(case_bad),
                                          "outcome": "pass"}],
                "evidence_blob": sha(evidence), "qualified": True, "limitations": []})],
            "blobs": [{"sha256": sha(blob), "encoding": "base64", "data": base64.b64encode(blob).decode()}
                      for blob in (evidence, case_ok, case_bad)]}


def _audit_body(paper_id) -> dict:
    return {"paper_id": paper_id, "mode": "focused", "targets": [R("items", "itm_lem"), R("items", "itm_thm")],
            "exclusions": [], "protocol_version": "item-audit/1", "independent_required": True,
            "qualification_id": "qua_r1", "report_path": "reports/audit.html",
            "global_tasks": [dict(task) for task in GLOBAL_TASKS]}


def _check_edits() -> list:
    def check(cid, target, kind, evidence=()):
        return edit("create", "checks", cid, {
            "audit_id": AUDIT, "target": target, "kind": kind, "role": "primary", "reviewer": "primary-1",
            "protocol_version": "item-audit/1", "state": "complete", "outcome": "supported",
            "reasoning": "checked against the source", "evidence_refs": list(evidence), "conditions": [],
            "next_action": None, "response_id": None, "supersedes": None})

    return [check("chk_comp_lem", R("arguments", "arg_lem"), "composition", ["anc_lem_proof"]),
            check("chk_comp_thm", R("arguments", "arg_thm"), "composition", ["anc_thm_proof"]),
            check("chk_der_lem", R("groups", "grp_lem"), "derivation"),
            check("chk_der_thm", R("groups", "grp_thm"), "derivation"),
            check("chk_app", R("uses", "use_lem_thm"), "application")]


def _observation_edits() -> list:
    return [edit("create", "observations", oid, {
        "target": R(collection, iid), "result": "matched", "reviewer": "primary-1",
        "note": "statement matches the source", "evidence_refs": [anchor]})
        for oid, collection, iid, anchor in (("obs_lem", "items", "itm_lem", "anc_lem"),
            ("obs_thm", "items", "itm_thm", "anc_thm"),
            ("obs_exact_lem", "target_specs", "tgt_lem", "anc_lem"),
            ("obs_exact_thm", "target_specs", "tgt_thm", "anc_thm"))]


BUILT: _CliPaper = None
_ROOT: Path = None


def setUpModule():
    global BUILT, _ROOT
    _ROOT = Path(tempfile.mkdtemp(prefix="paper_core_cli_"))
    BUILT = _CliPaper(_ROOT).build()


def tearDownModule():
    if _ROOT is not None and _ROOT.exists():
        rmtree_force(_ROOT)


class BuiltCase(TempCase):
    """A test case that works on its own copy of the module's CLI-built database."""

    def db_copy(self, stage="complete") -> Path:
        target = self.path(f"{stage}.db")
        shutil.copy2(BUILT.snapshots[stage], target)
        return target

    def head_revision(self, db) -> int:
        payload, _ = run_cli("status", db)
        return payload["head_revision"]

    def request(self, edits, packet_id, name) -> Path:
        self._requests = getattr(self, "_requests", 0) + 1
        return write_json(self.path(name), {
            "contract_version": 3, "request_id": f"req_{self.id().rsplit('.', 1)[-1]}_{self._requests}",
            "packet_id": packet_id, "edits": edits})


# -- version, identifiers, usage ------------------------------------------------------------------
class TestVersionCommand(TempCase):

    def test_version_reports_the_core_and_contract_identity(self):
        """version names core 2.3.9, storage format 4 and contract proofcheck-records/4."""
        payload, _ = run_cli("version")
        self.assertEqual(payload["command"], "version")
        self.assertEqual(payload["core_version"], "2.3.9")
        self.assertEqual(payload["storage_format"], 4)
        self.assertEqual(payload["contract_version"], 4)
        self.assertEqual(payload["contract"], "proofcheck-records/4")
        self.assertEqual(payload["packet_version"], 2)
        self.assertEqual(payload["projection_version"], 2)
        self.assertEqual(payload["python"], ".".join(str(p) for p in sys.version_info[:3]))

    def test_version_reports_a_bundle_verification_block(self):
        """The repository source tree carries no manifest, so every field of the block is empty."""
        payload, _ = run_cli("version")
        self.assertEqual(payload["bundle"], {
            "present": False, "ok": None, "source_identity": None, "file_count": None,
            "missing": [], "unexpected": [], "changed": [], "constants_match": None})

    def _bundled_copy(self):
        """A copy of the core package outside the repository, carrying its own generated manifest."""
        root = self.path("bundle")
        package = root / "paper_core"
        shutil.copytree(Path(storage.__file__).resolve().parent, package,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", MANIFEST_NAME))
        manifest = build_manifest(bundle_files(package))
        (package / MANIFEST_NAME).write_text(manifest_text(manifest), encoding="utf-8", newline="\n")
        return root, manifest

    def test_version_verifies_a_bundle_against_its_manifest(self):
        """A bundled copy verifies; a changed file and a stray file are both named, and ok turns false."""
        root, manifest = self._bundled_copy()
        env = dict(CLI_ENV, PYTHONPATH=str(root))
        payload, _ = run_cli("version", env=env)
        bundle = payload["bundle"]
        self.assertIs(bundle["present"], True)
        self.assertIs(bundle["ok"], True)
        self.assertIs(bundle["constants_match"], True)
        self.assertEqual(bundle["source_identity"], manifest["source_identity"])
        self.assertEqual(bundle["file_count"], manifest["file_count"])
        self.assertGreater(bundle["file_count"], 10)
        self.assertEqual((bundle["missing"], bundle["unexpected"], bundle["changed"]), ([], [], []))

        tampered = root / "paper_core" / "queries.py"
        tampered.write_bytes(tampered.read_bytes() + b"\n# a byte the manifest never saw\n")
        (root / "paper_core" / "stowaway.py").write_text("# not in the manifest\n", encoding="utf-8",
                                                         newline="\n")
        payload, _ = run_cli("version", env=env)
        bundle = payload["bundle"]
        self.assertIs(bundle["ok"], False)
        self.assertEqual(bundle["changed"], ["queries.py"])
        self.assertEqual(bundle["unexpected"], ["stowaway.py"])
        self.assertEqual(bundle["missing"], [])
        self.assertEqual(bundle["source_identity"], manifest["source_identity"],
                         "the manifest still reports the identity it was built with")

    def test_version_takes_no_positional_argument(self):
        """version reads no database, so a stray positional is a USAGE failure."""
        stdout, stderr = run_cli("version", "extra", expect=2, raw=True)
        self.assertEqual(json.loads(stdout)["error"]["code"], "USAGE")
        self.assertIn("unrecognized arguments", stdout)
        self.assertIn("USAGE", stderr)


class TestIdsCommand(TempCase):

    def test_ids_mints_distinct_prefixed_identifiers(self):
        """ids --kind items --count 3 returns three distinct itm_ identifiers."""
        payload, stderr = run_cli("ids", "--kind", "items", "--count", "3")
        self.assertEqual(payload["command"], "ids")
        self.assertEqual(payload["kind"], "items")
        self.assertEqual(len(payload["ids"]), 3)
        self.assertEqual(len(set(payload["ids"])), 3)
        self.assertTrue(all(i.startswith("itm_") for i in payload["ids"]), payload["ids"])
        self.assertEqual(stderr, "")

    def test_ids_rejects_an_unknown_kind(self):
        """An unknown id kind is a USAGE failure with exit 2, not a minted identifier."""
        payload, stderr = run_cli("ids", "--kind", "bogus", expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertIn("bogus", payload["error"]["message"])
        self.assertTrue(stderr.startswith("USAGE: "), stderr)

    def test_ids_rejects_a_count_outside_one_to_a_thousand(self):
        """--count is bounded at 1..1000 on both ends."""
        for count in ("0", "1001", "-3"):
            with self.subTest(count=count):
                payload, _ = run_cli("ids", "--kind", "items", "--count", count, expect=2)
                self.assertEqual(payload["error"]["code"], "USAGE")
                self.assertEqual(payload["error"]["message"], "--count must be between 1 and 1000")


class TestUsageErrors(TempCase):
    """Argument problems are reported as USAGE with exit 2 before any database is touched."""

    def test_unknown_command_is_a_usage_error(self):
        """An unknown command exits 2 with code USAGE naming the rejected choice."""
        payload, stderr = run_cli("frobnicate", expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertIn("invalid choice: 'frobnicate'", payload["error"]["message"])
        self.assertTrue(payload["error"]["message"].startswith("paper_audit.py: "), payload["error"]["message"])
        self.assertEqual(payload["error"]["records"], [])
        self.assertIn("frobnicate", stderr)

    def test_missing_required_argument_is_a_usage_error(self):
        """A missing positional database or required option exits 2 with code USAGE."""
        payload, _ = run_cli("status", expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertEqual(payload["error"]["message"], "paper_audit.py status: the following arguments are required: db")
        payload, _ = run_cli("checkpoint", self.path("nowhere.db"), expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertIn("required: --out", payload["error"]["message"])

    def test_get_rejects_bad_targets_and_modes_without_creating_the_database(self):
        """get validates its target syntax, collection and mode before opening any file."""
        missing = self.path("never.db")
        for arguments, fragment in (
                ((), "at least one --target"),
                (("--target", "nocolon"), "targets are written COLLECTION:ID"),
                (("--target", "sprockets:x"), "unknown collection"),
                (("--target", "items:itm_lem", "--mode", "sneaky"), "--mode must be one of")):
            with self.subTest(arguments=arguments):
                payload, _ = run_cli("get", missing, *arguments, expect=2)
                self.assertEqual(payload["error"]["code"], "USAGE")
                self.assertIn(fragment, payload["error"]["message"])
        self.assertFalse(missing.exists(), "a usage error must not create the database")

    def test_get_extend_requires_a_context_request_and_no_targets(self):
        """--extend takes its added targets from --request, never from --target."""
        missing = self.path("never.db")
        payload, _ = run_cli("get", missing, "--extend", "pkt_x", expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertIn("--request CONTEXT.json", payload["error"]["message"])
        payload, _ = run_cli("get", missing, "--extend", "pkt_x", "--target", "items:itm_lem", expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertIn("takes the added targets from the context request", payload["error"]["message"])
        self.assertFalse(missing.exists())

    def test_help_lists_the_whole_command_surface(self):
        """--help exits 0 and names every top-level command."""
        stdout, stderr = run_cli("--help", raw=True)
        self.assertEqual(stderr, "")
        for command in sorted({name.split(" ")[0] for name in LEAF_COMMANDS}):
            self.assertIn(command, stdout)


class TestCommandSurface(TempCase):
    """The set of commands and which of them carry the wrapper's --run-id option."""

    @staticmethod
    def _leaves(parser, prefix=()):
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not actions:
            yield " ".join(prefix), parser
            return
        for action in actions:
            for name, child in action.choices.items():
                yield from TestCommandSurface._leaves(child, prefix + (name,))

    def test_the_command_surface_is_exactly_the_documented_set(self):
        """No command appears or disappears from the CLI without this lane noticing."""
        self.assertEqual({name for name, _ in self._leaves(build_parser())}, LEAF_COMMANDS)

    def test_every_database_command_accepts_run_id(self):
        """Each command that takes a database positional also accepts --run-id for telemetry."""
        for name, parser in self._leaves(build_parser()):
            positionals = [a.dest for a in parser._actions if not a.option_strings]
            options = {o for a in parser._actions for o in a.option_strings}
            with self.subTest(command=name):
                if name in NO_DATABASE_COMMANDS or name == "import-legacy":
                    self.assertNotIn("db", positionals)
                    continue
                self.assertIn("db", positionals, f"{name} should take the database positionally")
                self.assertIn("--run-id", options)

    def test_only_telemetry_commands_own_their_run_id(self):
        """telemetry's own --run-id names the run being measured, so it records no command event."""
        own = {name for name, parser in self._leaves(build_parser())
               if parser.get_default("telemetry_own") is True}
        self.assertEqual(own, TELEMETRY_COMMANDS)

    def test_import_legacy_rejects_run_id(self):
        """import-legacy writes a brand new database and takes no --run-id."""
        payload, _ = run_cli("import-legacy", self.path("folder"), "--db", self.path("new.db"),
                             "--map", self.path("map.json"), "--run-id", "run_x", expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertIn("unrecognized arguments: --run-id run_x", payload["error"]["message"])
        self.assertFalse(self.path("new.db").exists())


# -- init ------------------------------------------------------------------------------------------
class TestInit(TempCase):

    def setUp(self):
        super().setUp()
        self.source_root = self.path("src")
        self.source_root.mkdir(parents=True, exist_ok=True)
        (self.source_root / "paper.tex").write_text(PAPER_TEX, encoding="utf-8")

    def test_init_creates_the_paper_record_at_revision_one(self):
        """init commits exactly one paper record and reports revision 1."""
        db = self.path("paper.db")
        payload, stderr = run_cli("init", db, "--source-root", self.source_root, "--title", "Fresh paper")
        self.assertEqual(payload["command"], "init")
        self.assertEqual(payload["revision"], 1)
        self.assertTrue(payload["paper_id"].startswith("pap_"), payload["paper_id"])
        self.assertEqual([(c["collection"], c["op"], c["version"]) for c in payload["receipt"]["changed"]],
                         [("papers", "create", 1)])
        self.assertEqual(stderr, "")
        self.assertTrue(db.is_file())
        status, _ = run_cli("status", db)
        self.assertEqual(status["paper"]["title"], "Fresh paper")
        self.assertEqual(status["paper"]["source_root"], self.source_root.resolve().as_posix())

    def test_init_refuses_to_overwrite_an_existing_database(self):
        """A second init on the same path exits 2 and leaves the first paper untouched."""
        db = self.path("paper.db")
        first, _ = run_cli("init", db, "--source-root", self.source_root, "--title", "First")
        payload, stderr = run_cli("init", db, "--source-root", self.source_root, "--title", "Second", expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertIn("refusing to overwrite existing file", payload["error"]["message"])
        self.assertIn("INVALID_REQUEST", stderr)
        status, _ = run_cli("status", db)
        self.assertEqual(status["paper"]["title"], "First")
        self.assertEqual(status["paper"]["id"], first["paper_id"])
        self.assertEqual(status["head_revision"], 1)

    def test_init_reports_an_unavailable_source_root_with_exit_five(self):
        """A source root that is not a directory exits 5 and creates no database."""
        db = self.path("paper.db")
        payload, stderr = run_cli("init", db, "--source-root", self.path("missing"), "--title", "x", expect=5)
        self.assertEqual(payload["error"]["code"], "SOURCE_UNAVAILABLE")
        self.assertIn("source root is not a directory", payload["error"]["message"])
        self.assertIn("SOURCE_UNAVAILABLE", stderr)
        self.assertFalse(db.exists(), "a refused init must not leave a database behind")


# -- the receipts the build itself printed -----------------------------------------------------------
class TestBuildReceipts(BuiltCase):
    """Assertions on the receipts printed while the shared database was built through the CLI."""

    def test_each_accepted_batch_allocates_exactly_one_revision(self):
        """init, capture, anchor, apply, qualification and compare each advance the revision by one."""
        step = BUILT.steps
        self.assertEqual(step["init"]["revision"], 1)
        self.assertEqual(step["capture"]["receipt"]["revision"], 2)
        self.assertEqual(step["anchors"]["receipt"]["revision"], 3)
        self.assertEqual(step["structure"]["revision"], 4)
        self.assertEqual(step["qualification"]["revision"], 5)
        self.assertEqual(step["boundary_review"]["receipt"]["revision"], 6)
        self.assertEqual(step["audit"]["revision"], 7)
        self.assertEqual(step["checks"]["revision"], 8)
        self.assertEqual(step["compare"]["revision"], 9)

    def test_source_capture_registers_the_listed_file(self):
        """source capture returns one source revision for the single listed relative path."""
        capture = BUILT.steps["capture"]
        self.assertEqual(capture["command"], "source capture")
        self.assertEqual([s["path"] for s in capture["sources"]], ["paper.tex"])
        self.assertTrue(BUILT.source_id.startswith("src_"), BUILT.source_id)

    def test_source_anchor_binds_every_locator_it_was_given(self):
        """Label locators resolve by label match and line locators by exact lines."""
        anchors = BUILT.steps["anchors"]
        self.assertEqual(anchors["command"], "source anchor")
        self.assertEqual({a["id"]: a["method"] for a in anchors["anchors"]},
                         {"anc_lem": "label_match", "anc_lem_proof": "exact_lines",
                          "anc_thm": "label_match", "anc_thm_proof": "exact_lines"})

    def test_apply_reports_every_created_record_in_its_receipt(self):
        """The eight input records normalize to nine canonical records at version 1."""
        changed = BUILT.steps["structure"]["receipt"]["changed"]
        self.assertEqual([(c["collection"], c["id"], c["op"], c["version"]) for c in changed], [
            ("items", "itm_lem", "create", 1), ("items", "itm_thm", "create", 1),
            ("scopes", "scp_plain", "create", 1), ("arguments", "arg_lem", "create", 1),
            ("arguments", "arg_thm", "create", 1), ("groups", "grp_lem", "create", 1),
            ("groups", "grp_thm", "create", 1), ("uses", "use_lem_thm", "create", 1),
            ("application_details", "use_lem_thm", "create", 1)])

    def test_an_independent_packet_carries_no_checks(self):
        """The blinded packet a worker receives contains no primary judgments."""
        for key in ("independent_lem", "independent_thm"):
            packet = BUILT.steps[key]["packet"]
            with self.subTest(round=key):
                self.assertEqual(packet["mode"], "independent")
                self.assertEqual([r["ref"] for r in packet["records"] if r["ref"]["collection"] == "checks"], [])

    def test_review_submit_keeps_an_unmappable_judgment_pending(self):
        """A judgment the packet read set cannot resolve is preserved as needs_revision."""
        submitted = BUILT.steps["independent_lem"]["submitted"]
        self.assertEqual(submitted["command"], "review submit")
        self.assertEqual(submitted["state"], "needs_revision")
        self.assertEqual(submitted["exposure"], "source_only")
        self.assertEqual([p["judgment_index"] for p in submitted["pending"]], [0])
        self.assertIn("awaits mapping", submitted["pending"][0]["reason"])
        self.assertEqual(submitted["checks"], [])

    def test_review_map_accepts_the_response_and_derives_the_check(self):
        """Mapping a pending judgment to a canonical target closes the response and mints its check."""
        mapped = BUILT.steps["independent_lem"]["mapped"]
        self.assertEqual(mapped["command"], "review map")
        self.assertEqual(mapped["state"], "accepted")
        self.assertEqual(len(mapped["checks"]), 1)
        self.assertEqual(mapped["checks"][0]["judgment_index"], 0)
        self.assertTrue(mapped["checks"][0]["check_id"].startswith("chk_"))

    def test_reconcile_records_one_reconciliation_per_argument(self):
        """review reconcile commits both reconciliations in a single revision."""
        receipt = BUILT.steps["reconcile"]["receipt"]
        self.assertEqual(BUILT.steps["reconcile"]["command"], "review reconcile")
        self.assertEqual(sorted(c["id"] for c in receipt["changed"] if c["collection"] == "reconciliations"),
                         ["rec_lem", "rec_thm"])
        self.assertEqual(BUILT.steps["reconcile"]["revision"], receipt["revision"])


# -- status and validate ------------------------------------------------------------------------------
class TestStatusAndValidate(BuiltCase):

    def test_status_before_an_audit_reports_overview_mode(self):
        """With no audit registered, status reports overview mode and no audit."""
        status = BUILT.steps["status_overview"]
        self.assertEqual(status["command"], "status")
        self.assertEqual(status["mode"], "overview")
        self.assertIsNone(status["audit"])
        self.assertIs(status["process_complete"], False)
        self.assertEqual(status["counts"]["items"], 2)
        self.assertEqual(status["counts"]["uses"], 1)
        self.assertEqual(status["paper"]["id"], BUILT.paper_id)
        storage_block = dict(status["storage"])
        self.assertIsInstance(storage_block.pop("metadata"), dict)
        self.assertEqual(storage_block, {"storage_format": 4, "contract_version": 4,
                                         "contract": "proofcheck-records/4", "core_version": "2.3.9",
                                         "projection_version": 2})

    def test_an_incomplete_assessment_is_a_successful_status_query(self):
        """Half-finished mathematics exits 0 with process_complete false, never as a command failure."""
        status = BUILT.steps["status_primary"]
        self.assertNotIn("error", status)
        self.assertIs(status["process_complete"], False)
        self.assertEqual(status["mode"], "focused")
        self.assertEqual(status["audit"]["id"], AUDIT)
        self.assertIs(status["audit"]["independent_required"], True)
        self.assertEqual(status["progress"]["required_obligations"], 13)
        self.assertEqual(status["progress"]["completed_current_obligations"], 9)
        self.assertEqual(len(status["obligations"]["unsatisfied"]), 4)
        self.assertTrue(all(o.startswith("obl_") for o in status["obligations"]["unsatisfied"]))
        self.assertEqual({key: value["state"] for key, value in status["assessments"].items()
                          if key.startswith("items:")}, {"items:itm_lem": "green", "items:itm_thm": "green"})

    def test_status_reports_pending_independent_review_before_reconciliation(self):
        """An unreconciled independent check leaves the item's independent indicator pending."""
        status = BUILT.steps["status_independent"]
        self.assertEqual(status["independent"], {"items:itm_lem": "pending", "items:itm_thm": "pending"})
        self.assertIs(status["process_complete"], False)

    def test_status_reports_a_complete_process_after_reconciliation(self):
        """Reconciling both arguments satisfies every required obligation."""
        status = BUILT.steps["status_complete"]
        self.assertIs(status["process_complete"], True)
        self.assertEqual(status["obligations"]["unsatisfied"], [])
        self.assertEqual(len(status["obligations"]["required"]), 13)
        self.assertEqual(status["progress"], {"completed_current_obligations": 13, "draft_checks": 0,
                                              "major_results": 2, "process_complete": True,
                                              "required_obligations": 13, "source_unbound_items": 0})
        self.assertEqual(set(status["independent"].values()), {"complete"})
        self.assertEqual(status["problems"], [])
        self.assertEqual(status["source_limits"], [])

    def test_status_rejects_an_unknown_audit(self):
        """--audit naming a record that is not live exits 2 with AUDIT_UNKNOWN."""
        payload, _ = run_cli("status", BUILT.snapshots["complete"], "--audit", "aud_missing", expect=2)
        self.assertEqual(payload["error"]["code"], "AUDIT_UNKNOWN")
        self.assertIn("aud_missing", payload["error"]["message"])

    def test_status_rejects_a_snapshot_outside_the_revision_range(self):
        """--snapshot outside 1..head exits 2 with REVISION_RANGE."""
        for snapshot in ("0", "999"):
            with self.subTest(snapshot=snapshot):
                payload, _ = run_cli("status", BUILT.snapshots["complete"], "--snapshot", snapshot, expect=2)
                self.assertEqual(payload["error"]["code"], "REVISION_RANGE")

    def test_status_of_an_earlier_snapshot_reports_that_revision(self):
        """A snapshot query answers from the historical revision, not from the head."""
        payload, _ = run_cli("status", BUILT.snapshots["complete"], "--snapshot", "4")
        self.assertEqual(payload["revision"], 4)
        self.assertEqual(payload["head_revision"], BUILT.complete_revision)
        self.assertEqual(payload["mode"], "overview")
        self.assertIsNone(payload["audit"])

    def test_validate_accepts_the_built_snapshot(self):
        """validate exits 0 with ok true and no errors for a healthy database."""
        payload, stderr = run_cli("validate", BUILT.snapshots["complete"])
        self.assertEqual(payload["command"], "validate")
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["revision"], BUILT.complete_revision)
        self.assertEqual(payload["integrity"]["integrity"], ["ok"])
        self.assertEqual(stderr, "")

    def test_validate_of_the_overview_stage_is_also_clean(self):
        """The structure-only snapshot validates before any audit exists."""
        payload = BUILT.steps["validate_overview"]
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["records"]["items"], 2)


class TestStdoutAndStderrContract(BuiltCase):
    """Exactly one JSON object on stdout; diagnostics only on stderr."""

    def test_successful_commands_print_one_json_object_and_nothing_on_stderr(self):
        """A success writes a single trailing-newline JSON object to stdout and no diagnostics."""
        db = BUILT.snapshots["complete"]
        for command in (("version",), ("status", db), ("validate", db), ("changes", db, "--since", "0"),
                        ("telemetry", "summary", db)):
            with self.subTest(command=command[0]):
                stdout, stderr = run_cli(*command, raw=True)
                self.assertEqual(stderr, "")
                self.assertTrue(stdout.endswith("\n"))
                payload = json.loads(stdout)
                self.assertIsInstance(payload, dict)
                self.assertNotIn("error", payload)

    def test_failing_commands_still_print_one_json_object_and_diagnose_on_stderr(self):
        """A failure prints the error envelope on stdout and "CODE: message" on stderr."""
        stdout, stderr = run_cli("status", BUILT.snapshots["complete"], "--snapshot", "999", expect=2, raw=True)
        payload = json.loads(stdout)
        self.assertEqual(set(payload), {"error"})
        self.assertTrue(set(payload["error"]) >= {"code", "message", "records"}, payload)
        self.assertEqual(stderr.splitlines()[0],
                         f"{payload['error']['code']}: {payload['error']['message']}")

    def test_error_records_are_echoed_to_stderr_for_the_operator(self):
        """Every record in the error envelope is also written to stderr as JSON."""
        db = self.db_copy("primary")
        payload, stderr = run_cli("release", db, "--audit", AUDIT, "--out", self.path("release"), expect=2)
        self.assertEqual(payload["error"]["code"], "RELEASE_BLOCKED")
        lines = stderr.splitlines()
        self.assertEqual(len(lines), 1 + len(payload["error"]["records"]))
        for record, line in zip(payload["error"]["records"], lines[1:]):
            self.assertEqual(json.loads(line.strip()), record)


# -- release refusals ---------------------------------------------------------------------------------
class TestReleaseBlocked(BuiltCase):

    def test_release_refuses_an_incomplete_process_and_creates_no_directory(self):
        """An incomplete audit exits 2 with RELEASE_BLOCKED and leaves no output directory."""
        db = self.db_copy("primary")
        before = self.head_revision(db)
        out = self.path("release")
        payload, stderr = run_cli("release", db, "--audit", AUDIT, "--out", out, expect=2)
        self.assertEqual(payload["error"]["code"], "RELEASE_BLOCKED")
        self.assertIn("is not process-complete", payload["error"]["message"])
        self.assertEqual({record["kind"] for record in payload["error"]["records"]}, {"obligation"})
        self.assertEqual(sorted(record["id"] for record in payload["error"]["records"]),
                         sorted(BUILT.steps["status_primary"]["obligations"]["unsatisfied"]))
        self.assertIn("RELEASE_BLOCKED", stderr)
        self.assertFalse(out.exists(), "a refused release must not create its output directory")
        self.assertEqual(self.head_revision(db), before)
        retry = payload["error"]["retry"]
        self.assertEqual(retry["next_commands"],
                         [["paper_audit.py", "work", "list", str(db.resolve()), "--audit", AUDIT]])
        self.assertEqual(retry["checkpoint"]["command"],
                         ["paper_audit.py", "checkpoint", str(db.resolve()), "--audit", AUDIT])
        self.assertEqual(retry["checkpoint"]["required_options"], ["--out"])
        self.assertIn("report.html", retry["checkpoint"]["instruction"])
        self.assertFalse(self.path("report.html").exists())
        self.assertFalse(out.with_suffix(".working.html").exists())

    def test_blocked_release_preserves_the_selected_checkpoint_destination_without_writing_it(self):
        """Retry guidance keeps the selected report path; release never writes the working report."""
        db = self.db_copy("primary")
        before = self.head_revision(db)
        for report_name in ("report.html", "custom reports/proof audit.html"):
            for existing in (False, True):
                with self.subTest(report_name=report_name, existing=existing):
                    report = self.path(report_name)
                    original = b"existing working report\n"
                    if existing:
                        report.write_bytes(original)
                    out = self.path("release")
                    payload, _ = run_cli("release", db, "--audit", AUDIT, "--out", out,
                                         "--checkpoint-out", report, expect=2)
                    self.assertEqual(payload["error"]["code"], "RELEASE_BLOCKED")
                    self.assertEqual(payload["error"]["retry"]["next_commands"], [
                        ["paper_audit.py", "checkpoint", str(db.resolve()), "--audit", AUDIT,
                         "--out", str(report.resolve())],
                        ["paper_audit.py", "work", "list", str(db.resolve()), "--audit", AUDIT]])
                    self.assertFalse(out.exists())
                    self.assertFalse(out.with_suffix(".working.html").exists())
                    if existing:
                        self.assertEqual(report.read_bytes(), original)
                    else:
                        self.assertFalse(report.exists())
                    self.assertEqual(self.head_revision(db), before)

    def test_an_open_source_issue_blocks_completion_and_release(self):
        """A recorded source limit reopens the process even with every obligation satisfied."""
        db = self.db_copy()
        summary, _ = run_cli("get", db, "--target", ITEMS[0], "--target", ITEMS[1], "--mode", "primary",
                             "--out", self.path("pkt.json"))
        request = self.request([edit("create", "source_issues", "sis_1", {
            "source_id": BUILT.source_id, "anchor_id": "anc_thm_proof", "category": "locator_limit",
            "description": "proof spills onto an unnumbered page", "lifecycle": "open", "resolution": None,
            "reviewer": "coord"})], summary["packet_id"], "source_review.json")
        review, _ = run_cli("source", "review", db, "--request", request)
        self.assertEqual(review["command"], "source review")
        status, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertIs(status["process_complete"], False)
        self.assertEqual([limit["id"] for limit in status["source_limits"]], ["sis_1"])
        self.assertEqual(status["obligations"]["unsatisfied"], [])
        out = self.path("release")
        payload, _ = run_cli("release", db, "--audit", AUDIT, "--out", out, expect=2)
        self.assertEqual(payload["error"]["code"], "RELEASE_BLOCKED")
        self.assertIn("source_limit", {record["kind"] for record in payload["error"]["records"]})
        self.assertFalse(out.exists())

    def test_release_refuses_a_non_empty_output_directory(self):
        """A release directory that already holds files is refused before anything is rendered."""
        db = self.db_copy()
        out = self.path("release")
        out.mkdir()
        (out / "leftover.txt").write_text("previous attempt\n", encoding="utf-8")
        payload, _ = run_cli("release", db, "--audit", AUDIT, "--out", out, expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertIn("is not empty", payload["error"]["message"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["leftover.txt"])


# -- publication --------------------------------------------------------------------------------------
@unittest.skipUnless(node_available(), "rendering a report needs the node executable")
class TestPublication(BuiltCase):
    """checkpoint, attach and release; the rendered page is built once for the whole class."""

    @classmethod
    def setUpClass(cls):
        cls.shared = Path(tempfile.mkdtemp(prefix="paper_core_cli_pub_"))
        cls.shared_db = cls.shared / "paper.db"
        shutil.copy2(BUILT.snapshots["complete"], cls.shared_db)
        cls.shared_html = cls.shared / "reports" / "check.html"
        cls.checkpoint, cls.checkpoint_stderr = run_cli("checkpoint", cls.shared_db, "--out", cls.shared_html)
        cls.html_bytes = cls.shared_html.read_bytes()

    @classmethod
    def tearDownClass(cls):
        rmtree_force(cls.shared)

    def published_copy(self):
        db, html = self.path("paper.db"), self.path("reports/check.html")
        shutil.copy2(self.shared_db, db)
        shutil.copy2(self.shared_html, html)
        return db, html

    def test_checkpoint_publishes_a_working_report(self):
        """checkpoint renders the default audit into a working publication and says so."""
        self.assertEqual(self.checkpoint["command"], "checkpoint")
        self.assertEqual(self.checkpoint["kind"], "working")
        self.assertEqual(self.checkpoint["state"], "published")
        self.assertEqual(self.checkpoint["audit_id"], AUDIT)
        self.assertIs(self.checkpoint["process_complete"], True)
        self.assertEqual(self.checkpoint["revision"], BUILT.complete_revision)
        self.assertTrue(self.checkpoint["publication_id"].startswith("pub_"))
        self.assertEqual(self.checkpoint["artifact_sha256"], sha(self.html_bytes))
        self.assertEqual(self.checkpoint_stderr, "")
        self.assertIn(b"<html", self.html_bytes[:400].lower())

    def test_attach_registers_a_report_path_once(self):
        """attach adds the report path on first use and is a no-op on the second."""
        db, _ = self.published_copy()
        first, _ = run_cli("attach", db, "--report", "reports/check.html")
        self.assertIs(first["changed"], True)
        self.assertEqual(first["report_paths"], ["reports/check.html"])
        self.assertEqual(first["paper_id"], BUILT.paper_id)
        second, _ = run_cli("attach", db, "--report", "reports/check.html")
        self.assertIs(second["changed"], False)
        self.assertEqual(second["revision"], first["revision"])
        self.assertEqual(second["report_paths"], ["reports/check.html"])

    def test_release_writes_an_immutable_three_file_package(self):
        """release freezes three files and leaves the selected working report unchanged."""
        db, html = self.published_copy()
        working_bytes = html.read_bytes()
        out = self.path("release")
        payload, stderr = run_cli("release", db, "--audit", AUDIT, "--out", out, "--checkpoint-out", html)
        self.assertEqual(payload["command"], "release")
        self.assertIs(payload["process_complete"], True)
        self.assertEqual(payload["core_version"], "2.3.9")
        self.assertEqual(payload["storage_format"], 4)
        self.assertEqual(payload["contract"], "proofcheck-records/4")
        self.assertEqual(payload["audit_id"], AUDIT)
        self.assertEqual(payload["paper_id"], BUILT.paper_id)
        self.assertEqual(payload["publication"]["kind"], "release")
        self.assertEqual(payload["publication"]["state"], "published")
        self.assertEqual(payload["files"], ["report.html", "export.json", "receipt.json"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["export.json", "receipt.json", "report.html"])
        self.assertEqual(html.read_bytes(), working_bytes)
        self.assertEqual(sha((out / "report.html").read_bytes()), payload["publication"]["artifact_sha256"])
        receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["revision"], payload["revision"])
        self.assertEqual(receipt["audit_id"], AUDIT)
        self.assertGreater(receipt["export"]["history"], 0)
        exported = json.loads((out / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(exported["revision"], payload["revision"])
        self.assertEqual(exported["paper_id"], BUILT.paper_id)
        self.assertEqual(exported["storage_format"], 4)
        self.assertEqual(stderr, "")
        status, _ = run_cli("status", db)
        self.assertEqual(status["published_revision"], payload["revision"])
        self.assertIn("release", {p["kind"] for p in status["publications"]})

    def test_a_second_release_into_the_same_directory_is_refused(self):
        """The release directory is written once; a repeat exits 2 without touching the package."""
        db, _ = self.published_copy()
        out = self.path("release")
        run_cli("release", db, "--audit", AUDIT, "--out", out)
        before = sorted((p.name, p.stat().st_size) for p in out.iterdir())
        payload, _ = run_cli("release", db, "--audit", AUDIT, "--out", out, expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertIn("is not empty", payload["error"]["message"])
        self.assertEqual(sorted((p.name, p.stat().st_size) for p in out.iterdir()), before)

    def test_a_render_failure_exits_six_and_keeps_the_prior_page(self):
        """With no node on PATH the publication fails with exit 6 and the previous HTML survives."""
        db, html = self.published_copy()
        empty = self.path("emptybin")
        empty.mkdir()
        status_before, _ = run_cli("status", db)
        payload, stderr = run_cli("checkpoint", db, "--out", html, expect=6,
                                  env=dict(CLI_ENV, PATH=str(empty)))
        self.assertEqual(payload["error"]["code"], "PUBLICATION_FAILED")
        self.assertIn("Node.js is required", payload["error"]["message"])
        self.assertTrue(any(record.get("prior_output_retained") for record in payload["error"]["records"]),
                        payload["error"]["records"])
        self.assertEqual(html.read_bytes(), self.html_bytes, "a failed publication must keep the prior page")
        self.assertIn("PUBLICATION_FAILED", stderr)
        status_after, _ = run_cli("status", db)
        self.assertIn("failed", {p["state"] for p in status_after["publications"]})
        self.assertEqual(status_after["published_revision"], status_before["published_revision"])


# -- conflicts ------------------------------------------------------------------------------------------
class TestConflict(BuiltCase):

    def _author_packet(self, db):
        summary, _ = run_cli("get", db, "--target", "items:itm_lem", "--mode", "author", "--out",
                             self.path("pkt_author.json"))
        packet = json.loads(self.path("pkt_author.json").read_text(encoding="utf-8"))
        record = next(r for r in packet["records"]
                      if r["ref"]["collection"] == "items" and r["ref"]["id"] == "itm_lem")
        return summary["packet_id"], record["ref"]["version"], record["body"]

    def test_a_stale_packet_exits_three_and_asks_for_a_replacement(self):
        """Reusing a packet whose inputs moved exits 3 and names the replacement get command."""
        db = self.db_copy()
        packet_id, version, body = self._author_packet(db)
        accepted, _ = run_cli("apply", db, "--batch", self.request(
            [edit("replace", "items", "itm_lem", dict(body, caption="Lemma 1 (bounded sequence)"), version)],
            packet_id, "edit1.json"))
        self.assertEqual(accepted["receipt"]["changed"][0]["version"], version + 1)
        payload, stderr = self._conflicting_edit(db, packet_id, body, version + 1, "edit2.json")
        self.assertEqual(payload["error"]["code"], "CONFLICT")
        self.assertIn("request a replacement packet", payload["error"]["message"])
        self.assertEqual(payload["error"]["retry"]["mode"], "author")
        self.assertIn("--target items:itm_lem", payload["error"]["retry"]["command"])
        self.assertIn("CONFLICT", stderr)
        changed = payload["error"]["records"][0]["changed"]
        self.assertEqual([(c["ref"]["id"], c["expected_version"], c["actual_version"]) for c in changed],
                         [("itm_lem", version, version + 1)])
        status, _ = run_cli("status", db)
        self.assertEqual(status["counts"]["items"], 2)
        self.assertEqual(self._author_packet(db)[1], version + 1, "the refused batch must write nothing")

    def test_a_stale_expected_version_exits_three_even_with_a_fresh_packet(self):
        """Optimistic concurrency is enforced per record: a stale expected_version conflicts on its own."""
        db = self.db_copy()
        packet_id, version, body = self._author_packet(db)
        run_cli("apply", db, "--batch", self.request(
            [edit("replace", "items", "itm_lem", dict(body, caption="Lemma 1 (first rename)"), version)],
            packet_id, "first.json"))
        fresh_packet, fresh_version, fresh_body = self._author_packet(db)
        self.assertEqual(fresh_version, version + 1)
        payload, _ = self._conflicting_edit(db, fresh_packet, fresh_body, version, "stale.json")
        self.assertEqual(payload["error"]["code"], "CONFLICT")
        self.assertIn("request a replacement packet", payload["error"]["message"])
        changed = payload["error"]["records"][0]["changed"]
        self.assertEqual([(c["ref"]["id"], c["expected_version"], c["actual_version"]) for c in changed],
                         [("itm_lem", version, version + 1)])
        self.assertIs(payload["error"]["records"][0]["source_context_changed"], False)
        self.assertEqual(self._author_packet(db)[1], version + 1, "the refused batch must write nothing")

    def _conflicting_edit(self, db, packet_id, body, expected, name):
        return run_cli("apply", db, "--batch", self.request(
            [edit("replace", "items", "itm_lem", dict(body, caption="Lemma 1 (renamed twice)"), expected)],
            packet_id, name), expect=3)


# -- malformed requests ---------------------------------------------------------------------------------
class TestMalformedRequests(BuiltCase):

    def setUp(self):
        super().setUp()
        self.db = self.db_copy()
        self.before = self.head_revision(self.db)

    def tearDown(self):
        self.assertEqual(self.head_revision(self.db), self.before, "a refused command must write nothing")
        super().tearDown()

    def test_a_missing_request_file_is_reported_as_unreadable(self):
        """A batch path that does not exist exits 2 with FILE_UNREADABLE."""
        payload, _ = run_cli("apply", self.db, "--batch", self.path("nowhere.json"), expect=2)
        self.assertEqual(payload["error"]["code"], "FILE_UNREADABLE")
        self.assertIn("cannot read batch", payload["error"]["message"])

    def test_a_file_that_is_not_json_is_reported_as_invalid(self):
        """A batch file that is not UTF-8 JSON exits 2 with JSON_INVALID."""
        junk = self.path("junk.json")
        junk.write_text("not json", encoding="utf-8")
        payload, _ = run_cli("apply", self.db, "--batch", junk, expect=2)
        self.assertEqual(payload["error"]["code"], "JSON_INVALID")
        self.assertIn("is not valid UTF-8 JSON", payload["error"]["message"])

    def test_a_malformed_batch_envelope_names_every_missing_field(self):
        """An envelope missing request_id, packet_id and edits exits 2 listing all three."""
        payload, stderr = run_cli("apply", self.db, "--batch",
                                  write_json(self.path("shape.json"), {"contract_version": 3}), expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(payload["error"]["message"], "invalid edit envelope")
        self.assertEqual(sorted(payload["error"]["records"]),
                         ["/edits: missing required field", "/packet_id: missing required field",
                          "/request_id: missing required field"])
        self.assertIn("INVALID_REQUEST", stderr)

    def test_an_unknown_packet_is_refused(self):
        """A batch quoting a packet id the database never issued exits 2 with PACKET_UNKNOWN."""
        payload, _ = run_cli("apply", self.db, "--batch", self.request([], "pkt_never_issued", "ghost.json"),
                             expect=2)
        self.assertEqual(payload["error"]["code"], "PACKET_UNKNOWN")

    def test_compare_refuses_a_packet_argument_that_contradicts_the_batch(self):
        """--packet must agree with the packet_id inside the file."""
        batch = self.request([], "pkt_in_the_file", "compare.json")
        payload, _ = run_cli("compare", self.db, "--packet", "pkt_on_the_command_line", "--batch", batch, expect=2)
        self.assertEqual(payload["error"]["code"], "ARGUMENT_MISMATCH")
        self.assertIn("pkt_on_the_command_line", payload["error"]["message"])
        self.assertIn("pkt_in_the_file", payload["error"]["message"])

    def test_review_map_refuses_a_response_argument_that_contradicts_the_file(self):
        """--response must agree with the response_id inside the mapping file."""
        mapping = write_json(self.path("mapping.json"), {"contract_version": 3, "request_id": "req_map_x",
                                                         "packet_id": "pkt_x", "response_id": "rsp_in_the_file",
                                                         "entries": [], "reviewer": "coord"})
        payload, _ = run_cli("review", "map", self.db, "--response", "rsp_on_the_command_line",
                             "--mapping", mapping, expect=2)
        self.assertEqual(payload["error"]["code"], "ARGUMENT_MISMATCH")
        self.assertIn("rsp_in_the_file", payload["error"]["message"])


# -- a corrupt database ------------------------------------------------------------------------------
class TestCorruptDatabase(BuiltCase):

    def test_validate_reports_a_tampered_record_body_with_exit_two(self):
        """A body edited behind the CLI's back fails validation: exit 2, ok false, no error envelope."""
        db = self.db_copy()
        connection = sqlite3.connect(db)
        try:
            connection.execute("DROP TRIGGER immutable_versions_update")
            changed = connection.execute(
                "UPDATE record_versions SET body_json = json_set(body_json, '$.kind', 'bogus') "
                "WHERE collection = 'items' AND id = 'itm_thm' AND version = "
                "(SELECT version FROM record_heads WHERE collection = 'items' AND id = 'itm_thm')").rowcount
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(changed, 1)
        payload, stderr = run_cli("validate", db, expect=2)
        self.assertIs(payload["ok"], False)
        self.assertNotIn("error", payload)
        self.assertTrue(any("items:itm_thm" in message for message in payload["errors"]), payload["errors"])
        self.assertTrue(any("/kind" in message for message in payload["errors"]), payload["errors"])
        self.assertEqual(stderr, "")

    def test_release_is_blocked_when_the_snapshot_fails_validation(self):
        """A corrupt snapshot cannot be released even though its audit was process-complete."""
        db = self.db_copy()
        connection = sqlite3.connect(db)
        try:
            connection.execute("DROP TRIGGER immutable_versions_update")
            connection.execute(
                "UPDATE record_versions SET body_json = json_set(body_json, '$.kind', 'bogus') "
                "WHERE collection = 'items' AND id = 'itm_thm' AND version = "
                "(SELECT version FROM record_heads WHERE collection = 'items' AND id = 'itm_thm')")
            connection.commit()
        finally:
            connection.close()
        out = self.path("release")
        payload, _ = run_cli("release", db, "--audit", AUDIT, "--out", out, expect=2)
        self.assertEqual(payload["error"]["code"], "RELEASE_BLOCKED")
        self.assertIn("fails validation", payload["error"]["message"])
        self.assertTrue(payload["error"]["records"])
        self.assertFalse(out.exists())


# -- changes, export, backup ---------------------------------------------------------------------------
class TestChangesExportBackup(BuiltCase):

    def test_changes_pages_through_the_version_log(self):
        """changes reports total, returned and next_offset consistently across pages."""
        db = BUILT.snapshots["complete"]
        first, _ = run_cli("changes", db, "--since", "0", "--limit", "5")
        self.assertEqual(first["command"], "changes")
        self.assertEqual((first["since"], first["limit"], first["offset"]), (0, 5, 0))
        self.assertEqual(first["returned"], 5)
        self.assertEqual(first["next_offset"], 5)
        self.assertGreater(first["total"], 5)
        self.assertEqual(first["records"][0], {"collection": "papers", "id": BUILT.paper_id, "version": 1,
                                               "revision": 1, "retired": False, "op": "create"})
        self.assertEqual(first["affected_checks"], [])
        self.assertIs(first["source_context"]["changed"], False)
        second, _ = run_cli("changes", db, "--since", "0", "--limit", "5", "--offset", first["next_offset"])
        self.assertEqual(second["offset"], 5)
        self.assertEqual(second["total"], first["total"])
        self.assertNotEqual(second["records"][0], first["records"][0])

    def test_changes_since_the_head_returns_nothing(self):
        """Nothing has changed since the head revision."""
        payload, _ = run_cli("changes", BUILT.snapshots["complete"], "--since", str(BUILT.complete_revision))
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["records"], [])
        self.assertIsNone(payload["next_offset"])

    def test_changes_rejects_a_revision_outside_the_range(self):
        """--since above the head revision exits 2 with REVISION_RANGE."""
        payload, _ = run_cli("changes", BUILT.snapshots["complete"], "--since", "999", expect=2)
        self.assertEqual(payload["error"]["code"], "REVISION_RANGE")
        self.assertIn("0..", payload["error"]["message"])

    def test_export_writes_a_portable_snapshot(self):
        """export --history writes the complete contract-4 snapshot plus its version history."""
        out = self.path("export.json")
        payload, _ = run_cli("export", BUILT.snapshots["complete"], "--out", out, "--history")
        self.assertEqual(payload["command"], "export")
        self.assertEqual(payload["revision"], BUILT.complete_revision)
        self.assertGreater(payload["records"], 0)
        self.assertGreaterEqual(payload["history"], payload["records"])
        self.assertTrue(Path(payload["output"]).is_file())
        exported = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(exported["revision"], payload["revision"])
        self.assertEqual(exported["paper_id"], BUILT.paper_id)
        self.assertEqual(exported["storage_format"], 4)
        self.assertEqual(exported["contract_version"], 4)

    def test_export_of_an_earlier_snapshot_reports_that_revision(self):
        """--snapshot exports the historical revision rather than the head."""
        out = self.path("export_rev2.json")
        payload, _ = run_cli("export", BUILT.snapshots["complete"], "--out", out, "--snapshot", "2")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["revision"], 2)

    def test_export_rejects_revision_zero_and_writes_no_file(self):
        """Revision 0 is outside 1..head, so export exits 2 and writes nothing."""
        out = self.path("export_bad.json")
        payload, _ = run_cli("export", BUILT.snapshots["complete"], "--out", out, "--snapshot", "0", expect=2)
        self.assertEqual(payload["error"]["code"], "REVISION_RANGE")
        self.assertFalse(out.exists())

    def test_backup_copies_the_database_at_the_head_revision(self):
        """backup writes a readable copy whose status matches the original."""
        out = self.path("backup.db")
        payload, _ = run_cli("backup", BUILT.snapshots["complete"], "--out", out)
        self.assertEqual(payload["command"], "backup")
        self.assertEqual(payload["revision"], BUILT.complete_revision)
        self.assertTrue(Path(payload["backup"]).is_file())
        original, _ = run_cli("status", BUILT.snapshots["complete"])
        copied, _ = run_cli("status", out)
        self.assertEqual(copied["revision"], original["revision"])
        self.assertEqual(copied["counts"], original["counts"])

    def test_backup_refuses_to_overwrite(self):
        """An existing backup path exits 2 and the existing file is left alone."""
        out = self.path("backup.db")
        out.write_bytes(b"not a database")
        payload, _ = run_cli("backup", BUILT.snapshots["complete"], "--out", out, expect=2)
        self.assertIn("refusing to overwrite", payload["error"]["message"])
        self.assertEqual(out.read_bytes(), b"not a database")

    def test_backup_creates_missing_parents_and_reports_non_directory_parent(self):
        source = BUILT.snapshots["complete"]
        before = source.read_bytes()
        out = self.path("missing/nested/backup.db")
        payload, _ = run_cli("backup", source, "--out", out)
        self.assertEqual(BUILT.complete_revision, payload["revision"])
        copied, _ = run_cli("status", out)
        self.assertEqual(BUILT.complete_revision, copied["revision"])
        parent = self.path("parent-file")
        parent.write_bytes(b"keep parent")
        payload, _ = run_cli("backup", source, "--out", parent / "backup.db", expect=2)
        self.assertEqual("BACKUP_PATH_INVALID", payload["error"]["code"])
        self.assertIn("not a directory", payload["error"]["message"])
        self.assertEqual(b"keep parent", parent.read_bytes())
        self.assertEqual(before, source.read_bytes())


# -- packets -------------------------------------------------------------------------------------------
class TestPackets(BuiltCase):

    def test_get_out_writes_the_manifest_and_prints_a_summary(self):
        """get --out writes the packet and prints counts that match the written file."""
        db = self.db_copy()
        out = self.path("packet.json")
        payload, _ = run_cli("get", db, "--target", "items:itm_lem", "--mode", "primary", "--out", out)
        packet = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["command"], "get")
        self.assertEqual(payload["out"], str(out))
        self.assertEqual(payload["bytes"], len(out.read_bytes()))
        self.assertEqual(payload["packet_id"], packet["packet_id"])
        self.assertEqual(payload["mode"], "primary")
        self.assertEqual(payload["base_revision"], packet["base_revision"])
        self.assertEqual(payload["targets"], [{"collection": "items", "id": "itm_lem"}])
        self.assertEqual(payload["records"], len(packet["records"]))
        self.assertEqual(payload["write_scope"], len(packet["write_scope"]))
        self.assertIsNone(payload["extends"])

    def test_get_without_out_prints_the_whole_packet(self):
        """Omitting --out puts the packet itself on stdout as the single JSON object."""
        db = self.db_copy()
        payload, _ = run_cli("get", db, "--target", "items:itm_lem", "--mode", "primary")
        self.assertEqual(payload["command"], "get")
        self.assertIsInstance(payload["records"], list)
        self.assertIn("items:itm_lem", {f"{r['ref']['collection']}:{r['ref']['id']}" for r in payload["records"]})
        self.assertEqual(payload["packet_version"], 2)

    def test_get_extend_issues_a_new_packet_that_names_its_parent(self):
        """--extend widens the read set through the original mode's allowlist under a new packet id."""
        db = self.db_copy()
        base, _ = run_cli("get", db, "--target", "items:itm_lem", "--mode", "primary", "--out",
                          self.path("base.json"))
        context = write_json(self.path("context.json"), {
            "targets": [R("items", "itm_thm")], "source_anchor_ids": ["anc_thm_proof"],
            "source_paths": ["paper.tex"], "reason": "need the neighbouring proof text"})
        out = self.path("extended.json")
        payload, _ = run_cli("get", db, "--extend", base["packet_id"], "--request", context, "--out", out)
        self.assertEqual(payload["extends"], base["packet_id"])
        self.assertNotEqual(payload["packet_id"], base["packet_id"])
        self.assertGreater(payload["records"], base["records"])
        extended = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("items:itm_thm",
                      {f"{r['ref']['collection']}:{r['ref']['id']}" for r in extended["records"]})

    def test_get_extend_rejects_an_unknown_packet(self):
        """Extending a packet the database never issued exits 2 and writes no packet file."""
        db = self.db_copy()
        context = write_json(self.path("context.json"), {"targets": [], "source_anchor_ids": [],
                                                         "source_paths": ["paper.tex"], "reason": "why not"})
        out = self.path("extended.json")
        payload, _ = run_cli("get", db, "--extend", "pkt_never_issued", "--request", context, "--out", out,
                             expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(payload["error"]["message"], "unknown packet pkt_never_issued")
        self.assertFalse(out.exists())


# -- telemetry -----------------------------------------------------------------------------------------
class TestTelemetry(BuiltCase):

    def test_telemetry_record_appends_one_observational_event(self):
        """telemetry record stores the stage and duration it was given."""
        db = self.db_copy()
        payload, _ = run_cli("telemetry", "record", db, "--run-id", "run_cli", "--stage", "authoring",
                             "--elapsed-ms", "1200", "--details", '{"note": "typed the structure batch"}')
        self.assertEqual(payload["command"], "telemetry record")
        self.assertEqual(payload["run_id"], "run_cli")
        self.assertEqual(payload["stage"], "authoring")
        self.assertEqual(payload["elapsed_ms"], 1200)
        self.assertTrue(payload["event_id"].startswith("evt_"), payload["event_id"])
        summary, _ = run_cli("telemetry", "summary", db, "--run-id", "run_cli", "--events")
        self.assertIs(summary["observational_only"], True)
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["stages"]["authoring"], {"events": 1, "elapsed_ms": 1200, "unknown_elapsed": 0})
        self.assertEqual(summary["event_list"][0]["details"], {"note": "typed the structure batch"})

    def test_run_id_records_a_command_event_for_each_invocation(self):
        """--run-id appends one 'command' stage event naming the command and its exit code."""
        db = self.db_copy()
        run_cli("status", db, "--run-id", "run_cli")
        run_cli("changes", db, "--since", "0", "--limit", "1", "--run-id", "run_cli")
        summary, _ = run_cli("telemetry", "summary", db, "--run-id", "run_cli", "--events")
        self.assertEqual(summary["events"], 2)
        self.assertEqual(summary["runs"][0]["run_id"], "run_cli")
        self.assertEqual(summary["runs"][0]["events"], 2)
        self.assertEqual({event["stage"] for event in summary["event_list"]}, {"command"})
        details = [event["details"] for event in summary["event_list"]]
        self.assertEqual({d["command"] for d in details}, {"status", "changes"})
        self.assertTrue(all(d["exit_code"] == 0 and d["outcome"] == "ok" for d in details), details)
        self.assertTrue(all(d["core_version"] == "2.3.9" for d in details), details)

    def test_a_failed_command_records_its_exit_code_and_error_code(self):
        """The telemetry event of a refused command carries outcome error and the error code."""
        db = self.db_copy()
        run_cli("status", db, "--snapshot", "999", "--run-id", "run_bad", expect=2)
        summary, _ = run_cli("telemetry", "summary", db, "--run-id", "run_bad", "--events")
        self.assertEqual(summary["events"], 1)
        details = summary["event_list"][0]["details"]
        self.assertEqual(details["command"], "status")
        self.assertEqual(details["exit_code"], 2)
        self.assertEqual(details["outcome"], "error")
        self.assertEqual(details["error_code"], "REVISION_RANGE")

    def test_telemetry_commands_record_no_command_event_of_their_own(self):
        """telemetry's own --run-id names the run being measured, so it adds no 'command' event."""
        db = self.db_copy()
        run_cli("telemetry", "summary", db, "--run-id", "run_own")
        run_cli("telemetry", "record", db, "--run-id", "run_own", "--stage", "report")
        summary, _ = run_cli("telemetry", "summary", db, "--run-id", "run_own", "--events")
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["event_list"][0]["stage"], "report")
        self.assertIsNone(summary["event_list"][0]["elapsed_ms"])

    def test_telemetry_summary_omits_the_event_list_unless_asked(self):
        """Without --events the summary reports totals only."""
        db = self.db_copy()
        run_cli("telemetry", "record", db, "--run-id", "run_plain", "--stage", "waiting", "--elapsed-ms", "5")
        summary, _ = run_cli("telemetry", "summary", db)
        self.assertNotIn("event_list", summary)
        self.assertEqual(summary["events"], 1)

    def test_telemetry_rejects_an_unknown_stage_and_stores_nothing(self):
        """An unknown stage exits 2 with INVALID_EVENT and appends no event."""
        db = self.db_copy()
        payload, _ = run_cli("telemetry", "record", db, "--run-id", "run_cli", "--stage", "daydreaming", expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_EVENT")
        self.assertTrue(any("stage must be one of" in record for record in payload["error"]["records"]),
                        payload["error"]["records"])
        summary, _ = run_cli("telemetry", "summary", db)
        self.assertEqual(summary["events"], 0)

    def test_telemetry_rejects_details_that_are_not_a_json_object(self):
        """--details must be JSON object text or a path to one."""
        db = self.db_copy()
        payload, _ = run_cli("telemetry", "record", db, "--run-id", "run_cli", "--stage", "report",
                             "--details", "{oops", expect=2)
        self.assertEqual(payload["error"]["code"], "USAGE")
        self.assertIn("--details must be a JSON object", payload["error"]["message"])


# -- legacy databases ------------------------------------------------------------------------------------
class TestLegacyOverview(TempCase):
    """An archify overview database is storage format 1: incompatible until it is migrated."""

    def legacy_database(self) -> Path:
        scripts = str(OVERVIEW / "scripts")
        if scripts not in sys.path:
            sys.path.append(scripts)
        import paper_database

        target = self.path("legacy.db")
        paper_database._native_init_database(target, OVERVIEW_EXAMPLE / "overview.json", source_root=OVERVIEW_EXAMPLE)
        return target

    def test_opening_a_legacy_overview_exits_four(self):
        """A storage-format-1 database is reported as INCOMPATIBLE, naming the format it holds."""
        db = self.legacy_database()
        payload, stderr = run_cli("status", db, expect=4)
        self.assertEqual(payload["error"]["code"], "INCOMPATIBLE")
        self.assertEqual(payload["error"]["records"][0]["format"], "archify-paper-database-1")
        self.assertIn("INCOMPATIBLE", stderr)
        payload, _ = run_cli("validate", db, expect=4)
        self.assertEqual(payload["error"]["code"], "INCOMPATIBLE")

    def test_migrate_overview_upgrades_in_place_and_keeps_a_backup(self):
        """After migration the same file answers status in overview mode and validates."""
        db = self.legacy_database()
        backup = self.path("legacy.backup.db")
        payload, _ = run_cli("migrate-overview", db, "--backup", backup)
        self.assertEqual(payload["command"], "migrate-overview")
        self.assertEqual(payload["counts"]["items"], 6)
        self.assertTrue(Path(payload["backup"]["path"]).is_file())
        status, _ = run_cli("status", db)
        self.assertEqual(status["mode"], "overview")
        self.assertEqual(status["counts"]["items"], 6)
        self.assertEqual(status["counts"]["uses"], 11)
        self.assertEqual(status["storage"]["storage_format"], 4)
        validated, _ = run_cli("validate", db)
        self.assertIs(validated["ok"], True)

    def test_migrating_an_already_migrated_database_is_refused(self):
        """A second migration exits 2 with ALREADY_MIGRATED and writes no second backup."""
        db = self.legacy_database()
        run_cli("migrate-overview", db, "--backup", self.path("legacy.backup.db"))
        second = self.path("legacy.backup2.db")
        payload, _ = run_cli("migrate-overview", db, "--backup", second, expect=2)
        self.assertEqual(payload["error"]["code"], "ALREADY_MIGRATED")
        self.assertFalse(second.exists())


class TestImportLegacy(TempCase):
    """Importing a stat-paper-proofcheck v1.5 audit folder into a brand new database."""

    @classmethod
    def setUpClass(cls):
        cls.shared = Path(tempfile.mkdtemp(prefix="paper_core_cli_import_"))
        cls.folder = cls.shared / "legacy_audit"
        shutil.copytree(support.REFERENCE_AUDIT, cls.folder)
        cls.db = cls.shared / "imported.db"
        cls.receipt, cls.stderr = run_cli("import-legacy", cls.folder, "--db", cls.db,
                                          "--map", cls.shared / "map.json")

    @classmethod
    def tearDownClass(cls):
        rmtree_force(cls.shared)

    def test_import_legacy_creates_the_database_and_its_identity_map(self):
        """The import reports its counts, the audit it created and the preserved artifact."""
        self.assertEqual(self.receipt["command"], "import-legacy")
        self.assertEqual(self.receipt["counts"]["items"], 2)
        self.assertTrue(self.receipt["audit_id"].startswith("aud_"), self.receipt["audit_id"])
        self.assertTrue(Path(self.receipt["import_artifact"]["path"]).is_file())
        self.assertTrue((self.shared / "map.json").is_file())

    def test_the_imported_audit_is_historical_and_incomplete(self):
        """Imported legacy checks are qualified: triage mode, nothing established, still valid data."""
        status, _ = run_cli("status", self.db)
        self.assertEqual(status["audit"]["mode"], "triage")
        self.assertIs(status["process_complete"], False)
        self.assertEqual({state["state"] for key, state in status["assessments"].items()
                          if key.startswith("items:")}, {"gray"})
        validated, _ = run_cli("validate", self.db)
        self.assertIs(validated["ok"], True)

    def test_import_legacy_refuses_an_existing_database(self):
        """Importing into a database that already exists exits 2 and writes no mapping file."""
        mapping = self.shared / "map2.json"
        payload, _ = run_cli("import-legacy", self.folder, "--db", self.db, "--map", mapping, expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertIn("refusing to overwrite", payload["error"]["message"])
        self.assertFalse(mapping.exists())

    def test_import_legacy_refuses_a_missing_audit_folder(self):
        """A missing audit folder exits 2 before any database is created."""
        target = self.path("new.db")
        payload, _ = run_cli("import-legacy", self.path("no_such_folder"), "--db", target,
                             "--map", self.path("map.json"), expect=2)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertIn("legacy audit folder not found", payload["error"]["message"])
        self.assertFalse(target.exists())


class TestWorkDiagnostics(TempCase):
    def prepare(self, fixture, *extra):
        return run_cli("work", "prepare", fixture.path, "--audit", "aud_1", "--mode", "primary",
                       "--out", self.work / "assignment", *extra)[0]

    def test_no_primary_assignment_does_not_claim_unfinished_review_is_complete(self):
        fx = self.fixture().primary()
        result = self.prepare(fx)
        self.assertFalse(result["prepared"])
        self.assertFalse(result["preparation"]["process_complete"])
        self.assertNotEqual("recorded_scope_complete", result["preparation"]["reason"])
        self.assertEqual(result["preparation"]["next_commands"][0][1:3], ["work", "list"])

    def test_oversized_assignment_reports_size_blocker_without_creating_packet(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            before = db.conn.execute("SELECT count(*) FROM packets").fetchone()[0]
        result = self.prepare(fx, "--max-bytes", "1")
        self.assertFalse(result["prepared"])
        self.assertEqual("packet_size_limit", result["preparation"]["reason"])
        self.assertFalse(result["preparation"]["process_complete"])
        with fx.open() as db:
            self.assertEqual(before, db.conn.execute("SELECT count(*) FROM packets").fetchone()[0])
        action = result["preparation"]["size_action"]
        self.assertEqual("retry_supported_limit", action["operation"])
        retried, _ = run_cli(*action["command"][1:])
        self.assertTrue(retried["prepared"], retried)
        self.assertEqual(1048576, retried["packet_limits"]["max_bytes"])

    def test_maximum_size_failure_has_no_ineffective_retry_command(self):
        from paper_core import cli
        fx = self.fixture().audit()
        result = {"prepared": False, "diagnostics": [{"code": "OVERSIZED_CONTEXT",
            "measured_or_lower_bound_bytes": 1048577, "unique_record_count": 1}]}
        args = argparse.Namespace(max_bytes=1048576)
        with fx.open() as db:
            before = db.max_revision()
            cli._preparation_diagnostic(db, result, fx.audit_id, args)
            self.assertEqual(before, db.max_revision())
        self.assertEqual("inspect_context_boundary", result["preparation"]["size_action"]["operation"])
        self.assertNotIn("command", result["preparation"]["size_action"])

    def test_no_assignment_after_completion_names_recorded_scope(self):
        result = self.prepare(self.fixture().complete())
        self.assertFalse(result["prepared"])
        self.assertTrue(result["preparation"]["process_complete"])
        self.assertEqual("recorded_scope_complete", result["preparation"]["reason"])

    @unittest.skipUnless(node_available(), "rendering a report needs node")
    def test_partial_checkpoint_returns_same_scope_as_status_and_continuation_commands(self):
        fx = self.fixture().primary()
        report = self.work / "working report.html"
        result, _ = run_cli("checkpoint", fx.path, "--audit", "aud_1", "--out", report)
        state, _ = run_cli("status", fx.path, "--audit", "aud_1")
        self.assertFalse(result["process_complete"])
        self.assertEqual(result["factual_summary"], state["factual_summary"])
        self.assertEqual(result["output_path"], str(report.resolve()))
        self.assertEqual(result["next_commands"][0][1:3], ["work", "list"])
        self.assertTrue(report.is_file())

    @unittest.skipUnless(node_available(), "rendering a report needs node")
    def test_partial_release_failure_reports_saved_files_without_claiming_delivery(self):
        from paper_core import cli
        from paper_core.errors import PublicationError
        fx = self.fixture().complete()
        destination = self.work / "release"
        args = argparse.Namespace(db=str(fx.path), audit="aud_1", out=str(destination))
        replace = cli.os.replace
        def fail_export_replace(source, target):
            if Path(target) == destination / "export.json":
                raise OSError("fixture export write failed")
            return replace(source, target)
        with patch.object(cli.os, "replace", side_effect=fail_export_replace):
            with self.assertRaises(PublicationError) as caught:
                cli.cmd_release(args)
        failure = caught.exception.records[-1]
        self.assertFalse(failure["delivery_complete"])
        self.assertEqual(failure["stage"], "export")
        self.assertEqual(failure["available_files"], ["report.html"])
        self.assertTrue((destination / "report.html").is_file())
        self.assertFalse((destination / "receipt.json").exists())
        self.assertTrue((Path(failure["preparation_directory"]) / "export.json").is_file())
        self.assertIn("--resume", failure["resume_command"])


if __name__ == "__main__":
    unittest.main()
