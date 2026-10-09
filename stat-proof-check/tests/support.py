"""Shared fixtures for the new-format test lane (implementation-handoff 9).

Every test in this folder builds its data through the real acceptance path, never by writing rows
directly, so a fixture that stops being reachable through the public API fails loudly. Nothing here
imports the legacy monolith; legacy modules are imported only by the tests that build legacy fixtures.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "scripts"
CORE = SHARED / "paper_core"
PROOFCHECK = REPO
OVERVIEW = REPO.parent / "proof-graphify"
REFERENCE_AUDIT = REPO.parent / "tests" / "fixtures" / "reference-audit" / "proofcheck-audit"
OVERVIEW_EXAMPLE = OVERVIEW / "examples" / "representer-theorem"
HANDOFF = REPO.parent / "tests" / "new_format" / "fixtures" / "legacy-handoff"
TOOLS = REPO.parent / "tools"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from paper_core import acceptance, packets, review, sources, storage  # noqa: E402

CLI_ENV = dict(os.environ, PYTHONPATH=str(SHARED), PYTHONDONTWRITEBYTECODE="1")

PAPER_TEX = "\n".join([
    r"\documentclass{article}",
    r"\newtheorem{theorem}{Theorem}",
    r"\newtheorem{lemma}{Lemma}",
    r"\begin{document}",
    r"\begin{lemma}\label{lem:a}",
    r"For every $n$, $a_n \le 1$.",
    r"\end{lemma}",
    r"\begin{proof}",
    r"By induction on $n$.",
    r"\end{proof}",
    r"\begin{theorem}\label{thm:b}",
    r"The sequence $a_n$ converges.",
    r"\end{theorem}",
    r"\begin{proof}",
    r"Lemma~\ref{lem:a} gives boundedness; monotonicity gives convergence.",
    r"\end{proof}",
    r"\end{document}", ""])

GLOBAL_TASKS = [{"kind": kind, "applicability": "not_applicable", "reason": "outside this fixture"}
                for kind in ("global_consistency", "adversarial", "method_interface")]


# -- small helpers ---------------------------------------------------------------------------------
def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def R(collection: str, id: str) -> dict:
    return {"collection": collection, "id": id}


def edit(op: str, collection: str, id: str, body, expected=None) -> dict:
    return {"op": op, "collection": collection, "id": id, "expected_version": expected, "body": body}


def locator(label=None, start=None, end=None, page=None) -> dict:
    return {"start_line": start, "end_line": end, "page": page, "label": label}


def rmtree_force(path) -> None:
    """Remove a tree that may hold read-only release artifacts."""
    def onexc(func, target, exc):
        os.chmod(target, 0o666)
        func(target)
    shutil.rmtree(path, onexc=onexc)


def node_available() -> bool:
    return shutil.which("node") is not None


def write_json(path, payload) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=1)
        stream.write("\n")
    return path


def run_cli(*args, expect=0, env=None, raw=False, cwd=None):
    """Run the module CLI in a subprocess; assert the exit code and return ``(payload, stderr)``."""
    command = [sys.executable, "-B", "-m", "paper_core.cli", *[str(a) for a in args]]
    proc = subprocess.run(command, env=env or CLI_ENV, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect} for {args}\n"
                             f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    if raw:
        return proc.stdout, proc.stderr
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"stdout is not one JSON object for {args}:\n{proc.stdout!r}\n{proc.stderr}") from None
    if not isinstance(payload, dict):
        raise AssertionError(f"stdout is not a JSON object: {payload!r}")
    if expect != 0 and payload.get("ok") is not False:
        if "error" not in payload or not set(payload["error"]) >= {"code", "message", "records"}:
            raise AssertionError(f"a failing command must print an error envelope: {payload}")
    return payload, proc.stderr


def run_wrapper(package_root, *args, expect=0, env=None):
    """Run one package's installed ``scripts/paper_audit.py`` with no repository on the import path."""
    command = [sys.executable, "-I", "-B", str(Path(package_root) / "scripts" / "paper_audit.py"),
               *[str(a) for a in args]]
    clean = dict(env or os.environ)
    clean.pop("PYTHONPATH", None)
    clean["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(command, env=clean, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect} for {args}\n"
                             f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return (json.loads(proc.stdout) if proc.stdout.strip() else None), proc.stderr


# -- the standard two-item fixture ------------------------------------------------------------------
class Fixture:
    """A two-item paper (one lemma used by one theorem) built stage by stage through the public API.

    Stages are cumulative and each one is idempotent for the caller: call ``structure()`` for an
    overview-mode database, ``audit()`` for a registered focused audit, ``primary()`` for primary
    judgments, and ``complete()`` for a database whose process is complete.
    """

    ITEMS = ("items:itm_lem", "items:itm_thm")
    ITEM_REFS = [R("items", "itm_lem"), R("items", "itm_thm")]

    def __init__(self, root, *, title="Test paper", tag="fx"):
        self.root = Path(root)
        self.source_root = self.root / "src"
        self.source_root.mkdir(parents=True, exist_ok=True)
        (self.source_root / "paper.tex").write_text(PAPER_TEX, encoding="utf-8")
        self.path = self.root / "paper.db"
        self.tag = tag
        self._counter = 0
        info = storage.initialize(self.path, source_root=self.source_root, title=title)
        self.paper_id = info["paper_id"]
        self.source_id = None
        self._stages = set()

    # -- plumbing ----------------------------------------------------------------------------------
    def open(self, *, write=True):
        return storage.Database(self.path, write=write)

    def request_id(self) -> str:
        self._counter += 1
        return f"req_{self.tag}_{self._counter}"

    def packet(self, db, *targets, mode="author"):
        refs = [R(*t.split(":", 1)) for t in targets] or [R("papers", self.paper_id)]
        return packets.get_packet(db, targets=refs, mode=mode)

    def batch(self, edits, packet_id) -> dict:
        return {"contract_version": 3, "request_id": self.request_id(), "packet_id": packet_id, "edits": edits}

    def apply(self, db, edits, *targets, mode="author"):
        packet = self.packet(db, *targets, mode=mode)
        return acceptance.apply_batch(db, self.batch(edits, packet["packet_id"]))

    def head_version(self, db, collection, id) -> int:
        return db.head(collection, id).version

    def pin(self, db, collection, id) -> dict:
        return {"collection": collection, "id": id, "version": self.head_version(db, collection, id)}

    def _once(self, name, function):
        if name in self._stages:
            return self
        function()
        self._stages.add(name)
        return self

    # -- stages ------------------------------------------------------------------------------------
    def capture(self):
        def go():
            with self.open() as db:
                result = sources.capture_sources(db, files=["paper.tex"])
                self.source_id = result["sources"][0]["id"]
        return self._once("capture", go)

    def anchors(self):
        self.capture()

        def go():
            with self.open() as db:
                packet = self.packet(db)
                sources.anchor_sources(db, request={
                    "contract_version": 3, "request_id": self.request_id(), "packet_id": packet["packet_id"],
                    "anchors": [
                        {"id": "anc_lem", "expected_version": None, "source_id": self.source_id,
                         "locator": locator(label="lem:a")},
                        {"id": "anc_lem_proof", "expected_version": None, "source_id": self.source_id,
                         "locator": locator(start=8, end=10)},
                        {"id": "anc_thm", "expected_version": None, "source_id": self.source_id,
                         "locator": locator(label="thm:b")},
                        {"id": "anc_thm_proof", "expected_version": None, "source_id": self.source_id,
                         "locator": locator(start=14, end=16)}]})
        return self._once("anchors", go)

    @staticmethod
    def item_edit(iid, kind, label, anchor, proof):
        return edit("create", "items", iid, {
            "kind": kind, "label": label, "caption": label,
            "statement": {"form": "verbatim", "text": label + " text"},
            "passages": [{"role": "statement", "anchor_id": anchor}, {"role": "proof", "anchor_id": proof}],
            "aliases": [], "uncertainty": None, "origin": "source", "owner_id": None, "scope_id": None})

    @staticmethod
    def argument_edit(aid, target, final, anchor):
        return edit("create", "arguments", aid, {
            "target": R("items", target), "label": f"Proof of {target}", "origin": "source",
            "scope_id": "scp_plain", "final_group_id": final, "evidence_refs": [anchor],
            "lifecycle": "registered"})

    @staticmethod
    def group_edit(gid, aid, conclusion, anchor):
        return edit("create", "groups", gid, {
            "argument_id": aid, "conclusion": R("items", conclusion), "kind": "joint", "scope_id": "scp_plain",
            "case_scope_ids": [], "discharges": [], "rationale": "one step", "evidence_refs": [anchor]})

    def structure(self):
        self.anchors()

        def go():
            with self.open() as db:
                self.apply(db, [
                    self.item_edit("itm_lem", "lemma", "Lemma 1", "anc_lem", "anc_lem_proof"),
                    self.item_edit("itm_thm", "theorem", "Theorem 1", "anc_thm", "anc_thm_proof"),
                    edit("create", "scopes", "scp_plain", {"argument_id": None, "parent_id": None, "assumptions": [],
                                                           "binders": [], "conditions": [], "evidence_refs": []}),
                    self.argument_edit("arg_lem", "itm_lem", "grp_lem", "anc_lem_proof"),
                    self.argument_edit("arg_thm", "itm_thm", "grp_thm", "anc_thm_proof"),
                    self.group_edit("grp_lem", "arg_lem", "itm_lem", "anc_lem_proof"),
                    self.group_edit("grp_thm", "arg_thm", "itm_thm", "anc_thm_proof"),
                    edit("create", "uses", "use_lem_thm", {
                        "from": R("items", "itm_lem"), "to": R("items", "itm_thm"), "type": "dependency",
                        "group_id": "grp_thm", "reason": "applied as stated", "needed_form": {"form":"verbatim", "text":"Lemma 1 text"},
                        "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None,
                        "uncertainty": None})])
        return self._once("structure", go)

    def qualification(self, reviewer="checker-A", qid="qua_r1"):
        self.structure()

        def go():
            evidence, case_ok, case_bad = b"calibration transcript", b'{"case":"valid-1"}', b'{"case":"invalid-1"}'
            with self.open() as db:
                review.record_qualification(db, receipt={
                    "contract_version": 3, "request_id": self.request_id(),
                    "edits": [edit("create", "qualifications", qid, {
                        "reviewer": reviewer,
                        "profile": {"provider": "anthropic", "model": "claude-fable-5-1", "effort": "high",
                                    "tools": [], "context_isolation": "fresh session, source only"},
                        "protocol_version": "coherent-proof-audit/1",
                        "valid_case_results": [{"case_id": "valid-1", "response_blob": sha(case_ok), "outcome": "pass"}],
                        "invalid_case_results": [{"case_id": "invalid-1", "response_blob": sha(case_bad),
                                                  "outcome": "pass"}],
                        "evidence_blob": sha(evidence), "qualified": True, "limitations": []})],
                    "blobs": [{"sha256": sha(b), "encoding": "base64", "data": base64.b64encode(b).decode()}
                              for b in (evidence, case_ok, case_bad)]})
        return self._once("qualification", go)

    def audit(self, *, mode="focused", independent_required=True, audit_id="aud_1",
              report_path="reports/audit.html"):
        self.structure()

        def go():
            with self.open() as db:
                # Synthetic model judgments still come from the test. The new
                # contract explicitly records exact targets and full boundaries.
                if db.head('target_specs', 'tgt_lem') is None:
                    packet = self.packet(db, *self.ITEMS, mode='primary')
                    sources.review_sources(db, batch=self.batch([edit('create','source_reviews','srv_boundaries',{
                        'source_refs':[self.pin(db,'sources',self.source_id)],
                        'anchor_refs':[self.pin(db,'anchors',f'anc_{name}_proof') for name in ('lem','thm')],
                        'purpose':'proof_boundary','decision':'accepted',
                        'rationale':'Synthetic fixture identifies complete written proofs.', 'reviewer':'fixture'})],packet['packet_id']))
                    exact_edits=[]
                    for name in ('lem','thm'):
                        exact_edits.extend([
                            edit('create','target_specs',f'tgt_{name}',{
                                'target':R('items',f'itm_{name}'), 'statement_ref':self.pin(db,'items',f'itm_{name}'),
                                'statement':None,'scope_id':None,'evidence_refs':[f'anc_{name}'],
                                'state':'registered','fidelity_ref':None}),
                            edit('create','proof_boundaries',f'bnd_{name}',{
                                'target':R('items',f'itm_{name}'),'argument_ids':[f'arg_{name}'],
                                'anchor_refs':[self.pin(db,'anchors',f'anc_{name}_proof')],
                                'source_review_ref':self.pin(db,'source_reviews','srv_boundaries'),'state':'complete'})])
                    self.apply(db,exact_edits,*self.ITEMS,mode='primary')
                self.apply(db, [edit("create", "audits", audit_id, {
                    "paper_id": self.paper_id, "mode": mode, "targets": list(self.ITEM_REFS), "exclusions": [],
                    "protocol_version": "coherent-proof-audit/1", "independent_required": independent_required,
                    "qualification_id": None, "report_path": report_path,
                    "global_tasks": []})], *self.ITEMS, mode="primary")
            self.audit_id = audit_id
        self.audit_id = audit_id
        return self._once("audit", go)

    @staticmethod
    def check_edit(cid, target, kind, audit_id="aud_1", evidence=(), reviewer="primary-1",
                   outcome="supported", state="complete", role="primary", supersedes=None):
        return edit("create", "checks", cid, {
            "audit_id": audit_id, "target": target, "kind": kind, "role": role, "reviewer": reviewer,
            "protocol_version": "coherent-proof-audit/1", "state": state, "outcome": outcome,
            "reasoning": "checked against the source", "evidence_refs": list(evidence), "conditions": [],
            "next_action": None, "response_id": None, "supersedes": supersedes,
            **({"extent": "whole_unit", "omissions": ""} if kind == "composition" else {})})

    def coverage_edits(self, db):
        return [edit("create", "coverage", f"cov_{name}", {
            "argument_id": f"arg_{name}", "anchor_id": f"anc_{name}_proof",
            "start_offset": 0, "end_offset": len(db.head("anchors", f"anc_{name}_proof").body["excerpt"]),
            "classification": "substantive", "claim_refs": [R("items", f"itm_{name}")],
            "check_ids": [f"chk_der_{name}"], "note": "the captured proof is covered by its derivation"})
                for name in ("lem", "thm")]

    def primary(self):
        self.audit()

        def go():
            with self.open() as db:
                self.apply(db, [
                    *self.coverage_edits(db),
                    self.check_edit("chk_comp_lem", R("arguments", "arg_lem"), "composition",
                                    evidence=["anc_lem_proof"]),
                    self.check_edit("chk_comp_thm", R("arguments", "arg_thm"), "composition",
                                    evidence=["anc_thm_proof"]),
                    self.check_edit("chk_der_lem", R("groups", "grp_lem"), "derivation"),
                    self.check_edit("chk_der_thm", R("groups", "grp_thm"), "derivation"),
                    self.check_edit("chk_app", R("uses", "use_lem_thm"), "application"),
                ], *self.ITEMS, mode="primary")
                packet = self.packet(db, *self.ITEMS, mode="primary")
                review.compare(db, batch=self.batch([
                    edit("create", "observations", oid, {
                        "target": R("items", iid), "result": "matched", "reviewer": "primary-1",
                        "note": "statement matches the source", "evidence_refs": [anchor]})
                    for oid, iid, anchor in (("obs_lem", "itm_lem", "anc_lem"), ("obs_thm", "itm_thm", "anc_thm"))],
                    packet["packet_id"]))
                packet = self.packet(db, *self.ITEMS, mode='primary')
                review.compare(db,batch=self.batch([edit('create','observations',f'obs_exact_{name}',{
                    'target':R('target_specs',f'tgt_{name}'),'result':'matched','reviewer':'primary-1',
                    'note':'The pinned exact text and its applicable setup were examined.',
                    'evidence_refs':[f'anc_{name}'],'context_kind':'exact_target'}) for name in ('lem','thm')],packet['packet_id']))
        return self._once("primary", go)

    def independent_round(self, db, item_id, argument_id, anchor, *, judgment_target=None, reviewer="checker-A"):
        """One blinded independent packet, worker response, and coordinator mapping; returns the check id."""
        packet = packets.get_packet(db, targets=[R("items", item_id)], mode="independent")
        worker = {"packet_id": packet["packet_id"], "covered_targets": [R("items", item_id)],
                  "coverage_note": "read the statement and proof from the source",
                  "exposure_report": {"status": "none_known", "note": ""},
                  "judgments": [{"target": judgment_target or R("arguments", argument_id), "kind": "composition",
                                 "state": "complete", "outcome": "supported",
                                 "reasoning": "independent reading of the proof", "evidence_refs": [anchor],
                                 "conditions": [], "next_action": None, "supersedes": None,
                                 "extent": "whole_unit", "omissions": ""}]}
        submitted = review.submit_review(db, submission={
            "contract_version": 3, "request_id": self.request_id(), "packet_id": packet["packet_id"],
            "reviewer": reviewer, "qualification_id": None, "exposure": "source_only", "exposure_note": ""},
            response_bytes=json.dumps(worker).encode("utf-8"))
        if submitted["state"] == "accepted":
            return submitted["checks"][0]["check_id"], submitted
        mapping_packet = self.packet(db, *self.ITEMS, mode="primary")
        mapped = review.map_response(db, mapping={
            "contract_version": 3, "request_id": self.request_id(), "packet_id": mapping_packet["packet_id"],
            "response_id": submitted["response_id"],
            "entries": [{"judgment_index": 0, "target": R("arguments", argument_id),
                         "rationale": "the proof passage is this argument"}],
            "reviewer": "coord"})
        return mapped["checks"][0]["check_id"], mapped

    def independent(self):
        self.primary()

        def go():
            with self.open() as db:
                self.independent_checks = {
                    "itm_lem": self.independent_round(
                        db, "itm_lem", "arg_lem", "anc_lem_proof",
                        judgment_target={"source_anchor_id": "anc_lem_proof",
                                         "description": "the proof of the lemma"})[0],
                    "itm_thm": self.independent_round(db, "itm_thm", "arg_thm", "anc_thm_proof")[0]}
        return self._once("independent", go)

    def reconciliation_edit(self, db, rid, argument_id, primary_check, independent_check, audit_id="aud_1"):
        return edit("create", "reconciliations", rid, {
            "audit_id": audit_id, "target": R("arguments", argument_id),
            "primary_checks": [self.pin(db, "checks", primary_check)],
            "independent_checks": [self.pin(db, "checks", independent_check)],
            "decision": "agree", "rationale": "adjudicated", "evidence_refs": [], "successor_checks": [],
            "supersedes": None, "adjudicator": "coord"})

    def complete(self):
        self.independent()

        def go():
            with self.open() as db:
                packet = self.packet(db, *self.ITEMS, mode="reconcile")
                review.reconcile(db, batch=self.batch([
                    self.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem",
                                             self.independent_checks["itm_lem"]),
                    self.reconciliation_edit(db, "rec_thm", "arg_thm", "chk_comp_thm",
                                             self.independent_checks["itm_thm"])], packet["packet_id"]))
        return self._once("complete", go)


class TempCase(unittest.TestCase):
    """A test case with its own temporary directory, cleaned even when release artifacts are read-only."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="paper_core_test_"))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if self.work.exists():
            rmtree_force(self.work)

    def path(self, *parts) -> Path:
        target = self.work.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def fixture(self, name="paper", **kwargs) -> Fixture:
        root = self.work / name
        root.mkdir(parents=True, exist_ok=True)
        return Fixture(root, **kwargs)

    def legacy_audit_copy(self, name="legacy_audit") -> Path:
        target = self.work / name
        shutil.copytree(REFERENCE_AUDIT, target)
        return target


__all__ = ["CLI_ENV", "CORE", "Fixture", "GLOBAL_TASKS", "HANDOFF", "OVERVIEW", "OVERVIEW_EXAMPLE",
           "PAPER_TEX", "PROOFCHECK", "R", "REFERENCE_AUDIT", "REPO", "SHARED", "TOOLS", "TempCase", "edit",
           "locator", "node_available", "rmtree_force", "run_cli", "run_wrapper", "sha", "write_json"]
