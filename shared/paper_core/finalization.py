"""Freeze one assessed revision for delivery without repeating scientific work."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import CORE_VERSION, PROJECTION_VERSION, PROTOCOL_VERSION
from .assessment import derive_full
from .bundle import PACKAGE_DIR, bundle_files, content_identity
from .canonical import digest, sha256_bytes
from .errors import InvalidRequest
from .export_import import export_snapshot
from .paths import resolve_path
from .projection import project, public_assessment
from .queries import validate_snapshot
from .staging import staging_directory
from .storage import now_iso

FINALIZATION_VERSION = 1
SNAPSHOT_NAME = "report-snapshot.json"
RECEIPT_NAME = "finalization.json"
SUMMARY_NAME = "summary.json"
EXPORT_NAME = "export.json"
DIAGNOSTIC_NAME = "finalization-diagnostics.json"
SUMMARY_LIMIT = 100


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def producer_identity():
    return {"core_version": CORE_VERSION, "projection_version": PROJECTION_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "bundle_source_identity": content_identity(bundle_files(PACKAGE_DIR))}


def protected_destination(output, protected_paths, *, what="report output"):
    destination = resolve_path(output)
    for value in protected_paths:
        path = resolve_path(value)
        if destination == path or (destination.exists() and path.exists() and destination.samefile(path)):
            raise InvalidRequest(f"{what} collides with the database, registered evidence or frozen input: {destination}",
                                 code="OUTPUT_CONFLICT")
    if destination.is_dir():
        raise InvalidRequest(f"{what} is a directory: {destination}", code="OUTPUT_CONFLICT")
    return destination


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise InvalidRequest(f"cannot read frozen input {path}: {exc}", code="FINALIZATION_INVALID") from exc
    if not isinstance(value, dict):
        raise InvalidRequest(f"frozen input {path} must be an object", code="FINALIZATION_INVALID")
    return value


def validate_finalization(snapshot, receipt):
    """Check saved identities and completion labels, never reassess mathematics."""
    errors = []
    if snapshot.get("snapshot_version") != FINALIZATION_VERSION or receipt.get("finalization_version") != FINALIZATION_VERSION:
        errors.append("unsupported frozen version")
    revision = snapshot.get("revision")
    if type(revision) is not int or revision < 1:
        errors.append("revision must be a positive integer")
    for field in ("revision", "audit_id", "paper_id", "kind", "scope", "source_identity", "producer",
                  "process_complete", "representation_settled", "finalization_blockers", "finalization_blocker_count"):
        if field not in snapshot or snapshot.get(field) != receipt.get(field):
            errors.append(f"receipt and snapshot disagree on {field}")
    projection = snapshot.get("projection", {})
    if not isinstance(projection, dict):
        projection = {}
        errors.append("projection must be an object")
    for field in ("nodes", "connections", "records", "obligations", "record_locations"):
        if not isinstance(projection.get(field), list):
            errors.append(f"projection {field} must be a list")
    for field in ("details", "layout", "summary"):
        if not isinstance(projection.get(field), dict):
            errors.append(f"projection {field} must be an object")
    summary = projection.get("summary") if isinstance(projection.get("summary"), dict) else {}
    progress = summary.get("progress") if isinstance(summary.get("progress"), dict) else {}
    if (projection.get("snapshot_revision"), projection.get("audit_id"), projection.get("projection_version")) != (
            snapshot.get("revision"), snapshot.get("audit_id"), PROJECTION_VERSION):
        errors.append("projection identity differs from its frozen revision")
    if snapshot.get("scope") != summary.get("scope") or snapshot.get("process_complete") is not progress.get("process_complete"):
        errors.append("projection scope or completion differs from its frozen summary")
    factual = summary.get("factual") if isinstance(summary.get("factual"), dict) else {}
    if (factual.get("revision"), factual.get("audit_id"), factual.get("process_complete")) != (
            revision, snapshot.get("audit_id"), snapshot.get("process_complete")):
        errors.append("factual summary describes another revision")
    scope = snapshot.get("scope")
    if not isinstance(scope, dict) or scope.get("mode") not in ("full", "focused", "triage"):
        errors.append("declared scope is invalid")
    paper = snapshot.get("paper") or {}
    if not isinstance(paper, dict) or paper.get("id") != snapshot.get("paper_id") or not isinstance(paper.get("title"), str):
        errors.append("pinned paper identity is invalid")
        paper = {}
    audits = []
    for row in projection.get("records", []) if isinstance(projection.get("records"), list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("ref"), dict) or not isinstance(row.get("body"), dict):
            errors.append("projection records need reference and body objects")
            continue
        ref, body = row["ref"], row["body"]
        if ref.get("collection") == "papers" and (ref.get("id"), body.get("title")) != (snapshot.get("paper_id"), paper.get("title")):
            errors.append("projection paper differs from the frozen paper")
        if ref.get("collection") == "audits" and ref.get("id") == snapshot.get("audit_id"):
            audits.append(body)
    if len(audits) != 1 or audits[0].get("protocol_version") != PROTOCOL_VERSION:
        errors.append("projection must identify one audit with the current scientific protocol")
    elif {"mode": audits[0].get("mode"), "target_refs": audits[0].get("targets"),
          "exclusions": audits[0].get("exclusions")} != scope:
        errors.append("projection audit differs from the declared scope")
    for field in ("process_complete", "representation_settled"):
        if type(snapshot.get(field)) is not bool:
            errors.append(f"{field} must be boolean")
    blockers = snapshot.get("finalization_blockers")
    if not isinstance(blockers, list) or not all(isinstance(b, dict) and isinstance(b.get("message"), str) for b in blockers):
        errors.append("limitations must be structured messages")
        blockers = []
    count = snapshot.get("finalization_blocker_count")
    if type(count) is not int or count < len(blockers):
        errors.append("limitation count is inconsistent")
    if snapshot.get("kind") not in ("working", "release"):
        errors.append("kind must be working or release")
    if snapshot.get("kind") == "release" and (snapshot.get("process_complete") is not True
            or snapshot.get("representation_settled") is not True or blockers or count != 0):
        errors.append("release must have its promised work and source representation complete")
    protected = snapshot.get("protected_paths")
    if not isinstance(protected, list) or not all(isinstance(p, str) for p in protected):
        errors.append("protected paths must be a list")
        protected = []
    if snapshot.get("database_path") not in protected:
        errors.append("database path must be protected")
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not all(isinstance(s, dict) and isinstance(s.get("ref"), dict)
            and isinstance(s.get("body"), dict) and isinstance(s["ref"].get("id"), str)
            and type(s["ref"].get("version")) is int and isinstance(s["body"].get("blob_sha256"), str)
            and s["body"].get("paper_id") == snapshot.get("paper_id") for s in sources):
        errors.append("captured source provenance is invalid")
    elif snapshot.get("source_identity") != digest(sorted([s["ref"]["id"], s["ref"]["version"], s["body"]["blob_sha256"]] for s in sources)):
        errors.append("source identity differs from the captured provenance")
    originals = snapshot.get("source_originals")
    if not isinstance(originals, list) or not all(isinstance(s, dict) and isinstance(s.get("path"), str)
            and s["path"] in protected for s in originals):
        errors.append("original evidence paths must be protected")
    producer = snapshot.get("producer") or {}
    if not isinstance(producer, dict) or producer.get("protocol_version") != PROTOCOL_VERSION or producer.get("projection_version") != PROJECTION_VERSION:
        errors.append("scientific producer identity is invalid")
    status = snapshot.get("status") or {}
    if not isinstance(status, dict) or status.get("progress") != progress:
        errors.append("saved status describes another progress assessment")
    validation = receipt.get("validation")
    if receipt.get("analysis_complete") is not True or not isinstance(validation, dict) or validation.get("ok") is not True:
        errors.append("frozen input requires complete analysis and valid structure")
    if errors:
        raise InvalidRequest("frozen input is inconsistent", code="FINALIZATION_INVALID", records=errors)


def load_finalization(directory):
    """Read a frozen bundle without opening, fetching or updating a scientific store."""
    directory = resolve_path(directory)
    receipt = _read_json(directory / RECEIPT_NAME)
    if receipt.get("snapshot_file") != SNAPSHOT_NAME:
        raise InvalidRequest("unexpected frozen snapshot name", code="FINALIZATION_INVALID")
    snapshot = _read_json(directory / SNAPSHOT_NAME)
    if receipt.get("snapshot_sha256") != sha256_bytes((directory / SNAPSHOT_NAME).read_bytes()):
        raise InvalidRequest("frozen snapshot hash does not match", code="FINALIZATION_INVALID")
    validate_finalization(snapshot, receipt)
    summary = _read_json(directory / SUMMARY_NAME)
    if receipt.get("summary_sha256") != sha256_bytes((directory / SUMMARY_NAME).read_bytes()) or summary != {
            "revision": snapshot["revision"], "audit_id": snapshot["audit_id"], "kind": snapshot["kind"],
            "summary": snapshot["projection"]["summary"], "status": snapshot["status"]}:
        raise InvalidRequest("frozen summary differs from its assessed snapshot", code="FINALIZATION_INVALID")
    if receipt.get("export") is not None:
        exported = receipt["export"]
        if not isinstance(exported, dict) or exported.get("file") != EXPORT_NAME:
            raise InvalidRequest("unexpected frozen export name", code="FINALIZATION_INVALID")
        data = _read_json(directory / EXPORT_NAME)
        if exported.get("sha256") != sha256_bytes((directory / EXPORT_NAME).read_bytes()) or (
                data.get("revision"), data.get("paper_id")) != (snapshot["revision"], snapshot["paper_id"]):
            raise InvalidRequest("frozen export differs from its snapshot", code="FINALIZATION_INVALID")
    return snapshot, receipt


def _result(directory, snapshot, receipt, *, reused=False):
    return {**receipt, "directory": str(directory), "snapshot_path": str(directory / SNAPSHOT_NAME),
            "finalization_path": str(directory / RECEIPT_NAME), "summary_path": str(directory / SUMMARY_NAME),
            "status": snapshot["status"], "reused": reused}


def finalize_audit(db, *, audit_id, output, partial=False, include_export=False):
    """Freeze valid limited work as working output, or performed work as release output."""
    if db.conn.in_transaction:
        raise InvalidRequest("freeze requires a connection without an active transaction")
    directory = resolve_path(output)
    if directory.exists() and not directory.is_dir():
        raise InvalidRequest("freeze output must be a directory")
    revision = None
    protected = [str(db.path.resolve())]
    db.conn.execute("BEGIN")
    try:
        revision = db.max_revision()
        if directory.exists() and any(directory.iterdir()):
            snapshot, receipt = load_finalization(directory)
            if (snapshot["revision"], snapshot["audit_id"], snapshot["database_path"], bool(receipt.get("export"))) != (
                    revision, audit_id, str(db.path.resolve()), bool(include_export)) or (partial and snapshot["kind"] != "working"):
                raise InvalidRequest("freeze destination contains a different request; choose a new directory",
                                     code="FINALIZATION_CONFLICT")
            return _result(directory, snapshot, receipt, reused=True)
        validation = validate_snapshot(db, revision=revision, check_projection=False)
        if not validation["ok"]:
            raise InvalidRequest("cannot freeze invalid saved records", code="FINALIZATION_INVALID", records=validation["errors"])
        derived = derive_full(db, revision=revision, audit_id=audit_id)
        derivation, assessment = derived
        if assessment.get("analysis_complete") is not True:
            raise InvalidRequest("cannot freeze incomplete scientific analysis", code="ANALYSIS_INCOMPLETE")
        if derivation.audit is None or derivation.audit.body["protocol_version"] != PROTOCOL_VERSION:
            raise InvalidRequest("freeze requires a current-protocol audit", code="PROTOCOL_UNSUPPORTED")
        projection, report = project(db, revision=revision, audit_id=audit_id, derived=derived)
        papers = derivation.snap.all("papers")
        if len(papers) != 1:
            raise InvalidRequest("freeze requires one saved paper", code="FINALIZATION_INVALID")
        paper = papers[0]
        sources = derivation.snap.all("sources")
        originals = []
        for source in sources:
            path = Path(source.body["path"])
            original = str((path if path.is_absolute() else Path(paper.body["source_root"]) / path).resolve())
            originals.append({"ref": source.pinned, "path": original, "label": source.body["path"]})
            protected.append(original)
        for name in (SNAPSHOT_NAME, RECEIPT_NAME, SUMMARY_NAME, EXPORT_NAME, DIAGNOSTIC_NAME):
            protected_destination(directory / name, protected, what="freeze output")
        pending = [o for o in assessment["obligations"] if o["required"] and not o["satisfied"]]
        blockers = [{"code": "required_work", "task_id": o["id"], "target_ref": o["target"],
                     "message": f"Required {o['role']} {o['kind'].replace('_', ' ')} work is unfinished."} for o in pending]
        blockers += [{"code": "source_limit", "target_ref": ref, "message": "Required source evidence remains limited."}
                     for ref in assessment["source_limits"]]
        blockers += [{"code": "assessment_problem", "message": str(p)} for p in assessment["problems"]]
        # Gaps, inconclusive conclusions and integrated scientific disagreement are findings,
        # so there is no outcome-based delivery blocker here.
        factual_limits = projection["summary"]["factual"].get("source_limits", [])
        blockers += [{"code": "source_limit", "message": row["description"], "target_ref": row["ref"]}
                     for row in factual_limits if row["ref"] not in assessment["source_limits"]]
        representation_settled = not any(o["kind"] == "source_fidelity" for o in pending)
        representation_settled = representation_settled and not factual_limits and not assessment["source_limits"]
        if assessment["mode"] == "triage":
            blockers.append({"code": "triage_scope", "message": "Triage does not promise a completed proof audit."})
        complete = assessment["progress"]["process_complete"]
        kind = "release" if complete and representation_settled and not blockers and not partial else "working"
        snapshot = {"snapshot_version": FINALIZATION_VERSION, "revision": revision, "audit_id": audit_id,
            "paper_id": paper.id, "paper": {"id": paper.id, "ref": paper.pinned, "title": paper.body["title"]},
            "scope": projection["summary"]["scope"], "source_identity": assessment["context"]["source_context_digest"],
            "sources": [{"ref": s.pinned, "body": s.body} for s in sources], "source_originals": originals,
            "database_path": str(db.path.resolve()), "protected_paths": sorted(set(protected)),
            "kind": kind, "process_complete": complete, "representation_settled": representation_settled,
            "finalization_blockers": blockers[:SUMMARY_LIMIT], "finalization_blocker_count": len(blockers),
            "producer": producer_identity(), "projection": projection,
            "status": {"progress": assessment["progress"], "independent": assessment["independent"],
                       "findings": assessment["findings"], "assessments": {
                           k: public_assessment(v) for k, v in sorted(assessment["assessments"].items())}}}
        summary = {"revision": revision, "audit_id": audit_id, "kind": kind,
                   "summary": projection["summary"], "status": snapshot["status"]}
        receipt = {k: snapshot[k] for k in ("revision", "audit_id", "paper_id", "kind", "scope", "source_identity",
            "process_complete", "representation_settled", "finalization_blockers", "finalization_blocker_count", "producer")}
        receipt.update(finalization_version=FINALIZATION_VERSION, snapshot_file=SNAPSHOT_NAME,
            snapshot_sha256=sha256_bytes(_json_bytes(snapshot)), summary_sha256=sha256_bytes(_json_bytes(summary)),
            created_at=now_iso(), analysis_complete=True,
            validation={"ok": True, "warnings": validation["warnings"], "projection_problems": report["problems"]})
        exported = export_snapshot(db, revision=revision, history=True) if include_export else None
        if exported is not None:
            receipt["export"] = {"file": EXPORT_NAME, "sha256": sha256_bytes(_json_bytes(exported))}
        validate_finalization(snapshot, receipt)
    finally:
        db.rollback()
    directory.parent.mkdir(parents=True, exist_ok=True)
    with staging_directory(directory.parent, ".paper-freeze-") as staged:
        (staged / SNAPSHOT_NAME).write_bytes(_json_bytes(snapshot))
        (staged / RECEIPT_NAME).write_bytes(_json_bytes(receipt))
        (staged / SUMMARY_NAME).write_bytes(_json_bytes(summary))
        if exported is not None:
            (staged / EXPORT_NAME).write_bytes(_json_bytes(exported))
        load_finalization(staged)
        if directory.exists():
            directory.rmdir()
        os.replace(staged, directory)
    return _result(directory, snapshot, receipt)


__all__ = ["FINALIZATION_VERSION", "SNAPSHOT_NAME", "RECEIPT_NAME", "SUMMARY_NAME", "EXPORT_NAME",
           "finalize_audit", "load_finalization", "validate_finalization", "protected_destination", "producer_identity"]
