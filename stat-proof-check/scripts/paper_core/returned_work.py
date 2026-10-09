"""Consume explicitly named saved returns once, using existing intake history."""
from __future__ import annotations

from pathlib import Path

from .bindings import task_binding_changes
from .canonical import canonical_bytes, load_json_bytes
from .controller import RESPONSE_LIMIT, read_bounded, stage_submission_envelope, submit_work
from .errors import InvalidRequest
from .packets import independent_context_binding, independent_context_changes
from .paths import resolve_path
from .refs import relation_members
from .validation import State
from .work import derive_work


def _response(raw):
    try:
        value = load_json_bytes(raw)
        canonical_bytes(value)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InvalidRequest(f"returned response is not valid JSON: {exc}", code="JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise InvalidRequest("returned response must be an object", code="RESPONSE_SHAPE")
    return value


def _content(response):
    # Only the delivery wrapper is administrative. Keep every authored field,
    # including unknown fields, omissions, reasoning, and question identifiers.
    return canonical_bytes({key: value for key, value in response.items() if key != "packet_id"})


def _provenance(envelope):
    return {key: envelope.get(key) for key in
            ("reviewer", "qualification_id", "exposure", "exposure_note", "rebase_packet_id")}


def _assignment(manifest):
    work = manifest["work"]
    return work["audit_id"], manifest["mode"], tuple(sorted(task["id"] for task in work["tasks"]))


def _binding_identity(db, manifest):
    """Compare captured science, including added neutral context, across wrappers."""
    def unpin(value):
        if isinstance(value, dict):
            return {key: unpin(child) for key, child in value.items()
                    if key != "version" or not {"collection", "id"} <= value.keys()}
        if isinstance(value, list):
            return [unpin(child) for child in value]
        return value

    def relations(rows):
        # Membership versions may change without changing the relevant facets.
        # Their captured identities, together with bound record digests, suffice.
        values = [{"relation": row["relation"], "key": row["key"],
                   "members": sorted([[c, i] for c, i, _ in relation_members(db.conn,
                       row["relation"], row["key"], revision=manifest["base_revision"])])}
                  for row in rows]
        return sorted(values, key=canonical_bytes)

    tasks = []
    for task in sorted(manifest["work"]["tasks"], key=lambda row: row["id"]):
        value = {key: unpin(task[key]) for key in ("id", "target", "kind", "role", "action",
            "neutral_question", "coherent_scope", "coherent_scopes") if key in task}
        value["consumed_inputs"] = sorted(unpin(task["consumed_inputs"]), key=canonical_bytes)
        value["membership_guards"] = relations(task["membership_guards"])
        tasks.append(value)
    context = independent_context_binding(State(db, []), manifest)
    neutral = None if context is None else {
        "records": sorted(unpin(context["records"]), key=canonical_bytes),
        "relations": relations(context["relations"])}
    return canonical_bytes({"tasks": tasks, "independent_context": neutral})


def _fresh(db, manifest):
    state = State(db, [])
    for task in manifest["work"]["tasks"]:
        changes = task_binding_changes(state, task, packet=manifest)
        if changes["records"] or changes["relations"]:
            return False
    if manifest["mode"] == "independent":
        changes = independent_context_changes(state, manifest)
        if changes["records"] or changes["relations"]:
            return False
    return True


class _SavedReturns:
    """Read metadata once per audit; only load blobs for matching assignments."""

    def __init__(self, db):
        self.db = db
        self.packets, self.audits, self.attempts, self.bindings = {}, {}, {}, {}

    def manifest(self, packet_id):
        if packet_id not in self.packets:
            packet = self.db.packet(packet_id)
            self.packets[packet_id] = packet["manifest"] if packet else None
        return self.packets[packet_id]

    def history(self, audit_id):
        if audit_id not in self.audits:
            grouped, after = {}, None
            while True:
                page = self.db.work_submissions(audit_id=audit_id, limit=100, after=after)
                for row in page:
                    if row["role"] not in ("primary", "independent"):
                        continue
                    manifest = self.manifest(row["packet_id"])
                    if manifest and isinstance(manifest.get("work"), dict):
                        grouped.setdefault(_assignment(manifest), []).append(row)
                if len(page) < 100:
                    break
                after = [page[-1]["received_at"], page[-1]["request_id"]]
            self.audits[audit_id] = grouped
        return self.audits[audit_id]

    def attempt(self, row):
        request_id = row["request_id"]
        if request_id not in self.attempts:
            saved = self.db.work_submission(request_id)
            envelope = load_json_bytes(self.db.get_blob(saved["envelope_sha256"]))
            self.attempts[request_id] = (saved, envelope, None)
        return self.attempts[request_id]

    def binding_identity(self, manifest):
        packet_id = manifest["packet_id"]
        if packet_id not in self.bindings:
            self.bindings[packet_id] = _binding_identity(self.db, manifest)
        return self.bindings[packet_id]

    def match(self, manifest, envelope, response):
        candidates = self.history(manifest["work"]["audit_id"]).get(_assignment(manifest), [])
        content = _content(response)
        terminal = None
        for row in reversed(candidates):
            saved, old_envelope, old_content = self.attempt(row)
            if _provenance(old_envelope) != _provenance(envelope):
                continue
            if old_content is None:
                try:
                    old_content = _content(_response(self.db.get_blob(saved["response_sha256"])))
                except InvalidRequest:
                    continue
                self.attempts[saved["request_id"]] = saved, old_envelope, old_content
            if old_content != content:
                continue
            # Both wrappers must capture the same current science. Extending a
            # neutral source context can keep task IDs and both bindings fresh.
            # Same-packet history remains a saved attempt when stale.
            if saved["packet_id"] != manifest["packet_id"] and (
                    not _fresh(self.db, manifest)
                    or not _fresh(self.db, self.manifest(saved["packet_id"]))
                    or self.binding_identity(manifest) != self.binding_identity(self.manifest(saved["packet_id"]))):
                continue
            if saved["state"] == "received":
                return saved
            terminal = terminal or saved
        return terminal

    def remember(self, request_id, manifest):
        saved = self.db.work_submission(request_id)
        if saved is not None:
            rows = self.history(manifest["work"]["audit_id"]).setdefault(_assignment(manifest), [])
            if not any(row["request_id"] == request_id for row in rows):
                rows.append(saved)
            self.attempts.pop(request_id, None)


def _locations(entry):
    paths = list(dict.fromkeys(str(path) for path in entry.get("prior_response_paths", []) if path))
    return {"response_path": str(entry["response_path"]) if entry.get("response_path") else None,
            "prior_response_paths": paths,
            "existing_prior_response_paths": [path for path in paths if Path(path).is_file()]}


def _read_return(entry, locations):
    path = locations["response_path"]
    if path is None:
        raise InvalidRequest("group member has no expected response path; select a known location explicitly",
                             code="RESPONSE_MISSING")
    raw = read_bounded(path, RESPONSE_LIMIT)
    response = _response(raw)
    if response.get("packet_id") != entry["packet_id"]:
        raise InvalidRequest("returned response must name its original saved packet", code="PACKET_MISMATCH")
    if not entry.get("response_override"):
        alternatives = []
        for prior in locations["existing_prior_response_paths"]:
            if resolve_path(prior) == resolve_path(path):
                continue
            try:
                same = canonical_bytes(_response(read_bounded(prior, RESPONSE_LIMIT))) == canonical_bytes(response)
            except InvalidRequest:
                same = False
            if not same:
                alternatives.append(prior)
        if alternatives:
            raise InvalidRequest("distinct saved response files need an explicit response-path selection",
                                 code="RESPONSE_SELECTION", records=[path, *alternatives])
    return raw, response


def consume_returns(db, returns):
    """One finite pass over primary/independent packet paths and true provenance.

    Reconciliation retains its existing direct submission and correction route.
    No response is repaired, relabeled, dispatched, or selected from history.
    """
    selected = tuple(dict(entry) for entry in returns)
    saved_returns, outputs, audit_ids, assignments = _SavedReturns(db), [], set(), {}
    for entry in selected:
        packet_id = entry["packet_id"]
        locations = _locations(entry)
        output = {"packet_id": packet_id, **locations}
        outputs.append(output)
        manifest = saved_returns.manifest(packet_id)
        if manifest is None or not isinstance(manifest.get("work"), dict):
            output.update(status="deferred", decision="unknown_packet", diagnostics=["No saved work assignment."])
            continue
        audit_id, mode, task_ids = _assignment(manifest)
        audit_ids.add(audit_id)
        assignments[packet_id] = audit_id, task_ids
        if mode not in ("primary", "independent"):
            output.update(status="deferred", decision="use_existing_integration_route",
                          diagnostics=["Submit this integration through the existing direct command."])
            continue
        try:
            raw, response = _read_return(entry, locations)
        except InvalidRequest as exc:
            missing = exc.code == "RESPONSE_MISSING" or (
                exc.code == "FILE_UNREADABLE" and locations["response_path"] is not None
                and not Path(locations["response_path"]).exists())
            output.update(status="missing" if missing else
                          "deferred" if exc.code == "RESPONSE_SELECTION" else "locally_failed",
                          decision="missing_return" if missing else "invalid_local_response",
                          **exc.to_json())
            continue
        envelope = stage_submission_envelope(packet_id=packet_id, reviewer=entry["reviewer"],
            response_bytes=raw, exposure=entry.get("exposure"), exposure_note=entry.get("exposure_note", ""))
        previous = saved_returns.match(manifest, envelope, response)
        if previous is not None and previous["state"] == "received":
            # Stored envelope and bytes are recovery authority, including when
            # the selected local copy differs only in formatting.
            receipt = submit_work(db, envelope_bytes=db.get_blob(previous["envelope_sha256"]),
                                  response_bytes=db.get_blob(previous["response_sha256"]))
            output.update(status="submitted", decision="recover_received", receipt=receipt,
                          request_id=previous["request_id"], state=receipt["state"])
            saved_returns.remember(previous["request_id"], manifest)
            continue
        if previous is not None:
            output.update(status="already_saved", decision="saved_terminal_return",
                          request_id=previous["request_id"], state=previous["state"], receipt=previous["result"])
            if not _fresh(db, manifest):
                output["diagnostics"] = ["This historical assignment changed; inspect affected current work or its limitation."]
            continue
        if not _fresh(db, manifest):
            output.update(status="deferred", decision="changed_context_requires_affected_work",
                          diagnostics=["The original assignment changed; prepare affected current work or disclose its limitation."])
            continue
        receipt = submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
        output.update(status="submitted" if receipt["state"] in ("accepted", "received") else "deferred",
                      decision="submit", request_id=envelope["request_id"], state=receipt["state"], receipt=receipt)
        saved_returns.remember(envelope["request_id"], manifest)

    current_views = {audit_id: derive_work(db, audit_id=audit_id) for audit_id in audit_ids}
    remaining = {audit_id: sorted(task["id"] for task in view["tasks"] if task["state"] != "satisfied")
                 for audit_id, view in current_views.items()}
    for output in outputs:
        audit_and_tasks = assignments.get(output["packet_id"])
        output["remaining_task_ids"] = ([] if audit_and_tasks is None else
            sorted(set(audit_and_tasks[1]) & set(remaining[audit_and_tasks[0]])))
    statuses = ("submitted", "already_saved", "missing", "deferred", "locally_failed")
    return {"entries": outputs, "counts": {status: sum(row["status"] == status for row in outputs)
            for status in statuses}, "remaining_task_ids": sorted({task["id"] for view in current_views.values()
                for task in view["tasks"] if task["required"] and task["state"] != "satisfied"})}
