"""Freeze a consistent scientific snapshot before attempting report delivery.

These files are derived presentation inputs. The audit database and authored
responses remain the scientific and continuation records.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from . import CORE_VERSION, PROJECTION_VERSION
from .assessment import derive_full
from .bundle import PACKAGE_DIR, bundle_files, content_identity, load_manifest
from .canonical import compact_json, digest, sha256_bytes
from .errors import CoreError, InvalidRequest
from .export_import import export_snapshot
from .projection import project, public_assessment
from .queries import validate_snapshot
from .storage import Database, now_iso

FINALIZATION_VERSION = 1
SNAPSHOT_NAME = "report-snapshot.json"
RECEIPT_NAME = "finalization.json"
EXPORT_NAME = "export.json"
DIAGNOSTIC_NAME = "finalization-diagnostics.json"
SUMMARY_LIMIT = 100


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def producer_identity() -> dict:
    manifest = load_manifest()
    identity = manifest.get("source_identity") if manifest else content_identity(bundle_files(PACKAGE_DIR))
    return {"core_version": CORE_VERSION, "bundle_source_identity": identity,
            "projection_version": PROJECTION_VERSION}


def protected_destination(output, protected_paths, *, what="report output") -> Path:
    """Reject path aliases, including existing hard links, before any output writes."""
    destination = Path(output).resolve()
    for value in protected_paths:
        path = Path(value).resolve()
        same = destination == path
        if not same and destination.exists() and path.exists():
            same = destination.samefile(path)
        if same:
            raise InvalidRequest(f"{what} collides with the database, a registered source, or frozen input: {destination}")
    if destination.exists() and destination.is_dir():
        raise InvalidRequest(f"output path is a directory: {destination}")
    return destination


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise InvalidRequest(f"cannot read frozen finalization {path}: {exc}", code="FINALIZATION_INVALID") from exc
    if not isinstance(value, dict):
        raise InvalidRequest(f"frozen finalization {path} must contain an object", code="FINALIZATION_INVALID")
    return value


def validate_finalization(snapshot: dict, receipt: dict) -> None:
    """Validate producer cross-fields as well as hashes checked by the loader."""
    failures = []
    if snapshot.get("snapshot_version") != FINALIZATION_VERSION or receipt.get("finalization_version") != FINALIZATION_VERSION:
        failures.append("unsupported frozen finalization version")
    revision = snapshot.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        failures.append("snapshot revision must be a positive integer")
    if not all(isinstance(snapshot.get(field), str) and snapshot[field] for field in ("paper_id", "audit_id", "source_identity")):
        failures.append("snapshot identities must be nonempty strings")
    scope = snapshot.get("scope")
    if not isinstance(scope, dict) or scope.get("mode") not in ("full", "focused", "triage") or \
            not isinstance(scope.get("target_refs"), list) or not isinstance(scope.get("exclusions"), list):
        failures.append("snapshot declared scope is invalid")
    projection = snapshot.get("projection")
    if not isinstance(projection, dict):
        failures.append("snapshot projection must be an object")
        projection = {}
    for field in ("nodes", "connections", "records", "obligations", "record_locations"):
        if not isinstance(projection.get(field), list):
            failures.append(f"projection {field} must be a list")
    for field in ("details", "layout"):
        if not isinstance(projection.get(field), dict):
            failures.append(f"projection {field} must be an object")
    summary = projection.get("summary")
    if not isinstance(summary, dict):
        failures.append("projection summary must be an object")
        summary = {}
    progress = summary.get("progress")
    if not isinstance(progress, dict):
        failures.append("projection progress must be an object")
        progress = {}
    fields = ("revision", "audit_id", "paper_id", "kind", "process_complete", "representation_settled",
              "finalization_blockers", "finalization_blocker_count", "scope", "source_identity", "producer")
    for field in fields:
        if field not in snapshot or field not in receipt or compact_json(snapshot.get(field)) != compact_json(receipt.get(field)):
            failures.append(f"receipt and snapshot disagree on {field}")
    if snapshot.get("revision") != projection.get("snapshot_revision"):
        failures.append("snapshot and projection revisions disagree")
    if snapshot.get("audit_id") != projection.get("audit_id"):
        failures.append("snapshot and projection audit identities disagree")
    if snapshot.get("scope") != summary.get("scope"):
        failures.append("snapshot and projection scopes disagree")
    if snapshot.get("process_complete") is not progress.get("process_complete"):
        failures.append("snapshot and projection canonical completion disagree")
    factual = summary.get("factual")
    if isinstance(factual, dict) and (factual.get("revision") != snapshot.get("revision") or
                                     factual.get("audit_id") != snapshot.get("audit_id") or
                                     factual.get("process_complete") is not snapshot.get("process_complete")):
        failures.append("factual summary describes a different revision or completion value")
    paper = snapshot.get("paper")
    if not isinstance(paper, dict) or paper.get("id") != snapshot.get("paper_id") or not isinstance(paper.get("title"), str):
        failures.append("snapshot paper identity or pinned title is invalid")
        paper = {}
    else:
        ref = paper.get("ref", {})
        if not isinstance(ref, dict) or ref.get("collection") != "papers" or ref.get("id") != snapshot.get("paper_id"):
            failures.append("pinned paper identity differs from snapshot paper")
    selected_audits = 0
    for entry in projection.get("records", []) if isinstance(projection.get("records"), list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("ref"), dict) or not isinstance(entry.get("body"), dict):
            failures.append("projection records must contain reference and body objects")
            continue
        ref, body = entry["ref"], entry["body"]
        if ref.get("collection") == "audits" and ref.get("id") == snapshot.get("audit_id"):
            selected_audits += 1
        if ref.get("collection") == "papers" and (ref.get("id") != snapshot.get("paper_id") or
                                                  body.get("title") != (paper or {}).get("title")):
            failures.append("projection paper identity or title differs from snapshot paper")
        if ref.get("collection") == "audits" and ref.get("id") == snapshot.get("audit_id") and \
                (body.get("paper_id") != snapshot.get("paper_id") or
                 {"mode": body.get("mode"), "target_refs": body.get("targets"), "exclusions": body.get("exclusions")} != snapshot.get("scope")):
            failures.append("selected projection audit differs from snapshot identity or scope")
        if ref.get("collection") == "sources" and body.get("paper_id") != snapshot.get("paper_id"):
            failures.append("projection source paper identity differs from snapshot paper")
    if selected_audits != 1:
        failures.append("projection must identify its selected audit once")
    for field in ("process_complete", "representation_settled"):
        if not isinstance(snapshot.get(field), bool):
            failures.append(f"{field} must be a boolean")
    blockers = snapshot.get("finalization_blockers")
    if not isinstance(blockers, list) or not all(isinstance(row, dict) and isinstance(row.get("message"), str) for row in blockers):
        failures.append("finalization blockers must be structured messages")
        blockers = []
    count = snapshot.get("finalization_blocker_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < len(blockers):
        failures.append("finalization blocker count must include every displayed blocker")
    if snapshot.get("representation_settled") is False and not any(row.get("code") == "source_representation_unsettled" for row in blockers):
        failures.append("unsettled representation must retain its source comparison blocker")
    if not isinstance(snapshot.get("protected_paths"), list) or not all(isinstance(p, str) for p in snapshot.get("protected_paths", [])):
        failures.append("protected paths must be a list of paths")
    database_path = snapshot.get("database_path")
    protected = snapshot.get("protected_paths") if isinstance(snapshot.get("protected_paths"), list) else []
    if not isinstance(database_path, str) or database_path not in protected:
        failures.append("the frozen database path must be protected")
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not all(isinstance(row, dict) and isinstance(row.get("ref"), dict)
            and isinstance(row.get("body"), dict) and isinstance(row["ref"].get("id"), str)
            and isinstance(row["ref"].get("version"), int) and isinstance(row["body"].get("blob_sha256"), str)
            and row["body"].get("paper_id") == snapshot.get("paper_id") for row in sources):
        failures.append("frozen sources must retain their identities and captured provenance")
    elif digest(sorted([row["ref"]["id"], row["ref"]["version"], row["body"]["blob_sha256"]] for row in sources)) != snapshot.get("source_identity"):
        failures.append("frozen source identity disagrees with captured source provenance")
    originals = snapshot.get("source_originals")
    if not isinstance(originals, list) or not all(isinstance(row, dict) and isinstance(row.get("ref"), dict)
            and isinstance(row.get("label"), str) and isinstance(row.get("path"), str) and row["path"] in protected for row in originals):
        failures.append("original source paths must be identified and protected")
    status = snapshot.get("status")
    if not isinstance(status, dict) or status.get("progress") != progress or not all(isinstance(status.get(field), dict)
            for field in ("assessments", "independent", "findings")):
        failures.append("frozen status must describe the projection's canonical progress")
    if snapshot.get("kind") not in ("working", "release"):
        failures.append("output kind must be working or release")
    if snapshot.get("kind") == "release" and (snapshot.get("process_complete") is not True or
                                                snapshot.get("representation_settled") is not True or blockers or count != 0):
        failures.append("release requires canonical completion and settled source representation without finalization blockers")
    validation = receipt.get("validation")
    if receipt.get("analysis_complete") is not True or not isinstance(validation, dict) or validation.get("ok") is not True:
        failures.append("snapshot requires complete analysis and valid structure")
    producer = snapshot.get("producer")
    if not isinstance(producer, dict) or producer.get("projection_version") != PROJECTION_VERSION or not isinstance(producer.get("core_version"), str) or not isinstance(producer.get("bundle_source_identity"), str):
        failures.append("frozen producer identity is invalid")
    if projection.get("projection_version") != PROJECTION_VERSION:
        failures.append("unsupported projection version")
    if failures:
        raise InvalidRequest("frozen finalization is inconsistent", code="FINALIZATION_INVALID", records=failures)


def load_finalization(directory) -> tuple:
    """Return validated ``(snapshot, receipt)`` without opening an audit database."""
    directory = Path(directory).resolve()
    receipt = _read_json(directory / RECEIPT_NAME)
    if receipt.get("snapshot_file") != SNAPSHOT_NAME:
        raise InvalidRequest("finalization receipt names an unexpected snapshot file", code="FINALIZATION_INVALID")
    snapshot_path = directory / SNAPSHOT_NAME
    snapshot = _read_json(snapshot_path)
    if receipt.get("snapshot_sha256") != sha256_bytes(snapshot_path.read_bytes()):
        raise InvalidRequest("frozen report snapshot hash does not match its receipt", code="FINALIZATION_INVALID")
    validate_finalization(snapshot, receipt)
    exported = receipt.get("export")
    if exported is not None:
        if not isinstance(exported, dict) or exported.get("file") != EXPORT_NAME:
            raise InvalidRequest("finalization receipt names an unexpected export", code="FINALIZATION_INVALID")
        export_path = directory / EXPORT_NAME
        data = _read_json(export_path)
        if exported.get("sha256") != sha256_bytes(export_path.read_bytes()) or data.get("revision") != snapshot["revision"] or data.get("paper_id") != snapshot["paper_id"]:
            raise InvalidRequest("frozen export hash, revision, or paper differs from its snapshot", code="FINALIZATION_INVALID")
    return snapshot, receipt


def _result(directory: Path, snapshot: dict, receipt: dict, *, reused=False) -> dict:
    result = {**receipt, "directory": str(directory), "snapshot_path": str(directory / SNAPSHOT_NAME),
              "finalization_path": str(directory / RECEIPT_NAME), "reused": reused,
              "status": snapshot["status"]}
    if receipt.get("export") is not None:
        result["export_path"] = str(directory / EXPORT_NAME)
    return result


def _diagnostic(directory: Path, error: CoreError, *, audit_id, revision, protected):
    # A valid or unrelated existing bundle is never replaced by a failed analysis.
    if directory.exists() and any(directory.iterdir()):
        return
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / DIAGNOSTIC_NAME
    protected_destination(path, protected, what="finalization diagnostic")
    path.write_bytes(_json_bytes({"audit_id": audit_id, "revision": revision, "snapshot_created": False,
                                 "error": error.to_json()["error"], "created_at": now_iso()}))
    error.records.append({"diagnostic_path": str(path), "snapshot_created": False})


def finalize_audit(db: Database, *, audit_id: str, output, partial=False, include_export=False,
                   release_output=None) -> dict:
    """Freeze one current read transaction, ending it before any publication writes.

    Existing valid bundles for the same audit/revision/kind are returned unchanged;
    publication metadata and timestamps do not participate in this comparison.
    ``include_export`` and ``release_output`` support the legacy release recovery.
    """
    from .stages import representation_readiness

    directory = Path(output).resolve()
    if directory.exists() and not directory.is_dir():
        raise InvalidRequest(f"finalization output {directory} is not a directory")
    if db.conn.in_transaction:
        raise InvalidRequest("finalization requires a connection without an active transaction")
    kind = "working" if partial else "release"
    revision = None
    protected = [str(db.path.resolve())]
    db.conn.execute("BEGIN")
    try:
        revision = db.max_revision()
        papers_at_revision = db.records_at(revision, "papers")
        if len(papers_at_revision) == 1:
            root_value = papers_at_revision[0].body.get("source_root")
            if isinstance(root_value, str):
                source_root = Path(root_value)
                for source in db.records_at(revision, "sources"):
                    value = source.body.get("path")
                    if isinstance(value, str):
                        path = Path(value)
                        protected.append(str((path if path.is_absolute() else source_root / path).resolve()))
        for name in (SNAPSHOT_NAME, RECEIPT_NAME, EXPORT_NAME, DIAGNOSTIC_NAME):
            protected_destination(directory / name, protected, what="finalization output")
        if directory.exists() and any(directory.iterdir()):
            snapshot, receipt = load_finalization(directory)
            expected_output = None if release_output is None else str(Path(release_output).resolve())
            if (snapshot["revision"], snapshot["audit_id"], snapshot["kind"]) != (revision, audit_id, kind) or \
                    bool(receipt.get("export")) != bool(include_export) or snapshot.get("release_output") != expected_output or \
                    snapshot.get("database_path") != str(db.path.resolve()):
                raise InvalidRequest("finalization destination contains a different frozen request; choose a new directory",
                                     code="FINALIZATION_CONFLICT")
            return _result(directory, snapshot, receipt, reused=True)
        validation = validate_snapshot(db, revision=revision, check_projection=False)
        if not validation["ok"]:
            raise InvalidRequest("finalization refused: the snapshot fails validation", code="RELEASE_BLOCKED",
                                 records=validation["errors"])
        try:
            derived = derive_full(db, revision=revision, audit_id=audit_id)
        except CoreError:
            raise
        except Exception as exc:
            raise InvalidRequest(f"finalization analysis failed: {type(exc).__name__}: {exc}",
                                 code="ANALYSIS_FAILED") from exc
        derivation, assessment = derived
        if assessment.get("analysis_complete") is not True:
            raise InvalidRequest("finalization requires successful complete analysis", code="ANALYSIS_INCOMPLETE")
        representation = representation_readiness(derivation, assessment)
        if representation["representation_settled"] is None:
            raise InvalidRequest("finalization source representation analysis is incomplete", code="ANALYSIS_INCOMPLETE")
        blockers = list(representation["blockers"])
        blocker_count = representation["blocker_count"]
        pending = [o for o in assessment["obligations"] if o["required"] and not o["satisfied"]]
        extra = [{"code": "required_examination", "task_id": row["id"], "target_ref": row["target"],
                  "message": f"Required {row['role']} {row['kind'].replace('_', ' ')} examination is unfinished."} for row in pending]
        extra += [{"code": "assessment_problem", "message": str(p)} for p in assessment["problems"]]
        extra += [{"code": "source_limit", "target_ref": ref, "message": "A required source has an unresolved limitation."}
                  for ref in assessment["source_limits"]]
        extra += [{"code": "review_disagreement", "target_ref": {"collection": key.split(':')[0], "id": key.split(':')[1]},
                   "message": "Independent review remains disputed."}
                  for key, indicator in assessment["independent"].items() if indicator == "disputed"]
        if assessment["mode"] == "triage":
            extra.append({"code": "triage_scope", "message": "Triage records can produce only a working report."})
        blocker_count += len(extra)
        blockers = (blockers + extra)[:SUMMARY_LIMIT]
        complete = assessment["progress"]["process_complete"]
        if not partial and (not complete or not representation["representation_settled"]):
            raise InvalidRequest(f"finalization refused: audit {audit_id} is not eligible for completed delivery at revision {revision}",
                                 code="RELEASE_BLOCKED", records=blockers,
                                 retry={"command": "stage2 finalize", "required_options": ["--partial"],
                                        "instruction": "Finish the identified required work, or preserve an explicitly working snapshot."})
        try:
            projection, report = project(db, revision=revision, audit_id=audit_id, derived=derived)
        except CoreError:
            raise
        except Exception as exc:
            raise InvalidRequest(f"finalization projection failed: {type(exc).__name__}: {exc}",
                                 code="ANALYSIS_FAILED") from exc
        work = projection["worklist"]
        papers = derivation.snap.all("papers")
        if len(papers) != 1:
            raise InvalidRequest("finalization requires one pinned paper record", code="FINALIZATION_INVALID")
        paper = papers[0]
        sources = derivation.snap.all("sources")
        root = Path(paper.body["source_root"])
        source_originals = []
        for source in sources:
            path = Path(source.body["path"])
            original = str((path if path.is_absolute() else root / path).resolve())
            source_originals.append({"ref": source.pinned, "path": original, "label": source.body["path"]})
        producer = producer_identity()
        snapshot = {"snapshot_version": FINALIZATION_VERSION, "revision": revision, "audit_id": audit_id,
                    "paper_id": paper.id, "paper": {"id": paper.id, "ref": paper.pinned, "title": paper.body["title"]},
                    "scope": projection["summary"]["scope"], "source_identity": assessment["context"]["source_context_digest"],
                    "sources": [{"ref": source.pinned, "body": source.body} for source in sources],
                    "source_originals": source_originals,
                    "database_path": str(db.path.resolve()), "protected_paths": sorted(set(protected)),
                    "release_output": None if release_output is None else str(Path(release_output).resolve()),
                    "kind": kind, "process_complete": complete,
                    "representation_settled": representation["representation_settled"],
                    "finalization_blockers": blockers, "finalization_blocker_count": blocker_count,
                    "producer": producer, "projection": projection,
                    "status": {"progress": assessment["progress"],
                               "assessments": {key: public_assessment(value) for key, value in sorted(assessment["assessments"].items())},
                               "independent": assessment["independent"], "findings": assessment["findings"]}}
        remaining = [task for task in work["tasks"] if task["required"] and task["state"] != "satisfied"]
        receipt = {key: snapshot[key] for key in ("revision", "audit_id", "paper_id", "scope", "source_identity", "kind",
                   "process_complete", "representation_settled", "finalization_blockers", "finalization_blocker_count", "producer")}
        receipt.update({"finalization_version": FINALIZATION_VERSION, "snapshot_file": SNAPSHOT_NAME,
                        "snapshot_sha256": sha256_bytes(_json_bytes(snapshot)), "created_at": now_iso(),
                        "analysis_complete": True, "validation": {"ok": True, "warnings": validation["warnings"],
                                                                    "projection_problems": report["problems"]},
                        "remaining_work": {"count": len(remaining), "truncated": len(remaining) > SUMMARY_LIMIT,
                                           "tasks": [{key: task[key] for key in ("id", "target", "kind", "role", "state")}
                                                     for task in remaining[:SUMMARY_LIMIT]]}})
        exported = export_snapshot(db, revision=revision, history=True) if include_export else None
        export_bytes = None if exported is None else _json_bytes(exported)
        if exported is not None:
            receipt["export"] = {"file": EXPORT_NAME, "sha256": sha256_bytes(export_bytes), "revision": revision,
                                 "paper_id": paper.id, "records": len(exported["records"]), "blobs": len(exported["blobs"]),
                                 "history": len(exported.get("history", [])),
                                 "missing_blobs": exported["provenance"].get("missing_blobs", [])}
        validate_finalization(snapshot, receipt)
    except CoreError as exc:
        db.rollback()
        if exc.code not in ("FINALIZATION_CONFLICT", "FINALIZATION_INVALID"):
            _diagnostic(directory, exc, audit_id=audit_id, revision=revision, protected=protected)
        raise
    finally:
        db.rollback()
    # Filesystem publication starts only after the consistent read is closed.
    directory.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(dir=directory.parent, prefix=".paper-finalization-"))
    try:
        (staged / SNAPSHOT_NAME).write_bytes(_json_bytes(snapshot))
        (staged / RECEIPT_NAME).write_bytes(_json_bytes(receipt))
        if export_bytes is not None:
            (staged / EXPORT_NAME).write_bytes(export_bytes)
        load_finalization(staged)
        if directory.exists():
            directory.rmdir()  # Only the empty destination accepted above.
        os.replace(staged, directory)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return _result(directory, snapshot, receipt)


__all__ = ["FINALIZATION_VERSION", "SNAPSHOT_NAME", "RECEIPT_NAME", "EXPORT_NAME", "finalize_audit",
           "load_finalization", "validate_finalization", "protected_destination", "producer_identity"]
