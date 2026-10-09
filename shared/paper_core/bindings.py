"""Evidence bindings generated when assessment records are accepted (record-contract 6).

A binding pins the record versions and facets a judgment consumed, plus the
membership digests of the relations it depended on, all computed on the
prospective (post-batch) state. Outgoing consumers are never part of a
supplier's binding.
"""
from __future__ import annotations

from .refs import facet_digests, membership_digest, relation_members, setup_digest
from .semantics import application, target_spec, boundaries
from .canonical import digest

COHERENT_PROTOCOL = "coherent-proof-audit/1"


def coherent_unit_inputs(state, argument_id):
    """Substantive unit inputs, independent of optional graph detail and coverage."""
    argument = state.live("arguments", argument_id)
    if argument is None:
        return None
    b = _Builder(state)
    b.statement(argument.body["target"])
    b.scope_chain(argument.body["scope_id"])
    anchor_ids = set(argument.body["evidence_refs"])
    suppliers, visited, application_inputs, inference_inputs = [], set(), [], []
    for c, identity, _ in state.relation_members("groups_in_argument", argument.ref):
        group = state.live(c, identity)
        if group is None:
            continue
        inference_inputs.append({"ref": group.pinned, "digest": coherent_group_digest(state, group)})
        # A selected local derivation includes its exact conclusion and located
        # evidence. Ownership and consuming applications alone select no proof.
        if group.body["conclusion"] != argument.body["target"]:
            conclusion = state.live(group.body["conclusion"]["collection"], group.body["conclusion"]["id"])
            if conclusion is not None:
                anchor_ids.update(p["anchor_id"] for p in conclusion.body["passages"]
                                  if p["role"] in ("statement", "definition"))
            anchor_ids.update(group.body["evidence_refs"])
        b.scope_chain(group.body["scope_id"])
        for scope_id in group.body["case_scope_ids"] + group.body["discharges"]:
            b.scope_chain(scope_id)
        suppliers.extend(state.live(uc, ui) for uc, ui, _ in state.relation_members("uses_in_group", group.ref))
    while suppliers:
        use = suppliers.pop()
        if use is None or use.key in visited:
            continue
        visited.add(use.key)
        application_inputs.append({"ref": use.pinned, "digest": coherent_application_digest(state, use)})
        ref = use.body["from"]
        supplier = state.live(ref["collection"], ref["id"])
        if supplier is None:
            continue
        from .contract import MAJOR_KINDS
        if supplier.collection == "parts" or supplier.body["kind"] in MAJOR_KINDS:
            b.statement(ref)
            if use.body["type"] == "proof_argument":
                b.borrowed_proof(ref)
        else:
            if use.body["type"] == "proof_argument":
                b.borrowed_proof(ref)
            b.scope_chain(supplier.body.get("scope_id"))
            suppliers.extend(state.live(c, i) for c, i, _ in state.relation_members("incoming_uses", ref))
            for c, i, _ in state.relation_members("arguments_for_target", ref):
                route = state.live(c, i)
                if route is None:
                    continue
                for gc, gi, _ in state.relation_members("groups_in_argument", route.ref):
                    group = state.live(gc, gi)
                    if group:
                        suppliers.extend(state.live(uc, ui) for uc, ui, _ in state.relation_members("uses_in_group", group.ref))
    target = state.live(argument.body["target"]["collection"], argument.body["target"]["id"])
    if target:
        anchor_ids.update(p["anchor_id"] for p in target.body["passages"])
    selections = []
    from .proof_spans import reviewed_spans
    for boundary in boundaries(state, argument_id):
        pin = boundary.body["source_review_ref"]
        review = state.version("source_reviews", pin["id"], pin["version"])
        spans = reviewed_spans(state, review, argument, boundary.body["anchor_refs"]) if review else None
        selections.append({"state": boundary.body["state"], "spans": spans,
                           "anchors": boundary.body["anchor_refs"]})
        anchor_ids.update(ref["id"] for ref in boundary.body["anchor_refs"])
    b.anchors(sorted(anchor_ids), "source")
    inputs = b.result(None)["records"]
    scientific = [[row["ref"]["collection"], row["ref"]["id"], row["facet"], row["digest"]] for row in inputs]
    return {"argument_ref": argument.pinned, "target_ref": argument.body["target"],
            "scientific_inputs_digest": digest({"target": argument.body["target"],
                "origin": argument.body["origin"], "scope_id": argument.body["scope_id"],
                "inputs": scientific, "selections": selections}),
            "application_inputs": sorted(application_inputs, key=lambda row: row["ref"]["id"]),
            "inference_inputs": sorted(inference_inputs, key=lambda row: row["ref"]["id"]),
            "final_inference_digest": coherent_group_digest(state, state.live("groups", argument.body["final_group_id"]))
                if argument.body["final_group_id"] else None,
            "source_evidence_refs": [state.live("anchors", aid).pinned for aid in sorted(anchor_ids)
                                     if state.live("anchors", aid) is not None],
            "consumed_inputs": inputs}


def coherent_application_digest(state, use):
    def statement_meaning(ref):
        statement = state.live(ref["collection"], ref["id"])
        if statement is None:
            return None
        spec = target_spec(state, ref)
        exact = spec.body["statement"] if spec else None
        if spec and exact is None and spec.body["statement_ref"]:
            pin = spec.body["statement_ref"]
            original = state.version(pin["collection"], pin["id"], pin["version"])
            exact = original.body["statement"] if original else None
        return exact or statement.body["statement"]
    detail = application(state, use)
    return digest({"from": statement_meaning(use.body["from"]), "to": statement_meaning(use.body["to"]),
        "type": use.body["type"], "needed_form": detail.get("needed_form"),
        "substitutions": detail.get("substitutions", []), "regime": use.body.get("regime")})


def coherent_group_digest(state, group):
    if group is None:
        return None
    def scope_meaning(scope_id):
        result, seen = [], set()
        while scope_id and scope_id not in seen:
            seen.add(scope_id)
            scope = state.live("scopes", scope_id)
            if scope is None:
                result.append(None)
                break
            assumptions = []
            for ref in scope.body["assumptions"]:
                record = state.live(ref["collection"], ref["id"])
                assumptions.append(record.body["statement"] if record else None)
            result.append({"conditions": scope.body["conditions"], "binders": scope.body["binders"],
                           "assumptions": assumptions})
            scope_id = scope.body["parent_id"]
        return result
    ref = group.body["conclusion"]
    conclusion = state.live(ref["collection"], ref["id"])
    spec = target_spec(state, ref)
    exact = spec.body["statement"] if spec else None
    if spec and exact is None and spec.body["statement_ref"]:
        pin = spec.body["statement_ref"]
        original = state.version(pin["collection"], pin["id"], pin["version"])
        exact = original.body["statement"] if original else None
    return digest({"kind": group.body["kind"], "conclusion": exact or (conclusion.body["statement"] if conclusion else None),
        "scope": scope_meaning(group.body["scope_id"]),
        "cases": [scope_meaning(identity) for identity in group.body["case_scope_ids"]],
        "discharges": [scope_meaning(identity) for identity in group.body["discharges"]]})


def _coherent_check(b, body):
    return body.get("kind") == "composition" and body["target"]["collection"] == "arguments" \
        and (body.get("protocol_version") == COHERENT_PROTOCOL or
             ((audit := b.state.live("audits", body.get("audit_id"))) is not None
              and audit.body["protocol_version"] == COHERENT_PROTOCOL))

BOUND_COLLECTIONS = ("checks", "observations", "reconciliations", "reuse_decisions", "source_reviews")


class _Builder:
    def __init__(self, state):
        self.state = state
        self.records = {}
        self.relations = {}
        self.statements_seen = set()
        self.scopes_seen = set()

    def add(self, collection, id, facet, *, version=None):
        if id is None:
            return None
        if version is None:
            record = self.state.live(collection, id)
        else:
            record = self.state.version(collection, id, version)
        if record is None or record.retired:
            return None
        facets = facet_digests(record.collection, record.body)
        digest_value = facets.get(facet) or facets["full"]
        key = (record.collection, record.id, record.version, facet if facet in facets else "full")
        self.records[key] = digest_value
        return record

    def add_ref(self, ref, facet):
        if ref is None:
            return None
        return self.add(ref["collection"], ref["id"], facet, version=ref.get("version"))

    def anchors(self, ids, facet="proof"):
        for anchor_id in ids:
            anchor = self.add("anchors", anchor_id, facet)
            if anchor:
                self.add('sources', anchor.body['source_id'], 'source')

    def relation(self, relation, key):
        members = self.state.relation_members(relation, key)
        self.relations[(relation, key["collection"], key["id"])] = membership_digest(members)

    def scope_chain(self, scope_id):
        while scope_id is not None and scope_id not in self.scopes_seen:
            self.scopes_seen.add(scope_id)
            scope = self.add("scopes", scope_id, "scope")
            if scope is None:
                break
            for assumption in scope.body["assumptions"]:
                self.statement(assumption)
            self.anchors(scope.body["evidence_refs"], "statement")
            scope_id = scope.body["parent_id"]

    def statement(self, ref):
        record = self.state.live(ref['collection'], ref['id'])
        if record is None:
            return None
        key = (record.collection, record.id, record.version)
        if key in self.statements_seen:
            return record
        # A scope may name an assumption declared in that same scope. Expand each
        # consumed statement once, while still binding every record in the cycle.
        self.statements_seen.add(key)
        self.relation('target_specs_for_target', ref)
        spec = target_spec(self.state, ref)
        if spec:
            self.add('target_specs', spec.id, 'statement')
            if spec.body['statement_ref']:
                pin = spec.body['statement_ref']
                pinned = self.state.version(pin['collection'],pin['id'],pin['version'])
                if pinned and facet_digests(pinned.collection,pinned.body)['statement'] == facet_digests(record.collection,record.body)['statement']:
                    self.add_ref(ref, 'statement')
                else:
                    self.add_ref(pin, 'statement')
            self.anchors(spec.body['evidence_refs'], 'statement')
            for aid in spec.body['evidence_refs']:
                anchor = self.state.live('anchors', aid)
                if anchor:
                    self.add('sources', anchor.body['source_id'], 'source')
            self.scope_chain(spec.body['scope_id'])
        else:
            self.add_ref(ref, 'statement')
        self.anchors([p["anchor_id"] for p in record.body["passages"]
                      if p["role"] in ("statement", "definition")], "statement")
        self.scope_chain(record.body["scope_id"])
        if record.collection == "parts":
            self.statement({"collection": "items", "id": record.body["item_id"]})
        return record

    def borrowed_proof(self, ref):
        record = self.add_ref(ref, "proof")
        if record is None:
            return
        anchors = [p["anchor_id"] for p in record.body["passages"] if p["role"] in ("proof", "evidence")]
        self.anchors(anchors)
        if not anchors and record.collection == "parts":
            self.borrowed_proof({"collection": "items", "id": record.body["item_id"]})

    def use(self, use_id):
        use = self.add("uses", use_id, "application")
        if use is None:
            return None
        self.statement(use.body["from"])
        self.statement(use.body["to"])
        if use.body["type"] == "proof_argument":
            self.borrowed_proof(use.body["from"])
        self.anchors(use.body["evidence_refs"])
        detail = application(self.state, use)
        self.add('application_details', use.id, 'application')
        self.scope_chain(detail.get('scope_id'))
        if detail["group_id"] is not None:
            group = self.add("groups", detail["group_id"], "inference")
            if group is not None:
                self.scope_chain(group.body["scope_id"])
            self.relation("uses_in_group", {"collection": "groups", "id": detail["group_id"]})
        return use

    def group(self, group_id, *, with_uses=True):
        group = self.add("groups", group_id, "inference")
        if group is None:
            return None
        self.statement(group.body["conclusion"])
        self.scope_chain(group.body["scope_id"])
        for scope_id in group.body["case_scope_ids"] + group.body["discharges"]:
            self.scope_chain(scope_id)
        self.anchors(group.body["evidence_refs"])
        key = {"collection": "groups", "id": group_id}
        self.relation("uses_in_group", key)
        if with_uses:
            for _, use_id, _ in self.state.relation_members("uses_in_group", key):
                self.use(use_id)
        return group

    def argument(self, argument_id):
        argument = self.add("arguments", argument_id, "proof")
        if argument is None:
            return None
        target = self.statement(argument.body["target"])
        if target is not None and target.collection == "items":
            item_key = {"collection": "items", "id": target.id}
            self.relation("parts_of_item", item_key)
            for _, part_id, _ in self.state.relation_members("parts_of_item", item_key):
                self.statement({"collection": "parts", "id": part_id})
        self.relation("incoming_uses", argument.body["target"])
        self.scope_chain(argument.body["scope_id"])
        self.anchors(argument.body["evidence_refs"])
        for boundary in boundaries(self.state, argument_id):
            self.add('proof_boundaries', boundary.id, 'coverage')
            self.add_ref(boundary.body['source_review_ref'], 'source')
            for ref in boundary.body['anchor_refs']:
                self.add_ref(ref, 'source')
        key = {"collection": "arguments", "id": argument_id}
        for relation in ("groups_in_argument", "coverage_in_argument", "scopes_in_argument"):
            self.relation(relation, key)
        for _, group_id, _ in self.state.relation_members("groups_in_argument", key):
            self.group(group_id)
        for _, scope_id, _ in self.state.relation_members("scopes_in_argument", key):
            self.scope_chain(scope_id)
        for _, coverage_id, _ in self.state.relation_members("coverage_in_argument", key):
            coverage = self.add("coverage", coverage_id, "coverage")
            if coverage is not None:
                self.add("anchors", coverage.body["anchor_id"], "proof")
        return argument

    def source_statement(self, ref, *, source_only=False, exact=False):
        if ref['collection'] == 'target_specs':
            spec = self.add_ref(ref, 'statement')
            if spec:
                if spec.body['statement_ref']:
                    self.add_ref(spec.body['statement_ref'], 'statement')
                self.scope_chain(spec.body['scope_id'])
                self.anchors(spec.body['evidence_refs'], 'source')
            return spec
        record = self.statement(ref) if exact and not source_only else self.add_ref(ref, 'statement')
        if record is None:
            return None
        self.add_ref(ref, "proof")
        for passage in record.body["passages"]:
            self.add("anchors", passage["anchor_id"], "source")
            self.add("anchors", passage["anchor_id"], "statement")
        if record.body["scope_id"] is not None and not source_only:
            self.scope_chain(record.body["scope_id"])
        if record.collection == "items" and not source_only:
            self.relation("parts_of_item", {"collection": "items", "id": record.id})
        return record

    def result(self, packet):
        records = [{"ref": {"collection": c, "id": i, "version": v}, "facet": f, "digest": d}
                   for (c, i, v, f), d in sorted(self.records.items())]
        relations = [{"relation": r, "key": {"collection": c, "id": i}, "digest": d}
                     for (r, c, i), d in sorted(self.relations.items())]
        manifest = (packet or {}).get("manifest") or {}
        return {"records": records, "relations": relations,
                "source_context_digest": manifest.get("source_context_digest"),
                "packet_id": (packet or {}).get("packet_id")}


def _bind_check(b: _Builder, body: dict):
    kind, target = body["kind"], body["target"]
    if kind == "application":
        b.use(target["id"])
    elif kind in ("derivation", "case_coverage", "scope_discharge"):
        b.group(target["id"])
    elif kind == "composition":
        if target["collection"] in ("items", "parts"):
            b.source_statement(target, exact=True)
            b.relation("arguments_for_target", target)
        elif _coherent_check(b, body):
            selected = coherent_unit_inputs(b.state, target["id"])
            if selected:
                b.coherent_scope = {key: value for key, value in selected.items() if key != "consumed_inputs"}
                for row in selected["consumed_inputs"]:
                    b.add_ref(row["ref"], row["facet"])
        else:
            b.argument(target["id"])
    elif kind == "external_source":
        b.statement(target)
    else:
        audit = b.add("audits", target["id"], "proof" if body.get("role") == "primary" else "full")
        if audit is not None:
            audit_targets = audit.body["targets"]
            if audit.body["mode"] == "full":
                b.relation("audit_scope", target)
                audit_targets = [{"collection": c, "id": i} for c, i, _ in
                                 b.state.relation_members("audit_scope", target)]
            for audit_target in audit_targets:
                b.statement(audit_target)
                b.relation("arguments_for_target", audit_target)
                if audit.body["protocol_version"] == COHERENT_PROTOCOL:
                    from .packets import selected_proof_context
                    selected = selected_proof_context(b.state, audit_target)
                    b.anchors(pin["id"] for pin in selected["anchor_refs"])
                    for entry in selected["consumed_inputs"]:
                        b.add_ref(entry["ref"], entry["facet"])
                    if not hasattr(b, "coherent_scopes"):
                        b.coherent_scopes = []
                    b.coherent_scopes.extend(selected["coherent_scopes"])
                else:
                    b.relation("incoming_uses", audit_target)
    b.anchors(body["evidence_refs"])
    if body["supersedes"] is not None:
        b.add_ref(body["supersedes"], "full")


MATHEMATICAL_FACETS = ("statement", "proof", "application", "inference", "scope", "coverage")
RELATION_FACETS = {"uses_in_group": "application", "incoming_uses": "application",
                   "groups_in_argument": "inference", "scopes_in_argument": "scope",
                   "coverage_in_argument": "coverage", "parts_of_item": "statement",
                   "arguments_for_target": "proof", "checks_or_findings_for_target": "full",
                   "target_specs_for_target": "statement", "proof_boundaries_for_target": "coverage",
                   "refinements_for_use": "full",
                   "audit_scope": "statement"}


def _semantic_members(b, *, relations=None):
    """Freeze membership identities plus facets for the selected binding relations."""
    identities = []
    for relation, collection, id in list(b.relations):
        if relations is not None and relation not in relations:
            continue
        key = {"collection": collection, "id": id}
        members = b.state.relation_members(relation, key)
        for member_collection, member_id, _ in members:
            b.add(member_collection, member_id, RELATION_FACETS[relation])
        identities.append({"relation": relation, "key": key,
                           "members": sorted([[c, i] for c, i, _ in members])})
    return identities


def binding_changes(state, binding: dict) -> dict:
    """Compare a stored binding with ``state`` (prospective State or Snapshot).

    Returns ``{"records": [{ref, facet, expected, actual}], "relations": [{relation, key, expected, actual}]}``
    where ``actual`` is None when the bound record is no longer live.
    """
    records, relations = [], []
    scopes = binding.get("coherent_scopes", []) + ([binding["coherent_scope"]] if binding.get("coherent_scope") else [])
    for scope in scopes:
        actual = coherent_unit_inputs(state, scope["argument_ref"]["id"])
        if actual is None or actual["scientific_inputs_digest"] != scope["scientific_inputs_digest"]:
            records.append({"ref": scope["argument_ref"], "facet": "coherent_unit",
                            "expected": scope["scientific_inputs_digest"],
                            "actual": None if actual is None else actual["scientific_inputs_digest"]})
        for entry in scope.get("application_inputs", []):
            ref = entry["ref"]
            use = state.live(ref["collection"], ref["id"])
            meaning = coherent_application_digest(state, use) if use else None
            if use is None and actual is not None and any(row["digest"] == entry["digest"] for row in actual["application_inputs"]):
                continue
            if meaning != entry["digest"]:
                records.append({"ref": ref, "facet": "examined_application", "expected": entry["digest"], "actual": meaning})
        for entry in scope.get("inference_inputs", []):
            ref = entry["ref"]
            group = state.live(ref["collection"], ref["id"])
            meaning = coherent_group_digest(state, group)
            if group is None and actual is not None and any(row["digest"] == entry["digest"] for row in actual["inference_inputs"]):
                continue
            if meaning != entry["digest"]:
                records.append({"ref": ref, "facet": "examined_inference", "expected": entry["digest"], "actual": meaning})
        if actual is not None and "final_inference_digest" in scope and actual["final_inference_digest"] != scope["final_inference_digest"]:
            records.append({"ref": scope["argument_ref"], "facet": "final_inference",
                "expected": scope["final_inference_digest"], "actual": actual["final_inference_digest"]})
    if binding.get('overview_context'):
        from .overview import comparison_context
        context = binding['overview_context']
        actual = comparison_context(state, context['target'], context['selection_id'])
        if actual != context['digest']:
            records.append({'ref': context['target'], 'facet':'overview_context',
                            'expected':context['digest'], 'actual':actual, 'live_version':None})
    for entry in binding["records"]:
        ref = entry["ref"]
        live = state.live(ref["collection"], ref["id"])
        actual = None
        expected = entry.get("setup_digest", entry["digest"])
        if live is not None:
            facets = facet_digests(live.collection, live.body)
            actual = (setup_digest(live.collection, live.body,
                                  include_evidence=entry.get("source_passage_selection") == 1) if "setup_digest" in entry
                      else facets.get(entry["facet"]) or facets["full"])
        if actual != expected:
            records.append({"ref": ref, "facet": entry["facet"], "expected": expected, "actual": actual,
                            "live_version": None if live is None else live.version})
    for entry in binding["relations"]:
        actual = membership_digest(state.relation_members(entry["relation"], entry["key"]))
        if actual != entry["digest"]:
            semantic = next((r for r in binding.get("semantic_memberships", [])
                             if r["relation"] == entry["relation"] and r["key"] == entry["key"]), None)
            if semantic is not None and sorted([[c, i] for c, i, _ in state.relation_members(
                    entry["relation"], entry["key"])]) == semantic["members"]:
                continue
            if semantic is not None and semantic.get("neutral_context"):
                from .packets import neutral_relation_covered
                if neutral_relation_covered(state, entry, binding["records"]):
                    continue
            relations.append({"relation": entry["relation"], "key": entry["key"], "expected": entry["digest"],
                              "actual": actual})
    return {"records": records, "relations": relations}


def task_binding(state, task: dict) -> dict:
    """Freeze one assigned obligation's mathematical inputs, independent of packet siblings.

    ``state`` is a lazy current-state adapter or the coordinator's existing snapshot.
    A work packet transports the union of these records, but that union is never a
    judgment's freshness boundary.
    """
    b = _Builder(state)
    target = task["target"]
    if task["action"] == "compare_source":
        if target["collection"] == "uses":
            b.use(target["id"])
        else:
            b.source_statement(target, source_only=task.get('source_only',False))
    elif task["action"] == "reconcile":
        if target["collection"] in ("items", "parts"):
            b.statement(target)
        elif target["collection"] == "groups":
            b.group(target["id"])
        elif target["collection"] == "arguments":
            from . import PROTOCOL_VERSION
            _bind_check(b, {"kind": "composition", "target": target, "role": task["role"],
                "protocol_version": task.get("protocol_version", PROTOCOL_VERSION),
                "evidence_refs": [], "supersedes": None})
        elif target["collection"] == "uses":
            b.use(target["id"])
        else:
            b.add_ref(target, "full")
        b.relation("checks_or_findings_for_target", target)
        for ref in task.get("judgment_refs", []) + task.get("prerequisite_judgment_refs", []):
            check = b.add_ref(ref, "full")
            if check is not None and check.collection == "checks":
                _bind_check(b, check.body)
                b.relation("checks_or_findings_for_target", check.body["target"])
    else:
        from . import PROTOCOL_VERSION
        _bind_check(b, {"kind": task["kind"], "target": target, "role": task["role"],
                        "protocol_version": task.get("protocol_version", PROTOCOL_VERSION),
                        "evidence_refs": [], "supersedes": None})
    if task["kind"] == "composition" and not hasattr(b, "coherent_scope"):
        for ref in task.get("prerequisite_judgment_refs", []):
            b.add_ref(ref, "full")
    # Work guards protect mathematical membership, not presentation-only member
    # versions. Store each member's relevant facet so semantic comparison below
    # can distinguish changed membership from a relabelled existing member.
    _semantic_members(b)
    result = b.result(None)
    result = {"consumed_inputs": result["records"], "membership_guards": result["relations"]}
    if hasattr(b, "coherent_scope"):
        result["coherent_scope"] = b.coherent_scope
    if hasattr(b, "coherent_scopes"):
        result["coherent_scopes"] = b.coherent_scopes
    return result


def task_binding_changes(state, task: dict, *, evidence_refs=(), packet=None) -> dict:
    """Compare original assigned inputs and result-specific extra evidence with current state.

    Extra evidence must have been delivered in the original packet. Its pinned
    version is read explicitly; a new current excerpt is never silently consumed.
    Source-context freshness remains acceptance's separate mandatory check.
    """
    binding = {"records": list(task["consumed_inputs"]),
               "relations": list(task["membership_guards"])}
    if task.get("coherent_scope"):
        binding["coherent_scope"] = task["coherent_scope"]
    if task.get("coherent_scopes"):
        binding["coherent_scopes"] = task["coherent_scopes"]
    missing_scope = missing_full_audit_scope(state, task["target"], binding)
    if missing_scope is not None:
        return {"records": [missing_scope], "relations": []}
    manifest = (packet or {}).get("manifest", packet or {})
    pins = {(r["collection"], r["id"]): r for r in manifest.get("read_set", [])}
    missing = []
    facet = "source" if task["action"] == "compare_source" else "proof"
    seen = {(r["ref"]["collection"], r["ref"]["id"], r["facet"]) for r in binding["records"]}
    for anchor_id in dict.fromkeys(evidence_refs):
        pin = pins.get(("anchors", anchor_id))
        if pin is None:
            missing.append({"ref": {"collection": "anchors", "id": anchor_id},
                            "facet": facet, "expected": "original packet evidence", "actual": None})
            continue
        if ("anchors", anchor_id, facet) in seen:
            continue
        original = state.version("anchors", anchor_id, pin["version"])
        if original is None or original.retired:
            missing.append({"ref": pin, "facet": facet, "expected": "original packet evidence", "actual": None})
            continue
        binding["records"].append({"ref": pin, "facet": facet,
                                   "digest": facet_digests("anchors", original.body)[facet]})
    result = binding_changes(state, binding)
    if task.get("neutral_question"):
        from .packets import neutral_question
        actual = neutral_question(state, task, allow_proposed=manifest.get("review_basis") == "route_provided")
        if actual != task["neutral_question"]:
            result["records"].append({"ref": task["target"], "facet": "neutral_question",
                "expected": digest(task["neutral_question"]), "actual": digest(actual)})
    revision = manifest.get("base_revision")
    if revision is not None and hasattr(state, "db"):
        changed_relations = []
        for changed in result["relations"]:
            original_members = relation_members(state.db.conn, changed["relation"], changed["key"], revision=revision)
            current_members = state.relation_members(changed["relation"], changed["key"])
            if {(c, i) for c, i, _ in original_members} != {(c, i) for c, i, _ in current_members}:
                changed_relations.append(changed)
        result["relations"] = changed_relations
    result["records"].extend(missing)
    return result


def missing_full_audit_scope(state, target, binding):
    """Older global evidence cannot claim an inventory it never captured."""
    if target.get("collection") != "audits":
        return None
    audit = state.live("audits", target["id"])
    if audit is None or audit.body["mode"] != "full":
        return None
    if any(row["relation"] == "audit_scope" and row["key"] == target
           for row in binding["relations"]):
        return None
    pin = next((row["ref"] for row in binding["records"] if row["ref"]["collection"] == "audits"
                and row["ref"]["id"] == audit.id), audit.pinned)
    return {"ref": pin, "facet": "audit_scope", "expected": "captured full audit scope",
            "actual": None, "live_version": audit.version,
            "reason": "renew the global examination to capture its full audit scope"}


def _work_composition_checks(b, body, packet):
    """Bind a controller composition to the actual prospective local judgments.

    Earlier results in the same response now have real generated IDs in the
    prospective state. Applications/derivations do not consume these siblings.
    """
    if _coherent_check(b, body):
        return
    manifest = (packet or {}).get("manifest", packet or {})
    if not manifest.get("work") or body["kind"] != "composition" or body["role"] != "primary":
        return
    if body["target"]["collection"] != "arguments":
        return
    targets = []
    for _, group_id, _ in b.state.relation_members("groups_in_argument", body["target"]):
        group_ref = {"collection": "groups", "id": group_id}
        targets.append(group_ref)
        targets.extend({"collection": c, "id": i} for c, i, _ in
                       b.state.relation_members("uses_in_group", group_ref))
    for target in targets:
        for collection, id, _ in b.state.relation_members("checks_or_findings_for_target", target):
            if collection != "checks":
                continue
            check = b.state.live(collection, id)
            if check is not None and check.body["audit_id"] == body["audit_id"] \
                    and check.body["role"] == body["role"] and check.body["state"] == "complete":
                b.add("checks", id, "full")


def _semantic_membership_origin(state, collection, body, manifest):
    """Preserve a controller review's binding policy through generic identity mapping.

    The mapping command still checks both packets using its ordinary strict
    transaction rules. This selects only the saved check's future comparison
    policy, using immutable response-to-original-packet provenance.
    """
    if manifest.get("packet_version") == 2 and isinstance(manifest.get("work"), dict):
        return True
    if collection != "checks" or body["role"] != "independent" or body["response_id"] is None:
        return False
    response = state.live("responses", body["response_id"])
    if response is None:
        return False
    original = state.db.packet(response.body["packet_id"])
    if original is None or original["packet_version"] != 2 or original["mode"] != "independent":
        return False
    work = original["manifest"].get("work")
    return isinstance(work, dict) and work.get("mode") == "independent" \
        and work.get("audit_id") == body["audit_id"]


def compute_bindings(state, collection: str, body: dict, *, packet=None) -> dict | None:
    """Bindings for one prospective record, or None when the collection carries none."""
    if collection not in BOUND_COLLECTIONS:
        return None
    if collection == 'observations' and body.get('context_kind') == 'overview':
        from .overview import comparison_context
        selection_id = body.get('context_data', {}).get('selection_id')
        return {'records': [], 'relations': [], 'source_context_digest': None,
                'packet_id': (packet or {}).get('packet_id'),
                'overview_context': {'selection_id':selection_id, 'target':body['target'],
                                     'digest':comparison_context(state,body['target'],selection_id)}}
    b = _Builder(state)
    neutral_context = None
    if collection == "checks":
        _bind_check(b, body)
        _work_composition_checks(b, body, packet)
        if body.get('role') == 'independent' and body.get('response_id'):
            response = state.live('responses', body['response_id'])
            original = state.db.packet(response.body['packet_id']) if response else None
            manifest = original['manifest'] if original else {}
            from .packets import independent_context_binding
            neutral_context = independent_context_binding(state, manifest)
            if neutral_context is not None:
                changes = binding_changes(state, neutral_context)
                if changes["records"] or changes["relations"]:
                    from .errors import ConflictError
                    raise ConflictError("original independent source or applicable setup changed; obtain a renewed review",
                                        records=[changes])
            for ref in manifest.get('supplied_derivation_refs', []):
                check = b.add_ref(ref, 'full')
                if check:
                    b.relation('checks_or_findings_for_target', check.body['target'])
    elif collection == "observations":
        if body["target"]["collection"] == "target_specs":
            spec = b.add_ref(body['target'], 'statement')
            if spec:
                if spec.body['statement_ref']:
                    b.add_ref(spec.body['statement_ref'], 'statement')
                b.scope_chain(spec.body['scope_id'])
                b.anchors(spec.body['evidence_refs'], 'source')
                for identity in spec.body['evidence_refs']:
                    anchor = state.live('anchors', identity)
                    if anchor:
                        b.add('sources', anchor.body['source_id'], 'source')
        elif body["target"]["collection"] == "uses":
            b.use(body["target"]["id"])
        else:
            b.source_statement(body["target"])
        b.anchors(body["evidence_refs"], "source")
    elif collection == "reconciliations":
        for ref in body["primary_checks"] + body["independent_checks"] + body["successor_checks"]:
            b.add_ref(ref, "full")
        for disposition in body.get("response_dispositions", []):
            b.add_ref(disposition["response_ref"], "full")
        if body["target"]["collection"] in ("items", "parts"):
            b.statement(body["target"])
        else:
            b.add_ref(body["target"], "full")
        b.anchors(body["evidence_refs"])
    elif collection == "reuse_decisions":
        check = b.add_ref(body["check_ref"], "full")
        b.add("source_reviews", body["source_review_id"], "full")
        b.anchors(body["evidence_refs"], "source")
        if check is not None:
            # pin the check's consumed records in the new context so the decision itself stays current
            # exactly as long as that context does (record-contract 6)
            _bind_check(b, check.body)
    elif collection == "source_reviews":
        for ref in body["source_refs"]:
            b.add_ref(ref, "source")
        for ref in body["anchor_refs"]:
            b.add_ref(ref, "source")
    manifest = (packet or {}).get("manifest", packet or {})
    if collection == 'checks' or _semantic_membership_origin(state, collection, body, manifest):
        identities = _semantic_members(b)
    elif collection == 'observations':
        # Attaching source-fidelity provenance changes a specification's version,
        # not its statement. Preserve strict policy for all other relations and
        # for historical bindings that do not carry these semantic memberships.
        identities = _semantic_members(b, relations={'target_specs_for_target'})
    else:
        identities = None
    result = b.result(packet)
    if hasattr(b, "coherent_scope"):
        result["coherent_scope"] = b.coherent_scope
    if hasattr(b, "coherent_scopes"):
        result["coherent_scopes"] = b.coherent_scopes
    if neutral_context is not None:
        result["neutral_setup_validated"] = 1
        consumed = {(row["ref"]["collection"], row["ref"]["id"], row["ref"]["version"], row["facet"],
                     "setup_digest" in row): row
                    for row in result["records"]}
        consumed.update({(row["ref"]["collection"], row["ref"]["id"], row["ref"]["version"], row["facet"],
                          "setup_digest" in row): row
                         for row in neutral_context["records"]})
        result["records"] = [consumed[key] for key in sorted(consumed)]
        relations = {(row["relation"], row["key"]["collection"], row["key"]["id"]): row
                     for row in result["relations"]}
        for row in neutral_context["relations"]:
            relations.setdefault((row["relation"], row["key"]["collection"], row["key"]["id"]), row)
        result["relations"] = [relations[key] for key in sorted(relations)]
        memberships = {(row["relation"], row["key"]["collection"], row["key"]["id"]): row
                       for row in identities or []}
        for row in neutral_context["semantic_memberships"]:
            memberships.setdefault((row["relation"], row["key"]["collection"], row["key"]["id"]), row)
        identities = [memberships[key] for key in sorted(memberships)]
    # Source currentness is tied to consumed sources/anchors. Adding an unrelated
    # audit source is not a mathematical change to every prior examination.
    result['source_context_digest'] = None
    if identities is not None:
        result["semantic_memberships"] = identities
    return result


__all__ = ["BOUND_COLLECTIONS", "MATHEMATICAL_FACETS", "binding_changes", "compute_bindings",
           "task_binding", "task_binding_changes", "coherent_unit_inputs"]
