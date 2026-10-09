"""Located proof selections over immutable, complete captured excerpts.

Selections identify evidence, not a character coverage obligation.
"""
from __future__ import annotations

from .canonical import digest
from .refs import facet_digests


def uncovered_spans(intervals, required):
    union = []
    for start, end in sorted(required):
        if start >= end:
            continue
        if union and start <= union[-1][1]:
            union[-1][1] = max(union[-1][1], end)
        else:
            union.append([start, end])
    missing = []
    for start, end in union:
        cursor = start
        for left, right in sorted(intervals):
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


def reviewed_spans(state, review, argument, anchor_refs):
    anchors = {}
    for pin in anchor_refs:
        anchor = state.version("anchors", pin["id"], pin["version"])
        if anchor is None or anchor.retired:
            return None
        anchors[(pin["id"], pin["version"])] = anchor
    if "proof_spans" not in review.body:
        return {key[0]: [(0, len(anchor.body["excerpt"]))] for key, anchor in anchors.items()}
    rows = [row for row in review.body["proof_spans"] if row["argument_ref"]["id"] == argument.id]
    if not rows or {(row["anchor_ref"]["id"], row["anchor_ref"]["version"]) for row in rows} != set(anchors):
        return None
    selected = {key[0]: [] for key in anchors}
    for row in rows:
        pin = row["argument_ref"]
        original = state.version("arguments", pin["id"], pin["version"])
        if original is None or original.retired or facet_digests("arguments", original.body)["proof"] != \
                facet_digests("arguments", argument.body)["proof"]:
            return None
        key = row["anchor_ref"]["id"], row["anchor_ref"]["version"]
        start, end = row["start_offset"], row["end_offset"]
        if not 0 <= start < end <= len(anchors[key].body["excerpt"]):
            return None
        selected[key[0]].append((start, end))
    return {identity: uncovered_spans([], spans) for identity, spans in selected.items()}


def boundary_selection_digest(state, boundary):
    body = boundary.body
    pin = body["source_review_ref"]
    review = state.version("source_reviews", pin["id"], pin["version"])
    rows = [] if review is None else [row for row in review.body.get("proof_spans", [])
                                     if row["argument_ref"]["id"] in body["argument_ids"]]
    return digest({"target": body["target"], "state": body["state"],
                   "argument_ids": sorted(body["argument_ids"]),
                   "anchor_refs": sorted(body["anchor_refs"], key=lambda ref: (ref["id"], ref["version"])),
                   "proof_spans": sorted(rows, key=lambda row: (row["argument_ref"]["id"],
                       row["anchor_ref"]["id"], row["start_offset"], row["end_offset"]))})
