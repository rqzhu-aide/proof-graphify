"""Uncommitted authoring assistance derived from the live validation contract.

These views supply shapes and candidate identities, never mathematical decisions.
Role guidance is independent of the private assignment manifest. Primary task
labels are a separate view of the original packet's pinned records.
"""
from __future__ import annotations

from copy import deepcopy

from . import CONTRACT_VERSION
from . import contract as c
from .errors import InvalidRequest
from .ids import new_id, valid_id


def describe(spec):
    """A compact, informational shape; the contract remains the only validator."""
    if isinstance(spec, c.Obj):
        result = {"fields": {name: describe(child) for name, child in spec.fields.items()}}
        if spec.optional:
            result["optional_fields"] = sorted(spec.optional)
    elif isinstance(spec, c.OneOf):
        result = {"one_of": [describe(option) for option in spec.options]}
    elif isinstance(spec, c.Arr):
        result = {"array_of": describe(spec.inner)}
        if spec.nonempty:
            result["nonempty"] = True
    elif isinstance(spec, c.RefT):
        result = {"type": "PinnedRef" if spec.pinned else "Ref",
                  "keys": ["collection", "id"] + (["version"] if spec.pinned else [])}
        if spec.collections != c.COLLECTIONS:
            result["collections"] = list(spec.collections)
    elif isinstance(spec, c.Enum):
        result = {"enum": list(spec.values)}
    elif isinstance(spec, c.Const):
        result = {"constant": spec.expected}
    elif isinstance(spec, c.Id):
        result = {"type": "identifier"}
        if spec.target:
            result["collection"] = spec.target
    elif isinstance(spec, c.Int):
        result = {"type": "integer"}
        if spec.minimum is not None:
            result["minimum"] = spec.minimum
    elif isinstance(spec, c.Str):
        result = {"type": "string"}
        if spec.nonempty:
            result["nonempty"] = True
    elif isinstance(spec, c.Hash):
        result = {"type": "lowercase_sha256"}
    elif isinstance(spec, c.Bool):
        result = {"type": "boolean"}
    elif isinstance(spec, c.RequestVersion):
        result = {"type": "request_contract_version", "current": CONTRACT_VERSION}
    elif isinstance(spec, c.Null):
        result = {"type": "null"}
    elif isinstance(spec, c.Any):
        result = {"type": "any"}
    else:
        raise TypeError(f"unsupported contract type {type(spec).__name__}")
    if spec.nullable and not isinstance(spec, (c.Null, c.Any)):
        result["nullable"] = True
    return result


def skeleton(spec):
    """Include required fields, using unmistakably unfinished scientific values."""
    if spec.nullable:
        return None
    if isinstance(spec, c.Obj):
        return {name: skeleton(child) for name, child in spec.fields.items() if name not in spec.optional}
    if isinstance(spec, c.OneOf):
        return skeleton(spec.options[0])
    if isinstance(spec, c.Arr):
        return []
    if isinstance(spec, c.RefT):
        return dict(collection="", id="", **({"version": None} if spec.pinned else {}))
    if isinstance(spec, c.Const):
        return deepcopy(spec.expected)
    if isinstance(spec, c.RequestVersion):
        return CONTRACT_VERSION
    if isinstance(spec, (c.Int, c.Bool)):
        return None
    if isinstance(spec, (c.Enum, c.Id, c.Str, c.Hash)):
        return ""
    raise TypeError(f"unsupported contract type {type(spec).__name__}")


def _identifier(value, name):
    if not valid_id(value):
        raise InvalidRequest(f"{name} must be a nonempty identifier", code="ASSISTANCE_INPUT")


def authoring_template(collection, *, packet_id, record_id=None):
    """Return one create envelope and its selected body's current contract shape.

    Blank fields are intentional, not a valid or completed scientific assertion.
    Application-detail identity must be selected by the caller, since it shares
    the use's ID rather than allocating an independent record identity.
    """
    if collection not in c.BODY_SCHEMAS:
        raise InvalidRequest(f"unknown collection {collection!r}", code="ASSISTANCE_COLLECTION")
    _identifier(packet_id, "packet_id")
    if collection == "application_details" and record_id is None:
        raise InvalidRequest("application_details requires record_id equal to the existing use ID",
                             code="ASSISTANCE_IDENTITY")
    identifier = new_id(collection) if record_id is None else record_id
    _identifier(identifier, "record_id")
    body = skeleton(c.BODY_SCHEMAS[collection])
    if collection == "application_details":
        body["use_id"] = identifier
    entry = skeleton(c.EDIT_CREATE)
    entry.update(collection=collection, id=identifier, body=body)
    batch = skeleton(c.BATCH)
    batch.update(request_id=new_id("request"), packet_id=packet_id, edits=[entry])
    note = ("Uncommitted template. Fill blank scientific fields and references before submission. "
            "All displayed fields are required unless listed as optional; nullable does not mean optional.")
    if collection == "audits":
        note += (" Excluding an item removes that result and its parts from required work. "
                 "Keep an unavailable proof of a requested result in scope as a source limitation "
                 "or unresolved examination; missing material alone does not authorize narrowing the request.")
    return {"template": batch, "body_shape": describe(c.BODY_SCHEMAS[collection]), "note": note}


ROLE_REFERENCES = {
    "primary": ("primary-checker.md", "mathematical-checking.md", "evidence-and-verdicts.md"),
    "independent": ("independent-checker.md", "mathematical-checking.md", "evidence-and-verdicts.md"),
    "reconcile": ("reconciler.md", "evidence-and-verdicts.md"),
}


def worker_guidance(mode, *, composition=False):
    guidance = _response_guidance(mode)
    guidance["reference_files"] = list(ROLE_REFERENCES[mode])
    if mode == "primary" and composition:
        guidance["coverage_note"] = (
            "Link coverage claims to statements the checks actually examined, not merely cited anchors. "
            "Use check_task_ids for this response or existing_check_refs for saved checks in the same argument. "
            "Keep replaces present (null for new coverage). These are controller response fields; "
            "direct stored coverage uses check_ids and replacement in its enclosing edit instead. "
            "Save partial work when coverage remains unfinished.")
    return guidance


def _response_guidance(mode):
    """Describe only this role's response interface, with no assignment data.

    This replaces full contract manuals in routine dispatch. In particular the
    independent branch cannot access task decomposition, draft pins or outcomes.
    """
    if mode == "independent":
        # The response scaffold already carries the envelope. Only its missing
        # row and source-target interface belong in this companion file.
        return {"mode": mode, "judgment_shape": describe(c.JUDGMENT),
                "source_target_template": skeleton(c.SOURCE_TARGET),
                "canonical_target_collections": {kind: list(collections)
                                                 for kind, collections in c.CHECK_TARGETS.items()},
                "source_target_example": {
                    "kind": "composition",
                    "target": {"source_anchor_id": "<supplied proof anchor ID>",
                               "description": "The complete written route establishing the requested conclusion."}},
                "note": "Keep required nullable scaffold fields. covered_targets names reviewed source conclusions; "
                        "composition uses a source target describing its conclusion and written route. Replace "
                        "the example anchor and author scientific fields. Examine every substantive inference "
                        "in route reasoning; separate judgments suit distinct targets/routes or local outcomes "
                        "needing separate treatment, with no row quota. Put extra prerequisite concerns in "
                        "coverage_note; concerns undermining the conclusion also belong in its reasoning/outcome. "
                        "Preserve counterexamples through corrections; never silently add hypotheses. "
                        "Context extension retains the obligation; an out-of-scope target needs another assignment."}
    if mode == "primary":
        return {"mode": mode, "response_shape": describe(c.WORK_PRIMARY_RESPONSE),
                "coverage_row_template": skeleton(c.WORK_COVERAGE),
                "finding_row_template": skeleton(c.WORK_FINDING),
                "note": "Use assigned task IDs; keep required nullable fields. "
                        "check_task_ids/related_task_ids link this response's checks, never source_fidelity "
                        "observations; existing_check_refs pins saved checks. Author judgments; cite existing "
                        "findings during renewal. Renewed checks alone do not resolve findings. "
                        "Row templates are unfinished examples outside the response scaffold. Fill only "
                        "rows justified by the examination; author their classifications, evidence, links "
                        "and descriptions. Coverage replaces is null for new rows; saved check references "
                        "must be permissible pinned checks from the packet. Coverage links stay in the "
                        "same argument."}
    if mode == "reconcile":
        return {"mode": mode, "row_shape": describe(c.BODY_SCHEMAS["reconciliations"]),
                "note": "Choose exact-target pins from coordinator guidance; author the decision and rationale. "
                        "Preserve the scaffold request_id and use that same ID in the submission envelope. "
                        "An empty pin list or template is not completed reconciliation."}
    raise InvalidRequest(f"unknown assistance mode {mode!r}", code="ASSISTANCE_MODE")


def primary_task_table(db, manifest):
    """Label only assigned primary tasks, using the original packet's read set.

    This helper is intentionally separate from role-only worker_guidance. Never
    attach its private decomposition to independent delivery.
    """
    if manifest.get("mode") != "primary" or manifest.get("work", {}).get("mode") != "primary":
        raise InvalidRequest("a primary task table requires a primary work assignment", code="ASSISTANCE_MODE")
    from .work import record_label

    class PinnedLabels:
        def __init__(self):
            self.pins = {(p["collection"], p["id"]): p for p in manifest["read_set"]}
            self.records = {}

        def get(self, ref):
            key = (ref["collection"], ref["id"])
            pin = self.pins.get(key)
            if pin is None or ref.get("version", pin["version"]) != pin["version"]:
                return None
            if key not in self.records:
                self.records[key] = db.version(*key, pin["version"])
            return self.records[key]

        def live(self, collection, identifier):
            return self.get({"collection": collection, "id": identifier})

    labels = PinnedLabels()
    return [{"task_id": task["id"], "target": deepcopy(task["target"]),
             "target_label": record_label(labels, task["target"]), "kind": task["kind"],
             "result_type": (c.WORK_COMPARISON if task["action"] == "compare_source"
                             else c.WORK_CHECK).fields["type"].expected}
            for task in manifest["work"]["tasks"]]


def _opinion(record, pin):
    """Reference material from the named version, never a new check or verdict."""
    return {"ref": deepcopy(pin), **{field: deepcopy(record.body[field]) for field in (
        "target", "kind", "role", "reviewer", "state", "outcome", "reasoning", "conditions",
        "evidence_refs", "next_action", "supersedes")}}


def coordinator_guidance(db, manifest, *, assessed=None):
    """Candidate identities from the authorized read set; never dispatch to a blind worker.

    ``assessed`` may reuse ``derive_full``'s (derivation, assessment) result.
    Reconciliation uses its existing freshness and independence reducers rather
    than inventing a parallel notion of eligible evidence.
    """
    mode = manifest["mode"]
    tasks = manifest.get("work", {}).get("tasks", ())
    readable = {(p["collection"], p["id"], p["version"]) for p in manifest["read_set"]}
    result = {"mode": mode, "packet_id": manifest["packet_id"], "draft_candidates": []}
    for task in tasks:
        for pin in task.get("draft_refs", ()):
            if (pin["collection"], pin["id"], pin["version"]) not in readable:
                continue
            record = db.version(pin["collection"], pin["id"], pin["version"])
            if record is None or record.collection != "checks" or record.body["state"] != "draft":
                continue
            result["draft_candidates"].append({"task_id": task["id"], **_opinion(record, pin)})
    if result["draft_candidates"]:
        result["draft_note"] = (
            "For replaces, choose the assigned task's same-reviewer draft ref and preserve that draft's "
            "supersedes. A completed predecessor is not a replaces candidate. No candidate is selected here.")
    audit_id = manifest.get("work", {}).get("audit_id")
    renewal_checks = []
    if mode == "primary":
        assigned = {(t["target"]["collection"], t["target"]["id"], t["kind"]): t
                    for t in tasks if t["action"] == "check" and t["role"] == "primary"}
        for pin in manifest["read_set"]:
            if pin["collection"] != "checks":
                continue
            record = db.version("checks", pin["id"], pin["version"])
            if record is None or record.retired:
                continue
            body = record.body
            task = assigned.get((body["target"]["collection"], body["target"]["id"], body["kind"]))
            if task is not None and body["audit_id"] == audit_id and body["role"] == "primary" \
                    and body["state"] == "complete":
                renewal_checks.append((task, pin))
    if mode != "reconcile" and not renewal_checks:
        return result
    if not audit_id:
        raise InvalidRequest("coordinator guidance requires an audit work assignment", code="ASSISTANCE_AUDIT")
    if assessed is None:
        from .assessment import derive_full
        assessed = derive_full(db, audit_id=audit_id)
    derivation, assessment = assessed
    if assessment["audit_id"] != audit_id or assessment["revision"] != db.max_revision():
        raise InvalidRequest("coordinator guidance needs the current assessment for this audit",
                             code="ASSISTANCE_SNAPSHOT")
    if renewal_checks:
        candidates = []
        for task, pin in renewal_checks:
            info = assessment["judgments"].get(f"checks:{pin['id']}")
            if info is None or info["ref"] != pin or info["freshness"] not in ("needs_review", "historical") \
                    or info["superseded"]:
                continue
            record = db.version("checks", pin["id"], pin["version"])
            candidate = {"task_id": task["id"], **_opinion(record, pin)}
            from .work import _recovery
            recovery = _recovery(derivation, [pin], [])
            if recovery:
                candidate["recovery"] = recovery
            candidates.append(candidate)
        if candidates:
            result["renewal_candidates"] = candidates
            result["renewal_note"] = (
                "These completed checks consumed changed inputs. Their pinned opinions are reference material, "
                "not renewed proof credit. Each candidate's ref is its possible supersedes pin, not replaces. "
                "Pass only the needed predecessor context to the assigned primary "
                "checker, who re-examines the affected work and authors explicit supersedes before saving. "
                "Preserve negative outcomes, conditions and reasoning unless the examiner explicitly revises "
                "them. Submit the response unchanged; keep this inventory out of independent delivery.")
    if mode != "reconcile":
        return result
    rows = {}

    def candidate(target):
        key = (target["collection"], target["id"])
        return rows.setdefault(key, {"target": deepcopy(target), "primary_checks": [], "independent_checks": [],
                                     "primary_opinions": [], "independent_opinions": [],
                                     "required_other_opinions": []})

    for info in assessment["judgments"].values():
        pin = info["ref"]
        if (pin["collection"], pin["id"], pin["version"]) not in readable \
                or info["audit_id"] != audit_id or info["state"] != "complete" \
                or info["freshness"] != "current" or info["superseded"]:
            continue
        if info["role"] == "independent" and not derivation.independent_usable(info):
            continue
        row = candidate(info["target"])
        row[f"{info['role']}_checks"].append(deepcopy(pin))
        record = db.version("checks", pin["id"], pin["version"])
        row[f"{info['role']}_opinions"].append(_opinion(record, pin))
    # Reconciliation validation requires every accepted opinion on the exact
    # target, including an explicitly superseded predecessor. Inclusion records
    # the history; it does not make that opinion current or qualifying support.
    from .validation import _response_covers
    visible_targets = {(collection, identifier) for collection, identifier, _ in readable}
    for info in assessment["judgments"].values():
        target, pin = info["target"], info["ref"]
        if info["role"] != "independent" or info["audit_id"] != audit_id \
                or info["response_state"] != "accepted" \
                or (target["collection"], target["id"]) not in visible_targets:
            continue
        check = derivation.snap.get(pin)
        response = derivation.responses.get(check.body["response_id"]) if check else None
        if response is None or not _response_covers(derivation.snap, response, target):
            continue
        row = candidate(target)
        if pin in row["independent_checks"]:
            continue
        if (pin["collection"], pin["id"], pin["version"]) not in readable:
            row["missing_required_opinion_count"] = row.get("missing_required_opinion_count", 0) + 1
            row["next_action"] = "This read set omits required accepted opinions; obtain a complete reconciliation packet or report a packet-selection limitation."
            continue
        record = db.version("checks", pin["id"], pin["version"])
        row["required_other_opinions"].append({**_opinion(record, pin),
            "freshness": info["freshness"], "superseded": info["superseded"], "exposure": info["exposure"]})
    result["reconciliation_candidates"] = []
    # One template for the role, rather than repeating its fields per target.
    # No evidence, target, decision or rationale is selected for the coordinator.
    result["reconciliation_row_template"] = skeleton(c.BODY_SCHEMAS["reconciliations"])
    result["reconciliation_row_template"]["audit_id"] = audit_id
    for key in sorted(rows):
        row = rows[key]
        for field in ("primary_checks", "independent_checks"):
            row[field].sort(key=lambda pin: (pin["id"], pin["version"]))
        for field in ("primary_opinions", "independent_opinions"):
            row[field].sort(key=lambda entry: (entry["ref"]["id"], entry["ref"]["version"]))
        row["required_other_opinions"].sort(key=lambda entry: (entry["ref"]["id"], entry["ref"]["version"]))
        row["has_both_roles"] = bool(row["primary_checks"] and row["independent_checks"])
        result["reconciliation_candidates"].append(row)
    result["note"] = "primary_checks and independent_checks are current eligible evidence on the exact target. " \
        "required_other_opinions are accepted historical or otherwise nonqualifying opinions that validation " \
        "also requires in the authored independent_checks list; their inclusion does not restore current support. " \
        "has_both_roles records role presence only. Even matching outcome labels require an authored comparison " \
        "of reasoning and conditions; they never establish an agree decision. " \
        "Keep disagreement and explicit succession; author the decision, rationale and any successor_checks. " \
        "Parent, group and use checks are not interchangeable. Acceptance still validates the submitted row."
    return result


def mapping_template(*, source_packet_id, mapping_packet_id, response_id, judgment_indexes=()):
    """Keep worker packet A distinct from private mapping authorization packet B."""
    for name, value in (("source_packet_id", source_packet_id), ("mapping_packet_id", mapping_packet_id),
                        ("response_id", response_id)):
        _identifier(value, name)
    indexes = list(judgment_indexes)
    if any(type(index) is not int or index < 0 for index in indexes) or len(set(indexes)) != len(indexes):
        raise InvalidRequest("judgment_indexes must be distinct nonnegative integers", code="ASSISTANCE_INPUT")
    template = skeleton(c.MAPPING_REQUEST)
    template.update(request_id=new_id("request"), packet_id=mapping_packet_id, response_id=response_id)
    template["entries"] = [dict(skeleton(c.MAPPING_REQUEST.fields["entries"].inner), judgment_index=index)
                           for index in indexes]
    return {"source_packet_id": source_packet_id, "mapping_packet_id": mapping_packet_id,
            "template": template, "entry_shape": describe(c.MAPPING_REQUEST.fields["entries"].inner),
            "note": "A is the original source-only worker packet; preserve its response unchanged. "
                    "B is the private current coordinator packet authorizing mapped targets in its read set. "
                    "Choose each target and source-overlap rationale explicitly. Mapping never changes the "
                    "worker's kind, outcome, reasoning, evidence or reviewed scope. Wrong kinds or incompatible "
                    "targets need a reviewer-authored correction, preserving unresolved concerns. Refine a "
                    "missing inference from source; never invent records only to accept a response. "
                    "All required routes and relevant accepted opinions still need examination and reconciliation."}
