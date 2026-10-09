"""One examination basis for coherent proof units.

This resolver supplies local validity, never premise availability. The founded
support closure still evaluates suppliers, cases, discharge and alternative
routes. A partial or unsuccessful composition grants no blanket local credit.
"""
from __future__ import annotations

from .canonical import digest
from .contract import INTERMEDIATE_KINDS

PROTOCOL = "coherent-proof-audit/1"


def enabled(audit):
    return audit is not None and audit.body.get("protocol_version") == PROTOCOL


def examination_complete(body):
    """Whether the declared examination was performed, regardless of outcome."""
    if body.get("state") != "complete" or not body.get("reasoning", "").strip():
        return False
    if body.get("kind") != "composition":
        return True
    extent = body.get("extent")
    return extent == "whole_unit" or (extent == "partial" and bool(body.get("omissions", "").strip()))


def _key(ref):
    return f"{ref['collection']}:{ref['id']}"


def _ref(record):
    return {"collection": record.collection, "id": record.id}


def unit_targets(state, target):
    """The exact unit and its existing inference/application targets."""
    targets = [target]
    if target["collection"] == "arguments":
        argument = state.live("arguments", target["id"])
        for collection, identity, _ in state.relation_members("groups_in_argument", target):
            group = {"collection": collection, "id": identity}
            targets.append(group)
            record = state.live(collection, identity)
            if record is not None and argument is not None \
                    and record.body["conclusion"] != argument.body["target"] \
                    and record.body["conclusion"] not in targets:
                targets.append(record.body["conclusion"])
            targets.extend({"collection": c, "id": i} for c, i, _ in
                           state.relation_members("uses_in_group", group))
    return targets


class LocalBasis:
    """Shared local examination and source-comparison resolver for v3."""

    def __init__(self, derivation):
        self.d, self.snap = derivation, derivation.snap
        self._examined_members = {}

    @staticmethod
    def pending_accounted(response, reconciliation):
        """Disposition is tied to the actual preserved response and pending rows."""
        pending = set(response.body.get("pending_judgments", ()))
        if not pending:
            return True
        if reconciliation is None:
            return False
        covered = set()
        for row in reconciliation.body.get("response_dispositions", ()):
            pin = row.get("response_ref", {})
            if pin.get("collection") == "responses" and pin.get("id") == response.id \
                    and pin.get("version") == response.version and row.get("rationale", "").strip():
                covered.update(row.get("judgment_indexes", ()))
        return pending <= covered

    def _members_at_examination(self, argument, check):
        key = (argument.id, check.revision)
        if key not in self._examined_members:
            db, revision = self.snap.db, check.revision
            groups = [r for r in db.records_at(revision, collection="groups")
                      if r.body.get("argument_id") == argument.id]
            group_ids = {r.id for r in groups}
            details = {r.id: r for r in db.records_at(revision, collection="application_details")}
            uses = [r for r in db.records_at(revision, collection="uses")
                    if (details[r.id].body.get("group_id") if r.id in details else r.body.get("group_id")) in group_ids]
            old_argument = db.latest_at("arguments", argument.id, revision)
            targets = [g.body["conclusion"] for g in groups]
            if old_argument is not None:
                targets.append(old_argument.body["target"])
            statements = [db.latest_at(r["collection"], r["id"], revision) for r in targets]
            self._examined_members[key] = [r for r in [*statements, *groups, *uses] if r is not None]
        return self._examined_members[key]

    def _scientific_content(self, record, revision=None):
        """Exact stored content comparison, without mathematical equivalence claims."""
        db = self.snap.db
        def get(ref):
            return self.snap.get(ref) if revision is None else db.latest_at(ref["collection"], ref["id"], revision)
        def statement(ref):
            row = get(ref)
            return None if row is None else {"statement": row.body["statement"],
                                             "scope_id": row.body.get("scope_id"), "origin": row.body["origin"]}
        body = record.body
        if record.collection in ("items", "parts"):
            return statement(_ref(record))
        if record.collection == "uses":
            detail = self.snap.application(record) if revision is None else db.latest_at("application_details", record.id, revision)
            app = detail.body if hasattr(detail, "body") else detail or body
            return {"from": statement(body["from"]), "to": statement(body["to"]), "type": body["type"],
                    "needed_form": app.get("needed_form"), "substitutions": app.get("substitutions", ()),
                    "scope_id": app.get("scope_id"), "regime": body.get("regime"),
                    "reason": body["reason"], "evidence_refs": body["evidence_refs"]}
        if record.collection == "groups":
            if revision is None:
                uses = self.snap.member_records("uses_in_group", _ref(record))
            else:
                details = {r.id: r for r in db.records_at(revision, collection="application_details")}
                uses = [r for r in db.records_at(revision, collection="uses")
                        if (details[r.id].body.get("group_id") if r.id in details else r.body.get("group_id")) == record.id]
            return {"conclusion": statement(body["conclusion"]), "kind": body["kind"],
                    "scope_id": body["scope_id"], "case_scope_ids": body["case_scope_ids"],
                    "discharges": body["discharges"], "rationale": body["rationale"],
                    "evidence_refs": body["evidence_refs"],
                    "premises": sorted(digest(self._scientific_content(use, revision)) for use in uses)}
        return None

    def _exact_equivalent_member(self, record, argument, check):
        content = self._scientific_content(record)
        if content is None:
            return False
        return any((r.collection == record.collection or r.collection in ("items", "parts")
                    and record.collection in ("items", "parts"))
                   and content == self._scientific_content(r, check.revision)
                   for r in self._members_at_examination(argument, check))

    def arguments_for(self, target):
        record = self.snap.get(target)
        if record is None:
            return []
        if record.collection == "arguments":
            return [record]
        if record.collection == "groups":
            argument = self.snap.live("arguments", record.body.get("argument_id"))
            return [argument] if argument else []
        if record.collection == "uses":
            group = self.snap.live("groups", self.snap.application(record).get("group_id"))
            return self.arguments_for(_ref(group)) if group else []
        if record.collection in ("items", "parts"):
            arguments = {a.id: a for a in self.snap.member_records("arguments_for_target", target)}
            for group in self.snap.groups_for_conclusion(target):
                for argument in self.arguments_for(_ref(group)):
                    arguments[argument.id] = argument
            return [arguments[k] for k in sorted(arguments)]
        return []

    def scope_binding(self, check):
        stored = self.snap.binding(check)
        if stored is None:
            return None
        bound = stored.get("bindings", stored)
        scope = bound.get("coherent_scope")
        return scope if isinstance(scope, dict) else None

    def whole_checks(self, argument):
        if self.d._explicit_local_basis(_ref(argument), "composition") != "supported":
            return []
        result = []
        adopted = self.d._integrated_checks(_ref(argument), "composition")
        candidates = adopted if adopted is not None else self.d.checks_by_target.get(_key(_ref(argument)), ())
        for check in candidates:
            if check.id in self.d.superseded or check.body.get("protocol_version") != PROTOCOL \
                    or check.body["kind"] != "composition" or (adopted is None and check.body["role"] != "primary") \
                    or check.body.get("extent") != "whole_unit" \
                    or check.body.get("outcome") != "supported":
                continue
            info = self.d.judgment_info(check)
            scope = self.scope_binding(check)
            if info["state"] == "complete" and info["freshness"] == "current" and scope is not None:
                result.append(check)
        return result

    def grounded(self, record, argument, check):
        """Require located evidence inside the fixed examined scientific input."""
        scope = self.scope_binding(check)
        refs = (scope or {}).get("source_evidence_refs", ())
        anchors = {ref["id"] if isinstance(ref, dict) else ref for ref in refs}
        if record.collection == "uses":
            stored = self.snap.binding(check) or {}
            bound = stored.get("bindings", stored)
            bound_anchors = {row["ref"]["id"] for row in bound.get("records", ())
                             if row["ref"]["collection"] == "anchors"}
            anchors.update(set(check.body.get("evidence_refs", ())) & bound_anchors)
        if not anchors:
            return False
        evidence = set(record.body.get("evidence_refs", ()))
        if record.collection in ("items", "parts"):
            evidence.update(p["anchor_id"] for p in record.body.get("passages", ()))
        if record.collection == "arguments":
            return record.id == argument.id
        # The scope binding deliberately omits graph membership. Compare an
        # existing member's scientific facets at examination time so changing
        # its formula or application cannot inherit an old encompassing basis.
        previous = self.snap.db.latest_at(record.collection, record.id, check.revision)
        members = self._members_at_examination(argument, check)
        was_member = any(r.collection == record.collection and r.id == record.id for r in members)
        facets = {"items": "statement", "parts": "statement", "groups": "inference", "uses": "application"}
        facet = facets.get(record.collection)
        if (previous is None or not was_member) and not self._exact_equivalent_member(record, argument, check):
            return False
        if previous is not None and facet is not None \
                and self.snap.facets(previous).get(facet) != self.snap.facets(record).get(facet):
            return False
        if record.collection == "uses":
            detail = self.snap.live("application_details", record.id)
            old_detail = self.snap.db.latest_at("application_details", record.id, check.revision)
            if detail is not None and old_detail is not None \
                    and self.snap.facets(detail)["application"] != self.snap.facets(old_detail)["application"]:
                return False
        # No ownership-based credit for a new unlocated assertion or connection.
        return bool(evidence) and evidence <= anchors

    def local_finding(self, target):
        from .assessment import judgment_freshness
        record = self.snap.get(target)
        findings = list(self.d.findings_by_target.get(_key(target), ()))
        checks = self.d.checks_by_target.get(_key(target), ())
        for check in checks:
            if check.id not in self.d.superseded:
                findings.extend(self.d.findings_by_check.get(check.id, ()))
        if record is not None and record.collection == "arguments" and record.body["origin"] == "source":
            ids = {check.id for check in checks}
            findings.extend(f for f in self.d.findings_by_target.get(_key(record.body["target"]), ())
                            if not f.body["check_refs"] or any(r["id"] in ids for r in f.body["check_refs"]))
        if record is not None and record.collection == "uses":
            findings.extend(self.d.findings_by_use.get(record.id, ()))
        for finding in findings:
            if finding.body["lifecycle"] != "open" \
                    or judgment_freshness(self.snap, finding, superseded=False)["freshness"] != "current":
                continue
            if finding.body["category"] in ("proof_gap", "dependency_mismatch", "statement_refutation"):
                return "defect"
            if finding.body["category"] == "inconclusive":
                return "open"
        return None

    def independent_limit(self, target):
        """Adverse independent work and unresolved integration remain effective."""
        from .assessment import judgment_freshness
        checks = [self.d.judgment_info(c) for c in self.d.checks_by_target.get(_key(target), ())
                  if c.body["role"] == "independent" and c.id not in self.d.superseded]
        checks = [i for i in checks if i["state"] == "complete" and i["freshness"] == "current"
                  and self.d.independent_usable(i)]
        pending = {response.id: response for i in checks
                   if (response := self.d.responses.get(self.snap.get(i["ref"]).body["response_id"])) is not None
                   and response.body.get("pending_judgments")}
        if pending:
            # Only the selected current unit integration can account for these
            # rows; an unrelated disposition cannot grant support here.
            accounted = set()
            for argument in self.arguments_for(target):
                integration = self.d._coherent_integration(argument.id)
                if integration["state"] != "complete" or integration["freshness"] != "current":
                    continue
                for pin in integration["check_refs"]:
                    reconciliation = self.snap.get(pin)
                    accounted.update(ident for ident, response in pending.items()
                                     if self.pending_accounted(response, reconciliation))
            if set(pending) - accounted:
                return "open"
        record = self.snap.get(target)
        targets = [target]
        if record is not None and record.collection == "arguments":
            targets.append(record.body["target"])
        reconciliations = [r for r in self.d.reconciliations
                           if r.body["target"] in targets and r.id not in self.d.superseded_reconciliations
                           and judgment_freshness(self.snap, r, superseded=False)["freshness"] == "current"]
        if any(r.body["decision"] == "unresolved" for r in reconciliations):
            return "open"
        adopted = self.d._integrated_checks(target, "composition")
        revised = {p["id"] for r in reconciliations
                   if r.body["decision"] in ("primary_revised", "independent_revised")
                   for p in r.body["independent_checks"]
                   if adopted
                   and any(c.pinned in r.body["successor_checks"] for c in adopted)
                   and self.snap.get(p).body["target"] == target
                   and self.snap.get(p).body["kind"] == "composition"
                   and self.snap.get(p).body.get("extent") == "whole_unit"}
        adverse = [i for i in checks if i["ref"]["id"] not in revised]
        if any(i["outcome"] in ("gap", "refuted") for i in adverse):
            return "defect"
        if any(i["outcome"] == "inconclusive" for i in adverse):
            return "open"
        return None

    def resolve(self, target, kind):
        """Return supported, defect or open using explicit and encompassing work."""
        finding = self.local_finding(target)
        if finding is not None:
            return finding
        independent = self.independent_limit(target)
        if independent is not None:
            return independent
        explicit = self.d._explicit_local_basis(target, kind)
        # An explicit inconclusive result cannot be replaced by an encompassing label.
        obligation = self.d.obligation_for(target, kind)
        if explicit != "open" or (obligation and self.d._candidates(obligation)):
            return explicit
        record = self.snap.get(target)
        if record is None or kind == "external_source":
            return "open"
        for argument in self.arguments_for(target):
            if argument.body["lifecycle"] != "registered":
                continue
            if self.local_finding(_ref(argument)) is not None or self.independent_limit(_ref(argument)) is not None:
                continue
            for check in self.whole_checks(argument):
                if self.grounded(record, argument, check) and self.d._check_conditions_current(check, target):
                    return "supported"
        return "open"

    def synopsis_matches_exact(self, target, spec):
        """Reuse only the same statement, source and setup, never a shorter hypothesis."""
        record = self.snap.get(target)
        if record is None or spec.body.get("scope_id") != record.body.get("scope_id"):
            return False
        pin = spec.body.get("statement_ref")
        if pin is not None:
            pinned = self.snap.version(pin["collection"], pin["id"], pin["version"])
            if pinned is None or self.snap.facets(pinned)["statement"] != self.snap.facets(record)["statement"]:
                return False
        elif digest(spec.body.get("statement")) != digest(record.body.get("statement")):
            return False
        evidence = set(spec.body.get("evidence_refs", ()))
        passages = {p["anchor_id"] for p in record.body.get("passages", ())
                    if p["role"] in ("statement", "definition")}
        return not evidence or evidence <= passages

    def source_basis(self, target, spec=None):
        """Reuse current source verification or grounded examined internal detail."""
        from .assessment import judgment_freshness
        record = self.snap.get(target)
        if record is None:
            return False
        external = spec is None and record.collection == "items" \
            and record.body.get("kind") == "external_result" and record.body.get("origin") == "source" \
            and record.body.get("statement", {}).get("form") in ("verbatim", "transcription")
        if external or (spec is not None and self.synopsis_matches_exact(target, spec)):
            rows = sorted(self.d.observations_by_target.get(_key(target), ()), key=self.d._observation_order)
            if rows:
                latest = rows[-1]
                if latest.body["result"] == "matched" and self.d._source_match_has_evidence(record) \
                        and judgment_freshness(self.snap, latest, superseded=False)["freshness"] == "current":
                    # The ordinary external-item template has no separate spec.
                    # Its current exact statement and source examination suffice;
                    # adding a spec afterward would invalidate saved bindings.
                    return not external or self.resolve(target, "external_source") == "supported"
        internal = record.collection == "parts" or record.body.get("kind") in INTERMEDIATE_KINDS
        if not internal or (spec is not None and not self.synopsis_matches_exact(target, spec)):
            return False
        if self.local_finding(target) is not None:
            return False
        rows = sorted(self.d.observations_by_target.get(_key(target), ()), key=self.d._observation_order)
        if rows and (rows[-1].body["result"] != "matched"
                     or judgment_freshness(self.snap, rows[-1], superseded=False)["freshness"] != "current"):
            return False
        # A saved local derivation can preserve an internal result even when
        # the enclosing proof has a failed final combination.
        if self.d._source_match_has_evidence(record):
            for group in self.snap.groups_for_conclusion(target):
                if self.d._explicit_local_basis(_ref(group), "derivation") == "supported":
                    return True
        for argument in self.arguments_for(target):
            for check in self.whole_checks(argument):
                if self.grounded(record, argument, check):
                    return True
        return False


__all__ = ["PROTOCOL", "LocalBasis", "enabled", "examination_complete"]
