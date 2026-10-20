"""Consolidate local Phase 1 proposals without reading or writing an audit database.

A bundle has a namespace, reviewer, items, connections and examinations. Items
use local_id, kind, label, statement, source={document, locator}, optional
context, and optional unit fields from add-unit. References are a local ID,
{namespace, local_id}, or an existing {collection, id}. A connection has from,
to and reason; its optional type defaults to dependency (context for assumptions).
Examinations have target plus the worker's unchanged reasoning/outcome fields.

The returned material is coordinator assistance, not source-only reviewer input
or accepted scientific work. Exact matching is syntactic, not an equivalence
judgment. Original bundles and conflicting opinions remain available separately.
"""
from __future__ import annotations

from copy import deepcopy

from .authoring import RECORD_DEFINITION, UNIT_DEFINITION
from .canonical import digest
from .contract import ITEM_KINDS, INTERMEDIATE_KINDS, validate_body, validate_shape
from .errors import InvalidRequest
from .ids import valid_id


def _fail(path, message):
    raise InvalidRequest(f"{path}: {message}", code="DRAFT_INPUT")


def _text(value, path):
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a nonempty string")


def _rows(bundle, key, path):
    rows = bundle.get(key, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        _fail(f"{path}/{key}", "must be an array of objects")
    return rows


def _identity(item):
    # Do not let differences in private assumptions disappear behind identical prose.
    unit = item.get("unit", {})
    identity = {"kind": item["kind"], "statement": item["statement"], "source": item["source"],
            "context": item.get("context", ""),
            "scope": {key: unit.get(key, []) for key in ("conditions", "binders", "assumptions")}}
    if "scope_id" in unit:
        identity["scope"]["scope_id"] = unit["scope_id"]
    return identity


def consolidate_drafts(bundles):
    """Return deterministic proposed identities, authoring inputs and preserved work.

    Missing local references remain local limitations; they do not discard valid
    proposals. Repeating an identical bundle is harmless. Different bundles with
    the same namespace require distinct namespaces rather than silent overwrite.
    """
    if not isinstance(bundles, list):
        _fail("drafts", "must be an array of bundles")
    unique = {}
    for index, bundle in enumerate(bundles):
        path = f"drafts/{index}"
        if not isinstance(bundle, dict):
            _fail(path, "must be an object")
        for key in ("namespace", "reviewer"):
            _text(bundle.get(key), f"{path}/{key}")
        namespace = bundle["namespace"]
        if namespace in unique and unique[namespace] != bundle:
            _fail(f"{path}/namespace", "different bundles share this namespace; give each draft its own namespace")
        unique[namespace] = deepcopy(bundle)
    mapping, proposals, origins = {}, {}, {}
    ordered = [unique[key] for key in sorted(unique)]
    for bundle in ordered:
        namespace = bundle["namespace"]
        mapping[namespace] = {}
        for index, item in enumerate(_rows(bundle, "items", namespace)):
            path = f"{namespace}/items/{index}"
            for key in ("local_id", "kind", "label", "statement"):
                _text(item.get(key), f"{path}/{key}")
            if item["kind"] not in ITEM_KINDS:
                _fail(f"{path}/kind", f"expected an existing item kind: {', '.join(ITEM_KINDS)}")
            source = item.get("source")
            if not isinstance(source, dict):
                _fail(f"{path}/source", "requires document and locator")
            for key in ("document", "locator"):
                _text(source.get(key), f"{path}/source/{key}")
            if "context" in item and not isinstance(item["context"], str):
                _fail(f"{path}/context", "must be text describing the source case or local assumptions")
            if not isinstance(item.get("unit", {}), dict):
                _fail(f"{path}/unit", "must be an object of existing add-unit fields")
            local = item["local_id"]
            if local in mapping[namespace]:
                _fail(f"{path}/local_id", "is duplicated within this namespace")
            key = "draft_" + digest(_identity(item))[:32]
            target = {"collection": "items", "id": "itm_" + key}
            mapping[namespace][local] = target
            origin = {"namespace": namespace, "local_id": local, "reviewer": bundle["reviewer"]}
            origins.setdefault(target["id"], []).append((origin, item))
            if target["id"] not in proposals:
                proposals[target["id"]] = {"target": target, "key": key,
                    "kind": item["kind"], "label": item["label"], "statement": item["statement"],
                    "source": deepcopy(source), "context": item.get("context", "")}

    unresolved = []

    def resolve(value, namespace, path):
        if isinstance(value, str):
            reference = {"namespace": namespace, "local_id": value}
        elif isinstance(value, dict) and set(value) == {"namespace", "local_id"}:
            reference = deepcopy(value)
            for key in reference:
                _text(reference[key], f"{path}/{key}")
        elif isinstance(value, dict) and set(value) == {"collection", "id"} \
                and value["collection"] in ("items", "parts") and valid_id(value["id"]):
            return deepcopy(value)
        else:
            _fail(path, "use a local ID, {namespace, local_id}, or existing {collection, id}")
        found = mapping.get(reference["namespace"], {}).get(reference["local_id"])
        if found:
            return deepcopy(found)
        unresolved.append({"path": path, "reference": reference,
                           "reason": "local item was not supplied; preserve the draft and resolve this reference locally"})
        return {"unresolved": reference}

    connections, examinations = {}, []
    for bundle in ordered:
        namespace = bundle["namespace"]
        for index, connection in enumerate(_rows(bundle, "connections", namespace)):
            path = f"{namespace}/connections/{index}"
            _text(connection.get("reason"), f"{path}/reason")
            body = deepcopy(connection)
            body["from"] = resolve(connection.get("from"), namespace, path + "/from")
            body["to"] = resolve(connection.get("to"), namespace, path + "/to")
            supplier = proposals.get(body["from"].get("id"), {})
            body.setdefault("type", "context" if supplier.get("kind") == "assumption" else "dependency")
            if body["type"] not in ("context", "dependency", "definition", "proof_argument"):
                _fail(path + "/type", "expected context, dependency, definition, or proof_argument")
            key = digest(body)
            row = connections.setdefault(key, {"proposal": body, "origins": []})
            row["origins"].append({"namespace": namespace, "index": index})
        for index, examination in enumerate(_rows(bundle, "examinations", namespace)):
            target = resolve(examination.get("target"), namespace, f"{namespace}/examinations/{index}/target")
            examinations.append({"namespace": namespace, "reviewer": bundle["reviewer"],
                                 "target": target, "examination": deepcopy(examination)})

    edges = [connections[key] for key in sorted(connections)]
    owners = {}
    for identity, entries in origins.items():
        for origin, item in entries:
            if "owner" in item:
                owner = resolve(item["owner"], origin["namespace"],
                                f"{origin['namespace']}/{item['local_id']}/owner")
                owners.setdefault(identity, set()).add(owner.get("id"))
            elif item.get("unit", {}).get("owner_id"):
                owners.setdefault(identity, set()).add(item["unit"]["owner_id"])
    authoring = []
    for identity in sorted(proposals):
        proposal = proposals[identity]
        proposal["origins"] = [deepcopy(origin) for origin, _ in origins[identity]]
        for origin, item in origins[identity]:
            unit = deepcopy(item.get("unit", {}))
            # Keep each worker's source-boundary judgments as a separate option.
            option = {"target": proposal["target"], "origin": deepcopy(origin), "context": [],
                      "source_context": item.get("context", ""),
                      "note": "Proposed authoring shape only. Confirm existing identities and source anchors before intake. "
                              "Keep source_context explicit in the exact claim or its supplied setup; no prose is rewritten here."}
            incoming = [edge["proposal"] for edge in edges if edge["proposal"]["to"] == proposal["target"]]
            suppliers, deferred = [], []
            pending = []
            for edge in incoming:
                if edge["type"] == "context":
                    option["context"].append(deepcopy(edge))
                    # A named source assumption supplies setup, not another proof obligation.
                    # Carry its captured statement with the consumer's statement/setup evidence.
                    setup = list(dict.fromkeys(anchor for _, source_item in origins.get(edge["from"].get("id"), [])
                        for anchor in source_item.get("unit", {}).get("statement_anchors", [])))
                    if not setup:
                        pending.append("supply captured statement/setup anchors for the referenced context; no proof of the assumption is requested")
                    elif unit.get("statement_anchors"):
                        unit["statement_anchors"] = list(dict.fromkeys(unit["statement_anchors"] + setup))
                    else:
                        pending.append("capture the claim's own statement anchors together with its referenced setup")
                    continue
                if "unresolved" in edge["from"]:
                    pending.append("resolve the reported supplier's local reference")
                    continue
                supplier = {"target": edge["from"], "type": edge["type"], "reason": edge["reason"]}
                if "needed_form" in edge:
                    supplier["needed_form"] = deepcopy(edge["needed_form"])
                else:
                    upstream = proposals.get(edge["from"].get("id"))
                    if upstream:
                        supplier["needed_form"] = {"form": "verbatim", "text": upstream["statement"]}
                    else:
                        pending.append("supply needed_form for the existing supplier " + edge["from"]["id"])
                        continue
                for name in ("evidence_refs", "substitutions"):
                    if name in edge:
                        supplier[name] = deepcopy(edge[name])
                # Register an owner before its owned prerequisite, then attach
                # this consuming use. The returned examination is unchanged.
                if proposal["target"]["id"] in owners.get(edge["from"].get("id"), ()):
                    deferred.append(supplier)
                else:
                    suppliers.append(supplier)
            if item["kind"] in ("lemma", "proposition", "theorem", "corollary"):
                definition = unit
                definition.update(key=proposal["key"], kind=item["kind"], label=item["label"], statement=item["statement"])
                definition.setdefault("reviewer", origin["reviewer"])
                if suppliers:
                    if "suppliers" in definition:
                        pending.append("choose between unit.suppliers and the separately proposed connections")
                    else:
                        definition["suppliers"] = suppliers
                errors = validate_shape(UNIT_DEFINITION, definition)
                option.update(command="stage1 add-unit", definition=definition, issues=pending + errors)
            else:
                passages = [{"role": "statement", "anchor_id": a} for a in unit.get("statement_anchors", [])]
                passages += [{"role": "proof", "anchor_id": a} for a in unit.get("proof_anchors", [])]
                owner = resolve(item["owner"], origin["namespace"], f"{origin['namespace']}/{item['local_id']}/owner") \
                    if "owner" in item else {"collection": "items", "id": unit["owner_id"]} if unit.get("owner_id") else None
                body = {"kind": item["kind"], "label": item["label"], "caption": item["label"],
                        "statement": {"form": "verbatim", "text": item["statement"]}, "passages": passages,
                        "aliases": unit.get("aliases", []), "uncertainty": None, "origin": "source",
                        "owner_id": owner.get("id") if owner else None, "scope_id": None}
                if "proof_idea" in unit:
                    body["proof_idea"] = unit["proof_idea"]
                if item["kind"] in INTERMEDIATE_KINDS and not body["owner_id"]:
                    pending.append("identify the existing proof unit that owns this intermediate result")
                if not passages:
                    pending.append("capture statement source locators as existing anchor IDs")
                definition = deepcopy(unit)
                definition.update(key=proposal["key"], kind=item["kind"], label=item["label"], statement=item["statement"])
                definition.setdefault("reviewer", origin["reviewer"])
                if owner and owner.get("id"):
                    definition["owner_id"] = owner["id"]
                if "derivation_in" in item:
                    selected = resolve(item["derivation_in"], origin["namespace"],
                                       f"{origin['namespace']}/{item['local_id']}/derivation_in")
                    owning = proposals.get(selected.get("id"))
                    if owning:
                        definition["argument_id"] = "arg_" + owning["key"]
                    else:
                        pending.append("supply unit.argument_id for the existing selected owning argument")
                if not definition.get("separate_examination"):
                    definition.pop("proof_complete", None)
                if suppliers:
                    if "suppliers" in definition:
                        pending.append("choose between unit.suppliers and the separately proposed connections")
                    else:
                        definition["suppliers"] = suppliers
                schema = UNIT_DEFINITION if definition.get("separate_examination") else RECORD_DEFINITION
                if definition.get("suppliers") and not definition.get("argument_id") and not definition.get("separate_examination"):
                    pending.append("select the grouped derivation with argument_id or a separate proof unit before adding its premises")
                if definition.get("argument_id") and not definition.get("proof_anchors"):
                    pending.append("supply the selected local derivation's proof_anchors")
                if definition.get("argument_id") and definition.get("separate_examination"):
                    pending.append("choose grouped derivation or separate proof unit")
                errors = validate_shape(schema, {k: v for k, v in definition.items() if k != "separate_examination"})
                if item["kind"] == "external_result" or errors:
                    # Incomplete readable drafts still have the familiar item
                    # proposal; their original evidence and judgments remain.
                    option.update(command="template", collection="items", record_id=identity,
                                  body=body, issues=pending + validate_body("items", body))
                    if item["kind"] != "external_result":
                        option.update(definition=definition, issues=pending + errors)
                else:
                    option.update(command="stage1 add-record", definition=definition, issues=pending)
            if deferred:
                proof = unit.get("proof_anchors", [])
                if not proof:
                    option["issues"].append("capture the owning proof before attaching its owned prerequisite")
                option["deferred_connections"] = [{"op": "create", "collection": "uses",
                    "id": "use_draft_" + digest({"from": supplier["target"], "to": proposal["target"],
                                                  "supplier": supplier})[:32],
                    "expected_version": None,
                    "body": {"from": supplier["target"], "to": proposal["target"],
                        "type": supplier.get("type", "dependency"), "reason": supplier["reason"],
                        "needed_form": supplier["needed_form"], "substitutions": supplier.get("substitutions", []),
                        "group_id": "grp_" + proposal["key"],
                        "evidence_refs": supplier.get("evidence_refs", proof), "regime": None, "uncertainty": None}}
                    for supplier in deferred]
            option["authoring_shape_ready"] = not option["issues"]
            authoring.append(option)
    # Supply a useful authoring order, without requiring proof examinations in
    # that order or pretending that cyclic proposals form a writable unit batch.
    prerequisites = {identity: set() for identity in proposals}
    for edge in edges:
        body = edge["proposal"]
        before, after = body["from"].get("id"), body["to"].get("id")
        if before in proposals and after in proposals and before != after and after not in owners.get(before, ()):
            prerequisites[after].add(before)
    for option in authoring:
        owner = option.get("definition", option.get("body", {})).get("owner_id")
        if owner in proposals and owner != option["target"]["id"]:
            prerequisites[option["target"]["id"]].add(owner)
    remaining, order = set(proposals), []
    while remaining:
        ready = sorted(identity for identity in remaining if not prerequisites[identity] & remaining)
        if not ready:
            break
        order.extend(ready)
        remaining.difference_update(ready)
    return {"kind": "local-draft-consolidation", "mapping": mapping,
            "items": [proposals[key] for key in sorted(proposals)], "connections": edges,
            "authoring": authoring, "examinations": examinations,
            "authoring_order": order, "cyclic_items": sorted(remaining),
            "deferred_connections": [{"origin": deepcopy(option["origin"]), "edit": deepcopy(row)}
                                     for option in authoring for row in option.get("deferred_connections", [])],
            "unresolved_references": unresolved, "source_drafts": ordered,
            "note": "Coordinator proposals only: no database mutation, scientific adoption, source verification, "
                    "or independent-review credit. Choose one authoring option per canonical item after checking "
                    "existing records. Source-only context connections are not proof-supplier edges. Cyclic items "
                    "need existing record/link authoring, not repeated add-unit retries. Resolve affected questions "
                    "without re-examining unrelated work."}


__all__ = ["consolidate_drafts"]
