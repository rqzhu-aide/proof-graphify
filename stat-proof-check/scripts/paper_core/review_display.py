"""Research issue display, derived separately from logical support judgments."""
from __future__ import annotations

from collections import defaultdict


SEVERITIES = ("minor", "moderate", "severe")


def _key(ref):
    return f"{ref['collection']}:{ref['id']}"


def display(status, refs=(), *, unrated=0, explanation=""):
    return {"status": status, "finding_refs": sorted(set(refs)),
            "unrated_count": unrated, "explanation": explanation}


class ReviewDisplay:
    """Use existing finding freshness and saved review evidence, without new bindings."""

    def __init__(self, derivation):
        self.d = derivation
        self.snap = derivation.snap
        self.by_target = defaultdict(set)
        self.by_owner = defaultdict(set)
        self.by_use = defaultdict(set)
        self.findings = {f.id: f for f in derivation.findings}
        self.displays = {}
        for finding in derivation.findings:
            target = finding.body["target"]
            self.by_target[_key(target)].add(finding.id)
            owner = self.snap.owner_of(target)
            if owner is not None:
                self.by_owner[owner.id].add(finding.id)
            for use_id in finding.body["affected_uses"]:
                self.by_use[use_id].add(finding.id)
                owner = self.snap.owner_of({"collection": "uses", "id": use_id})
                if owner is not None:
                    self.by_owner[owner.id].add(finding.id)

    def _disputed(self, finding):
        from .assessment import judgment_freshness
        # Scope a disagreement to the finding's own evidence, not all findings
        # owned by a result whose independent review happens to be unresolved.
        for pin in finding.body["check_refs"]:
            check = self.snap.version("checks", pin["id"], pin["version"])
            if check is None:
                continue
            target, kind = check.body["target"], check.body["kind"]
            current = [self.d.judgment_info(c) for c in self.d.checks_by_target.get(_key(target), ())
                       if c.body["kind"] == kind]
            current = [i for i in current if i["state"] == "complete"
                       and i["freshness"] == "current" and not i["superseded"]
                       and (i["role"] != "independent" or self.d.independent_usable(i))]
            linked = {(r["id"], r["version"]) for r in finding.body["check_refs"]}
            for rec in sorted(self.d.reconciliations, key=lambda r: (r.revision, r.id), reverse=True):
                compared = rec.body["primary_checks"] + rec.body["independent_checks"] + rec.body["successor_checks"]
                if rec.id in self.d.superseded_reconciliations or rec.body["target"] != target \
                        or not linked.intersection((r["id"], r["version"]) for r in compared) \
                        or judgment_freshness(self.snap, rec, superseded=False)["freshness"] != "current":
                    continue
                if {(i["ref"]["id"], i["ref"]["version"]) for i in current} <= \
                        {(r["id"], r["version"]) for r in compared}:
                    if rec.body["decision"] == "unresolved":
                        return True
                    # This target is settled; other linked evidence may still be disputed.
                    break
            else:
                if len({i["outcome"] for i in current}) > 1:
                    return True
        return False

    def finding(self, finding_id):
        from .assessment import judgment_freshness
        if finding_id in self.displays:
            return self.displays[finding_id]
        finding = self.findings[finding_id]
        body = finding.body
        freshness = judgment_freshness(self.snap, finding,
                                      superseded=body["lifecycle"] == "superseded")["freshness"]
        if body["lifecycle"] != "open" or freshness != "current":
            value = display("historical", explanation="Resolved, superseded or noncurrent finding; retained as history.")
        elif body["category"] == "inconclusive" or self._disputed(finding):
            value = display("unresolved", [finding_id], explanation="This concern remains unresolved; no defect severity is established.")
        elif body.get("severity") in SEVERITIES:
            value = display(body["severity"], [finding_id], explanation=f"Current applicable {body['severity']} issue.")
        else:
            value = display("unrated", [finding_id], unrated=1, explanation="Current issue; severity not rated.")
        self.displays[finding_id] = value
        return value

    def applicable(self, *, targets=(), owners=(), use_ids=(), finding_ids=()):
        ids = set(finding_ids).intersection(self.findings)
        for target in targets:
            ids.update(self.by_target.get(_key(target), ()))
        for owner in owners:
            ids.update(self.by_owner.get(owner, ()))
        for use_id in use_ids:
            ids.update(self.by_use.get(use_id, ()))
        return sorted(ids)

    def assessment(self, assessment, *, targets=(), owners=(), use_ids=(), finding_ids=None):
        if finding_ids is None:
            # Reducer refs are scoped to represented obligations. Explicit
            # owner/target inputs also cover findings with no linked check.
            finding_ids = [] if targets or owners or use_ids else [
                r if isinstance(r, str) else r["id"] for r in assessment.get("finding_refs", ())]
        ids = self.applicable(targets=targets, owners=owners, use_ids=use_ids, finding_ids=finding_ids)
        current = [(ident, self.finding(ident)) for ident in ids
                   if self.finding(ident)["status"] != "historical"]
        refs = [ident for ident, _ in current]
        unrated = sum(row["status"] == "unrated" for _, row in current)
        unresolved = any(row["status"] == "unresolved" for _, row in current)
        rated = [row["status"] for _, row in current if row["status"] in SEVERITIES]
        if rated:
            status = max(rated, key=SEVERITIES.index)
            note = f"Highest current applicable rated issue: {status}."
            if unrated:
                note += f" {unrated} other issue(s) have no severity rating."
            if unresolved or assessment.get("independent_review") == "disputed":
                note += " Separate unresolved review questions remain."
        elif unresolved:
            status, note = "unresolved", "Applicable concern remains unresolved."
        elif unrated:
            status, note = "unrated", "Current applicable issues have no severity rating."
        elif assessment.get("state") == "green":
            status, note = "checked", "Current examination supports the scoped mathematics."
            if assessment.get("independent_review") == "pending":
                note += " Initial review; independent review pending."
        elif assessment.get("availability") in ("conditional", "unavailable") \
                and assessment.get("local_state") == "green":
            status, note = "dependency", "Local reasoning is supported; prerequisite support remains unresolved."
        elif assessment.get("label") in ("conditional", "premise unavailable"):
            status, note = "dependency", "Depends on unresolved result."
        elif assessment.get("state") == "gray":
            status, note = "unassessed", "No current positive mathematical examination supports this scope."
        else:
            status, note = "unresolved", "The scoped examination is unresolved or requires review."
        return display(status, refs, unrated=unrated, explanation=note)

    def attach(self, assessment, **scope):
        if self.d.audit is not None:
            assessment["review_display"] = self.assessment(assessment, **scope)
        return assessment
