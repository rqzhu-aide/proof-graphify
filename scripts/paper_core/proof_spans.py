"""Resolve immutable proof selections without changing captured source excerpts."""
from __future__ import annotations

from .canonical import digest
from .refs import facet_digests


def _argument_proof(state, pin):
    argument = state.version("arguments", pin["id"], pin["version"])
    return None if argument is None or argument.retired else facet_digests("arguments", argument.body)["proof"]


def _reviewed_argument_proof(state, review, pin):
    """Compare physical-span provenance under its original private policy."""
    if not hasattr(state, "live"):
        from .validation import State
        state = State(state, [])
    expected = _argument_proof(state, pin)
    current = state.live("arguments", pin["id"])
    if current is None:
        return None
    if facet_digests("arguments", current.body)["proof"] == expected:
        return expected
    stored = state.db.binding("source_reviews", review.id, review.version)
    if stored is not None:
        from .bindings import evidence_maintenance_compatible
        for entry in stored["bindings"]["records"]:
            if entry["ref"] == pin and entry["facet"] == "proof" \
                    and evidence_maintenance_compatible(state, entry, current):
                return expected
    return None


def _boundary_argument_proof(state, review, pin):
    """Unmarked certificates retain their original digest comparison policy."""
    db = getattr(state, "db", state)
    stored = db.binding("source_reviews", review.id, review.version)
    if stored is not None and any(entry["ref"] == pin and isinstance(entry.get("evidence_maintenance"), dict)
                                  and entry["evidence_maintenance"].get("version") == 1
                                  for entry in stored["bindings"]["records"]):
        return _reviewed_argument_proof(state, review, pin)
    return _argument_proof(state, pin)


def review_covers_added_anchor(state, review, argument, anchor_id):
    """A maintained source link does not enlarge the certified proof extent."""
    stored = state.db.binding("source_reviews", review.id, review.version)
    if stored is None:
        return False
    from .bindings import evidence_maintenance_compatible, _selection_covers
    anchor = state.live("anchors", anchor_id)
    if anchor is None:
        return False
    for entry in stored["bindings"]["records"]:
        if entry["ref"]["collection"] == "arguments" and entry["ref"]["id"] == argument.id \
                and entry["facet"] == "proof" and evidence_maintenance_compatible(state, entry, argument):
            return _selection_covers(state, entry["evidence_maintenance"]["selections"], anchor)
    return False


def boundary_selection_digest(state, boundary):
    """Private source selection, excluding the reviewer's administrative metadata."""
    body = boundary.body
    selected = {"target": body["target"], "state": body["state"], "argument_ids": sorted(body["argument_ids"]),
                "anchor_refs": sorted(body["anchor_refs"], key=lambda ref: (ref["id"], ref["version"]))}
    pin = body["source_review_ref"]
    review = state.version("source_reviews", pin["id"], pin["version"])
    if review is not None and not review.retired and "proof_spans" in review.body:
        grouped = {}
        for row in review.body["proof_spans"]:
            argument, anchor = row["argument_ref"], row["anchor_ref"]
            if argument["id"] in body["argument_ids"]:
                key = (argument["id"], _boundary_argument_proof(state, review, argument), anchor["id"], anchor["version"])
                grouped.setdefault(key, []).append((row["start_offset"], row["end_offset"]))
        selected["proof_spans"] = [{"argument_id": key[0], "argument_proof": key[1],
                                   "anchor_ref": {"collection": "anchors", "id": key[2], "version": key[3]},
                                   "intervals": uncovered_spans([], grouped[key])}
                                  for key in sorted(grouped, key=lambda value: (value[0], value[1] or "", value[2], value[3]))]
    return digest(selected)


def reviewed_spans(state, review, argument, anchor_refs):
    """Return required ranges by anchor, or None for an incomplete certificate.

    Missing selectors retain the historical whole-anchor meaning. An explicit
    selection pins its argument's proof inputs and cannot lose a reviewed
    continuation by dropping its anchor from the mutable boundary record.
    """
    anchors = {}
    for pin in anchor_refs:
        anchor = state.version("anchors", pin["id"], pin["version"])
        if anchor is None or anchor.retired:
            return None
        anchors[pin["id"]] = anchor
    if "proof_spans" not in review.body:
        return {identity: [(0, len(anchor.body["excerpt"]))] for identity, anchor in anchors.items()}
    selected = [row for row in review.body["proof_spans"] if row["argument_ref"]["id"] == argument.id
                and _reviewed_argument_proof(state, review, row["argument_ref"]) is not None]
    pins = {(pin["id"], pin["version"]) for pin in anchor_refs}
    if not selected or {(row["anchor_ref"]["id"], row["anchor_ref"]["version"]) for row in selected} != pins:
        return None
    spans = {identity: [] for identity in anchors}
    for row in selected:
        identity = row["anchor_ref"]["id"]
        start, end = row["start_offset"], row["end_offset"]
        if not 0 <= start < end <= len(anchors[identity].body["excerpt"]):
            return None
        spans[identity].append((start, end))
    return spans


def uncovered_spans(intervals, required):
    """Subtract coverage intervals from the required union, using character offsets."""
    union = []
    for start, end in sorted(required):
        if start >= end:
            continue
        if union and start <= union[-1][1]:
            union[-1][1] = max(union[-1][1], end)
        else:
            union.append([start, end])
    covered, missing = sorted(intervals), []
    for start, end in union:
        cursor = start
        for left, right in covered:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                missing.append([cursor, left])
            cursor = max(cursor, min(right, end))
        if cursor < end:
            missing.append([cursor, end])
    return missing
