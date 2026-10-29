"""Export several ordinary independent packets for one reviewer, without dispatch state."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .controller import inspect_work, write_artifacts
from .errors import CoreError, InvalidRequest
from .paths import resolve_path
from .stage1 import prepare_stage
from .work import derive_work

INDEX_NAME = "group-index.json"
DELIVERY_NAME = "reviewer-delivery.json"


def _saved_packets(db, audit_id, index_path):
    try:
        index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidRequest(f"Cannot read review group index: {exc}", code="GROUP_INDEX") from exc
    if not isinstance(index, dict) or index.get("group_version") != 1 \
            or index.get("audit_id") != audit_id or index.get("mode") != "independent" \
            or not isinstance(index.get("packets"), list):
        raise InvalidRequest("review group index must name this audit and independent packets", code="GROUP_INDEX")
    packets, seen, assigned = [], set(), set()
    for entry in index["packets"]:
        identity = entry.get("packet_id") if isinstance(entry, dict) else None
        if not isinstance(identity, str) or identity in seen:
            raise InvalidRequest("review group contains an invalid or repeated packet ID", code="GROUP_INDEX")
        saved = db.packet(identity)
        manifest = saved["manifest"] if saved else {}
        work = manifest.get("work", {})
        if manifest.get("mode") != "independent" or work.get("audit_id") != audit_id \
                or manifest.get("review_basis", "source_only") != "source_only":
            raise InvalidRequest("review group packet is not saved source-only work for this audit",
                                 code="GROUP_INDEX", records=[identity])
        ids = {task["id"] for task in work["tasks"]}
        if assigned & ids:
            raise InvalidRequest("review group repeats assigned tasks", code="GROUP_INDEX", records=sorted(assigned & ids))
        seen.add(identity)
        assigned.update(ids)
        packets.append(identity)
    return index, packets, assigned


def _protect(db, path):
    protected = {db.path.resolve()}
    paper = db.heads("papers")[0]
    source_root = Path(paper.body["source_root"]).resolve()
    protected.update((source_root / source.body["path"]).resolve() for source in db.heads("sources"))
    if path.resolve() in protected:
        raise InvalidRequest("group output would overwrite a source or database", code="OUTPUT_CONFLICT")


def _write_json(db, path, value, *, previous=None):
    """Only update an index written by this invocation; other differing files survive."""
    _protect(db, path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if not path.is_file():
            raise InvalidRequest(f"group output is not a file: {path}", code="OUTPUT_CONFLICT")
        existing = path.read_bytes()
        if existing == raw:
            return raw
        if previous is None or existing != previous:
            raise InvalidRequest(f"group output already exists with different content: {path}", code="OUTPUT_CONFLICT")
    path.parent.mkdir(parents=True, exist_ok=True)
    if previous is None:
        with path.open("xb") as stream:
            stream.write(raw)
    else:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".group-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return raw


def _entry(db, prepared, directory):
    packet, manifest = prepared["packet"], prepared["manifest"]
    folder = directory / prepared["packet_id"]
    records = {(row["ref"]["collection"], row["ref"]["id"]): row["body"] for row in packet["records"]}
    labels = []
    for target in packet.get("targets", []):
        body = records.get((target["collection"], target["id"]), {})
        label = body.get("label") or body.get("caption")
        if label and label not in labels:
            labels.append(label)
    if not labels:
        labels = ["Assigned proof examination"]
    source_root = Path(db.head("papers", db.head("audits", manifest["work"]["audit_id"]).body["paper_id"]).body["source_root"])
    sources = [{"path": str((source_root / row["body"]["path"]).resolve()),
                "sha256": row["body"]["blob_sha256"]}
               for row in packet["records"] if row["ref"]["collection"] == "sources"]
    worker_files = [str(folder / name) for name in prepared["worker_delivery_files"]]
    response_path = str(folder / "response.json")
    row = {"packet_id": prepared["packet_id"],
           "assigned_task_ids": [task["id"] for task in manifest["work"]["tasks"]],
           "labels": labels, "directory": str(folder), "worker_files": worker_files,
           "response_path": response_path}
    if "reused" in prepared:
        row["packet_reused"] = prepared["reused"]
    delivery = {"labels": labels, "files": worker_files, "sources": sources, "response_path": response_path}
    return row, delivery


def _failure(exc, db, index, directory):
    record = {"group_index": str(directory / INDEX_NAME),
              "packet_ids": [row["packet_id"] for row in index["packets"]],
              "recovery_commands": [["paper_audit.py", "work", "inspect", str(db.path),
                  "--packet", row["packet_id"], "--out", "<fresh-directory>"] for row in index["packets"]]}
    if isinstance(exc, CoreError):
        exc.records.append(record)
        return exc
    return InvalidRequest(f"Cannot export review group: {exc}", code="ARTIFACT_WRITE_FAILED", records=[record])


def _finish(db, index, directory, deliveries, *, index_bytes=None, reused=False):
    refs = Path(__file__).resolve().parents[2] / "references"
    delivery = {"instructions": "These are source-only files for the listed packets, not a new dispatch instruction. "
                "The coordinator identifies the unfinished packets to examine; re-exporting files does not "
                "request a repeated examination. For assigned work, reuse your own independent source context "
                "and fill each response-scaffold.json using worker-guidance.json. Save it at its listed "
                "response_path. Keep the generated fields and question_id. Put concerns about the assigned "
                "conclusion in judgment reasoning and outcome, and other concerns in coverage_note. "
                "Do not read coordinator files or primary opinions. Do not read other reviewers' responses "
                "outside your explicitly assigned source-only continuation lineage. "
                "The coordinator submits the responses; do not write the database.",
                "role_reference_files": [str(refs / "independent-checker.md"), str(refs / "mathematical-checking.md")],
                "packets": deliveries}
    _write_json(db, directory / DELIVERY_NAME, delivery)
    _write_json(db, directory / INDEX_NAME, index, previous=index_bytes)
    view = derive_work(db, audit_id=index["audit_id"])
    tracked = {tid for row in index["packets"] for tid in row["assigned_task_ids"]}
    tracked.update(row["task_id"] for row in index.get("unassigned", []))
    remaining = [task["id"] for task in view["tasks"] if task["id"] in tracked and task["state"] != "satisfied"]
    response_locations = []
    for row in index["packets"]:
        paths = list(dict.fromkeys(row.get("prior_response_paths", []) + [row["response_path"]]))
        response_locations.append({"packet_id": row["packet_id"], "paths": paths,
                                   "existing_paths": [path for path in paths if Path(path).is_file()]})
    reused_packets = [row["packet_id"] for row in index["packets"] if reused or row.get("packet_reused")]
    note = ("Group re-export preserves saved membership." if reused else
            "A new group may contain saved pending packets; group reuse and packet reuse are separate.")
    if reused_packets:
        note += " Inspect saved work for reused_packet_ids before assigning an examination."
    if not index["packets"]:
        note += " Only group index/delivery files were produced; there is no worker packet or response scaffold."
    if any(row.get("code") == "OVERSIZED_CONTEXT" for row in index.get("diagnostics", [])):
        note += (" Use the size diagnostics for an explicit larger permitted --max-bytes cap or a coherent "
                 "smaller selection in a new group; re-export does not change membership.")
    return {**index, "prepared": bool(index["packets"]), "reused": reused,
            "reused_packet_ids": reused_packets, "preparation_note": note,
            "packet_ids": [row["packet_id"] for row in index["packets"]],
            "assigned_task_ids": [tid for row in index["packets"] for tid in row["assigned_task_ids"]],
            "remaining_task_ids": remaining,
            "response_file_locations": response_locations,
            "continuation_note": "Before dispatch, inspect saved responses and current remaining_task_ids. "
                                 "An existing response file may be unfinished or unsubmitted; its presence is not "
                                 "acceptance. Re-export preserves membership and does not request new examinations.",
            "group_index": str(directory / INDEX_NAME), "reviewer_delivery": str(directory / DELIVERY_NAME)}


def submit_group(db, *, audit_id, index_path, reviewer, exposure, exposure_note="", response_paths=None):
    """Submit the finite saved membership, with explicit optional path selections."""
    from .returned_work import consume_returns

    index, identities, _ = _saved_packets(db, audit_id, index_path)
    overrides = dict(response_paths or {})
    if overrides.keys() - set(identities):
        raise InvalidRequest("response-path override must name a packet in this saved group",
                             code="GROUP_INDEX", records=sorted(overrides.keys() - set(identities)))
    returns = [{"packet_id": row["packet_id"],
                "response_path": overrides.get(row["packet_id"], row.get("response_path")),
                "prior_response_paths": row.get("prior_response_paths", []),
                "response_override": row["packet_id"] in overrides,
                "reviewer": reviewer, "exposure": exposure, "exposure_note": exposure_note}
               for row in index["packets"]]
    return {"audit_id": audit_id, "group_index": str(resolve_path(index_path)),
            **consume_returns(db, returns)}


def reexport_group(db, *, audit_id, index_path, output):
    """Re-export saved membership. Current pending work never expands a saved group."""
    original, identities, _ = _saved_packets(db, audit_id, index_path)
    directory = resolve_path(output)
    index = {**original, "packets": []}
    prepared = [inspect_work(db, packet_id=identity) for identity in identities]
    original_rows = {row["packet_id"]: row for row in original["packets"]}
    deliveries = []
    for packet in prepared:
        row, delivery = _entry(db, packet, directory)
        original_row = original_rows[packet["packet_id"]]
        if "packet_reused" in original_row:
            row["packet_reused"] = original_row["packet_reused"]
        prior = list(original_row.get("prior_response_paths", []))
        if original_row["response_path"] != row["response_path"]:
            prior.append(original_row["response_path"])
        if prior:
            # Coordinator-only locations survive chained exports. Do not copy a
            # prior opinion into the files delivered to an independent context.
            row["prior_response_paths"] = list(dict.fromkeys(prior))
        index["packets"].append(row)
        deliveries.append(delivery)
    try:
        raw = _write_json(db, directory / INDEX_NAME, index)
        for packet, row in zip(prepared, index["packets"]):
            if (resolve_path(index_path) == directory / INDEX_NAME
                    and (Path(row["directory"]) / "coordinator-guidance.json").is_file()):
                # Reopen the delivered advice. Inspection may generate newer coordinator advice
                # after a submission; only a fresh export directory should receive that version.
                packet = {key: value for key, value in packet.items() if key != "coordinator_guidance"}
            write_artifacts(db, packet, row["directory"])
        return _finish(db, index, directory, deliveries, index_bytes=raw, reused=True)
    except (CoreError, OSError) as exc:
        error = _failure(exc, db, index, directory)
        if error is exc:
            raise
        raise error from exc


def prepare_group(db, *, audit_id, output, task_ids=None, exclude_task_ids=(), exclude_groups=(),
                  focus=None, max_packets=3, max_units=5, max_bytes=131072):
    """Collect distinct existing proof packets; exclusions apply only to this call."""
    if type(max_packets) is not int or not 1 <= max_packets <= 100:
        raise InvalidRequest("max_packets must be 1..100", code="WORK_LIMIT")
    if type(max_units) is not int or not 1 <= max_units <= 10:
        raise InvalidRequest("max_units must be 1..10", code="WORK_LIMIT")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
        raise InvalidRequest("max_bytes must be 1..1048576", code="WORK_LIMIT")
    excluded_packets, group_exclusions = set(), set()
    for path in exclude_groups:
        _, identities, assigned = _saved_packets(db, audit_id, path)
        excluded_packets.update(identities)
        group_exclusions.update(assigned)
    selection = {"task_ids": sorted(set(task_ids)) if task_ids is not None else None,
                 "exclude_task_ids": sorted(set(exclude_task_ids)), "exclude_packet_ids": sorted(excluded_packets),
                 "focus": focus, "max_packets": max_packets, "max_units": max_units, "max_bytes": max_bytes}
    directory = resolve_path(output)
    if (directory / INDEX_NAME).exists():
        previous, _, _ = _saved_packets(db, audit_id, directory / INDEX_NAME)
        if previous.get("selection") != selection:
            raise InvalidRequest("saved group has different selection; use a fresh output directory", code="OUTPUT_CONFLICT")
        return reexport_group(db, audit_id=audit_id, index_path=directory / INDEX_NAME, output=directory)
    view = derive_work(db, audit_id=audit_id, focus=focus)
    tasks = {task["id"]: task for task in view["tasks"]}
    eligible = {tid for tid, task in tasks.items() if task["role"] == "independent"}
    requested = eligible if task_ids is None else set(task_ids)
    if requested - eligible or set(exclude_task_ids) - tasks.keys():
        raise InvalidRequest("unknown or out-of-focus independent task IDs", code="WORK_TASK",
                             records=sorted((requested - eligible) | (set(exclude_task_ids) - tasks.keys())))
    excluded = set(exclude_task_ids) | (group_exclusions & tasks.keys())
    reasons = {tid: "satisfied" if tasks[tid]["state"] == "satisfied" else "excluded"
               for tid in requested if tasks[tid]["state"] == "satisfied" or tid in excluded}
    units = {unit["id"]: unit for unit in view["units"]}
    candidates = requested - reasons.keys()
    index = {"group_version": 1, "audit_id": audit_id, "mode": "independent", "selection": selection,
             "packets": [], "unassigned": [], "diagnostics": [],
             "coordinator_actions": view["coordinator_actions"]}
    deliveries, assigned, raw = [], set(), None
    try:
        while candidates - excluded and len(index["packets"]) < max_packets:
            prepared = prepare_stage(db, audit_id=audit_id, stage=2, mode="independent", focus=focus,
                task_ids=sorted(candidates - excluded) if task_ids is not None else None,
                exclude_task_ids=sorted(excluded), max_units=max_units, max_bytes=max_bytes)
            for diagnostic in prepared.get("diagnostics", []):
                if diagnostic not in index["diagnostics"]:
                    index["diagnostics"].append(diagnostic)
            if not prepared.get("prepared"):
                oversized = {tid for diag in prepared.get("diagnostics", []) if diag.get("code") == "OVERSIZED_CONTEXT"
                             for tid in units.get(diag["unit_id"], {}).get("pending_obligation_ids", [])}
                if oversized - excluded:
                    reasons.update({tid: "oversized_context" for tid in oversized & requested})
                    excluded.update(oversized)
                    continue
                break
            actual = set(prepared["assigned_task_ids"])
            if not actual or actual & assigned or not actual <= requested:
                raise InvalidRequest("group preparation did not select distinct requested tasks", code="WORK_TASK")
            row, delivery = _entry(db, prepared, directory)
            index["packets"].append(row)
            deliveries.append(delivery)
            assigned.update(actual)
            excluded.update(actual)
            # Persist packet identities before child export, including a recoverable interrupted prefix.
            index["unassigned"] = [{"task_id": tid, "reason": reasons.get(tid, "not_prepared")}
                                   for tid in sorted(requested - assigned)]
            raw = _write_json(db, directory / INDEX_NAME, index, previous=raw)
            write_artifacts(db, prepared, row["directory"])
        for tid in requested - assigned - reasons.keys():
            task = tasks[tid]
            reasons[tid] = ("fresh_independent_context" if task.get("requires_independent_context") else
                            "needs_coordinator" if task["blocker_ids"] else
                            "waiting_on_prerequisites" if task["waiting_on"] else
                            "packet_limit" if len(index["packets"]) >= max_packets else "no_useful_assignment")
        index["unassigned"] = [{"task_id": tid, "reason": reasons[tid]} for tid in sorted(requested - assigned)]
        return _finish(db, index, directory, deliveries, index_bytes=raw)
    except (CoreError, OSError) as exc:
        error = _failure(exc, db, index, directory)
        if error is exc:
            raise
        raise error from exc
