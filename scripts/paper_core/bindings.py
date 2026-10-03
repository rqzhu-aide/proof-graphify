"""Evidence bindings generated when assessment records are accepted (record-contract 6).

A binding pins the record versions and facets a judgment consumed, plus the
membership digests of the relations it depended on, all computed on the
prospective (post-batch) state. Outgoing consumers are never part of a
supplier's binding.
"""
from __future__ import annotations

from .refs import facet_digests, membership_digest, relation_members, setup_digest
from .semantics import application, target_spec, boundaries
from .errors import ConflictError, InvalidRequest

BOUND_COLLECTIONS = ("checks", "observations", "reconciliations", "reuse_decisions", "source_reviews")

# Private, forward-only comparison metadata. Ordinary facet digests and pins
# remain intact so a reader that does not recognize this policy stays strict.
EVIDENCE_MAINTENANCE_VERSION = 1
_EVIDENCE_FACETS = {"arguments": "proof", "groups": "inference", "uses": "application",
                    "scopes": "scope", "target_specs": "statement"}


def _anchor_extent(anchor, selected):
    """Candidate excerpt offsets inside a pinned selection anchor, or unknown."""
    if (anchor.body["source_id"], anchor.body["source_version"]) != (
            selected.body["source_id"], selected.body["source_version"]):
        return None
    loc, prior = anchor.body["locator"], selected.body["locator"]
    if loc["page"] is not None or prior["page"] is not None:
        if loc["page"] != prior["page"] or anchor.body["excerpt"] != selected.body["excerpt"]:
            return None
        return 0, len(selected.body["excerpt"])
    start, end = loc["start_line"], loc["end_line"]
    left, right = prior["start_line"], prior["end_line"]
    if any(type(value) is not int for value in (start, end, left, right)) or not left <= start <= end <= right:
        return None
    lines = selected.body["excerpt"].split("\n")
    if len(lines) != right - left + 1:
        return None
    begin = sum(len(line) + 1 for line in lines[:start - left])
    stop = begin + len("\n".join(lines[start - left:end - left + 1]))
    return (begin, stop) if selected.body["excerpt"][begin:stop] == anchor.body["excerpt"] else None


def _selection_covers(state, selections, anchor):
    from .proof_spans import uncovered_spans
    for selection in selections:
        pin, source_pin = selection["anchor_ref"], selection["source_ref"]
        prior = state.version("anchors", pin["id"], pin["version"])
        current = state.live("anchors", pin["id"])
        source = state.live("sources", source_pin["id"])
        if prior is None or prior.retired or current is None or source is None \
                or source.version != source_pin["version"] \
                or facet_digests("sources", source.body)["source"] != selection["source_digest"] \
                or facet_digests("anchors", current.body)["source"] != selection["anchor_digest"]:
            continue
        extent = _anchor_extent(anchor, prior)
        if extent is not None and extent[0] < extent[1] \
                and not uncovered_spans(selection["intervals"], [extent]):
            return True
    return False


def evidence_maintenance_compatible(state, entry, live):
    """Prove an append-only link addition from original consumed source extent."""
    policy = entry.get("evidence_maintenance")
    if not isinstance(policy, dict) or policy.get("version") != EVIDENCE_MAINTENANCE_VERSION \
            or set(policy) != {"version", "selections"} or not policy["selections"] \
            or entry["facet"] != _EVIDENCE_FACETS.get(live.collection) \
            or any(key in entry for key in ("global_proof_selection_digest", "proof_span_selection_digest")):
        return False
    pin = entry["ref"]
    original = state.version(pin["collection"], pin["id"], pin["version"])
    if original is None or original.retired or "evidence_refs" not in original.body:
        return False
    if entry["digest"] != facet_digests(original.collection, original.body).get(entry["facet"]):
        return False
    if "setup_digest" in entry and (entry.get("source_passage_selection") != 1 or entry["setup_digest"] !=
            setup_digest(original.collection, original.body, include_evidence=True)):
        return False
    before, after = original.body["evidence_refs"], live.body.get("evidence_refs")
    if not isinstance(after, list) or after[:len(before)] != before or len(after) <= len(before) \
            or len(after) != len(set(after)) \
            or {k: v for k, v in original.body.items() if k != "evidence_refs"} != {
                k: v for k, v in live.body.items() if k != "evidence_refs"}:
        return False
    try:
        for identity in after[len(before):]:
            anchor = state.live("anchors", identity)
            if anchor is None or not _selection_covers(state, policy["selections"], anchor):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _maintenance_selections(state, rows, packet, *, spans=None):
    """Only anchors both delivered and consumed can authorize future additions."""
    manifest = (packet or {}).get("manifest", packet or {})
    delivered = {(ref["collection"], ref["id"], ref["version"]) for ref in manifest.get("read_set", [])}
    selections = []
    for row in rows:
        pin = row["ref"]
        if pin["collection"] != "anchors" or ("anchors", pin["id"], pin["version"]) not in delivered:
            continue
        anchor = state.version("anchors", pin["id"], pin["version"])
        if anchor is None or anchor.retired:
            continue
        source_pin = {"collection": "sources", "id": anchor.body["source_id"], "version": anchor.body["source_version"]}
        if ("sources", source_pin["id"], source_pin["version"]) not in delivered:
            continue
        source = state.version("sources", source_pin["id"], source_pin["version"])
        intervals = (spans or {}).get(pin["id"], []) if spans is not None else [(0, len(anchor.body["excerpt"]))]
        if source is None or source.retired or not intervals:
            continue
        selection = {"anchor_ref": pin, "source_ref": source_pin,
                     "source_digest": facet_digests("sources", source.body)["source"],
                     "anchor_digest": facet_digests("anchors", anchor.body)["source"],
                     "intervals": [list(interval) for interval in intervals]}
        if selection not in selections:
            selections.append(selection)
    return selections


def _argument_selection(state, argument_id):
    """Restrict consumed page anchors to an actual explicit route certificate."""
    from .proof_spans import reviewed_spans
    argument = state.live("arguments", argument_id)
    explicit = False
    for boundary in boundaries(state, argument_id):
        pin = boundary.body["source_review_ref"]
        review = state.version("source_reviews", pin["id"], pin["version"])
        if review is None or "proof_spans" not in review.body:
            continue
        explicit = True
        if boundary.body["state"] == "complete" and review.body["decision"] == "accepted":
            spans = reviewed_spans(state, review, argument, boundary.body["anchor_refs"])
            if spans is not None:
                return spans
    return {} if explicit else None


def _mark_evidence_maintenance(state, result, collection, body, packet):
    spans = None
    if collection == "source_reviews":
        if "proof_spans" not in body or body["decision"] != "accepted" or body["purpose"] != "proof_boundary":
            return
    else:
        target = body.get("target", {})
        record = state.live(target.get("collection"), target.get("id")) if target else None
        argument_id = None
        if record is not None:
            if record.collection == "arguments":
                argument_id = record.id
            elif record.collection == "groups":
                argument_id = record.body["argument_id"]
            elif record.collection == "uses":
                group = state.live("groups", application(state, record).get("group_id"))
                argument_id = group.body["argument_id"] if group else None
        if argument_id is not None:
            spans = _argument_selection(state, argument_id)
    # The private neutral closure transports source context but does not say
    # which passages an actual returned judgment examined. Require its own
    # explicit evidence, or a source review's certified selection.
    consumed_ids = {span["anchor_ref"]["id"] for span in body.get("proof_spans", [])} \
        if collection == "source_reviews" else set(body.get("evidence_refs", []))
    consumed_rows = [row for row in result["records"] if row["ref"]["collection"] == "anchors"
                     and row["ref"]["id"] in consumed_ids]
    for row in result["records"]:
        pin = row["ref"]
        if row["facet"] != _EVIDENCE_FACETS.get(pin["collection"]):
            continue
        selected = spans
        if collection == "source_reviews":
            if pin["collection"] != "arguments":
                continue
            selected = {}
            for span in body["proof_spans"]:
                if span["argument_ref"] == pin:
                    selected.setdefault(span["anchor_ref"]["id"], []).append((span["start_offset"], span["end_offset"]))
        selections = _maintenance_selections(state, consumed_rows, packet, spans=selected)
        if selections:
            row["evidence_maintenance"] = {"version": EVIDENCE_MAINTENANCE_VERSION, "selections": selections}


class _Builder:
    def __init__(self, state):
        self.state = state
        self.records = {}
        self.relations = {}
        self.statements_seen = set()
        self.scopes_seen = set()
        self.global_proof_selections = {}

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
        for row in records:
            key = row["ref"]["collection"], row["ref"]["id"]
            if row["facet"] == "proof" and key in self.global_proof_selections:
                row["global_proof_selection_digest"] = self.global_proof_selections[key]
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
        b.argument(target["id"])
    elif kind == "external_source":
        b.source_statement(target, exact=True)
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
                from .packets import global_proof_selection
                selected = global_proof_selection(b.state, audit_target)
                for record in selected["statements"] + selected["arguments"]:
                    b.add_ref(record.ref, "proof")
                if selected["statements"]:
                    b.global_proof_selections[(audit_target["collection"], audit_target["id"])] = selected["digest"]
                b.anchors(selected["anchor_ids"], "source")
                b.relation("arguments_for_target", audit_target)
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
        expected = entry.get("global_proof_selection_digest", entry.get("proof_span_selection_digest", entry.get("setup_digest", entry["digest"])))
        if live is not None:
            facets = facet_digests(live.collection, live.body)
            if "global_proof_selection_digest" in entry:
                from .packets import global_proof_selection
                actual = global_proof_selection(state, live.ref)["digest"]
            elif "proof_span_selection_digest" in entry:
                from .proof_spans import boundary_selection_digest
                actual = boundary_selection_digest(state, live)
            else:
                actual = (setup_digest(live.collection, live.body,
                                      include_evidence=entry.get("source_passage_selection") == 1) if "setup_digest" in entry
                          else facets.get(entry["facet"]) or facets["full"])
        if actual != expected:
            if live is not None and evidence_maintenance_compatible(state, entry, live):
                continue
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


def _source_only_work_manifest(state, body):
    """Identify eligible review provenance, never from a binding's policy marker."""
    if body.get("role") != "independent" or not body.get("response_id"):
        return None
    response = state.live("responses", body["response_id"])
    if response is None or response.body["state"] != "accepted" \
            or response.body["exposure"] != "source_only" \
            or any(response.body[key] != body[key] for key in ("audit_id", "reviewer")):
        return None
    qualification = state.live("qualifications", response.body["qualification_id"])
    if qualification is None or not qualification.body["qualified"] \
            or qualification.body["reviewer"] != response.body["reviewer"] \
            or qualification.body["protocol_version"] != body["protocol_version"]:
        return None
    original = state.db.packet(response.body["packet_id"])
    if original is None or not state.db.has_blob(response.body["original_blob"]):
        raise InvalidRequest("original independent packet or response is unavailable", code="SOURCE_CONTEXT_UNAVAILABLE")
    manifest = original["manifest"]
    work = manifest.get("work")
    if original["packet_version"] != 2 or manifest.get("mode") != "independent" \
            or manifest.get("review_basis", "source_only") != "source_only" \
            or not isinstance(work, dict) or work.get("mode") != "independent" \
            or work.get("audit_id") != body["audit_id"]:
        return None
    return manifest


def _without_coordinator_coverage(binding):
    # Boundary certificates also have a "coverage" facet. Only the coordinator's
    # coverage collection/relation is irrelevant to a source-only examination.
    result = {**binding,
        "records": [row for row in binding["records"] if row["ref"]["collection"] != "coverage"],
        "relations": [row for row in binding["relations"] if row["relation"] != "coverage_in_argument"]}
    if "semantic_memberships" in binding:
        result["semantic_memberships"] = [row for row in binding["semantic_memberships"]
                                          if row["relation"] != "coverage_in_argument"]
    return result


def record_binding_changes(state, record, binding):
    """Current mathematical drift, with narrow read-only recovery of old checks.

    Generic binding_changes remains strict for transaction/reuse validation.
    Saved bindings and original response bytes are never rewritten.
    """
    changes = binding_changes(state, binding)
    if record.collection == "checks" and record.body["target"]["collection"] == "audits":
        historical = _legacy_global_selection_changes(state, record.body["target"], binding)
        changes["records"].extend(historical["records"])
        changes["relations"].extend(historical["relations"])
    coverage_changed = any(row["ref"]["collection"] == "coverage" for row in changes["records"]) \
        or any(row["relation"] == "coverage_in_argument" for row in changes["relations"])
    # Do not introduce new review gates where this correction grants no exemption.
    # In particular, local group checks retain their existing mapped bindings.
    if record.collection == "checks" and coverage_changed:
        try:
            manifest = _source_only_work_manifest(state, record.body)
            if manifest is not None:
                from .packets import independent_context_binding
                neutral = independent_context_binding(state, manifest)
                if neutral is not None:
                    context_changes = binding_changes(state, neutral)
                    if context_changes["records"] or context_changes["relations"]:
                        return changes
                    return binding_changes(state, _without_coordinator_coverage(binding))
        except (ConflictError, InvalidRequest):
            # Missing/insufficient original provenance cannot recover old credit.
            return changes
    return changes


def _legacy_global_selection_changes(state, target, binding, *, manifest=None):
    """Compare old global inputs read-only, using the existing bounded historical adapter."""
    if any("global_proof_selection_digest" in row for row in binding["records"]):
        return {"records": [], "relations": []}
    from .packets import MAX_WORK_BYTES, _ContextLimit, _legacy_extension_setup
    original = state.db.packet(binding.get("packet_id")) if binding.get("packet_id") else None
    manifest = manifest or (original["manifest"] if original else None)
    unknown = {"ref": target, "facet": "global_proof_selection", "expected": "captured proof selection",
               "actual": None, "reason": "historical global proof selection is unknown; inspect saved assignment provenance"}
    if manifest is None or type(manifest.get("base_revision")) is not int:
        return {"records": [unknown], "relations": []}
    # The adapter reads only the original audit's shallow consumed closure. It
    # neither loads worker blobs nor changes the original binding or receipt.
    task = {"target": target, "kind": "global_consistency", "role": "primary", "action": "check"}
    historical_manifest = {**manifest, "work": {"tasks": [task],
        "limits": {"max_bytes": manifest.get("work", {}).get("limits", {}).get("max_bytes", MAX_WORK_BYTES)}}}
    try:
        inputs, relations = _legacy_extension_setup(state.db, historical_manifest, state, verify=False)
        if not any("global_proof_selection_digest" in row for row in inputs):
            return {"records": [unknown], "relations": []}
        return binding_changes(state, {"records": inputs, "relations": relations, "semantic_memberships": relations})
    except (_ContextLimit, InvalidRequest) as exc:
        unknown["reason"] += f" ({getattr(exc, 'code', 'WORK_CONTEXT_LIMIT')})"
        return {"records": [unknown], "relations": []}


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
            b.argument(target["id"])
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
        _bind_check(b, {"kind": task["kind"], "target": target, "role": task["role"],
                        "evidence_refs": [], "supersedes": None})
    if task["kind"] == "composition":
        for ref in task.get("prerequisite_judgment_refs", []):
            b.add_ref(ref, "full")
    # Work guards protect mathematical membership, not presentation-only member
    # versions. Store each member's relevant facet so semantic comparison below
    # can distinguish changed membership from a relabelled existing member.
    _semantic_members(b)
    result = b.result(None)
    return {"consumed_inputs": result["records"], "membership_guards": result["relations"]}


def task_binding_changes(state, task: dict, *, evidence_refs=(), packet=None) -> dict:
    """Compare original assigned inputs and result-specific extra evidence with current state.

    Extra evidence must have been delivered in the original packet. Its pinned
    version is read explicitly; a new current excerpt is never silently consumed.
    Source-context freshness remains acceptance's separate mandatory check.
    """
    binding = {"records": list(task["consumed_inputs"]),
               "relations": list(task["membership_guards"])}
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
    if task["target"]["collection"] == "audits":
        historical = _legacy_global_selection_changes(state, task["target"], binding, manifest=manifest)
        result["records"].extend(historical["records"])
        result["relations"].extend(historical["relations"])
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
    maintenance_packet = packet
    if collection == "checks":
        _bind_check(b, body)
        _work_composition_checks(b, body, packet)
        if body.get('role') == 'independent' and body.get('response_id'):
            response = state.live('responses', body['response_id'])
            original = state.db.packet(response.body['packet_id']) if response else None
            maintenance_packet = original
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
        for span in body.get("proof_spans", []):
            b.add_ref(span["argument_ref"], "proof")
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
    if collection == "checks" and neutral_context is not None \
            and _source_only_work_manifest(state, body) is not None:
        result = _without_coordinator_coverage(result)
    if collection in ("checks", "observations", "source_reviews"):
        _mark_evidence_maintenance(state, result, collection, body, maintenance_packet)
    return result


__all__ = ["BOUND_COLLECTIONS", "MATHEMATICAL_FACETS", "binding_changes", "record_binding_changes", "compute_bindings",
           "task_binding", "task_binding_changes"]
