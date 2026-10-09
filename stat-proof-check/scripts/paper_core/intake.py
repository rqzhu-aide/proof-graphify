"""Optional read-only splitting of an already authored native primary response.

The saved assignment supplies task identity. The normal submission path still
decides scientific validity, scope and freshness; this helper supplies no work.
"""
from __future__ import annotations

from . import PACKET_VERSION
from .canonical import canonical_bytes, load_json_bytes, sha256_bytes
from .contract import WORK_CHECK, WORK_COMPARISON, WORK_PRIMARY_RESPONSE, validate_shape
from .controller import DIAGNOSTIC_LIMIT, RESPONSE_LIMIT
from .errors import InvalidRequest

_MISSING = object()


def _assignment_tasks(db, packet_id):
    """Validate only the saved assignment fields consumed by this helper."""
    if not isinstance(packet_id, str) or not packet_id.strip():
        raise InvalidRequest("packet_id must be nonempty text", code="PACKET_INVALID")
    saved = db.packet(packet_id)
    if saved is None:
        raise InvalidRequest(f"unknown packet {packet_id}", code="PACKET_UNKNOWN")
    manifest = saved.get("manifest")
    if (not isinstance(manifest, dict) or type(manifest.get("packet_version")) is not int
            or manifest["packet_version"] != PACKET_VERSION
            or not isinstance(manifest.get("work"), dict)):
        raise InvalidRequest("intake needs a version-2 work assignment", code="WORK_PACKET_REQUIRED")
    work = manifest["work"]
    if saved.get("mode") != "primary" or manifest.get("mode") != "primary" or work.get("mode") != "primary":
        raise InvalidRequest("intake supports native primary responses only", code="PACKET_MODE")
    if manifest.get("packet_id") != packet_id:
        raise InvalidRequest("saved assignment packet identity is inconsistent", code="PACKET_INVALID")
    rows = work.get("tasks")
    if not isinstance(rows, list):
        raise InvalidRequest("saved assignment has no task array", code="WORK_PACKET_INVALID")
    tasks = {}
    for index, task in enumerate(rows):
        tid = task.get("id") if isinstance(task, dict) else None
        if (not isinstance(tid, str) or not tid.strip() or tid in tasks
                or task.get("role") != "primary" or task.get("action") not in ("check", "compare_source")):
            raise InvalidRequest("saved primary assignment has an invalid or duplicate task",
                                 code="WORK_PACKET_INVALID", records=[f"/work/tasks/{index}"])
        tasks[tid] = task
    return tasks


def _shape_diagnostic(path, reason, errors):
    result = {"path": path, "reason": reason, "errors": errors[:DIAGNOSTIC_LIMIT]}
    if len(errors) > DIAGNOSTIC_LIMIT:
        result["error_count"] = len(errors)
    return result


def intake_response(db, *, packet_id, response_bytes=None, response=_MISSING):
    """Return a native candidate, diagnostics and unchanged deferred originals.

    Supply either exact response bytes or a parsed JSON value. Malformed bytes
    yield a local diagnostic and their digest/size, without copying the file's
    bytes into diagnostics. The caller preserves the original file. Parsed rows
    deferred by splitting retain their original JSON Pointer and content.

    This function never writes the database or mutates either caller input.
    Invalid saved assignments or ambiguous API arguments raise InvalidRequest;
    native response defects are returned as local diagnostics.
    """
    if response_bytes is not None and response is not _MISSING:
        raise InvalidRequest("supply response_bytes or response, not both")
    if response_bytes is None and response is _MISSING:
        raise InvalidRequest("supply response_bytes or a parsed response")
    if response_bytes is not None and not isinstance(response_bytes, bytes):
        raise InvalidRequest("response_bytes must be bytes")
    tasks = _assignment_tasks(db, packet_id)
    result = {"response": None, "diagnostics": [], "deferred": [], "selected_task_ids": []}
    if response_bytes is not None:
        result.update(source_sha256=sha256_bytes(response_bytes), source_size=len(response_bytes))
        if len(response_bytes) > RESPONSE_LIMIT:
            result["diagnostics"].append({"path": "/", "reason": "input_too_large", "limit": RESPONSE_LIMIT})
            return result
        try:
            response = load_json_bytes(response_bytes)
            # Escaped lone surrogates and exponent overflow can parse but cannot
            # be emitted as finite UTF-8 JSON. Leave their original bytes local.
            canonical_bytes(response)
        except (ValueError, UnicodeError, RecursionError) as exc:
            result["diagnostics"].append({"path": "/", "reason": "json_invalid", "message": str(exc)})
            return result
    else:
        # A parsed input must represent JSON without implicit tuple/key coercion.
        try:
            raw = canonical_bytes(response)
            parsed = load_json_bytes(raw)
            if parsed != response:
                raise ValueError("parsed response must contain JSON objects and arrays")
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise InvalidRequest(f"parsed response is not a JSON value: {exc}", code="JSON_INVALID") from exc
        if len(raw) > RESPONSE_LIMIT:
            result["diagnostics"].append({"path": "/", "reason": "input_too_large", "limit": RESPONSE_LIMIT})
            return result
        response = parsed

    def defer_whole(diagnostic):
        result["diagnostics"].append(diagnostic)
        result["deferred"] = [{"path": "/", "original": response}]
        return result

    if not isinstance(response, dict):
        return defer_whole({"path": "/", "reason": "response_not_object"})
    if response.get("packet_id") != packet_id:
        return defer_whole({"path": "/packet_id", "reason": "original_packet_required"})
    if set(response) != set(WORK_PRIMARY_RESPONSE.fields) or not isinstance(response.get("results"), list):
        return defer_whole(_shape_diagnostic("/", "repair_response_shape",
                                            validate_shape(WORK_PRIMARY_RESPONSE, response)))

    # An ancillary structure defect needs explicit local repair, not a guessed
    # dependency partition. Retain the complete response, including all results.
    ancillary_errors = []
    for field in ("coverage", "findings"):
        ancillary_errors.extend(validate_shape(WORK_PRIMARY_RESPONSE.fields[field], response[field], f"/{field}"))
    if ancillary_errors:
        return defer_whole(_shape_diagnostic("/", "repair_ancillary_shape", ancillary_errors))

    counts = {}
    for row in response["results"]:
        tid = row.get("task_id") if isinstance(row, dict) else None
        if isinstance(tid, str) and tid in tasks:
            counts[tid] = counts.get(tid, 0) + 1
    # The parser has already detached every input object. Keep those authored
    # values without recursively copying malformed, deeply nested rows.
    candidate = {"packet_id": response["packet_id"], "results": [], "coverage": [], "findings": []}
    selected_checks = set()

    def defer(path, row, reason, **details):
        result["diagnostics"].append({"path": path, "reason": reason, **details})
        result["deferred"].append({"path": path, "original": row})

    for index, row in enumerate(response["results"]):
        path = f"/results/{index}"
        tid = row.get("task_id") if isinstance(row, dict) else None
        if not isinstance(row, dict):
            defer(path, row, "row_not_object")
        elif not isinstance(tid, str) or not tid.strip():
            defer(path, row, "missing_or_invalid_task_id")
        elif tid not in tasks:
            defer(path, row, "unassigned_task", task_id=tid)
        elif counts[tid] != 1:
            defer(path, row, "ambiguous_same_task", task_id=tid)
        else:
            check = tasks[tid]["action"] == "check"
            errors = validate_shape(WORK_CHECK if check else WORK_COMPARISON, row, path)
            if errors:
                diagnostic = _shape_diagnostic(path, "repair_row_shape", errors)
                defer(path, row, diagnostic.pop("reason"), task_id=tid,
                      **{key: value for key, value in diagnostic.items() if key != "path"})
            else:
                candidate["results"].append(row)
                result["selected_task_ids"].append(tid)
                if check:
                    selected_checks.add(tid)

    for field, links in (("coverage", "check_task_ids"), ("findings", "related_task_ids")):
        candidate[field] = []
        for index, row in enumerate(response[field]):
            absent = [tid for tid in row[links] if tid not in selected_checks]
            if absent:
                defer(f"/{field}/{index}", row, "linked_result_deferred", task_ids=absent)
            else:
                candidate[field].append(row)

    if not any(candidate[field] for field in ("results", "coverage", "findings")):
        result["diagnostics"].append({"path": "/", "reason": "no_usable_work"})
        if not result["deferred"]:
            result["deferred"].append({"path": "/", "original": response})
        return result
    result["response"] = candidate
    return result
