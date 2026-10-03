"""Independent review intake, judgment mapping, reconciliation, qualification (record-contract 5.1).

The worker's response bytes are preserved verbatim as a blob before anything
else is derived from them. The tool generates response and check identifiers,
audit and protocol fields, role ``independent``, and bindings; the coordinator
never edits an independent judgment. Unparseable or out-of-scope material is
kept as a ``needs_revision`` response with diagnostics, and ``review map``
later resolves SourceTargets and mis-scoped references to canonical targets
without changing kind, outcome, reasoning, or evidence.
"""
from __future__ import annotations

import base64
import re

from .acceptance import COMMAND_MODES, accept, apply_batch
from .canonical import digest, load_json_bytes, sha256_bytes
from .contract import (BATCH, CHECK_TARGETS, EDIT_CREATE, INTERMEDIATE_KINDS, MAPPING_REQUEST, SUBMISSION, WORKER_RESPONSE, Arr, Const, RequestVersion,
                       Hash, Obj, Str, validate_body, validate_shape)
from .errors import ConflictError, InvalidRequest
from .ids import new_id, valid_id
from .packets import independent_context_changes, load_packet
from .storage import Database
from .semantics import application

QUALIFICATION_REQUEST = Obj({"contract_version": RequestVersion(), "request_id": Str(nonempty=True), "edits": Arr(EDIT_CREATE),
                             "blobs": Arr(Obj({"sha256": Hash(), "encoding": Const("base64"), "data": Str()}))})
JUDGMENT_KEY_RE = re.compile(r"^judgment:(\d+)$")


def _judgment_ref(index: int) -> str:
    return f"judgment:{index}"


def _in_scope(target: dict, scope_targets: list, db_or_packet_parts) -> bool:
    if target in scope_targets:
        return True
    if target["collection"] == "parts":
        item_id = db_or_packet_parts.get(target["id"])
        return item_id is not None and {"collection": "items", "id": item_id} in scope_targets
    return False


def judgment_diagnostics(manifest: dict, response: dict, packet_records: dict) -> list:
    """Describe every pending cause where it is detected, without parsing human-readable reasons."""
    read_set = {(r["collection"], r["id"]) for r in manifest["read_set"]}
    pending = []
    for index, judgment in enumerate(response["judgments"]):
        target = judgment["target"]
        problems = []
        def problem(category, reason, **details):
            problems.append({"category": category, "reason": reason, **details})
        if "source_anchor_id" in target:
            problem("source_target_mapping", f"SourceTarget on anchor {target['source_anchor_id']} awaits mapping: "
                    f"{target['description']}")
            if ("anchors", target["source_anchor_id"]) not in read_set:
                problem("missing_neutral_source", f"source target anchor {target['source_anchor_id']} is not in "
                        "the packet read set", anchor_id=target["source_anchor_id"], source_target=True)
        else:
            if target["collection"] not in CHECK_TARGETS[judgment["kind"]]:
                problem("wrong_target_kind", f"kind {judgment['kind']} cannot target {target['collection']}")
            if (target["collection"], target["id"]) not in read_set:
                problem("target_not_in_packet", f"target {target['collection']}:{target['id']} is not in the packet read set")
            if manifest.get("review_basis") == "route_provided":
                assigned = {(t["target"]["collection"], t["target"]["id"], t["kind"])
                            for t in manifest.get("work", {}).get("tasks", [])}
                if (target["collection"], target["id"], judgment["kind"]) not in assigned:
                    problem("outside_route_assignment", "target is outside the exact supplied-route assignment")
        for anchor_id in judgment["evidence_refs"]:
            if ("anchors", anchor_id) not in read_set:
                problem("missing_neutral_source", f"evidence anchor {anchor_id} is not in the packet read set",
                        anchor_id=anchor_id)
        if problems:
            pending.append({"judgment_index": index, "reason": "; ".join(p["reason"] for p in problems),
                            "problems": problems})
    return pending


def classify_judgments(manifest: dict, response: dict, packet_records: dict) -> tuple[list, list]:
    """Keep the historical ``(resolved, pending)`` tuple interface for callers."""
    details = judgment_diagnostics(manifest, response, packet_records)
    # A missing SourceTarget anchor is extra advice; this judgment was already
    # pending for correspondence. Preserve the legacy explanation and policy.
    pending = [(row["judgment_index"], "; ".join(p["reason"] for p in row["problems"]
                if not p.get("source_target"))) for row in details]
    indexes = {i for i, _ in pending}
    resolved = [(i, row["target"]) for i, row in enumerate(response["judgments"]) if i not in indexes]
    return resolved, pending


def _covered_scope_diagnostics(db, packet, worker, details):
    """Add scope advice even when another problem already prevents resolution."""
    scope = (packet.get("declared_scope") or {}).get("targets") or packet["targets"]
    parts = _packet_parts(packet)
    by_index = {row["judgment_index"]: row for row in details}
    for index, judgment in enumerate(worker["judgments"]):
        target = judgment["target"]
        if "source_anchor_id" in target or _target_statement(db, target) is None:
            continue
        if _target_in_scope(db, target, scope, parts) and _target_in_scope(
                db, target, worker["covered_targets"], parts):
            continue
        problem = {"category": "judgment_out_of_covered_scope",
                   "reason": "target is outside the independent review's covered scope; the worker must resubmit"}
        row = by_index.setdefault(index, {"judgment_index": index, "reason": "", "problems": []})
        row["problems"].append(problem)
        row["reason"] = "; ".join(p["reason"] for p in row["problems"])
    return [by_index[index] for index in sorted(by_index)]


def _review_judgment_facts(db, packet, worker):
    """Use the same complete pending identities at intake, mapping and inspection."""
    details = _covered_scope_diagnostics(db, packet, worker,
        judgment_diagnostics(packet["_manifest"], worker, packet))
    pending = []
    for row in details:
        problems = [problem for problem in row["problems"] if not problem.get("source_target")]
        # Preserve the historical explanation when correspondence already failed,
        # while retaining the additional scope cause in the complete facts.
        ordinary = [problem for problem in problems if problem["category"] != "judgment_out_of_covered_scope"]
        pending.append((row["judgment_index"], "; ".join(problem["reason"] for problem in ordinary or problems)))
    indexes = {index for index, _ in pending}
    resolved = [(index, judgment["target"]) for index, judgment in enumerate(worker["judgments"])
                if index not in indexes]
    return resolved, pending, details


def mapping_input_changes(db, manifest):
    """Current original-packet guards enforced by response mapping."""
    from .acceptance import _guard_changes, _read_set_conflicts
    from .packets import source_context_digest
    changes = {"records": [], "relations": [], "source_context_changed": False}
    _read_set_conflicts(db, manifest, changes["records"])
    changes["relations"] = _guard_changes(db, manifest)
    changes["source_context_changed"] = manifest["source_context_digest"] != source_context_digest(db)
    return changes


def _check_body(audit_id: str, protocol_version: str, reviewer: str, judgment: dict, target: dict,
                response_id: str) -> dict:
    return {"audit_id": audit_id, "target": target, "kind": judgment["kind"], "role": "independent",
            "reviewer": reviewer, "protocol_version": protocol_version, "state": judgment["state"],
            "outcome": judgment["outcome"], "reasoning": judgment["reasoning"],
            "evidence_refs": list(judgment["evidence_refs"]), "conditions": list(judgment["conditions"]),
            "next_action": judgment["next_action"], "response_id": response_id, "supersedes": judgment["supersedes"]}


def _packet_parts(packet: dict) -> dict:
    return {r["ref"]["id"]: r["body"]["item_id"] for r in packet["records"] if r["ref"]["collection"] == "parts"}


def _target_statement(db: Database, target: dict):
    """Resolve an assessed local record to the statement whose proof contains it."""
    record = db.head(target["collection"], target["id"])
    visited = set()
    while record is not None and not record.retired and record.key not in visited:
        visited.add(record.key)
        if record.collection in ("items", "parts"):
            return record
        if record.collection == "arguments":
            ref = record.body["target"]
        elif record.collection == "groups":
            ref = {"collection": "arguments", "id": record.body["argument_id"]}
        elif record.collection == "uses":
            group_id = application(db, record)["group_id"]
            ref = ({"collection": "groups", "id": group_id} if group_id else record.body["to"])
        else:
            return None
        record = db.head(ref["collection"], ref["id"])
    return None


def _target_in_scope(db: Database, target: dict, scope: list, parts: dict) -> bool:
    statement = _target_statement(db, target)
    visited = set()
    while statement is not None and statement.key not in visited:
        visited.add(statement.key)
        if _in_scope(statement.ref, scope, parts):
            return True
        if statement.collection != "items" or statement.body["kind"] not in INTERMEDIATE_KINDS:
            return False
        statement = db.head("items", statement.body["owner_id"]) if statement.body["owner_id"] else None
    return False


def _anchors_overlap(left: dict, right: dict) -> bool:
    if (left["source_id"], left["source_version"]) != (right["source_id"], right["source_version"]):
        return False
    a, b = left["locator"], right["locator"]
    if all(type(value) is int for value in (a["start_line"], a["end_line"], b["start_line"], b["end_line"])):
        return max(a["start_line"], b["start_line"]) <= min(a["end_line"], b["end_line"])
    return left["excerpt_sha256"] == right["excerpt_sha256"]


def _audit_for(db: Database, packet: dict):
    scope = packet.get("declared_scope") or {}
    audit = db.head("audits", scope["audit_id"]) if scope.get("audit_id") else None
    if audit is None or audit.retired:
        targets = packet["targets"]
        candidates = [a for a in db.heads("audits")
                      if any(t in a.body["targets"] for t in targets) or a.body["mode"] == "full"]
        if not candidates:
            raise InvalidRequest("no live audit covers the packet targets", code="AUDIT_UNKNOWN")
        audit = sorted(candidates, key=lambda a: a.id)[0]
    return audit, scope


def _worker_diagnostics(response_bytes, packet):
    """Parse immutable worker bytes and retain independent causes in structured form."""
    details, worker, parsed = [], None, None
    try:
        parsed = load_json_bytes(response_bytes)
    except ValueError as exc:
        details.append({"category": "worker_response_invalid_json", "reason": f"response is not valid JSON: {exc}"})
    else:
        errors = validate_shape(WORKER_RESPONSE, parsed)
        if errors:
            details.extend({"category": "worker_response_invalid_shape", "reason": f"response shape: {e}"}
                           for e in errors)
        else:
            worker = parsed
    if (isinstance(parsed, dict) and valid_id(parsed.get("packet_id"))
            and parsed["packet_id"] != packet["packet_id"]):
        details.append({"category": "worker_packet_mismatch",
            "envelope_packet_id": packet["packet_id"], "worker_packet_id": parsed["packet_id"],
            "reason": f"worker response names packet {parsed['packet_id']} but the submission names {packet['packet_id']}"})
    if worker is not None:
        if not valid_id(worker["packet_id"]):
            details.append({"category": "worker_response_invalid_shape",
                "reason": "response packet_id is not a valid identifier"})
        scope = (packet.get("declared_scope") or {}).get("targets") or packet["targets"]
        parts = _packet_parts(packet)
        for target in worker["covered_targets"]:
            if not _in_scope(target, scope, parts):
                details.append({"category": "covered_target_out_of_scope", "target": target,
                    "reason": f"covered target {target['collection']}:{target['id']} lies outside the declared scope"})
    return worker, details


def plan_review_submission(db: Database, *, submission: dict, response_bytes: bytes) -> dict:
    """Derive the existing independent intake edits without owning a transaction."""
    errors = validate_shape(SUBMISSION, submission)
    if errors:
        raise InvalidRequest("invalid submission envelope", records=errors)
    if not isinstance(response_bytes, (bytes, bytearray)):
        raise InvalidRequest("the worker response must be supplied as bytes")
    response_bytes = bytes(response_bytes)
    packet_row = db.packet(submission["packet_id"])
    if packet_row is None:
        raise InvalidRequest(f"unknown packet {submission['packet_id']}", code="PACKET_UNKNOWN")
    manifest = packet_row["manifest"]
    if manifest["mode"] != "independent":
        raise InvalidRequest(f"review submit needs an independent packet; {submission['packet_id']} is a "
                             f"{manifest['mode']} packet", code="PACKET_MODE")
    qualification = db.head("qualifications", submission["qualification_id"])
    if qualification is None or qualification.retired:
        raise InvalidRequest(f"qualification {submission['qualification_id']} is not a live record")
    qualification_errors = validate_body("qualifications", qualification.body)
    if qualification_errors:
        raise InvalidRequest(f"qualification {qualification.id} does not satisfy the calibration policy",
                             records=qualification_errors)
    if qualification.body["reviewer"] != submission["reviewer"]:
        raise InvalidRequest(f"qualification {qualification.id} belongs to reviewer "
                             f"{qualification.body['reviewer']!r}, not {submission['reviewer']!r}")
    if not qualification.body["qualified"]:
        raise InvalidRequest(f"reviewer {submission['reviewer']!r} is not qualified under {qualification.id}")
    packet = load_packet(db, submission["packet_id"])
    audit, scope = _audit_for(db, packet)
    if qualification.body["protocol_version"] != audit.body["protocol_version"]:
        raise InvalidRequest(f"qualification protocol {qualification.body['protocol_version']} does not match audit "
                             f"protocol {audit.body['protocol_version']}", code="PROTOCOL_MISMATCH")
    blob_sha = sha256_bytes(response_bytes)
    request_digest = digest({"submission": submission, "response_sha256": blob_sha})
    worker, diagnostic_details = _worker_diagnostics(response_bytes, packet)
    diagnostics = [row["reason"] for row in diagnostic_details]
    resolved, pending, judgment_details = [], [], []
    covered, coverage_note, worker_exposure = [], "", {"status": "possible_exposure", "note": "response unreadable"}
    if worker is not None:
        parts = _packet_parts(packet)
        scope_targets = scope.get("targets") or packet["targets"]
        covered = [t for t in worker["covered_targets"] if _in_scope(t, scope_targets, parts)]
        coverage_note = worker["coverage_note"]
        worker_exposure = worker["exposure_report"]
        facts_resolved, facts_pending, judgment_details = _review_judgment_facts(db, packet, worker)
        if not diagnostics:
            resolved, pending = facts_resolved, facts_pending
    review_basis = manifest.get("review_basis", "source_only")
    if submission["exposure"] == review_basis and worker_exposure["status"] == "none_known":
        exposure, exposure_note = review_basis, submission["exposure_note"]
    else:
        exposure = "compromised"
        exposure_note = (f"coordinator: {submission['exposure']}"
                         + (f" ({submission['exposure_note']})" if submission["exposure_note"] else "")
                         + f"; worker: {worker_exposure['status']}"
                         + (f" ({worker_exposure['note']})" if worker_exposure.get("note") else ""))
    state = "accepted" if worker is not None and not diagnostics and not pending else "needs_revision"
    response_id = new_id("responses")
    response_body = {"audit_id": audit.id, "packet_id": submission["packet_id"], "reviewer": submission["reviewer"],
                     "qualification_id": qualification.id, "original_blob": blob_sha, "covered_targets": covered,
                     "coverage_note": coverage_note, "exposure": exposure, "exposure_note": exposure_note,
                     "state": state}
    edits = [{"op": "create", "collection": "responses", "id": response_id, "expected_version": None,
              "body": response_body}]
    annotations, checks = {}, []
    for index, target in resolved:
        judgment = worker["judgments"][index]
        check_id = new_id("checks")
        edits.append({"op": "create", "collection": "checks", "id": check_id, "expected_version": None,
                      "body": _check_body(audit.id, audit.body["protocol_version"], submission["reviewer"], judgment,
                                          target, response_id)})
        annotations[("checks", check_id)] = {"judgment_index": index}
        checks.append({"judgment_index": index, "check_id": check_id})
    warnings = list(diagnostics) + [f"judgment {i}: {reason}" for i, reason in pending]
    return {"request_digest": request_digest, "edits": edits, "blobs": [response_bytes],
            "annotations": annotations, "warnings": warnings, "response_id": response_id,
            "state": state, "exposure": exposure, "pending": pending, "diagnostics": diagnostics,
            "judgment_diagnostics": judgment_details, "diagnostic_details": diagnostic_details}


def submit_review(db: Database, *, submission: dict, response_bytes: bytes) -> dict:
    """Preserve a worker response and accept the shared independent intake plan."""
    planned = plan_review_submission(db, submission=submission, response_bytes=response_bytes)
    response_id, state, exposure = (planned[k] for k in ("response_id", "state", "exposure"))
    pending, diagnostics = planned["pending"], planned["diagnostics"]
    receipt = accept(db, request_id=submission["request_id"], request_digest=planned["request_digest"],
                     packet_id=submission["packet_id"], edits=planned["edits"], command="review_submit",
                     blobs=planned["blobs"], annotations=planned["annotations"], warnings=planned["warnings"])
    # An idempotent replay returns the original receipt; report from it rather than from fresh identifiers.
    response_ids = [c["id"] for c in receipt["changed"] if c["collection"] == "responses"]
    response_id = response_ids[0] if response_ids else response_id
    stored = db.head("responses", response_id)
    check_list = [{"judgment_index": c["judgment_index"], "check_id": c["id"], "version": c["version"]}
                  for c in receipt["changed"] if c["collection"] == "checks"]
    return {"receipt": receipt, "response_id": response_id, "state": stored.body["state"] if stored else state,
            "exposure": stored.body["exposure"] if stored else exposure, "checks": check_list,
            "pending": [{"judgment_index": i, "reason": r} for i, r in pending],
            "diagnostics": diagnostics, "judgment_diagnostics": planned["judgment_diagnostics"],
            "diagnostic_details": planned["diagnostic_details"]}


def _mapped_indexes(db: Database, response_id: str) -> set:
    mapped = set()
    for record in db.heads("identity_maps"):
        if record.body["reason"] != "response_mapping" or record.body["response_id"] != response_id:
            continue
        for entry in record.body["entries"]:
            match = JUDGMENT_KEY_RE.match(entry["old"])
            if match and entry["new_refs"]:
                mapped.add(int(match.group(1)))
    return mapped


def inspect_response(db: Database, *, response_id: str, limit: int = 100) -> dict:
    """Read current recovery facts without modifying receipts, responses or evidence.

    Detailed rows are bounded. Category counts summarize all pending judgments,
    so a blocker beyond the displayed page cannot turn into mapping-only advice.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise InvalidRequest("response inspection limit must be between 1 and 100")
    def bounded_changes(changes):
        if changes is None:
            return None
        records, relations = changes.get("records", []), changes.get("relations", [])
        return {**changes, "records": records[:limit], "relations": relations[:limit],
                "record_count": len(records), "relation_count": len(relations),
                "truncated": len(records) > limit or len(relations) > limit}
    response = db.head("responses", response_id)
    if response is None or response.retired:
        raise InvalidRequest(f"response {response_id} is not a live record", code="RESPONSE_UNKNOWN")
    body = response.body
    packet = load_packet(db, body["packet_id"])
    raw = db.get_blob(body["original_blob"])
    if raw is None:
        worker, details = None, [{"category": "worker_response_unavailable", "reason": "Original worker bytes are missing."}]
    else:
        worker, details = _worker_diagnostics(raw, packet)
    judgment_rows = [] if worker is None else _review_judgment_facts(db, packet, worker)[2]
    original = db.versions_of("responses", response_id)[0]
    original_commit = db.conn.execute("SELECT request_id FROM commits WHERE revision = ?", (original.revision,)).fetchone()
    mapped, check_rows = _mapped_indexes(db, response_id), []
    check_indexes = {}
    # Judgment annotations are immutable receipt facts, including automatically
    # resolved judgments and later mappings. Never infer an index from prose.
    receipts = {}
    for row in db.conn.execute("""SELECT id, MIN(revision) AS revision FROM record_versions
            WHERE collection = 'checks' AND json_extract(body_json, '$.response_id') = ? GROUP BY id""", (response_id,)):
        if row["revision"] not in receipts:
            saved = db.conn.execute("SELECT receipt_json FROM commits WHERE revision = ?", (row["revision"],)).fetchone()
            receipts[row["revision"]] = load_json_bytes(saved[0].encode("utf-8"))
        indexes = [changed["judgment_index"] for changed in receipts[row["revision"]]["changed"]
                   if changed["collection"] == "checks" and changed["id"] == row["id"]
                   and "judgment_index" in changed]
        check_indexes[row["id"]] = indexes[0] if indexes else None
        mapped.update(indexes)
    from .assessment import derive_full, key_of
    from .validation import State
    derivation, assessed = derive_full(db, audit_id=body["audit_id"])
    current_obligations = {row["id"]: row for row in assessed["obligations"]}
    assigned_tasks = []
    for task in packet["_manifest"].get("work", {}).get("tasks", []):
        current = current_obligations.get(task["id"])
        assigned_tasks.append({"task_id": task["id"], "target": task["target"], "kind": task["kind"],
            "role": task["role"], "current": None if current is None else
                {key: current[key] for key in ("required", "state", "satisfied", "freshness", "outcome", "check_refs")}})
    context_changes = independent_context_changes(State(db, []), packet["_manifest"])
    stale_refs = []
    for check_id, index in check_indexes.items():
        check = db.head("checks", check_id)
        if check is None or check.retired:
            check_rows.append({"check_id": check_id, "judgment_index": index, "retired": True,
                               "eligible_independent_evidence": False})
            continue
        info = dict(derivation.judgment_info(check))
        changes = derivation.judgment_changes.get(key_of(check.pinned))
        basis_usable = derivation.independent_usable(info)
        eligible = (info["state"] == "complete" and info["substantive"] and info["freshness"] == "current"
                    and not info["superseded"] and basis_usable)
        if changes and not info["superseded"]:
            stale_refs.append(check.pinned)
        check_rows.append({**info, "judgment_index": index, "changes": bounded_changes(changes),
                           "independence_basis_usable": basis_usable, "eligible_independent_evidence": eligible})
    pending = [row for row in judgment_rows if row["judgment_index"] not in mapped]
    pending_indexes = sorted(set(range(len(worker["judgments"]))) - mapped) if worker else []
    mapping_changes = {"records": [], "relations": [], "source_context_changed": False}
    if pending_indexes:
        # Mapping still enforces the original packet's raw guards, including
        # older direct-review packets with no neutral work-context binding.
        mapping_changes = mapping_input_changes(db, packet["_manifest"])
    categories = {}
    for row in pending:
        for problem in row["problems"]:
            categories.setdefault(problem["category"], set()).add(row["judgment_index"])
    qualification = db.head("qualifications", body["qualification_id"])
    info = {"revision": db.max_revision(), "response_id": response_id, "response_ref": response.pinned,
        "packet_id": body["packet_id"], "audit_id": body["audit_id"], "state": body["state"],
        "original_request_id": original_commit["request_id"], "original_response_ref": original.pinned,
        "original_blob_sha256": body["original_blob"], "reviewer": body["reviewer"],
        "qualification_id": body["qualification_id"],
        "qualification": None if qualification is None or qualification.retired else
            {"ref": qualification.pinned, **qualification.body},
        "exposure": body["exposure"], "exposure_note": body["exposure_note"],
        "judgment_count": 0 if worker is None else len(worker["judgments"]),
        "mapped_judgment_indexes": sorted(mapped)[:limit], "mapped_judgment_count": len(mapped),
        "pending_judgment_indexes": pending_indexes[:limit], "pending_judgment_count": len(pending_indexes),
        "judgment_diagnostics": pending[:limit], "diagnostic_details": details[:limit],
        "diagnostic_categories": sorted({row["category"] for row in details}),
        "problem_summary": [{"category": category, "judgment_indexes": sorted(indexes)[:limit],
                             "judgment_count": len(indexes)} for category, indexes in sorted(categories.items())],
        "context_changes": bounded_changes(context_changes), "mapping_input_changes": bounded_changes(mapping_changes),
        "stale_check_refs": stale_refs[:limit],
        "stale_check_count": len(stale_refs), "checks": check_rows[:limit], "check_count": len(check_rows),
        "eligible_independent_check_count": sum(row["eligible_independent_evidence"] for row in check_rows),
        "assigned_task_statuses": assigned_tasks[:limit], "assigned_task_count": len(assigned_tasks),
        "details_limit": limit, "details_truncated": any(len(rows) > limit for rows in
            (mapped, pending_indexes, pending, details, check_rows, stale_refs, assigned_tasks))}
    # Recovery needs complete overlapping causes. Public rows above are only a
    # bounded view and cannot establish that a displayed candidate has no blocker.
    info["recovery"] = response_recovery({
        **{key: info[key] for key in ("packet_id", "response_id", "state", "exposure",
                                     "stale_check_count", "eligible_independent_check_count")},
        "judgment_diagnostics": pending, "diagnostic_details": details,
        "context_changes": context_changes, "mapping_input_changes": mapping_changes,
    }, complete=True, limit=limit)
    return info


def packet_pairing_recovery(envelope_packet_id, worker_packet_id) -> dict:
    """A pair of valid, conflicting identities does not identify the faulty input."""
    return {"operation": "inspect_assignment", "reason_code": "PACKET_MISMATCH",
        "envelope_packet_id": envelope_packet_id, "worker_packet_id": worker_packet_id,
        "message": "Compare the saved assignment, delivery artifacts and actual provenance to resolve the conflicting packet identities. "
                   "If the envelope is wrong, correct it with a fresh request ID and preserve worker bytes; "
                   "if the authored response is wrong, obtain its author's correction. Do not choose a packet by folder name or recency."}


def response_recovery(info: dict, *, complete: bool = False, limit: int = 100) -> list:
    """Derive remedies only from explicitly complete facts, then bound their display.

    Intake plans and internal inspection facts are complete. Public inspection
    rows may be shortened; callers must not reconstruct eligibility from them.
    Advice never grants evidence eligibility.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise InvalidRequest("recovery limit must be between 1 and 100")
    if complete is not True or info.get("details_truncated"):
        return [{"operation": "inspect_saved_response", "reason_code": "incomplete_recovery_facts",
            "message": "Inspect the saved response for recovery based on complete current facts; shortened diagnostics do not establish safe mapping indexes.",
            "judgment_indexes": [], "judgment_count": 0, "judgment_indexes_truncated": False,
            **{key: info[key] for key in ("packet_id", "response_id") if key in info}}]
    actions = []
    summary = {row["category"]: {**row, "judgment_indexes": list(row["judgment_indexes"])}
               for row in info.get("problem_summary", [])}
    categories = set(summary) | set(info.get("diagnostic_categories", ()))
    categories.update(row["category"] for row in info.get("diagnostic_details", []))
    # Also accept unbounded intake diagnostics before a response has been stored.
    for row in info.get("judgment_diagnostics", []):
        for problem in row["problems"]:
            category = problem["category"]
            categories.add(category)
            if category not in summary:
                summary[category] = {"judgment_indexes": []}
            if row["judgment_index"] not in summary[category]["judgment_indexes"]:
                summary[category]["judgment_indexes"].append(row["judgment_index"])
    def action(operation, reason_code, message, causes=(), *, indexes=None):
        if indexes is None:
            indexes = sorted({index for category in causes for index in summary.get(category, {}).get("judgment_indexes", [])})
        actions.append({"operation": operation, "reason_code": reason_code, "message": message,
            "judgment_indexes": indexes[:limit], "judgment_count": len(indexes),
            "judgment_indexes_truncated": len(indexes) > limit,
            **{key: info[key] for key in ("packet_id", "response_id") if key in info}})
    mapping = {"source_target_mapping", "target_not_in_packet"} & categories
    pairing = next((row for row in info.get("diagnostic_details", [])
                    if row["category"] == "worker_packet_mismatch"), None)
    pairing_unresolved = "worker_packet_mismatch" in categories
    if pairing_unresolved:
        pair = packet_pairing_recovery((pairing or {}).get("envelope_packet_id", info.get("packet_id")),
                                       (pairing or {}).get("worker_packet_id"))
        action(pair.pop("operation"), pair.pop("reason_code"), pair.pop("message"))
        actions[-1].update({key: value for key, value in pair.items() if valid_id(value)})
    corrections = categories & {"wrong_target_kind", "worker_response_invalid_json", "worker_response_invalid_shape"}
    if not pairing_unresolved:
        corrections |= categories & {"outside_route_assignment", "judgment_out_of_covered_scope", "covered_target_out_of_scope"}
    changes = info.get("context_changes") or {}
    changed = bool(changes.get("records") or changes.get("relations") or info.get("stale_check_count"))
    mapping_changes = info.get("mapping_input_changes") or {}
    mapping_blocked = bool(mapping_changes.get("records") or mapping_changes.get("relations")
                           or mapping_changes.get("source_context_changed"))
    if changed and not pairing_unresolved:
        action("inspect_current_evidence", "changed_scientific_inputs",
            "Inspect current obligations and applicable replacement reviews first. Renew affected examination only where current required evidence is still missing; preserve and compare unresolved concerns in this saved response.")
    elif mapping_blocked and not pairing_unresolved:
        action("inspect_current_evidence", "original_mapping_inputs_changed",
            "Inspect original packet changes, current obligations and applicable replacement reviews. Existing guards prevent mapping this unchanged response; renew affected examination only where current required evidence is still missing.")
    if corrections:
        action("author_response_correction", "worker_authored_response_problem",
            "Obtain an authored correction for the identified response fields or scope; retain the original response.", corrections)
    if "missing_neutral_source" in categories and not pairing_unresolved:
        action("extend_neutral_source", "missing_neutral_source",
            "Capture the missing source and extend the neutral context; the examiner must examine it and author a response for the extended packet.",
            ("missing_neutral_source",))
    if info.get("exposure") == "compromised":
        action("obtain_independent_review", "compromised_independence",
            "Preserve this response and obtain a genuinely separate independent examination with actual provenance.")
    if "worker_response_unavailable" in categories:
        action("recover_original_response", "worker_response_unavailable", "Recover the exact original worker bytes before further integration.")
    global_blockers = {row["category"] for row in info.get("diagnostic_details", [])} | set(info.get("diagnostic_categories", ()))
    blocked_indexes = {index for category in corrections | {"missing_neutral_source"}
                       for index in summary.get(category, {}).get("judgment_indexes", [])}
    mappable = sorted({index for category in mapping for index in summary.get(category, {}).get("judgment_indexes", [])}
                      - blocked_indexes)
    if mappable and not pairing_unresolved and not changed and not mapping_blocked and not global_blockers:
        action("map_saved_response", "source_target_correspondence",
            "Map these saved unchanged judgments to their source-backed targets. Other unresolved judgments keep the whole response pending.",
            indexes=mappable)
    if not actions and info.get("state") == "accepted":
        if info.get("eligible_independent_check_count", 0):
            action("inspect_reconciliation", "current_independent_evidence",
                "Compare the current independent evidence with primary work and inspect required reconciliation and remaining audit work.")
        else:
            action("inspect_remaining_work", "accepted_response_not_completion",
                "Inspect remaining audit work and check eligibility; response acceptance alone does not establish a current completed examination.")
    elif not actions and info.get("state") == "needs_revision":
        action("inspect_saved_response", "unresolved_saved_response",
            "Inspect the retained response and its current diagnostics before commissioning more work.")
    return actions


def map_response(db: Database, *, mapping: dict) -> dict:
    """Map source identities or explicitly reuse equivalent examined routine mathematics."""
    errors = validate_shape(MAPPING_REQUEST, mapping)
    if errors:
        raise InvalidRequest("invalid mapping request", records=errors)
    if not mapping["entries"]:
        raise InvalidRequest("mapping request lists no entries")
    prior = db.commit_by_request(mapping["request_id"])
    if prior is not None:
        if prior["request_digest"] != digest(mapping):
            raise InvalidRequest("mapping request ID was already used for different input", code="REQUEST_ID_REUSED")
        receipt = load_json_bytes(prior["receipt_json"].encode("utf-8"))
        return {"receipt": receipt, "response_id": mapping["response_id"],
                "state": db.head("responses", mapping["response_id"]).body["state"]}
    response = db.head("responses", mapping["response_id"])
    if response is None or response.retired:
        raise InvalidRequest(f"response {mapping['response_id']} is not a live record")
    accepted_reuse = response.body["state"] == "accepted"
    packet_row = db.packet(mapping["packet_id"])
    if packet_row is None:
        raise InvalidRequest(f"unknown packet {mapping['packet_id']}", code="PACKET_UNKNOWN")
    if packet_row["manifest"]["mode"] not in COMMAND_MODES["review_map"]:
        raise InvalidRequest(f"review map needs a packet in mode {list(COMMAND_MODES['review_map'])}",
                             code="PACKET_MODE")
    raw = db.get_blob(response.body["original_blob"])
    if raw is None:
        raise InvalidRequest(f"response {response.id} original bytes are missing")
    try:
        worker = load_json_bytes(raw)
    except ValueError as exc:
        raise InvalidRequest(f"response {response.id} bytes are not valid JSON; the worker must resubmit: {exc}",
                             code="RESPONSE_UNREADABLE") from exc
    if validate_shape(WORKER_RESPONSE, worker):
        raise InvalidRequest(f"response {response.id} does not follow the worker response shape; the worker must "
                             "resubmit", code="RESPONSE_UNREADABLE")
    original_packet = load_packet(db, response.body["packet_id"])
    from .validation import State
    context_changes = independent_context_changes(State(db, []), original_packet["_manifest"])
    if context_changes["records"] or context_changes["relations"]:
        raise ConflictError("original independent source or applicable setup changed; obtain a renewed review",
                            records=[context_changes])
    original_records = {(r["ref"]["collection"], r["ref"]["id"]): r["body"]
                        for r in original_packet["records"]}
    original_scope = (original_packet.get("declared_scope") or {}).get("targets") or original_packet["targets"]
    original_parts = _packet_parts(original_packet)
    if worker["packet_id"] != response.body["packet_id"] or any(
            not _in_scope(t, original_scope, original_parts) for t in worker["covered_targets"]):
        raise InvalidRequest("the original response's packet or covered scope is invalid; the worker must resubmit",
                             code="RESPONSE_SCOPE")
    mapping_read_set = {(r["collection"], r["id"]) for r in packet_row["manifest"]["read_set"]}
    resolved, pending, _ = _review_judgment_facts(db, original_packet, worker)
    pending_indexes = {i for i, _ in pending}
    already = _mapped_indexes(db, response.id)
    mapped_targets = set()
    for record in db.heads("identity_maps"):
        if record.body["reason"] == "response_mapping" and record.body["response_id"] == response.id:
            for entry in record.body["entries"]:
                match = JUDGMENT_KEY_RE.match(entry["old"])
                if match:
                    mapped_targets.update((int(match.group(1)), r["collection"], r["id"]) for r in entry["new_refs"])
    for index, target in resolved:
        mapped_targets.add((index, target["collection"], target["id"]))
    audit = db.head("audits", response.body["audit_id"])
    if audit is None:
        raise InvalidRequest(f"audit {response.body['audit_id']} is missing")
    qualification = db.head("qualifications", response.body["qualification_id"])
    if (qualification is None or qualification.retired or not qualification.body["qualified"]
            or validate_body("qualifications", qualification.body)
            or qualification.body["reviewer"] != response.body["reviewer"]
            or qualification.body["protocol_version"] != audit.body["protocol_version"]):
        raise InvalidRequest("the original response lacks a valid qualification for this audit; "
                             "obtain a qualified review before mapping", code="QUALIFICATION_INVALID")
    edits, entries, check_list, annotations = [], [], [], {}
    seen = set()
    for index, entry in enumerate(mapping["entries"]):
        j = entry["judgment_index"]
        where = f"entries/{index}"
        if j >= len(worker["judgments"]):
            errors.append(f"{where}: judgment {j} does not exist (response has {len(worker['judgments'])})")
            continue
        if j not in pending_indexes and not accepted_reuse:
            errors.append(f"{where}: judgment {j} was already resolved at submission")
            continue
        if (j in already and not accepted_reuse) or j in seen:
            errors.append(f"{where}: judgment {j} is already mapped")
            continue
        seen.add(j)
        judgment = worker["judgments"][j]
        target = entry["target"]
        if (j, target["collection"], target["id"]) in mapped_targets:
            errors.append(f"{where}: judgment {j} already maps to this exact target")
            continue
        if original_packet["_manifest"].get("review_basis") == "route_provided":
            assigned = {(t["target"]["collection"], t["target"]["id"], t["kind"])
                        for t in original_packet["_manifest"].get("work", {}).get("tasks", [])}
            if (target["collection"], target["id"], judgment["kind"]) not in assigned:
                errors.append(f"{where}: target was not in the supplied-route review")
                continue
        if target["collection"] not in CHECK_TARGETS[judgment["kind"]]:
            errors.append(f"{where}: kind {judgment['kind']} cannot target {target['collection']}")
            continue
        head = db.head(target["collection"], target["id"])
        if head is None or head.retired:
            errors.append(f"{where}: target {target['collection']}:{target['id']} is not a live record")
            continue
        if (target["collection"], target["id"]) not in mapping_read_set:
            errors.append(f"{where}: target {target['collection']}:{target['id']} is not in the mapping packet read set")
            continue
        if not _target_in_scope(db, target, original_scope, original_parts) or not _target_in_scope(
                db, target, worker["covered_targets"], original_parts):
            errors.append(f"{where}: target is outside the original independent review's covered scope")
            continue
        evidence = list(judgment["evidence_refs"])
        if "source_anchor_id" in judgment["target"]:
            evidence.append(judgment["target"]["source_anchor_id"])
        if any(("anchors", anchor_id) not in original_records for anchor_id in evidence):
            errors.append(f"{where}: judgment refers to evidence absent from the original independent packet; "
                          "the worker must review a source extension and resubmit")
            continue
        target_anchor_ids = (head.body.get("evidence_refs") or
                             [p["anchor_id"] for p in head.body.get("passages", [])])
        target_anchors = [db.head("anchors", aid) for aid in target_anchor_ids]
        if not any(anchor is not None and _anchors_overlap(original_records[("anchors", aid)], anchor.body)
                   for aid in evidence for anchor in target_anchors):
            errors.append(f"{where}: mapped target has no source passage overlapping the worker's reviewed evidence")
            continue
        check_id = new_id("checks")
        edits.append({"op": "create", "collection": "checks", "id": check_id, "expected_version": None,
                      "body": _check_body(audit.id, audit.body["protocol_version"], response.body["reviewer"], judgment,
                                          target, response.id)})
        annotations[("checks", check_id)] = {"judgment_index": j}
        entries.append({"old": _judgment_ref(j), "new_refs": [target], "rationale": entry["rationale"]})
        check_list.append({"judgment_index": j, "check_id": check_id})
    if errors:
        raise InvalidRequest("mapping rejected", records=errors)
    map_id = new_id("identity_maps")
    edits.append({"op": "create", "collection": "identity_maps", "id": map_id, "expected_version": None,
                  "body": {"reason": "response_mapping", "source_blob": response.body["original_blob"],
                           "response_id": response.id, "entries": entries, "reviewer": mapping["reviewer"],
                           "note": ""}})
    remaining = pending_indexes - already - seen
    completes = not remaining
    if completes and not accepted_reuse:
        body = dict(response.body)
        body["state"] = "accepted"
        edits.append({"op": "replace", "collection": "responses", "id": response.id,
                      "expected_version": response.version, "body": body})
    receipt = accept(db, request_id=mapping["request_id"], request_digest=digest(mapping),
                     packet_id=mapping["packet_id"], edits=edits, command="review_map", annotations=annotations,
                     scope_exempt={("responses", response.id)}, required_packet_ids=(response.body["packet_id"],))
    stored = db.head("responses", response.id)
    return {"receipt": receipt, "response_id": response.id, "state": stored.body["state"],
            "identity_map_id": map_id,
            "checks": [{"judgment_index": c["judgment_index"], "check_id": c["id"], "version": c["version"]}
                       for c in receipt["changed"] if c["collection"] == "checks"],
            "remaining": sorted(remaining)}


def reconcile(db: Database, *, batch: dict) -> dict:
    """Record reconciliations with their successor checks and finding updates (reconcile packet)."""
    errors = validate_shape(BATCH, batch)
    if errors:
        raise InvalidRequest("invalid edit envelope", records=errors)
    return accept(db, request_id=batch["request_id"], request_digest=digest(batch), packet_id=batch["packet_id"],
                  edits=batch["edits"], command="reconcile")


def compare(db: Database, *, batch: dict) -> dict:
    """Record source-versus-record observations for a packet (compare command)."""
    return apply_batch(db, batch, command="compare")


def record_qualification(db: Database, *, receipt: dict) -> dict:
    """Store a qualification receipt: qualification records plus their evidence blobs (packetless)."""
    errors = validate_shape(QUALIFICATION_REQUEST, receipt)
    if errors:
        raise InvalidRequest("invalid qualification receipt", records=errors)
    blobs = []
    for index, blob in enumerate(receipt["blobs"]):
        try:
            data = base64.b64decode(blob["data"], validate=True)
        except (ValueError, TypeError) as exc:
            raise InvalidRequest(f"blobs/{index}: data is not valid base64") from exc
        if sha256_bytes(data) != blob["sha256"]:
            raise InvalidRequest(f"blobs/{index}: sha256 does not match the decoded data")
        blobs.append(data)
    for index, edit in enumerate(receipt["edits"]):
        if edit["collection"] != "qualifications":
            errors.append(f"edits/{index}: qualification receipts create qualifications only")
    if errors:
        raise InvalidRequest("qualification receipt rejected", records=errors)
    return accept(db, request_id=receipt["request_id"], request_digest=digest(receipt), packet_id=None,
                  edits=receipt["edits"], command="qualification", blobs=blobs)


__all__ = ["QUALIFICATION_REQUEST", "classify_judgments", "judgment_diagnostics", "inspect_response", "response_recovery", "packet_pairing_recovery",
           "compare", "map_response", "reconcile", "record_qualification", "submit_review"]
