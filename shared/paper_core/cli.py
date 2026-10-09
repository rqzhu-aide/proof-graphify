"""Command line entry for the shared proofcheck core (implementation-handoff 5).

Every command prints exactly one JSON object on stdout; diagnostics go to
stderr. Exit codes: 0 ok, 2 invalid request, 3 conflict, 4 incompatible
database, 5 source unavailable, 6 render or publication failure. An incomplete
mathematical assessment is a successful status query with
``process_complete: false``, not a command failure. Workers never edit the
SQLite file directly; every mutation enters through these commands.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import CONTRACT_NAME, CONTRACT_VERSION, CORE_VERSION, PACKET_VERSION, PROJECTION_VERSION, STORAGE_FORMAT
from .acceptance import apply_batch
from .errors import CoreError, InvalidRequest, PublicationError
from .export_import import import_legacy, migrate_overview, write_export
from .ids import COLLECTIONS, PREFIXES, new_id
from .packets import MODES, get_packet
from .paths import resolve_path
from .projection import build_projection
from .publish import publish_report
from .queries import changes as query_changes
from .queries import status as query_status
from .queries import validate_snapshot
from .review import compare, map_response, reconcile, record_qualification, submit_review
from .sources import anchor_sources, capture_sources, review_sources
from .storage import Database, initialize, paper_record
from .telemetry import STAGES, events, record_event, summarize

ID_KINDS = tuple(PREFIXES)
PROG = "paper_audit.py"


class _Parser(argparse.ArgumentParser):
    """argparse that reports usage problems as InvalidRequest (exit 2 with a JSON body)."""

    def error(self, message):
        raise InvalidRequest(f"{self.prog}: {message}", code="USAGE")


# -- helpers ----------------------------------------------------------------------
def _load_json(path, *, what="JSON file"):
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise InvalidRequest(f"cannot read {what} {p}: {exc}", code="FILE_UNREADABLE") from exc
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidRequest(f"{what} {p} is not valid UTF-8 JSON: {exc}", code="JSON_INVALID") from exc


def _write_json(path, payload) -> dict:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
    staged = p.with_name(p.name + f".tmp-{os.getpid()}")
    staged.write_text(text, encoding="utf-8", newline="\n")
    os.replace(staged, p)
    return {"path": str(p), "bytes": len(text.encode("utf-8"))}


def _write_template(path, payload):
    """Authoring assistance never overwrites an existing response or source."""
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if not destination.is_file() or destination.read_bytes() != data:
            raise InvalidRequest("template output exists with different content; choose a new output path",
                                 code="OUTPUT_CONFLICT") from None
    return {"path": str(destination), "bytes": len(data)}


def _protect_template_destination(db, path):
    destination = resolve_path(path)
    protected = {db.path.resolve()}
    for source in db.heads("sources"):
        paper = db.head("papers", source.body["paper_id"])
        if paper is not None:
            protected.add((Path(paper.body["source_root"]) / source.body["path"]).resolve())
    if destination in protected:
        raise InvalidRequest("template output cannot replace a database or registered source, even if absent",
                             code="OUTPUT_CONFLICT")


def cmd_template(args):
    from .assistance import authoring_template
    with Database(args.db) as db:
        _protect_template_destination(db, args.out)
        if db.packet(args.packet) is None:
            raise InvalidRequest(f"unknown packet {args.packet}", code="PACKET_UNKNOWN")
        result = authoring_template(args.collection, packet_id=args.packet, record_id=args.id, db=db)
    return {"command": "template", "file": _write_template(args.out, result),
            "next_action": "author the template's scientific fields; submit only its template member"}


def cmd_review_mapping_template(args):
    from .assistance import mapping_template
    from .contract import WORKER_RESPONSE, validate_shape
    from .acceptance import COMMAND_MODES
    from .packets import load_packet
    from .review import _mapped_indexes, classify_judgments
    with Database(args.db) as db:
        _protect_template_destination(db, args.out)
        response = db.head("responses", args.response)
        if response is None or response.retired:
            raise InvalidRequest("mapping template needs a live saved response", code="RESPONSE_UNKNOWN")
        packet = db.packet(args.packet)
        if packet is None:
            raise InvalidRequest(f"unknown packet {args.packet}", code="PACKET_UNKNOWN")
        if packet["manifest"]["mode"] not in COMMAND_MODES["review_map"]:
            raise InvalidRequest("choose a private coordinator mapping packet containing canonical targets",
                                 code="PACKET_MODE")
        try:
            worker = json.loads(db.get_blob(response.body["original_blob"]))
        except (TypeError, ValueError, UnicodeError):
            raise InvalidRequest("unreadable worker response requires a new response, not mapping",
                                 code="RESPONSE_UNREADABLE") from None
        if validate_shape(WORKER_RESPONSE, worker):
            raise InvalidRequest("malformed worker response requires a new response, not mapping",
                                 code="RESPONSE_UNREADABLE")
        original = load_packet(db, response.body["packet_id"])
        _, pending = classify_judgments(original["_manifest"], worker, original)
        already_mapped = _mapped_indexes(db, response.id)
        indexes = args.judgment if args.judgment is not None else [
            i for i, _ in pending if i not in already_mapped]
        if any(i < 0 or i >= len(worker["judgments"]) for i in indexes):
            raise InvalidRequest("judgment indexes must identify saved response rows")
        result = mapping_template(source_packet_id=response.body["packet_id"], mapping_packet_id=args.packet,
                                  response_id=args.response, judgment_indexes=indexes)
    return {"command": "review mapping-template", "file": _write_template(args.out, result),
            "next_action": "author exact target and rationale for each selected row; keep the worker bytes unchanged"}


def _parse_target(text: str) -> dict:
    collection, sep, id = text.partition(":")
    if not sep or not collection or not id:
        raise InvalidRequest(f"targets are written COLLECTION:ID, got {text!r}", code="USAGE")
    if collection not in COLLECTIONS:
        raise InvalidRequest(f"unknown collection {collection!r} in target {text!r}", code="USAGE")
    return {"collection": collection, "id": id}


def _revision_arg(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise InvalidRequest(f"revision must be an integer, got {value!r}", code="USAGE") from None


def _agree(option: str, given, found, *, what: str):
    if given is not None and given != found:
        raise InvalidRequest(f"{option} {given} does not match the {what} named in the file ({found})",
                             code="ARGUMENT_MISMATCH")


def _latest_audit(db: Database):
    audits = db.heads("audits")
    if not audits:
        return None
    return sorted(audits, key=lambda a: (a.revision or 0, a.id))[-1]


def _diag(message: str):
    print(message, file=sys.stderr)


# -- command implementations -------------------------------------------------------
def cmd_init(args):
    result = initialize(args.db, source_root=args.source_root, title=args.title)
    result["command"] = "init"
    return result


def cmd_attach(args):
    report = Path(args.report).as_posix()
    with Database(args.db, write=True) as db:
        paper = paper_record(db)
        if report in paper.body["report_paths"]:
            return {"command": "attach", "changed": False, "paper_id": paper.id, "report_paths": paper.body["report_paths"],
                    "revision": db.max_revision()}
        packet = get_packet(db, targets=[{"collection": "papers", "id": paper.id}], mode="author")
        body = dict(paper.body)
        body["report_paths"] = list(paper.body["report_paths"]) + [report]
        batch = {"contract_version": CONTRACT_VERSION, "request_id": new_id("request"), "packet_id": packet["packet_id"],
                 "edits": [{"op": "replace", "collection": "papers", "id": paper.id,
                            "expected_version": paper.version, "body": body}]}
        receipt = apply_batch(db, batch)
        return {"command": "attach", "changed": True, "paper_id": paper.id, "report_paths": body["report_paths"],
                "packet_id": packet["packet_id"], "receipt": receipt, "revision": receipt["revision"]}


def cmd_migrate_overview(args):
    result = migrate_overview(args.db, backup=args.backup)
    result["command"] = "migrate-overview"
    return result


def cmd_source_capture(args):
    listing = _load_json(args.files, what="file list")
    if isinstance(listing, dict) and isinstance(listing.get("files"), list):
        listing = listing["files"]
    if not isinstance(listing, list) or not all(isinstance(f, str) and f for f in listing):
        raise InvalidRequest("the file list must be a JSON array of relative paths (or {\"files\": [...]})")
    with Database(args.db, write=True) as db:
        result = capture_sources(db, files=listing, request_id=args.request_id)
    result["command"] = "source capture"
    return result


def cmd_source_anchor(args):
    request = _load_json(args.request, what="anchor request")
    with Database(args.db, write=True) as db:
        result = anchor_sources(db, request=request)
    result["command"] = "source anchor"
    return result


def cmd_source_review(args):
    batch = _load_json(args.request, what="source review batch")
    with Database(args.db, write=True) as db:
        result = review_sources(db, batch=batch)
    return {"command": "source review", "receipt": result}


def cmd_ids(args):
    if args.kind not in ID_KINDS:
        raise InvalidRequest(f"unknown id kind {args.kind!r}; choose one of {list(ID_KINDS)}", code="USAGE")
    if args.count < 1 or args.count > 1000:
        raise InvalidRequest("--count must be between 1 and 1000", code="USAGE")
    return {"command": "ids", "kind": args.kind, "ids": [new_id(args.kind) for _ in range(args.count)]}


def _packet_summary(packet: dict) -> dict:
    return {"packet_id": packet["packet_id"], "packet_version": packet["packet_version"], "mode": packet["mode"],
            "base_revision": packet["base_revision"], "targets": packet["targets"], "records": len(packet["records"]),
            "write_scope": len(packet["write_scope"]), "extends": packet.get("extends"),
            "omitted": len(packet.get("omitted") or []), "truncated": packet.get("truncated", False)}


def cmd_get(args):
    if args.extend is not None:
        if args.target:
            raise InvalidRequest("get --extend takes the added targets from the context request, not --target",
                                 code="USAGE")
        if args.request is None:
            raise InvalidRequest("get --extend needs --request CONTEXT.json", code="USAGE")
        request = _load_json(args.request, what="context request")
        with Database(args.db, write=True) as db:
            packet = get_packet(db, extend=args.extend, request=request)
    else:
        if not args.target:
            raise InvalidRequest("get needs at least one --target COLLECTION:ID (or --extend PACKET_ID)", code="USAGE")
        if args.mode not in MODES:
            raise InvalidRequest(f"--mode must be one of {list(MODES)}", code="USAGE")
        targets = [_parse_target(t) for t in args.target]
        with Database(args.db, write=True) as db:
            packet = get_packet(db, targets=targets, mode=args.mode)
    if args.out is None:
        packet["command"] = "get"
        return packet
    written = _write_json(args.out, packet)
    summary = _packet_summary(packet)
    summary.update({"command": "get", "out": written["path"], "bytes": written["bytes"]})
    return summary


def cmd_apply(args):
    batch = _load_json(args.batch, what="batch")
    with Database(args.db, write=True) as db:
        receipt = apply_batch(db, batch)
    return {"command": "apply", "receipt": receipt, "revision": receipt["revision"]}


def cmd_compare(args):
    batch = _load_json(args.batch, what="comparison batch")
    if isinstance(batch, dict):
        _agree("--packet", args.packet, batch.get("packet_id"), what="packet")
    with Database(args.db, write=True) as db:
        receipt = compare(db, batch=batch)
    return {"command": "compare", "receipt": receipt, "revision": receipt["revision"]}


def cmd_review_submit(args):
    submission = _load_json(args.submission, what="submission envelope")
    try:
        response_bytes = Path(args.response).read_bytes()
    except OSError as exc:
        raise InvalidRequest(f"cannot read worker response {args.response}: {exc}", code="FILE_UNREADABLE") from exc
    with Database(args.db, write=True) as db:
        result = submit_review(db, submission=submission, response_bytes=response_bytes)
    result["command"] = "review submit"
    return result


def cmd_review_map(args):
    mapping = _load_json(args.mapping, what="mapping request")
    if isinstance(mapping, dict):
        _agree("--response", args.response, mapping.get("response_id"), what="response")
    with Database(args.db, write=True) as db:
        result = map_response(db, mapping=mapping)
    result["command"] = "review map"
    return result


def cmd_review_reconcile(args):
    batch = _load_json(args.batch, what="reconciliation batch")
    if isinstance(batch, dict):
        _agree("--packet", args.packet, batch.get("packet_id"), what="packet")
    with Database(args.db, write=True) as db:
        receipt = reconcile(db, batch=batch)
    return {"command": "review reconcile", "receipt": receipt, "revision": receipt["revision"]}


def cmd_qualification_record(args):
    receipt_request = _load_json(args.receipt, what="qualification receipt")
    with Database(args.db, write=True) as db:
        receipt = record_qualification(db, receipt=receipt_request)
    return {"command": "qualification record", "receipt": receipt, "revision": receipt["revision"]}


def cmd_changes(args):
    with Database(args.db) as db:
        result = query_changes(db, since=_revision_arg(args.since), limit=args.limit, offset=args.offset)
    result["command"] = "changes"
    return result


def cmd_status(args):
    with Database(args.db) as db:
        result = query_status(db, audit_id=args.audit, revision=_revision_arg(args.snapshot))
    result["command"] = "status"
    return result


def cmd_migrate(args):
    from .storage import migrate_database
    return {"command": "migrate", **migrate_database(args.db, backup=args.backup)}


def cmd_work_list(args):
    from .controller import list_work
    with Database(args.db) as db:
        result = list_work(db, audit_id=args.audit, focus=_parse_target(args.focus) if args.focus else None,
                           revision=_revision_arg(args.snapshot), limit=args.limit, cursor=args.cursor)
    return {"command": "work list", **result}


def _compact_work(result):
    return {k: v for k, v in result.items()
            if k not in ("packet", "manifest", "scaffold", "worker_guidance", "coordinator_guidance", "source_navigation",
                         "submission_envelope_template")}


def _work_commands(db, audit_id):
    flags = [str(db.path.resolve()), "--audit", audit_id]
    return [[PROG, "work", "list", *flags], [PROG, "status", *flags]]


def _preparation_diagnostic(db, result, audit_id):
    """Explain an empty selection using existing assessment and selection diagnostics."""
    if result.get("prepared"):
        return
    state = query_status(db, audit_id=audit_id)
    codes = {row.get("code") for row in result.get("diagnostics", [])}
    deferred = result.get("deferred_reasons", result.get("deferred", []))
    reasons = {row.get("reason") for row in deferred if isinstance(row, dict)}
    if state["process_complete"]:
        reason = "recorded_scope_complete"
    elif "OVERSIZED_CONTEXT" in codes or "packet_size_limit" in reasons:
        reason = "packet_size_limit"
    elif result.get("coordinator_actions") or "needs_coordinator" in reasons:
        reason = "coordinator_work"
    else:
        reason = "prerequisites_or_remaining_work"
    result["preparation"] = {"reason": reason, "revision": state["revision"],
                             "process_complete": state["process_complete"],
                             "next_commands": _work_commands(db, audit_id)}


def _write_work_artifacts(db, result, directory):
    from .controller import write_artifacts
    try:
        return write_artifacts(db, result, directory)
    except CoreError as exc:
        kind, identifier = ("--packet", result["packet_id"]) if "packet" in result else (
            "--request", result["request_id"])
        exc.records.append({"next_command": [PROG, "work", "inspect", str(db.path.resolve()),
                                               kind, identifier, "--out", "<new-output-directory>"],
                            "note": "Inspect the saved work; keep differing files and use a new output directory."})
        raise


def cmd_work_prepare(args):
    from .controller import prepare_work
    with Database(args.db, write=True) as db:
        result = prepare_work(db, audit_id=args.audit, mode=args.mode,
                              focus=_parse_target(args.focus) if args.focus else None, task_ids=args.task,
                              exclude_task_ids=args.exclude_task, max_units=args.max_units,
                              max_bytes=args.max_bytes, allow_provisional=args.allow_provisional, route_id=args.route)
        if result.get("prepared"):
            result["files"] = _write_work_artifacts(db, result, args.out)
        else:
            _preparation_diagnostic(db, result, args.audit)
    return {"command": "work prepare", **_compact_work(result)}


def cmd_work_extend(args):
    from .controller import extend_work, read_bounded
    from .canonical import load_json_bytes
    try:
        request = load_json_bytes(read_bounded(args.request, 65536))
    except (UnicodeError, ValueError) as exc:
        raise InvalidRequest(f"context request is not valid UTF-8 JSON: {exc}", code="JSON_INVALID") from exc
    with Database(args.db, write=True) as db:
        result = extend_work(db, packet_id=args.packet, request=request)
        if result.get("prepared"):
            result["files"] = _write_work_artifacts(db, result, args.out)
    return {"command": "work extend", **_compact_work(result)}


def cmd_work_submit(args):
    from .controller import ENVELOPE_LIMIT, RESPONSE_LIMIT, read_bounded, submit_work
    try:
        envelope = read_bounded(args.submission, ENVELOPE_LIMIT)
        response = read_bounded(args.response, RESPONSE_LIMIT)
    except CoreError as exc:
        return {"command": "work submit", "stored": False, "exit_code": exc.exit_code, **exc.to_json()}
    with Database(args.db, write=True) as db:
        result = submit_work(db, envelope_bytes=envelope, response_bytes=response)
    return {"command": "work submit", **result}


def cmd_work_inspect(args):
    from .controller import inspect_work
    if args.audit and args.out:
        raise InvalidRequest("history inspection has no payload output; choose a request or packet")
    with Database(args.db) as db:
        result = inspect_work(db, request_id=args.request, packet_id=args.packet, audit_id=args.audit,
                              limit=args.limit, cursor=args.cursor)
        if args.out:
            result["files"] = _write_work_artifacts(db, result, args.out)
        if "manifest" in result:
            manifest = result["manifest"]
            result["assignment"] = {"audit_id": manifest["work"]["audit_id"], "mode": manifest["mode"],
                                    "task_ids": [t["id"] for t in manifest["work"]["tasks"]]}
    return {"command": "work inspect", **_compact_work(result)}


def cmd_stage_scope(args):
    from .authoring import create_audit
    with Database(args.db, write=True) as db:
        result = create_audit(db, mode=args.mode, targets=[_parse_target(t) for t in args.target],
                              report_path=args.report_path)
    return {"command": "stage1 scope", **result}


def cmd_stage_add_unit(args):
    from .authoring import create_unit
    definition = _load_json(args.input, what="proof unit definition")
    with Database(args.db, write=True) as db:
        result = create_unit(db, definition)
    return {"command": "stage1 add-unit", **result}


def cmd_stage_add_targets(args):
    from .authoring import add_targets
    with Database(args.db, write=True) as db:
        result = add_targets(db, audit_id=args.audit, expected_version=args.expected_version,
                             targets=[_parse_target(target) for target in args.target])
    return {"command": "stage1 add-targets", **result}


def cmd_stage_add_record(args):
    from .authoring import create_record
    definition = _load_json(args.input, what="graph record definition")
    with Database(args.db, write=True) as db:
        result = create_record(db, definition)
    return {"command": "stage1 add-record", **result}


def cmd_stage_consolidate_drafts(args):
    from .drafts import consolidate_drafts
    bundles = [_load_json(path, what="local Phase 1 draft") for path in args.input]
    result = consolidate_drafts(bundles)
    return {"command": "stage1 consolidate-drafts", "file": _write_template(args.out, result),
            "next_action": "Coordinator confirms shared identities and authors the proposed graph; "
                           "preserve returned examinations and their actual authors."}


def cmd_stage_correct_claim(args):
    from .authoring import correct_claim
    from .correction_feedback import compact_receipt, sync_current
    correction = _load_json(args.correction, what="claim correction") if args.correction else None
    with Database(args.db, write=True) as db:
        result = (sync_current(db, args.item, args.expected_version) if args.sync_current
                  else correct_claim(db, args.item, args.expected_version, correction))
        result = compact_receipt(db, result)
    return {"command": "stage1 correct-claim", **result}


def cmd_stage_prepare_group(args):
    from .review_groups import prepare_group, reexport_group
    selectors = (args.task, args.exclude_task, args.exclude_group, args.focus,
                 args.max_packets, args.max_units, args.max_bytes)
    if args.resume_group and any(value is not None for value in selectors):
        raise InvalidRequest("--resume-group re-exports fixed membership; omit selection and capacity options",
                             code="USAGE")
    with Database(args.db, write=True) as db:
        if args.resume_group:
            result = reexport_group(db, audit_id=args.audit, index_path=args.resume_group, output=args.out)
        else:
            result = prepare_group(db, audit_id=args.audit, output=args.out, task_ids=args.task,
                exclude_task_ids=args.exclude_task or (), exclude_groups=args.exclude_group or (),
                focus=_parse_target(args.focus) if args.focus else None,
                max_packets=3 if args.max_packets is None else args.max_packets,
                max_units=5 if args.max_units is None else args.max_units,
                max_bytes=131072 if args.max_bytes is None else args.max_bytes)
    return {"command": "stage2 prepare-group", **result}


def cmd_stage_status(args):
    from .stage1 import stage_status
    with Database(args.db) as db:
        result = stage_status(db, audit_id=args.audit, stage=args.stage_number,
                              revision=_revision_arg(args.snapshot),
                              focus=_parse_target(args.focus) if args.focus else None)
    return {"command": f"stage{args.stage_number} status", **result}


def cmd_stage_intake_response(args):
    from .controller import RESPONSE_LIMIT, read_bounded
    from .intake import intake_response
    original = resolve_path(args.response)
    destination = resolve_path(args.out)
    if destination == original:
        raise InvalidRequest("keep the original response; choose a different candidate path", code="OUTPUT_CONFLICT")
    raw = read_bounded(original, RESPONSE_LIMIT)
    with Database(args.db) as db:
        _protect_template_destination(db, destination)
        result = intake_response(db, packet_id=args.packet, response_bytes=raw)
    candidate = result.pop("response")
    output = None
    if candidate is not None and any(candidate.get(key) for key in ("results", "coverage", "findings")):
        output = _write_template(destination, candidate)
    return {"command": "stage1 intake-response", **result, "candidate_file": output,
            "original_response_path": str(original),
            "next_action": "Submit a usable candidate through stage1 examine with the original examiner. "
                           "Deferred concerns remain for local repair or an explicit limitation; shape is not acceptance."
                           if output else "No candidate written. Repair the named local input; keep the original response."}


def cmd_stage_submit_group(args):
    from .review_groups import submit_group
    overrides = {}
    for packet_id, path in args.response or []:
        if packet_id in overrides:
            raise InvalidRequest("select only one response override per packet", code="GROUP_INPUT", records=[packet_id])
        overrides[packet_id] = str(resolve_path(path))
    with Database(args.db, write=True) as db:
        result = submit_group(db, audit_id=args.audit, index_path=args.group_index,
                              reviewer=args.reviewer, exposure=args.exposure,
                              exposure_note=args.exposure_note, response_paths=overrides)
    return {"command": "stage2 submit-group", **result}


def cmd_stage_prepare(args):
    from .stage1 import prepare_stage
    mode = {"integration": "reconcile", "global": "primary"}.get(args.mode, args.mode)
    with Database(args.db, write=True) as db:
        result = prepare_stage(db, audit_id=args.audit, stage=args.stage_number, mode=mode,
            focus=_parse_target(args.focus) if args.focus else None, task_ids=args.task,
            exclude_task_ids=args.exclude_task, max_units=args.max_units, max_bytes=args.max_bytes,
            allow_provisional=args.allow_provisional, correct=args.correct)
        if result.get("prepared") and args.out:
            result["files"] = _write_work_artifacts(db, result, args.out)
    return {"command": f"stage{args.stage_number} prepare", **_compact_work(result)}


def cmd_stage_submit(args):
    from .canonical import canonical_bytes
    from .controller import ENVELOPE_LIMIT, RESPONSE_LIMIT, read_bounded, stage_submission_envelope, submit_work
    response = read_bounded(args.response, RESPONSE_LIMIT)
    if args.submission:
        envelope = read_bounded(args.submission, ENVELOPE_LIMIT)
        submission = _load_json(args.submission, what="submission envelope")
    else:
        if not args.packet or not args.reviewer:
            raise InvalidRequest("supply --packet and --reviewer, or an existing --submission envelope", code="USAGE")
        submission = stage_submission_envelope(packet_id=args.packet, reviewer=args.reviewer,
            response_bytes=response, exposure=args.exposure, exposure_note=args.exposure_note,
            request_id=args.request_id)
        envelope = canonical_bytes(submission)
    with Database(args.db, write=True) as db:
        packet = db.packet(submission.get("packet_id"))
        expected = {"examine": "primary", "review": "independent", "integrate": "reconcile"}.get(args.subcommand)
        if packet is None or not isinstance(packet["manifest"].get("work"), dict):
            raise InvalidRequest("stage submission requires a saved work assignment", code="WORK_PACKET_REQUIRED")
        if expected is not None and packet["mode"] != expected:
            raise InvalidRequest("the packet belongs to another stage action", code="PACKET_MODE")
        previous = db.work_submission(submission.get("request_id"))
        result = submit_work(db, envelope_bytes=envelope, response_bytes=response)
        if packet["manifest"].get("protocol_version") == "coherent-proof-audit/1":
            # Invocation feedback is not part of the immutable saved receipt.
            replayed = bool(previous and previous["state"] != "received" and previous["result"] == result)
            result = {**result, "replayed": replayed}
            if replayed:
                result["next_actions"] = [
                    "This unchanged input replays a historical saved receipt and saves no new work. Stop resubmitting it.",
                    "Its remaining_task_ids describe that saved receipt, not current unfinished work. Check current stage status before deciding what remains."]
            if result.get("state") in ("needs_revision", "conflict") and not replayed and not args.submission and not args.request_id:
                result["next_actions"] = [
                    "Correct the named row, field or context and resubmit through this stage command; it derives the request ID.",
                    "Unchanged input replays this saved outcome and does not perform new work."]
    return {"command": f"stage{args.stage_number} {args.subcommand}", **result}


def cmd_stage_finalize(args):
    from .finalization import finalize_audit
    with Database(args.db) as db:
        result = finalize_audit(db, audit_id=args.audit, output=args.out,
                                partial=args.partial, include_export=args.export)
    return {"command": "stage2 finalize", **result}


def cmd_stage_render(args):
    from .stage3 import render
    result = render(args.bundle, output=args.out, receipt_output=args.receipt_out)
    return {"command": "stage3 render", **result}


def cmd_validate(args):
    with Database(args.db) as db:
        result = validate_snapshot(db, revision=_revision_arg(args.snapshot))
    result["command"] = "validate"
    return result


def cmd_checkpoint(args):
    with Database(args.db, write=True) as db:
        audit_id = args.audit
        if audit_id is None:
            audit = _latest_audit(db)
            audit_id = None if audit is None else audit.id
        projection = build_projection(db, audit_id=audit_id)
        result = publish_report(db, projection=projection, output=args.out, release=False)
    result.update({"command": "checkpoint", "audit_id": audit_id,
                   "process_complete": projection["summary"]["progress"]["process_complete"],
                   "factual_summary": projection["summary"]["factual"]})
    if audit_id is not None and not result["process_complete"]:
        result["next_commands"] = _work_commands(db, audit_id)
    return result


def cmd_release(args):
    """Compatibility convenience using the same frozen pipeline as the three stages."""
    from .finalization import finalize_audit
    from .publish import publish_frozen
    directory = resolve_path(args.out)
    with Database(args.db) as db:
        frozen = finalize_audit(db, audit_id=args.audit, output=directory, include_export=True)
    publication = publish_frozen(directory, output=directory / "report.html")
    return {"command": "release", **frozen, "publication": publication,
            "delivery_complete": True, "files": sorted(p.name for p in directory.iterdir() if p.is_file())}


def cmd_export(args):
    with Database(args.db) as db:
        result = write_export(db, output=args.out, revision=_revision_arg(args.snapshot), history=args.history)
    result["command"] = "export"
    return result


def cmd_backup(args):
    with Database(args.db) as db:
        result = db.backup(args.out)
    result["command"] = "backup"
    return result


def cmd_import_legacy(args):
    result = import_legacy(args.audit_folder, db_path=args.db, mapping_path=args.map)
    result["command"] = "import-legacy"
    return result


def cmd_telemetry_record(args):
    details = {}
    if args.details is not None:
        text = args.details
        if Path(text).is_file():
            details = _load_json(text, what="event details")
        else:
            try:
                details = json.loads(text)
            except ValueError as exc:
                raise InvalidRequest(f"--details must be a JSON object or a path to one: {exc}", code="USAGE") from exc
    with Database(args.db, write=True) as db:
        result = record_event(db, run_id=args.run_id, stage=args.stage, elapsed_ms=args.elapsed_ms, details=details,
                              started_at=args.started_at)
    result["command"] = "telemetry record"
    return result


def cmd_telemetry_summary(args):
    with Database(args.db) as db:
        result = summarize(db, run_id=args.run_id)
        if args.events:
            result["event_list"] = events(db, run_id=args.run_id)
    result["command"] = "telemetry summary"
    return result


def cmd_version(args):
    from .bundle import verify_bundle
    return {"command": "version", "core_version": CORE_VERSION, "storage_format": STORAGE_FORMAT,
            "contract_version": CONTRACT_VERSION, "contract": CONTRACT_NAME, "packet_version": PACKET_VERSION,
            "projection_version": PROJECTION_VERSION, "python": sys.version.split()[0],
            "bundle": verify_bundle()}


# -- parser ---------------------------------------------------------------------------
def _db_arg(parser, *, run_id=True):
    parser.add_argument("db", help="path of the paper database")
    if run_id:
        parser.add_argument("--run-id", default=None,
                            help="record a 'command' telemetry event for this invocation under RUN_ID")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog=PROG, description="Proofcheck paper database commands (one JSON object on stdout).")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    for number in (1, 2):
        stage = sub.add_parser(f"stage{number}", help="prepare and perform declared work" if number == 1
                               else "review, integrate and freeze saved work").add_subparsers(
            dest="subcommand", metavar="ACTION", required=True)
        if number == 1:
            p = stage.add_parser("intake-response", help="prepare a native primary response subset without changing saved work")
            _db_arg(p, run_id=False)
            p.add_argument("--packet", required=True)
            p.add_argument("--response", required=True)
            p.add_argument("--out", required=True, metavar="CANDIDATE")
            p.set_defaults(func=cmd_stage_intake_response, stage_number=1)
            p = stage.add_parser("scope", help="declare one finite audit scope")
            _db_arg(p)
            p.add_argument("--mode", choices=("full", "focused", "triage"), default="full")
            p.add_argument("--target", action="append", default=[])
            p.add_argument("--report-path", default="report.html")
            p.set_defaults(func=cmd_stage_scope, stage_number=1)
            p = stage.add_parser("add-targets", help="append explicit item targets to the same Full audit")
            _db_arg(p)
            p.add_argument("--audit", required=True)
            p.add_argument("--expected-version", required=True, type=int)
            p.add_argument("--target", action="append", required=True, metavar="items:ID")
            p.set_defaults(func=cmd_stage_add_targets, stage_number=1)
            p = stage.add_parser("add-unit", help="save an exact claim and its coherent written route")
            _db_arg(p)
            p.add_argument("--input", required=True, metavar="JSON")
            p.set_defaults(func=cmd_stage_add_unit, stage_number=1)
            p = stage.add_parser("add-record", help="save ordinary setup, shared results or proof units")
            _db_arg(p)
            p.add_argument("--input", required=True, metavar="JSON")
            p.set_defaults(func=cmd_stage_add_record, stage_number=1)
            p = stage.add_parser("consolidate-drafts", help="combine local proposals without changing a database")
            p.add_argument("--input", action="append", required=True, metavar="JSON",
                           help="one worker's local draft; repeat for other returns")
            p.add_argument("--out", required=True, metavar="JSON")
            p.set_defaults(func=cmd_stage_consolidate_drafts, stage_number=1)
            p = stage.add_parser("correct-claim", help="correct an ordinary claim and its direct exact specification")
            _db_arg(p)
            p.add_argument("--item", required=True)
            p.add_argument("--expected-version", required=True, type=int)
            correction = p.add_mutually_exclusive_group(required=True)
            correction.add_argument("--correction", metavar="JSON")
            correction.add_argument("--sync-current", action="store_true",
                                    help="align the direct exact specification with the saved current statement")
            p.set_defaults(func=cmd_stage_correct_claim, stage_number=1)
        p = stage.add_parser("status", help="account for this stage's saved work")
        _db_arg(p)
        p.add_argument("--audit", required=True)
        p.add_argument("--focus")
        p.add_argument("--snapshot")
        p.set_defaults(func=cmd_stage_status, stage_number=number)
        p = stage.add_parser("prepare", help="return one current assignment or explain that none is useful")
        _db_arg(p)
        p.add_argument("--audit", required=True)
        if number == 2:
            p.add_argument("--mode", choices=("independent", "integration", "global"), default="independent")
        else:
            p.set_defaults(mode="primary")
        p.add_argument("--focus")
        p.add_argument("--task", action="append", default=None)
        p.add_argument("--exclude-task", action="append", default=[])
        p.add_argument("--max-units", type=int, default=5)
        p.add_argument("--max-bytes", type=int, default=131072)
        p.add_argument("--allow-provisional", action="store_true")
        p.add_argument("--out", metavar="DIRECTORY")
        p.add_argument("--correct", action="store_true",
                       help="optionally correct completed current integrations named by --task; stage2 integration only")
        p.set_defaults(func=cmd_stage_prepare, stage_number=number)
        for action in (("examine",) if number == 1 else ("review", "integrate", "submit")):
            p = stage.add_parser(action, help="preserve the actual response and generate routine record associations")
            _db_arg(p)
            p.add_argument("--response", required=True)
            p.add_argument("--submission", help="existing coordinator envelope, when recovering a saved attempt")
            p.add_argument("--packet")
            p.add_argument("--reviewer")
            p.add_argument("--request-id")
            p.add_argument("--exposure", choices=("source_only", "route_provided", "compromised"))
            p.add_argument("--exposure-note", default="")
            p.set_defaults(func=cmd_stage_submit, stage_number=number)
        if number == 2:
            p = stage.add_parser("submit-group", help="consume saved reviewer-group responses once, using existing intake history")
            _db_arg(p)
            p.add_argument("--audit", required=True)
            p.add_argument("--group-index", required=True)
            p.add_argument("--reviewer", required=True)
            p.add_argument("--exposure", required=True, choices=("source_only", "route_provided", "compromised"))
            p.add_argument("--exposure-note", default="")
            p.add_argument("--response", action="append", nargs=2, metavar=("PACKET_ID", "PATH"),
                           help="explicit response path override for one member (repeatable)")
            p.set_defaults(func=cmd_stage_submit_group, stage_number=2)
            p = stage.add_parser("prepare-group", help="deliver distinct ordinary packets to one independent reviewer")
            _db_arg(p)
            p.add_argument("--audit", required=True)
            p.add_argument("--out", required=True, metavar="DIRECTORY")
            p.add_argument("--task", action="append", default=None)
            p.add_argument("--exclude-task", action="append", default=None)
            p.add_argument("--exclude-group", action="append", default=None, metavar="INDEX")
            p.add_argument("--focus")
            p.add_argument("--max-packets", type=int, default=None)
            p.add_argument("--max-units", type=int, default=None)
            p.add_argument("--max-bytes", type=int, default=None)
            p.add_argument("--resume-group", metavar="INDEX", help="re-export fixed saved membership")
            p.set_defaults(func=cmd_stage_prepare_group, stage_number=2)
            p = stage.add_parser("finalize", aliases=["freeze"], help="freeze this assessed revision with an honest delivery label")
            _db_arg(p)
            p.add_argument("--audit", required=True)
            p.add_argument("--out", required=True, metavar="DIRECTORY")
            p.add_argument("--partial", action="store_true", help="explicitly retain a working label")
            p.add_argument("--export", action="store_true", help="include the saved database export and captured blobs")
            p.set_defaults(func=cmd_stage_finalize, stage_number=2)
    stage = sub.add_parser("stage3", help="render saved frozen input without a live database").add_subparsers(
        dest="subcommand", metavar="ACTION", required=True)
    p = stage.add_parser("render", aliases=["build"], help="build or retry HTML from the same frozen scientific bytes")
    p.add_argument("bundle", help="directory containing the frozen snapshot and finalization receipt")
    p.add_argument("--out", required=True, metavar="HTML")
    p.add_argument("--receipt-out", metavar="JSON")
    p.set_defaults(func=cmd_stage_render)

    p = sub.add_parser("init", help="create a database with its paper record")
    _db_arg(p)
    p.add_argument("--source-root", required=True)
    p.add_argument("--title", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("attach", help="register a report path on the paper record")
    _db_arg(p)
    p.add_argument("--report", required=True)
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser("migrate-overview", help="upgrade an archify overview database in place (backup first)")
    _db_arg(p)
    p.add_argument("--backup", required=True)
    p.set_defaults(func=cmd_migrate_overview)

    p = sub.add_parser("migrate", help="upgrade native storage in place after an explicit SQLite backup")
    _db_arg(p)
    p.add_argument("--backup", required=True)
    p.set_defaults(func=cmd_migrate)

    work = sub.add_parser("work", help="bounded work preparation, submission and inspection").add_subparsers(
        dest="subcommand", metavar="ACTION", required=True)
    p = work.add_parser("list", help="derive current tasks and coordinator actions")
    _db_arg(p)
    p.add_argument("--audit", required=True)
    p.add_argument("--focus")
    p.add_argument("--snapshot")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--cursor")
    p.set_defaults(func=cmd_work_list)
    p = work.add_parser("prepare", help="prepare one coherent assignment without dispatching a model")
    _db_arg(p)
    p.add_argument("--audit", required=True)
    p.add_argument("--mode", choices=("primary", "independent", "reconcile"), required=True)
    p.add_argument("--focus")
    p.add_argument("--route", help="exact argument for supplied-route independent review")
    p.add_argument("--task", action="append", default=[])
    p.add_argument("--exclude-task", action="append", default=[])
    p.add_argument("--max-units", type=int, default=5)
    p.add_argument("--max-bytes", type=int, default=131072)
    p.add_argument("--allow-provisional", action="store_true")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_work_prepare)
    p = work.add_parser("extend", help="add captured neutral source to an independent work assignment")
    _db_arg(p)
    p.add_argument("--packet", required=True)
    p.add_argument("--request", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_work_extend)
    p = work.add_parser("submit", help="preserve and validate one structured response")
    _db_arg(p)
    p.add_argument("--submission", required=True)
    p.add_argument("--response", required=True)
    p.set_defaults(func=cmd_work_submit)
    p = work.add_parser("inspect", help="inspect saved input, a preparation, or bounded audit history")
    _db_arg(p)
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--request")
    choice.add_argument("--packet")
    choice.add_argument("--audit")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--cursor")
    p.add_argument("--out")
    p.set_defaults(func=cmd_work_inspect)

    source = sub.add_parser("source", help="capture, anchor and review sources").add_subparsers(dest="subcommand",
                                                                                                 metavar="ACTION")
    source.required = True
    p = source.add_parser("capture", help="capture listed files under the source root")
    _db_arg(p)
    p.add_argument("--files", required=True, help="path to a JSON file containing an array of relative source paths")
    p.add_argument("--request-id", default=None)
    p.set_defaults(func=cmd_source_capture)
    p = source.add_parser("anchor", help="create or rebind anchors from a locator request")
    _db_arg(p)
    p.add_argument("--request", required=True)
    p.set_defaults(func=cmd_source_anchor)
    p = source.add_parser("review", help="record source reviews and source issues")
    _db_arg(p)
    p.add_argument("--request", required=True)
    p.set_defaults(func=cmd_source_review)

    p = sub.add_parser("ids", help="mint identifiers")
    p.add_argument("--kind", required=True, help=f"one of {', '.join(ID_KINDS)}")
    p.add_argument("--count", type=int, default=1)
    p.set_defaults(func=cmd_ids)

    p = sub.add_parser("template", help="generate one collection's uncommitted authoring shape")
    _db_arg(p)
    p.add_argument("--collection", required=True, choices=COLLECTIONS)
    p.add_argument("--packet", required=True)
    p.add_argument("--id", default=None, help="existing shared identity for a same-ID extension")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_template)

    p = sub.add_parser("get", help="assemble a packet")
    _db_arg(p)
    p.add_argument("--target", action="append", default=[], help="COLLECTION:ID (repeatable; required unless --extend is used)")
    p.add_argument("--mode", default="author", help=f"one of {', '.join(MODES)}")
    p.add_argument("--extend", default=None, metavar="PACKET_ID")
    p.add_argument("--request", default=None, metavar="CONTEXT.json")
    p.add_argument("--out", default=None, metavar="PACKET.json")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("apply", help="accept an edit batch against a packet")
    _db_arg(p)
    p.add_argument("--batch", required=True)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("compare", help="record source-versus-record observations")
    _db_arg(p)
    p.add_argument("--packet", default=None)
    p.add_argument("--batch", required=True)
    p.set_defaults(func=cmd_compare)

    review = sub.add_parser("review", help="independent review submission, mapping, reconciliation").add_subparsers(
        dest="subcommand", metavar="ACTION")
    review.required = True
    p = review.add_parser("submit", help="preserve a worker response and derive independent checks")
    _db_arg(p)
    p.add_argument("--submission", required=True)
    p.add_argument("--response", required=True)
    p.set_defaults(func=cmd_review_submit)
    p = review.add_parser("map", help="map pending judgments of a needs_revision response")
    _db_arg(p)
    p.add_argument("--response", default=None, metavar="RESPONSE_ID")
    p.add_argument("--mapping", required=True)
    p.set_defaults(func=cmd_review_map)
    p = review.add_parser("mapping-template", help="scaffold coordinator mapping with worker and mapping packet identities")
    _db_arg(p)
    p.add_argument("--response", required=True)
    p.add_argument("--packet", required=True)
    p.add_argument("--judgment", type=int, action="append", default=None)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_review_mapping_template)
    p = review.add_parser("reconcile", help="record reconciliations against a reconcile packet")
    _db_arg(p)
    p.add_argument("--packet", default=None)
    p.add_argument("--batch", required=True)
    p.set_defaults(func=cmd_review_reconcile)

    qualification = sub.add_parser("qualification", help="reviewer qualification receipts").add_subparsers(
        dest="subcommand", metavar="ACTION")
    qualification.required = True
    p = qualification.add_parser("record", help="store a qualification receipt")
    _db_arg(p)
    p.add_argument("--receipt", required=True)
    p.set_defaults(func=cmd_qualification_record)

    p = sub.add_parser("changes", help="record versions committed after a revision")
    _db_arg(p)
    p.add_argument("--since", required=True, metavar="REV")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--offset", type=int, default=0)
    p.set_defaults(func=cmd_changes)

    p = sub.add_parser("status", help="progress and presentation state")
    _db_arg(p)
    p.add_argument("--audit", default=None)
    p.add_argument("--snapshot", default=None, metavar="REV")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("validate", help="check a snapshot (exit 2 when it fails)")
    _db_arg(p)
    p.add_argument("--snapshot", default=None, metavar="REV")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("checkpoint", help="render a working report")
    _db_arg(p)
    p.add_argument("--out", required=True, metavar="HTML")
    p.add_argument("--audit", default=None)
    p.set_defaults(func=cmd_checkpoint)

    p = sub.add_parser("release", help="freeze and render with an honest release or working label")
    _db_arg(p)
    p.add_argument("--audit", required=True)
    p.add_argument("--out", required=True, metavar="DIRECTORY")
    p.add_argument("--checkpoint-out", metavar="HTML",
                   help="accepted for older callers; delivery now keeps its working label in the chosen bundle")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("export", help="write the export JSON of a snapshot")
    _db_arg(p)
    p.add_argument("--out", required=True, metavar="JSON")
    p.add_argument("--snapshot", default=None, metavar="REV")
    p.add_argument("--history", action="store_true")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("backup", help="copy the database with the SQLite backup API")
    _db_arg(p)
    p.add_argument("--out", required=True, metavar="BACKUP")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("import-legacy", help="import a stat-paper-proofcheck v1.5 audit folder into a new database")
    p.add_argument("audit_folder")
    p.add_argument("--db", required=True, metavar="NEW_DB")
    p.add_argument("--map", required=True, metavar="MAPPING.json")
    p.set_defaults(func=cmd_import_legacy, run_id=None)

    telemetry = sub.add_parser("telemetry", help="observational timing events").add_subparsers(dest="subcommand",
                                                                                                metavar="ACTION")
    telemetry.required = True
    p = telemetry.add_parser("record", help="append one timing event")
    _db_arg(p, run_id=False)
    p.add_argument("--run-id", required=True)
    p.add_argument("--stage", required=True, help=f"one of {', '.join(STAGES)}")
    p.add_argument("--elapsed-ms", type=int, default=None)
    p.add_argument("--details", default=None, help="JSON object text or a path to a JSON file")
    p.add_argument("--started-at", default=None)
    p.set_defaults(func=cmd_telemetry_record, telemetry_own=True)
    p = telemetry.add_parser("summary", help="per-stage and per-run totals (observational only)")
    _db_arg(p, run_id=False)
    p.add_argument("--run-id", default=None)
    p.add_argument("--events", action="store_true", help="include the individual events")
    p.set_defaults(func=cmd_telemetry_summary, telemetry_own=True)

    p = sub.add_parser("version", help="core and format versions")
    p.set_defaults(func=cmd_version)
    return parser


# -- entry ------------------------------------------------------------------------------
def _emit(payload):
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _record_command_event(args, *, started, exit_code, error_code=None):
    run_id = getattr(args, "run_id", None)
    if not run_id or getattr(args, "telemetry_own", False) or getattr(args, "db", None) is None:
        return
    elapsed_ms = int(round((time.monotonic() - started) * 1000))
    details = {"command": args.command, "subcommand": getattr(args, "subcommand", None), "exit_code": exit_code,
               "outcome": "ok" if exit_code == 0 else "error", "core_version": CORE_VERSION}
    if error_code is not None:
        details["error_code"] = error_code
    try:
        with Database(args.db, write=True) as db:
            record_event(db, run_id=run_id, stage="command", elapsed_ms=elapsed_ms, details=details)
    except Exception as exc:  # telemetry never changes the command's outcome
        _diag(f"telemetry: could not record command event: {exc}")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (ValueError, AttributeError):  # pragma: no cover - exotic stdout replacements
            pass
    parser = build_parser()
    args = None
    started = time.monotonic()
    try:
        args = parser.parse_args(argv)
        payload = args.func(args)
        _emit(payload)
        exit_code = payload.get("exit_code", 0) if args.command in ("work", "stage1", "stage2") else 0
        if args.command == "validate" and not payload.get("ok", True):
            exit_code = 2
        _record_command_event(args, started=started, exit_code=exit_code)
        return exit_code
    except CoreError as exc:
        _emit(exc.to_json())
        _diag(f"{exc.code}: {exc.message}")
        for record in exc.records[:20]:
            _diag(f"  {json.dumps(record, ensure_ascii=False, default=str)}")
        if args is not None:
            _record_command_event(args, started=started, exit_code=exc.exit_code, error_code=exc.code)
        return exc.exit_code
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - last resort: still one JSON object on stdout
        _emit({"error": {"code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}", "records": []}})
        traceback.print_exc(file=sys.stderr)
        if args is not None:
            _record_command_event(args, started=started, exit_code=2, error_code="INTERNAL")
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
