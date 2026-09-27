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
from .storage import Database, now_iso, paper_record

RENDERER = Path(__file__).resolve().parent / "renderer" / "render_projection.mjs"
RENDER_TIMEOUT = 120
FRAGMENT_FIELDS = ("label", "statement", "reason", "needed_form", "rationale", "conditions", "reasoning", "description",
                   "proof_idea", "regime", "uncertainty", "impact_reason")
COUNT_NAMES_STATES = ("green", "red", "gray", "amber")


def _node_executable() -> str:
    node = shutil.which("node")
    if node is None:
        raise PublicationError("Node.js is required to render reports but no `node` executable was found")
    return node


def display_fragments(projection: dict) -> dict:
    """Escaped prose plus MathML for the text fields the renderer replaces; keyed by pinned ref."""
    refs = {}
    for entry in projection["records"]:
        ref, body = entry["ref"], entry["body"]
        fragments = {}
        for field in FRAGMENT_FIELDS:
            value = body.get(field)
            if field in ("statement", "needed_form") and isinstance(value, dict):
                value = value.get("text")
            if value is None:
                continue
            if field == "conditions":
                if isinstance(value, list) and all(isinstance(v, str) for v in value):
                    fragments["conditions_html"] = [render_text(v) for v in value]
                continue
            if isinstance(value, str):
                fragments[f"{field}_html"] = render_text(value)
        if fragments:
            refs[f"{ref['collection']}:{ref['id']}:{ref['version']}"] = fragments
    return refs


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
        "display": {"refs": display_fragments(projection)},
    }


class _Scan(HTMLParser):
    """Collect the embedded projection and the identity-bearing markers of a rendered page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.script_id = None
        self.scripts = {}
        self.node_ids, self.edge_ids, self.index_items, self.index_connections = [], [], [], []
        self.node_states, self.edge_states = {}, {}
        self.findings, self.limits, self.process = [], [], []
        self.limitations, self.limitation_open = [], False
        self.count_open, self.counts = None, {}
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
        if "data-proof-finding" in a:
            self.findings.append(a["data-proof-finding"])
        if "data-proof-source-limit" in a:
            self.limits.append(a["data-proof-source-limit"])
        if "data-proof-limitation" in a:
            self.limitations.append("")
            self.limitation_open = True
        if "data-proof-process-complete" in a:
            self.process.append(a["data-proof-process-complete"])
        if "data-proof-count" in a:
            self.count_open = a["data-proof-count"]
            self.counts[self.count_open] = ""
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
        if tag == "span" and self.count_open is not None:
            self.count_open = None
        if tag == "li":
            self.limitation_open = False

    def handle_data(self, data):
        for element in self.stack:
            element["text"].append(data)
        if self.script_id is not None:
            self.scripts[self.script_id].append(data)
        if self.count_open is not None:
            self.counts[self.count_open] += data
        if self.limitation_open:
            self.limitations[-1] += data


def _multiset_equal(a, b) -> bool:
    return sorted(a) == sorted(b)


def _visible_failures(scan, projection):
    """Check actual visible classes/text as well as identity metadata."""
    failures = []
    glyphs = {"green": "✓", "red": "✕", "gray": "?", "amber": "!"}
    text = lambda element: "".join(element["text"]).strip() if element else ""
    classes = lambda element: element["attrs"].get("class", "").split() if element else []

    def descendants(element):
        for child in element["children"]:
            yield child
            yield from descendants(child)

    def field(element, name):
        return next((child for child in descendants(element) if name in classes(child)), None) if element else None

    def assessment_matches(element, expected):
        return element is not None and f"s-{expected['state']}" in classes(element) \
            and text(field(element, "proof-assessment-label")) == expected["label"] \
            and text(field(element, "proof-assessment-text")) == expected["explanation"] \
            and text(field(element, "proof-state-glyph")) == glyphs[expected["state"]] \
            and (not expected.get("availability") or text(field(element, "proof-availability"))
                 == f"Exact target support: {expected['availability']}")

    by_detail = {e["attrs"]["data-proof-detail"]: e for e in scan.elements if "data-proof-detail" in e["attrs"]}
    for entry in projection["nodes"] + projection["connections"]:
        if not assessment_matches(field(by_detail.get(entry["detail_key"]), "proof-assessment"), entry["assessment"]):
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
    applications = {app["use_id"]: app for edge in projection["connections"] for app in edge.get("applications", ())}
    for element in scan.elements:
        attrs = element["attrs"]
        if "data-node-id" in attrs and (node := nodes.get(attrs["data-node-id"])):
            state = node["assessment"]["state"]
            if f"s-{state}" not in classes(element) or text(field(element, "proof-node-label")) != node["label"] \
                    or text(field(element, "proof-node-state")) != glyphs[state]:
                failures.append(f"visible node {node['id']} has altered color, label or glyph")
        if "data-edge-id" in attrs and (edge := connections.get(attrs["data-edge-id"])):
            state = edge["assessment"]["state"]
            if f"s-{state}" not in classes(element) or attrs.get("marker-end") != f"url(#proof-arrow-{state})":
                failures.append(f"visible connection {edge['id']} has an altered color")
        if "data-application-id" in attrs:
            app = applications.get(attrs["data-application-id"])
            if app is None or not assessment_matches(field(element, "proof-assessment"), app["assessment"]):
                failures.append(f"visible application {attrs['data-application-id']} has an altered assessment")
    scope = projection["summary"]["scope"]
    mode = [e for e in scan.elements if "data-proof-scope-mode" in e["attrs"]]
    targets = [e for e in scan.elements if "data-proof-scope-targets" in e["attrs"]]
    expected_targets = ", ".join(f"{r['collection']}:{r['id']}" for r in scope["target_refs"]) or (
        "Recorded items; no audit selected" if projection["audit_id"] is None else "No explicit audit targets recorded")
    if len(mode) != 1 or text(mode[0]) != scope["mode"] or len(targets) != 1 or text(targets[0]) != expected_targets:
        failures.append("visible audit scope differs from the canonical scope")
    factual = projection["summary"].get("factual")
    if factual is not None:
        support, review = factual["statement_support"], factual["independent_review"]
        outcomes = "; ".join(f"{outcome}: {factual['work']['current_primary_outcomes'][outcome]}"
                             for outcome in ("supported", "gap", "refuted", "inconclusive"))
        expected = {
            "snapshot": f"These facts describe snapshot {factual['revision']}. Process completion is separate from the mathematical outcomes.",
            "primary_outcomes": "Saved check counts include nonqualifying independent work. Current primary mathematical outcomes: " + outcomes + ".",
            "statement_support": "Statement support at each statement's recorded scope: " + "; ".join(
                f"{state} {support['counts'][state]}" for state in ("available", "conditional", "unavailable")) + ".",
            "independent_review": "Independent review: " + review["state"].replace("_", " ") + ".",
            **{f"checks.{key}": str(value) for key, value in factual["work"]["checks"].items()},
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
        groups = factual["work"].get("obligation_groups") or []
        if groups:
            expected["obligations.caption"] = ("Completed examinations do not mean verified statements; "
                                                "other completion requirements still apply.")
            expected.update({f"obligations.header.{field}": title for field, title in
                             (("role", "Role"), ("kind", "Examination"), ("required", "Required"),
                              ("completed", "Completed"), ("unfinished", "Unfinished"))})
        for index, row in enumerate(groups):
            labels = {"role": row["role"].capitalize(), "kind": "Source comparison" if
                      row["kind"] == "source_fidelity" else row["kind"].replace("_", " ").capitalize()}
            expected.update({f"obligations.{index}.{field}": labels[field] if field in labels else str(row[field])
                             for field in ("role", "kind", "required", "completed", "unfinished")})
        shown = [(e["attrs"]["data-proof-fact"], text(e)) for e in scan.elements if "data-proof-fact" in e["attrs"]]
        expected_completion = [(key, value) for key, value in expected.items() if key.startswith("obligations.")]
        shown_completion = [(key, value) for key, value in shown if key.startswith("obligations.")]
        if sorted(shown) != sorted(expected.items()) or shown_completion != expected_completion:
            failures.append("visible scientific summary differs from the assessed snapshot facts")
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
            add(key, f"finding:{i}", ref, "category", "description", "impact_reason")
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
            key, at = connection["detail_key"], f"application:{i}"
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
                     if "data-reader-overview" in e["attrs"]]
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

    for detail_key in reader_keys:
        reader = projection["details"][detail_key]["reader"]
        overview = next((e for e in scan.elements if e["attrs"].get("data-reader-overview") == detail_key), None)
        if overview is None:
            continue
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
        if text not in (raw.strip(), rendered_text[raw]) or not inside_overview(element, key[0]):
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
        if shown[key] != 1:
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
                explanations[connection["detail_key"], f"application:{index}"] = explanation
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
    return failures


def mechanical_acceptance(html_bytes: bytes, projection: dict) -> dict:
    """Compare embedded IDs, status counts and findings with the fixed projection (handoff 7.4)."""
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
    if projection["layout"]["mode"] in ("dag", "cyclic"):
        if not _multiset_equal(scan.node_ids, node_ids):
            failures.append("diagram node identities differ from projection nodes")
        if not _multiset_equal(scan.edge_ids, connection_ids):
            failures.append("diagram edge identities differ from projection connections")
        if scan.index_items or scan.index_connections:
            failures.append(f"{projection['layout']['mode']} mode emitted index articles")
    else:
        if not _multiset_equal(scan.index_items, node_ids):
            failures.append("index item identities differ from projection nodes")
        if not _multiset_equal(scan.index_connections, connection_ids):
            failures.append("index connection identities differ from projection connections")
        if scan.node_ids or scan.edge_ids:
            failures.append("index mode emitted diagram elements")
    for node in projection["nodes"]:
        if scan.node_states.get(node["id"]) != node["assessment"]["state"]:
            failures.append(f"node {node['id']} shows state {scan.node_states.get(node['id'])!r}")
    for connection in projection["connections"]:
        expected = (connection["from"], connection["to"], connection["assessment"]["state"])
        if scan.edge_states.get(connection["id"]) != expected:
            failures.append(f"connection {connection['id']} shows {scan.edge_states.get(connection['id'])!r}")
    summary = projection["summary"]
    expected_counts = {}
    for state in COUNT_NAMES_STATES:
        expected_counts[f"nodes.{state}"] = sum(1 for n in projection["nodes"] if n["assessment"]["state"] == state)
        expected_counts[f"connections.{state}"] = sum(1 for c in projection["connections"]
                                                      if c["assessment"]["state"] == state)
    for name in ("open", "resolved", "superseded"):
        expected_counts[f"findings.{name}"] = summary["findings"][name]
    for name, value in summary["progress"].items():
        if name != "process_complete":
            expected_counts[f"progress.{name}"] = value
    for name, value in expected_counts.items():
        shown = scan.counts.get(name)
        if shown is None or shown.strip() != str(value):
            failures.append(f"count {name} shows {shown!r}, projection has {value}")
    if scan.process != [str(summary["progress"]["process_complete"]).lower()]:
        failures.append(f"process completion marker shows {scan.process!r}")
    if not _multiset_equal(scan.findings, summary["findings"]["refs"]):
        failures.append("listed findings differ from summary.findings.refs")
    if not _multiset_equal(scan.limits, summary["source_limits"]):
        failures.append("listed source limits differ from summary.source_limits")
    if not _multiset_equal(scan.limitations, summary.get("limitations", [])):
        failures.append("listed completion limitations differ from summary.limitations")
    if scan.external:
        failures.append(f"page references external resources: {scan.external[:3]}")
    failures.extend(_visible_failures(scan, projection))
    failures.extend(_reader_failures(scan, projection))
    return {"status": "pass" if not failures else "fail", "failures": failures,
            "nodes": len(node_ids), "connections": len(connection_ids), "layout_mode": projection["layout"]["mode"]}


def render_html(db: Database, projection: dict, *, release: bool, source_identity: str, workdir: Path) -> tuple:
    """Run the renderer in ``workdir``; return ``(html_bytes, receipt)`` or raise ``PublicationError``."""
    node = _node_executable()
    if not RENDERER.is_file():
        raise PublicationError(f"renderer missing at {RENDERER}")
    payload = render_input(db, projection, release=release, source_identity=source_identity)
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
    acceptance = mechanical_acceptance(html_bytes, projection)
    if acceptance["status"] != "pass":
        raise PublicationError("mechanical acceptance failed", records=[acceptance])
    receipt["python_acceptance"] = acceptance
    receipt["input_bytes"] = input_path.stat().st_size
    return html_bytes, receipt


def _replace_file(staged: Path, destination: Path):
    os.replace(staged, destination)


def _report_destination(db: Database, output) -> Path:
    """Reject aliases of the database and registered manuscript files before rendering."""
    destination = Path(output).resolve()
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


__all__ = ["FRAGMENT_FIELDS", "RENDERER", "display_fragments", "mechanical_acceptance", "publish_report",
           "render_html", "render_input"]
