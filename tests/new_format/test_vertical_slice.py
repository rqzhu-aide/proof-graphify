"""The first-milestone vertical slice, end to end through the shipped command surface (handoff 11).

Handoff 11 names the first usable milestone: "source capture, a joint inference, hidden claim,
application check, saved draft, resumed work, independent response, reconciliation, and one honest
report", plus "one harmless concurrent edit and one real conflict". Every other module in this lane
exercises one mechanism in isolation; this one exists to prove the mechanisms *compose*.

So the slice is walked exactly once, in order, against a single database, and entirely through the
command surface an operator actually has (handoff 5: ``scripts/paper_audit.py``, run here as
``paper_core.cli`` by ``support.run_cli``, with one call through the packaged wrapper itself to show
the shipped file works). The walk records every command's payload and copies the database aside
after each step, so ``TestVerticalSlice`` can assert the ordered record of one real run while the
focused classes below re-open a single step without rebuilding the paper.

The slice deliberately goes *beyond* ``support.Fixture``'s two-item paper: that fixture has no joint
inference, no hidden claim and only one application, so the extra records (``itm_asm``,
``itm_hidden``, ``grp_joint`` and the four uses) are built explicitly here. The fixture's static edit
builders are reused wherever they fit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from support import (CLI_ENV, GLOBAL_TASKS, PAPER_TEX, PROOFCHECK, Fixture, R, TempCase, edit, locator,
                     node_available, rmtree_force, run_cli, run_wrapper, sha, write_json)
from paper_core import storage

AUDIT = "aud_1"
SLICE_TEX = PAPER_TEX.replace(r"\begin{document}", r"\begin{document} Assume throughout that $(a_n)$ is nondecreasing.")
# The three statements the audit is responsible for. itm_asm -- the hidden claim -- is a target in
# its own right precisely so that it cannot stay invisible (step 3 below).
TARGETS = ("items:itm_lem", "items:itm_thm", "items:itm_asm")
# The one obligation the slice deliberately leaves open, so every "honest report" assertion has a
# specific unfinished item to find. Recomputed below from the documented identity, never imported.
MISSING_USE = ("uses", "use_lem_thm", "application", "primary")


def _obligation_id(collection, id, kind, role, audit=AUDIT):
    """The documented obligation identity: sha256 over compact [audit, collection, id, kind, role]."""
    payload = json.dumps([audit, collection, id, kind, role], ensure_ascii=False, separators=(",", ":"))
    return "obl_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _targets(*names):
    flags = []
    for name in names:
        flags += ["--target", name]
    return flags


def _keys(refs):
    """``[{collection, id, ...}]`` as sorted ``collection:id`` strings."""
    return sorted(f"{ref['collection']}:{ref['id']}" for ref in refs)


def _item_edit(iid, kind, label, passages, *, origin="source", owner=None):
    """An item with an arbitrary passage list; ``Fixture.item_edit`` only builds statement+proof items."""
    return edit("create", "items", iid, {
        "kind": kind, "label": label, "caption": label,
        "statement": {"form": "verbatim", "text": label + " text"}, "passages": list(passages),
        "aliases": [], "uncertainty": None, "origin": origin, "owner_id": owner, "scope_id": None})


def _use_edit(uid, source, target, group_id, reason, anchor):
    statements = {"itm_lem": "Lemma 1 text", "itm_hidden": "Bounded and monotone text", "itm_asm": "Monotonicity text"}
    return edit("create", "uses", uid, {
        "from": R("items", source), "to": R("items", target), "type": "dependency", "group_id": group_id,
        "reason": reason, "needed_form": {"form": "verbatim", "text": statements[source]}, "substitutions": [], "evidence_refs": [anchor],
        "regime": None, "uncertainty": None})


def _check_edit(cid, target, kind, *, evidence=(), reasoning="checked against the source", supersedes=None):
    """A complete primary check; ``Fixture.check_edit`` cannot carry ``supersedes`` or a custom reason."""
    return edit("create", "checks", cid, {
        "audit_id": AUDIT, "target": target, "kind": kind, "role": "primary", "reviewer": "primary-1",
        "protocol_version": "item-audit/1", "state": "complete", "outcome": "supported",
        "reasoning": reasoning, "evidence_refs": list(evidence), "conditions": [], "next_action": None,
        "response_id": None, "supersedes": supersedes})


def _pin(applied, collection, id):
    """The ``{collection, id, version}`` pin for a record this apply receipt just wrote."""
    for row in applied["receipt"]["changed"]:
        if row["collection"] == collection and row["id"] == id:
            return {"collection": collection, "id": id, "version": row["version"]}
    raise AssertionError(f"{collection}:{id} was not written by {applied['receipt']}")


def _body(packet, collection, id):
    """The body and version of one record as the packet delivered it."""
    for record in packet["records"]:
        if record["ref"]["collection"] == collection and record["ref"]["id"] == id:
            return dict(record["body"]), record["ref"]["version"]
    raise AssertionError(f"{collection}:{id} is not in packet {packet['packet_id']}")


def _caption_edit(packet, item_id, caption):
    """A caption-only replacement: captions live in a facet no binding reads, so this is inert."""
    body, version = _body(packet, "items", item_id)
    body["caption"] = caption
    return edit("replace", "items", item_id, body, expected=version)


def _record(export, collection, id):
    for row in export["records"]:
        if row["collection"] == collection and row["id"] == id and not row["retired"]:
            return row
    raise AssertionError(f"{collection}:{id} is not in the export")


class _SlicePaper:
    """Walks the milestone slice once through the CLI, snapshotting the database after every step."""

    def __init__(self, root):
        self.root = Path(root)
        self.source_root = self.root / "src"
        self.source_root.mkdir(parents=True, exist_ok=True)
        (self.source_root / "paper.tex").write_text(SLICE_TEX, encoding="utf-8", newline="\n")
        self.db = self.root / "paper.db"
        self.stages = {}
        self.state = {}
        self.log = {}
        self.responses = {}
        self.report = None
        self._counter = 0

    # -- plumbing ----------------------------------------------------------------------------------
    def request_id(self):
        self._counter += 1
        return f"req_slice_{self._counter}"

    def json_file(self, name, payload):
        return write_json(self.root / "requests" / name, payload)

    def snapshot(self, name):
        target = self.root / f"stage-{name}.db"
        shutil.copy2(self.db, target)
        self.stages[name] = target
        return target

    def status(self, name):
        payload, _ = run_cli("status", self.db, "--audit", AUDIT)
        self.state[name] = payload
        return payload

    def packet(self, name, *targets, mode="author"):
        out = self.root / "packets" / f"{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        summary, _ = run_cli("get", self.db, *_targets(*targets), "--mode", mode, "--out", out)
        packet = json.loads(out.read_text(encoding="utf-8"))
        self.log[f"packet:{name}"] = packet
        self.log[f"summary:{name}"] = summary
        return packet

    def apply(self, name, packet, edits, *, expect=0):
        batch = self.json_file(f"{name}.json", {
            "contract_version": 3, "request_id": self.request_id(), "packet_id": packet["packet_id"],
            "edits": edits})
        payload, _ = run_cli("apply", self.db, "--batch", batch, expect=expect)
        self.log[name] = payload
        return payload

    def export(self, name):
        out = self.root / f"export-{name}.json"
        run_cli("export", self.db, "--out", out)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.log[f"export:{name}"] = data
        return data

    # -- the slice ---------------------------------------------------------------------------------
    def build(self):
        self._capture()
        self._structure()
        self._audit()
        self._compare()
        self._primary()
        self._draft()
        self._resume()
        self._independent()
        self._reconcile()
        self._report()
        self._concurrency()
        self._wrapper()
        return self

    def _capture(self):
        # STEP 1 -- SOURCE CAPTURE. The paper's bytes enter the database once, and every later
        # statement is anchored into those captured bytes rather than retyped.
        created, _ = run_cli("init", self.db, "--source-root", self.source_root, "--title", "Vertical slice")
        self.paper_id = created["paper_id"]
        self.log["init"] = created
        captured, _ = run_cli("source", "capture", self.db, "--files", self.json_file("files.json", ["paper.tex"]))
        self.log["capture"] = captured
        self.source_id = captured["sources"][0]["id"]
        self.snapshot("captured")

        packet = self.packet("anchors", f"papers:{self.paper_id}")
        anchored, _ = run_cli("source", "anchor", self.db, "--request", self.json_file("anchors.json", {
            "contract_version": 3, "request_id": self.request_id(), "packet_id": packet["packet_id"],
            "anchors": [
                {"id": "anc_lem", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(label="lem:a")},
                {"id": "anc_lem_proof", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(start=8, end=10)},
                {"id": "anc_thm", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(label="thm:b")},
                {"id": "anc_thm_proof", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(start=14, end=16)},
                # The standing assumption the theorem's proof relies on.
                {"id": "anc_mono", "expected_version": None, "source_id": self.source_id,
                 "locator": locator(start=4, end=4)}]}))
        self.log["anchor"] = anchored
        self.snapshot("anchored")
        packet = self.packet("boundary_review", f"papers:{self.paper_id}")
        self.log["boundary_review"], _ = run_cli("source", "review", self.db, "--request",
            self.json_file("boundary_review.json", {"contract_version": 4, "request_id": self.request_id(),
                "packet_id": packet["packet_id"], "edits": [edit("create", "source_reviews", "srv_boundary", {
                    "source_refs": [{"collection": "sources", "id": self.source_id, "version": 1}],
                    "anchor_refs": [{"collection": "anchors", "id": f"anc_{name}_proof", "version": 1} for name in ("lem", "thm")],
                    "purpose": "proof_boundary", "decision": "accepted", "rationale": "Read both full proof environments and their continuations.",
                    "reviewer": "coordinator"})]}))

    def _structure(self):
        # STEPS 2-4 -- the mathematical shape. itm_hidden is the JOINT INFERENCE's conclusion: it
        # follows from boundedness and monotonicity together, so grp_joint carries two uses.
        # itm_asm promotes the standing monotonicity assumption into an explicit audited premise.
        # use_lem_thm and use_hidden_thm are two distinct APPLICATIONS of two suppliers inside the
        # theorem's own group, so a check on one cannot stand in for the other.
        packet = self.packet("structure", f"papers:{self.paper_id}")
        self.log["structure_applied"] = self.apply("structure", packet, [
            Fixture.item_edit("itm_lem", "lemma", "Lemma 1", "anc_lem", "anc_lem_proof"),
            Fixture.item_edit("itm_thm", "theorem", "Theorem 1", "anc_thm", "anc_thm_proof"),
            _item_edit("itm_asm", "assumption", "Monotonicity",
                       [{"role": "statement", "anchor_id": "anc_mono"}]),
            _item_edit("itm_hidden", "intermediate_result", "Bounded and monotone", [],
                       origin="reconstruction", owner="itm_thm"),
            edit("create", "scopes", "scp_plain", {"argument_id": None, "parent_id": None,
                                                   "assumptions": [R("items", "itm_asm")],
                                                   "binders": [], "conditions": [], "evidence_refs": ["anc_mono"]}),
            Fixture.argument_edit("arg_lem", "itm_lem", "grp_lem", "anc_lem_proof"),
            Fixture.argument_edit("arg_thm", "itm_thm", "grp_thm", "anc_thm_proof"),
            Fixture.group_edit("grp_lem", "arg_lem", "itm_lem", "anc_lem_proof"),
            Fixture.group_edit("grp_thm", "arg_thm", "itm_thm", "anc_thm_proof"),
            Fixture.group_edit("grp_joint", "arg_thm", "itm_hidden", "anc_mono"),
            _use_edit("use_lem_thm", "itm_lem", "itm_thm", "grp_thm", "the lemma is applied to the theorem",
                      "anc_thm_proof"),
            _use_edit("use_hidden_thm", "itm_hidden", "itm_thm", "grp_thm", "the hidden claim closes the theorem",
                      "anc_thm_proof"),
            _use_edit("use_lem_hidden", "itm_lem", "itm_hidden", "grp_joint", "boundedness premise", "anc_lem"),
            _use_edit("use_asm_hidden", "itm_asm", "itm_hidden", "grp_joint", "monotonicity premise", "anc_mono"),
            *[edit("create", "target_specs", f"tgt_{name}", {
                "target": R("items", f"itm_{name}"), "statement_ref": {"collection": "items", "id": f"itm_{name}", "version": 1},
                "statement": None, "scope_id": "scp_plain", "evidence_refs": anchors,
                "state": "registered", "fidelity_ref": None})
              for name, anchors in (("lem", ["anc_lem"]), ("thm", ["anc_thm"]), ("asm", ["anc_mono"]), ("hidden", []))],
            *[edit("create", "proof_boundaries", f"bnd_{name}", {"target": R("items", f"itm_{name}"),
                "argument_ids": [f"arg_{name}"], "anchor_refs": [{"collection": "anchors", "id": f"anc_{name}_proof", "version": 1}],
                "source_review_ref": {"collection": "source_reviews", "id": "srv_boundary", "version": 1}, "state": "complete"})
              for name in ("lem", "thm")]])
        self.snapshot("structured")
        self.export("structured")

    def _audit(self):
        # The audit registers who is responsible for what; obligations are derived from the structure
        # above, so nothing here lists them by hand.
        blobs = (b"calibration transcript", b'{"case":"valid-1"}', b'{"case":"invalid-1"}')
        evidence, case_ok, case_bad = blobs
        qualified, _ = run_cli("qualification", "record", self.db, "--receipt", self.json_file("qual.json", {
            "contract_version": 3, "request_id": self.request_id(),
            "edits": [edit("create", "qualifications", "qua_r1", {
                "reviewer": "checker-A",
                "profile": {"provider": "anthropic", "model": "claude-fable-5-1", "effort": "high", "tools": [],
                            "context_isolation": "fresh session, source only"},
                "protocol_version": "item-audit/1",
                "valid_case_results": [{"case_id": "valid-1", "response_blob": sha(case_ok), "outcome": "pass"}],
                "invalid_case_results": [{"case_id": "invalid-1", "response_blob": sha(case_bad), "outcome": "pass"}],
                "evidence_blob": sha(evidence), "qualified": True, "limitations": []})],
            "blobs": [{"sha256": sha(blob), "encoding": "base64", "data": base64.b64encode(blob).decode()}
                      for blob in blobs]}))
        self.log["qualification"] = qualified
        packet = self.packet("audit", *TARGETS, mode="primary")
        self.apply("audit", packet, [edit("create", "audits", AUDIT, {
            "paper_id": self.paper_id, "mode": "focused", "targets": [R(*t.split(":", 1)) for t in TARGETS],
            "exclusions": [], "protocol_version": "item-audit/1", "independent_required": True,
            "qualification_id": "qua_r1", "report_path": "reports/audit.html",
            "global_tasks": [dict(task) for task in GLOBAL_TASKS]})])
        self.snapshot("audited")
        self.status("audited")

    def _primary(self):
        # One premise of the joint inference is checked and the other is not, on purpose: this is what
        # makes "needs both premises" observable rather than asserted.
        packet = self.packet("primary_one", *TARGETS, mode="primary")
        # Account for the entire captured proof passages through the same public edit batch.
        # The remaining application and joint-inference obligations still have to be completed.
        coverage = [edit("create", "coverage", f"cov_{name}", {
            "argument_id": f"arg_{name}", "anchor_id": f"anc_{name}_proof",
            "start_offset": 0, "end_offset": len(_body(packet, "anchors", f"anc_{name}_proof")[0]["excerpt"]),
            "classification": "substantive", "claim_refs": [R("items", f"itm_{name}")],
            "check_ids": [f"chk_der_{name}"], "note": "the captured proof is covered by its derivation"})
                    for name in ("lem", "thm")]
        self.log["primary_one"] = self.apply("primary_one", packet, [
            *coverage,
            Fixture.check_edit("chk_comp_lem", R("arguments", "arg_lem"), "composition", evidence=["anc_lem_proof"]),
            Fixture.check_edit("chk_comp_thm", R("arguments", "arg_thm"), "composition", evidence=["anc_thm_proof"]),
            Fixture.check_edit("chk_der_lem", R("groups", "grp_lem"), "derivation"),
            Fixture.check_edit("chk_der_thm", R("groups", "grp_thm"), "derivation"),
            Fixture.check_edit("chk_app_hidden_thm", R("uses", "use_hidden_thm"), "application"),
            Fixture.check_edit("chk_app_lem_hidden", R("uses", "use_lem_hidden"), "application",
                               evidence=["anc_lem"])])
        self.snapshot("one_premise")
        self.status("one_premise")

        packet = self.packet("primary_two", *TARGETS, mode="primary")
        self.log["primary_two"] = self.apply("primary_two", packet, [
            Fixture.check_edit("chk_app_asm_hidden", R("uses", "use_asm_hidden"), "application",
                               evidence=["anc_mono"])])
        self.snapshot("both_premises")
        self.status("both_premises")

    def _draft(self):
        # STEP 5 -- A SAVED DRAFT. The derivation of the joint step is started and put down unfinished.
        packet = self.packet("draft", *TARGETS, mode="primary")
        self.log["draft"] = self.apply("draft", packet, [
            Fixture.check_edit("chk_der_joint_draft", R("groups", "grp_joint"), "derivation",
                               state="draft", outcome=None)])
        self.draft_pin = _pin(self.log["draft"], "checks", "chk_der_joint_draft")
        self.snapshot("draft")
        self.status("draft")

    def _resume(self):
        # STEP 6 -- RESUMED WORK. Every CLI call closes the database, so this genuinely reopens it; the
        # finished judgment supersedes the saved draft instead of sitting beside it.
        packet = self.packet("resume", *TARGETS, mode="primary")
        self.log["resume"] = self.apply("resume", packet, [
            _check_edit("chk_der_joint", R("groups", "grp_joint"), "derivation", evidence=["anc_mono"],
                        reasoning="both premises together give the hidden claim", supersedes=self.draft_pin)])
        self.snapshot("resumed")
        self.status("resumed")

    def _compare(self):
        # The source-fidelity obligations: each audited statement is read back against its anchor.
        packet = self.packet("compare", *TARGETS, mode="primary")
        batch = self.json_file("compare.json", {
            "contract_version": 3, "request_id": self.request_id(), "packet_id": packet["packet_id"],
            "edits": [edit("create", "observations", oid, {
                "target": R("items", iid), "result": "matched", "reviewer": "primary-1",
                "note": "statement matches the source", "evidence_refs": [anchor]})
                for oid, iid, anchor in (("obs_lem", "itm_lem", "anc_lem"), ("obs_thm", "itm_thm", "anc_thm"),
                                         ("obs_asm", "itm_asm", "anc_mono"))]
            + [edit("create", "observations", f"obs_exact_{name}", {"target": R("target_specs", f"tgt_{name}"),
                "result": "matched", "reviewer": "primary-1", "note": "The exact form and standing setup match the source.",
                "evidence_refs": list(dict.fromkeys([anchor, "anc_mono"]))}) for name, anchor in (("lem", "anc_lem"), ("thm", "anc_thm"), ("asm", "anc_mono"))]})
        payload, _ = run_cli("compare", self.db, "--batch", batch)
        self.log["compare"] = payload
        self.snapshot("compared")
        self.status("compared")

    def _independent(self):
        # STEP 7 -- AN INDEPENDENT RESPONSE. The packet is blinded (handoff 6): the worker sees the
        # statements and the source and nothing the primary reviewer concluded.
        self.independent_checks = {}
        rounds = (("itm_lem", "arg_lem", "anc_lem_proof",
                   {"source_anchor_id": "anc_lem_proof", "description": "the proof of the lemma"}),
                  ("itm_thm", "arg_thm", "anc_thm_proof", R("arguments", "arg_thm")))
        for item_id, argument_id, anchor, judgment_target in rounds:
            packet = self.packet(f"independent_{item_id}", f"items:{item_id}", mode="independent")
            worker = {"packet_id": packet["packet_id"], "covered_targets": [R("items", item_id)],
                      "coverage_note": "read the statement and proof from the source",
                      "exposure_report": {"status": "none_known", "note": ""},
                      "judgments": [{"target": judgment_target, "kind": "composition", "state": "complete",
                                     "outcome": "supported", "reasoning": "independent reading of the proof",
                                     "evidence_refs": [anchor], "conditions": [], "next_action": None,
                                     "supersedes": None}]}
            response_bytes = json.dumps(worker).encode("utf-8")
            response_path = self.root / "requests" / f"response_{item_id}.json"
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_bytes(response_bytes)
            self.responses[item_id] = response_bytes
            submission = self.json_file(f"submission_{item_id}.json", {
                "contract_version": 3, "request_id": self.request_id(), "packet_id": packet["packet_id"],
                "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "source_only",
                "exposure_note": ""})
            submitted, _ = run_cli("review", "submit", self.db, "--submission", submission,
                                   "--response", response_path)
            self.log[f"submit:{item_id}"] = submitted
            # The blinded worker cannot name a record it was never shown, so the coordinator maps the
            # judgment onto the argument it belongs to before it becomes a check.
            mapping_packet = self.packet(f"mapping_{item_id}", *TARGETS, mode="primary")
            mapped, _ = run_cli("review", "map", self.db, "--response", submitted["response_id"],
                                "--mapping", self.json_file(f"mapping_{item_id}.json", {
                                    "contract_version": 3, "request_id": self.request_id(),
                                    "packet_id": mapping_packet["packet_id"],
                                    "response_id": submitted["response_id"],
                                    "entries": [{"judgment_index": 0, "target": R("arguments", argument_id),
                                                 "rationale": "the proof passage is this argument"}],
                                    "reviewer": "coord"}))
            self.log[f"map:{item_id}"] = mapped
            self.independent_checks[item_id] = mapped["checks"][0]
        self.snapshot("independent")
        self.status("independent")

    def _reconcile(self):
        # STEP 8 -- RECONCILIATION. Primary and independent judgments are put side by side and settled.
        primary_pins = {"itm_lem": _pin(self.log["primary_one"], "checks", "chk_comp_lem"),
                        "itm_thm": _pin(self.log["primary_one"], "checks", "chk_comp_thm")}
        packet = self.packet("reconcile", *TARGETS, mode="reconcile")
        batch = self.json_file("reconcile.json", {
            "contract_version": 3, "request_id": self.request_id(), "packet_id": packet["packet_id"],
            "edits": [edit("create", "reconciliations", rec_id, {
                "audit_id": AUDIT, "target": R("arguments", argument_id),
                "primary_checks": [primary_pins[item_id]],
                "independent_checks": [{"collection": "checks",
                                        "id": self.independent_checks[item_id]["check_id"],
                                        "version": self.independent_checks[item_id]["version"]}],
                "decision": "agree", "rationale": "adjudicated", "evidence_refs": [], "successor_checks": [],
                "supersedes": None, "adjudicator": "coord"})
                for rec_id, argument_id, item_id in (("rec_lem", "arg_lem", "itm_lem"),
                                                     ("rec_thm", "arg_thm", "itm_thm"))]})
        payload, _ = run_cli("review", "reconcile", self.db, "--batch", batch)
        self.log["reconcile"] = payload
        self.snapshot("reconciled")
        self.status("reconciled")
        # The worker's own bytes are still in the database and still reachable from the command line.
        self.export("reconciled")

    def _report(self):
        # STEP 9 -- ONE HONEST REPORT, produced while a required obligation is still open.
        if not node_available():
            return
        self.report = self.root / "reports" / "checkpoint.html"
        payload, _ = run_cli("checkpoint", self.db, "--out", self.report, "--audit", AUDIT)
        self.log["checkpoint"] = payload
        self.snapshot("reported")

    def _concurrency(self):
        # STEP 10 -- ONE HARMLESS CONCURRENT EDIT. Two authors take packets at the same revision and
        # touch different items; the second commit rebases onto the first instead of being refused.
        base = self.status("before_concurrency")["head_revision"]
        self.concurrency_base = base
        first = self.packet("harmless_a", "items:itm_lem")
        second = self.packet("harmless_b", "items:itm_asm")
        self.log["harmless_packets"] = (first, second)
        self.log["harmless_a"] = self.apply("harmless_a", first,
                                            [_caption_edit(first, "itm_lem", "Lemma 1 (boundedness)")])
        self.log["harmless_b"] = self.apply("harmless_b", second,
                                            [_caption_edit(second, "itm_asm", "Monotonicity (stated)")])
        self.snapshot("harmless")
        # Read the two harmless captions back out of the database before the conflict step overwrites
        # itm_lem again: without this the only evidence that they landed would be their own receipts.
        self.export("harmless")

        # STEP 11 -- ONE REAL CONFLICT. Two authors take packets at the same revision and both edit the
        # same item; the loser is refused whole and told which command produces a fresh packet.
        winner = self.packet("conflict_winner", "items:itm_lem")
        loser = self.packet("conflict_loser", "items:itm_lem")
        self.conflict_base = self.status("before_conflict")["head_revision"]
        self.log["conflict_winner"] = self.apply("conflict_winner", winner,
                                                 [_caption_edit(winner, "itm_lem", "Lemma 1 (winner)")])
        self.log["conflict_loser"] = self.apply("conflict_loser", loser,
                                                [_caption_edit(loser, "itm_lem", "Lemma 1 (loser)")], expect=3)
        self.snapshot("final")
        self.status("final")
        self.export("final")

    def _wrapper(self):
        # The same database read through the file the package actually ships, with no repository on the
        # import path, so the slice is demonstrable from an installed copy.
        payload, _ = run_wrapper(PROOFCHECK, "status", self.db, "--audit", AUDIT)
        self.log["wrapper"] = payload


BUILT = None
_ROOT = None


def setUpModule():
    global BUILT, _ROOT
    _ROOT = Path(tempfile.mkdtemp(prefix="paper_slice_"))
    BUILT = _SlicePaper(_ROOT).build()


def tearDownModule():
    if _ROOT is not None and Path(_ROOT).exists():
        rmtree_force(_ROOT)


class SliceCase(TempCase):
    """Focused cases that re-open one step of the shared slice, copying the database before mutating it."""

    def db_copy(self, stage):
        target = self.path(f"{stage}.db")
        shutil.copy2(BUILT.stages[stage], target)
        return target

    def head_revision(self, db):
        with storage.Database(db) as handle:
            return handle.max_revision()

    def changed_since(self, db, revision):
        payload, _ = run_cli("changes", db, "--since", str(revision))
        return payload

    def packet_file(self, db, *targets, mode="author", name="packet"):
        out = self.path(f"{name}.json")
        run_cli("get", db, *_targets(*targets), "--mode", mode, "--out", out)
        return json.loads(out.read_text(encoding="utf-8"))

    def batch_file(self, packet, edits, name="batch", request_id="req_case_1"):
        return write_json(self.path(f"{name}.json"), {
            "contract_version": 3, "request_id": request_id, "packet_id": packet["packet_id"], "edits": edits})


class TestVerticalSlice(SliceCase):
    """The whole milestone, in order, over the single database the module built."""

    def test_the_milestone_slice_runs_end_to_end(self):
        """Every step of handoff 11's first milestone lands, in order, on one database."""
        # 1. SOURCE CAPTURE -- the paper's bytes are in the database and the statements point into them.
        captured = BUILT.log["capture"]
        self.assertEqual([entry["path"] for entry in captured["sources"]], ["paper.tex"])
        self.assertEqual(captured["sources"][0]["blob_sha256"], sha(SLICE_TEX.encode("utf-8")))
        self.assertEqual([anchor["id"] for anchor in BUILT.log["anchor"]["anchors"]],
                         ["anc_lem", "anc_lem_proof", "anc_thm", "anc_thm_proof", "anc_mono"])
        self.assertEqual({anchor["source_id"] for anchor in BUILT.log["anchor"]["anchors"]}, {BUILT.source_id})

        # 2. A JOINT INFERENCE -- grp_joint concludes itm_hidden from two premises recorded as uses.
        export = BUILT.log["export:structured"]
        joint = _record(export, "groups", "grp_joint")
        self.assertEqual(joint["body"]["conclusion"], R("items", "itm_hidden"))
        premises = sorted(row["body"]["from"]["id"] for row in export["records"]
                          if row["collection"] == "uses" and
                          _record(export, "application_details", row["id"])["body"]["group_id"] == "grp_joint")
        self.assertEqual(premises, ["itm_asm", "itm_lem"])

        # 3. A HIDDEN CLAIM -- the standing monotonicity hypothesis is an audited item of its own.
        assumption = _record(export, "items", "itm_asm")
        self.assertEqual(assumption["body"]["kind"], "assumption")
        self.assertEqual([p["anchor_id"] for p in assumption["body"]["passages"]], ["anc_mono"])
        audited = BUILT.state["audited"]
        self.assertIn(_obligation_id("items", "itm_asm", "source_fidelity", "primary"),
                      audited["obligations"]["required"])

        # 4. AN APPLICATION CHECK -- bound to one use, not to the lemma in general.
        one_premise = BUILT.state["one_premise"]
        self.assertEqual([ref["id"] for ref in one_premise["assessments"]["uses:use_lem_hidden"]["check_refs"]],
                         ["chk_app_lem_hidden"])
        self.assertEqual(one_premise["assessments"]["uses:use_lem_thm"]["check_refs"], [])
        self.assertEqual(one_premise["assessments"]["uses:use_lem_thm"]["state"], "gray")

        # 5. A SAVED DRAFT -- stored, visible, and counting for nothing.
        draft = BUILT.state["draft"]
        self.assertEqual(draft["progress"]["draft_checks"], 1)
        self.assertIn("chk_der_joint_draft",
                      [ref["id"] for ref in draft["assessments"]["groups:grp_joint"]["check_refs"]])
        self.assertEqual(draft["assessments"]["groups:grp_joint"]["state"], "amber")
        self.assertEqual(draft["progress"]["completed_current_obligations"],
                         BUILT.state["both_premises"]["progress"]["completed_current_obligations"])

        # 6. RESUMED WORK -- the finished judgment replaces the draft and progress moves.
        resumed = BUILT.state["resumed"]
        self.assertEqual(resumed["progress"]["draft_checks"], 0)
        self.assertEqual(sorted(ref["id"] for ref in resumed["assessments"]["groups:grp_joint"]["check_refs"]),
                         ["chk_app_asm_hidden", "chk_app_lem_hidden", "chk_der_joint"])
        self.assertEqual(resumed["assessments"]["groups:grp_joint"]["state"], "green")
        self.assertEqual(resumed["progress"]["completed_current_obligations"],
                         draft["progress"]["completed_current_obligations"] + 1)

        # 7. AN INDEPENDENT RESPONSE -- blinded packet, worker response, submission, mapped judgment.
        blinded = BUILT.log["packet:independent_itm_lem"]
        self.assertEqual(_keys(blinded["read_set"]),
                         ["anchors:anc_lem", "anchors:anc_lem_proof", "anchors:anc_mono", "items:itm_asm",
                          "items:itm_lem", f"sources:{BUILT.source_id}"])
        self.assertEqual(sorted({record["ref"]["collection"] for record in blinded["records"]}),
                         ["anchors", "items", "sources"])
        self.assertEqual(BUILT.log["submit:itm_lem"]["state"], "needs_revision")
        mapped = BUILT.log["map:itm_lem"]["checks"]
        self.assertEqual([entry["judgment_index"] for entry in mapped], [0])
        self.assertEqual(_record(BUILT.log["export:final"], "checks", mapped[0]["check_id"])["body"]["role"],
                         "independent")

        # 8. RECONCILIATION -- primary and independent judgments adjudicated, worker bytes preserved.
        self.assertEqual(sorted(row["id"] for row in BUILT.log["reconcile"]["receipt"]["changed"]),
                         ["rec_lem", "rec_thm"])
        reconciled = BUILT.state["reconciled"]
        self.assertEqual(reconciled["independent"],
                         {"items:itm_lem": "complete", "items:itm_thm": "complete",
                          "items:itm_asm": "not_required", "items:itm_hidden": "not_required"})
        self.assertEqual(self.preserved_responses(BUILT.log["export:reconciled"]),
                         sorted(BUILT.responses.values()))

        # 9. ONE HONEST REPORT -- the projection says the work is unfinished and names what is missing.
        missing = _obligation_id(*MISSING_USE)
        self.assertEqual(reconciled["obligations"]["unsatisfied"], [missing])
        self.assertIs(reconciled["progress"]["process_complete"], False)
        if BUILT.report is None:
            self.skipTest("node is unavailable, so only the rendering of the honest report is skipped")
        self.assertIs(BUILT.log["checkpoint"]["process_complete"], False)
        html = BUILT.report.read_text(encoding="utf-8")
        self.assertIn('data-proof-process-complete="false"', html)
        self.assertIn(f"Missing obligations: <code>{missing}</code>", html)

        # 10. ONE HARMLESS CONCURRENT EDIT -- two packets at one revision, disjoint items, both land.
        first, second = BUILT.log["harmless_packets"]
        self.assertEqual((first["base_revision"], second["base_revision"]),
                         (BUILT.concurrency_base, BUILT.concurrency_base))
        self.assertIsNone(BUILT.log["harmless_a"]["receipt"]["rebased_from"])
        self.assertEqual(BUILT.log["harmless_b"]["receipt"]["rebased_from"], BUILT.concurrency_base)
        self.assertEqual(BUILT.log["harmless_b"]["revision"], BUILT.log["harmless_a"]["revision"] + 1)

        # 11. ONE REAL CONFLICT -- two packets at one revision, the same item, one refused with a rebase.
        error = BUILT.log["conflict_loser"]["error"]
        self.assertEqual(error["code"], "CONFLICT")
        self.assertEqual(error["records"][0]["changed"],
                         [{"actual_version": 3, "expected_version": 2,
                           "ref": R("items", "itm_lem"), "retired": False}])
        self.assertEqual(error["retry"]["command"],
                         "get DB --target items:itm_lem --mode author --out PACKET.json")
        final_captions = {row["id"]: row["body"]["caption"] for row in BUILT.log["export:final"]["records"]
                          if row["collection"] == "items" and not row["retired"]}
        self.assertEqual(final_captions["itm_lem"], "Lemma 1 (winner)")

        # The honesty property of the milestone: status still tells the truth about the whole state.
        final = BUILT.state["final"]
        self.assertIs(final["progress"]["process_complete"], False)
        self.assertEqual(final["obligations"]["unsatisfied"], [missing])
        self.assertEqual(final["revision"], BUILT.log["conflict_winner"]["revision"])
        self.assertEqual(BUILT.log["wrapper"]["obligations"], final["obligations"])

    def preserved_responses(self, export):
        """The worker response bytes an export hands back, decoded from its blob table."""
        blobs = {blob["sha256"]: base64.b64decode(blob["data"]) for blob in export["blobs"]}
        return sorted(blobs[row["body"]["original_blob"]] for row in export["records"]
                      if row["collection"] == "responses" and not row["retired"])


class TestSourceCapture(SliceCase):
    """Step 1: the captured source and the anchors that bind statements into it."""

    def test_capture_stores_the_file_under_its_own_digest(self):
        """The captured source records the real bytes of paper.tex, not a re-typed copy."""
        captured = BUILT.log["capture"]
        self.assertEqual(captured["sources"][0]["blob_sha256"], sha(SLICE_TEX.encode("utf-8")))
        self.assertEqual(captured["sources"][0]["version"], 1)
        self.assertIs(captured["sources"][0]["changed"], True)
        self.assertEqual(captured["sources"][0]["media_type"], "tex")
        self.assertEqual(BUILT.state["audited"]["counts"]["sources"], 1)
        # Capture read the file rather than trusting a caller's description of it.
        self.assertEqual([(d["kind"], d["label"], d["start_line"], d["end_line"], d["proof"])
                          for d in captured["declarations"]],
                         [("lemma", "lem:a", 5, 7, {"start_line": 8, "end_line": 10}),
                          ("theorem", "thm:b", 11, 13, {"start_line": 14, "end_line": 16})])

    def test_anchors_point_at_the_captured_lines_they_claim(self):
        """Each anchor's excerpt digest is the digest of the source lines its locator names."""
        lines = SLICE_TEX.split("\n")
        anchors = {anchor["id"]: anchor for anchor in BUILT.log["anchor"]["anchors"]}
        self.assertEqual(anchors["anc_mono"]["locator"]["start_line"], 4)
        self.assertEqual(anchors["anc_mono"]["locator"]["end_line"], 4)
        self.assertEqual(anchors["anc_mono"]["excerpt_sha256"], sha(lines[3].encode("utf-8")))
        self.assertEqual(anchors["anc_lem"]["method"], "label_match")
        self.assertEqual(anchors["anc_lem"]["excerpt_sha256"], sha("\n".join(lines[4:7]).encode("utf-8")))
        self.assertEqual({anchor["source_version"] for anchor in anchors.values()}, {1})

    def test_recapturing_the_same_bytes_writes_nothing(self):
        """Capture is content-addressed: the unchanged file is recognised and no revision is spent."""
        db = self.db_copy("captured")
        before = self.head_revision(db)
        payload, _ = run_cli("source", "capture", db, "--files",
                             write_json(self.path("again.json"), ["paper.tex"]))
        self.assertIs(payload["changed"], False)
        self.assertIsNone(payload["receipt"])
        self.assertEqual(payload["sources"][0]["version"], 1)
        self.assertEqual(payload["sources"][0]["blob_sha256"], sha(SLICE_TEX.encode("utf-8")))
        self.assertEqual(self.head_revision(db), before)
        self.assertEqual(self.changed_since(db, before)["total"], 0)
        self.assertEqual(BUILT.state["audited"]["progress"]["source_unbound_items"], 0)


class TestJointInference(SliceCase):
    """Step 2: a conclusion that needs two premises together, not either one alone."""

    def test_the_joint_group_records_both_premises_as_inputs(self):
        """grp_joint concludes itm_hidden and both of its premise uses sit inside that group."""
        export = BUILT.log["export:structured"]
        self.assertEqual(_record(export, "groups", "grp_joint")["body"]["conclusion"], R("items", "itm_hidden"))
        self.assertEqual(_record(export, "uses", "use_lem_hidden")["body"]["from"], R("items", "itm_lem"))
        self.assertEqual(_record(export, "uses", "use_asm_hidden")["body"]["from"], R("items", "itm_asm"))
        self.assertEqual([_record(export, "uses", uid)["body"]["to"]
                          for uid in ("use_lem_hidden", "use_asm_hidden")],
                         [R("items", "itm_hidden"), R("items", "itm_hidden")])
        self.assertEqual(_record(export, "items", "itm_hidden")["body"]["owner_id"], "itm_thm")

    def test_one_premise_alone_leaves_the_joint_conclusion_unsupported(self):
        """With only the boundedness premise checked, grp_joint is partial and names what is missing."""
        assessment = BUILT.state["one_premise"]["assessments"]["groups:grp_joint"]
        self.assertEqual(assessment["state"], "amber")
        self.assertEqual(assessment["label"], "partial")
        self.assertEqual(sorted(assessment["missing_obligation_ids"]),
                         sorted([_obligation_id("groups", "grp_joint", "derivation", "primary"),
                                 _obligation_id("uses", "use_asm_hidden", "application", "primary")]))

    def test_both_premises_and_the_derivation_together_support_the_conclusion(self):
        """Only once both premise applications and the derivation are checked does grp_joint turn green."""
        after_second = BUILT.state["both_premises"]["assessments"]["groups:grp_joint"]
        self.assertEqual(after_second["state"], "amber")
        self.assertEqual(after_second["missing_obligation_ids"],
                         [_obligation_id("groups", "grp_joint", "derivation", "primary")])
        resumed = BUILT.state["resumed"]["assessments"]["groups:grp_joint"]
        self.assertEqual(resumed["state"], "green")
        self.assertEqual(resumed["missing_obligation_ids"], [])

    def test_the_derivation_check_alone_does_not_carry_the_joint_conclusion(self):
        """Checking the joint step itself, with neither premise applied, still leaves both premises open."""
        db = self.db_copy("audited")
        packet = self.packet_file(db, *TARGETS, mode="primary")
        run_cli("apply", db, "--batch", self.batch_file(packet, [
            Fixture.check_edit("chk_der_only", R("groups", "grp_joint"), "derivation")], name="deriv_only"))
        payload, _ = run_cli("status", db, "--audit", AUDIT)
        assessment = payload["assessments"]["groups:grp_joint"]
        self.assertEqual([ref["id"] for ref in assessment["check_refs"]], ["chk_der_only"])
        self.assertEqual(assessment["state"], "amber")
        self.assertEqual(sorted(assessment["missing_obligation_ids"]),
                         sorted([_obligation_id("uses", "use_lem_hidden", "application", "primary"),
                                 _obligation_id("uses", "use_asm_hidden", "application", "primary")]))


class TestHiddenClaim(SliceCase):
    """Step 3: an assumption the proof leans on silently, registered so it cannot stay invisible."""

    def test_the_unstated_assumption_is_an_item_of_its_own(self):
        """The monotonicity hypothesis is a first-class assumption anchored to the line that uses it."""
        assumption = _record(BUILT.log["export:structured"], "items", "itm_asm")
        self.assertEqual(assumption["body"]["kind"], "assumption")
        self.assertEqual(assumption["body"]["origin"], "source")
        self.assertEqual([p["anchor_id"] for p in assumption["body"]["passages"]], ["anc_mono"])

    def test_the_hidden_claim_carries_its_own_required_obligation(self):
        """itm_asm is an audit target, so it owns a source-fidelity obligation nothing else discharges."""
        obligation = _obligation_id("items", "itm_asm", "source_fidelity", "primary")
        self.assertIn(obligation, BUILT.state["audited"]["obligations"]["required"])
        self.assertIn(obligation, BUILT.state["audited"]["obligations"]["unsatisfied"])
        self.assertEqual(BUILT.state["audited"]["assessments"]["items:itm_asm"]["missing_obligation_ids"],
                         [obligation])
        compared = BUILT.state["compared"]["assessments"]["items:itm_asm"]
        self.assertEqual([ref["id"] for ref in compared["check_refs"]], ["obs_asm"])
        self.assertNotIn(obligation, BUILT.state["compared"]["obligations"]["unsatisfied"])

    def test_the_hidden_claim_is_wired_into_the_theorem_it_supports(self):
        """The assumption reaches the theorem through the joint step, not by sitting unused beside it."""
        export = BUILT.log["export:structured"]
        self.assertEqual(_record(export, "application_details", "use_asm_hidden")["body"]["group_id"], "grp_joint")
        self.assertEqual(_record(export, "groups", "grp_joint")["body"]["argument_id"], "arg_thm")
        self.assertEqual(_record(export, "arguments", "arg_thm")["body"]["target"], R("items", "itm_thm"))


class TestApplicationCheck(SliceCase):
    """Step 4: a use of a result whose hypotheses are verified at the point of use."""

    def test_the_application_check_is_bound_to_the_use_not_the_supplier(self):
        """chk_app_lem_hidden targets one use of the lemma and leaves the lemma's other use untouched."""
        checks = _record(BUILT.log["export:final"], "checks", "chk_app_lem_hidden")
        self.assertEqual(checks["body"]["target"], R("uses", "use_lem_hidden"))
        self.assertEqual(checks["body"]["kind"], "application")
        assessments = BUILT.state["one_premise"]["assessments"]
        self.assertEqual([ref["id"] for ref in assessments["uses:use_lem_hidden"]["check_refs"]],
                         ["chk_app_lem_hidden"])
        self.assertEqual(assessments["uses:use_lem_thm"]["check_refs"], [])

    def test_each_use_of_the_same_lemma_needs_its_own_check(self):
        """Both uses of itm_lem carry separate application obligations and only one is discharged."""
        required = BUILT.state["reconciled"]["obligations"]["required"]
        for use_id in ("use_lem_thm", "use_lem_hidden"):
            self.assertIn(_obligation_id("uses", use_id, "application", "primary"), required)
        self.assertEqual(BUILT.state["reconciled"]["obligations"]["unsatisfied"],
                         [_obligation_id("uses", "use_lem_thm", "application", "primary")])
        self.assertEqual(BUILT.state["reconciled"]["assessments"]["uses:use_lem_thm"]["state"], "gray")
        self.assertEqual(BUILT.state["reconciled"]["assessments"]["uses:use_lem_hidden"]["state"], "green")

    def test_the_unchecked_application_holds_its_theorem_back(self):
        """The theorem stays partial while one of its applications is unchecked, and lists that obligation."""
        theorem = BUILT.state["reconciled"]["assessments"]["items:itm_thm"]
        self.assertEqual(theorem["state"], "amber")
        self.assertEqual(theorem["missing_obligation_ids"],
                         [_obligation_id("uses", "use_lem_thm", "application", "primary")])
        self.assertEqual(BUILT.state["reconciled"]["assessments"]["items:itm_lem"]["state"], "green")


class TestSavedDraft(SliceCase):
    """Step 5: an incomplete judgment saved as a draft."""

    def test_the_draft_is_stored_and_reopened_from_disk(self):
        """The draft check survives closing the database and reads back as state draft with no outcome."""
        payload, _ = run_cli("status", self.db_copy("draft"), "--audit", AUDIT)
        self.assertEqual(payload["progress"]["draft_checks"], 1)
        body = _record(BUILT.log["export:final"], "checks", "chk_der_joint_draft")["body"]
        self.assertEqual(body["state"], "draft")
        self.assertIsNone(body["outcome"])
        self.assertEqual(body["target"], R("groups", "grp_joint"))

    def test_the_draft_does_not_count_towards_completion(self):
        """Saving the draft raises draft_checks but discharges no obligation and keeps the group amber."""
        before = BUILT.state["both_premises"]["progress"]
        after = BUILT.state["draft"]["progress"]
        self.assertEqual(before["draft_checks"], 0)
        self.assertEqual(after["draft_checks"], 1)
        self.assertEqual(after["completed_current_obligations"], before["completed_current_obligations"])
        self.assertEqual(BUILT.state["draft"]["obligations"]["unsatisfied"],
                         BUILT.state["both_premises"]["obligations"]["unsatisfied"])
        self.assertEqual(BUILT.state["draft"]["assessments"]["groups:grp_joint"]["state"], "amber")

    def test_the_draft_is_visible_on_the_thing_it_is_about(self):
        """The saved draft is attached to grp_joint, so the unfinished work is not hidden from the group."""
        assessment = BUILT.state["draft"]["assessments"]["groups:grp_joint"]
        self.assertIn("chk_der_joint_draft", [ref["id"] for ref in assessment["check_refs"]])
        self.assertEqual(assessment["missing_obligation_ids"],
                         [_obligation_id("groups", "grp_joint", "derivation", "primary")])


class TestResumedWork(SliceCase):
    """Step 6: reopening the database and finishing the saved draft."""

    def test_the_completed_judgment_supersedes_the_draft(self):
        """chk_der_joint pins the draft it replaces, and the group lists the successor instead."""
        body = _record(BUILT.log["export:final"], "checks", "chk_der_joint")["body"]
        self.assertEqual(body["supersedes"], {"collection": "checks", "id": "chk_der_joint_draft", "version": 1})
        refs = [ref["id"] for ref in BUILT.state["resumed"]["assessments"]["groups:grp_joint"]["check_refs"]]
        self.assertIn("chk_der_joint", refs)
        self.assertNotIn("chk_der_joint_draft", refs)

    def test_the_draft_is_replaced_rather_than_duplicated(self):
        """Finishing the draft adds one check and removes the draft from the count, not two live judgments."""
        self.assertEqual(BUILT.state["resumed"]["progress"]["draft_checks"], 0)
        self.assertEqual(BUILT.state["resumed"]["counts"]["checks"],
                         BUILT.state["draft"]["counts"]["checks"] + 1)
        self.assertEqual(sorted(ref["id"] for ref in
                                BUILT.state["resumed"]["assessments"]["groups:grp_joint"]["check_refs"]),
                         ["chk_app_asm_hidden", "chk_app_lem_hidden", "chk_der_joint"])

    def test_progress_moves_when_the_draft_is_completed(self):
        """The derivation obligation the draft could not discharge is discharged by its successor."""
        obligation = _obligation_id("groups", "grp_joint", "derivation", "primary")
        self.assertIn(obligation, BUILT.state["draft"]["obligations"]["unsatisfied"])
        self.assertNotIn(obligation, BUILT.state["resumed"]["obligations"]["unsatisfied"])
        self.assertEqual(BUILT.state["resumed"]["progress"]["completed_current_obligations"],
                         BUILT.state["draft"]["progress"]["completed_current_obligations"] + 1)
        self.assertEqual(BUILT.state["resumed"]["assessments"]["groups:grp_joint"]["state"], "green")


class TestIndependentResponse(SliceCase):
    """Step 7: a blinded packet, a worker response, and its submission."""

    def test_the_independent_packet_carries_no_primary_checks(self):
        """The blinded packet holds the statements, their anchors and the source -- and nothing judged."""
        for item_id, expected in (("itm_lem", ["anchors:anc_lem", "anchors:anc_lem_proof", "anchors:anc_mono",
                                               "items:itm_asm", "items:itm_lem"]),
                                  ("itm_thm", ["anchors:anc_lem", "anchors:anc_mono", "anchors:anc_thm", "anchors:anc_thm_proof",
                                               "items:itm_asm", "items:itm_lem", "items:itm_thm"])):
            packet = BUILT.log[f"packet:independent_{item_id}"]
            self.assertEqual(packet["mode"], "independent")
            self.assertEqual(_keys(packet["read_set"]), sorted(expected + [f"sources:{BUILT.source_id}"]))
            self.assertEqual(_keys(record["ref"] for record in packet["records"]),
                             sorted(expected + [f"sources:{BUILT.source_id}"]))
            if item_id == "itm_thm":
                # Invoking the lemma supplies its statement, not its unborrowed proof.
                self.assertNotIn("anchors:anc_lem_proof", _keys(packet["read_set"]))
            self.assertEqual(packet["write_scope"], [])
            # The one membership guard a blinded packet may carry is the part list of the target item.
            # Any other relation would let the worker infer primary work from a conflict (handoff 6).
            self.assertEqual([(guard["relation"], guard["key"]) for guard in packet["membership_guards"]],
                             [("parts_of_item", R("items", item_id))])
            self.assertEqual(packet["omitted"], [])
            self.assertEqual(packet["declared_scope"],
                             {"audit_id": AUDIT, "mode": "focused", "targets": [R("items", item_id)],
                              "exclusions": [], "protocol_version": "item-audit/1"})

    def test_the_independent_packet_hides_the_reconstruction_and_the_argument(self):
        """A blinded reviewer sees no checks, no arguments, no groups, no uses and no reconstructed claim."""
        collections = set()
        for item_id in ("itm_lem", "itm_thm"):
            packet = BUILT.log[f"packet:independent_{item_id}"]
            collections |= {record["ref"]["collection"] for record in packet["records"]}
            self.assertNotIn("items:itm_hidden", _keys(record["ref"] for record in packet["records"]))
        self.assertEqual(sorted(collections), ["anchors", "items", "sources"])

    def test_the_worker_response_becomes_a_mapped_independent_check(self):
        """The submission is held for mapping, then the coordinator binds it to the argument it judged."""
        submitted = BUILT.log["submit:itm_lem"]
        self.assertEqual(submitted["state"], "needs_revision")
        self.assertEqual(submitted["checks"], [])
        self.assertEqual([entry["judgment_index"] for entry in submitted["pending"]], [0])
        mapped = BUILT.log["map:itm_lem"]
        self.assertEqual([entry["judgment_index"] for entry in mapped["checks"]], [0])
        check_id = mapped["checks"][0]["check_id"]
        body = _record(BUILT.log["export:final"], "checks", check_id)["body"]
        self.assertEqual(body["role"], "independent")
        self.assertEqual(body["target"], R("arguments", "arg_lem"))
        self.assertEqual(body["response_id"], submitted["response_id"])

    def test_the_independent_round_discharges_the_independent_obligation(self):
        """Both arguments' independent composition obligations close only after the rounds are mapped."""
        for argument_id in ("arg_lem", "arg_thm"):
            obligation = _obligation_id("arguments", argument_id, "composition", "independent")
            self.assertIn(obligation, BUILT.state["compared"]["obligations"]["unsatisfied"])
            self.assertNotIn(obligation, BUILT.state["independent"]["obligations"]["unsatisfied"])
        self.assertEqual(BUILT.state["compared"]["independent"]["items:itm_lem"], "pending")
        self.assertEqual(BUILT.state["independent"]["independent"]["items:itm_lem"], "pending")


class TestReconciliation(SliceCase):
    """Step 8: mapping the independent judgments against the primary ones and settling them."""

    def test_reconciliation_pins_the_two_judgments_it_settled(self):
        """Each reconciliation names the exact primary and independent check versions it adjudicated."""
        body = _record(BUILT.log["export:final"], "reconciliations", "rec_lem")["body"]
        self.assertEqual(body["decision"], "agree")
        self.assertEqual(body["target"], R("arguments", "arg_lem"))
        self.assertEqual(body["primary_checks"], [{"collection": "checks", "id": "chk_comp_lem", "version": 1}])
        self.assertEqual(body["independent_checks"],
                         [{"collection": "checks", "id": BUILT.independent_checks["itm_lem"]["check_id"],
                           "version": BUILT.independent_checks["itm_lem"]["version"]}])

    def test_reconciliation_closes_the_coordinator_obligations(self):
        """The reconciliation obligations on both proved statements are the ones that move here."""
        before = set(BUILT.state["independent"]["obligations"]["unsatisfied"])
        after = set(BUILT.state["reconciled"]["obligations"]["unsatisfied"])
        self.assertEqual(before - after, {_obligation_id("items", "itm_lem", "reconciliation", "coordinator"),
                                          _obligation_id("items", "itm_thm", "reconciliation", "coordinator")})
        self.assertEqual(after, {_obligation_id(*MISSING_USE)})
        self.assertEqual(BUILT.state["reconciled"]["independent"]["items:itm_thm"], "complete")

    def test_the_original_independent_response_survives_unedited(self):
        """After reconciliation the worker's exact submitted bytes still come back out of the database."""
        export = BUILT.log["export:reconciled"]
        blobs = {blob["sha256"]: base64.b64decode(blob["data"]) for blob in export["blobs"]}
        preserved = sorted(blobs[row["body"]["original_blob"]] for row in export["records"]
                           if row["collection"] == "responses" and not row["retired"])
        self.assertEqual(preserved, sorted(BUILT.responses.values()))
        for item_id, raw in BUILT.responses.items():
            response = _record(export, "responses", BUILT.log[f"submit:{item_id}"]["response_id"])
            self.assertEqual(response["body"]["original_blob"], sha(raw))
            self.assertEqual(blobs[response["body"]["original_blob"]], raw)
            self.assertEqual(json.loads(raw.decode("utf-8"))["judgments"][0]["outcome"], "supported")


class TestHonestReport(SliceCase):
    """Step 9: a report that shows the real state, including what is unfinished."""

    def setUp(self):
        super().setUp()
        if BUILT.report is None:
            self.skipTest("node is unavailable, so only the report rendering is skipped")
        self.html = BUILT.report.read_text(encoding="utf-8")
        self.counts = dict(re.findall(r'data-proof-count="([^"]+)"[^>]*>([^<]*)<', self.html))

    def test_the_report_reports_the_work_as_incomplete(self):
        """checkpoint publishes while an obligation is open and marks the page not process-complete."""
        self.assertIs(BUILT.log["checkpoint"]["process_complete"], False)
        self.assertEqual(BUILT.log["checkpoint"]["kind"], "working")
        self.assertEqual(BUILT.log["checkpoint"]["revision"], BUILT.state["reconciled"]["revision"])
        self.assertIn('data-proof-process-complete="false"', self.html)
        self.assertNotIn('data-proof-process-complete="true"', self.html)

    def test_the_report_names_the_specific_unfinished_obligation(self):
        """The one obligation the slice left open is visible in the page body, not only in the data."""
        missing = _obligation_id(*MISSING_USE)
        self.assertIn(f"Missing obligations: <code>{missing}</code>", self.html)
        projection = json.loads(re.search(r'<script id="proof-projection"[^>]*>(.*?)</script>',
                                          self.html, re.S).group(1))
        self.assertEqual(projection["summary"]["progress"], BUILT.state["reconciled"]["progress"])
        unfinished = [node for node in projection["nodes"] if node["assessment"]["missing_obligation_ids"]]
        self.assertEqual([(node["id"], node["assessment"]["state"]) for node in unfinished], [("itm_thm", "amber")])

    def test_the_report_shows_no_green_where_the_work_is_incomplete(self):
        """The counted progress and node colours match status exactly; the unfinished theorem is not green."""
        progress = BUILT.state["reconciled"]["progress"]
        self.assertEqual(self.counts["progress.required_obligations"], str(progress["required_obligations"]))
        self.assertEqual(self.counts["progress.completed_current_obligations"],
                         str(progress["completed_current_obligations"]))
        self.assertNotEqual(progress["completed_current_obligations"], progress["required_obligations"])
        self.assertEqual(self.counts["nodes.amber"], "1")
        self.assertEqual(self.counts["nodes.green"], "2")
        self.assertEqual(BUILT.log["checkpoint"]["receipt"]["python_acceptance"]["failures"], [])
        self.assertEqual(BUILT.log["checkpoint"]["receipt"]["python_acceptance"]["status"], "pass")

    def test_release_is_refused_while_an_obligation_is_open(self):
        """release names the open obligation, exits 2 and writes neither a directory nor a revision."""
        db = self.db_copy("reconciled")
        before = self.head_revision(db)
        out = self.path("release")
        payload, _ = run_cli("release", db, "--audit", AUDIT, "--out", out, expect=2)
        self.assertEqual(payload["error"]["code"], "RELEASE_BLOCKED")
        self.assertEqual(payload["error"]["records"],
                         [{"kind": "obligation", "id": _obligation_id(*MISSING_USE)}])
        self.assertFalse(out.exists())
        self.assertEqual(self.head_revision(db), before)
        self.assertEqual(self.changed_since(db, before)["total"], 0)

    def test_completing_the_last_check_flips_the_report_to_complete(self):
        """The unfinished state is real: checking the last application makes status and release succeed."""
        db = self.db_copy("reconciled")
        packet = self.packet_file(db, *TARGETS, mode="primary")
        run_cli("apply", db, "--batch", self.batch_file(packet, [
            Fixture.check_edit("chk_app_lem_thm", R("uses", "use_lem_thm"), "application",
                               evidence=["anc_thm_proof"])], name="last"))
        payload, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertIs(payload["progress"]["process_complete"], True)
        self.assertEqual(payload["obligations"]["unsatisfied"], [])
        self.assertEqual(payload["assessments"]["uses:use_lem_thm"]["state"], "green")
        self.assertEqual(payload["assessments"]["items:itm_thm"]["state"], "green")
        released, _ = run_cli("release", db, "--audit", AUDIT, "--out", self.path("release"))
        self.assertEqual(released["files"], ["report.html", "export.json", "receipt.json"])


class TestConcurrentEdits(SliceCase):
    """Steps 10 and 11: one harmless concurrent edit and one real conflict."""

    def test_two_disjoint_edits_from_one_revision_both_land(self):
        """Packets taken at the same revision on different items commit one after the other, rebased."""
        first, second = BUILT.log["harmless_packets"]
        self.assertEqual((first["base_revision"], second["base_revision"]),
                         (BUILT.concurrency_base, BUILT.concurrency_base))
        self.assertIn("items:itm_lem", _keys(first["write_scope"]))
        self.assertIn("items:itm_asm", _keys(second["write_scope"]))
        # The explicit standing assumption is part of the lemma's setup, while
        # the two actual edits still address distinct records.
        self.assertIn("items:itm_asm", _keys(first["write_scope"]))
        self.assertNotIn("items:itm_lem", _keys(second["write_scope"]))
        self.assertEqual(BUILT.log["harmless_a"]["receipt"]["changed"],
                         [{"collection": "items", "id": "itm_lem", "op": "replace", "version": 2}])
        self.assertEqual(BUILT.log["harmless_b"]["receipt"]["changed"],
                         [{"collection": "items", "id": "itm_asm", "op": "replace", "version": 2}])
        self.assertIsNone(BUILT.log["harmless_a"]["receipt"]["rebased_from"])
        self.assertEqual(BUILT.log["harmless_b"]["receipt"]["rebased_from"], BUILT.concurrency_base)
        self.assertEqual(BUILT.log["harmless_b"]["receipt"]["warnings"], [])
        # "Both commit" has to mean both edits are *in the database*: a pair of receipts describing
        # writes that silently did nothing would satisfy every assertion above. So read the captions
        # back from the snapshot taken between the harmless step and the conflict step, and check the
        # revision counter moved by exactly those two commits and no more.
        landed = {row["id"]: (row["body"]["caption"], row["version"])
                  for row in BUILT.log["export:harmless"]["records"]
                  if row["collection"] == "items" and not row["retired"]}
        self.assertEqual(landed["itm_lem"], ("Lemma 1 (boundedness)", 2))
        self.assertEqual(landed["itm_asm"], ("Monotonicity (stated)", 2))
        self.assertEqual(BUILT.conflict_base, BUILT.concurrency_base + 2)
        self.assertEqual((BUILT.log["harmless_a"]["revision"], BUILT.log["harmless_b"]["revision"]),
                         (BUILT.concurrency_base + 1, BUILT.concurrency_base + 2))

    def test_a_harmless_edit_changes_no_assessment(self):
        """Both captions land and the mathematical state is exactly what it was before the two edits."""
        captions = {row["id"]: row["body"]["caption"] for row in BUILT.log["export:final"]["records"]
                    if row["collection"] == "items" and not row["retired"]}
        self.assertEqual(captions["itm_asm"], "Monotonicity (stated)")
        # before_concurrency and before_conflict bracket the two harmless commits and nothing else, so
        # the comparison isolates them; the previous step's checkpoint publication falls outside it.
        # The revision assertion is what stops "nothing changed" from being trivially true.
        before, after = BUILT.state["before_concurrency"], BUILT.state["before_conflict"]
        self.assertEqual(after["head_revision"], before["head_revision"] + 2)
        # Whole assessments, not only their colours: an inert edit must not move an explanation, a
        # pinned check version, a finding or an independent indicator either.
        self.assertEqual(after["assessments"], before["assessments"])
        self.assertEqual(after["progress"], before["progress"])
        self.assertEqual(after["obligations"], before["obligations"])
        self.assertEqual(after["independent"], before["independent"])
        self.assertEqual(after["findings"], before["findings"])
        self.assertEqual(after["counts"], before["counts"])

    def test_overlapping_edits_conflict_and_name_the_rebase_command(self):
        """The loser is refused whole, told what changed, and given the get command that rebases it."""
        error = BUILT.log["conflict_loser"]["error"]
        self.assertEqual(error["code"], "CONFLICT")
        self.assertEqual(error["message"],
                         "the packet's inputs changed; request a replacement packet and rebase the batch")
        self.assertEqual(error["records"][0]["changed"],
                         [{"actual_version": 3, "expected_version": 2, "ref": R("items", "itm_lem"),
                           "retired": False}])
        self.assertEqual(error["records"][0]["changed_relations"], [])
        self.assertIs(error["records"][0]["source_context_changed"], False)
        self.assertEqual(error["retry"], {"command": "get DB --target items:itm_lem --mode author --out PACKET.json",
                                          "mode": "author", "targets": [R("items", "itm_lem")]})

    def test_the_refused_edit_wrote_nothing(self):
        """After the conflict the winner's caption stands at version 3 and no revision was added for the loser."""
        self.assertEqual(BUILT.state["final"]["head_revision"], BUILT.log["conflict_winner"]["revision"])
        self.assertEqual(BUILT.state["final"]["revision"], BUILT.conflict_base + 1)
        item = _record(BUILT.log["export:final"], "items", "itm_lem")
        self.assertEqual(item["body"]["caption"], "Lemma 1 (winner)")
        self.assertEqual(item["version"], 3)
        captions = [row["body"]["caption"] for row in BUILT.log["export:final"]["records"]
                    if row["collection"] == "items"]
        self.assertNotIn("Lemma 1 (loser)", captions)
        # Exactly one record version exists after the shared base revision -- the winner's. A loser
        # that committed anything, even a retired or superseded row, would be a second entry here.
        self.assertEqual(self.changed_since(self.db_copy("final"), BUILT.conflict_base)["records"],
                         [{"collection": "items", "id": "itm_lem", "version": 3,
                           "revision": BUILT.conflict_base + 1, "retired": False, "op": "replace"}])

    def test_a_rebased_retry_of_the_refused_edit_succeeds(self):
        """The refusal is recoverable: the named command yields a packet whose batch then commits."""
        db = self.db_copy("final")
        before = self.head_revision(db)
        packet = self.packet_file(db, "items:itm_lem", name="retry")
        run_cli("apply", db, "--batch", self.batch_file(
            packet, [_caption_edit(packet, "itm_lem", "Lemma 1 (rebased)")], name="retry_batch"))
        payload, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertEqual(payload["head_revision"], before + 1)
        self.assertEqual(payload["progress"], BUILT.state["final"]["progress"])


class TestPacketDiscipline(SliceCase):
    """Handoff 4.2 on the milestone database: the packet bounds what a batch may write and create.

    The rest of this module walks the slice forwards; these cases stand on the same finished database
    and push against its edges. Each refusal is asserted twice over -- the envelope the operator sees,
    and the fact that the revision counter did not move and the record still reads as it did -- because
    a refusal that quietly half-committed would print exactly the same error.
    """

    def refuse(self, db, batch, code):
        """Apply a batch that must be refused; assert the code and that nothing at all was written."""
        before = self.head_revision(db)
        payload, _ = run_cli("apply", db, "--batch", batch, expect=2)
        self.assertEqual(payload["error"]["code"], code)
        self.assertEqual(self.head_revision(db), before)
        self.assertEqual(self.changed_since(db, before)["total"], 0)
        return payload["error"]

    def test_editing_a_record_outside_the_packets_write_scope_is_refused(self):
        """An existing record may only be replaced through a packet that listed it; itm_asm's cannot."""
        db = self.db_copy("final")
        asm = self.packet_file(db, "items:itm_asm", name="scope_asm")
        lem = self.packet_file(db, "items:itm_lem", name="scope_lem")
        self.assertNotIn("items:itm_lem", _keys(asm["write_scope"]))
        error = self.refuse(db, self.batch_file(asm, [_caption_edit(lem, "itm_lem", "Lemma 1 (smuggled)")],
                                                name="scope_batch", request_id="req_scope_1"), "WRITE_SCOPE")
        self.assertEqual(error["records"], ["edits/0: items:itm_lem is not in the packet's write scope"])
        fresh = self.packet_file(db, "items:itm_lem", name="scope_after")
        self.assertEqual(_body(fresh, "items", "itm_lem")[0]["caption"], "Lemma 1 (winner)")

    def test_a_new_record_outside_the_packets_target_scope_is_refused(self):
        """A packet drawn for the lemma cannot mint a judgment about the theorem's own proof."""
        # Write scope governs records that already exist; a *created* record is bounded instead by the
        # packet's declared targets, which is why this needs its own case (handoff 4.2).
        db = self.db_copy("final")
        packet = self.packet_file(db, "items:itm_lem", mode="primary", name="target_scope")
        error = self.refuse(db, self.batch_file(
            packet, [Fixture.check_edit("chk_out_of_scope", R("groups", "grp_thm"), "derivation")],
            name="target_batch", request_id="req_target_1"), "INVALID_BATCH")
        self.assertEqual(error["records"],
                         ["edits/0 checks:chk_out_of_scope: outside the packet's target scope "
                          "(owners ['audit:aud_1', 'item:itm_thm'], allowed ['item:itm_lem'])"])
        payload, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertEqual([ref["id"] for ref in payload["assessments"]["groups:grp_thm"]["check_refs"]],
                         ["chk_der_thm", "chk_app_hidden_thm"])

    def test_a_forged_independent_judgment_cannot_enter_through_apply(self):
        """Independent work enters only through review submit; apply refuses both forgeries at once."""
        # The blinding of step 7 is worth nothing if a coordinator can simply write the second opinion
        # themselves, so ordinary apply refuses a check that claims the independent role and one that
        # claims a worker response. Both edits are listed, which also shows the batch is judged whole.
        db = self.db_copy("final")
        packet = self.packet_file(db, *TARGETS, mode="primary", name="forge")
        role = Fixture.check_edit("chk_forged_role", R("arguments", "arg_thm"), "composition",
                                  role="independent")
        borrowed = Fixture.check_edit("chk_forged_response", R("arguments", "arg_thm"), "composition")
        borrowed["body"]["response_id"] = BUILT.log["submit:itm_thm"]["response_id"]
        error = self.refuse(db, self.batch_file(packet, [role, borrowed], name="forge_batch",
                                                request_id="req_forge_1"), "INVALID_REQUEST")
        self.assertEqual(error["message"], "batch rejected")
        self.assertEqual(error["records"],
                         ["edits/0: independent checks enter through review submit, not apply",
                          "edits/1: checks with a response_id enter through review submit"])
        payload, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertEqual(payload["counts"]["checks"], BUILT.state["final"]["counts"]["checks"])
        self.assertEqual(payload["independent"], BUILT.state["final"]["independent"])

    def test_one_bad_edit_refuses_the_whole_batch(self):
        """A valid first edit does not survive an invalid second: the batch commits whole or not at all."""
        # The first edit here is the very one the slice left undone, so if the loop that validates a
        # batch ever stopped at the first clean edit, this database would silently become complete.
        db = self.db_copy("reconciled")
        packet = self.packet_file(db, *TARGETS, mode="primary", name="atomic")
        error = self.refuse(db, self.batch_file(packet, [
            Fixture.check_edit("chk_app_lem_thm", R("uses", "use_lem_thm"), "application",
                               evidence=["anc_thm_proof"]),
            Fixture.check_edit("chk_dangling", R("groups", "grp_ghost"), "derivation")],
            name="atomic_batch", request_id="req_atomic_1"), "INVALID_BATCH")
        self.assertEqual(error["records"],
                         ["edits/1 checks:chk_dangling /target: no live groups record grp_ghost"])
        payload, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertEqual(payload["obligations"]["unsatisfied"], [_obligation_id(*MISSING_USE)])
        self.assertEqual(payload["assessments"]["uses:use_lem_thm"]["check_refs"], [])
        self.assertIs(payload["progress"]["process_complete"], False)


class TestRepeatedRequests(SliceCase):
    """Handoff 4.3-4.4: a request id names exactly one batch, and repeating it commits once."""

    LAST_CHECK = ("chk_app_lem_thm", "use_lem_thm", "application")

    def last_check(self, cid="chk_app_lem_thm"):
        """The one judgment the slice deliberately left undone, so a replay has a visible effect."""
        return Fixture.check_edit(cid, R("uses", "use_lem_thm"), "application", evidence=["anc_thm_proof"])

    def test_replaying_the_same_batch_returns_the_first_receipt(self):
        """The identical batch sent twice yields one commit and byte-identical output both times."""
        db = self.db_copy("reconciled")
        packet = self.packet_file(db, *TARGETS, mode="primary", name="replay")
        batch = self.batch_file(packet, [self.last_check()], name="replay_batch", request_id="req_replay_1")
        first, _ = run_cli("apply", db, "--batch", batch)
        committed = self.head_revision(db)
        # The first send must really have changed something, or "the replay changed nothing" is empty.
        self.assertEqual(first["receipt"]["changed"],
                         [{"collection": "checks", "id": "chk_app_lem_thm", "op": "create", "version": 1}])
        second, _ = run_cli("apply", db, "--batch", batch)
        self.assertEqual(second, first)
        self.assertEqual(self.head_revision(db), committed)
        self.assertEqual(self.changed_since(db, committed)["total"], 0)
        payload, _ = run_cli("status", db, "--audit", AUDIT)
        # One judgment on the use, not two: a replay that committed again would double the findings.
        self.assertEqual([ref["id"] for ref in payload["assessments"]["uses:use_lem_thm"]["check_refs"]],
                         ["chk_app_lem_thm"])
        self.assertEqual(payload["counts"]["checks"], BUILT.state["reconciled"]["counts"]["checks"] + 1)
        self.assertIs(payload["progress"]["process_complete"], True)

    def test_reusing_the_request_id_for_a_different_batch_is_refused(self):
        """A spent request id cannot name different bytes; the second batch is refused and writes nothing."""
        db = self.db_copy("reconciled")
        packet = self.packet_file(db, *TARGETS, mode="primary", name="reuse")
        first, _ = run_cli("apply", db, "--batch", self.batch_file(
            packet, [self.last_check()], name="reuse_first", request_id="req_reuse_1"))
        before = self.head_revision(db)
        payload, _ = run_cli("apply", db, "--batch", self.batch_file(
            packet, [self.last_check("chk_app_lem_thm_again")], name="reuse_second",
            request_id="req_reuse_1"), expect=2)
        self.assertEqual(payload["error"]["code"], "REQUEST_ID_REUSED")
        self.assertEqual(payload["error"]["message"],
                         "request id req_reuse_1 was already used for a different batch")
        self.assertEqual(payload["error"]["records"],
                         [{"request_id": "req_reuse_1", "revision": first["revision"]}])
        self.assertEqual(self.head_revision(db), before)
        self.assertEqual(self.changed_since(db, before)["total"], 0)
        status, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertEqual([ref["id"] for ref in status["assessments"]["uses:use_lem_thm"]["check_refs"]],
                         ["chk_app_lem_thm"])


class TestExitCodes(SliceCase):
    """The documented exit codes of handoff 5, on the database the slice actually built."""

    def test_an_incomplete_assessment_is_a_successful_status_query(self):
        """status exits 0 and reports process_complete false; incompleteness is not a command failure."""
        payload, stderr = run_cli("status", self.db_copy("final"), "--audit", AUDIT)
        self.assertIs(payload["progress"]["process_complete"], False)
        self.assertIs(payload["process_complete"], False)
        self.assertEqual(payload["obligations"]["unsatisfied"], [_obligation_id(*MISSING_USE)])
        self.assertEqual(stderr, "")

    def test_an_invalid_request_exits_two_and_writes_nothing(self):
        """A malformed file list is refused as invalid, leaving the revision counter where it was."""
        db = self.db_copy("final")
        before = self.head_revision(db)
        payload, _ = run_cli("source", "capture", db, "--files",
                             write_json(self.path("bad.json"), {"paths": ["paper.tex"]}), expect=2)
        self.assertEqual(payload["error"]["message"],
                         'the file list must be a JSON array of relative paths (or {"files": [...]})')
        self.assertEqual(self.head_revision(db), before)
        self.assertEqual(self.changed_since(db, before)["total"], 0)

    def test_a_conflict_exits_three(self):
        """A batch whose base revision moved under it exits 3, and the refused writer changes nothing."""
        # The build's own conflict is asserted by TestConcurrentEdits. This reproduces one here so that
        # the exit code is pinned by a command *this* test runs: run_cli fails on any other code, so a
        # core that downgraded a conflict to 0 or 2 would be caught here rather than in module setup.
        db = self.db_copy("harmless")
        before = self.head_revision(db)
        winner = self.packet_file(db, "items:itm_lem", name="exit3_winner")
        loser = self.packet_file(db, "items:itm_lem", name="exit3_loser")
        run_cli("apply", db, "--batch", self.batch_file(
            winner, [_caption_edit(winner, "itm_lem", "Lemma 1 (first)")],
            name="exit3_w", request_id="req_exit3_w"))
        payload, _ = run_cli("apply", db, "--batch", self.batch_file(
            loser, [_caption_edit(loser, "itm_lem", "Lemma 1 (second)")],
            name="exit3_l", request_id="req_exit3_l"), expect=3)
        self.assertEqual(payload["error"]["code"], "CONFLICT")
        self.assertEqual(sorted(payload["error"]), ["code", "message", "records", "retry"])
        self.assertEqual(self.head_revision(db), before + 1)
        fresh = self.packet_file(db, "items:itm_lem", name="exit3_after")
        self.assertEqual(_body(fresh, "items", "itm_lem")[0]["caption"], "Lemma 1 (first)")

    def test_an_unreadable_storage_format_exits_four(self):
        """A database written by a newer core is refused as incompatible and names what this core reads."""
        db = self.db_copy("final")
        connection = sqlite3.connect(db)
        try:
            connection.execute("UPDATE metadata SET value='99' WHERE key='storage_format'")
            connection.commit()
        finally:
            connection.close()
        payload, _ = run_cli("status", db, "--audit", AUDIT, expect=4)
        self.assertEqual(payload["error"]["code"], "INCOMPATIBLE")
        self.assertEqual(payload["error"]["message"], "unsupported storage_format '99'; this core reads [2, 3, 4]")

    def test_a_missing_source_exits_five_and_writes_nothing(self):
        """Capturing a file that is not there is a source problem, and no source record is created."""
        db = self.db_copy("final")
        before = self.head_revision(db)
        payload, _ = run_cli("source", "capture", db, "--files",
                             write_json(self.path("ghost.json"), ["ghost.tex"]), expect=5)
        self.assertEqual(payload["error"]["code"], "SOURCE_UNAVAILABLE")
        self.assertTrue(payload["error"]["message"].endswith(
            "ghost.tex: not a readable file; supply the source or correct its path"),
            payload["error"]["message"])
        self.assertEqual(self.head_revision(db), before)
        self.assertEqual(self.changed_since(db, before)["total"], 0)
        after, _ = run_cli("status", db, "--audit", AUDIT)
        self.assertEqual(after["counts"]["sources"], 1)

    def test_a_missing_renderer_exits_six_and_leaves_no_report(self):
        """With no node on PATH the checkpoint fails to render, keeps no half-written page, and commits nothing."""
        db = self.db_copy("final")
        before = self.head_revision(db)
        output = self.path("norender", "report.html")
        payload, _ = run_cli("checkpoint", db, "--out", output, "--audit", AUDIT, expect=6,
                             env=dict(CLI_ENV, PATH=""))
        self.assertEqual(payload["error"]["code"], "PUBLICATION_FAILED")
        self.assertEqual(payload["error"]["message"],
                         "Node.js is required to render reports but no `node` executable was found")
        self.assertIs(payload["error"]["records"][-1]["prior_output_retained"], False)
        self.assertFalse(output.exists())
        self.assertEqual(self.changed_since(db, before)["total"], 0)


class TestShippedEntryPoint(SliceCase):
    """The slice is demonstrable through the file the package ships, not only through the module path."""

    def test_the_packaged_wrapper_reads_the_same_database(self):
        """scripts/paper_audit.py, run with no repository on sys.path, reports the slice's real state."""
        wrapper = BUILT.log["wrapper"]
        final = BUILT.state["final"]
        self.assertIs(wrapper["process_complete"], False)
        self.assertEqual(wrapper["revision"], final["revision"])
        # Anchored on the obligation identity recomputed in this module, so the shipped wrapper is
        # compared against the documented answer and not only against the module CLI's own answer.
        self.assertEqual(wrapper["obligations"]["unsatisfied"], [_obligation_id(*MISSING_USE)])
        self.assertIn(_obligation_id("items", "itm_asm", "source_fidelity", "primary"),
                      wrapper["obligations"]["required"])
        self.assertEqual(wrapper["obligations"], final["obligations"])
        self.assertEqual(wrapper["progress"], final["progress"])
        self.assertEqual(wrapper["counts"], final["counts"])
        self.assertTrue((PROOFCHECK / "scripts" / "paper_audit.py").is_file())


if __name__ == "__main__":
    unittest.main()
