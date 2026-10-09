"""Read-only compatibility of saved questions with the live audit.

Only appended explicit items can preserve an old local assignment. Mathematical
bindings, independent context, source delivery and write versions remain the
caller's existing checks.
"""
from __future__ import annotations

from .errors import ConflictError, InvalidRequest

COHERENT_PROTOCOL = "coherent-proof-audit/1"
TASK_IDENTITY_FIELDS = ("target", "kind", "role", "action")


def validate_assignment_audit(db, manifest, *, tasks=None, current_tasks=None):
    """Validate audit policy and, for an addition, current required authorization.

    ``tasks`` is the submitted subset, or every assigned task for reuse/extension.
    Reuse supplies its already derived ``current_tasks`` to avoid reassessment.
    A saved task's progress or accepted prerequisites are not its identity.
    """
    work = manifest["work"]
    tasks = list(work["tasks"] if tasks is None else tasks)
    audit_ref = work.get("audit_ref") or next(
        (ref for ref in manifest["read_set"] if ref["collection"] == "audits"
         and ref["id"] == work["audit_id"]), None)
    if audit_ref is None:
        raise InvalidRequest("assignment lacks pinned audit provenance", code="WORK_PACKET_REQUIRED")
    old = db.version("audits", audit_ref["id"], audit_ref["version"])
    live = db.head("audits", audit_ref["id"])
    if (old is None or old.retired or live is None or live.retired
            or audit_ref["id"] != work["audit_id"]):
        raise ConflictError("audit scope or checking protocol changed")
    ignored = {"report_path"}
    # Preserve the existing exception for newer primary global assignments only.
    if manifest["mode"] == "primary" and tasks and all(
            task["role"] == "primary" and task["target"] == live.ref
            and any(entry["ref"] == audit_ref and entry["facet"] == "proof"
                    for entry in task["consumed_inputs"]) for task in tasks):
        ignored.add("qualification_id")
    before = {key: value for key, value in old.body.items() if key not in ignored}
    after = {key: value for key, value in live.body.items() if key not in ignored}
    appended = before != after
    if appended:
        old_targets, new_targets = old.body["targets"], live.body["targets"]
        tail = new_targets[len(old_targets):]
        local = tasks and all(task["target"]["collection"] != "audits"
            and task["kind"] not in ("global_consistency", "adversarial", "method_interface")
            and not any(guard["relation"] == "audit_scope"
                        for guard in task.get("membership_guards", [])) for task in tasks)
        if (old.body["mode"] != "full" or live.body["mode"] != "full"
                or old.body["protocol_version"] != COHERENT_PROTOCOL
                or live.body["protocol_version"] != COHERENT_PROTOCOL or not local
                or not tail or new_targets[:len(old_targets)] != old_targets
                or any(target["collection"] != "items" or target in old_targets
                       or target in tail[:index]
                       or (record := db.head("items", target["id"])) is None or record.retired
                       for index, target in enumerate(tail))
                or {key: value for key, value in before.items() if key != "targets"}
                != {key: value for key, value in after.items() if key != "targets"}):
            raise ConflictError("audit scope or checking protocol changed")
        # The local exception does not inherit the primary-global qualification
        # exception, which by definition cannot apply to these local tasks.
        if current_tasks is None:
            from .work import derive_work
            view = derive_work(db, audit_id=live.id)
            if not view["analysis_complete"]:
                raise ConflictError("current assignment authorization could not be established")
            current_tasks = view["tasks"]
    if current_tasks is not None:
        current = {task["id"]: task for task in current_tasks}
        for task in tasks:
            fresh = current.get(task["id"])
            if (fresh is None or (appended and not fresh["required"])
                    or any(task[key] != fresh[key] for key in TASK_IDENTITY_FIELDS)):
                raise ConflictError("assignment task is no longer authorized", records=[{"task_id": task["id"]}])
    return {"audit_ref": audit_ref, "ignored_audit_fields": ignored, "targets_appended": appended}


__all__ = ["validate_assignment_audit", "TASK_IDENTITY_FIELDS"]
