"""Current-item correction and concise feedback from the saved versions."""
from .authoring import _live, correct_claim
from .contract import Id, Int, Obj, validate_shape
from .errors import InvalidRequest
from .semantics import related


def sync_current(db, item_id, expected_version):
    """Align the direct exact selection with the current saved source item."""
    errors = validate_shape(Obj({"item_id": Id("items"), "expected_version": Int(1)}),
                            {"item_id": item_id, "expected_version": expected_version})
    if errors:
        raise InvalidRequest("invalid current-item correction request",
                             code="CLAIM_CORRECTION_INPUT", records=errors)
    item = _live(db, "items", item_id)
    return correct_claim(db, item_id, expected_version, {
        "statement": item.body["statement"]["text"],
        "statement_anchors": [p["anchor_id"] for p in item.body["passages"]
                              if p["role"] == "statement"]})


def compact_receipt(db, result):
    """Describe the original saved change, also when its receipt is replayed."""
    pins = {p["collection"]: p for p in (result.get("receipt") or {}).get("changed", [])}
    item = (db.version("items", result["item_id"], pins["items"]["version"])
            if "items" in pins else _live(db, "items", result["item_id"]))
    spec = (db.version("target_specs", pins["target_specs"]["id"], pins["target_specs"]["version"])
            if "target_specs" in pins else related(db, "target_specs", "/target", item.ref)[0])
    before_spec = db.version("target_specs", spec.id, spec.version - 1) if "target_specs" in pins else spec
    if "items" not in pins and "target_specs" in pins:
        # A target-only sync leaves the item unchanged on both sides. Its old
        # exact selection can still point to a different historical item body.
        pin = spec.body["statement_ref"]
        item = db.version(pin["collection"], pin["id"], pin["version"])
    before_item = db.version("items", item.id, item.version - 1) if "items" in pins else item

    def exact_text(spec):
        pin = spec.body["statement_ref"]
        return db.version(pin["collection"], pin["id"], pin["version"]).body["statement"]["text"]

    def excerpt_offset(old, new):
        first = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
        return max(0, first - 80) if old != new else 0

    item_offset = excerpt_offset(before_item.body["statement"]["text"], item.body["statement"]["text"])
    exact_offset = excerpt_offset(exact_text(before_spec), exact_text(spec))

    def excerpt(text, start):
        return {"text": text[start:start + 240], "offset": start,
                "truncated": start > 0 or len(text) > start + 240, "characters": len(text)}

    def side(item, spec):
        return {"item": item.pinned,
                "statement_excerpt": excerpt(item.body["statement"]["text"], item_offset),
                "statement_anchors": [p["anchor_id"] for p in item.body["passages"] if p["role"] == "statement"],
                "exact_target": spec.pinned,
                "exact_statement_excerpt": excerpt(exact_text(spec), exact_offset),
                "exact_evidence_refs": spec.body["evidence_refs"], "fidelity_ref": spec.body["fidelity_ref"]}

    return {**result, "actual_change": {"before": side(before_item, before_spec), "after": side(item, spec)}}
