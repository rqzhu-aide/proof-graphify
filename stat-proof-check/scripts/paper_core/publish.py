"""Working and release publication (implementation-handoff 7.4): render, accept mechanically, record.

The renderer is a Node module bundled next to this package. Publication writes the page only after the
renderer's own receipt and an independent Python scan agree with the fixed projection; a failed build
retains any prior HTML at the destination and records a ``failed`` publication row.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from . import CORE_VERSION
from .canonical import compact_json, sha256_bytes
from .errors import InvalidRequest, PublicationError
from .ids import new_id
from .math_render import render_text
from .paths import resolve_path
from .staging import staging_directory
from .storage import Database, now_iso, paper_record

RENDERER = Path(__file__).resolve().parent / "renderer" / "render_projection.mjs"
RENDER_TIMEOUT = 120
FRAGMENT_FIELDS = ("label", "statement", "reason", "needed_form", "rationale", "conditions", "reasoning", "description",
                   "proof_idea", "regime", "uncertainty", "impact_reason")


def _review_color(assessment):
    """Display an already-derived policy, never reinterpret the logical state."""
    return {"severe": "red", "moderate": "orange", "minor": "yellow", "checked": "green"}.get(
        assessment.get("review_display", {}).get("status"), "gray")


def _node_executable() -> str:
    node = shutil.which("node")
    if node is None:
        raise PublicationError("Node.js is required to render reports but no `node` executable was found")
    return node


def display_fragments(projection: dict, diagnostics=None) -> dict:
    """Escaped prose plus MathML for the text fields the renderer replaces; keyed by pinned ref."""
    refs = {}
    seen = set()
    for entry in projection["records"]:
        ref, body = entry["ref"], entry["body"]
        key = f"{ref['collection']}:{ref['id']}:{ref['version']}"
        if key in seen:
            continue
        seen.add(key)
        fragments = {}

        def render(value, field):
            local = [] if diagnostics is not None else None
            markup = render_text(value, diagnostics=local)
            if local:
                diagnostics.extend({**row, "ref": dict(ref), "field": field,
                    "collection": ref["collection"], "record_id": ref["id"],
                    "record_version": ref["version"], "field_path": field} for row in local)
            return markup

        for field in FRAGMENT_FIELDS:
            value = body.get(field)
            path = field
            if field in ("statement", "needed_form") and isinstance(value, dict):
                value = value.get("text")
                path += ".text"
            if value is None:
                continue
            if field == "conditions":
                if isinstance(value, list) and all(isinstance(v, str) for v in value):
                    fragments["conditions_html"] = [render(v, f"conditions/{i}") for i, v in enumerate(value)]
                continue
            if isinstance(value, str):
                fragments[f"{field}_html"] = render(value, path)
        if fragments:
            refs[key] = fragments
    return refs


def summarize_math_diagnostics(entries) -> dict:
    """Count expression occurrences in saved fields, with bounded reading notes."""
    groups, classifications, reasons = {}, {}, {}
    for row in entries:
        kind, reason = row["kind"], row["reason"]
        classifications[kind] = classifications.get(kind, 0) + 1
        reasons[reason] = reasons.get(reason, 0) + 1
        group = groups.setdefault((kind, reason),
            {"kind": kind, "reason": reason, "count": 0, "samples": []})
        group["count"] += 1
        sample = {key: row[key] for key in ("ref", "field", "excerpt")}
        if len(group["samples"]) < 3 and sample not in group["samples"]:
            group["samples"].append(sample)
    visible = list(groups.values())[:5]
    messages = [f"{group['count']} expression{'s' if group['count'] != 1 else ''} "
                f"kept as literal LaTeX. {group['reason']}" for group in visible]
    return {"count": len(entries), "total": len(entries),
            "count_basis": "expression occurrences in saved record fields", "nonblocking": True,
            "by_classification": classifications, "by_reason": reasons,
            "groups": visible, "groups_truncated": len(groups) > 5,
            "messages": messages, "messages_truncated": len(groups) > 5}


def _display_metadata(projection: dict) -> dict:
    diagnostics = []
    fragments = display_fragments(projection, diagnostics)
    return {"refs": fragments, "math_diagnostics": diagnostics,
            "math_diagnostic_summary": summarize_math_diagnostics(diagnostics)}


def render_input(db: Database, projection: dict, *, release: bool, source_identity: str) -> dict:
    paper = paper_record(db)
    return {
        "render_input_version": 1,
        "title": paper.body["title"],
        "build": {
            "core_version": CORE_VERSION,
            "revision": projection["snapshot_revision"],
            "audit_id": projection["audit_id"],
            "built_at": now_iso(),
            "source_identity": source_identity,
            "kind": "release" if release else "working",
        },
        "projection": projection,
        "display": _display_metadata(projection),
    }


class _Scan(HTMLParser):
    """Collect the embedded projection and the identity-bearing markers of a rendered page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.script_id = None
        self.scripts = {}
        self.node_ids, self.edge_ids, self.index_items, self.index_connections = [], [], [], []
        self.index_hypotheses = []
        self.node_states, self.edge_states = {}, {}
        self.findings, self.limits, self.process = [], [], []
        self.external = []
        self.elements, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        element = {"tag": tag, "attrs": a, "text": [], "children": [],
                   "parent": self.stack[-1] if self.stack else None}
        self.elements.append(element)
        if self.stack:
            self.stack[-1]["children"].append(element)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(element)
        if tag == "script" and a.get("id") in ("proof-projection", "proof-render-input"):
            self.script_id = a["id"]
            self.scripts[self.script_id] = []
        if "data-node-id" in a:
            self.node_ids.append(a["data-node-id"])
            self.node_states[a["data-node-id"]] = a.get("data-node-state")
        if "data-edge-id" in a:
            self.edge_ids.append(a["data-edge-id"])
            self.edge_states[a["data-edge-id"]] = (a.get("data-edge-from"), a.get("data-edge-to"), a.get("data-edge-state"))
        if "data-proof-index-item" in a:
            self.index_items.append(a["data-proof-index-item"])
            self.node_states[a["data-proof-index-item"]] = a.get("data-node-state")
        if "data-proof-index-connection" in a:
            self.index_connections.append(a["data-proof-index-connection"])
            self.edge_states[a["data-proof-index-connection"]] = (a.get("data-edge-from"), a.get("data-edge-to"),
                                                                 a.get("data-edge-state"))
        if "data-proof-index-hypothesis" in a:
            self.index_hypotheses.append(a["data-proof-index-hypothesis"])
            self.edge_states[a["data-proof-index-hypothesis"]] = (a.get("data-edge-from"), a.get("data-edge-to"),
                                                                a.get("data-edge-state"))
        if "data-proof-finding" in a:
            self.findings.append(a["data-proof-finding"])
        if "data-proof-source-limit" in a:
            self.limits.append(a["data-proof-source-limit"])
        if "data-proof-process-complete" in a:
            self.process.append(a["data-proof-process-complete"])
        for name in ("src", "href"):
            value = a.get(name)
            if value and value.lower().startswith(("http://", "https://", "//")) and not (tag == "a" and name == "href"):
                self.external.append(value)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break
        if tag == "script":
            self.script_id = None

    def handle_data(self, data):
        for element in self.stack:
            element["text"].append(data)
        if self.script_id is not None:
            self.scripts[self.script_id].append(data)


def _multiset_equal(a, b) -> bool:
    return sorted(a) == sorted(b)


def _scientific_fields(projection):
    """Expected source values, independently selected from the saved scientific schema.

    Keys include the owning template, pinned source and leaf path. Derived source spans
    retain their exact offsets; a statement reference resolves only its pinned version.
    This is an acceptance expectation, not a second saved projection format.
    """
    fields = {
        "papers": ("scope", "exclusions"),
        "sources": ("media_type", "limitation"),
        "anchors": ("locator", "excerpt", "limitation"),
        "observations": ("result", "note"),
        "source_issues": ("category", "lifecycle", "description", "resolution"),
        "source_reviews": ("purpose", "decision", "rationale"),
        "items": ("kind", "label", "caption", "statement", "uncertainty", "origin", "proof_idea"),
        "parts": ("label", "statement", "origin"),
        "scopes": ("binders", "conditions"),
        "arguments": ("label", "origin", "lifecycle"),
        "groups": ("kind", "rationale"),
        "uses": ("type", "reason", "regime", "uncertainty", "needed_form", "substitutions"),
        "application_details": ("needed_form", "substitutions", "state"),
        "target_specs": ("statement", "state"),
        "overview_selections": ("scope", "unresolved"),
        "connection_refinements": ("state", "note"),
        "proof_boundaries": ("state",),
        "coverage": ("classification", "note"),
        "audits": ("mode",),
        "checks": ("kind", "state", "outcome", "reasoning", "conditions", "next_action", "extent", "omissions"),
        "findings": ("category", "severity", "lifecycle", "description", "impact_reason", "resolution"),
        "repairs": ("kind", "description", "added_conditions"),
        "qualifications": ("qualified", "limitations"),
        "responses": ("coverage_note", "exposure", "exposure_note", "state"),
        "reconciliations": ("decision", "rationale"),
        "reuse_decisions": ("decision", "rationale"),
        "identity_maps": ("note",),
    }
    records = {}
    latest = {}
    for row in projection["records"]:
        ref = row["ref"]
        pin = f"{ref['collection']}:{ref['id']}:{ref['version']}"
        records[pin] = row
        loose = (ref["collection"], ref["id"])
        if loose not in latest or latest[loose]["ref"]["version"] < ref["version"]:
            latest[loose] = row
    expected = {}

    def pin_of(ref):
        return f"{ref['collection']}:{ref['id']}:{ref['version']}"

    def add(owner, source, value, path, span=None):
        if value is None or value == "":
            return
        if isinstance(value, list):
            for index, entry in enumerate(value):
                add(owner, source, entry, path + (index,), span)
        elif isinstance(value, dict):
            if path and path[-1] in ("statement", "needed_form"):
                add(owner, source, value.get("text"), path + ("text",), span)
            else:
                for name, entry in value.items():
                    add(owner, source, entry, path + (name,), span)
        else:
            raw = str(value).lower() if isinstance(value, bool) else str(value)
            expected.setdefault((owner, source, path, span), []).append(raw)

    def passage(owner, anchor, start, end):
        if anchor is not None:
            excerpt = anchor["body"].get("excerpt", "")
            add(owner, pin_of(anchor["ref"]), excerpt[start:end], ("excerpt",), (start, end))

    for row in projection["records"]:
        ref, body = row["ref"], row["body"]
        owner, collection = pin_of(ref), ref["collection"]
        for field in fields.get(collection, ()):
            add(owner, owner, body.get(field), (field,))
        if collection == "target_specs" and body.get("statement_ref"):
            source = records.get(pin_of(body["statement_ref"]))
            if source:
                add(owner, pin_of(source["ref"]), source["body"].get("statement"), ("statement",))
        if collection == "coverage":
            passage(owner, latest.get(("anchors", body["anchor_id"])), body["start_offset"], body["end_offset"])
        if collection == "source_reviews":
            for span in body.get("proof_spans", ()):
                passage(owner, records.get(pin_of(span["anchor_ref"])), span["start_offset"], span["end_offset"])
        if collection == "reconciliations":
            for index, disposition in enumerate(body.get("response_dispositions", ())):
                add(owner, owner, disposition.get("rationale"), ("response_dispositions", index, "rationale"))
        if collection == "identity_maps":
            for index, entry in enumerate(body.get("entries", ())):
                add(owner, owner, entry.get("rationale"), ("entries", index, "rationale"))
        if collection == "audits":
            for index, exclusion in enumerate(body.get("exclusions", ())):
                for field in ("reason", "consequence"):
                    add(owner, owner, exclusion.get(field), ("exclusions", index, field))
    return expected


def _scientific_failures(scan, projection):
    """Verify selected evidence against canonical source values and usable destinations."""
    from collections import Counter
    failures, shown = [], Counter()
    expected = _scientific_fields(projection)
    templates = [e for e in scan.elements if "data-record-template" in e["attrs"]]
    record_keys = [f"{r['ref']['collection']}:{r['ref']['id']}:{r['ref']['version']}" for r in projection["records"]]
    if not _multiset_equal([e["attrs"]["data-record-template"] for e in templates], record_keys) \
            or any(e["tag"] != "template" for e in templates):
        failures.append("scientific evidence templates differ from the pinned record inventory")
    rendered = {}

    def descendants(element):
        for child in element["children"]:
            yield child
            yield from descendants(child)

    def math_signature(element):
        def tree(node):
            # Display-delimited mathematics becomes inline in a result label.
            # The outer display mode is presentation; the full mathematical tree remains exact.
            attrs = tuple(sorted((name, value) for name, value in node["attrs"].items()
                                 if not (node["tag"] == "math" and name == "display")))
            return (node["tag"], attrs,
                    "".join(node["text"]), tuple(tree(child) for child in node["children"]))
        return tuple(tree(child) for child in descendants(element) if child["tag"] == "math")

    for template in templates:
        bodies = [e for e in descendants(template) if "data-record-body" in e["attrs"]]
        if len(bodies) != 1 or bodies[0]["attrs"]["data-record-body"] != template["attrs"]["data-record-template"]:
            failures.append("scientific template body does not retain its pinned evidence identity")

    for element in scan.elements:
        attrs = element["attrs"]
        if "data-scientific-path" not in attrs:
            continue
        owner, current, hidden = None, element, False
        while current:
            if "data-record-template" in current["attrs"]:
                owner = current["attrs"]["data-record-template"]
                break
            current_attrs = current["attrs"]
            hidden = hidden or current["tag"] in ("template", "script", "style") \
                or "hidden" in current_attrs or current_attrs.get("aria-hidden") == "true" \
                or "display:none" in current_attrs.get("style", "").replace(" ", "").lower()
            current = current["parent"]
        if owner is None:
            failures.append("scientific evidence field is outside its pinned template")
            continue
        try:
            path = tuple(json.loads(attrs["data-scientific-path"]))
            span = (int(attrs["data-scientific-start"]), int(attrs["data-scientific-end"])) \
                if "data-scientific-start" in attrs or "data-scientific-end" in attrs else None
            key = (owner, attrs.get("data-scientific-ref", ""), path, span)
            raw = expected[key][0]
        except (KeyError, TypeError, ValueError):
            failures.append(f"scientific evidence field does not resolve to selected pinned content: {owner}")
            continue
        shown[key] += 1
        if raw not in rendered:
            fragment = _Scan()
            fragment.feed("<div>" + render_text(raw) + "</div>")
            rendered[raw] = ("".join(fragment.elements[0]["text"]).strip(), math_signature(fragment.elements[0]))
        text = "".join(element["text"]).strip()
        if hidden or text not in (raw.strip(), rendered[raw][0]) \
                or (math_signature(element) and math_signature(element) != rendered[raw][1]):
            failures.append(f"scientific evidence differs from its pinned text or mathematics: {key}")
    for key, values in expected.items():
        if shown[key] != len(values):
            failures.append(f"scientific evidence field missing or duplicated: {key}")
    details = {e["attrs"]["data-proof-detail"]: e for e in scan.elements if "data-proof-detail" in e["attrs"]}
    for detail_key, detail in projection["details"].items():
        actual = list(descendants(details[detail_key])) if detail_key in details else []
        sections = [e for e in actual if "data-proof-section" in e["attrs"]]
        if [e["attrs"]["data-proof-section"] for e in sections] != [s["key"] for s in detail["sections"]]:
            failures.append(f"scientific evidence sections differ from the saved detail: {detail_key}")
            continue
        for element, section in zip(sections, detail["sections"]):
            refs = [e["attrs"]["data-record-ref"] for e in descendants(element) if "data-record-ref" in e["attrs"]]
            pins = [f"{r['collection']}:{r['id']}:{r['version']}" for r in section["record_refs"]]
            if refs != pins:
                failures.append(f"scientific evidence destinations differ from their pinned section: {section['key']}")
    return failures


def _saved_limitations(projection):
    """Translate only known generated diagnostics; authored or mixed notes remain exact."""
    import re
    records, latest = {}, {}
    for row in projection["records"]:
        ref = row["ref"]
        records[(ref["collection"], ref["id"], ref["version"])] = row
        loose = (ref["collection"], ref["id"])
        if loose not in latest or latest[loose]["ref"]["version"] < ref["version"]:
            latest[loose] = row

    def label(ref):
        row = records.get((ref["collection"], ref["id"], ref["version"])) if "version" in ref else \
            latest.get((ref["collection"], ref["id"]))
        if row is None:
            return "Referenced material unavailable"
        body = row["body"]
        if body.get("label"):
            return body["label"]
        if ref["collection"] == "anchors":
            source = {"collection": "sources", "id": body["source_id"], "version": body["source_version"]}
            parts, locator = [label(source)], body["locator"]
            if locator.get("label"):
                parts.append(locator["label"])
            if locator.get("page") is not None:
                parts.append(f"page {locator['page']}")
            if locator.get("start_line") is not None:
                parts.append(f"lines {locator['start_line']} to {locator['end_line']}" if
                             locator.get("end_line") not in (None, locator["start_line"]) else f"line {locator['start_line']}")
            return ", ".join(parts)
        return body.get("path") or body.get("title") or "Saved scientific material"

    refs = [row["ref"] for row in projection["records"]] + projection["summary"]["scope"]["target_refs"]
    translations = {}
    for ref in refs:
        key, name = f"{ref['collection']}:{ref['id']}", label(ref)
        translations[f"register establishment for {key}: no exact registered proof route or local group"] = \
            name + ": no exact establishing argument is registered."
        translations[f"audit target {key} is an intermediate result"] = \
            name + ": the saved examination scope identifies a subsidiary result."
        translations[f"required target {key} is not live at revision {projection['snapshot_revision']}"] = \
            name + ": the required statement is unavailable in the current saved material."
        if ref["collection"] == "arguments":
            for message in (f"proof boundary for {key} remains unresolved",
                            f"proof boundary for {ref['id']}: complete current source-boundary review required"):
                translations[message] = name + ": the examined boundary of the written proof remains unresolved."
            translations[f"located proof passage for {key} changed"] = \
                name + ": a located proof passage changed, so its earlier examination is not current."
            translations[f"written proof for {key} has no located source passages"] = \
                name + ": the written proof has no located source passages."
            for anchor in (row for row in projection["records"] if row["ref"]["collection"] == "anchors"):
                translations[f"written proof for {key} has unavailable source passage {anchor['ref']['id']}"] = \
                    name + ": the source passage " + label(anchor["ref"]) + " is unavailable."
    expected = []
    for note in projection["summary"].get("limitations", []):
        replacement = translations.get(note)
        if replacement is None:
            for ref in refs:
                for anchor in (row for row in projection["records"] if row["ref"]["collection"] == "anchors"):
                    prefix = f"proof coverage for {ref['collection']}:{ref['id']}, anchor {anchor['ref']['id']}: uncovered or unchecked spans "
                    if note.startswith(prefix) and re.fullmatch(r"\[\d+, \d+\)(?:, \[\d+, \d+\))*", note[len(prefix):]):
                        replacement = label(ref) + ": " + label(anchor["ref"]) + \
                            " contains proof material without a completed current substantive examination."
                        break
                if replacement is not None:
                    break
        expected.append(note if replacement is None else replacement)
    return expected


def _visible_failures(scan, projection, *, build=None):
    """Check actual visible classes/text as well as identity metadata."""
    failures = []
    glyphs = {"green": "✓", "red": "✕", "gray": "?", "orange": "!", "yellow": "i"}
    display_colors = {"checked": "green", "severe": "red", "moderate": "orange", "minor": "yellow"}
    display_labels = {"checked": "Checked", "severe": "Severe", "moderate": "Moderate", "minor": "Minor",
                      "unrated": "Severity not rated", "unresolved": "Unable to assess", "unassessed": "Not assessed",
                      "dependency": "Depends on unresolved result", "historical": "Saved assessment, not rated"}
    def display_status(assessment):
        return assessment.get("review_display", {}).get("status", "historical")
    def display_state(assessment):
        return display_colors.get(display_status(assessment), "gray")
    def display_label(assessment):
        if display_status(assessment) == "unassessed" and assessment.get("label") == "examined in proof":
            return "Examined in proof"
        return display_labels[display_status(assessment)]
    text = lambda element: "".join(element["text"]).strip() if element else ""
    classes = lambda element: element["attrs"].get("class", "").split() if element else []

    def visible(element, *, allow_disclosure=False):
        while element:
            attrs = element["attrs"]
            if element["tag"] in ("template", "script", "style") or "hidden" in attrs \
                    or attrs.get("aria-hidden") == "true" \
                    or (element["tag"] == "details" and "open" not in attrs and not allow_disclosure) \
                    or "display:none" in attrs.get("style", "").replace(" ", "").lower():
                return False
            element = element["parent"]
        return True

    def descendants(element):
        for child in element["children"]:
            yield child
            yield from descendants(child)

    def visible_text(element, value, *, allow_disclosure=False):
        return element is not None and value in text(element) and visible(element, allow_disclosure=allow_disclosure) \
            and all(visible(child, allow_disclosure=allow_disclosure) for child in descendants(element))

    def field(element, name):
        return next((child for child in descendants(element) if name in classes(child)), None) if element else None

    def assessment_matches(element, expected):
        return element is not None and f"s-{display_state(expected)}" in classes(element) \
            and element["attrs"].get("data-review-status") == display_status(expected) \
            and text(field(element, "proof-state-badge")) == glyphs[display_state(expected)] + display_label(expected) \
            and text(field(element, "proof-assessment-label")) == expected["label"] \
            and text(field(element, "proof-assessment-text")) == expected["explanation"] \
            and text(field(element, "proof-state-glyph")) == glyphs[display_state(expected)] \
            and (not expected.get("availability") or text(field(element, "proof-availability"))
                 == f"Exact target support: {expected['availability']}")

    by_detail = {e["attrs"]["data-proof-detail"]: e for e in scan.elements if "data-proof-detail" in e["attrs"]}
    for kind, entries in (("node", projection["nodes"]), ("connection", projection["connections"])):
        for entry in entries:
            detail = by_detail.get(entry["detail_key"])
            owners = [child for child in descendants(detail)
                      if child["attrs"].get(f"data-proof-owner-{kind}") == entry["id"]] if detail else []
            block = field(owners[0], "proof-assessment") if len(owners) == 1 else None
            if not assessment_matches(block, entry["assessment"]):
                failures.append(f"visible assessment for {entry['id']} disagrees with its canonical state, glyph, label or support")
    for key, detail in projection["details"].items():
        reader = detail.get("reader")
        if not reader or key not in by_detail:
            continue
        expected = [(f"target:{i}", row["assessment"]) for i, row in enumerate(reader["targets"])] + \
                   [(f"application:{i}", row["assessment"]) for i, row in enumerate(reader["applications"])]
        for context, assessment in expected:
            occurrences = [element for element in descendants(by_detail[key])
                           if element["attrs"].get("data-reader-detail") == key
                           and element["attrs"].get("data-reader-assessment") == context]
            block = field(occurrences[0], "proof-assessment") if len(occurrences) == 1 else None
            if not assessment_matches(block, assessment) \
                    or text(field(block, "proof-review")) != "Independent review: " + assessment["independent_review"].replace("_", " ") \
                    or (assessment.get("local_label") and text(field(block, "proof-local-outcome")) !=
                        "Recorded local work: " + assessment["local_label"]):
                failures.append(f"reader assessment differs from its target or application: {key}/{context}")
    nodes = {entry["id"]: entry for entry in projection["nodes"]}
    connections = {entry["id"]: entry for entry in projection["connections"]}
    hypotheses = {entry["id"]: entry for entry in projection.get("hypothesis_connections", [])}
    applications = {app["use_id"]: app for edge in projection["connections"] for app in edge.get("applications", ())}
    for element in scan.elements:
        attrs = element["attrs"]
        if "data-proof-finding" in attrs:
            identity = attrs["data-proof-finding"]
            cards = [child for child in descendants(element)
                     if child["attrs"].get("data-issue-ref") == identity]
            if len(cards) != 1 or not visible(cards[0], allow_disclosure=True):
                failures.append(f"summary issue card {identity} is missing, duplicated or hidden")
        if "data-issue-ref" in attrs:
            saved = projection.get("finding_displays", {}).get(attrs["data-issue-ref"], {})
            expected = {"review_display": saved} if saved else {}
            status, color = display_status(expected), display_state(expected)
            if attrs.get("data-review-status") != status or f"s-{color}" not in classes(element) \
                    or text(field(element, "proof-state-badge")) != glyphs[color] + display_labels[status]:
                failures.append(f"issue card {attrs['data-issue-ref']} has altered severity or status")
        if "data-node-id" in attrs and (node := nodes.get(attrs["data-node-id"])):
            state = display_state(node["assessment"])
            if f"s-{state}" not in classes(element) or text(field(element, "proof-node-label")) != node["label"] \
                    or text(field(element, "proof-node-state")) != glyphs[state]:
                failures.append(f"visible node {node['id']} has altered color, label or glyph")
        if "data-edge-id" in attrs and (edge := connections.get(attrs["data-edge-id"])):
            state = display_state(edge["assessment"])
            if f"s-{state}" not in classes(element) or attrs.get("marker-end") != f"url(#proof-arrow-{state})":
                failures.append(f"visible connection {edge['id']} has an altered color")
        hypothesis_id = attrs.get("data-edge-id") or attrs.get("data-proof-index-hypothesis")
        if hypothesis_id in hypotheses:
            hypothesis = hypotheses[hypothesis_id]
            members = [element, *descendants(element)]
            if "proof-hypothesis" not in classes(element) or any(
                    any(name.startswith("s-") or name in ("proof-assessment", "proof-state-badge", "proof-state-glyph")
                        for name in classes(member))
                    or any(name.startswith("data-review-") or name in ("data-severity", "data-edge-severity", "data-assessment")
                           for name in member["attrs"]) for member in members):
                failures.append(f"hypothesis {hypothesis_id} has an assessment or severity display")
            if "data-edge-id" in attrs:
                if element["tag"] != "path" or "proof-edge" not in classes(element) \
                        or attrs.get("marker-end") != "url(#proof-hypothesis-arrow)" \
                        or attrs.get("data-detail-key") != hypothesis["detail_key"]:
                    failures.append(f"hypothesis {hypothesis_id} has an altered path or destination")
            elif not any(member["attrs"].get("data-detail-key") == hypothesis["detail_key"] for member in members):
                failures.append(f"index hypothesis {hypothesis_id} has an altered destination")
            if attrs.get("data-edge-kind") != hypothesis["kind"]:
                failures.append(f"hypothesis {hypothesis_id} shows an altered relation kind")
        if "data-application-id" in attrs:
            app = applications.get(attrs["data-application-id"])
            if app is None or not assessment_matches(field(element, "proof-assessment"), app["assessment"]):
                failures.append(f"visible application {attrs['data-application-id']} has an altered assessment")
    def pin(ref):
        return f"{ref['collection']}:{ref['id']}:{ref['version']}"

    records_by_pin = {pin(row["ref"]) for row in projection["records"]}
    expected_contexts = []
    for identity, hypothesis in hypotheses.items():
        source, target = nodes.get(hypothesis["from"]), nodes.get(hypothesis["to"])
        proof = connections.get(hypothesis.get("proof_connection_id"))
        expected_detail = target["detail_key"] if target else None
        if source is None or target is None or hypothesis["from"] == hypothesis["to"] \
                or hypothesis["premise_ref"] != source["item_ref"] \
                or hypothesis["target_ref"] != target["item_ref"] \
                or hypothesis["detail_key"] != expected_detail or expected_detail not in by_detail \
                or hypothesis["kind"] not in ("hypothesis", "setup") or "assessment" in hypothesis \
                or (hypothesis.get("proof_connection_id") is not None and
                    (proof is None or (proof["from"], proof["to"]) != (hypothesis["from"], hypothesis["to"]))):
            failures.append(f"hypothesis {identity} has invalid endpoints or destinations")
        expected_attrs = {
            "data-hypothesis-context": identity,
            "data-hypothesis-premise": pin(hypothesis["premise_ref"]),
            "data-hypothesis-target": pin(hypothesis["target_ref"]),
            "data-hypothesis-spec": pin(hypothesis["spec_ref"]),
            "data-hypothesis-statement": pin(hypothesis["statement_ref"]),
            "data-hypothesis-proof-connection": hypothesis.get("proof_connection_id") or "",
        }
        scope_pins = [pin(ref) for ref in hypothesis["scope_refs"]]
        if any(value not in records_by_pin for key, value in expected_attrs.items()
               if key not in ("data-hypothesis-context", "data-hypothesis-proof-connection")) \
                or any(value not in records_by_pin for value in scope_pins):
            failures.append(f"hypothesis {identity} does not resolve to pinned source records")
        detail_keys = {hypothesis["detail_key"]}
        if proof:
            detail_keys.add(proof["detail_key"])
        for detail_key in sorted(detail_keys):
            expected_contexts.append((identity, detail_key))
            detail = by_detail.get(detail_key)
            contexts = [member for member in descendants(detail)
                        if member["attrs"].get("data-hypothesis-context") == identity] if detail else []
            actual = contexts[0]["attrs"] if len(contexts) == 1 else {}
            try:
                actual_scopes = json.loads(actual.get("data-hypothesis-scopes", "null"))
            except (ValueError, TypeError):
                actual_scopes = None
            if any(actual.get(key) != value for key, value in expected_attrs.items()) or actual_scopes != scope_pins:
                failures.append(f"hypothesis {identity} lost its pinned context in {detail_key}")
            context = contexts[0] if len(contexts) == 1 else None
            links = [member for member in descendants(context)
                     if member["tag"] == "a" and "data-jump-record" in member["attrs"]] if context else []
            expected_links = [pin(hypothesis["premise_ref"]), pin(hypothesis["target_ref"]), *scope_pins]
            if not context or not visible(context, allow_disclosure=True) \
                    or [link["attrs"]["data-jump-record"] for link in links] != expected_links \
                    or any(not text(link) or not visible(link, allow_disclosure=True) for link in links):
                failures.append(f"hypothesis {identity} lost its visible context links in {detail_key}")
    actual_contexts = []
    for element in scan.elements:
        if "data-hypothesis-context" not in element["attrs"]:
            continue
        current = element["parent"]
        while current and "data-proof-detail" not in current["attrs"]:
            current = current["parent"]
        actual_contexts.append((element["attrs"]["data-hypothesis-context"],
                                current["attrs"]["data-proof-detail"] if current else ""))
    if sorted(actual_contexts) != sorted(expected_contexts):
        failures.append("hypothesis context destinations differ from the saved relations")
    scope = projection["summary"]["scope"]
    mode = [e for e in scan.elements if "data-proof-scope-mode" in e["attrs"]]
    targets = [e for e in scan.elements if "data-proof-scope-targets" in e["attrs"]]
    records = {}
    for row in projection["records"]:
        ref = row["ref"]
        key = (ref["collection"], ref["id"])
        if key not in records or records[key]["ref"]["version"] < ref["version"]:
            records[key] = row
    expected_labels = [records.get((r["collection"], r["id"]), {}).get("body", {}).get("label")
                       or r["collection"].replace("_", " ").removesuffix("s") for r in scope["target_refs"]]
    expected_targets = ", ".join(expected_labels) or (
        "Recorded items; no audit selected" if projection["audit_id"] is None else "No explicit audit targets recorded")
    target_rows = [e for e in descendants(targets[0]) if "data-proof-scope-target" in e["attrs"]] if len(targets) == 1 else []
    target_ids = [e["attrs"]["data-proof-scope-target"] for e in target_rows]
    expected_ids = [f"{r['collection']}:{r['id']}" for r in scope["target_refs"]]
    if len(mode) != 1 or text(mode[0]) != scope["mode"] or len(targets) != 1 or text(targets[0]) != expected_targets \
            or target_ids != expected_ids or [text(e) for e in target_rows] != expected_labels:
        failures.append("visible audit scope differs from the canonical scope")
    factual = projection["summary"].get("factual")
    if factual is not None:
        support, review = factual["statement_support"], factual["independent_review"]
        outcomes = [outcome for outcome in ("supported", "gap", "refuted", "inconclusive")
                    if factual["work"]["current_primary_outcomes"][outcome]]
        expected = {
            "primary_outcomes": ("Current initial assessment outcomes: " + ", ".join(outcomes) + "." if outcomes else
                                 "No completed current initial mathematical outcome is recorded.") +
                                " Completion of the examination does not establish that every statement is supported.",
            "statement_support": "Read each result and application for its exact support conditions.",
            "independent_review": review.get("explanation", "Independent review: " + review["state"].replace("_", " ") + "."),
            **({"scope_explanation": factual["scope"]["explanation"]} if factual["scope"].get("explanation") else {}),
            **{f"unresolved.{index}": f"{row['label']}: {row['availability']}" +
               (f" (declared {row['kind']}; scope-dependent premise)" if row.get("kind") in ("assumption", "definition") else "")
               for index, row in enumerate(support["unresolved"])},
            **{f"source_limits.{index}": f"{row.get('source_path') or row['label']}: {row['description']}"
               for index, row in enumerate(factual["source_limits"])},
            **{f"external.{index}": f"{row['label']}: {row['availability']}"
               for index, row in enumerate(factual["unresolved_external_sources"])},
            **{f"qualification.{index}": note for index, note in enumerate(review["qualification_limitations"])},
            **{f"exclusion.{index}": f"{row['label']}: {row['reason']} Consequence: {row['consequence']}"
               for index, row in enumerate(factual["scope"]["exclusions"])},
        }
        shown = [(e["attrs"]["data-proof-fact"], text(e)) for e in scan.elements if "data-proof-fact" in e["attrs"]]
        if sorted(shown) != sorted(expected.items()):
            failures.append("visible scientific summary differs from the assessed snapshot facts")
    reports = [e for e in scan.elements if "data-reader-report-state" in e["attrs"]]
    report = reports[0] if len(reports) == 1 else None
    completion_text = ("Registered examinations complete." if projection["summary"]["progress"]["process_complete"]
                       else "Registered examinations incomplete.")
    report_paragraphs = [e for e in report["children"] if e["tag"] == "p"] if report is not None else []
    process_rows = [e for e in scan.elements if "data-proof-process-complete" in e["attrs"]]
    process = process_rows[0] if len(process_rows) == 1 else None
    if not any(visible_text(paragraph, completion_text) for paragraph in report_paragraphs):
        failures.append("current examination state is missing, hidden or inconsistent")
    if not visible_text(process, completion_text, allow_disclosure=True):
        failures.append("summary examination state is missing, hidden or inconsistent")
    if build is not None and build.get("kind") == "working":
        working_limit = "This working report does not establish completion of the promised audit scope."
        if not any(visible_text(paragraph, working_limit) for paragraph in report_paragraphs):
            failures.append("working report promised-scope limitation is missing, hidden or inconsistent")
        if not visible_text(process, working_limit, allow_disclosure=True):
            failures.append("working summary promised-scope limitation is missing, hidden or inconsistent")
    if report is not None and factual is not None:
        required_limits = [review.get("explanation", "Independent review: " + review["state"].replace("_", " ") + "."),
                           *review["qualification_limitations"],
                           *(f"{row.get('source_path') or row['label']}: {row['description']}" for row in factual["source_limits"])]
        if any(value not in text(report) for value in required_limits):
            failures.append("independent review or source limitations are absent from the visible report state")
    work = {task["id"]: task for task in (projection.get("worklist") or {}).get("tasks", [])
            if task["required"] and task["state"] != "satisfied"}
    rows = [e for e in scan.elements if "data-proof-review-limit" in e["attrs"]]
    if not _multiset_equal([e["attrs"]["data-proof-review-limit"] for e in rows], list(work)):
        failures.append("current examination limitations differ from the saved required material")
    for row in rows:
        task = work.get(row["attrs"]["data-proof-review-limit"])
        if task is None:
            continue
        role = {"independent": "Independent assessment", "coordinator": "Combined assessment"}.get(task["role"], "Initial assessment")
        if task.get("outcome"):
            consequence = role + ": " + task["outcome"] + ". Examination remains incomplete for the current material." \
                if task["freshness"] == "current" else "Earlier " + role.lower() + ": " + task["outcome"] + \
                ". It does not establish a completed current examination."
        elif task["kind"] in ("derivation", "application", "composition", "case_coverage", "scope_discharge", "external_source"):
            consequence = "No completed current " + role.lower() + " is recorded for this material."
        elif task["kind"] == "source_fidelity" and task["target"]["collection"] in ("items", "parts"):
            consequence = "Source comparison is incomplete for this statement."
        elif task["kind"] == "reconciliation":
            consequence = "The recorded assessments have not been fully reconciled."
        else:
            consequence = "A review requirement remains unresolved; this record alone does not identify unexamined mathematics."
        if task.get("dependency_support") and task["dependency_support"] != "available":
            consequence += " Premise support: " + task["dependency_support"] + "."
        target = f"{task['target']['collection']}:{task['target']['id']}"
        if row["attrs"].get("data-proof-review-kind") != task["kind"] \
                or row["attrs"].get("data-proof-review-target") != target or not visible(row) \
                or not text(row).endswith(": " + consequence):
            failures.append(f"current examination limitation lost its saved consequence: {task['id']}")
    notes = [e for e in scan.elements if "data-proof-limitation" in e["attrs"]]
    expected_notes = _saved_limitations(projection)
    if [(e["attrs"].get("data-proof-limitation-index"), text(e)) for e in notes] != \
            [(str(index), note) for index, note in enumerate(expected_notes)] or any(not visible(e) for e in notes):
        failures.append("saved scientific or mixed review limitations were omitted, changed or hidden")
    return failures


def _reader_fields(projection):
    """Required authored fields in each reader context, resolved only from pinned records."""
    records = {(r["ref"]["collection"], r["ref"]["id"], r["ref"]["version"]): r["body"]
               for r in projection["records"]}
    expected = {}

    def add(detail, context, ref, *fields):
        if not ref:
            return
        pin = (ref["collection"], ref["id"], ref["version"])
        body = records[pin]

        def leaves(value, path):
            if value is None or value == "":
                return
            if isinstance(value, list):
                for i, entry in enumerate(value):
                    leaves(entry, f"{path}.{i}")
            elif isinstance(value, dict):
                if path in ("statement", "needed_form"):
                    leaves(value.get("text"), f"{path}.text")
                else:
                    for name, entry in value.items():
                        leaves(entry, f"{path}.{name}")
            else:
                expected[(detail, context, ":".join(map(str, pin)), path)] = str(value)

        for field in fields:
            leaves(body.get(field), field)

    def scopes(detail, context, chain):
        for i, entry in enumerate(chain):
            at = f"{context}:scope:{i}"
            add(detail, at, entry["scope_ref"], "conditions", "binders")
            for j, ref in enumerate(entry["assumption_refs"]):
                add(detail, f"{at}:assumption:{j}", ref, "label", "statement")

    def group_fields(detail, context, group):
        add(detail, context, group["group_ref"], "kind", "rationale")
        scopes(detail, context, group["scope_chain"])
        for i, case in enumerate(group["case_scopes"]):
            scopes(detail, f"{context}:case:{i}", case["scope_chain"])

    for key, detail in projection["details"].items():
        reader = detail.get("reader")
        if reader is None:
            continue
        for node in projection["nodes"]:
            if node["detail_key"] == key and node["item_ref"] != reader["item_ref"]:
                add(key, "legacy", node["item_ref"], "statement")
        add(key, "strategy", reader.get("strategy_ref"), "proof_idea")
        for i, target in enumerate(reader["targets"]):
            at = f"target:{i}"
            add(key, at, target["target_ref"], "label")
            add(key, at, target["statement_ref"], "statement")
            target_body = records[tuple(target["target_ref"][field] for field in ("collection", "id", "version"))]
            statement_body = records[tuple(target["statement_ref"][field] for field in ("collection", "id", "version"))]
            if target_body["statement"] != statement_body["statement"]:
                add(key, at + ":synopsis", target["target_ref"], "statement")
            scopes(key, at, target["scope_chain"])
        for i, argument in enumerate(reader["arguments"]):
            at = f"argument:{i}"
            add(key, at, argument["argument_ref"], "label", "origin", "lifecycle")
            scopes(key, at, argument["scope_chain"])
            for j, group in enumerate(argument["groups"]):
                group_fields(key, f"{at}:group:{j}", group)
        for i, group in enumerate(reader.get("provenance_groups", [])):
            group_fields(key, f"provenance_group:{i}", group)
        for i, application in enumerate(reader["applications"]):
            at = f"application:{i}"
            add(key, at, application["use_ref"], "reason", "regime", "uncertainty")
            add(key, at, application.get("application_ref"), "needed_form", "state")
            add(key, at + ":from", application["from_ref"], "label")
            add(key, at + ":to", application["to_ref"], "label")
            scopes(key, at, application["scope_chain"])
        for i, ref in enumerate(reader["finding_refs"]):
            add(key, f"finding:{i}", ref, "category", "description", "impact_reason", "resolution")
        for i, ref in enumerate(reader["source_limit_refs"]):
            add(key, f"source_limit:{i}", ref, "category", "description", "limitation")
    latest = {}
    for row in projection["records"]:
        ref = row["ref"]
        key = (ref["collection"], ref["id"])
        if key not in latest or ref["version"] > latest[key]["version"]:
            latest[key] = ref
    for connection in projection["connections"]:
        identities = list(dict.fromkeys(connection["primary_use_ids"] +
                          [row["use_id"] for row in connection.get("applications", [])]))
        for i, identity in enumerate(identities):
            ref = latest.get(("uses", identity))
            if not ref:
                continue
            key = connection["detail_key"]
            shared = sum(entry["detail_key"] == key for entry in projection["nodes"] + projection["connections"]) > 1
            at = (f"connection:{connection['id']}:" if shared else "") + f"application:{i}"
            add(key, at, ref, "reason", "regime", "uncertainty")
            body = records[(ref["collection"], ref["id"], ref["version"])]
            for direction in ("from", "to"):
                target = body[direction]
                add(key, at + ":" + direction, latest.get((target["collection"], target["id"])), "label")
            application_ref = latest.get(("application_details", identity))
            if application_ref is None and (body.get("group_id") or body.get("needed_form")):
                application_ref = ref  # Historical format-3 applications stored these fields on the use.
            add(key, at, application_ref, "needed_form", "state")
    return expected


def _reader_failures(scan, projection):
    """Validate the actual reader occurrences, not matching text in hidden evidence templates."""
    from collections import Counter
    failures = []
    expected = _reader_fields(projection)
    shown = Counter()
    records = {f"{r['ref']['collection']}:{r['ref']['id']}:{r['ref']['version']}": r["body"]
               for r in projection["records"]}
    overview_keys = [e["attrs"]["data-reader-overview"] for e in scan.elements
                     if "data-reader-overview" in e["attrs"]
                     and "proof-reader-overview" in e["attrs"].get("class", "").split()]
    reader_keys = [key for key, detail in projection["details"].items() if detail.get("reader") is not None]
    # Older projections are readable without pretending that structured context was available.
    if any(overview_keys.count(key) != 1 for key in reader_keys):
        failures.append("reader overview is missing or duplicated")
    rendered_text = {}

    def inside_overview(element, detail):
        current, found = element, False
        while current:
            attrs = current["attrs"]
            if current["tag"] == "template" or "hidden" in attrs or attrs.get("aria-hidden") == "true" \
                    or "display:none" in attrs.get("style", "").replace(" ", "").lower():
                return False
            if attrs.get("data-reader-overview") == detail:
                found = True
            current = current["parent"]
        return found

    def ancestors(element):
        current = element["parent"]
        while current:
            yield current
            current = current["parent"]

    def pin(ref):
        return f"{ref['collection']}:{ref['id']}:{ref['version']}" if ref else ""

    def summary_context(element, key):
        try:
            kind, index = key[1].split(":")
            if kind == "finding":
                identity = projection["summary"]["findings"]["refs"][int(index)]
                collection, marker, fields = "findings", "data-proof-finding", ("category", "description", "impact_reason", "resolution")
            elif kind == "source_limit":
                identity = projection["summary"]["source_limits"][int(index)]
                collection, marker, fields = "source_issues", "data-proof-source-limit", ("description",)
            else:
                return False
            version = max(row["ref"]["version"] for row in projection["records"]
                          if row["ref"]["collection"] == collection and row["ref"]["id"] == identity)
            if key[2] != f"{collection}:{identity}:{version}" or key[3] not in fields:
                return False
        except (IndexError, ValueError):
            return False
        current, row_found, summary_found = element, False, False
        while current:
            attrs = current["attrs"]
            if current["tag"] == "template" or "hidden" in attrs or attrs.get("aria-hidden") == "true" \
                    or "display:none" in attrs.get("style", "").replace(" ", "").lower():
                return False
            row_found = row_found or attrs.get(marker) == identity
            summary_found = summary_found or attrs.get("id") == "proof-summary"
            current = current["parent"]
        return row_found and summary_found

    for detail_key in reader_keys:
        reader = projection["details"][detail_key]["reader"]
        overview = next((e for e in scan.elements if e["attrs"].get("data-reader-overview") == detail_key
                         and "proof-reader-overview" in e["attrs"].get("class", "").split()), None)
        if overview is None:
            continue
        owner_id = (overview["parent"] or {}).get("attrs", {}).get("data-proof-owner-node")
        owner = next((node for node in projection["nodes"] if node["id"] == owner_id), None)
        if owner is None or owner["detail_key"] != detail_key or owner["item_ref"] != reader["item_ref"]:
            failures.append(f"reader overview is placed under a different owner: {detail_key}")
        # Check contextual rows independently from field text: carrying correct text to the
        # wrong supplier or target row must not pass just because its marker moved with it.
        rows, pending = [], [overview]
        while pending:
            row = pending.pop()
            rows.append(row)
            pending.extend(row["children"])
        for i, target in enumerate(reader["targets"]):
            matches = [e for e in rows if e["attrs"].get("data-reader-target") == str(i)]
            if len(matches) != 1 or matches[0]["attrs"].get("data-reader-exact-state") != target["exact_state"] \
                    or any(matches[0]["attrs"].get("data-reader-" + name + "-ref") != pin(target[name + "_ref"])
                           for name in ("target", "statement", "spec")):
                failures.append(f"reader exact-target state or context differs: {detail_key}/{i}")
        for i, app in enumerate(reader["applications"]):
            matches = [e for e in rows if e["attrs"].get("data-reader-application") == str(i)]
            if len(matches) != 1 or any(matches[0]["attrs"].get("data-reader-" + field) != pin(app[field + "_ref"])
                                       for field in ("from", "to", "group", "argument")):
                failures.append(f"reader supplier application context differs: {detail_key}/{i}")

    for element in scan.elements:
        attrs = element["attrs"]
        if "data-reader-field" not in attrs:
            continue
        key = tuple(attrs.get(name, "") for name in
                    ("data-reader-detail", "data-reader-context", "data-reader-ref", "data-reader-field"))
        shown[key] += 1
        body = records.get(key[2])
        try:
            value = body
            for name in key[3].split("."):
                value = value[int(name)] if isinstance(value, list) else value[name]
            raw = str(value)
        except (KeyError, IndexError, TypeError, ValueError):
            failures.append(f"reader field does not resolve to its pinned source: {key}")
            continue
        if raw not in rendered_text:
            fragment_scan = _Scan()
            fragment_scan.feed("<div>" + render_text(raw) + "</div>")
            rendered_text[raw] = "".join(fragment_scan.elements[0]["text"]).strip()
        text = "".join(element["text"]).strip()
        correct_context = summary_context(element, key) if key[0] == "summary" else inside_overview(element, key[0])
        if text not in (raw.strip(), rendered_text[raw]) or not correct_context:
            failures.append(f"reader field differs from its visible pinned source: {key}")
        if key[0] in reader_keys and key[1].startswith("application:"):
            row = next((e for e in ancestors(element) if "data-reader-application" in e["attrs"]), None)
            if row is None or row["attrs"]["data-reader-application"] != key[1].split(":")[1]:
                failures.append(f"reader field is placed under a different application: {key}")
        context_parts = key[1].split(":")
        if key[0] in reader_keys and context_parts[0] == "target" and key[3] in ("statement.text", "label") \
                and (len(context_parts) == 2 or context_parts[2:] == ["synopsis"]):
            target_row, disclosed = None, False
            for parent in ancestors(element):
                if "data-reader-target" in parent["attrs"]:
                    target_row = parent
                    break
                disclosed = disclosed or parent["tag"] == "details"
            if target_row is None or target_row["attrs"]["data-reader-target"] != context_parts[1] \
                    or disclosed != (len(context_parts) == 3):
                failures.append(f"reader exact statement and saved synopsis placement differs: {key}")
        if key[0] in reader_keys and key not in expected:
            failures.append(f"unexpected reader field or context: {key}")
    for key in expected:
        optional_administration = key[3] in ("lifecycle", "state")
        if shown[key] != 1 and not (optional_administration and shown[key] == 0):
            failures.append(f"reader field missing or duplicated in its context: {key}")

    explanations = {}
    for detail_key, detail in projection["details"].items():
        for field, prefix in (("targets", "target"), ("applications", "application")):
            for index, row in enumerate((detail.get("reader") or {}).get(field, [])):
                if row.get("support_explanation"):
                    explanations[detail_key, f"{prefix}:{index}"] = row["support_explanation"]
    for connection in projection["connections"]:
        applications = {row["use_id"]: row for row in connection.get("applications", [])}
        identities = list(dict.fromkeys(connection["primary_use_ids"] + list(applications)))
        for index, identity in enumerate(identities):
            if explanation := applications.get(identity, {}).get("support_explanation"):
                key = connection["detail_key"]
                shared = sum(entry["detail_key"] == key for entry in projection["nodes"] + projection["connections"]) > 1
                context = (f"connection:{connection['id']}:" if shared else "") + f"application:{index}"
                explanations[key, context] = explanation
    shown_explanations = Counter()

    def support_visible(element, key):
        if not inside_overview(element, key[0]):
            return False
        for parent in ancestors(element):
            # Internal, historical and summary applications may be disclosed as a
            # whole. Their support notice must remain visible within that row.
            if key[1].startswith("application:") and "data-reader-application" in parent["attrs"]:
                return parent["attrs"]["data-reader-application"] == key[1].split(":")[1]
            if parent["tag"] == "details" and "open" not in parent["attrs"]:
                return False
        return True

    for element in scan.elements:
        attrs = element["attrs"]
        if "data-reader-support" not in attrs:
            continue
        key = attrs.get("data-reader-detail"), attrs["data-reader-support"]
        shown_explanations[key] += 1
        explanation = explanations.get(key)
        if explanation is None or not support_visible(element, key):
            failures.append(f"unexpected or hidden reader support explanation: {key}")
            continue
        children, pending = [], list(element["children"])
        while pending:
            child = pending.pop()
            children.append(child)
            pending.extend(child["children"])
        messages = [e for e in children if "data-reader-support-message" in e["attrs"]]
        if attrs.get("data-reader-support-code") != explanation["code"] \
                or attrs.get("data-reader-support-availability") != explanation["availability"] \
                or len(messages) != 1 or "".join(messages[0]["text"]).strip() != explanation["message"] \
                or not support_visible(messages[0], key):
            failures.append(f"reader support explanation differs from its snapshot: {key}")
        links = {field.removesuffix("_ref"): ref for field, ref in explanation.items()
                 if field.endswith("_ref") and ref}
        application = next((ref for ref in explanation["path_refs"] if ref["collection"] == "uses"), None)
        if application:
            links["application"] = application
        shown_links = [e for e in children if "data-reader-support-link" in e["attrs"]]
        if Counter(e["attrs"]["data-reader-support-link"] for e in shown_links) != Counter(links.keys()):
            failures.append(f"reader support links differ from their context: {key}")
        for link in shown_links:
            ref = links.get(link["attrs"]["data-reader-support-link"])
            if ref is None or link["attrs"].get("data-reader-support-ref") != pin(ref) \
                    or not support_visible(link, key) \
                    or not any(child["attrs"].get("data-jump-record") == pin(ref) for child in link["children"]):
                failures.append(f"reader support link does not reach its pinned evidence: {key}")
    for key in explanations:
        if shown_explanations[key] != 1:
            failures.append(f"reader support explanation missing or duplicated: {key}")
    failures.extend(_scientific_failures(scan, projection))
    return failures


def mechanical_acceptance(html_bytes: bytes, projection: dict, *, build=None) -> dict:
    """Compare rendered scientific evidence, assessments and destinations with the saved projection."""
    scan = _Scan()
    scan.feed(html_bytes.decode("utf-8"))
    scan.close()
    failures = []
    embedded = None
    try:
        embedded = json.loads("".join(scan.scripts.get("proof-projection", [])))
    except ValueError as exc:
        failures.append(f"embedded projection is not JSON: {exc}")
    if embedded is not None and compact_json(embedded) != compact_json(projection):
        failures.append("embedded projection differs from the built projection")
    node_ids = [n["id"] for n in projection["nodes"]]
    connection_ids = [c["id"] for c in projection["connections"]]
    hypotheses = projection.get("hypothesis_connections", [])
    hypothesis_ids = [entry["id"] for entry in hypotheses]
    visible_hypotheses = [entry for entry in hypotheses if entry.get("proof_connection_id") is None]
    visible_edge_ids = connection_ids + [entry["id"] for entry in visible_hypotheses]
    if projection["layout"]["mode"] in ("dag", "cyclic"):
        if not _multiset_equal(scan.node_ids, node_ids):
            failures.append("diagram node identities differ from projection nodes")
        if not _multiset_equal(scan.edge_ids, visible_edge_ids):
            failures.append("diagram edge identities differ from projection connections")
        if scan.index_items or scan.index_connections or scan.index_hypotheses:
            failures.append(f"{projection['layout']['mode']} mode emitted index articles")
    else:
        if not _multiset_equal(scan.index_items, node_ids):
            failures.append("index item identities differ from projection nodes")
        if not _multiset_equal(scan.index_connections, connection_ids):
            failures.append("index connection identities differ from projection connections")
        if not _multiset_equal(scan.index_hypotheses, hypothesis_ids):
            failures.append("index hypothesis identities differ from projection hypotheses")
        if scan.node_ids or scan.edge_ids:
            failures.append("index mode emitted diagram elements")
    for node in projection["nodes"]:
        if scan.node_states.get(node["id"]) != _review_color(node["assessment"]):
            failures.append(f"node {node['id']} shows state {scan.node_states.get(node['id'])!r}")
    for connection in projection["connections"]:
        expected = (connection["from"], connection["to"], _review_color(connection["assessment"]))
        if scan.edge_states.get(connection["id"]) != expected:
            failures.append(f"connection {connection['id']} shows {scan.edge_states.get(connection['id'])!r}")
    shown_hypotheses = visible_hypotheses if projection["layout"]["mode"] in ("dag", "cyclic") else hypotheses
    for hypothesis in shown_hypotheses:
        expected = (hypothesis["from"], hypothesis["to"], "hypothesis")
        if scan.edge_states.get(hypothesis["id"]) != expected:
            failures.append(f"hypothesis {hypothesis['id']} shows {scan.edge_states.get(hypothesis['id'])!r}")
    summary = projection["summary"]
    if scan.process != [str(summary["progress"]["process_complete"]).lower()]:
        failures.append(f"process completion marker shows {scan.process!r}")
    if not _multiset_equal(scan.findings, summary["findings"]["refs"]):
        failures.append("listed findings differ from summary.findings.refs")
    if not _multiset_equal(scan.limits, summary["source_limits"]):
        failures.append("listed source limits differ from summary.source_limits")
    if scan.external:
        failures.append(f"page references external resources: {scan.external[:3]}")
    failures.extend(_visible_failures(scan, projection, build=build))
    failures.extend(_reader_failures(scan, projection))
    return {"status": "pass" if not failures else "fail", "failures": failures,
            "nodes": len(node_ids), "connections": len(connection_ids), "hypothesis_connections": len(hypothesis_ids),
            "layout_mode": projection["layout"]["mode"]}


def render_html(db: Database, projection: dict, *, release: bool, source_identity: str, workdir: Path) -> tuple:
    """Run the renderer in ``workdir``; return ``(html_bytes, receipt)`` or raise ``PublicationError``."""
    payload = render_input(db, projection, release=release, source_identity=source_identity)
    return render_payload(payload, workdir=workdir)


def render_payload(payload: dict, *, workdir: Path) -> tuple:
    """Render an already frozen presentation input without a scientific database."""
    node = _node_executable()
    if not RENDERER.is_file():
        raise PublicationError(f"renderer missing at {RENDERER}")
    input_path = workdir / "render-input.json"
    output_path = workdir / "report.html"
    input_path.write_bytes(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    try:
        run = subprocess.run([node, str(RENDERER), str(input_path), str(output_path)], capture_output=True,
                             timeout=RENDER_TIMEOUT, cwd=str(workdir))
    except subprocess.TimeoutExpired:
        raise PublicationError(f"renderer exceeded {RENDER_TIMEOUT} seconds") from None
    stderr = run.stderr.decode("utf-8", "replace").strip()
    if run.returncode != 0:
        detail = stderr
        try:
            detail = json.loads(stderr.splitlines()[-1]) if stderr else {"error": "renderer produced no diagnostics"}
        except ValueError:
            pass
        raise PublicationError("renderer failed", records=[detail] if isinstance(detail, dict) else [{"stderr": detail}])
    try:
        receipt = json.loads(run.stdout.decode("utf-8"))
    except ValueError:
        raise PublicationError("renderer printed an unreadable receipt",
                               records=[{"stdout": run.stdout.decode("utf-8", "replace")[:2000]}]) from None
    html_bytes = output_path.read_bytes()
    if receipt.get("representation", {}).get("status") != "pass":
        raise PublicationError("renderer representation receipt failed", records=[receipt])
    if receipt.get("geometry", {}).get("status") == "fail":
        raise PublicationError("renderer geometry receipt failed", records=[receipt])
    if receipt.get("artifact_sha256") != sha256_bytes(html_bytes):
        raise PublicationError("renderer receipt hash does not match the written page", records=[receipt])
    if receipt.get("input_sha256") != sha256_bytes(input_path.read_bytes()):
        raise PublicationError("renderer receipt hash does not match its input", records=[receipt])
    acceptance = mechanical_acceptance(html_bytes, payload["projection"], build=payload["build"])
    scan = _Scan()
    scan.feed(html_bytes.decode("utf-8"))
    try:
        embedded = json.loads("".join(scan.scripts["proof-render-input"]))
    except (KeyError, ValueError):
        embedded = None
    if embedded != {"title": payload["title"], "build": payload["build"]}:
        acceptance["failures"].append("embedded build metadata differs from its frozen input")
        acceptance["status"] = "fail"
    if acceptance["status"] != "pass":
        raise PublicationError("mechanical acceptance failed", records=[acceptance])
    receipt["python_acceptance"] = acceptance
    receipt["input_bytes"] = input_path.stat().st_size
    display = payload.get("display", {})
    receipt["math_diagnostics"] = display.get("math_diagnostics", [])
    receipt["math_diagnostic_summary"] = display.get("math_diagnostic_summary",
                                                           summarize_math_diagnostics([]))
    return html_bytes, receipt


def frozen_render_input(snapshot: dict, *, snapshot_sha256: str) -> dict:
    """Construct presentation fields solely from saved scientific bytes."""
    return {"render_input_version": 1, "title": snapshot["paper"]["title"],
            "build": {"core_version": CORE_VERSION, "revision": snapshot["revision"],
                      "audit_id": snapshot["audit_id"], "built_at": now_iso(),
                      "source_identity": snapshot["source_identity"], "kind": snapshot["kind"],
                      "scientific_producer": snapshot["producer"],
                      "finalization": {"snapshot_sha256": snapshot_sha256,
                          "process_complete": snapshot["process_complete"],
                          "representation_settled": snapshot["representation_settled"],
                          "finalization_blockers": snapshot["finalization_blockers"],
                          "finalization_blocker_count": snapshot["finalization_blocker_count"]}},
            "projection": snapshot["projection"], "display": _display_metadata(snapshot["projection"])}


def _restore_output(path, backup, existed):
    if existed:
        shutil.copy2(backup, path)
    else:
        path.unlink(missing_ok=True)


def publish_frozen(bundle, *, output, receipt_output=None) -> dict:
    """Build a frozen bundle without reading or writing the live scientific store."""
    from .finalization import (EXPORT_NAME, RECEIPT_NAME, SNAPSHOT_NAME, SUMMARY_NAME,
                               load_finalization, protected_destination)
    directory = resolve_path(bundle)
    snapshot, frozen = load_finalization(directory)
    protected = snapshot["protected_paths"] + [str(directory / name) for name in (
        SNAPSHOT_NAME, RECEIPT_NAME, SUMMARY_NAME, EXPORT_NAME)]
    output = protected_destination(output, protected)
    receipt_path = Path(receipt_output) if receipt_output is not None else output.with_name(output.name + ".receipt.json")
    receipt_path = protected_destination(receipt_path, protected + [str(output)], what="build receipt")
    before_html, before_receipt = output.exists(), receipt_path.exists()
    prior_output_retained, prior_receipt_retained = before_html, before_receipt
    pub_id, started = new_id("publication"), now_iso()
    committed = False
    warnings = []
    try:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PublicationError("could not create local report output directories", code="OUTPUT_PATH_FAILED",
                                   records=[{"output_directory": str(output.parent),
                                             "build_receipt_directory": str(receipt_path.parent),
                                             "details": str(exc)}]) from None
        with staging_directory(output.parent, ".paper-report-") as workdir:
            cleanup_path = workdir
            payload = frozen_render_input(snapshot, snapshot_sha256=frozen["snapshot_sha256"])
            html_bytes, render_receipt = render_payload(payload, workdir=workdir)
            artifact_sha = sha256_bytes(html_bytes)
            receipt = {"build_receipt_version": 1, "publication_id": pub_id, "state": "published",
                       "revision": snapshot["revision"], "audit_id": snapshot["audit_id"],
                       "paper_id": snapshot["paper_id"], "kind": snapshot["kind"],
                       "source_identity": snapshot["source_identity"], "producer": snapshot["producer"],
                       "snapshot_sha256": frozen["snapshot_sha256"], "artifact_sha256": artifact_sha,
                       "started_at": started, "output_path": str(output), "renderer": render_receipt,
                       "math_diagnostics": payload["display"]["math_diagnostics"],
                       "math_diagnostic_summary": payload["display"]["math_diagnostic_summary"]}
            staged_html = workdir / "staged.html"
            staged_html.write_bytes(html_bytes)
            fd, name = tempfile.mkstemp(dir=receipt_path.parent, prefix=".paper-build-", suffix=".json")
            os.close(fd)
            staged_receipt = Path(name)
            staged_receipt.write_text(json.dumps(receipt, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            prior_html, prior_receipt = workdir / "prior.html", workdir / "prior-receipt.json"
            if before_html:
                shutil.copy2(output, prior_html)
            if before_receipt:
                shutil.copy2(receipt_path, prior_receipt)
            replaced_html = replaced_receipt = False
            commit_error = None
            try:
                protected_destination(output, protected)
                protected_destination(receipt_path, protected + [str(output)], what="build receipt")
                _replace_file(staged_html, output)
                replaced_html = True
                prior_output_retained = False
                _replace_file(staged_receipt, receipt_path)
                replaced_receipt = True
                prior_receipt_retained = False
                committed = True
            except BaseException as primary:
                commit_error = primary
                if replaced_receipt:
                    try:
                        _restore_output(receipt_path, prior_receipt, before_receipt)
                    except Exception as restore:
                        primary.add_note(f"Prior build receipt restoration failed at {receipt_path}: {restore}")
                    else:
                        prior_receipt_retained = before_receipt
                if replaced_html:
                    try:
                        _restore_output(output, prior_html, before_html)
                    except Exception as restore:
                        primary.add_note(f"Prior report restoration failed at {output}: {restore}")
                    else:
                        prior_output_retained = before_html
                raise
            finally:
                cleanup_path = staged_receipt
                try:
                    staged_receipt.unlink(missing_ok=True)
                except Exception as cleanup:
                    if commit_error is None:
                        raise
                    commit_error.add_note(f"Build receipt staging cleanup also failed at {staged_receipt}: {cleanup}")
                cleanup_path = workdir
    except Exception as exc:
        failure_notes = list(getattr(exc, "__notes__", ()))
        if committed:
            warnings.append({"code": "REPORT_CLEANUP_FAILED",
                             "message": "The report and build receipt were published, but temporary-file cleanup failed.",
                             "details": " ".join([str(exc), *failure_notes]), "path": str(cleanup_path)})
        else:
            if not isinstance(exc, PublicationError):
                exc = PublicationError(f"frozen report delivery failed: {exc}")
                for note in failure_notes:
                    exc.add_note(note)
            if failure_notes:
                exc.records.append({"failure_notes": failure_notes})
            next_step = ("Choose valid, writable output and receipt directories, then rerun stage3 build with the same frozen bundle."
                         if exc.code == "OUTPUT_PATH_FAILED" else
                         "Fix the Phase 3 rendering or local delivery issue, then rerun stage3 build with the same frozen bundle.")
            exc.records.append({"publication_id": pub_id, "snapshot_sha256": frozen["snapshot_sha256"],
                                "bundle": str(directory), "prior_output_retained": prior_output_retained,
                                "prior_receipt_retained": prior_receipt_retained, "next_step": next_step})
            raise exc
    result = {"publication_id": pub_id, "state": "published", "kind": snapshot["kind"],
              "revision": snapshot["revision"], "snapshot_sha256": frozen["snapshot_sha256"],
              "artifact_sha256": artifact_sha, "output_path": str(output),
              "build_receipt_path": str(receipt_path), "receipt": receipt}
    if warnings:
        result["warnings"] = warnings
    return result


def _replace_file(staged: Path, destination: Path):
    os.replace(staged, destination)


def _report_destination(db: Database, output) -> Path:
    """Reject aliases of the database and registered manuscript files before rendering."""
    destination = resolve_path(output)
    paper = paper_record(db)
    root = Path(paper.body["source_root"])
    protected = [db.path.resolve()]
    for source in db.records_at(db.max_revision(), "sources"):
        path = Path(source.body["path"])
        protected.append((path if path.is_absolute() else root / path).resolve())
    for path in protected:
        same = destination == path
        if not same and destination.exists() and path.exists():
            same = destination.samefile(path)
        if same:
            raise InvalidRequest(f"report output collides with the database or a registered source: {destination}")
    if destination.exists() and destination.is_dir():
        raise InvalidRequest(f"output path is a directory: {destination}")
    return destination


def publish_report(db: Database, *, projection: dict, output, release: bool = False, source_identity: str | None = None,
                   publication_id: str | None = None) -> dict:
    """Render ``projection`` to ``output`` atomically and record the publication in the database.

    Requires a writable database. The prior page at ``output`` survives any failure. Returns
    ``{publication_id, revision, kind, state, output_path, artifact_sha256, receipt}``.
    """
    if not db.write:
        raise InvalidRequest("publication requires a writable database")
    output = _report_destination(db, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    kind = "release" if release else "working"
    pub_id = publication_id or new_id("publication")
    revision = projection["snapshot_revision"]
    if source_identity is None:
        from .packets import source_context_digest
        source_identity = source_context_digest(db)
    started = now_iso()
    try:
        with tempfile.TemporaryDirectory(dir=output.parent, prefix=".paper-report-") as tmp:
            workdir = Path(tmp)
            html_bytes, receipt = render_html(db, projection, release=release, source_identity=source_identity,
                                              workdir=workdir)
            staged = workdir / "staged.html"
            staged.write_bytes(html_bytes)
            artifact_sha = sha256_bytes(html_bytes)
            db.begin_immediate()
            try:
                db.put_blob(html_bytes)
                receipt.update({"publication_id": pub_id, "started_at": started, "output_path": str(output),
                                "kind": kind, "state": "published"})
                db.insert_publication(pub_id, revision, kind, "published", str(output), artifact_sha, receipt)
                _report_destination(db, output)
                _replace_file(staged, output)
            except Exception:
                db.rollback()
                raise
            db.commit()
    except PublicationError as exc:
        failure = {"publication_id": pub_id, "started_at": started, "output_path": str(output), "kind": kind,
                   "state": "failed", "error": exc.to_json()["error"]}
        try:
            db.begin_immediate()
            db.insert_publication(pub_id, revision, kind, "failed", str(output), None, failure)
            db.commit()
        except Exception as record_exc:  # pragma: no cover - secondary failure while recording the first
            try:
                db.rollback()
            except Exception:
                pass
            print(f"could not record failed publication: {record_exc}", file=sys.stderr)
        exc.records = list(exc.records) + [{"publication_id": pub_id, "prior_output_retained": output.exists()}]
        raise
    return {"publication_id": pub_id, "revision": revision, "kind": kind, "state": "published",
            "output_path": str(output), "artifact_sha256": artifact_sha, "receipt": receipt}


__all__ = ["FRAGMENT_FIELDS", "RENDERER", "display_fragments", "summarize_math_diagnostics", "mechanical_acceptance", "publish_report",
           "render_html", "render_input", "render_payload", "frozen_render_input", "publish_frozen"]
