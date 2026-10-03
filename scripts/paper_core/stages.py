"""Derived stage boundaries and assignment selection over one assessed snapshot.

Stages schedule existing obligations. They do not change scientific completion,
accepted evidence, or the common submission and recovery interfaces.
"""
from __future__ import annotations

from .assessment import TraversalLimit, coverage_diagnostic, derive_full, key_of
from .errors import InvalidRequest
from .semantics import anchors_overlap, target_source_resolution
from .work import _focus, build_work, select_assignment


GLOBAL_KINDS = frozenset(("global_consistency", "adversarial", "method_interface"))
DIAGNOSTIC_LIMIT = 100


def task_stage(task):
    """Stage membership uses kind, target and role rather than role alone."""
    if task["target"]["collection"] == "audits" and task["kind"] in GLOBAL_KINDS:
        return "global"
    if task["role"] == "primary" and task["target"]["collection"] != "audits":
        return "primary"
    if task["role"] == "independent":
        return "independent"
    if task["kind"] == "reconciliation" and task["role"] == "coordinator":
        return "reconcile"
    return None


def _bounded(rows, field, *, limit=DIAGNOSTIC_LIMIT):
    return {field: rows if limit is None else rows[:limit], field.rstrip("s") + "_count": len(rows),
            field + "_truncated": limit is not None and len(rows) > limit}


def representation_readiness(derivation, assessment, task_ids=None, *, diagnostic_limit=DIAGNOSTIC_LIMIT):
    """Require the current qualifying comparison of required text to be matched.

    The engine's latest comparison and freshness decisions remain authoritative.
    Mathematical outcomes do not participate in this representation boundary.
    ``task_ids=None`` means the entire registered scope; an empty set means none.
    """
    if derivation is None or not assessment.get("analysis_complete"):
        return {"representation_settled": None, "required_count": None, "matched_count": None,
                **_bounded([], "blockers")}
    wanted = None if task_ids is None else set(task_ids)
    obligations = [row for row in assessment["obligations"] if row["required"]
                   and row["kind"] == "source_fidelity"
                   and (wanted is None or row["id"] in wanted)]
    blockers, matched = [], 0
    for row in obligations:
        comparison_ref = row["check_refs"][-1] if row["check_refs"] else None
        comparison = derivation.snap.get(comparison_ref) if comparison_ref else None
        result = None if comparison is None else comparison.body["result"]
        if row["satisfied"] and row["freshness"] == "current" and result == "matched":
            matched += 1
            continue
        target = row["target"]
        blockers.append({"code": "source_representation_unsettled", "task_id": row["id"],
            "target_ref": target, "comparison_ref": comparison_ref, "result": result,
            "freshness": row["freshness"],
            "message": "The required recorded statement has no current qualifying matched source comparison.",
            "next_action": {"operation": "correct_and_compare_source", "target_ref": target,
                "comparison_ref": comparison_ref,
                "get_targets": [target] + ([comparison_ref] if comparison_ref else []),
                "compare_operation": "compare",
                "message": "Inspect the affected statement and comparison, correct the representation through an authorized packet, and compare the current source again. Preserve the earlier observation."}})
    return {"representation_settled": not blockers, "required_count": len(obligations),
            "matched_count": matched, **_bounded(blockers, "blockers", limit=diagnostic_limit)}


def _focus_closure(full_work, focus):
    """Retain all prerequisite facts and complete joint units for a focus."""
    if focus is None:
        return {row["id"] for row in full_work["tasks"]}
    tasks = {row["id"]: row for row in full_work["tasks"]}
    unit_of = {oid: unit for unit in full_work["units"] for oid in unit["obligation_ids"]}
    pending = [oid for oid, task in tasks.items() if task["target"] == focus or task["owner"] == focus
               or task["argument"] == focus]
    wanted = set()
    while pending:
        oid = pending.pop()
        if oid in wanted:
            continue
        wanted.add(oid)
        pending.extend(tasks[oid]["prerequisite_ids"])
        pending.extend(unit_of[oid]["obligation_ids"])
    return wanted


def grounding_readiness(derivation, assessment, full_work, task_ids=None, *, diagnostic_limit=DIAGNOSTIC_LIMIT):
    """Derive known mapping prerequisites for the required written-proof closure.

    This checks physical source associations on canonical records. It neither
    preassigns independent judgments nor certifies their mathematical meaning.
    Reconstructed routes retain their honest origin and supplied-route path.
    A group's argument membership does not establish where its supporting
    derivation or an application is written. Such records resolve their own
    source links; the written argument itself must match its reviewed boundary.
    """
    if derivation is None or not assessment.get("analysis_complete") or not full_work.get("analysis_complete") \
            or full_work.get("diagnostics_truncated") \
            or {row["id"] for row in assessment["obligations"]} != {row["id"] for row in full_work["tasks"]}:
        return {"source_grounding_settled": None, "required_target_count": None,
                "grounded_target_count": None, **_bounded([], "blockers", limit=diagnostic_limit)}
    snap = derivation.snap
    required = [row for row in full_work["tasks"] if row["required"] and task_stage(row) == "primary"
                and (task_ids is None or row["id"] in task_ids)
                and row["target"]["collection"] in ("arguments", "groups", "uses")]
    targets, routes, blockers = {}, {}, []
    for task in required:
        argument_ref = task["argument"]
        argument = snap.get(argument_ref) if argument_ref else None
        if argument is not None and argument.body["origin"] != "source":
            continue
        identity = (key_of(task["target"]), key_of(argument_ref) if argument_ref else None)
        targets.setdefault(identity, {"target": task["target"], "argument": argument_ref, "task_ids": []})
        targets[identity]["task_ids"].append(task["id"])
        if argument is not None and argument.id not in routes:
            cached = getattr(derivation, "reviewed_boundaries", {})
            routes[argument.id] = cached[argument.id] if argument.id in cached else derivation._reviewed_boundary(argument)

    grounded = 0
    for row in targets.values():
        target, argument_ref = row["target"], row["argument"]
        resolution = target_source_resolution(snap, target)
        ranges = routes.get(argument_ref["id"]) if argument_ref else None
        code = None
        if not resolution["anchors"]:
            code = "source_grounding_required"
            message = "The required written-proof record has no usable current source association."
        elif argument_ref is None:
            code = "source_grounding_route_unresolved"
            message = "The required application has no resolved written-proof route for its source association."
        elif target["collection"] != "arguments":
            # Source-backed prerequisites may be written elsewhere. Membership
            # alone cannot justify a narrower source rule than review mapping.
            grounded += 1
            continue
        elif ranges is None:
            # Boundary recovery is argument scoped and already reported by the
            # assessed coverage facts. It grants no source correspondence credit.
            continue
        elif not any(anchors_overlap(anchor.body, reviewed.body, right_spans=spans)
                     for anchor in resolution["anchors"] for identity, spans in ranges.items()
                     if (reviewed := snap.live("anchors", identity)) is not None):
            code = "source_grounding_outside_reviewed_proof"
            message = "The record's source association does not overlap this route's current reviewed proof spans."
        else:
            grounded += 1
            continue
        blockers.append({"code": code, "target_ref": target, "argument_ref": argument_ref,
            "related_task_ids": row["task_ids"], "anchor_ids": resolution["anchor_ids"],
            "source_issues": resolution["issues"], "message": message,
            "next_action": {"operation": "ground_source_record", "target_ref": target,
                "argument_ref": argument_ref, "get_targets": [target] + ([argument_ref] if argument_ref else []),
                "source_field": "evidence_refs",
                "message": "Inspect this record's actual content and applicable source context, then add or correct links to passages supporting that content through an authorized packet. For an inferred step or unavailable source, preserve its honest origin and limitation and use the supplied-route investigation where applicable; do not invent a manuscript passage."}})
    for identity, ranges in routes.items():
        if ranges is None:
            argument_ref = {"collection": "arguments", "id": identity}
            blockers.append({"code": "source_grounding_boundary_unsettled", "target_ref": argument_ref,
                "argument_ref": argument_ref,
                "message": "Current reviewed proof spans are needed to verify this written route's source associations.",
                "next_action": {"operation": "review_proof_boundary", "target_ref": argument_ref,
                    "message": "Recover the affected proof-boundary certificate. An unresolved explicit selection supplies no whole-page grounding credit."}})
    return {"source_grounding_settled": not blockers and grounded == len(targets),
            "required_target_count": len(targets), "grounded_target_count": grounded,
            **_bounded(blockers, "blockers", limit=diagnostic_limit)}


def _primary_boundary(derivation, assessment, full_work, *, task_ids=None):
    tasks = [row for row in full_work["tasks"] if row["required"] and task_stage(row) == "primary"
             and (task_ids is None or row["id"] in task_ids)]
    ids = {row["id"] for row in tasks}
    remaining = [row for row in tasks if row["state"] != "satisfied"]
    representation = representation_readiness(derivation, assessment, ids, diagnostic_limit=None)
    grounding = grounding_readiness(derivation, assessment, full_work, ids, diagnostic_limit=None)
    refs = {key_of(ref) for row in tasks for ref in (row["target"], row["owner"], row["argument"]) if ref}
    arguments = {row["argument"]["id"] for row in tasks if row["argument"]}
    whole_scope = task_ids is None
    blockers = []
    for action in full_work["coordinator_actions"]:
        if not action.get("required", True) or action["code"] in ("qualification_required", "coverage_authoring"):
            continue
        related = set(action["related_task_ids"])
        relevant = bool(ids & related or refs & {key_of(ref) for ref in action["target_refs"]})
        unassigned_source_limit = action["code"] == "source_attention" and not related
        if relevant or whole_scope and (unassigned_source_limit or action["code"] in ("missing_scope_target", "invalid_scope_target")):
            blockers.append(action)
    # Public coverage lists and grouped examples are deliberately bounded. Use
    # the derivation's complete raw facts when deciding readiness instead.
    for fact in derivation.coverage_diagnostics:
        if whole_scope or arguments.intersection(fact.get("argument_ids", ())) or fact.get("owner") in refs:
            blockers.append(coverage_diagnostic(fact))
    blockers.extend(representation["blockers"])
    blockers.extend(grounding["blockers"])
    # The structured facts cover scope and coverage. The whole audit also keeps
    # any remaining derivation problem, without parsing its human wording.
    if whole_scope and assessment["problems"] and not blockers:
        blockers.append({"code": "assessment_problems", "message": "Resolve the recorded scope or proof problems.",
                         "problems": assessment["problems"][:DIAGNOSTIC_LIMIT],
                         "problem_count": len(assessment["problems"])})
    if not assessment["statements"]:
        blockers.append({"code": "empty_scope", "message": "The audit has no registered in-scope statements."})
    elif not tasks:
        blockers.append({"code": "empty_primary_work", "message": "This scope has no required local primary work."})
    if assessment["mode"] == "triage":
        blockers.append({"code": "triage_scope", "message": "Triage retains a partial examination and has no required independent or global review workflow."})
    ready = not remaining and not blockers and representation["representation_settled"] is True \
        and grounding["source_grounding_settled"] is True
    return {"ready": ready, "state": "ready" if ready else "blocked", "required_count": len(tasks),
            "completed_count": len(tasks) - len(remaining), "remaining_task_ids": [row["id"] for row in remaining[:DIAGNOSTIC_LIMIT]],
            "remaining_count": len(remaining), "remaining_truncated": len(remaining) > DIAGNOSTIC_LIMIT,
            **_bounded(blockers, "blockers"), "representation_settled": representation["representation_settled"],
            "source_grounding_settled": grounding["source_grounding_settled"],
            "grounding_required_target_count": grounding["required_target_count"],
            "grounding_grounded_target_count": grounding["grounded_target_count"]}


def _task_counts(tasks):
    required = [row for row in tasks if row["required"]]
    remaining = [row for row in required if row["state"] != "satisfied"]
    return {"required_count": len(required), "completed_count": len(required) - len(remaining),
            "remaining_task_ids": [row["id"] for row in remaining[:DIAGNOSTIC_LIMIT]],
            "remaining_count": len(remaining), "remaining_truncated": len(remaining) > DIAGNOSTIC_LIMIT}


def assess_stages(derivation, assessment, full_work):
    """Assess all stages from complete, unpaginated work and derivation facts."""
    if derivation is not None and assessment.get("analysis_complete"):
        expected = {row["id"] for row in assessment["obligations"]}
        supplied = {row["id"] for row in full_work["tasks"]}
        if expected != supplied or full_work.get("diagnostics_truncated"):
            full_work = dict(full_work, analysis_complete=False, coordinator_actions=[{
                "code": "STAGE_FACTS_INCOMPLETE", "message": "Stage readiness requires the complete work and diagnostic facts before pagination or truncation."}])
    if not full_work.get("analysis_complete") or derivation is None or not assessment.get("analysis_complete"):
        unknown = {"ready": None, "state": "unknown", "required_count": None, "completed_count": None,
                   "remaining_task_ids": [], "remaining_count": None, "remaining_truncated": False,
                   **_bounded(full_work.get("coordinator_actions", []), "blockers"), "representation_settled": None,
                   "source_grounding_settled": None}
        return {"revision": full_work["revision"], "audit_id": full_work["audit_id"],
                "mode": assessment.get("mode"), "declared_scope": assessment.get("scope"),
                "analysis_complete": False, "progress": full_work["progress"], "representation_settled": None,
                "source_grounding_settled": None,
                "stage1": unknown, "stage2": {"ready_for_local_review": None, "ready_for_global": None,
                    "finalization_ready": None, "process_complete": full_work["progress"]["process_complete"]},
                **({"limit": assessment["limit"]} if "limit" in assessment else {})}
    primary = _primary_boundary(derivation, assessment, full_work)
    local_review = _task_counts([row for row in full_work["tasks"] if task_stage(row) in ("independent", "reconcile")])
    global_work = _task_counts([row for row in full_work["tasks"] if task_stage(row) == "global"])
    review_ready = primary["ready"] and assessment["mode"] != "triage"
    return {"revision": assessment["revision"], "audit_id": assessment["audit_id"], "mode": assessment["mode"],
            "declared_scope": assessment["scope"], "analysis_complete": True, "progress": assessment["progress"],
            "representation_settled": primary["representation_settled"],
            "source_grounding_settled": primary["source_grounding_settled"], "stage1": primary,
            "stage2": {"ready_for_local_review": review_ready,
                       "ready_for_global": review_ready and local_review["remaining_count"] == 0,
                       "local_review": local_review, "global": global_work,
                       "process_complete": assessment["progress"]["process_complete"],
                       "finalization_ready": assessment["progress"]["process_complete"] and review_ready}}


def _assess(db, *, audit_id, revision=None, limits=None):
    try:
        derivation, assessment = derive_full(db, audit_id=audit_id, revision=revision, limits=limits)
        view = build_work(derivation, assessment, diagnostic_limit=None)
        status = assess_stages(derivation, assessment, view)
    except TraversalLimit as exc:
        revision = db.max_revision() if revision is None else revision
        assessment = {"analysis_complete": False, "limit": {"bound": exc.bound, "maximum": exc.maximum,
                                                              "context": exc.context}}
        audit = db.latest_at("audits", audit_id, revision)
        if audit and not audit.retired:
            assessment.update(mode=audit.body["mode"], scope={"mode": audit.body["mode"],
                "target_refs": audit.body["targets"], "exclusions": audit.body["exclusions"]})
        view = {"revision": revision, "audit_id": audit_id, "analysis_complete": False,
                "progress": {"process_complete": False}, "tasks": [], "units": [], "task_contexts": {},
                "coordinator_actions": [{"code": exc.code, "message": exc.message, "required": True}], "focus": None}
        derivation = None
        status = assess_stages(derivation, assessment, view)
    return derivation, assessment, view, status


def stage_status(db, *, audit_id, stage=None, revision=None, focus=None, limits=None):
    derivation, assessment, view, result = _assess(db, audit_id=audit_id, revision=revision, limits=limits)
    if stage is not None:
        if stage not in (1, 2):
            raise InvalidRequest("stage must be 1 or 2", code="STAGE_MODE")
        result["stage"] = stage
    focus = _focus(focus)
    if focus is not None:
        if derivation is not None and derivation.snap.get(focus) is None:
            raise InvalidRequest(f"focus {key_of(focus)} is not live", code="WORK_FOCUS")
        result["focus"] = focus
        if result["analysis_complete"]:
            result["focus_status"] = _primary_boundary(derivation, assessment, view,
                task_ids=_focus_closure(view, focus))
    return result


def prepare_stage(db, *, audit_id, stage, mode=None, focus=None, ready_subset=False, task_ids=(),
                  exclude_task_ids=(), max_units=5, max_bytes=131072, allow_provisional=False, limits=None,
                  _assessed=None):
    """Apply the stage boundary, then prepare with this same assessed revision."""
    if stage not in (1, 2):
        raise InvalidRequest("stage must be 1 or 2", code="STAGE_MODE")
    mode = "primary" if stage == 1 and mode is None else mode
    if stage == 1 and mode != "primary" or stage == 2 and mode not in ("independent", "reconcile", "global"):
        raise InvalidRequest("invalid mode for this stage", code="STAGE_MODE")
    if type(ready_subset) is not bool or type(allow_provisional) is not bool:
        raise InvalidRequest("ready_subset and allow_provisional must be boolean", code="STAGE_REQUEST")
    if type(max_units) is not int or not 1 <= max_units <= 10:
        raise InvalidRequest("max_units must be 1..10", code="WORK_LIMIT")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
        raise InvalidRequest("max_bytes must be between 1 and 1048576", code="WORK_LIMIT")
    focus = _focus(focus)
    if ready_subset and (stage != 2 or mode == "global" or focus is None):
        raise InvalidRequest("ready-subset requires focused Stage 2 independent or reconciliation preparation", code="STAGE_SUBSET")
    derivation, assessment, view, status = _assess(db, audit_id=audit_id, limits=limits) if _assessed is None else _assessed
    base = {"prepared": False, "revision": view["revision"], "audit_id": audit_id, "stage": stage,
            "stage_mode": mode, "mode": "primary" if mode == "global" else mode,
            "stage_status": status, "scope_limited": bool(ready_subset), "declared_scope": status["declared_scope"],
            "focus": focus, "assigned_task_ids": []}
    if not status["analysis_complete"]:
        return {**base, "reason_code": "STAGE_ANALYSIS_UNKNOWN", "boundary": status["stage1"]}
    if focus is not None and derivation.snap.get(focus) is None:
        raise InvalidRequest(f"focus {key_of(focus)} is not live", code="WORK_FOCUS")
    closure = _focus_closure(view, focus)
    tasks = {row["id"]: row for row in view["tasks"]}
    unknown = (set(task_ids) | set(exclude_task_ids)) - (closure if focus else tasks.keys())
    if unknown:
        raise InvalidRequest("unknown or out-of-focus task IDs", code="WORK_TASK", records=sorted(unknown))
    not_required = sorted({oid for oid in task_ids if not tasks[oid]["required"]})
    if not_required:
        from .work import selection_guidance
        base["task_selection"] = selection_guidance(view, task_ids, ())
        base["selection_diagnostics"] = [{"code": "TASK_NOT_REQUIRED", "task_id": oid,
            "message": "This task is not required for the declared audit scope."} for oid in not_required]
        if len(not_required) == len(set(task_ids)):
            return {**base, "reason_code": "TASK_NOT_REQUIRED"}
    wrong_stage = [oid for oid in task_ids if tasks[oid]["required"] and task_stage(tasks[oid]) != mode]
    if wrong_stage:
        return {**base, "reason_code": "TASK_OTHER_STAGE", "selection_diagnostics": [
            {"code": "TASK_OTHER_STAGE", "task_id": oid, "correct_stage": 1 if task_stage(tasks[oid]) == "primary" else 2,
             "correct_mode": task_stage(tasks[oid]), "message": "Prepare this task in its own stage and mode."}
            for oid in wrong_stage]}
    boundary = status["stage1"]
    if stage == 2:
        if ready_subset:
            boundary = _primary_boundary(derivation, assessment, view, task_ids=closure)
            outside = [row["id"] for row in view["tasks"] if row["required"] and row["state"] != "satisfied"
                       and row["id"] not in closure]
            base.update(outside_remaining_task_ids=outside[:DIAGNOSTIC_LIMIT], outside_remaining_count=len(outside),
                        outside_remaining_truncated=len(outside) > DIAGNOSTIC_LIMIT)
        base["boundary"] = boundary
        if not boundary["ready"]:
            return {**base, "reason_code": "STAGE1_NOT_READY"}
        if mode == "global" and not status["stage2"]["ready_for_global"]:
            return {**base, "reason_code": "LOCAL_REVIEW_NOT_COMPLETE", "boundary": status["stage2"]["local_review"]}
    candidates = [oid for oid, task in tasks.items() if task_stage(task) == mode]
    # Full facts govern the boundary; assignment diagnostics follow the same
    # focused projection as ordinary work without another scientific assessment.
    assignment_view = view if focus is None else build_work(derivation, assessment, focus=focus, diagnostic_limit=None)
    request = {"mode": base["mode"], "focus": focus, "task_ids": list(task_ids),
               "exclude_task_ids": list(exclude_task_ids), "candidate_task_ids": candidates,
               "max_units": max_units, "allow_provisional": allow_provisional}
    # This selector is also used by status/diagnostic advice and the controller.
    selection = select_assignment(assignment_view, request)
    if not selection["prepared"]:
        return {**selection, **base, "reason_code": "STAGE_NO_WORK", "selection": selection}
    from .controller import prepare_assessed_work
    prepared = prepare_assessed_work(db, audit_id=audit_id, mode=base["mode"], view=assignment_view,
        assessed=(derivation, assessment), focus=focus, task_ids=task_ids, exclude_task_ids=exclude_task_ids,
        candidate_task_ids=candidates, max_units=max_units, max_bytes=max_bytes, allow_provisional=allow_provisional)
    return {**base, **prepared, "stage": stage, "stage_mode": mode, "stage_status": status}


def preparation_policy(view, *, mode, focus=None, task_ids=(), exclude_task_ids=()):
    """Resolve ordinary compatibility preparation to the existing stage policy.

    Audit-level primary tasks require explicit selection. A mixed request is
    split exactly, and no empty filtered selection falls back to unrelated work.
    Exceptions and supplied-route investigations are handled explicitly by the
    caller; this helper never waives an ordinary stage boundary.
    """
    if mode not in ("primary", "independent", "reconcile"):
        raise InvalidRequest("work mode must be primary, independent or reconcile", code="WORK_MODE")
    focus = _focus(focus)
    tasks = {row["id"]: row for row in view["tasks"]}
    closure = _focus_closure(view, focus)
    requested = list(dict.fromkeys(task_ids or ()))
    unknown = (set(requested) | set(exclude_task_ids or ())) - closure
    if unknown:
        raise InvalidRequest("unknown or out-of-focus task IDs", code="WORK_TASK", records=sorted(unknown))
    role = {"primary": "primary", "independent": "independent", "reconcile": "coordinator"}[mode]
    if any(tasks[identity]["role"] != role for identity in requested):
        raise InvalidRequest("requested tasks belong to another role", code="WORK_ROLE")
    local = [identity for identity in requested if task_stage(tasks[identity]) != "global"]
    global_ids = [identity for identity in requested if task_stage(tasks[identity]) == "global"]
    if local and global_ids:
        return {"reason_code": "MIXED_STAGE_REQUEST", "stage": None, "stage_mode": None,
            "task_ids": requested, "selection_diagnostics": [{"code": "MIXED_STAGE_REQUEST",
                "message": "Prepare the selected local and audit-level global tasks separately through their own stages.",
                "split": [{"stage": 1, "mode": "primary", "task_ids": local},
                          {"stage": 2, "mode": "global", "task_ids": global_ids}]}]}
    return {"stage": 2 if mode != "primary" or global_ids else 1,
            "stage_mode": "global" if global_ids else mode, "task_ids": requested}


def prepare_ordinary_work(db, *, audit_id, mode, focus=None, task_ids=(), exclude_task_ids=(),
                          max_units=5, max_bytes=131072, allow_provisional=False, limits=None):
    """Apply ordinary stage eligibility to compatibility preparation once."""
    if mode not in ("primary", "independent", "reconcile"):
        raise InvalidRequest("work mode must be primary, independent or reconcile", code="WORK_MODE")
    if type(max_units) is not int or not 1 <= max_units <= 10:
        raise InvalidRequest("max_units must be 1..10", code="WORK_LIMIT")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
        raise InvalidRequest("max_bytes must be between 1 and 1048576", code="WORK_LIMIT")
    if type(allow_provisional) is not bool:
        raise InvalidRequest("allow_provisional must be boolean", code="STAGE_REQUEST")
    facts = _assess(db, audit_id=audit_id, limits=limits)
    derivation, assessment, view, status = facts
    if not status["analysis_complete"]:
        # There are no trustworthy task identities on which to derive a split.
        return {"prepared": False, "revision": view["revision"], "audit_id": audit_id, "mode": mode,
                "stage_status": status, "assigned_task_ids": [], "reason_code": "STAGE_ANALYSIS_UNKNOWN",
                "boundary": status["stage1"]}
    if focus is not None and derivation.snap.get(_focus(focus)) is None:
        raise InvalidRequest(f"focus {key_of(_focus(focus))} is not live", code="WORK_FOCUS")
    policy = preparation_policy(view, mode=mode, focus=focus, task_ids=task_ids,
                                exclude_task_ids=exclude_task_ids)
    if policy.get("reason_code"):
        return {"prepared": False, "revision": view["revision"], "audit_id": audit_id, "mode": mode,
                "stage_status": status, "focus": _focus(focus), "assigned_task_ids": [], **policy}
    return prepare_stage(db, audit_id=audit_id, stage=policy["stage"], mode=policy["stage_mode"],
        focus=focus, task_ids=policy["task_ids"], exclude_task_ids=exclude_task_ids, max_units=max_units,
        max_bytes=max_bytes, allow_provisional=allow_provisional, limits=limits, _assessed=facts)


__all__ = ["assess_stages", "grounding_readiness", "preparation_policy", "prepare_ordinary_work",
           "prepare_stage", "representation_readiness", "stage_status", "task_stage"]
