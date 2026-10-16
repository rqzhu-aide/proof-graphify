"""Uncommitted authoring assistance derived from the live validation contract.

These views supply shapes and candidate identities, never mathematical decisions.
Worker guidance is deliberately independent of the private assignment manifest.
"""
from __future__ import annotations

from copy import deepcopy

from . import CONTRACT_VERSION, PROTOCOL_VERSION
from . import contract as c
from .errors import ConflictError, InvalidRequest
from .ids import new_id, valid_id

FINDING_CARD_NOTE = (
    "Use the severity rubric in evidence-and-verdicts.md for established issues; "
    "omitted severity is unrated. Inconclusive limitations have no inferred defect severity. "
    "Write description as one short issue sentence with one decisive formula or exact witness when useful. "
    "Write impact_reason as one short sentence stating what remains valid and what changes, "
    "including an already apparent correction when useful. "
    "Use explicit LaTeX delimiters and JSON-escaped backslashes as in mathematical-checking.md. "
    "Keep longer derivations and inspection-process details in the existing examination reasoning; "
    "no separate card-writing pass. "
    "Keep source locators in the existing evidence references.")


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


def authoring_template(collection, *, packet_id, record_id=None, db=None):
    """Return an uncommitted create or current-record replacement envelope.

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
    current = db.head(collection, identifier) if db is not None and record_id is not None else None
    if current is not None and current.retired:
        raise InvalidRequest(f"{collection}:{identifier} is retired; identifiers are not reused",
                             code="ASSISTANCE_RETIRED", records=[current.pinned])
    if current is not None:
        from .acceptance import _guard_changes, _read_set_conflicts
        from .packets import source_context_digest
        packet = db.packet(packet_id)
        target = current.ref if collection in ("papers", "items", "parts", "audits") else current.body.get("target")
        if not isinstance(target, dict) or target.get("collection") not in ("items", "parts"):
            target = current.ref if collection in ("papers", "items", "parts", "audits") else db.heads("papers")[0].ref
        edit_mode = "reconcile" if collection == "findings" else "author"
        retry = {"command": f"get DB --target {target['collection']}:{target['id']} --mode {edit_mode} --out PACKET.json",
                 "targets": [target], "mode": edit_mode}
        manifest = packet["manifest"] if packet else {}
        allowed_modes = ("author", "primary", "reconcile") if collection == "findings" else ("author", "primary")
        authorized = (manifest.get("mode") in allowed_modes and not manifest.get("work")
                      and current.ref in manifest.get("write_scope", [])
                      and current.pinned in manifest.get("read_set", []))
        if not authorized:
            raise ConflictError(f"the packet cannot authorize this current replacement; request a current {edit_mode} packet",
                                code="ASSISTANCE_PACKET", records=[current.pinned], retry=retry)
        conflicts = []
        _read_set_conflicts(db, manifest, conflicts)
        if conflicts or _guard_changes(db, manifest) or manifest["source_context_digest"] != source_context_digest(db):
            raise ConflictError("the packet's inputs changed; refresh it before editing current contents",
                                code="ASSISTANCE_PACKET", records=conflicts, retry=retry)
        body = deepcopy(current.body)
        entry = skeleton(c.EDIT_REPLACE)
        entry["expected_version"] = current.version
    else:
        body = skeleton(c.BODY_SCHEMAS[collection])
        if collection == "application_details":
            body["use_id"] = identifier
        entry = skeleton(c.EDIT_CREATE)
    entry.update(collection=collection, id=identifier, body=body)
    batch = skeleton(c.BATCH)
    batch.update(request_id=new_id("request"), packet_id=packet_id, edits=[entry])
    note = (f"Uncommitted {entry['op']} template. " +
            ("Edit only the intended fields in the saved current body. " if current is not None else
             "Fill blank scientific fields and references before submission. ") +
            "All displayed fields are required unless listed as optional; nullable does not mean optional.")
    if collection == "audits":
        note += (" Excluding an item removes that result and its parts from required work. "
                 "Keep an unavailable proof of a requested result in scope as a source limitation "
                 "or unresolved examination; missing material alone does not authorize narrowing the request.")
    if collection == "findings":
        note += " " + FINDING_CARD_NOTE
    return {"template": batch, "body_shape": describe(c.BODY_SCHEMAS[collection]), "note": note}


ROLE_REFERENCES = {
    "primary": ("primary-checker.md", "mathematical-checking.md", "evidence-and-verdicts.md"),
    "independent": ("independent-checker.md", "mathematical-checking.md", "evidence-and-verdicts.md"),
    "reconcile": ("reconciler.md", "evidence-and-verdicts.md"),
}


def worker_guidance(mode, *, composition=False):
    guidance = _response_guidance(mode)
    guidance["reference_files"] = list(ROLE_REFERENCES[mode])
    if (mode == "primary" and composition) or mode == "independent":
        guidance["examination_note"] = (
            "Extent is coverage, not outcome. After examining all assigned supplied material, including a proof "
            "omission (outcome=gap), use whole_unit and empty omissions. proof_gap is a primary finding category. "
            "Assessed external unavailability may finish inconclusive. For unexamined assigned material, "
            "including necessary unreadable passages, use partial and name it in omissions. Follow scaffold types. "
            "Preserve adverse reasoning and limitations. For a new response, leave conditions empty unless "
            "naming a restriction explicitly listed in the applicable scopes.conditions; copy such entries verbatim. "
            "This field is not a summary of the supplied setup. "
            "If support needs an additional restriction, explain it in reasoning and do not mark the unchanged question supported. "
            "Do not remove a substantive restriction from the reasoning to obtain support. Never clear omissions for acceptance. "
            + ("Put conclusion concerns in judgment reasoning and outcome, others in coverage_note. " if mode == "independent" else
               "Put defects and uncertainty in reasoning or findings. ") +
            "No proof, repair or counterexample construction is required. Unrelated discoveries do not expand "
            "scope; relevant dependencies may need coordinator attention.")
    if mode == "primary" and composition:
        guidance["examination_note"] += (
            " Assess important applications together; distinguish meaningful local outcomes and missing suppliers. "
            "Local checks and coverage rows are optional; do not invent omitted-proof routes.")
    if mode == "independent":
        guidance["evidence_note"] = (
            "source-navigation.json optionally locates all packet anchors by source and version, including "
            "prerequisites and continuations. Use only packet-registered IDs in evidence_refs. Other inspected "
            "material may be cited by traceable locators in reasoning or coverage_note; that prose does not bind "
            "evidence or establish support. Fix harmless citation formatting locally. When support relies on "
            "newly consumed evidence, ask the coordinator to capture and extend context for the unchanged question. "
            "Return a response naming the extended packet; reuse current reasoning and already examined passages. "
            "Examine only material still unexamined or materially changed, or leave support unresolved.")
    if mode == "primary":
        guidance["authoring_note"] = (
            "The coordinator alone writes the shared database. Source-based local drafts may precede canonical "
            "graph IDs. Report a missing dependency by its source locator in reasoning or a separate draft; "
            "do not invent unknown typed references. A missing graph identity alone is not a mathematical gap.")
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
                    "target": {"source_anchor_id": "<supplied statement or proof anchor ID>",
                               "description": "The supplied reasoning for the requested conclusion, including any omission."}},
                "note": "Use the scaffold; required nullable fields stay present. "
                        "Answer the exact neutral question and preserve its question_id; the enclosing theorem "
                        "supplies context. "
                         "The scaffold's source target is mapped by the script to that exact assignment. "
                         "Delivery may also include matching original source pages, source-only images and role reference files. "
                         "Source-only excludes primary judgments, not original sources. Reuse readable evidence; "
                         "if a consequential symbol remains unreadable, identify the local limitation or seek clarification. "
                        "Replace the example's anchor placeholder and author all scientific fields. "
                        "The coordinator maps your unchanged response. Preserve extra prerequisite concerns "
                        "in coverage_note; concerns undermining the assigned conclusion belong in its reasoning "
                        "and outcome. Do not silently add hypotheses. Context extension keeps the same obligation; "
                        "a new target outside scope is a disclosed finding, not an automatic new assignment. "
                        "An unresolved judgment needs a reason, not a newly constructed proof or counterexample."}
    if mode == "primary":
        return {"mode": mode, "response_shape": describe(c.WORK_PRIMARY_RESPONSE),
                "optional_finding_example": _finding_example(),
                "finding_card_note": FINDING_CARD_NOTE,
                "note": "Use assigned task IDs; required nullable fields stay present. "
                        "Keep each scaffold row's type: source_fidelity uses result, note and evidence_refs; "
                        "check uses state, outcome, reasoning and its check fields. Do not fill source rows as checks. "
                        "Return the rows actually examined; leave missing work pending rather than filling defaults. "
                        "Author the judgments. Finding rows create new issues. After an accepted submission, "
                        "retain unchanged finding IDs from receipt.changed entries with collection=findings, "
                        "even if the reused packet predates them; cite them in reasoning and leave new findings empty. "
                        "record_map and existing_check_refs are not finding-ID fields. An atomically rejected "
                        "submission committed no findings: retain its adverse concerns on retry. Add only "
                        "materially distinct concerns; keep no-defect observations in reasoning. A renewed "
                        "check alone does not resolve a finding."}
    if mode == "reconcile":
        from .controller import INTEGRATION_RESPONSE
        return {"mode": mode, "response_shape": describe(INTEGRATION_RESPONSE),
                "optional_finding_example": _finding_example(),
                "finding_card_note": FINDING_CARD_NOTE,
                "note": "Use the integration scaffold's unit task IDs; scripts select current opinion references. "
                         "Use the coordinator reconciliation candidate whose integration_task_ids contains the scaffold task_id. "
                         "Return only authored integrations; omit undecided rows. An unresolved decision needs an authored rationale. "
                         "Compare saved reasoning and conditions and author the decision and rationale. "
                         "Adopting a saved finding is integration; disagreement does not require another examination. "
                         "Use adopt_independent to adopt the saved independent conclusion, adopt_primary to "
                         "retain the saved primary conclusion, agree for compatible opinions, or unresolved. "
                         "For adopt aliases, omit successor_checks or leave it empty; scripts select the saved opinions. "
                         "Canonical primary_revised and independent_revised remain accepted for existing responses "
                         "and explicit saved-check selection. "
                         "Optional top-level findings use the example and related integration task IDs; scripts link current opinions. "
                         "Omit findings or leave it empty when none is new. A changed disposition of an existing finding "
                         "also needs that identified finding updated through review reconcile; a rationale alone does not update it. "
                        "Stage 2 generates the submission envelope. If response_dispositions are listed, explain "
                        "how the preserved extra rows are handled, retaining material unresolved concerns. "
                        "Do not fabricate an independent examination to repair a peripheral response field."}
    raise InvalidRequest(f"unknown assistance mode {mode!r}", code="ASSISTANCE_MODE")


def _finding_example():
    """Optional scientific content; this example is never a required response row."""
    return {"target": {"collection": "arguments", "id": "<assigned target ID>"},
            "category": "inconclusive", "description": "<the new material concern>",
            "evidence_refs": [], "related_task_ids": ["<related task ID>"],
            "existing_check_refs": [], "affected_uses": [],
            "impact_reason": "<its consequence for the assigned conclusion>"}


def _opinion(record, pin):
    """Reference material from the named version, never a new check or verdict."""
    return {"ref": deepcopy(pin), **{field: deepcopy(record.body[field]) for field in (
        "target", "kind", "role", "reviewer", "state", "outcome", "reasoning", "conditions",
        "evidence_refs", "next_action", "supersedes")},
        **{key: deepcopy(record.body[key]) for key in ("extent", "omissions") if key in record.body}}


def _partial_primary_predecessors(derivation, assessment, tasks):
    """Current partial opinions needed by these pending coherent primary tasks."""
    if derivation.audit.body["protocol_version"] != PROTOCOL_VERSION:
        return []
    pending = {row["id"] for row in assessment["obligations"]
               if row["required"] and not row["satisfied"] and row["role"] == "primary"
               and row["kind"] == "composition"}
    assigned = {(task["target"]["collection"], task["target"]["id"]): task
                for task in tasks if task["id"] in pending and task["role"] == "primary"
                and task["kind"] == "composition" and task["action"] == "check"}
    candidates = []
    for info in assessment["judgments"].values():
        task = assigned.get((info["target"]["collection"], info["target"]["id"]))
        if task is None or info["audit_id"] != assessment["audit_id"] \
                or info["role"] != "primary" or info["kind"] != "composition" \
                or info["state"] != "complete" or info["freshness"] != "current" \
                or info.get("extent") != "partial" or info["superseded"]:
            continue
        record = derivation.snap.get(info["ref"])
        if record is not None and not record.retired:
            candidates.append((task, info["ref"]))
    return candidates


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
        partial_pins = {(pin["id"], pin["version"]) for _, pin in
                        _partial_primary_predecessors(derivation, assessment, tasks)}
        candidates = []
        for task, pin in renewal_checks:
            info = assessment["judgments"].get(f"checks:{pin['id']}")
            if info is None or info["ref"] != pin or info["superseded"] \
                    or (info["freshness"] not in ("needs_review", "historical")
                        and (pin["id"], pin["version"]) not in partial_pins):
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
                "These completed checks have changed inputs or leave current examination coverage partial. "
                "Their pinned opinions are reference material, not new proof credit. Pass only the needed "
                "predecessor context to the assigned primary checker. Examine only changed or unexamined "
                "material, or explicitly correct misclassified coverage when the saved examination establishes it. "
                "Author the successor with explicit supersedes; do not infer whole-unit coverage. "
                "Preserve negative outcomes, conditions and reasoning unless the examiner explicitly revises "
                "them. Submit the response unchanged; keep this inventory out of independent delivery.")
    if mode != "reconcile":
        return result
    rows = {}
    coherent = derivation.audit.body["protocol_version"] == "coherent-proof-audit/1"
    from .coherent import unit_targets
    units = [(task["target"], unit_targets(derivation.snap, task["target"]))
             for task in tasks if coherent and task["kind"] == "reconciliation"]

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
        if coherent and not derivation.integration_eligible(info):
            continue
        if not coherent and info["role"] == "independent" and not derivation.independent_usable(info):
            continue
        row = candidate(info["target"])
        row[f"{info['role']}_checks"].append(deepcopy(pin))
        record = db.version("checks", pin["id"], pin["version"])
        row[f"{info['role']}_opinions"].append(_opinion(record, pin))
        if info["role"] == "independent" and record.body["response_id"]:
            response = db.head("responses", record.body["response_id"])
            if response and (response.body.get("pending_judgments") or response.body["coverage_note"].strip()):
                row.setdefault("retained_concerns", []).append({"response_ref": response.pinned,
                    "pending_judgments": response.body.get("pending_judgments", []),
                    "coverage_note": response.body["coverage_note"],
                    "intake_diagnostics": response.body.get("intake_diagnostics", []),
                    "original_blob": response.body["original_blob"]})
        if info["role"] == "independent":
            for unit, members in units:
                if info["target"] == unit or info["target"] not in members:
                    continue
                owner = candidate(unit)
                owner["required_other_opinions"].append({**_opinion(record, pin),
                    "freshness": info["freshness"], "superseded": info["superseded"], "exposure": info["exposure"]})
                for concern in row.get("retained_concerns", []):
                    if concern not in owner.setdefault("retained_concerns", []):
                        owner["retained_concerns"].append(concern)
    # Reconciliation validation requires every accepted opinion on the exact
    # target, including an explicitly superseded predecessor. Inclusion records
    # the history; it does not make that opinion current or qualifying support.
    from .validation import _response_covers
    visible_targets = {(collection, identifier) for collection, identifier, _ in readable}
    for info in (() if coherent else assessment["judgments"].values()):
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
    if coherent:
        result["note"] = ("These are current eligible opinions on each exact unit. Scripts attach their references "
            "when the integration scaffold is submitted. Compare the reasoning and conditions, preserve retained "
            "concerns, and state unresolved disagreements. Use adopt_independent or adopt_primary for the adopted "
            "side, with successor_checks empty or omitted. Matching outcome labels alone do not establish agreement.")
        return result
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
                    "worker's kind, outcome, reasoning, evidence or reviewed scope."}
