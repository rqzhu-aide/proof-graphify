"""Prepare and record a finite primary examination using the existing work API."""
from __future__ import annotations

import json
from copy import deepcopy

from .audit_compatibility import validate_assignment_audit
from .bindings import task_binding_changes
from .controller import _assignment_assistance, submit_work
from .errors import CoreError, InvalidRequest
from .packets import independent_context_changes, prepare_assignment
from .validation import State
from .work import derive_work, select_assignment

GLOBAL_KINDS = frozenset(("global_consistency", "adversarial", "method_interface"))


def _preparation_feedback(result):
    """Coordinator feedback only; packet and response artifacts keep their shapes."""
    if not result.get("prepared"):
        note = "No worker packet or response scaffold was produced. Use the returned reason and diagnostics."
        if any(row.get("code") == "OVERSIZED_CONTEXT" for row in result.get("diagnostics", [])):
            note += (" The size diagnostic can guide an explicit larger permitted --max-bytes cap "
                     "or a coherent smaller selection; do not repeat the same preparation.")
        return {**result, "preparation_note": note}
    if result.get("reused"):
        return {**result, "preparation_note":
                "This is the same saved assignment, not another task. Reuse its saved work, or select "
                "distinct ready work while excluding assigned task IDs. Repeating generic preparation "
                "does not advance the queue; retain any conditional prerequisites."}
    return result


def _in_stage(task, stage, mode):
    role = {"primary": "primary", "independent": "independent", "reconcile": "coordinator"}[mode]
    # Selected cross-proof questions are primary work too. Stage 2's explicit
    # global mode remains a compatible entry point for an already saved task.
    return task["role"] == role and (stage == 1 or mode != "primary" or task["kind"] in GLOBAL_KINDS)


def stage_status(db, *, audit_id, stage=1, mode=None, focus=None, revision=None):
    """Account for this stage's work without another readiness or completion gate."""
    view = derive_work(db, audit_id=audit_id, focus=focus, revision=revision)
    modes = ("primary",) if stage == 1 else ((mode,) if mode else ("independent", "reconcile", "primary"))
    tasks = [task for task in view["tasks"] if any(_in_stage(task, stage, m) for m in modes)]
    return {"stage": stage, "audit_id": audit_id, "revision": view["revision"],
            "analysis_complete": view["analysis_complete"], "tasks": tasks,
            "required": sum(t["required"] for t in tasks),
            "performed": sum(t["required"] and t["state"] == "satisfied" for t in tasks),
            "remaining_task_ids": [t["id"] for t in tasks if t["required"] and t["state"] != "satisfied"],
            "coordinator_actions": view["coordinator_actions"]}


def _reuse_assignment(db, *, audit_id, mode, selection, max_bytes):
    assigned = set(selection["assigned_task_ids"])
    state = State(db, [])
    prior_reconciliations = {}
    if mode == "reconcile" and db.head("audits", audit_id).body["protocol_version"] == "coherent-proof-audit/1":
        targets = [task["target"] for task in selection["tasks"]]
        for record in sorted(db.heads("reconciliations"), key=lambda r: (r.revision, r.id)):
            if record.body["audit_id"] == audit_id and record.body["target"] in targets:
                target = record.body["target"]
                prior_reconciliations[(target["collection"], target["id"])] = record.pinned
    rows = db.conn.execute(
        "SELECT packet_id FROM packets WHERE mode = ? "
        "AND json_extract(manifest_json, '$.work.audit_id') = ? ORDER BY created_at DESC, packet_id DESC",
        (mode, audit_id))
    for row in rows:
        saved = db.packet(row["packet_id"])
        manifest = saved["manifest"]
        tasks = manifest.get("work", {}).get("tasks", [])
        if assigned != {task["id"] for task in tasks}:
            continue
        try:
            validate_assignment_audit(db, manifest, tasks=tasks, current_tasks=selection["tasks"])
        except CoreError:
            continue
        # Submission supersedes the latest comparison. Refresh its administrative
        # context without making the underlying examinations stale.
        if any(pin not in manifest["read_set"] for pin in prior_reconciliations.values()):
            continue
        raw = db.get_blob(saved["payload_sha256"])
        if len(raw) > max_bytes:
            continue
        drift = [task_binding_changes(state, task, packet=manifest) for task in tasks]
        if any(change["records"] or change["relations"] for change in drift):
            continue
        if mode == "independent":
            drift = independent_context_changes(state, manifest)
            if drift["records"] or drift["relations"]:
                continue
        return _assignment_assistance(db, {"prepared": True, "reused": True,
            "packet_id": saved["packet_id"], "revision": db.max_revision(), "audit_id": audit_id,
            "mode": mode, "assigned_task_ids": sorted(assigned), "manifest": manifest,
            "conditional_on_task_ids": manifest["work"].get("conditional_on_task_ids", []),
            "packet": json.loads(raw), "selection": selection})
    return None


def prepare_stage(db, *, audit_id, stage=1, mode="primary", focus=None, task_ids=None,
                  exclude_task_ids=(), max_units=5, max_bytes=131072, allow_provisional=False,
                  correct=False):
    """Select only this stage. An explicit empty selection means no work."""
    if stage not in (1, 2) or mode not in ("primary", "independent", "reconcile"):
        raise InvalidRequest("choose stage 1 primary or a stage 2 review/integration mode")
    if stage == 1 and mode != "primary":
        raise InvalidRequest("stage 1 prepares primary examinations")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
        raise InvalidRequest("max_bytes must be between 1 and 1048576")
    view, assessed = derive_work(db, audit_id=audit_id, focus=focus, include_assessment=True)
    if correct:
        if stage != 2 or mode != "reconcile" or not task_ids:
            raise InvalidRequest("correction requires stage 2 integration and explicit task IDs", code="WORK_CORRECTION")
        requested = set(task_ids)
        current = {task["id"]: task for task in view["tasks"]}
        if any(tid not in current or current[tid]["role"] != "coordinator"
               or current[tid]["state"] != "satisfied" or current[tid]["freshness"] != "current"
               or not current[tid]["judgment_refs"] for tid in requested):
            raise InvalidRequest("correct only a completed current integration; changed questions need affected scientific work",
                                 code="WORK_CORRECTION")
        # Assignment intent only: the saved assessment remains completed, including
        # unresolved conclusions. Unrelated pending or completed tasks stay excluded.
        view = deepcopy(view)
        for unit in view["units"]:
            unit["pending_obligation_ids"] = [tid for tid in unit["obligation_ids"] if tid in requested]
    eligible = {task["id"] for task in view["tasks"] if _in_stage(task, stage, mode)}
    selected = sorted(eligible) if task_ids is None else list(task_ids)
    if set(selected) - eligible:
        raise InvalidRequest("requested tasks do not belong to this stage", code="WORK_TASK",
                             records=sorted(set(selected) - eligible))
    base = {"stage": stage, "audit_id": audit_id, "revision": view["revision"], "mode": mode,
            "prepared": False, "reused": False, "assigned_task_ids": [],
            "analysis_complete": view["analysis_complete"], "coordinator_actions": view["coordinator_actions"]}
    if not selected:
        return _preparation_feedback({**base, "reason": "no_selected_work" if task_ids is not None else "no_stage_work"})
    excluded = set(exclude_task_ids) | (set(t["id"] for t in view["tasks"]) - eligible)
    selection = select_assignment(view, {"mode": mode, "focus": focus,
        "task_ids": selected if task_ids is not None else [],
        "exclude_task_ids": sorted(excluded), "max_units": max_units, "allow_provisional": allow_provisional})
    if not selection.get("prepared"):
        return _preparation_feedback({**base, **selection, "reason": "no_useful_assignment"})
    reused = _reuse_assignment(db, audit_id=audit_id, mode=mode, selection=selection, max_bytes=max_bytes)
    if reused is not None:
        return _preparation_feedback({**reused, "stage": stage, "correction": correct})
    prepared = prepare_assignment(db, audit_id=audit_id, mode=mode, selection=selection, max_bytes=max_bytes)
    if prepared.get("prepared"):
        prepared = _assignment_assistance(db, prepared, assessed=assessed)
    return _preparation_feedback({**prepared, "stage": stage, "reused": False, "correction": correct})


def examine(db, *, envelope_bytes, response_bytes):
    return submit_work(db, envelope_bytes=envelope_bytes, response_bytes=response_bytes)


__all__ = ["prepare_stage", "stage_status", "examine"]
