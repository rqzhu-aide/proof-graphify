"""The selected overview's field boundary and its private native import route."""
from __future__ import annotations

from contextlib import contextmanager

from .canonical import canonical_bytes, digest, sha256_bytes
from .contract import MAJOR_KINDS, validate_body
from .errors import InvalidRequest
from .storage import paper_record
from .validation import State

FIELDS = {
    "papers": {"title", "main_items", "scope", "exclusions"},
    "sources": {"path", "media_type", "blob_sha256"},
    "anchors": {"source_id", "source_version", "locator", "excerpt", "excerpt_sha256", "method", "limitation"},
    "items": {"kind", "label", "caption", "statement", "passages", "aliases", "uncertainty", "owner_id", "proof_idea"},
    "uses": {"from", "to", "type", "reason", "regime", "uncertainty", "evidence_refs"},
}
SELECTION_FIELDS = {"paper_id", "title", "scope", "item_ids", "use_ids", "main_item_ids", "source_ids",
                    "authoring_profile", "roots", "unresolved", "native_context"}
NATIVE_IMPORT_METADATA = frozenset({"legacy_overview_format", "legacy_overview_current_snapshot",
                                  "legacy_overview_snapshot_ids", "legacy_overview_backup"})
_NATIVE_IMPORT = object()


def native_import_active(db):
    return getattr(db, "_native_overview_import", None) is _NATIVE_IMPORT


def snapshot_digest(data):
    """Native authored-content identity, excluding appended comparisons."""
    content = {k: v for k, v in data.items() if k not in {"snapshot_id", "observations"}}
    if "source_revision" in content:
        content["source_revision"] = {k: v for k, v in content["source_revision"].items() if k != "created_at"}
    return digest(content)


def validate_overview_plan(db, plan, *, refresh_root=None):
    """Check normalized changes, then leave shape and linked-state checks to acceptance."""
    from .overview import SELECTION_ID, project
    paper = paper_record(db)
    current = db.head("overview_selections", SELECTION_ID)
    state = State(db, plan)
    selection = state.live("overview_selections", SELECTION_ID)
    errors = []
    malformed = [error for p in plan if p.body is not None for error in validate_body(p.collection, p.body)]
    if malformed:
        return malformed
    if selection is None or not isinstance(selection.body, dict):
        return ["overview writes require the default selected overview"]
    body = selection.body
    selected = {c: set() for c in ("items", "uses", "sources", "anchors")}
    for entry in (current, selection):
        if entry is None:
            continue
        for c, field in (("items", "item_ids"), ("uses", "use_ids"), ("sources", "source_ids")):
            values = entry.body.get(field, [])
            if isinstance(values, list) and all(isinstance(v, str) for v in values):
                selected[c].update(values)
        context = entry.body.get("native_context") or {}
        if isinstance(context, dict):
            selected["anchors"].update(v for v in context.get("anchor_ids", []) if isinstance(v, str))
        for c in ("items", "uses"):
            for identity in selected[c]:
                record = state.live(c, identity) if entry is selection else db.head(c, identity)
                if record and isinstance(record.body, dict):
                    evidence = ([p.get("anchor_id") for p in record.body.get("passages", []) if isinstance(p, dict)]
                                if c == "items" else record.body.get("evidence_refs", []))
                    selected["anchors"].update(v for v in evidence if isinstance(v, str))
    post_items = body.get("item_ids", [])
    profile = current.body["authoring_profile"] if current else body.get("authoring_profile")
    current_data = project(db)[0] if current else None
    prospective_paper = state.live("papers", paper.id)
    if prospective_paper and any(body.get(selected_field) != prospective_paper.body.get(paper_field)
            for selected_field, paper_field in (("title", "title"), ("scope", "scope"), ("main_item_ids", "main_items"))):
        errors.append("selected overview title, scope and main items must match the corresponding paper fields")
    for p in plan:
        where = f"edits/{p.index} {p.collection}:{p.id}"
        if p.op == "retire" or not isinstance(p.body, dict):
            errors.append(f"{where}: overview records are deselected, never retired or replaced with null")
            continue
        new, old = p.body, p.prev.body if p.prev else {}
        changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k) or (k in old) != (k in new)}
        c = p.collection
        if c == "overview_selections":
            if p.id != SELECTION_ID or set(new) - SELECTION_FIELDS or new.get("paper_id") != paper.id:
                errors.append(f"{where}: overview must use the default selection and existing paper")
            if new.get("authoring_profile") != profile or profile not in ("focused", "compatibility"):
                errors.append(f"{where}: ordinary overview edits preserve the authoring profile")
            if p.prev and new.get("roots") != old.get("roots"):
                errors.append(f"{where}: ordinary overview edits preserve selection roots")
            context = new.get("native_context") or {}
            prior_context = old.get("native_context") or {}
            archived = context.get("archived_observations", []) if isinstance(context, dict) else []
            prior_archived = prior_context.get("archived_observations", [])
            if not isinstance(archived, list) or any(observation not in archived for observation in prior_archived):
                errors.append(f"{where}: existing archived comparisons are immutable history and must be retained")
            if current_data is not None and isinstance(context, dict):
                historical = {o["id"]: o for o in current_data.get("observations", [])}
                if (not isinstance(archived, list) or any(not isinstance(o, dict)
                        or historical.get(o.get("id")) != o for o in archived)):
                    errors.append(f"{where}: archived comparisons preserve their original observation bytes")
            if profile == "focused" and isinstance(context, dict) and context.get("groups", {}) != prior_context.get("groups", {}):
                errors.append(f"{where}: focused overview authoring does not add native proof groups")
            if profile == "focused":
                prior_ids = set(old.get("item_ids", []))
                for identity in new.get("item_ids", []):
                    item = state.live("items", identity)
                    if identity not in prior_ids and item and (item.body["kind"] not in MAJOR_KINDS or item.body.get("owner_id") is not None):
                        errors.append(f"{where}: newly selected focused items are major statements without proof-step ownership")
            continue
        if c == "observations":
            context = new.get("context_data") or {}
            target = new.get("target") or {}
            native = context.get("native_observation") if isinstance(context, dict) else None
            actual_input = None
            if current_data is not None and target.get("collection") in ("items", "uses"):
                from .export_import import _overview_target_digest
                if any(r["id"] == target.get("id") for r in current_data[target["collection"]]):
                    actual_input = _overview_target_digest(current_data, target["collection"], target["id"])
            if (p.op != "create" or new.get("context_kind") != "overview"
                    or not isinstance(context, dict) or context.get("selection_id") != SELECTION_ID
                    or target.get("collection") not in ("items", "uses")
                    or target.get("id") not in body.get("item_ids" if target.get("collection") == "items" else "use_ids", [])
                    or not isinstance(native, dict)
                    or any(native.get(k) != new.get(k) for k in ("target", "result", "reviewer", "note", "created_at"))
                    or native.get("input_snapshot") != context.get("input_snapshot")
                    or not isinstance(context.get("input_snapshot"), str)
                    or current_data is not None and context.get("input_snapshot") != actual_input):
                errors.append(f"{where}: overview comparisons need the actual selected native input snapshot and selected target")
            continue
        if c not in FIELDS or c == "papers" and (p.op != "replace" or p.id != paper.id):
            errors.append(f"{where}: outside the overview field boundary")
            continue
        if c != "papers" and p.id not in selected[c]:
            errors.append(f"{where}: record is neither selected nor explicitly newly selected")
        allowed = FIELDS[c]
        if c == "papers" and refresh_root is not None and new.get("source_root") == refresh_root:
            allowed = allowed | {"source_root"}
        if p.op == "create" and c == "sources":
            allowed = allowed | {"paper_id", "capture_method", "limitation"}
            if new.get("paper_id") != paper.id:
                errors.append(f"{where}: selected sources belong to the existing paper")
        if p.op == "create" and c == "items":
            allowed = allowed | {"origin", "scope_id"}
            if new.get("origin") != "source" or new.get("scope_id") is not None:
                errors.append(f"{where}: new overview items have source origin and no audit scope")
        if changed - allowed:
            errors.append(f"{where}: overview cannot change fields {sorted(changed - allowed)}")
        if c == "anchors" and new.get("source_id") not in selected["sources"]:
            errors.append(f"{where}: overview evidence needs a selected captured source")
        if c == "uses" and any(not isinstance(new.get(k), dict) or new[k].get("collection") != "items"
                               or new[k].get("id") not in post_items for k in ("from", "to")):
            errors.append(f"{where}: overview connection endpoints remain selected items")
        if c == "items" and profile == "focused" and (p.op == "create" or {"kind", "owner_id"} & changed):
            if new.get("kind") not in MAJOR_KINDS or new.get("owner_id") is not None:
                errors.append(f"{where}: focused overview authoring selects major statements without proof-step ownership")
    return errors


def validate_native_import_plan(db, plan):
    """Only the backed-up native conversion may populate its fresh temporary store."""
    allowed = {"sources", "anchors", "items", "uses", "observations", "overview_selections", "groups",
               "application_details", "source_issues", "identity_maps"}
    paper = paper_record(db)
    errors = []
    for p in plan:
        if not (p.op == "create" and p.collection in allowed or
                p.op == "replace" and p.collection == "papers" and p.id == paper.id):
            errors.append(f"native overview import cannot {p.op} {p.collection}")
        if p.collection == "groups" and (p.body.get("argument_id") is not None or p.body.get("scope_id") is not None):
            errors.append("native overview groups have no canonical argument or scope")
        if p.collection == "application_details" and p.body.get("state") != "draft":
            errors.append("native overview application details remain draft")
    return errors


@contextmanager
def _native_import(db):
    from . import OVERVIEW_PROTOCOL_VERSION
    if (not db.write or db.write_scope != "overview" or db.max_revision() != 1
            or db.metadata.get("protocol_version") != OVERVIEW_PROTOCOL_VERSION
            or len(db.heads()) != 1 or native_import_active(db)):
        raise InvalidRequest("native overview import requires its fresh temporary overview store")
    db._native_overview_import = _NATIVE_IMPORT
    try:
        yield
    finally:
        del db._native_overview_import


def record_build_receipt(db, receipt):
    """Append one immutable canonical receipt within the caller's writer transaction."""
    if not db.write or not db.conn.in_transaction:
        raise InvalidRequest("overview receipt requires a caller-owned write transaction")
    current = db.check_compatibility()
    if current.get("generation") != db.metadata.get("generation"):
        raise InvalidRequest("database generation changed; reopen before recording the overview build")
    raw = canonical_bytes(receipt)
    key, value = "overview_build:" + sha256_bytes(raw), raw.decode("utf-8")
    existing = db.conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    if existing is not None:
        if existing[0] != value:
            raise InvalidRequest("an overview build receipt cannot replace different historical bytes")
        return key
    db.conn.execute("INSERT INTO metadata(key,value) VALUES (?,?)", (key, value))
    return key
