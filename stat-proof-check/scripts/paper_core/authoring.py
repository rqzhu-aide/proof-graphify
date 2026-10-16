"""Save a coherent written proof without manually pairing its storage records."""
from __future__ import annotations

import json
from copy import deepcopy

from . import CONTRACT_VERSION, PROTOCOL_VERSION
from .acceptance import accept, apply_batch
from .canonical import digest
from .contract import Arr, BINDER, Bool, Enum, Id, Int, INTERMEDIATE_KINDS, Obj, STATEMENT, SUBSTITUTION, TARGET, Str, validate_shape
from .errors import ConflictError, InvalidRequest
from .ids import valid_id
from .packets import NO_PROOF_CUE, get_packet
from .semantics import related

UNIT_DEFINITION = Obj({
    "key": Str(nonempty=True), "kind": Enum(("theorem", "lemma", "proposition", "corollary") + INTERMEDIATE_KINDS),
    "label": Str(nonempty=True), "statement": Str(nonempty=True),
    "statement_anchors": Arr(Id("anchors"), nonempty=True), "proof_anchors": Arr(Id("anchors")),
    "proof_complete": Bool(), "source_matched": Bool(), "source_note": Str(nonempty=True),
    "aliases": Arr(Str(nonempty=True)), "conditions": Arr(Str(nonempty=True)), "binders": Arr(BINDER),
    "assumptions": Arr(TARGET), "reviewer": Str(nonempty=True), "owner_id": Id("items"),
    "suppliers": Arr(Obj({"target": TARGET, "reason": Str(nonempty=True), "needed_form": STATEMENT,
        "type": Enum(("dependency", "definition", "proof_argument")), "substitutions": Arr(SUBSTITUTION),
        "evidence_refs": Arr(Id("anchors"))}, optional=("type", "substitutions", "evidence_refs"))),
    "proof_spans": Arr(Obj({"anchor_id": Id("anchors"), "start_offset": Int(0), "end_offset": Int(0)}), nonempty=True),
}, optional=("aliases", "conditions", "binders", "assumptions", "reviewer", "suppliers", "proof_spans", "owner_id"))

RECORD_DEFINITION = Obj({
    **{key: value for key, value in UNIT_DEFINITION.fields.items()
       if key not in ("proof_complete", "proof_spans")},
    "kind": Enum(("assumption", "definition") + INTERMEDIATE_KINDS),
    "argument_id": Id("arguments"), "scope_id": Id("scopes", nullable=True),
}, optional=("aliases", "conditions", "binders", "assumptions", "reviewer", "suppliers", "owner_id",
             "proof_anchors", "argument_id", "scope_id"))


def _edit(collection, identity, body):
    return {"op": "create", "collection": collection, "id": identity, "expected_version": None, "body": body}


def _live(db, collection, identity):
    record = db.head(collection, identity)
    if record is None or record.retired:
        raise InvalidRequest(f"unknown live {collection}:{identity}")
    return record


def create_unit(db, definition: dict) -> dict:
    """Author-confirmed exact claim, written proof if supplied, and applications.

    This records the author's source judgments, never a mathematical verdict.
    Existing units are corrected through ordinary versioned edits.
    """
    if not isinstance(definition, dict):
        raise InvalidRequest("a unit definition must be an object")
    errors = validate_shape(UNIT_DEFINITION, definition)
    if errors:
        raise InvalidRequest("invalid unit definition", records=errors)
    required = {"key", "kind", "label", "statement", "statement_anchors", "proof_anchors",
                "proof_complete", "source_matched", "source_note"}
    allowed = required | {"aliases", "conditions", "binders", "assumptions", "suppliers", "proof_spans", "reviewer", "owner_id"}
    if required - definition.keys() or definition.keys() - allowed:
        raise InvalidRequest("unit definition fields are invalid", records=[{
            "missing": sorted(required - definition.keys()), "unknown": sorted(definition.keys() - allowed)}])
    key = definition["key"]
    if not valid_id(key) or len(key) > 80:
        raise InvalidRequest("unit key must be a stable short identifier, for example theorem_1")
    internal = definition["kind"] in INTERMEDIATE_KINDS
    if internal != bool(definition.get("owner_id")):
        raise InvalidRequest("an intermediate proof unit needs owner_id; a major proof unit has no owner_id")
    owner = _live(db, "items", definition["owner_id"]) if internal else None
    if not isinstance(definition["statement"], str) or not definition["statement"].strip():
        raise InvalidRequest("statement is the exact nonempty source claim including its hypotheses")
    for name in ("source_matched", "proof_complete"):
        if not isinstance(definition[name], bool):
            raise InvalidRequest(f"{name} must be an explicit source judgment (true or false)")
    if not isinstance(definition["source_note"], str) or not definition["source_note"].strip():
        raise InvalidRequest("source_note explains the statement comparison and proof boundary, including limitations")
    for name in ("statement_anchors", "proof_anchors"):
        if not isinstance(definition[name], list) or (name == "statement_anchors" and not definition[name]) \
                or not all(isinstance(a, str) for a in definition[name]):
            raise InvalidRequest(f"{name} must contain located captured passages")
    statement_only = not definition["proof_anchors"]
    if statement_only and "proof_spans" in definition:
        raise InvalidRequest("proof_spans requires located proof_anchors")
    anchors = {identity: _live(db, "anchors", identity) for identity in
               dict.fromkeys(definition["statement_anchors"] + definition["proof_anchors"])}
    request_id = "req_unit_" + digest(definition)[:32]
    previous = db.commit_by_request(request_id)
    item, argument, scope, group, spec, boundary, source_review = (
        f"{prefix}_{key}" for prefix in ("itm", "arg", "scp", "grp", "tgt", "bnd", "srv"))
    identities = {"item": item, "argument": None if statement_only else argument, "scope": scope,
                  "group": None if statement_only else group, "target_spec": spec,
                  "boundary": None if statement_only else boundary}
    if statement_only and not definition["proof_complete"]:
        identities["source_issue"] = f"iss_{key}"
    if previous is not None:
        return {"unit": identities, "reused": True, "receipt": json.loads(previous["receipt_json"])}
    if db.head("items", item) is not None:
        raise InvalidRequest("unit key already exists with different input; repair its existing records instead of creating a duplicate",
                             code="UNIT_EXISTS", records=[identities])
    target = {"collection": "items", "id": item}
    reviewer = definition.get("reviewer", "primary")
    proof = list(dict.fromkeys(definition["proof_anchors"]))
    statements = list(dict.fromkeys(definition["statement_anchors"]))
    anchor_pins = [anchors[a].pinned for a in proof]
    source_pins = list({(anchors[a].body["source_id"], anchors[a].body["source_version"]):
                       {"collection": "sources", "id": anchors[a].body["source_id"],
                        "version": anchors[a].body["source_version"]} for a in proof}.values())
    review_body = {"source_refs": source_pins, "anchor_refs": anchor_pins, "purpose": "proof_boundary",
                   "decision": "accepted" if definition["proof_complete"] else "unresolved",
                   "rationale": definition["source_note"], "reviewer": reviewer}
    if "proof_spans" in definition:
        if any(s["anchor_id"] not in proof for s in definition["proof_spans"]):
            raise InvalidRequest("each selected proof span must belong to proof_anchors")
        review_body["proof_spans"] = [{"argument_ref": {"collection": "arguments", "id": argument, "version": 1},
                                       "anchor_ref": anchors[s["anchor_id"]].pinned,
                                       "start_offset": s["start_offset"], "end_offset": s["end_offset"]}
                                      for s in definition["proof_spans"]]
    edits = [
        _edit("items", item, {"kind": definition["kind"], "label": definition["label"], "caption": definition["label"],
             "statement": {"form": "verbatim", "text": definition["statement"]},
             "passages": [{"role": "statement", "anchor_id": a} for a in statements] +
                         [{"role": "proof", "anchor_id": a} for a in proof],
             "aliases": definition.get("aliases", []),
             "uncertainty": NO_PROOF_CUE if statement_only else None, "origin": "source", "owner_id": definition.get("owner_id"),
             "scope_id": scope}),
        _edit("scopes", scope, {"argument_id": None, "parent_id": owner.body.get("scope_id") if owner else None, "assumptions": definition.get("assumptions", []),
             "binders": definition.get("binders", []), "conditions": definition.get("conditions", []), "evidence_refs": statements}),
        _edit("arguments", argument, {"target": target, "label": "Written proof of " + definition["label"],
             "origin": "source", "scope_id": scope, "final_group_id": group, "evidence_refs": proof, "lifecycle": "registered"}),
        _edit("groups", group, {"argument_id": argument, "conclusion": target, "kind": "joint", "scope_id": scope,
             "case_scope_ids": [], "discharges": [], "rationale": "The written proof is examined as one coherent unit.", "evidence_refs": proof}),
        _edit("target_specs", spec, {"target": target, "statement_ref": {**target, "version": 1}, "statement": None,
             "scope_id": scope, "evidence_refs": statements, "state": "registered", "fidelity_ref": None}),
        _edit("source_reviews", source_review, review_body),
        _edit("proof_boundaries", boundary, {"target": target, "argument_ids": [argument], "anchor_refs": anchor_pins,
             "source_review_ref": {"collection": "source_reviews", "id": source_review, "version": 1},
             "state": "complete" if definition["proof_complete"] else "unresolved"}),
        _edit("observations", f"obs_{key}", {"target": target,
             "result": "matched" if definition["source_matched"] else "needs_attention", "reviewer": reviewer,
             "note": definition["source_note"], "evidence_refs": statements})]
    if statement_only:
        # The claim remains in scope, but an absent written proof is not a route.
        edits = [e for e in edits if e["collection"] not in
                 ("arguments", "groups", "source_reviews", "proof_boundaries")]
        if not definition["proof_complete"]:
            edits.append(_edit("source_issues", identities["source_issue"], {
                "source_id": anchors[statements[0]].body["source_id"], "anchor_id": statements[0],
                "category": "missing_source", "description": definition["source_note"],
                "lifecycle": "open", "resolution": None, "reviewer": reviewer}))
    for index, supplier in enumerate(definition.get("suppliers", [])):
        identity = f"use_{key}_{index + 1}"
        edits.append(_edit("uses", identity, {"from": supplier["target"], "to": target,
            "type": supplier.get("type", "dependency"), "reason": supplier["reason"],
            "needed_form": supplier["needed_form"], "substitutions": supplier.get("substitutions", []),
            "group_id": None if statement_only else group,
            "evidence_refs": supplier.get("evidence_refs", proof or statements), "regime": None, "uncertainty": None}))
    papers = db.heads("papers")
    packet = get_packet(db, targets=[papers[0].ref], mode="author")
    receipt = accept(db, request_id=request_id, request_digest=digest(definition), packet_id=packet["packet_id"],
                     edits=edits, command="unit")
    return {"unit": identities, "reused": False, "receipt": receipt}


def create_record(db, definition: dict) -> dict:
    """Register setup or an owned result, optionally selecting its local derivation.

    An existing argument_id explicitly groups the derivation with its owner.
    Merely providing proof passages never creates a separate examination.
    """
    if not isinstance(definition, dict):
        raise InvalidRequest("a record definition must be an object")
    if definition.get("kind") in ("theorem", "lemma", "proposition", "corollary"):
        return create_unit(db, definition)
    if "separate_examination" in definition:
        if definition["separate_examination"] is not True or "argument_id" in definition:
            raise InvalidRequest("separate_examination must be true and cannot accompany argument_id")
        unit = {key: value for key, value in definition.items() if key != "separate_examination"}
        return create_unit(db, unit)
    errors = validate_shape(RECORD_DEFINITION, definition)
    if errors:
        raise InvalidRequest("invalid record definition", records=errors)
    key = definition["key"]
    if not valid_id(key) or len(key) > 80:
        raise InvalidRequest("record key must be a stable short identifier")
    internal = definition["kind"] in INTERMEDIATE_KINDS
    if internal != bool(definition.get("owner_id")):
        raise InvalidRequest("an intermediate record needs owner_id; setup has no owner_id")
    proof = list(dict.fromkeys(definition.get("proof_anchors", [])))
    argument_id = definition.get("argument_id")
    if not internal and (proof or argument_id or definition.get("suppliers")):
        raise InvalidRequest("setup records register source context without a proof or proof suppliers")
    if argument_id and not proof:
        raise InvalidRequest("a grouped derivation needs its selected proof_anchors")
    if definition.get("suppliers") and not argument_id:
        raise InvalidRequest("derivation suppliers need argument_id; consuming uses belong to their own proof")
    statements = list(dict.fromkeys(definition["statement_anchors"]))
    for identity in statements + proof:
        _live(db, "anchors", identity)
    owner = _live(db, "items", definition["owner_id"]) if internal else None
    argument = _live(db, "arguments", argument_id) if argument_id else None
    if argument and argument.body["target"] != owner.ref:
        raise InvalidRequest("argument_id must be an argument of this result's owner")
    inherited_scope = argument.body["scope_id"] if argument else owner.body.get("scope_id") if owner else None
    scope = definition.get("scope_id", inherited_scope)
    private = any(definition.get(field) for field in ("conditions", "binders", "assumptions"))
    if private and "scope_id" in definition:
        raise InvalidRequest("choose an existing scope_id or describe new local conditions, not both")
    item, spec = "itm_" + key, "tgt_" + key
    group = "grp_" + key if argument else None
    scope = "scp_" + key if private else scope
    identities = {"item": item, "argument": argument_id, "scope": scope,
                  "group": group, "target_spec": spec, "boundary": None}
    request_id = "req_record_" + digest(definition)[:32]
    previous = db.commit_by_request(request_id)
    if previous is not None:
        return {"unit": identities, "reused": True, "receipt": json.loads(previous["receipt_json"])}
    if db.head("items", item) is not None:
        raise InvalidRequest("record key already exists with different input; repair its existing records",
                             code="UNIT_EXISTS", records=[identities])
    target = {"collection": "items", "id": item}
    edits = [_edit("items", item, {
        "kind": definition["kind"], "label": definition["label"], "caption": definition["label"],
        "statement": {"form": "verbatim", "text": definition["statement"]},
        "passages": [{"role": "statement", "anchor_id": a} for a in statements] +
                    [{"role": "proof", "anchor_id": a} for a in proof],
        "aliases": definition.get("aliases", []), "uncertainty": None, "origin": "source",
        "owner_id": definition.get("owner_id"), "scope_id": scope}),
        _edit("target_specs", spec, {"target": target, "statement_ref": {**target, "version": 1},
            "statement": None, "scope_id": scope, "evidence_refs": statements,
            "state": "registered", "fidelity_ref": None}),
        _edit("observations", "obs_" + key, {"target": target,
            "result": "matched" if definition["source_matched"] else "needs_attention",
            "reviewer": definition.get("reviewer", "primary"), "note": definition["source_note"],
            "evidence_refs": statements})]
    if private:
        edits.append(_edit("scopes", scope, {"argument_id": argument_id, "parent_id": inherited_scope,
            "assumptions": definition.get("assumptions", []), "binders": definition.get("binders", []),
            "conditions": definition.get("conditions", []), "evidence_refs": statements}))
    if argument:
        edits.append(_edit("groups", group, {"argument_id": argument.id, "conclusion": target,
            "kind": "joint", "scope_id": scope, "case_scope_ids": [], "discharges": [],
            "rationale": definition["source_note"], "evidence_refs": proof}))
    for index, supplier in enumerate(definition.get("suppliers", [])):
        edits.append(_edit("uses", f"use_{key}_{index + 1}", {"from": supplier["target"], "to": target,
            "type": supplier.get("type", "dependency"), "reason": supplier["reason"],
            "needed_form": supplier["needed_form"], "substitutions": supplier.get("substitutions", []),
            "group_id": group, "evidence_refs": supplier.get("evidence_refs", proof),
            "regime": None, "uncertainty": None}))
    packet = get_packet(db, targets=[db.heads("papers")[0].ref], mode="author")
    receipt = accept(db, request_id=request_id, request_digest=digest(definition),
                     packet_id=packet["packet_id"], edits=edits, command="unit")
    return {"unit": identities, "reused": False, "receipt": receipt}


def create_audit(db, *, mode="full", targets=(), exclusions=(), report_path="report.html"):
    if mode not in ("full", "focused", "triage"):
        raise InvalidRequest("mode must be full, focused or triage")
    if mode == "focused" and not targets:
        raise InvalidRequest("focused scope needs explicit targets")
    paper = db.heads("papers")[0]
    body = {"paper_id": paper.id, "mode": mode, "targets": list(targets), "exclusions": list(exclusions),
            "protocol_version": PROTOCOL_VERSION, "independent_required": mode != "triage", "qualification_id": None,
            "global_tasks": [], "report_path": report_path}
    identity = "aud_" + digest(body)[:20]
    if db.head("audits", identity):
        return {"audit_id": identity, "reused": True}
    packet = get_packet(db, targets=[paper.ref], mode="author")
    receipt = apply_batch(db, {"contract_version": CONTRACT_VERSION, "request_id": "req_" + identity,
        "packet_id": packet["packet_id"], "edits": [_edit("audits", identity, body)]})
    return {"audit_id": identity, "reused": False, "receipt": receipt}


def add_targets(db, *, audit_id, expected_version, targets):
    """Append selected existing items to one Full coherent audit, preserving policy.

    Excluded claims are reported without lifting the exclusion. This authors
    scope only; it records no examination and dispatches no reviewer.
    """
    targets = list(targets)
    if (type(expected_version) is not int or expected_version < 1 or not targets
            or any(not isinstance(target, dict) or set(target) != {"collection", "id"}
                   or target["collection"] != "items" or not isinstance(target["id"], str)
                   or not target["id"] for target in targets)):
        raise InvalidRequest("add-targets needs a positive expected version and explicit items:ID targets",
                             code="AUDIT_TARGET_INPUT")
    audit = _live(db, "audits", audit_id)
    if audit.body["mode"] != "full" or audit.body["protocol_version"] != PROTOCOL_VERSION:
        raise InvalidRequest("add-targets requires a Full coherent audit", code="AUDIT_TARGET_MODE")
    paper = _live(db, "papers", audit.body["paper_id"])
    request = {"audit_id": audit_id, "expected_version": expected_version, "targets": targets}
    request_id = "req_extend_" + digest(request)[:32]
    previous = db.commit_by_request(request_id)
    if previous is not None:
        receipt = json.loads(previous["receipt_json"])
        saved = next(pin for pin in receipt["changed"] if pin["collection"] == "audits" and pin["id"] == audit_id)
        if audit.version != saved["version"]:
            raise ConflictError("the addition was saved but the audit was edited afterward")
        omitted = []
        for target in targets:
            if target not in audit.body["targets"] and target not in [row["target"] for row in omitted]:
                omitted.append({"target": deepcopy(target), "reason": "not_added_in_saved_result", "source_anchor_ids": []})
        return {"audit_id": audit_id, "reused": True, "unchanged": False, "receipt": receipt,
                "ineffective_targets": omitted}
    if audit.version != expected_version:
        raise ConflictError("audit version changed", records=[{
            "ref": audit.ref, "expected_version": expected_version, "actual_version": audit.version}])
    additions, ineffective = [], []
    excluded = {tuple(exclusion["target"][key] for key in ("collection", "id"))
                for exclusion in audit.body["exclusions"] if exclusion["target"] is not None}
    excluded_anchors = {identity for exclusion in audit.body["exclusions"]
                        for identity in exclusion["source_anchor_ids"]}
    for target in targets:
        item = _live(db, "items", target["id"])
        anchor_ids = {passage["anchor_id"] for passage in item.body["passages"]}
        for spec in related(db, "target_specs", "/target", target):
            if spec.body["state"] == "registered":
                anchor_ids.update(spec.body["evidence_refs"])
        for route in related(db, "arguments", "/target", target):
            if route.body["lifecycle"] == "registered":
                anchor_ids.update(route.body["evidence_refs"])
                for group in related(db, "groups", "/argument_id", route.ref):
                    anchor_ids.update(group.body["evidence_refs"])
        for group in related(db, "groups", "/conclusion", target):
            route = db.head("arguments", group.body["argument_id"])
            if route is not None and not route.retired and route.body["lifecycle"] == "registered":
                anchor_ids.update(group.body["evidence_refs"])
        for boundary in related(db, "proof_boundaries", "/target", target):
            anchor_ids.update(pin["id"] for pin in boundary.body["anchor_refs"])
        for identity in anchor_ids:
            anchor = _live(db, "anchors", identity)
            source = _live(db, "sources", anchor.body["source_id"])
            if source.body["paper_id"] != paper.id:
                raise InvalidRequest("target source belongs to another paper", code="AUDIT_TARGET_PAPER",
                                     records=[target, source.pinned])
        if target in audit.body["targets"] or target in additions:
            continue
        excluded_passages = sorted(anchor_ids & excluded_anchors)
        if ("items", item.id) in excluded or excluded_passages:
            ineffective.append({"target": deepcopy(target), "reason": "excluded_target" if
                ("items", item.id) in excluded else "excluded_source_anchors",
                "source_anchor_ids": excluded_passages})
            continue
        additions.append(deepcopy(target))
    if not additions:
        return {"audit_id": audit_id, "reused": not ineffective, "unchanged": True, "receipt": None,
                "ineffective_targets": ineffective}
    body = deepcopy(audit.body)
    body["targets"].extend(additions)
    # An author packet cannot replace audits. The existing primary audit packet
    # already authorizes this ordinary versioned replacement.
    packet = get_packet(db, targets=[audit.ref], mode="primary")
    receipt = apply_batch(db, {"contract_version": CONTRACT_VERSION, "request_id": request_id,
        "packet_id": packet["packet_id"], "edits": [{"op": "replace", "collection": "audits", "id": audit_id,
            "expected_version": audit.version, "body": body}]})
    return {"audit_id": audit_id, "reused": False, "unchanged": False, "receipt": receipt,
            "ineffective_targets": ineffective}


def correct_claim(db, item_id, expected_version, correction):
    """Correct one ordinary exact item and its direct specification atomically.

    This is storage correction, not a source comparison or proof examination.
    Advanced specifications remain editable through the ordinary author batch.
    """
    errors = validate_shape(Obj({"item_id": Id("items"), "expected_version": Int(1),
        "correction": Obj({"statement": Str(nonempty=True),
            "statement_anchors": Arr(Id("anchors"), nonempty=True)},
            optional=("statement", "statement_anchors"))}),
        {"item_id": item_id, "expected_version": expected_version, "correction": correction})
    if errors or not correction:
        raise InvalidRequest("correction needs an exact statement and/or nonempty statement_anchors",
                             code="CLAIM_CORRECTION_INPUT", records=errors)
    request = {"item_id": item_id, "expected_version": expected_version, "correction": correction}
    request_digest = digest(request)
    request_id = "req_claim_" + request_digest[:32]
    retry = {"command": f"get DB --target items:{item_id} --mode author --out PACKET.json",
             "targets": [{"collection": "items", "id": item_id}], "mode": "author"}
    previous = db.commit_by_request(request_id)
    if previous is not None:
        receipt = json.loads(previous["receipt_json"])
        expected = list(receipt["changed"])
        if not any(pin["collection"] == "items" and pin["id"] == item_id for pin in expected):
            expected.append({"collection": "items", "id": item_id, "version": expected_version})
        changed = [pin for pin in expected
                   if (head := db.head(pin["collection"], pin["id"])) is None
                   or head.retired or head.version != pin["version"]]
        if changed:
            raise ConflictError("this correction was saved, but its item or specification was edited later; inspect the current records",
                                code="CLAIM_CORRECTION_CONFLICT", records=changed, retry=retry)
        return {"item_id": item_id, "reused": True, "unchanged": False, "receipt": receipt}
    item = _live(db, "items", item_id)
    if item.version != expected_version:
        raise ConflictError("the claim version changed; inspect the current item before correcting it",
                            code="CLAIM_CORRECTION_CONFLICT",
                            records=[{"ref": item.ref, "expected_version": expected_version,
                                      "actual_version": item.version}], retry=retry)
    specs = related(db, "target_specs", "/target", item.ref)
    arguments = related(db, "arguments", "/target", item.ref)
    spec = specs[0] if len(specs) == 1 else None
    pin = spec.body["statement_ref"] if spec else None
    selected = db.version(pin["collection"], pin["id"], pin["version"]) if pin else None
    if (item.body["statement"]["form"] not in ("verbatim", "transcription")
            or item.body.get("origin") != "source" or item.body.get("owner_id") is not None
            or spec is None or spec.body["state"] != "registered" or spec.body["statement"] is not None
            or pin is None or (pin["collection"], pin["id"]) != ("items", item_id)
            or selected is None or selected.retired
            or (selected.body["statement"] != item.body["statement"] and "statement" not in correction)
            or selected.body.get("scope_id") != item.body.get("scope_id")
            or spec.body["scope_id"] != item.body.get("scope_id") or len(arguments) > 1):
        raise InvalidRequest("claim correction needs one direct exact specification of this current item; "
                             "use the author packet and template --id for these existing records",
                             code="CLAIM_CORRECTION_ADVANCED",
                             records=[item.pinned] + [r.pinned for r in specs + arguments], retry=retry)
    body = deepcopy(item.body)
    if "statement" in correction:
        body["statement"]["text"] = correction["statement"]
    if "statement_anchors" in correction:
        anchors = list(dict.fromkeys(correction["statement_anchors"]))
        for identity in anchors:
            _live(db, "anchors", identity)
        current_anchors = [p["anchor_id"] for p in body["passages"] if p["role"] == "statement"]
        if current_anchors != anchors:
            passages, inserted = [], False
            for passage in body["passages"]:
                if passage["role"] == "statement":
                    if not inserted:
                        passages.extend({"role": "statement", "anchor_id": identity} for identity in anchors)
                        inserted = True
                else:
                    passages.append(passage)
            if not inserted:
                passages[0:0] = [{"role": "statement", "anchor_id": identity} for identity in anchors]
            body["passages"] = passages
    item_changed = body != item.body
    evidence_changed = "statement_anchors" in correction and spec.body["evidence_refs"] != anchors
    statement_changed = "statement" in correction and selected.body["statement"] != body["statement"]
    if not item_changed and not evidence_changed and not statement_changed:
        return {"item_id": item_id, "reused": False, "unchanged": True, "receipt": None}
    spec_body = deepcopy(spec.body)
    spec_body["statement_ref"] = {**item.ref, "version": item.version + int(item_changed)}
    if "statement_anchors" in correction:
        spec_body["evidence_refs"] = anchors
    spec_body["fidelity_ref"] = None
    edits = [{"op": "replace", "collection": record.collection, "id": record.id,
              "expected_version": record.version, "body": replacement}
             for record, replacement in ((item, body), (spec, spec_body)) if replacement != record.body]
    packet = get_packet(db, targets=[item.ref], mode="author")
    receipt = accept(db, request_id=request_id, request_digest=request_digest,
                     packet_id=packet["packet_id"], edits=edits, command="apply")
    return {"item_id": item_id, "reused": False, "unchanged": False, "receipt": receipt}
