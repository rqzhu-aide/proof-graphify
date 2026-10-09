"""Deterministic, offline views of canonical proofcheck records.

This module owns presentation only. The caller supplies the validator namespace
and release eligibility; it never imports proofcheck or decides mathematical truth.
"""
from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import posixpath
import re
import sys
import textwrap
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote


PROJECTION_VERSION = 1
AUTHOR_CONTEXT_FIELDS = {"title", "confidence", "confidence_rationale", "limitations", "notes", "essential_scope"}
ASSURANCE = (
    "This is a non-formal proof audit. Recorded judgments depend on mathematical "
    "review, not a proof-assistant kernel. An invalid proof does not by itself "
    "show that its statement is false."
)
JUDGMENT_FIELDS = (
    "contract_fidelity", "argument_status", "statement_status",
    "dependency_closure", "use_site_sufficiency",
)
FIELD_LABELS = {
    "contract_fidelity": "Statement matched", "argument_status": "Written argument",
    "statement_status": "Statement", "dependency_closure": "Prerequisite support",
    "use_site_sufficiency": "Support for later uses",
}
STATUS_LABELS = {
    "not_established": "Not established by this proof", "established": "Established",
    "refuted": "Refuted", "not_assessed": "Not assessed", "not_checked": "Not checked",
    "conditionally_verified": "Conditional", "not_applicable": "Not applicable",
    "fresh_context_same_model": "Fresh context, same model",
    "different_model": "Different model", "independent_human": "Independent human",
    "gap": "Gap", "incorrect": "Incorrect", "verified": "Verified",
    "refutation_evidence": "Recorded refutation",
}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _source_review_note(provenance: Any) -> str:
    if _dict(provenance).get("kind") != "latex":
        return ""
    return (
        "The visual-review status below is required for PDF transcriptions. "
        "It does not report whether this LaTeX manuscript was separately inspected; "
        "see Source resolution or Additional authored notes for any recorded inspection."
    )


def _rows(value: Any) -> list:
    return value if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    return [v for v in _rows(value) if isinstance(v, str)]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(kind: str, *parts: Any) -> str:
    return kind + "-" + hashlib.sha256(_json(parts).encode("utf-8")).hexdigest()[:20]


def _text(value: Any) -> str:
    if value is None:
        return "Not recorded"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _e(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def math_renderer() -> Any:
    """Load the presentation adapter without changing Python's import path."""
    return _presentation_module("math")


def _presentation_module(name: str) -> Any:
    """Load a local presentation component, refreshing it when its bytes change."""
    path = Path(__file__).with_name(f"proofcheck_{name}.py")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    key = f"_proofcheck_report_{name}"
    module = sys.modules.get(key)
    if module is None or getattr(module, "_loaded_digest", None) != digest:
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        module._loaded_digest = digest
    return module


def _rich(value: Any) -> str:
    return math_renderer().render_text(_text(value))


def _reading_source(value: str) -> str:
    """Omit only standalone structural wrappers in the optional reading view."""
    return re.sub(
        r"(?m)^\s*\\(?:begin|end)\{(?:lemma|theorem|proposition|corollary|definition|assumption|proof)\}"
        r"(?:\[[^\[\]\n]+\])?(?:\\label\{[^{}\n]+\})?\s*$", "", value,
    ).strip()


def _location(span: Any) -> str:
    """A physical manuscript locator, never a ledger or inventory counter."""
    span = _dict(span)
    file = str(span.get("file") or "Source unavailable").replace("\\", "/").rsplit("/", 1)[-1]
    start, end = span.get("start_line"), span.get("end_line")
    embedded_range = re.fullmatch(r"(.+):(\d+)-(\d+)", file)
    if embedded_range and start is None and end is None:
        file, start, end = embedded_range.group(1), int(embedded_range.group(2)), int(embedded_range.group(3))
    if type(start) is not int or type(end) is not int:
        return file
    return f"{file}, line {start}" if start == end else f"{file}, lines {start} to {end}"


def _manuscript_title(environment: str, statement_sources: list[dict]) -> str | None:
    # Optional environment titles must be literal and unambiguous. This is not
    # a TeX expansion or a guess at compiled result numbering.
    openings = []
    pattern = re.compile(r"\\begin\{" + re.escape(environment) + r"\}\s*(?:\[([^\[\]\n]+)\])?")
    restatable = re.compile(r"\\begin\{restatable\*?\}\s*(?:\[([^\[\]\n]+)\])?\s*\{" + re.escape(environment) + r"\}")
    for source in statement_sources:
        if source.get("status") != "locked":
            continue
        openings.extend(pattern.finditer(source.get("quote") or ""))
        openings.extend(restatable.finditer(source.get("quote") or ""))
    return openings[0].group(1).strip() if len(openings) == 1 and openings[0].group(1) else None


def _printed_result_label(kind: str, statement_sources: list[dict]) -> str | None:
    """Read a literal numbered heading, never infer TeX's compiled counter."""
    pattern = re.compile(r"(?m)^\s*(" + re.escape(kind.capitalize()) + r"\s+\d+(?:\.\d+)*[a-z]?)\.(?=\s|$)")
    headings = [match.group(1) for source in statement_sources if source.get("status") == "locked"
                for match in pattern.finditer(source.get("quote") or "")]
    return headings[0] if len(headings) == 1 else None


def _separate_assertion(statement: dict, conclusion_sources: list[dict]) -> bool:
    """A separately anchored assertion does not inherit a formal result heading."""
    start, end = statement.get("start_line"), statement.get("end_line")
    if not statement.get("file") or type(start) is not int or type(end) is not int:
        return False
    return bool(conclusion_sources) and all(
        source.get("status") == "locked"
        and type(source.get("start_line")) is int and type(source.get("end_line")) is int
        and (source.get("file") != statement["file"]
             or source["end_line"] < start or source["start_line"] > end)
        for source in conclusion_sources
    )


def _pdf_page_location(text: str, start: int, end: int) -> str | None:
    """Recognize an explicit, reviewed transcription page map or keep lines."""
    pattern = re.compile(r"\[PDF page ([1-9]\d*)(?:; journal page ([1-9]\d*))?\]")
    markers = [(line, int(match.group(1)), match.group(2))
               for line, value in enumerate(text.splitlines(), 1)
               if (match := pattern.fullmatch(value.strip()))]
    if not markers or [row[1] for row in markers] != list(range(1, len(markers) + 1)):
        return None
    def page_at(line: int) -> tuple | None:
        return next((row for row in reversed(markers) if row[0] <= line), None)
    first, last = page_at(start), page_at(end)
    if first is None or last is None:
        return None
    if first[1] == last[1]:
        return f"PDF page {first[1]}" + (f" (journal page {first[2]})" if first[2] else "")
    return f"PDF pages {first[1]} to {last[1]}"


def _distinguish_result_titles(results: list[dict]) -> None:
    """An exact claim is a faithful fallback when source locators coincide."""
    counts: dict[str, int] = {}
    for result in results:
        counts[result["title"]] = counts.get(result["title"], 0) + 1
    for result in results:
        if counts[result["title"]] > 1:
            result["title"] += " · Claim: " + _text(result["claim"])


def _result_groups(projection: dict) -> list[dict]:
    """Group reading records by their existing owner, without a theorem verdict."""
    sources = {s["id"]: s for s in projection.get("sources", [])}
    metadata = _dict(projection.get("manuscript_units"))
    active_issues = {i["id"] for i in projection.get("issues", [])
                     if i.get("status") in {"open", "deferred"}}
    members: dict[str, list[dict]] = {}
    for result in projection["results"]:
        # An absent owner is not permission to merge similarly named records.
        owner = result.get("unit_id") or result["id"]
        members.setdefault(owner, []).append(result)
    groups = []
    for owner, rows in members.items():
        meta = _dict(metadata.get(owner))
        formal = [r for r in rows if not r.get("separate_assertion") and r.get("kind") != "conclusion"]
        separate = [r for r in rows if r not in formal]
        heading_rows = formal or rows
        kind = (formal[0].get("kind") if formal else None) or meta.get("kind") or heading_rows[0].get("kind") or "result"
        if str(kind).endswith("*"):
            kind = "unnumbered " + str(kind).removesuffix("*")
        source_ids = list(dict.fromkeys(_strings(meta.get("statement_source_ids")) or [
            key for r in formal for key in _strings(r.get("statement_source_ids"))]))
        locked = [sources[key] for key in source_ids
                  if key in sources and sources[key].get("status") == "locked"]
        title = meta.get("manuscript_title")
        if not title:
            titles = list(dict.fromkeys(r.get("manuscript_title") for r in heading_rows if r.get("manuscript_title")))
            title = titles[0] if len(titles) == 1 else None
        labels = list(dict.fromkeys(r.get("display_label") or r.get("printed_label")
                                   for r in formal if r.get("display_label") or r.get("printed_label")))
        label = labels[0] if len(labels) == 1 else meta.get("printed_label")
        location = meta.get("location") or "; ".join(dict.fromkeys(_location(s) for s in locked))
        location = location or heading_rows[0].get("paper_location") or heading_rows[0].get("location") or "Source unavailable"
        identity = label or str(kind).capitalize()
        heading = identity + " · " + (title or location)
        known = [r for r in formal if r.get("conclusion_id") is not None]
        unresolved = (len(known) != len(formal)
                      or owner in projection.get("coverage", {}).get("unresolved_conclusion_units", []))
        counts = {"conclusions": len(known), "associated_assertions": len(separate),
                  "unresolved_conclusion_count": unresolved,
                  "records": len(rows), "assessed": 0, "attention": 0, "pending": 0,
                  "conditional": 0, "refuted": 0, "proof_gaps": 0, "invalid_proofs": 0,
                  "unclear": 0, "insufficient": 0, "unavailable": 0}
        assertion_counts = {key: 0 for key in counts}
        for row in rows:
            judgments = _dict(row.get("judgments"))
            statement, argument = judgments.get("statement_status"), judgments.get("argument_status")
            unavailable = row.get("availability", "missing") != "available"
            pending = unavailable or any(judgments.get(k) in {None, "not_checked", "not_assessed", "unchecked", "stale"}
                                         for k in JUDGMENT_FIELDS)
            needs_attention = (pending or bool(active_issues.intersection(row.get("issue_ids", [])))
                               or any(v in {"gap", "invalid", "incorrect", "refuted", "not_established",
                                            "conditional", "conditionally_verified", "unclear", "insufficient"}
                                      for v in judgments.values()))
            row_counts = {
                "assessed": statement not in {None, "not_checked", "not_assessed", "unchecked"},
                "refuted": statement == "refuted", "proof_gaps": argument == "gap",
                "invalid_proofs": argument in {"invalid", "incorrect"},
                "conditional": any(v in {"conditional", "conditionally_verified"} for v in judgments.values()),
                "unclear": "unclear" in judgments.values(),
                "insufficient": "insufficient" in judgments.values(),
                "unavailable": unavailable, "pending": pending, "attention": needs_attention,
            }
            for key, value in row_counts.items():
                counts[key] += value
                if row in separate:
                    assertion_counts[key] += value
        count_label = f'{len(known)} recorded ' + ("conclusion" if len(known) == 1 else "conclusions")
        if unresolved:
            count_label = "Conclusion coverage unresolved" + (f'; {count_label}' if known else "")
        if separate:
            count_label += f'; {len(separate)} associated ' + ("assertion" if len(separate) == 1 else "assertions")
        flags = []
        for key, singular, plural in (
                ("refuted", "refuted conclusion", "refuted conclusions"),
                ("proof_gaps", "proof gap", "proof gaps"), ("invalid_proofs", "invalid proof", "invalid proofs"),
                ("conditional", "conditional", "conditional"), ("unclear", "unclear", "unclear"),
                ("insufficient", "with insufficient support", "with insufficient support"),
                ("pending", "check pending", "checks pending")):
            formal_count = counts[key] - assertion_counts[key]
            if formal_count:
                flags.append(f'{formal_count} {singular if formal_count == 1 else plural}')
        if assertion_counts["attention"]:
            labels = [label for key, label in (("refuted", "refuted"), ("proof_gaps", "proof gap"),
                      ("invalid_proofs", "invalid proof"), ("conditional", "conditional"),
                      ("unclear", "unclear"), ("insufficient", "insufficient support"),
                      ("pending", "checks pending")) if assertion_counts[key]]
            flags.append("Associated assertions: " + ", ".join(labels or ["need attention"]))
        if counts["attention"] and not flags:
            flags.append(f'{counts["attention"]} need attention')
        summary = "; ".join([*flags, count_label])
        boundary = any(s.get("math_excerpt_boundary") for s in locked)
        reading = "\n\n".join(_reading_source(s["quote"]) for s in locked if s.get("quote")) if not boundary else ""
        complete_statement = bool(meta.get("complete_statement") and reading
                                  and len(locked) == len(source_ids))
        statement_label = ("Manuscript statement from the current source snapshot"
                           if complete_statement else "Recorded statement passages; complete statement unavailable")
        groups.append({"id": _id("manuscript-result", owner), "unit_id": owner,
                       "result_ids": [r["id"] for r in rows],
                       "formal_result_ids": [r["id"] for r in formal],
                       "associated_result_ids": [r["id"] for r in separate],
                       "kind": kind, "display_label": label, "printed_label": label,
                       "manuscript_title": title, "title": heading, "location": location,
                       "paper_location": meta.get("paper_location"),
                       "statement_source_ids": source_ids,
                       "statement_label": statement_label, "complete_statement": complete_statement,
                       "claim": reading or ("A recorded statement excerpt cuts through a formula. Open the statement source for the exact preserved passages."
                                            if boundary else "The complete manuscript statement is unavailable in the recorded source passages. Open the individual assessed conclusions below."),
                       "graph_reading_claim": (reading if complete_statement else statement_label + ".\n\n" + reading) if reading else None,
                       "assessment_summary": summary, "assessment_counts": counts,
                       "availability": "available" if not counts["unavailable"] else "incomplete"})
    return groups


def _prepare_report_views(projection: dict) -> dict:
    """Share the derived views across rendering and release validation."""
    graph_module = _presentation_module("graph")
    graph = projection["graph"]
    if not graph.get("views") or any("display" not in n for n in graph["nodes"]):
        graph = graph_module.prepare_graph(graph, projection["results"],
                                          preferred_units=projection["audit"].get("target_units"))
    groups = _result_groups(projection)
    prepared = {**projection, "graph": graph, "result_groups": groups}
    if graph is not projection["graph"] or groups != projection.get("result_groups") or not projection.get("overview"):
        prepared["overview"] = graph_module.prepare_overview(graph, projection["results"], groups)
    prepared["summary"], prepared["summary_details"] = _reader_summary(prepared)
    return prepared


def _reader_summary(p: dict) -> tuple[dict, dict]:
    """A bounded reading view of already reviewed records, without new judgments."""
    coverage = _dict(p.get("coverage"))
    groups = p["result_groups"]
    results = {r["id"]: r for r in p["results"]}
    sources = {s["id"]: s for s in p.get("sources", [])}
    owners = {r: g for g in groups for r in g["result_ids"]}
    by_unit = {g["unit_id"]: g for g in groups}
    active = sorted((i for i in p["issues"] if i.get("status") in {"open", "deferred"}),
                    key=lambda i: (i.get("severity_rank", 99), str(i.get("severity", "")), i["id"]))
    resolved = [i for i in p["issues"] if i.get("status") == "resolved"]
    current = coverage.get("source_current", True)
    issue_log_available = coverage.get("issue_log_available", True)

    def counted(n: int, singular: str, plural: str | None = None) -> str:
        return f"{n} {singular if n == 1 else plural or singular + 's'}"

    def group_link(group: dict) -> dict:
        # A paper number is compact; source location disambiguates unnumbered names.
        label = group.get("display_label") or group.get("printed_label")
        location = re.sub(r", lines (\d+) to (\d+)$", r":\1-\2", group["location"])
        location = re.sub(r", line (\d+)$", r":\1", location)
        return {"anchor": group["id"], "label": label or str(group["kind"]).capitalize() + " · " + location}

    categories = {key: [] for key in ("proof_problems", "refuted", "conditional", "unsupported", "statement_uncertainty", "dependency_problems", "unchecked", "established", "supplemented", "restricted_supplements")}
    associated_attention = []
    associated_refuted = 0
    formal_ids = {r for g in groups for r in g["formal_result_ids"]}
    affected_groups: set[str] = set()
    for rid, result in results.items():
        judgments = _dict(result.get("judgments"))
        statement, argument = judgments.get("statement_status"), judgments.get("argument_status")
        available = current and result.get("availability") == "available"
        values = set(judgments.values())
        pending = not available or bool(values & {None, "not_checked", "not_assessed", "unchecked", "stale"})
        flags = {
            "proof_problems": available and argument in {"gap", "invalid", "incorrect"},
            "refuted": available and statement == "refuted",
            "conditional": available and bool(values & {"conditional", "conditionally_verified"}),
            "unsupported": available and (bool(values & {"not_established", "unclear", "insufficient"})
                                           or any(judgments.get(key) in {"gap", "incorrect", "invalid"} for key in ("dependency_closure", "use_site_sufficiency"))),
            "statement_uncertainty": available and any(judgments.get(key) in {"not_established", "unclear", "insufficient"} for key in ("contract_fidelity", "argument_status", "statement_status")),
            "dependency_problems": available and any(judgments.get(key) in {"gap", "incorrect", "invalid", "unclear", "insufficient"} for key in ("dependency_closure", "use_site_sufficiency")),
            "unchecked": pending,
            "established": available and statement == "established",
        }
        supplement = _dict(result.get("statement_support"))
        accepted = available and supplement.get("acceptance") == "accepted"
        flags["supplemented"] = accepted and statement == "established" and not _strings(supplement.get("extra_conditions")) and argument != "valid"
        flags["restricted_supplements"] = accepted and bool(_strings(supplement.get("extra_conditions")))
        attention = any(flags[key] for key in ("proof_problems", "refuted", "conditional", "unsupported", "unchecked"))
        if rid not in formal_ids:
            if attention:
                associated_attention.append(rid)
            associated_refuted += flags["refuted"]
            continue
        if attention:
            affected_groups.add(owners[rid]["id"])
        # An unavailable placeholder represents unresolved coverage, not a conclusion.
        if result.get("conclusion_id") is None:
            continue
        for key, value in flags.items():
            if value:
                categories[key].append(rid)
    counts = {key: len(value) for key, value in categories.items()}
    counts.update(affected_results=len(affected_groups), associated_assertions=len(associated_attention),
                  associated_refuted=associated_refuted,
                  proof_problem_results=len({owners[r]["id"] for r in categories["proof_problems"]}))
    impact_parts = []
    if affected_groups:
        impact_parts.append(counted(len(affected_groups), "manuscript result") + " with proof problems or unresolved support.")
    for key, description in (("proof_problems", "with a written proof gap or invalid step"),
                             ("refuted", "directly refuted"), ("conditional", "conditional"),
                             ("statement_uncertainty", "with unresolved statement, contract, or written-proof support"),
                             ("dependency_problems", "with problems in prerequisite or later-use support"),
                             ("unchecked", "with checks pending")):
        if counts[key]:
            impact_parts.append(counted(counts[key], "conclusion") + " " + description + ".")
    if sum(bool(counts[key]) for key in ("proof_problems", "refuted", "conditional", "unsupported", "unchecked")) > 1:
        impact_parts.append("These categories can overlap.")
    if counts["established"]:
        impact_parts.append(counted(counts["established"], "conclusion") + " recorded as established.")
    if counts["supplemented"]:
        impact_parts.append(counted(counts["supplemented"], "unchanged conclusion") + " supported by accepted supplements; written gaps remain distinct.")
    if counts["restricted_supplements"]:
        impact_parts.append(counted(counts["restricted_supplements"], "accepted supplement") + " with additional conditions.")
    if associated_attention:
        impact_parts.append(counted(len(associated_attention), "associated assertion") + " needing separate attention; this is not a whole-result verdict.")
        if associated_refuted:
            impact_parts.append(counted(associated_refuted, "associated assertion") + " directly refuted.")
    if not impact_parts:
        impact_parts.append("Current conclusion-level support is unavailable; absence of findings does not establish correctness.")

    featured = []
    word_budget = 75 // max(1, min(3, len(active)))
    for issue in active[:3]:
        origin = _dict(issue.get("origin_ref"))
        origin_kind = origin.get("kind")
        path = _dict(issue.get("proof_path"))
        failed = next((n for n in _rows(path.get("nodes")) if n.get("id") == path.get("origin_id")), {})
        origin_sources = [sources[s] for s in _strings(issue.get("source_ids")) if s in sources]
        origin_group = by_unit.get(origin.get("unit_id"))
        origin_labels = {"ledger_move": "Proof inference", "obligation_pointer": "Statement contract", "dependency_use": "Dependency use", "interface_record": "Method interface", "global_check": "Global check"}
        origin_label = origin_labels.get(origin_kind, "Recorded origin")
        location = next((s["paper_location"] for s in origin_sources if s.get("paper_location")), None)
        location = location or (failed.get("location") if origin_kind == "ledger_move" else None)
        location = location or next((s.get("paper_location") or _location(s) for s in origin_sources), None)
        location = origin_label + (" · " + location if location else " · source location unavailable")
        location_anchor = issue["anchor"]
        if failed and origin_kind == "ledger_move":
            location_anchor += "-path"
        elif origin_sources:
            location_anchor = origin_sources[0]["id"]
        elif origin_kind == "interface_record" and p.get("method_interfaces"):
            location_anchor = "method-interfaces"
        elif origin_kind == "global_check" and p.get("global_checks"):
            location_anchor = "global-checks"
        elif origin_kind == "dependency_use" and p.get("dependency_edges"):
            location_anchor = "dependency-records"
        linked_groups = {owners[r]["id"]: owners[r] for r in issue.get("affected_result_ids", []) if r in owners}
        if origin_group:
            linked_groups.setdefault(origin_group["id"], origin_group)
        label = ("Presentation finding" if issue.get("invalidation_kind") == "presentation_only" else
                 "Inconclusive finding" if issue.get("finding_status") == "inconclusive" else
                 "Recorded mathematical defect" if issue.get("finding_status") == "defect" else "Recorded finding")
        explanation = issue.get("summary")
        text = explanation if (_substantive(explanation) and len(explanation.split()) <= word_budget and len(explanation) <= 650) else "See the complete reviewed explanation."
        featured.append({"issue_id": issue["id"], "anchor": issue["anchor"], "label": label,
                         "text": text, "location": location, "location_anchor": location_anchor,
                         "result_links": [group_link(g) for g in list(linked_groups.values())[:3]],
                         "additional_results": max(0, len(linked_groups) - 3)})
    if featured:
        main_reason = " ".join(f'{row["label"]} at {row["location"]}: {row["text"]}' for row in featured)
        if not current:
            main_reason = "Recorded findings; current source evidence is unavailable. " + main_reason
        if len(active) > 3:
            main_reason += " " + counted(len(active) - 3, "additional active finding") + " in the complete findings list."
    elif not issue_log_available:
        main_reason = "The issue log is unavailable; no clean-audit inference can be made from its absence."
    elif affected_groups or associated_attention:
        main_reason = "No active finding is recorded, but conclusion judgments still show problems or unresolved support. Inspect the affected results."
    else:
        main_reason = "No active finding is recorded. The result judgments and review coverage below delimit what was checked."

    directions = []
    absent_repairs = 0
    local_survivals = 0
    no_local_repair = 0
    for issue in active:
        repairs = _rows(issue.get("repairs"))
        absent_repairs += not repairs
        for index, repair in enumerate(repairs, 1):
            status = repair.get("verification_status")
            verification = {"candidate": "Proposed; required rechecks remain", "verified_sufficient": "Recorded as verified sufficient for its target; manuscript application is not established here"}.get(status, "Verification unavailable")
            if not current:
                verification = "Current verification unavailable"
            cost = repair.get("scientific_cost") or "Scientific cost unrecorded"
            targets = [{"anchor": sid, "label": _location(sources[sid])}
                       for sid in _strings(repair.get("target_source_ids")) if sid in sources]
            target_ref = _dict(repair.get("target_ref"))
            target = "; ".join(row["label"] for row in targets) or (
                _location(target_ref) if target_ref.get("kind") == "source_span"
                else "target location unavailable")
            directions.append({"anchor": _id("repair", issue["id"], index),
                               "label": _label(repair.get("action", "recorded_direction")),
                               "target": target, "target_links": targets,
                               "cost": cost, "verification": verification,
                               "issue_anchors": [issue["anchor"]]})
        search = _dict(issue.get("repair_search"))
        local_survivals += any(s.get("outcome") == "survives_local_inspection" for s in _rows(search.get("strategies")) if isinstance(s, dict))
        no_local_repair += search.get("conclusion") == "no_local_repair_found"
    # Neither a shared finding nor a shared cost establishes that two repairs
    # substitute for each other. Keep each recorded target and state together.
    featured_directions, direction_texts = [], []
    for row in directions[:3]:
        text = row["label"] + " at " + row["target"] + ": " + row["cost"] + ". " + row["verification"] + "."
        if direction_texts and len(" ".join([*direction_texts, text]).split()) > 45:
            break
        featured_directions.append(row)
        direction_texts.append(text)
    repair_notes = ""
    if len(directions) > len(featured_directions):
        repair_notes = counted(len(directions) - len(featured_directions), "additional direction") + " in all recorded directions."
    if local_survivals:
        repair_notes += " " + counted(local_survivals, "search", "searches") + " retained a locally inspected route; local survival alone is not verification."
    if no_local_repair:
        repair_notes += " " + counted(no_local_repair, "bounded search") + " found no local repair; this is not an impossibility result."
    if absent_repairs:
        repair_notes += " No proposal is recorded for " + counted(absent_repairs, "active finding") + "."
    if not active:
        repair_notes = ("Resolved findings and their recorded rechecks remain in history. " if resolved else "") + "No active repair is recorded; this does not establish that all support is complete."
    repair_outlook = " ".join([*direction_texts, repair_notes.strip()]).strip()

    overall = {
        "no_defect_found": "No load-bearing defect found under the stated non-formal protocol.",
        "defects_found": "Defects found under the stated non-formal protocol.",
        "inconclusive": "The audit is inconclusive under the stated non-formal protocol.",
    }.get(str(p["audit"].get("overall_assessment")), "The recorded overall assessment is unavailable.")
    if p["release"].get("status") != "FINAL":
        overall = "NONFINAL: no overall judgment has been released."
        known_limits = []
        if coverage.get("expected_units") is None:
            known_limits.append("audit scope is unresolved")
        if not current:
            known_limits.append("source evidence is stale or unavailable")
        if coverage.get("missing_units") or coverage.get("invalid_units"):
            known_limits.append("some review records are unavailable")
        if coverage.get("expected_units") is not None and coverage.get("checked_units", 0) < coverage["expected_units"]:
            known_limits.append("local review completion is not confirmed")
        if coverage.get("independent_checked_units", 0) < coverage.get("checked_units", 0):
            known_limits.append("independent review remains")
        if coverage.get("dependency_check_available") is False:
            known_limits.append("dependency closure is unavailable")
        overall += " Known limits: " + "; ".join(known_limits) + "." if known_limits else " See recorded diagnostics and scope; release status alone does not identify the remaining cause."
    expected = coverage.get("expected_units")
    checked = set(_strings(coverage.get("checked_unit_ids")))
    independent = set(_strings(coverage.get("independent_checked_unit_ids")))
    # Older projections have aggregate counts only. Do not invent per-result completion.
    checked_count = sum(g["unit_id"] in checked for g in groups) if "checked_unit_ids" in coverage else coverage.get("checked_units", 0)
    independent_count = sum(g["unit_id"] in independent for g in groups) if "independent_checked_unit_ids" in coverage else coverage.get("independent_checked_units", 0)
    result_completion = "checked_unit_ids" in coverage and "independent_checked_unit_ids" in coverage
    denominator = str(len(groups) if result_completion else expected) if expected is not None else "unresolved"
    completion_label = "results" if result_completion else "audit units"
    coverage_text = [counted(len(groups), "manuscript result") + " represented; scope " + ("reviewed" if expected is not None else "unresolved"),
                     f"{checked_count} / {denominator} {completion_label} reviewed; {independent_count} / {denominator} independently reviewed",
                     counted(coverage.get("checked_conclusions", 0), "conclusion record") + " assessed" + ("; total coverage unresolved" if coverage.get("expected_conclusions") is None else ""),
                     counted(len(active), "active finding") + "; " + counted(len(resolved), "resolved finding") + ("; issue log unavailable" if not issue_log_available else "")]
    return ({"overall_judgment": overall, "main_reason": main_reason, "impact": " ".join(impact_parts), "repair_outlook": repair_outlook.strip()},
            {"featured_findings": featured, "remaining_active_findings": max(0, len(active) - 3),
             "active_findings": len(active), "resolved_findings": len(resolved), "source_current": current,
             "impact_counts": counts, "impact_links": [group_link(g) for g in groups if g["id"] in affected_groups][:3],
             "repair_directions": directions, "featured_repair_directions": featured_directions,
             "repair_notes": repair_notes.strip(),
             "coverage_text": coverage_text})


def _label(value: Any) -> str:
    return STATUS_LABELS.get(str(value), str(value).replace("_", " ").capitalize())


def _brief(value: Any, words: int = 38) -> str:
    text = _text(value)
    if len(text.split()) <= words:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences[0].split()) <= words:
        return sentences[0]
    return "The decisive explanation is preserved in full in Findings and repairs below."


def _caption(value: Any, limit: int = 90) -> str:
    """A navigation preview of recorded prose, not a manuscript result title."""
    text = _text(value)
    # Math is one indivisible token, including its exact original whitespace.
    # The full claim remains in the existing preview and result details.
    tokens, previous = [], 0
    for start, end, _, _ in math_renderer()._spans(text):
        tokens.extend(re.findall(r"\s+|\S+", text[previous:start]))
        tokens.append(text[start:end])
        previous = end
    tokens.extend(re.findall(r"\s+|\S+", text[previous:]))
    tokens = [" " if token.isspace() else token for token in tokens]
    text = "".join(tokens).strip()
    if len(text) <= limit:
        return text
    kept, length = [], 0
    for token in tokens:
        if not kept and token == " ":
            continue
        if length + len(token) > max(0, limit - 3):
            break
        kept.append(token)
        length += len(token)
    prefix = "".join(kept).rstrip()
    return prefix + "..." if prefix else ("See full statement." if limit >= 19 else "...")


def _source_reading(source: dict) -> str:
    """Do not present a source-range boundary as malformed manuscript TeX."""
    if source.get("math_excerpt_boundary"):
        return ('<p class="source-label math-excerpt-boundary">The cited lines cut through a formula. '
                'The exact excerpt is preserved in source evidence; '
                'this is an excerpt boundary, not a LaTeX syntax finding.</p>')
    return _rich(_reading_source(source["quote"]))


def _math_excerpt_boundary(source: dict, lines: list[str], first_line: int = 1,
                           *, cache: dict | None = None) -> bool:
    """Recognize a clipped formula only from authenticated containing text."""
    start, end = source["start_line"] - first_line, source["end_line"] - first_line
    if not 0 <= start <= end < len(lines):
        return False
    quote = source["quote"]
    if "\n".join(lines[start:end + 1]) != quote:
        return False
    context = "\n".join(lines)
    is_tex = Path(str(source.get("file", ""))).suffix.lower() in {".tex", ".ltx", ".sty", ".cls"}
    key = is_tex, context
    cache = {} if cache is None else cache
    if key not in cache:
        renderer = math_renderer()
        # Keep character offsets while omitting actual TeX comments. A dollar
        # in a neighboring comment must not make a complete formula look cut.
        if is_tex:
            masked = []
            for line in lines:
                comment = next((i for i, char in enumerate(line) if char == "%"
                                and not renderer._escaped(line, i)), len(line))
                masked.append(line[:comment] + " " * (len(line) - comment))
            context = "\n".join(masked)
        offsets, offset = [], 0
        for line in lines:
            offsets.append(offset)
            offset += len(line) + 1
        spans = [(a, b) for a, b, tex, _ in renderer._spans(context) if tex is not None]
        cache[key] = offsets, spans
    offsets, spans = cache[key]
    begin, finish = offsets[start], offsets[start] + len(quote)
    return any(a < begin < b or a < finish < b for a, b in spans)


def _substantive(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() not in {
        "", "none", "null", "not recorded", "unavailable", "not available", "n/a",
    }


def _supplement_status(supplement: dict) -> str:
    return str(supplement.get("status", "not_checked")) if supplement.get("acceptance") == "accepted" else "not_checked"


def _pointer(value: Any, pointer: str) -> Any:
    current = value
    try:
        for key in pointer.lstrip("/").split("/"):
            key = key.replace("~1", "/").replace("~0", "~")
            current = current[int(key)] if isinstance(current, list) else current[key]
        return current
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def _tone(status: Any) -> str:
    if status in {"refuted", "invalid", "incorrect", "defect", "refutation_evidence"}:
        return "defect"
    if status in {"established", "valid", "verified"}:
        return "checked"
    if status == "given":
        return "given"
    return "uncertain"


def validate_report_context(value: Any) -> list[str]:
    """Accept authored prose and preserve JSON-valued legacy fields explicitly."""
    if not isinstance(value, dict):
        return ["report_context must be an object"]
    errors = []
    for field in ("title", "confidence", "confidence_rationale", "essential_scope"):
        if field in value and (not isinstance(value[field], str) or not value[field].strip()):
            errors.append(f"report_context.{field} must be a nonempty string")
    for field in ("limitations", "notes"):
        if field in value and (not isinstance(value[field], list) or any(not isinstance(item, str) for item in value[field])):
            errors.append(f"report_context.{field} must be a list of strings")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        errors.append(f"report_context must contain JSON data: {exc}")
    return errors


def build_report_projection(
    pc: Any, root: Path, *, final: bool = False,
    finalized_at: str | None = None, report_context: dict | None = None,
    manifest_override: dict | None = None,
) -> dict:
    """Read canonical records, retaining unavailable work in a NONFINAL view.

    ``final=True`` requires readable, locally valid records and source/dependency
    closure. The enclosing release command must additionally apply its full gates.
    No clock reads or report/finalization hashes enter the projection.
    """
    root = Path(root).resolve()
    diagnostics: list[str] = []
    _, manifest, errors = pc.load_audit_manifest(root)
    diagnostics.extend(errors)
    if manifest_override is not None:
        if not isinstance(manifest_override, dict):
            raise ValueError("manifest_override must be an object")
        manifest = manifest_override
    manifest = _dict(manifest)
    report_directory = posixpath.dirname(pc.preferred_report_path(manifest)) or "."

    def report_href(relative: str) -> str:
        return quote(posixpath.relpath(relative, report_directory), safe="/")

    context = report_context if report_context is not None else manifest.get("report_context", {})
    context_errors = validate_report_context(context)
    # Context is literal author prose, never a Markdown evidence quotation.
    # Flatten lines so indentation, quotes, or headings cannot mask assertions.
    def authored_values(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [text for pair in value.items() for item in pair for text in authored_values(item)]
        if isinstance(value, list):
            return [text for item in value for text in authored_values(item)]
        return [" ".join(value.split())] if isinstance(value, str) else []
    for assertion in authored_values(context):
        pc.validate_report_assurance_language(
            "Authored assertion: " + assertion.replace("`", ""), "report_context", context_errors
        )
    if context_errors:
        raise ValueError("; ".join(context_errors))

    def read(path: Path, label: str) -> dict:
        try:
            value, failures = pc.load_json_object(path, label)
        except (OSError, UnicodeError, ValueError) as exc:
            value, failures = {}, [f"{label}: {exc}"]
        diagnostics.extend(str(error) for error in failures)
        return _dict(value)

    def declared(field: str, default: str, label: str) -> tuple[Path, dict]:
        if field in manifest:
            path, valid = pc.manifest_canonical_artifact_path(
                manifest, root, field, label, diagnostics
            )
            return path, read(path, label) if valid else {}
        path = root / default
        return path, read(path, label)

    inventory_path, inventory = declared(
        "inventory_file", "audit/01_index/theorem_inventory.json", "proof inventory"
    )
    _, registry = declared(
        "dependency_registry", "audit/03_dependencies/DEPENDENCY_REGISTRY.json",
        "dependency registry",
    )
    _, interface_registry = declared(
        "method_interface_registry", "audit/03_dependencies/METHOD_INTERFACE_REGISTRY.json",
        "method-interface registry",
    )
    try:
        _, raw_issues, _, issue_errors = pc.load_issue_log(root)
    except (OSError, UnicodeError, ValueError) as exc:
        raw_issues, issue_errors = [], [f"Issue log: {exc}"]
    diagnostics.extend(issue_errors)
    scope = _dict(manifest.get("audit_scope"))
    scope_known = scope.get("status") == "reviewed" and isinstance(scope.get("in_scope_units"), list)
    declared_units = _strings(scope.get("in_scope_units"))
    inventory_units = {
        str(row["id"]): row for row in _rows(inventory.get("units"))
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    units = list(dict.fromkeys(declared_units if scope_known else [
        *declared_units,
        *(key for key, row in inventory_units.items() if row.get("proof_required")),
    ]))
    if not scope_known:
        diagnostics.append("Audit scope is not reviewed; the expected unit count is unresolved.")
    if scope_known and not units:
        diagnostics.append("The reviewed scope contains no proof units.")

    summaries: dict[str, dict] = {}
    ledgers: dict[str, tuple[Path, dict]] = {}
    invalid_units: dict[str, list[str]] = {}
    try:
        paths = pc.live_local_check_artifacts(root, ".ledger.json")
        for path in paths:
            ledger = read(path, "proof ledger")
            unit = ledger.get("unit_id")
            if not isinstance(unit, str) or unit not in units:
                continue
            if unit in ledgers:
                invalid_units.setdefault(unit, []).append("Multiple live ledgers name this unit.")
                continue
            ledgers[unit] = (path, ledger)
            try:
                local_errors, summary = pc.check_ledger_data(path, final)
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                local_errors, summary = [f"Unreadable local record: {exc}"], {}
            if local_errors:
                invalid_units.setdefault(unit, []).extend(map(str, local_errors))
            else:
                if final:
                    summary["report_local_complete"] = True
                else:
                    try:
                        completion_errors, _ = pc.check_ledger_data(path, True)
                        summary["report_local_complete"] = not completion_errors
                    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                        summary["report_local_complete"] = False
                summaries[unit] = summary
    except (OSError, UnicodeError, ValueError) as exc:
        diagnostics.append(f"Cannot enumerate proof ledgers: {exc}")
    for unit, failures in invalid_units.items():
        summaries.pop(unit, None)
        diagnostics.extend(f"{unit}: {error}" for error in failures)

    try:
        source_freshness_errors = pc.source_snapshot_freshness_errors(root, manifest) if manifest else []
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        source_freshness_errors = [f"Source freshness is unavailable: {exc}"]
    diagnostics.extend(source_freshness_errors)
    if source_freshness_errors:
        # Local integrity alone cannot authorize current judgments after source drift.
        for unit in list(summaries):
            invalid_units.setdefault(unit, []).append("The source snapshot is stale or unavailable.")
        summaries.clear()

    closure_errors: list[str] = []
    dependency_edges: list[dict] = []
    if registry and scope_known:
        try:
            closure = pc.validate_dependency_closure(
                registry, root, summaries,
                source_snapshot_sha256=_dict(manifest.get("source_snapshot")).get("sha256", ""),
                inventory_sha256=pc.sha256_file(inventory_path) if inventory_path.is_file() else "",
                in_scope=units, errors=closure_errors,
            )
            dependency_edges = _rows(closure.get("edges"))
            if not closure_errors:
                pc.apply_derived_use_site_sufficiency(summaries, dependency_edges)
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            closure_errors.append(f"Dependency closure unavailable: {exc}")
    else:
        closure_errors.append("Dependency closure is not available for the current scope.")
    diagnostics.extend(closure_errors)

    sources: dict[str, dict] = {}
    page_texts: dict[Path, str] = {}
    math_contexts: dict[tuple[bool, str], tuple[list[int], list[tuple[int, int]]]] = {}
    provenance = _dict(manifest.get("input_provenance"))
    reviewed_pdf = (provenance.get("kind") == "pdf_transcription"
                    and _dict(provenance.get("visual_review")).get("status") == "complete"
                    and not source_freshness_errors)

    def source_span(span: Any, base: Path) -> str | None:
        span = _dict(span)
        start, end = span.get("start_line"), span.get("end_line")
        if not isinstance(span.get("file"), str) or type(start) is not int or type(end) is not int:
            return None
        try:
            resolved = pc.resolve_stored_path(span["file"], base).resolve()
            relative = resolved.relative_to(root).as_posix()
        except (OSError, ValueError):
            # Keep portable identity and embedded evidence even for external source.
            relative = span["file"].replace("\\", "/")
            resolved = None
        key = _id("source", relative, start, end, span.get("sha256"))
        if key not in sources:
            try:
                locked = pc.locked_span_projection(span, base)
            except (OSError, UnicodeError, ValueError):
                locked = None
            expected = span.get("sha256")
            matches = bool(locked) and (not expected or locked.get("sha256") == expected)
            if not matches:
                diagnostics.append(f"Source excerpt unavailable or changed: {relative}:{start}-{end}")
            href = None
            if resolved is not None and resolved.is_relative_to(root):
                href = report_href(relative)
            sources[key] = {
                "id": key, "file": relative, "start_line": start, "end_line": end,
                "sha256": expected, "quote": locked.get("quote") if matches else None,
                "status": "locked" if matches and expected else "source_excerpt" if matches else "unavailable",
                "bundle_href": href,
            }
            if (matches and expected and not source_freshness_errors
                    and resolved is not None and resolved.is_relative_to(root)):
                try:
                    if resolved not in page_texts:
                        page_texts[resolved] = pc.read_text(resolved)
                    if _math_excerpt_boundary(sources[key], page_texts[resolved].splitlines(), cache=math_contexts):
                        sources[key]["math_excerpt_boundary"] = True
                    if reviewed_pdf:
                        sources[key]["paper_location"] = _pdf_page_location(page_texts[resolved], start, end)
                except (OSError, UnicodeError):
                    pass
        return key

    def step_source(unit: str, step_id: Any) -> str | None:
        if unit not in summaries:
            return None
        value = pc.ledger_step_projection(summaries[unit], step_id)
        if not value:
            return None
        return source_span(value, value["ledger_path"].parent)

    def artifact_link(reference: Any, label: str) -> dict | None:
        reference = _dict(reference)
        relative = reference.get("artifact")
        if not isinstance(relative, str):
            return None
        try:
            path = (root / relative).resolve()
            relative = path.relative_to(root).as_posix()
            if not path.is_file() or (reference.get("sha256") and pc.sha256_file(path) != reference["sha256"]):
                raise ValueError("missing or changed artifact")
        except (OSError, ValueError):
            diagnostics.append(f"{label}: artifact is unavailable or changed.")
            return None
        return {"label": label, "artifact": relative, "href": report_href(relative)}

    def initial_review(ledger: dict, conclusion_id: Any) -> dict:
        check = _dict(ledger.get("independent_check"))
        reference = _dict(check.get("initial_response"))
        link = artifact_link(reference, "Preserved initial response")
        if not link:
            return {"status": "not_recorded", "source_ids": [], "artifacts": []}
        artifact = read(root / link["artifact"], "initial challenge response")
        response = _dict(artifact.get("response"))
        row = next((row for row in _rows(response.get("conclusions"))
                    if isinstance(row, dict) and row.get("conclusion_id") == conclusion_id), {})
        source_ids = []
        for ref in _rows(row.get("source_refs")):
            ref = _dict(ref)
            span = _dict(_pointer(artifact.get("packet"), ref.get("packet_pointer", "")))
            start, end = ref.get("start_line"), ref.get("end_line")
            member = _dict(span.get("source_member"))
            if type(start) is not int or type(end) is not int or not member.get("audit_relative_file"):
                continue
            lines = [line for line in _rows(span.get("lines")) if isinstance(line, dict)
                     and type(line.get("line")) is int and start <= line["line"] <= end]
            if [line["line"] for line in lines] != list(range(start, end + 1)):
                continue
            excerpt = "\n".join(str(line.get("text", "")) for line in lines)
            key = _id("review-source", reference.get("sha256"), ref)
            sources[key] = {"id": key, "file": member["audit_relative_file"],
                            "start_line": start, "end_line": end, "sha256": pc.sha256_text(excerpt),
                            "quote": excerpt, "status": "preserved_initial_review_source", "bundle_href": None}
            context_lines = _rows(span.get("lines"))
            if (context_lines and all(isinstance(line, dict) and type(line.get("line")) is int
                                      and isinstance(line.get("text"), str) for line in context_lines)
                    and [line["line"] for line in context_lines] == list(range(
                        context_lines[0]["line"], context_lines[0]["line"] + len(context_lines)))):
                if _math_excerpt_boundary(sources[key], [line["text"] for line in context_lines],
                                          context_lines[0]["line"], cache=math_contexts):
                    sources[key]["math_excerpt_boundary"] = True
            source_ids.append(key)
        links = [link]
        if check.get("artifact"):
            if reconciliation := artifact_link({"artifact": check["artifact"], "sha256": check.get("challenge_artifact_sha256")}, "Reconciliation record"):
                links.append(reconciliation)
        superseded = _dict(artifact.get("superseded_review"))
        for field, label in (("initial_response", "Superseded initial response"), ("reconciliation_artifact", "Superseded reconciliation")):
            if prior := artifact_link(superseded.get(field), label):
                links.append(prior)
        return {"status": "recorded" if row else "not_recorded",
                **{field: row.get(field) for field in ("verdict", "argument_status", "statement_status", "decisive_reason")},
                "source_ids": source_ids, "artifacts": links,
                "primary_snapshot": _dict(artifact.get("primary_snapshot")),
                "superseded_check": _dict(superseded.get("independent_check"))}

    results: list[dict] = []
    manuscript_units: dict[str, dict] = {}
    unknown_conclusion_units = []
    for unit in units:
        item = inventory_units.get(unit, {})
        formal_statement = dict(_dict(item.get("statement")))
        try:
            paper = pc.resolve_stored_path(manifest["paper_file"], root)
            formal_statement["file"] = pc.resolve_stored_path(formal_statement["file"], paper.parent).resolve().relative_to(root).as_posix()
        except (KeyError, OSError, TypeError, ValueError):
            formal_statement = {}
        manuscript_sources = []
        if formal_statement and not source_freshness_errors:
            # A reading excerpt from the current source snapshot, not a widened
            # proof/evidence span or a new mathematical assessment.
            try:
                full_statement = pc.locked_span_projection(formal_statement, root)
                if full_statement and (key := source_span({**formal_statement, "sha256": full_statement["sha256"]}, root)):
                    manuscript_sources.append(key)
            except (OSError, UnicodeError, ValueError, KeyError):
                pass
        manuscript_units[unit] = {
            "kind": item.get("semantic_kind") or item.get("environment") or "result",
            "manuscript_title": item.get("statement_title"),
            "statement_source_ids": manuscript_sources,
            "complete_statement": bool(manuscript_sources),
            "location": _location(formal_statement or item.get("statement")),
        }
        entry = ledgers.get(unit)
        ledger_path, ledger = entry if entry else (root / "audit/04_local_checks/missing", {})
        obligation = _dict(ledger.get("obligation"))
        summary = summaries.get(unit)
        contracts = _rows(obligation.get("conclusions")) if summary else []
        if not contracts:
            unknown_conclusion_units.append(unit)
            contracts = [{"id": None, "claim": item.get("statement_excerpt", "The result has not been normalized.")}]
        judgments = {
            row.get("conclusion_id"): row for row in _rows(_dict(summary).get("conclusion_results"))
            if isinstance(row, dict)
        }
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            conclusion_id = contract.get("id")
            judgment = judgments.get(conclusion_id, {})
            source_ids = [
                key for span in _rows(contract.get("source_spans"))
                if (key := source_span(span, ledger_path.parent))
            ]
            conclusion_source_ids = source_ids.copy()
            statement_source_ids = []
            if summary:
                statement_source_ids = [
                    key for span in _rows(obligation.get("statement_spans"))
                    if (key := source_span(span, ledger_path.parent))
                ]
                source_ids.extend(statement_source_ids)
                source_ids.extend(key for span in _rows(obligation.get("context_spans"))
                                  if (key := source_span(span, ledger_path.parent)))
            support = _dict(judgment.get("support"))
            support_step = next((s for s in _rows(ledger.get("steps")) if isinstance(s, dict) and s.get("id") == support.get("step_id")), {})
            support_move = next((m for m in _rows(_dict(support_step.get("inference")).get("moves")) if isinstance(m, dict) and m.get("id") == support.get("move_id")), {})
            support_source_ids = []
            if key := step_source(unit, support.get("step_id")):
                source_ids.append(key)
                support_source_ids.append(key)
            supplement = dict(_dict(judgment.get("statement_support")))
            if supplement:
                selected = _dict(supplement.get("support"))
                supplement["source_ids"] = [key] if (key := step_source(unit, selected.get("step_id"))) else []
                extra_step = next((step for step in _rows(ledger.get("steps")) if isinstance(step, dict) and step.get("id") == selected.get("step_id")), {})
                extra_move = next((move for move in _rows(_dict(extra_step.get("inference")).get("moves")) if isinstance(move, dict) and move.get("id") == selected.get("move_id")), {})
                supplement["reason"] = extra_move.get("justification")
            statuses = {field: judgment.get(field, "not_checked") for field in JUDGMENT_FIELDS}
            if closure_errors:
                statuses["dependency_closure"] = "not_checked"
                statuses["use_site_sufficiency"] = "not_checked"
            environment = str(item.get("environment", "result"))
            kind = str(item.get("semantic_kind") or environment)
            separate = _separate_assertion(formal_statement, [sources[key] for key in conclusion_source_ids])
            if separate:
                kind = "conclusion"
            elif kind.endswith("*") or environment == kind + "*":
                kind = "unnumbered " + kind.removesuffix("*")
            heading_sources = [] if separate else [sources[key] for key in statement_source_ids]
            manuscript_title = _manuscript_title(environment, heading_sources)
            printed_label = _printed_result_label(kind, heading_sources)
            locations = [sources[key] for key in (conclusion_source_ids if len(contracts) > 1 else statement_source_ids)]
            location = "; ".join(dict.fromkeys(_location(span) for span in locations)) or _location(item.get("statement"))
            paper_location = "; ".join(dict.fromkeys(span["paper_location"] for span in locations if span.get("paper_location")))
            description = contract.get("reader_description") if summary else None
            title = (printed_label or kind.capitalize()) + (": " + manuscript_title if manuscript_title else "")
            if _substantive(description):
                title += " · " + description
            title += " · " + (paper_location or location)
            if location == "Source unavailable":
                title += " · Statement preview: " + _caption(contract.get("claim"))
            results.append({
                "id": _id("result", unit, conclusion_id), "unit_id": unit,
                "conclusion_id": conclusion_id, "kind": kind,
                "source_environment": environment,
                "separate_assertion": separate,
                "title": title, "manuscript_title": manuscript_title,
                "manuscript_label": item.get("label"), "location": location,
                "printed_label": printed_label, "reader_description": description,
                "paper_location": paper_location or None,
                "claim": contract.get("claim", "Not recorded"), "judgments": statuses,
                "availability": "available" if summary else "invalid" if entry else "missing",
                "conditions": [
                    {"pointer": pointer, "value": _pointer(obligation, pointer)}
                    for pointer in _strings(contract.get("applies_under"))
                ],
                "support": support, "issue_ids": _strings(judgment.get("issue_ids")),
                "statement_support": supplement,
                "support_failure": _dict(support_move.get("failure")) if summary else {},
                "support_reason": support_move.get("justification") if summary else None,
                "source_ids": list(dict.fromkeys(source_ids)),
                "conclusion_source_ids": conclusion_source_ids,
                "statement_source_ids": statement_source_ids, "support_source_ids": support_source_ids,
                "independent_check": {
                    key: _dict(ledger.get("independent_check")).get(key)
                    for key in ("status", "independence_level", "challenger_verdict", "reconciled_verdict", "disagreements", "resolution")
                } if summary else {},
                "initial_review": initial_review(ledger, conclusion_id) if summary else {},
            })

    _distinguish_result_titles(results)
    for edge in dependency_edges:
        for condition in _rows(edge.get("statement_support_conditions")):
            if isinstance(condition, dict):
                condition["source_ids"] = [key for span in _rows(condition.get("evidence_spans"))
                                           if (key := source_span(span, root))]

    interfaces = {
        row.get("id", row.get("interface_id")): row
        for row in _rows(interface_registry.get("interfaces")) if isinstance(row, dict)
    }
    global_checks = {
        row.get("aspect"): row
        for row in _rows(_dict(_dict(manifest.get("completion")).get("global_consistency_pass")).get("checks"))
        if isinstance(row, dict)
    }
    # Only fixed delivery identities affect issue closure. Hashes, issue lists,
    # and verdict stamps are derived after rendering and cannot enter this view.
    deliverables = [
        {key: row.get(key) for key in ("id", "role", "path")}
        for row in _rows(manifest.get("report_deliverables")) if isinstance(row, dict)
    ]
    issues = []
    for issue in sorted((row for row in raw_issues if isinstance(row, dict)), key=lambda r: (str(r.get("severity")), str(r.get("id")))):
        details = {}
        try:
            details = pc.canonical_issue_detail_projection(
                issue, summaries, dependency_edges, units, deliverables,
                scope.get("overall_assessment"), evidence_base=root,
                interfaces=interfaces, global_checks=global_checks,
            )
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError) as exc:
            diagnostics.append(f"{issue.get('id')}: detailed issue evidence unavailable: {exc}")
        origin = _dict(issue.get("origin_ref"))
        origin_unit = str(origin.get("unit_id", issue.get("affected_result", "")))
        evidence_ids = []
        if issue.get("status") != "resolved":
            if key := step_source(origin_unit, origin.get("step_id")):
                evidence_ids.append(key)
        for span in _rows(origin.get("evidence_spans")):
            if key := source_span(span, root):
                evidence_ids.append(key)
        failures = []
        for row in _rows(details.get("failure")):
            if isinstance(row, list) and len(row) >= 10:
                evidence = pc.plain_report_diagnostic(row[8])
                failures.append({
                    "location": row[0], "unit_id": row[3], "reference": row[4],
                    "claim": row[5], "rule": row[6], "premises": row[7],
                    "evidence": evidence if _substantive(evidence) else None, "kind": row[9],
                    "availability": "available" if _substantive(evidence) else "unavailable",
                })
                # Canonical archive projections may refer to historical source;
                # preserve their exact quote, rather than substituting current text.
                try:
                    excerpt = json.loads(row[2])
                except (TypeError, json.JSONDecodeError):
                    excerpt = row[2]
                if isinstance(excerpt, str):
                    key = _id("source", issue.get("id"), row[0], row[1])
                    sources[key] = {"id": key, "file": row[0], "start_line": None,
                                    "end_line": None, "sha256": row[1], "quote": excerpt,
                                    "status": "canonical_issue_evidence", "bundle_href": None}
                    evidence_ids.append(key)
        repairs = []
        for change in _rows(issue.get("suggested_changes")):
            if not isinstance(change, dict):
                continue
            target_ref = _dict(change.get("target_ref"))
            target_source_ids = []
            if issue.get("status") != "resolved" and target_ref.get("kind") == "source_span":
                if key := source_span(target_ref, root):
                    target_source_ids.append(key)
            repairs.append({
                "target_ref": target_ref, "target_source_ids": target_source_ids,
                "proposal": change.get("proposal"), "action": change.get("action"),
                "verification_status": change.get("verification_status"),
                "repair_scope": change.get("repair_scope"),
                "assumption_cost": change.get("assumption_cost"),
                "claim_cost": change.get("claim_cost"),
                "scientific_cost": pc.repair_cost_language(change),
                "required_rechecks": _strings(change.get("required_rechecks")),
            })
        issues.append({
            "id": str(issue.get("id", "unidentified")), "anchor": _id("issue", issue.get("id")),
            "severity_rank": pc.ISSUE_SEVERITY_RANK.get(str(issue.get("severity")), 99),
            **{key: issue.get(key) for key in ("severity", "confidence", "status", "finding_status", "load_bearing", "summary", "invalidation_kind")},
            "origin_ref": origin, "contract_refs": _rows(issue.get("contract_refs")),
            "affected_units": _strings(issue.get("affected_results")),
            "affected_result_ids": [r["id"] for r in results if issue.get("id") in r["issue_ids"]],
            "source_ids": list(dict.fromkeys(evidence_ids)), "failures": failures,
            "repairs": repairs, "repair_search": _dict(issue.get("repair_search")),
            "resolution_evidence_needed": _strings(issue.get("resolution_evidence_needed")),
            "resolution": issue.get("resolution"), "current_resolution": _dict(issue.get("current_resolution")),
            "recheck_evidence": _rows(issue.get("recheck_evidence")),
            "rechecked_units": _strings(issue.get("rechecked_units")),
            "rechecked_dependency_uses": _strings(issue.get("rechecked_dependency_uses")),
            "historical_origin": _dict(issue.get("historical_origin")),
            "canonical_details": details,
        })

    label_review = _presentation_module("labels").resolve_labels(
        root, context.get("manuscript_labels"),
        "" if source_freshness_errors else _dict(manifest.get("source_snapshot")).get("sha256", ""),
        results, list(sources.values()))
    for result in results:
        reviewed = label_review["labels"].get(result["id"], {})
        result["display_label"] = result.get("printed_label") or reviewed.get("label", "")
        result["label_provenance"] = reviewed.get("provenance", {})
        if reviewed:
            result["display_pdf_page"] = reviewed["pdf_page"]
        reading = [sources[key] for key in result.get("conclusion_source_ids", [])
                   if key in sources and sources[key]["status"] == "locked"
                   and math_renderer().legacy_reading_has_math(sources[key].get("quote") or "")]
        if reading and not math_renderer().legacy_reading_has_math(_text(result.get("claim"))):
            result["graph_reading_claim"] = "\n\n".join(_reading_source(s["quote"]) for s in reading)
    proof_graph = _proof_graph(pc, results, ledgers, summaries, registry, source_span, issues, dependency_edges)
    for node in proof_graph["nodes"]:
        located = next((sources[k] for k in node.get("source_ids", [])
                        if k in sources and sources[k]["status"] == "locked"), None)
        if located:
            node.setdefault("location", _location(located))
    graph = _presentation_module("graph").prepare_graph(
        proof_graph, results, preferred_units=_strings(scope.get("target_units")))
    for issue in issues:
        issue["proof_path"] = _issue_proof_path(
            pc, issue, results, ledgers, summaries, inventory_units, dependency_edges, step_source, sources
        )
    checked_units = [unit for unit in units if unit in summaries and summaries[unit].get("report_local_complete")]
    independent_units = [unit for unit in checked_units if _dict(ledgers[unit][1].get("independent_check")).get("status") in {"agreed", "resolved"}]
    assessment = scope.get("overall_assessment") if final else "inconclusive"
    if final and (not scope_known or not units or len(checked_units) != len(units)):
        diagnostics.append("A final report requires every declared unit to have a completed valid ledger.")
    diagnostics = list(dict.fromkeys(str(value) for value in diagnostics))
    if final and diagnostics:
        raise ValueError("Cannot build a final report: " + "; ".join(diagnostics))
    projection = {
        "schema_version": PROJECTION_VERSION,
        "release": {"status": "FINAL" if final else "NONFINAL", "finalized_at": finalized_at if final else None},
        "audit": {
            "depth": scope.get("depth", "unresolved"), "scope_status": scope.get("status", "unresolved"),
            "overall_assessment": assessment, "target_units": _strings(scope.get("target_units")),
            "in_scope_units": units, "excluded_units": _rows(scope.get("excluded_units")),
            "source_revision": _dict(manifest.get("source_snapshot")).get("sha256"),
            "source_provenance": {key: value for key, value in _dict(manifest.get("input_provenance")).items() if key != "original_locations"},
            "source_files": _rows(_dict(manifest.get("source_snapshot")).get("files")),
            "protocol": _dict(manifest.get("protocol")),
            "limits": _rows(scope.get("source_or_parser_limits")),
            "deliverables": deliverables,
        },
        "coverage": {
            "expected_units": len(units) if scope_known else None,
            "checked_units": len(checked_units), "independent_checked_units": len(independent_units),
            "checked_unit_ids": checked_units, "independent_checked_unit_ids": independent_units,
            "issue_log_available": not issue_errors, "source_current": not source_freshness_errors,
            "dependency_check_available": not closure_errors,
            "expected_conclusions": len(results) if scope_known and not unknown_conclusion_units else None,
            "checked_conclusions": sum(r["availability"] == "available" and r["judgments"]["statement_status"] not in {"not_checked", "not_assessed"} for r in results),
            "unresolved_conclusion_units": unknown_conclusion_units,
            "missing_units": [unit for unit in units if unit not in ledgers],
            "invalid_units": sorted(invalid_units), "issues": len(issues),
        },
        "results": results, "issues": issues, "sources": list(sources.values()), "graph": graph,
        "manuscript_units": manuscript_units,
        "dependency_edges": dependency_edges,
        "dependency_registry": {key: registry.get(key, []) for key in ("internal_uses", "external_results", "review")},
        "method_interfaces": interface_registry,
        "global_checks": global_checks,
        "report_context": context, "diagnostics": diagnostics,
        "display_notes": label_review["notes"],
        "math_rendering": {
            "description": "Explicit LaTeX formulas are typeset as static MathML for offline, unscripted, and printed reading. Unsupported formulas retain labeled literal TeX. Source-backed reading views do not change normalized obligations or exact source excerpts.",
            "converter": math_renderer().renderer_info(),
        },
    }
    return _prepare_report_views(projection)


def _finding_labels(issue: dict) -> dict[str, str]:
    """Navigation describes the recorded finding, without upgrading its judgment."""
    if issue.get("status") == "resolved":
        defect = issue.get("finding_status") == "defect" and issue.get("invalidation_kind") != "presentation_only"
        return {"role": "Historical finding", "inspect": "Inspect historical finding",
                "explanation": "Recorded finding, resolution, and rechecks",
                "evidence": "Original failure evidence" if defect else "Preserved finding evidence",
                "heading": "Original failure before repair" if defect else "Finding before resolution"}
    if issue.get("invalidation_kind") == "presentation_only":
        role, explanation, heading = "Presentation concern", "Presentation concern and suggested revision", "Presentation concern"
    elif issue.get("finding_status") == "inconclusive":
        role, explanation, heading = "Unresolved inference", "Unresolved concern and evidence still needed", "Why the inference remains unresolved"
    elif issue.get("finding_status") == "defect":
        role, explanation, heading = "Failed inference", "Why this inference fails and how to repair it", "Why the step fails"
    else:
        role, explanation, heading = "Inference under review", "Recorded concern and review evidence", "Recorded concern"
    if _dict(issue.get("origin_ref")).get("kind") != "ledger_move":
        role = "Recorded defect" if issue.get("finding_status") == "defect" and issue.get("invalidation_kind") != "presentation_only" else "Recorded finding"
        explanation, heading = "Recorded finding and review evidence", "Recorded finding evidence"
    return {"role": role, "inspect": "Inspect " + role.lower(),
            "explanation": explanation, "evidence": role, "heading": heading}


def _issue_proof_path(pc: Any, issue: dict, results: list[dict], ledgers: dict,
                      summaries: dict, inventory: dict, dependency_edges: list[dict],
                      step_source: Any, sources: dict) -> dict:
    """A local reading path from actual consumed moves, never line adjacency.

    The path is a support explanation. Refutation remains separately bound to
    each exact result by the existing graph projection.
    """
    if issue.get("status") == "resolved":
        return {"status": "historical", "nodes": [], "edges": []}
    origin = _dict(issue.get("origin_ref"))
    origin_key = (origin.get("unit_id"), origin.get("step_id"), origin.get("move_id"))
    moves, steps, edges = {}, {}, []
    result_supports = {}
    for result in results:
        support = _dict(result.get("support"))
        key = (result["unit_id"], support.get("step_id"), support.get("move_id"))
        result_supports[(result["unit_id"], result["conclusion_id"])] = key
    uses = {(edge.get("dependent_unit"), edge.get("use_id")): edge for edge in dependency_edges}
    for unit, (_, ledger) in ledgers.items():
        if unit not in summaries:
            continue
        for step in _rows(ledger.get("steps")):
            if not isinstance(step, dict):
                continue
            steps[(unit, step.get("id"))] = step
            for move in _rows(_dict(step.get("inference")).get("moves")):
                if isinstance(move, dict):
                    moves[(unit, step.get("id"), move.get("id"))] = move
    for key, move in moves.items():
        unit, step_id, _ = key
        step = steps[(unit, step_id)]
        for prior in _strings(move.get("prior_move_ids")):
            edges.append({"from": (unit, step_id, prior), "to": key, "kind": "prior_move"})
        premises = {row.get("id"): row for row in _rows(step.get("premise_uses")) if isinstance(row, dict)}
        for premise_id in _strings(move.get("premise_ids")):
            premise = premises.get(premise_id, {})
            ref = _dict(premise.get("origin"))
            if ref.get("kind") == "prior_step":
                previous = steps.get((unit, ref.get("reference")), {})
                parent = (unit, ref.get("reference"), _dict(previous.get("inference")).get("conclusion_move"))
                edges.append({"from": parent, "to": key, "kind": "consumed_premise", "premise_id": premise_id})
            elif ref.get("kind") == "internal_result":
                use = uses.get((unit, ref.get("reference")), {})
                selected = _dict(_dict(use.get("statement_support")).get("support"))
                parent = ((use.get("dependency_id"), selected.get("step_id"), selected.get("move_id"))
                          if use.get("statement_support") else result_supports.get((use.get("dependency_id"), use.get("dependency_conclusion_id"))))
                if parent:
                    edges.append({"from": parent, "to": key, "kind": "dependency_use",
                                  "use_id": ref.get("reference"), "premise_id": premise_id,
                                  "occurrence_id": premise.get("source_reference_occurrence_id"),
                                  "effective_status": use.get("effective_status", "not_checked"),
                                  "applicability_status": use.get("applicability_status", "not_checked")})
    edges = [edge for edge in edges if edge["from"] in moves and edge["to"] in moves]
    if origin_key not in moves:
        return {"status": "unavailable", "nodes": [], "edges": []}
    parents, children = {}, {}
    for edge in edges:
        parents.setdefault(edge["to"], []).append(edge["from"])
        children.setdefault(edge["from"], []).append(edge["to"])

    def reachable(initial: set, reverse: bool = False) -> set:
        found = set(initial)
        pending = list(initial)
        while pending:
            current = pending.pop()
            for end in (parents if reverse else children).get(current, []):
                if end not in found:
                    found.add(end)
                    pending.append(end)
        return found

    # Only retain routes which actually reach a recorded affected conclusion.
    targets = {result_supports[(result["unit_id"], result["conclusion_id"])]
               for result in results if result["id"] in issue.get("affected_result_ids", [])}
    selected = (reachable({origin_key}) & reachable(targets, reverse=True)) | {origin_key}
    selected.update(edge["from"] for edge in edges if edge["to"] == origin_key)
    selected_edges = [edge for edge in edges if edge["from"] in selected and edge["to"] in selected]
    ordered = []
    pending = [key for key in moves if key in selected]
    while pending:
        ready = [key for key in pending if all(edge["from"] not in pending for edge in selected_edges if edge["to"] == key)]
        if not ready:  # Preserve an explicit record even for a NONFINAL cycle.
            ready = pending[:1]
        ordered.extend(ready)
        pending = [key for key in pending if key not in ready]

    nodes = []
    for key in ordered:
        unit, step_id, move_id = key
        move, step = moves[key], steps[(unit, step_id)]
        sid = step_source(unit, step_id)
        source_ids = [sid] if sid else []
        linked_results = [result["id"] for result in results
                          if result_supports[(result["unit_id"], result["conclusion_id"])] == key]
        incoming = [edge for edge in selected_edges if edge["to"] == key]
        role = _finding_labels(issue)["role"] if key == origin_key else "Later consuming inference" if any(edge["kind"] == "dependency_use" for edge in incoming) else "Conclusion step" if linked_results else "Consumed premise"
        premises = [row for row in _rows(step.get("premise_uses"))
                    if isinstance(row, dict) and row.get("id") in _strings(move.get("premise_ids"))]
        nodes.append({"id": _id("path-move", issue["id"], key), "unit_id": unit,
                      "step_id": step_id, "move_id": move_id, "role": role,
                      "location": _location(sources.get(sid)), "source_ids": source_ids,
                      "claim": move.get("claim"), "reason": move.get("justification"),
                      "status": step.get("status", "not_checked"), "failure": _dict(move.get("failure")),
                      "premises": premises, "result_ids": linked_results})
    node_ids = {key: node["id"] for key, node in zip(ordered, nodes)}
    projected_edges = []
    for edge in selected_edges:
        projected = {**edge, "from": node_ids[edge["from"]], "to": node_ids[edge["to"]], "citation_source_ids": []}
        if edge.get("occurrence_id"):
            unit = edge["to"][0]
            occurrence = next((row for row in _rows(_dict(inventory.get(unit)).get("reference_occurrences"))
                               if isinstance(row, dict) and row.get("occurrence_id") == edge["occurrence_id"]), {})
            # Match the physical citation to its locked source unit, including
            # a multiline invocation. It is not a deriving move by itself.
            for (candidate_unit, step_id), _ in steps.items():
                if candidate_unit != unit:
                    continue
                value = pc.ledger_step_projection(summaries[unit], step_id)
                if not value or type(occurrence.get("line")) is not int:
                    continue
                occurrence_file = str(occurrence.get("file", "")).replace("\\", "/")
                physical_file = str(value.get("file", "")).replace("\\", "/")
                if (physical_file == occurrence_file or physical_file.endswith("/" + occurrence_file)) and value["start_line"] <= occurrence["line"] <= value["end_line"]:
                    if sid := step_source(unit, step_id):
                        projected["citation_source_ids"].append(sid)
        projected_edges.append(projected)
    return {"status": "available", "nodes": nodes, "edges": projected_edges,
            "origin_id": node_ids[origin_key]}


def _proof_graph(pc: Any, results: list[dict], ledgers: dict, summaries: dict,
                 registry: dict, source_span: Any, issues: list[dict],
                 dependency_edges: list[dict] | None = None) -> dict:
    """Project each conclusion's actual backward support, not nearby citations."""
    nodes = {r["id"]: {"id": r["id"], "kind": r["kind"], "label": r["title"],
                       "claim": r["claim"], "status": r["judgments"]["statement_status"],
                       "detail_id": r["id"], "source_ids": r["source_ids"]} for r in results}
    results_by_key = {(r["unit_id"], r["conclusion_id"]): r for r in results}
    known_units = {r["unit_id"] for r in results} | set(ledgers)
    current_uses = {(edge.get("dependent_unit"), edge.get("use_id")): edge for edge in dependency_edges or []}
    edges = []
    def add_route(result: dict, supplement: dict | None = None) -> None:
        unit = result["unit_id"]
        if unit not in summaries:
            return
        path, ledger = ledgers[unit]
        support = _dict(supplement.get("support")) if supplement else result["support"]
        if not support.get("step_id") or not support.get("move_id"):
            return
        closure = pc.ledger_support_contract_closure(ledger, support["step_id"], support["move_id"])
        # One explicitly selected checked move defines each recorded route.
        # Joint premises meet at this argument node, never at a shared statement.
        route_id = _id("supplement-argument" if supplement else "argument", unit, result["conclusion_id"], support)
        support_projection = pc.ledger_step_projection(summaries[unit], support["step_id"])
        route_label = ("Supplemental argument · " if supplement else "Conclusion step · ") + _location(support_projection)
        route_status = _supplement_status(supplement) if supplement else result["judgments"]["argument_status"]
        nodes[route_id] = {"id": route_id, "kind": "argument", "label": route_label,
                           "claim": "Selected support for " + result["title"],
                           "status": route_status, "detail_id": route_id,
                           "source_ids": supplement.get("source_ids", []) if supplement else result.get("support_source_ids", result["source_ids"]),
                           "reason": supplement.get("reason") if supplement else result.get("support_reason"),
                           "technical_reference": {"unit_id": unit, "support": support}}
        target_id = result["id"]
        if supplement:
            target_id = _id("statement-support", unit, result["conclusion_id"], supplement.get("sha256"))
            conditions = _strings(supplement.get("extra_conditions"))
            nodes[target_id] = {"id": target_id, "kind": "restricted statement" if conditions else "supplemented statement",
                                "label": ("Restricted form of " if conditions else "Supplement for ") + result["title"],
                                "claim": supplement.get("claim", result["claim"]), "conditions": conditions,
                                "status": route_status, "detail_id": target_id,
                                "source_ids": supplement.get("source_ids", []),
                                "result_id": result["id"], "acceptance": supplement.get("acceptance", "pending"),
                                "technical_reference": {"statement_support_sha256": supplement.get("sha256")}}
            if not conditions:
                edges.append({"from": target_id, "to": result["id"], "kind": "support", "unit_id": unit,
                              "status": route_status, "label": "Supplement addresses the unchanged statement; the written route keeps its own judgment"})
            for condition in conditions:
                key = _id("supplement-condition", unit, result["conclusion_id"], condition)
                nodes[key] = {"id": key, "kind": "condition", "label": "Supplement condition: " + _caption(condition),
                              "claim": condition, "status": "given", "detail_id": key, "source_ids": []}
                edges.append({"from": key, "to": route_id, "kind": "support", "unit_id": unit,
                              "label": "Additional condition of this restricted supplement"})
        edges.append({"from": route_id, "to": target_id, "kind": "support", "unit_id": unit, "support": support, "route_id": route_id,
                      "status": route_status, "label": "Supplemental argument" if supplement else "Written argument"})
        obligation = _dict(ledger.get("obligation"))
        for pointer in sorted(closure.get("obligation_pointers", set())):
            value = _pointer(obligation, pointer)
            if value is None:
                continue
            kind = "definition" if pointer.startswith("/definitions/") else "assumption" if pointer.startswith("/hypotheses/") else "condition"
            key = _id("premise", unit, pointer)
            anchors = []
            used_steps = {step for step, _ in closure.get("move_keys", set())}
            for step in _rows(ledger.get("steps")):
                if not isinstance(step, dict) or step.get("id") not in used_steps:
                    continue
                for premise in _rows(step.get("premise_uses")):
                    origin = _dict(_dict(premise).get("origin"))
                    if origin.get("kind") != "obligation" or origin.get("reference") != pointer:
                        continue
                    anchor = _dict(origin.get("anchor"))
                    spans = _rows(obligation.get("context_spans" if anchor.get("kind") == "context_span" else "statement_spans"))
                    index = anchor.get("index")
                    if type(index) is int and 0 < index <= len(spans):
                        anchors.append(spans[index - 1])
            source_ids = list(dict.fromkeys(sid for span in anchors if (sid := source_span(span, path.parent))))
            premise_label = {"definition": "Definition", "assumption": "Given condition", "condition": "Scope condition"}[kind]
            nodes[key] = {"id": key, "kind": kind, "label": premise_label + ": " + _caption(value),
                          "claim": _text(value), "status": "given", "detail_id": key,
                          "location": _location(anchors[0]) if anchors else result.get("location", "Source unavailable"),
                          "source_ids": source_ids, "technical_reference": {"unit_id": unit, "pointer": pointer}}
            edges.append({"from": key, "to": route_id, "kind": "support",
                          "unit_id": unit, "pointer": pointer, "support": support})
        uses = {row.get("use_id"): row for row in _rows(_dict(ledger.get("review")).get("direct_dependencies")) if isinstance(row, dict)}
        for use_id in sorted(closure.get("dependency_uses", set())):
            use = uses.get(use_id, {})
            dependency_id, conclusion_id = use.get("id"), use.get("conclusion_id")
            dependency = results_by_key.get((dependency_id, conclusion_id))
            current_use = current_uses.get((unit, use_id), {})
            selected_supplement = _dict(current_use.get("statement_support"))
            if dependency and selected_supplement:
                key = _id("statement-support", dependency_id, conclusion_id, selected_supplement.get("sha256"))
                if _dict(dependency.get("statement_support")).get("sha256") != selected_supplement.get("sha256"):
                    nodes[key] = {"id": key, "kind": "unavailable supplement", "label": "Selected supplement unavailable · " + dependency["title"],
                                  "claim": selected_supplement.get("claim", use.get("needed_form", "Not recorded")),
                                  "status": "not_checked", "detail_id": key, "source_ids": []}
            elif dependency:
                key = dependency["id"]
            else:
                internal = use.get("kind") == "internal_result" or dependency_id in known_units
                key = _id("internal-unavailable" if internal else "external", unit, use_id, dependency_id, conclusion_id)
                located = next((row for row in results if row["unit_id"] == dependency_id), {})
                external = next((row for row in _rows(registry.get("external_results"))
                                 if isinstance(row, dict) and row.get("id") == dependency_id), {}) if not internal else {}
                nodes[key] = {"id": key, "kind": "internal result" if internal else "external result", "label": located.get("title") or external.get("source_identity") or ("Unlocated internal result" if internal else "External prerequisite"),
                              "reader_description": external.get("source_identity"), "location": external.get("theorem_location"),
                              "claim": use.get("needed_form", "Dependency form unavailable"),
                              "status": "not_checked" if internal else current_use.get("source_status", "not_checked"),
                              "detail_id": key, "source_ids": []}
            edges.append({"from": key, "to": route_id, "kind": "support",
                          "unit_id": unit, "use_id": use_id, "dependency_id": dependency_id,
                          "dependency_conclusion_id": conclusion_id,
                          "needed_form": use.get("needed_form"), "status": current_use.get("effective_status", "not_checked"),
                          "applicability_status": current_use.get("applicability_status", "not_checked"),
                          "compatibility_checks": current_use.get("compatibility_checks", []),
                          "prerequisite_map": current_use.get("prerequisite_map", []),
                          "source_evidence": current_use.get("source_evidence", []),
                          "statement_support": selected_supplement,
                          "statement_support_conditions": _rows(current_use.get("statement_support_conditions")),
                          "support": support})
    for result in results:
        add_route(result)
        if supplement := _dict(result.get("statement_support")):
            add_route(result, supplement)
    # A failed dependency is never evidence that a downstream statement is false.
    # Show refutation only for explicitly named, currently refuted conclusions.
    for issue in issues:
        if issue.get("invalidation_kind") != "statement_refuted" or issue.get("status") not in {"open", "deferred"}:
            continue
        targets = [results_by_key.get((ref.get("unit_id"), ref.get("conclusion_id")))
                   for ref in issue["contract_refs"]
                   if isinstance(ref, dict) and ref.get("kind") == "conclusion"]
        targets = [target for target in targets if target and target["judgments"]["statement_status"] == "refuted"]
        for target in targets:
            failure = _dict(target.get("support_failure"))
            if (failure.get("issue_id") != issue["id"] or failure.get("target") != target["claim"]
                    or not _substantive(failure.get("evidence"))):
                continue
            kind = "counterexample" if failure.get("kind") == "counterexample" else "refutation evidence"
            key = _id("refutation", issue["id"], target["id"])
            nodes[key] = {"id": key, "kind": kind, "label": "Refutation of " + target["title"],
                          "claim": failure["evidence"], "status": "refutation_evidence",
                          "detail_id": target["id"], "source_ids": target["source_ids"]}
            edges.append({"from": key, "to": target["id"], "kind": "refutation",
                          "unit_id": target["unit_id"], "issue_id": issue["id"]})
    return {"nodes": [{**node, "status_label": _label(node["status"])} for node in nodes.values()], "edges": edges,
        "convention": "Solid arrows show recorded support; red solid arrows mark defective or unavailable routes. Premises entering one argument are used jointly. Supplements remain separate from the written argument, and restricted forms show their extra conditions. A later use follows its explicitly selected form. Dashed red arrows show explicit refutation evidence; a failed route alone does not refute its statement."}


CSS = r"""
:root{color-scheme:light;--ink:#233934;--muted:#596e65;--paper:#f5f7f2;--line:#d7e0d8;--given:#315e92;--checked:#23705d;--defect:#ab3834;--uncertain:#885b12}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 'Segoe UI',Arial,sans-serif}main{max-width:1250px;margin:auto;padding:28px 32px 60px}h1,h2,h3{line-height:1.2}h1{font:42px Georgia,serif;letter-spacing:-.025em;margin:20px 0 14px}h2{font:28px Georgia,serif;margin:32px 0 16px}h3{font:22px Georgia,serif}p{margin:10px 0}a{color:#285987;text-underline-offset:3px}button,input,select{font:inherit}button,summary{cursor:pointer}button{border:1px solid var(--line);border-radius:6px;background:white;padding:7px 12px;color:var(--ink)}:focus-visible{outline:3px solid #4a80b0;outline-offset:3px}.masthead{display:flex;justify-content:space-between;gap:18px;border-bottom:1px solid var(--line);padding-bottom:15px;font-size:13px}.brand{letter-spacing:.12em;font-weight:750}.badge{border:1px solid currentColor;border-radius:5px;padding:3px 8px;font-size:12px;font-weight:700;display:inline-block}.checked{color:var(--checked)}.defect{color:var(--defect)}.uncertain{color:var(--uncertain)}.given{color:var(--given)}.muted{color:var(--muted)}.assurance{font-size:13px;max-width:1000px}.overview{background:white;border:1px solid var(--line);border-radius:12px;padding:22px 26px}.overview dl{display:grid;grid-template-columns:120px 1fr;gap:9px 20px;margin:0}.overview dt{font-weight:650}.overview dd{margin:0}.coverage{display:flex;flex-wrap:wrap;gap:8px 28px;font-size:14px;margin-top:15px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}.toolbar input,.toolbar select{max-width:100%;padding:7px;border:1px solid var(--line);border-radius:5px;background:white}.js-only{display:none}.js .js-only{display:flex}.graph-card{background:white;border:1px solid var(--line);border-radius:12px;padding:18px}.graph-scroll{overflow:auto;border-radius:6px}.graph-scroll svg{display:block;width:100%;min-width:760px}.graph-note{font-size:13px;color:var(--muted)}details{margin:14px 0;border:1px solid var(--line);border-radius:9px;background:white;break-inside:avoid}summary{padding:14px 18px;font-weight:600;overflow-wrap:anywhere}summary .badge{margin-left:12px}.detail-content{padding:2px 20px 20px}dl.judgments{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr));gap:14px;font-size:13px}.judgments dt{color:var(--muted)}.judgments dd{margin:3px 0;font-weight:650}.claim-text{font-family:Georgia,'Times New Roman',serif;font-size:19px;overflow-wrap:anywhere}.conditions{padding-left:22px}.conditions code{font-size:12px;color:var(--muted)}.repair{border-left:3px solid #9bb7a3;padding:2px 0 5px 17px;margin:18px 0}.links{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:14px}.source{font:13px/1.75 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5ef;padding:15px;border-radius:6px;max-width:100%}.source-label{font-size:13px;color:var(--muted);overflow-wrap:anywhere}.hash{font:12px Consolas,monospace;overflow-wrap:anywhere}.warning{border-left:3px solid #a97928;padding:8px 14px;background:#fff7e9}.issue{border-left:4px solid var(--defect)}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}.scope-list dt{font-weight:650;margin-top:12px}.scope-list dd{margin:3px 0 12px}.footnote{font-size:13px;color:var(--muted);margin-top:30px}.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:760px){main{padding:20px 16px 40px}h1{font-size:33px}.masthead{font-size:11px}.overview{padding:17px}.overview dl{display:block}.overview dt{margin-top:11px}.overview dd{margin:3px 0 13px}.coverage{display:block}.coverage span{display:block;margin:4px 0}dl.judgments{grid-template-columns:1fr 1fr}.graph-scroll svg{min-width:900px}.detail-content{padding:0 14px 15px}.graph-note{font-size:14px}.claim-text{font-size:18px}summary{padding:13px}.toolbar{align-items:stretch}.toolbar label{width:100%}.toolbar input{width:100%}}


.issue-path{border-left:4px solid var(--defect)}.path-step{border:1px solid var(--line);border-left:4px solid currentColor;border-radius:7px;padding:12px 16px;margin:12px 0;color:var(--ink)}.path-step.defect{border-left-color:var(--defect)}.path-step.checked{border-left-color:var(--checked)}.path-step h4{margin:0 0 10px;font-size:16px}.path-step .badge{margin-left:8px}.path-relation{padding-left:16px;font-size:14px;color:var(--muted)}.technical summary{font-size:13px;font-weight:500}.technical{background:#fafbf8}.proof-path{max-width:1000px}
.detail-content,.scope-list,.scope-list dd{min-width:0;overflow-wrap:anywhere}
.math-inline{font-size:1.08em}.math-display{display:block;max-width:100%;overflow-x:auto;padding:10px 0;margin:10px auto;font-size:1.15em}.math-fallback{font:14px Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.math-fallback-label{font:12px 'Segoe UI',Arial,sans-serif;color:var(--muted)}.source-reading{line-height:1.9;margin:12px 0;padding:12px 16px;background:#f6f8f3;border-left:3px solid #b4c8b8}.source-reading math{font-size:1.1em}.original-claim{margin:10px 0}.original-claim summary{font-size:13px;padding:8px 12px}.original-claim p{padding:0 12px}.typeset-source{margin-bottom:15px}.claim-text math{font-size:1em}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
.group-assessment{display:block;color:var(--muted);font-size:13px;font-weight:400;line-height:1.45;margin-top:5px}.result-group>.detail-content>.result{margin:10px 0}.technical-evidence>summary{font-size:17px}
.summary-findings,.summary-repairs{margin:0;padding-left:20px}.summary-findings li+li,.summary-repairs li+li{margin-top:8px}.summary-locations{font-size:13px}.summary-directions{margin:8px 0}.summary-directions>summary{font-size:14px;padding:7px 12px}.summary-directions>ul{padding-right:16px}
@media screen{.result>summary,.result-group>summary,.detail-content{overflow-x:auto}}
@media print{body{background:white;color:#111;font-size:11pt}main{max-width:none;padding:0}h1{font-size:26pt}h2{font-size:19pt}h2,h3,h4,summary{break-after:avoid-page}.toolbar,.js-only,.graph-card,.graph-card-heading{display:none!important}.overview,details{box-shadow:none}details{break-inside:auto}details::details-content{content-visibility:visible!important}details>*:not(summary),[hidden]{display:block!important}.assurance,.footnote{color:#111}.source{font-size:9pt}.badge{color:#111}.detail-content{padding:0 12px 12px}.judgments{grid-template-columns:repeat(3,1fr)!important;break-inside:avoid-page}.judgments>div{break-inside:avoid-page}a{color:#111;text-decoration:underline}a[href^='http']:after{content:' (' attr(href) ')'}}
"""


SCRIPT = r"""
(()=>{'use strict';document.documentElement.classList.add('js');
const data=JSON.parse(document.getElementById('report-data').textContent);
const byId=id=>document.getElementById(id);const records=[...document.querySelectorAll('details.result')],groups=[...document.querySelectorAll('details.result-group')];
const search=byId('result-search'),count=byId('result-count');
document.querySelectorAll('details').forEach(d=>d.open=false);
function reveal(id){const item=byId(id);if(!item)return;if(item.closest('.result-group')&&search.value){search.value='';filter();}for(let parent=item;parent;parent=parent.parentElement){parent.hidden=false;if(parent.tagName==='DETAILS')parent.open=true;}item.scrollIntoView({block:'nearest'});}
document.addEventListener('click',event=>{const a=event.target.closest('a[href^="#"]');if(a)reveal(a.getAttribute('href').slice(1));});
window.addEventListener('hashchange',()=>reveal(location.hash.slice(1)));if(location.hash)reveal(location.hash.slice(1));
function filter(){const query=search.value.toLowerCase().trim();let shown=0,shownGroups=0;groups.forEach(group=>{const titleMatch=group.querySelector(':scope>summary').textContent.toLowerCase().includes(query);let found=0;group.querySelectorAll('details.result').forEach(item=>{const match=titleMatch||item.textContent.toLowerCase().includes(query);item.hidden=!match;if(match){found++;shown++;}});group.hidden=!found;group.open=!!query&&!!found;if(found)shownGroups++;});count.textContent=shownGroups+' of '+groups.length+' manuscript results; '+shown+' conclusion records shown';}
search.addEventListener('input',filter);byId('reset').addEventListener('click',()=>{search.value='';filter();resetGraph();});
/* PROOFCHECK_GRAPH */
let printState=[];window.addEventListener('beforeprint',()=>{printState=[...document.querySelectorAll('details')].map(d=>[d,d.open]);printState.forEach(([d])=>d.open=true);});window.addEventListener('afterprint',()=>printState.forEach(([d,open])=>d.open=open));
})();
"""


def _value_html(value: Any, *, typeset: bool = True) -> str:
    """Readable disclosure for less common canonical record fields."""
    if isinstance(value, dict):
        return '<dl class="scope-list">' + ''.join(
            '<dt>' + _e(str(key).replace('_', ' ').capitalize()) + '</dt><dd>' + _value_html(item, typeset=typeset) + '</dd>'
            for key, item in value.items()
        ) + '</dl>'
    if isinstance(value, list):
        return '<ul>' + ''.join('<li>' + _value_html(item, typeset=typeset) + '</li>' for item in value) + '</ul>' if value else '<span class="muted">None recorded</span>'
    return _rich(value) if typeset else _e(value)


def _source_links(ids: list[str], sources: dict, role: str = "Source passage") -> str:
    return '<div class="links">' + "".join(
        f'<a href="#{_e(key)}">{_e(role)} · {_e(_location(sources.get(key)))}</a>' for key in ids
    ) + "</div>" if ids else '<p class="muted">Source evidence is not available for this record.</p>'


def _claim_reading(claim: Any, ids: list[str], sources: dict, *, label: str = "Exact manuscript passage",
                   prefer_source: bool = False) -> str:
    reading = [sources[key] for key in ids if key in sources and sources[key].get("status") == "locked"
               and isinstance(sources[key].get("quote"), str) and sources[key]["quote"].strip()
               and (prefer_source or math_renderer().legacy_reading_has_math(sources[key]["quote"]))]
    if not reading or (not prefer_source and math_renderer().legacy_reading_has_math(_text(claim))):
        return '<div class="claim-text">' + _rich(claim) + '</div>'
    return ('<p class="source-label">' + _e(label) + ':</p>'
            + ''.join('<div class="claim-text source-reading">' + _rich(_reading_source(row["quote"])) + '</div>' for row in reading)
            + '<details class="original-claim"><summary>Normalized audit wording</summary><p>' + _rich(claim) + '</p></details>')


def _proof_path_html(issue: dict, results: dict, sources: dict) -> str:
    path = _dict(issue.get("proof_path"))
    if issue.get("status") == "resolved" or path.get("status") == "historical":
        return '<p class="muted">This finding is historical. Its preserved evidence and recorded resolution are shown with the finding; current proof steps are not substituted.</p>'
    if path.get("status") != "available":
        return '<p class="muted">A current source-bound inference path is unavailable. Consult the recorded finding and source evidence.</p>'
    labels = _finding_labels(issue)
    parts = ['<p class="graph-note">Arrows below follow recorded consumed premises and result uses. Other joint conditions remain in the finding and result details. Support-route status alone does not refute a later statement.</p><div class="proof-path">']
    nodes = {row["id"]: row for row in path["nodes"]}
    for index, node in enumerate(path["nodes"]):
        incoming = [edge for edge in path["edges"] if edge["to"] == node["id"]]
        if incoming:
            parts.append('<div class="path-relation">')
            for edge in incoming:
                parent = nodes[edge["from"]]
                relation = ('Invokes the result whose recorded conclusion step is at ' if edge["kind"] == "dependency_use"
                            else 'Uses the premise at ' if parent["role"] == "Consumed premise" else 'Uses the inference at ')
                parts.append('<p>↳ ' + relation + '<a href="#' + _e(parent["id"]) + '">' + _e(parent["location"]) + '</a>')
                if edge["kind"] == "dependency_use":
                    status = edge.get("effective_status")
                    parts.append('. Prerequisite support: <strong class="' + _tone(status) + '">' + _e(_label(status)) + '</strong>; application to this use: ' + _e(_label(edge.get("applicability_status"))) + '.')
                    if status in {"incorrect", "gap"}:
                        parts.append(' This prerequisite cannot supply the claimed support.')
                parts.append('</p>')
                if edge.get("citation_source_ids"):
                    parts.append(_source_links(edge["citation_source_ids"], sources, "Cited result use"))
            parts.append('</div>')
        # Keep lengthy paths available without making every issue's first view
        # large. These disclosures contain complete nodes, never invented edges.
        if index == 8:
            parts.append('<details class="path-continuation" open><summary>Continue the recorded support path</summary><div class="detail-content">')
        role = labels["role"] if node["id"] == path.get("origin_id") else node["role"]
        parts.append('<article class="path-step ' + _tone(node["status"]) + '" id="' + _e(node["id"]) + '"><h4>'
                     + _e(role + " · " + node["location"]) + ' <span class="badge">' + _e(_label(node["status"])) + '</span></h4>')
        parts.append(_claim_reading(node["claim"], node["source_ids"], sources, prefer_source=True))
        parts.append(_source_links(node["source_ids"], sources, role))
        if node["id"] == path.get("origin_id"):
            parts.append('<p><a href="#' + _e(issue["anchor"]) + '">' + _e(labels["explanation"]) + '</a></p>')
        for result_id in node["result_ids"]:
            result = results[result_id]
            parts.append('<p><a href="#' + _e(result_id) + '">' + _e(result["title"]) + '</a>. Statement: ' + _e(_label(result["judgments"]["statement_status"])) + '.</p>')
        parts.append('</article>')
    if len(path["nodes"]) > 8:
        parts.append('</div></details>')
    parts.append('</div>')
    return ''.join(parts)


def _svg(graph: dict) -> str:
    return _presentation_module("graph").render_graph(graph)


def _repair_direction_html(direction: dict) -> str:
    target = '; '.join('<a href="#' + _e(row["anchor"]) + '">' + _e(row["label"]) + '</a>'
                      for row in direction["target_links"]) or _e(direction["target"])
    return ('<li><a href="#' + _e(direction["anchor"]) + '">' + _e(direction["label"]) + '</a> at '
            + target + ': ' + _rich(direction["cost"]) + '. ' + _e(direction["verification"]) + '. '
            + ' '.join('<a href="#' + _e(anchor) + '">Finding</a>' for anchor in direction["issue_anchors"]) + '.</li>')


def render_report(projection: dict) -> str:
    """Render every semantic record; interaction only narrows navigation."""
    p = _prepare_report_views(projection)
    overview = p["overview"]
    sources_by_id = {source["id"]: source for source in p["sources"]}
    results_by_id = {result["id"]: result for result in p["results"]}
    issues_by_id = {issue["id"]: issue for issue in p["issues"]}
    audit, release, coverage = p["audit"], p["release"], p["coverage"]
    context = _dict(p.get("report_context"))
    title = context.get("title", "Proofcheck report")
    state = release["status"]
    summary_details = p["summary_details"]
    parts = [
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{_e(state)} | {_e(title)}</title><style>{CSS}{_presentation_module("graph").CSS}</style></head><body><main>',
        f'<header class="masthead"><span class="brand">PROOFCHECK</span><span>{_e(audit["depth"])} scope <span class="badge {_tone("not_checked" if state != "FINAL" else "established")}">{_e(state)}</span></span></header>',
        f'<h1>{_e(title)}</h1><p class="assurance">{_e(ASSURANCE)}</p>',
        ('<p class="assurance">Snapshot finalized at ' + _e(release.get("finalized_at") or "time not recorded") + '. Current workspace freshness is checked by delivery-check.</p>') if state == "FINAL" else '<p class="warning">Working report. No overall judgment has been released. See <a href="#scope">scope and recorded diagnostics</a> for the available evidence and known limits.</p>',
        '<section class="overview" aria-label="Audit summary"><dl>',
    ]
    for key, label in (("overall_judgment", "Overall finding"), ("main_reason", "Key issues"), ("impact", "Impact"), ("repair_outlook", "Repair outlook")):
        parts.append(f'<dt>{label}</dt><dd>')
        if key == "main_reason" and summary_details["featured_findings"]:
            if not summary_details["source_current"]:
                parts.append('<p>Recorded findings; current source evidence is unavailable.</p>')
            parts.append('<ul class="summary-findings">')
            for finding in summary_details["featured_findings"]:
                parts.append('<li><a href="#' + _e(finding["anchor"]) + '">' + _e(finding["label"]) + '</a> at <a href="#' + _e(finding["location_anchor"]) + '">' + _e(finding["location"]) + '</a>: ' + _rich(finding["text"]))
                if finding["result_links"]:
                    parts.append(' <span class="summary-locations">Results: ' + '; '.join('<a href="#' + _e(link["anchor"]) + '">' + _rich(link["label"]) + '</a>' for link in finding["result_links"]) + (f'; {finding["additional_results"]} more in the finding' if finding["additional_results"] else '') + '.</span>')
                parts.append('</li>')
            parts.append('</ul>')
            if summary_details["remaining_active_findings"]:
                parts.append('<p>' + str(summary_details["remaining_active_findings"]) + ' additional active ' + ('finding' if summary_details["remaining_active_findings"] == 1 else 'findings') + ' in the <a href="#findings">complete findings list</a>.</p>')
        elif key == "repair_outlook":
            if summary_details["featured_repair_directions"]:
                parts.append('<ul class="summary-repairs">' + ''.join(_repair_direction_html(row) for row in summary_details["featured_repair_directions"]) + '</ul>')
            parts.append(_rich(summary_details["repair_notes"]))
        else:
            parts.append(_rich(p["summary"][key]))
        if key == "impact":
            links = summary_details["impact_links"]
            parts.append('<div class="links">' + ''.join('<a href="#' + _e(link["anchor"]) + '">' + _rich(link["label"]) + '</a>' for link in links) + '<a href="#results">All result judgments</a></div>')
        if key == "repair_outlook":
            if len(summary_details["repair_directions"]) > len(summary_details["featured_repair_directions"]):
                parts.append('<details class="summary-directions"><summary>All recorded repair directions</summary><ul>')
                for direction in summary_details["repair_directions"]:
                    parts.append(_repair_direction_html(direction))
                parts.append('</ul></details>')
            parts.append(' <a href="#findings">Full findings, repairs, and rechecks</a>.')
        parts.append('</dd>')
        if key == "overall_judgment" and context.get("essential_scope"):
            parts.append('<dt>Essential scope</dt><dd class="essential-scope">' + _rich(context["essential_scope"]) + '</dd>')
    parts.append('</dl><div class="coverage">' + ''.join('<span>' + _e(text) + '</span>' for text in summary_details["coverage_text"]) + '</div></section>')
    parts.append('<h2 id="proof-structure" class="graph-card-heading">Proof structure</h2><section class="graph-card">')
    parts.append(f'<p class="graph-note" id="graph-convention">{_e(overview["convention"])}</p><p class="graph-note"><a href="#scope">Audit scope, exclusions, and limits</a>. Hover or focus for the statement; press Space or tap to pin it.</p>')
    parts.append('<div class="toolbar js-only"><label for="graph-mode">View</label><select id="graph-mode"><option value="overview" selected>Paper overview</option><option value="detail">Detailed proof</option></select><label for="graph-focus" id="graph-focus-label">Focus</label><select id="graph-focus"><option value="__paper_overview__" selected>All results in audit scope</option>')
    for group in p["result_groups"]:
        parts.append(f'<option value="{_e(group["id"])}">{_e(group["title"])}</option>')
    parts.append('</select><button id="graph-more" type="button">Show next nodes</button></div><div id="graph-canvas" class="graph-scroll" tabindex="0" role="region" aria-label="Proof graph; scroll vertically or horizontally">')
    parts.append(_svg(overview))
    parts.append('</div><p id="graph-count" class="graph-note" aria-live="polite">' + _e(_presentation_module("graph").page_note(overview)) + '</p>')
    parts.append(_presentation_module("graph").render_legend(overview))
    parts.append(_presentation_module("graph").render_previews(overview, rich=_rich, exact_graph=p["graph"]))
    parts.append(_presentation_module("graph").render_previews(p["graph"], rich=_rich, include_dialog=False))
    if p.get("display_notes"):
        parts.append('<details class="graph-display-notes"><summary>Manuscript label notes</summary><ul>' + ''.join('<li>' + _e(note) + '</li>' for note in p["display_notes"]) + '</ul></details>')
    parts.append('</section>')
    for issue in p["issues"]:
        path = _dict(issue.get("proof_path"))
        failed = next((row for row in _rows(path.get("nodes")) if row.get("id") == path.get("origin_id")), {})
        path_label = _finding_labels(issue)["inspect"] + " · " + failed.get("location", "Preserved finding")
        parts.append('<details class="issue-path" id="' + _e(issue["anchor"] + "-path") + '" open><summary>' + _e(path_label) + '</summary><div class="detail-content"><p>' + _rich(_brief(issue["summary"])) + '</p>')
        parts.append(_proof_path_html(issue, results_by_id, sources_by_id) + '</div></details>')
    parts.append('<h2 id="results">Results and impact</h2><div class="toolbar js-only"><label for="result-search">Find a result <input id="result-search" type="search" placeholder="Result, claim, or status"></label><button id="reset" type="button">Reset view</button>')
    parts.append(f'<span id="result-count" aria-live="polite">{len(p["result_groups"])} manuscript results; {len(p["results"])} conclusion records</span></div>')
    issue_anchors = {issue["id"]: issue["anchor"] for issue in p["issues"]}
    nodes = {node["id"]: node for node in p["graph"]["nodes"]}
    for group, result in [(group, results_by_id[key]) for group in p["result_groups"] for key in group["result_ids"]]:
        if result["id"] == group["result_ids"][0]:
            parts.append(f'<details class="result-group" id="{_e(group["id"])}"><summary>{_rich(group["title"])} <span class="group-assessment">{_e(group["assessment_summary"])}</span></summary><div class="detail-content">')
            parts.append('<p class="source-label">' + _e(group["statement_label"]) + ':</p><div class="claim-text">' + _rich(group["claim"]) + '</div>')
            parts.append(_source_links(group["statement_source_ids"], sources_by_id, "Manuscript statement"))
            if group["associated_result_ids"]:
                parts.append('<p class="source-label">Associated assertions are separately anchored claims. Their checks do not redefine the formal result statement.</p>')
        status = result["judgments"]["statement_status"]
        parts.append(f'<details class="result" id="{_e(result["id"])}"><summary>{_rich(result["title"])} <span class="badge {_tone(status)}">{_e(_label(status))}</span></summary><div class="detail-content">')
        if result["id"] in group["associated_result_ids"]:
            parts.append('<p class="source-label">Separately anchored assertion associated with this result.</p>')
        parts.append('<p class="js-only"><a href="#proof-structure" data-graph-detail="' + _e(result["id"]) + '">Inspect the detailed proof for this conclusion</a></p>')
        if result.get("display_pdf_page"):
            parts.append('<p class="source-label">Reviewed manuscript heading: ' + _e(result["display_label"]) + ', PDF page ' + _e(result["display_pdf_page"]) + '.</p>')
        if result.get("paper_location"):
            parts.append('<p class="source-label">Exact transcription location: ' + _e(result["location"]) + '.</p>')
        reading_sources = [sources_by_id[key] for key in result.get("conclusion_source_ids", [])
                           if key in sources_by_id and sources_by_id[key]["status"] == "locked"
                           and math_renderer().legacy_reading_has_math(sources_by_id[key].get("quote") or "")]
        if reading_sources and not math_renderer().legacy_reading_has_math(_text(result["claim"])):
            parts.append('<p class="source-label">Stated conclusion, typeset from the linked manuscript excerpt:</p>')
            for source in reading_sources:
                parts.append('<div class="claim-text source-reading">' + _source_reading(source) + '</div>')
            parts.append(_source_links([source["id"] for source in reading_sources], sources_by_id, "Stated conclusion"))
            parts.append('<details class="original-claim"><summary>Normalized audit wording</summary><p>' + _e(result["claim"]) + '</p></details>')
        else:
            parts.append(f'<div class="claim-text">{_rich(result["claim"])}</div>')
        parts.append(f'<p class="source-label">Record availability: {_e(result["availability"])}.</p><dl class="judgments">')
        for field in JUDGMENT_FIELDS:
            parts.append(f'<div><dt>{FIELD_LABELS[field]}</dt><dd>{_e(_label(result["judgments"][field]))}</dd></div>')
        parts.append('</dl>')
        supplement = _dict(result.get("statement_support"))
        if supplement:
            parts.append('<h3>Supplemental statement support</h3><p>A separate argument recorded during review. The written argument retains its recorded judgment.</p>')
            parts.append('<p>Supplement review: ' + _e(_label(supplement.get("acceptance", "pending"))) + '. Usable support: ' + _e(_label(_supplement_status(supplement))) + '.</p>')
            extra_conditions = _strings(supplement.get("extra_conditions"))
            if extra_conditions:
                parts.append('<p>Additional conditions of this supplemental claim:</p>' + _value_html(extra_conditions))
            elif supplement.get("acceptance") == "accepted":
                parts.append('<p>This accepted supplement addresses the unchanged statement under its original conditions.</p>')
            parts.append('<div class="claim-text">' + _rich(supplement.get("claim", result["claim"])) + '</div>')
            if supplement.get("evidence"):
                parts.append('<p>' + _rich(supplement["evidence"]) + '</p>')
            if supplement.get("reason"):
                parts.append('<p>' + _rich(supplement["reason"]) + '</p>')
            parts.append(_source_links(_strings(supplement.get("source_ids")), sources_by_id, "Supplement source anchor"))
        parts.append('<h3>Statement scope and conditions</h3><ul class="conditions">')
        for condition in result["conditions"]:
            parts.append(f'<li>{_rich(condition["value"])}</li>')
        parts.append('</ul>' if result["conditions"] else '</ul><p>Conditions have not been normalized for this record.</p>')
        incoming = [edge for edge in p["graph"]["edges"] if edge["to"] == result["id"] and edge["kind"] == "support"]
        parts.append('<h3>Support recorded for this result</h3><ul>')
        for edge in incoming:
            parent = nodes[edge["from"]]
            parts.append(f'<li><a href="#{_e(parent["detail_id"])}">{_e(parent["label"])}</a></li>')
        parts.append('</ul>')
        if not incoming:
            parts.append('<p>No support edges are available in this view. This does not establish that the result has no premises.</p>')
        refutations = [edge for edge in p["graph"]["edges"] if edge["to"] == result["id"] and edge["kind"] == "refutation"]
        if refutations:
            parts.append('<h3>Refutation evidence</h3><ul>')
            for edge in refutations:
                evidence = nodes[edge["from"]]
                parts.append(f'<li>{_e(evidence["kind"].capitalize())}: {_e(evidence["label"])}. This evidence addresses the statement itself.<p>{_rich(evidence["claim"])}</p></li>')
            parts.append('</ul>')
        check = result["independent_check"]
        parts.append('<h3>Independent review</h3><p>' + _e(_label(check.get("status", "not_checked"))) + '; ' + _e(_label(check.get("independence_level", "not_checked"))) + '.</p><details class="technical"><summary>Review reasoning and technical records</summary><div class="detail-content">')
        if result.get("manuscript_label"):
            parts.append('<p class="source-label">Manuscript label: <code>' + _e(result["manuscript_label"]) + '</code>.</p>')
        if check:
            parts.append(f'<p>Initial challenger verdict: {_e(_label(check.get("challenger_verdict")))}. Reconciled verdict: {_e(_label(check.get("reconciled_verdict")))}.</p>')
            if check.get("disagreements"):
                parts.append('<p>Disagreements:</p>' + _value_html(check["disagreements"]))
            if check.get("resolution"):
                parts.append('<p>Reconciliation: ' + _rich(check["resolution"]) + '</p>')
        initial = _dict(result.get("initial_review"))
        if initial.get("status") == "recorded":
            parts.append('<p><strong>Initial assessment of this conclusion:</strong> written argument: ' + _e(_label(initial.get("argument_status") or "not_recorded")) + '; statement: ' + _e(_label(initial.get("statement_status") or "not_recorded")) + '; recorded verdict: ' + _e(_label(initial.get("verdict"))) + '.</p>')
            parts.append('<p>' + _rich(initial.get("decisive_reason")) + '</p>' + _source_links(initial.get("source_ids", []), sources_by_id, "Preserved review source"))
            if not initial.get("argument_status") or not initial.get("statement_status"):
                parts.append('<p class="source-label">This historical response did not record both judgment dimensions. No missing judgment is inferred from its prose.</p>')
            snapshot = _dict(initial.get("primary_snapshot"))
            primary = next((r for r in _rows(snapshot.get("conclusions")) if isinstance(r, dict) and r.get("conclusion_id") == result["conclusion_id"]), None)
            if primary:
                parts.append('<p><strong>Primary judgment before reconciliation:</strong></p>' + _value_html(primary))
            parts.append('<div class="links">' + ''.join(f'<a href="{_e(link["href"])}">{_e(link["label"])}</a>' for link in initial.get("artifacts", [])) + '</div>')
        parts.append(_value_html({"Unit": result["unit_id"], "Conclusion": result["conclusion_id"], "Source environment": result.get("source_environment"), "Condition references": result["conditions"], "Selected support": result["support"]}, typeset=False) + '</div></details>')
        parts.append('<div class="links">' + "".join(f'<a href="#{_e(issue_anchors[issue])}">Finding: {_e(_brief(issues_by_id[issue]["summary"]))}</a>' for issue in result["issue_ids"] if issue in issue_anchors) + '</div>')
        parts.append(_source_links(result.get("statement_source_ids", result["source_ids"]), sources_by_id, "Statement") + '</div></details>')
        if result["id"] == group["result_ids"][-1]:
            parts.append('</div></details>')

    auxiliary = [node for node in p["graph"]["nodes"] if node["id"] not in {r["id"] for r in p["results"]} and node["detail_id"] == node["id"]]
    if auxiliary:
        parts.append('<details id="premises" class="technical-evidence"><summary>Assumptions and proof inputs (' + str(len(auxiliary)) + ' records)</summary><div class="detail-content">')
        for node in auxiliary:
            parts.append(f'<details id="{_e(node["detail_id"])}"><summary>{_e(node["label"])}</summary><div class="detail-content">' + _claim_reading(node["claim"], node["source_ids"], sources_by_id) + f'<p>Recorded status: {_e(_label(node["status"]))}.</p>')
            if node.get("reason"):
                parts.append('<p>' + _rich(node["reason"]) + '</p>')
            if node.get("conditions"):
                parts.append('<p>Additional conditions of this restricted form:</p>' + _value_html(node["conditions"]))
            if node.get("result_id"):
                result = results_by_id[node["result_id"]]
                parts.append('<p><a href="#' + _e(result["id"]) + '">Original statement and written argument: ' + _rich(result["title"]) + '</a>. Supplement review: ' + _e(_label(node.get("acceptance", "pending"))) + '.</p>')
            incoming = [edge for edge in p["graph"]["edges"] if edge["to"] == node["id"] and edge["kind"] == "support"]
            if incoming:
                parts.append('<p>Inputs used jointly in this argument:</p><ul>')
                for edge in incoming:
                    parent = nodes[edge["from"]]
                    parts.append(f'<li><a href="#{_e(parent["detail_id"])}">{_rich(parent["label"])}</a>' + (f'. Effective use: {_e(_label(edge["status"]))}; application: {_e(_label(edge["applicability_status"]))}' if "use_id" in edge else ''))
                    if edge.get("statement_support"):
                        parts.append('<p>This use selects the supplemental form. Its additional conditions are checked at this application.</p>')
                        for condition in _rows(edge.get("statement_support_conditions")):
                            if isinstance(condition, dict):
                                parts.append('<p>' + _rich(condition.get("condition")) + ' · ' + _e(_label(condition.get("status", "not_checked"))) + '.</p><p>' + _rich(condition.get("evidence")) + '</p>')
                                if condition.get("source_ids"):
                                    parts.append(_source_links(condition["source_ids"], sources_by_id, "Condition checked at this application"))
                    parts.append('</li>')
                parts.append('</ul>')
            parts.append(_source_links(node["source_ids"], sources_by_id, "Conclusion step" if node["kind"] == "argument" else "Given condition"))
            if node.get("technical_reference"):
                parts.append('<details class="technical"><summary>Technical reference</summary><div class="detail-content">' + _value_html(node["technical_reference"], typeset=False) + '</div></details>')
            parts.append('</div></details>')
        parts.append('</div></details>')

    parts.append('<h2 id="findings">Findings and repairs</h2>')
    if not p["issues"]:
        parts.append('<p>No issues are recorded in the available issue log. Consult completion and remaining-work information before interpreting this absence.</p>')
    for issue in p["issues"]:
        labels = _finding_labels(issue)
        parts.append(f'<details class="issue" id="{_e(issue["anchor"])}" open><summary>{_rich(issue["summary"])}</summary><div class="detail-content">')
        parts.append(f'<p>Finding: {_e(_label(issue["finding_status"]))}. Status: {_e(_label(issue["status"]))}. Confidence: {_e(_label(issue["confidence"]))}.</p>')
        path = _dict(issue.get("proof_path"))
        failed = next((row for row in _rows(path.get("nodes")) if row.get("id") == path.get("origin_id")), {})
        if issue.get("status") == "resolved":
            failed = {}
        if failed:
            parts.append('<p><a href="#' + _e(issue["anchor"] + '-path') + '">' + _e(labels["inspect"] + ' · ' + failed["location"]) + '</a></p><h3>Passage under review</h3>')
            parts.append(_claim_reading(failed["claim"], failed["source_ids"], sources_by_id))
            parents = [row for row in _rows(path.get("nodes")) if any(edge["from"] == row["id"] and edge["to"] == failed["id"] for edge in _rows(path.get("edges")))]
            parts.append('<h3>Premises consumed by this inference</h3>')
            for parent in parents:
                parts.append('<p><strong>' + _e(parent["role"] + " · " + parent["location"]) + '</strong>. Recorded step status: ' + _e(_label(parent["status"])) + '.</p>')
                parts.append(_claim_reading(parent["claim"], parent["source_ids"], sources_by_id))
            other_premises = [premise.get("claim") for premise in failed.get("premises", []) if _dict(premise.get("origin")).get("kind") != "prior_step"]
            if other_premises:
                parts.append(_value_html(other_premises))
        for failure in issue["failures"]:
            heading = labels["heading"]
            parts.append(f'<h3>{heading}</h3>')
            if not failed:
                parts.append('<p><strong>Recorded assertion:</strong> ' + _rich(failure["claim"]) + '</p><p><strong>Recorded premises:</strong> ' + _rich(failure["premises"]) + '</p>')
            parts.append(f'<p>{_rich(failure["evidence"]) if _substantive(failure["evidence"]) else "The recorded finding evidence is unavailable."}</p>')
        parts.append('<h3>Results affected</h3><ul>')
        for result_id in issue["affected_result_ids"]:
            result = results_by_id[result_id]
            refuted = any(edge.get("issue_id") == issue["id"] and edge["kind"] == "refutation" and edge["to"] == result_id for edge in p["graph"]["edges"])
            effect = 'Directly refuted by evidence for this statement.' if refuted else 'Written argument: ' + _label(result["judgments"]["argument_status"]) + '; statement: ' + _label(result["judgments"]["statement_status"]) + '. Support status alone does not establish falsity.'
            parts.append('<li><a href="#' + _e(result_id) + '">' + _e(result["title"]) + '</a>. ' + _e(effect) + '</li>')
        parts.append('</ul>')
        if issue.get("resolution") or issue.get("current_resolution"):
            parts.append('<h3>Recorded resolution and completed rechecks</h3><p>' + _rich(issue.get("resolution")) + '</p>')
            parts.append(_value_html({"Current mapping and verification": issue.get("current_resolution"), "Completed recheck evidence": issue.get("recheck_evidence"), "Rechecked units": issue.get("rechecked_units"), "Rechecked dependency uses": issue.get("rechecked_dependency_uses")}))
        parts.append(_source_links(issue["source_ids"], sources_by_id, labels["evidence"]))
        parts.append('<h3>Repair options and scientific cost</h3>')
        for index, repair in enumerate(issue["repairs"], 1):
            rechecks = [result for result in p["results"] if result["unit_id"] in repair["required_rechecks"]]
            recheck_links = '; '.join('<a href="#' + _e(result["id"]) + '">' + _e(result["title"]) + '</a>' for result in rechecks)
            parts.append(f'<article class="repair" id="{_e(_id("repair", issue["id"], index))}"><h4>Option {index}: {_e(_label(repair["action"]))}</h4><p>{_rich(repair["proposal"])}</p><p><strong>Scientific cost:</strong> {_rich(repair["scientific_cost"])}.</p><p><strong>Verification:</strong> {_e(_label(repair["verification_status"]))}. <strong>Required rechecks:</strong> {recheck_links or "See technical records for unavailable or unlocated rechecks"}.</p></article>')
            if repair.get("target_source_ids"):
                parts.append(_source_links(repair["target_source_ids"], sources_by_id, "Proposed repair target"))
        if not issue["repairs"]:
            parts.append('<p>No concrete repair option is recorded.</p>')
        search = issue["repair_search"]
        if search:
            parts.append('<h3>Recorded repair search</h3><ul>')
            for strategy in _rows(search.get("strategies")):
                if isinstance(strategy, dict):
                    parts.append(f'<li><strong>{_e(strategy.get("name"))}:</strong> {_rich(strategy.get("attempt"))} Outcome: {_e(_label(strategy.get("outcome")))}. {_rich(strategy.get("evidence"))}</li>')
            parts.append('</ul><p>Search conclusion: ' + _e(_label(search.get("conclusion"))) + '. This records the bounded search, not impossibility of other repairs.</p>')
        if issue["resolution_evidence_needed"]:
            parts.append('<p>Evidence still required: ' + _e(" ".join(issue["resolution_evidence_needed"])) + '</p>')
        parts.append('<details class="technical"><summary>Finding technical records</summary><div class="detail-content">' + _value_html({"Issue ID": issue["id"], "Severity": issue["severity"], "Load bearing": issue["load_bearing"], "Origin": issue["origin_ref"], "Failure records": issue["failures"], "Repair targets and rechecks": [{"target_ref": repair.get("target_ref"), "required_rechecks": repair["required_rechecks"]} for repair in issue["repairs"]]}, typeset=False) + '</div></details></div></details>')

    parts.append('<details id="source-evidence" class="technical-evidence"><summary>Exact source evidence (' + str(len(p["sources"])) + ' passages)</summary><div class="detail-content"><p class="muted">Excerpts are embedded for offline reading. Original-file links require the accompanying audit folder.</p>')
    for source in p["sources"]:
        start, end = source["start_line"], source["end_line"]
        location = _location(source)
        excerpt = source["quote"]
        numbered = "\n".join(f"{start + i:>4}  {line}" for i, line in enumerate(excerpt.splitlines())) if excerpt is not None and start is not None else excerpt
        parts.append(f'<details id="{_e(source["id"])}"><summary>{_e(location)}</summary><div class="detail-content"><p class="source-label">Evidence status: {_e(source["status"])}.</p>')
        if isinstance(excerpt, str) and math_renderer().legacy_reading_has_math(excerpt):
            parts.append('<div class="source-reading typeset-source" aria-label="Source reading view">' + _source_reading(source) + '</div><p class="source-label">Exact source with line numbers:</p>')
        parts.append(f'<pre class="source">{_e(numbered if numbered is not None else "The locked source is unavailable or changed. This view does not substitute current text.")}</pre>')
        if source.get("bundle_href"):
            parts.append(f'<p><a href="{_e(source["bundle_href"])}">Open bundled source file</a> (requires the audit folder)</p>')
        parts.append(f'<p class="hash">Source identity: {_e(source.get("sha256"))}</p></div></details>')
    parts.append('</div></details>')

    parts.append('<h2 id="scope">Scope and assurance</h2><p>' + _e(ASSURANCE) + '</p><details open id="scope-records"><summary>Scope, limitations, and source identity</summary><div class="detail-content"><dl class="scope-list">')
    scope_values = {
        "Depth": audit["depth"], "Scope review": audit["scope_status"],
        "Target units": audit["target_units"], "In-scope units": audit["in_scope_units"],
        "Explicit exclusions": audit["excluded_units"], "Source or parser limitations": audit["limits"],
        "Missing units": coverage["missing_units"], "Invalid or stale units": coverage["invalid_units"],
        "Units with unresolved conclusion counts": coverage["unresolved_conclusion_units"],
        "Source revision": audit["source_revision"], "Protocol": audit["protocol"],
        "Source provenance": audit.get("source_provenance"), "Locked source files": audit.get("source_files"),
        "Mathematical display": p["math_rendering"],
    }
    for label, value in scope_values.items():
        note = _source_review_note(value) if label == "Source provenance" else ""
        reading_note = '<p class="source-label">' + _e(note) + '</p>' if note else ""
        parts.append(f'<dt>{_e(label)}</dt><dd>{reading_note}{_value_html(value, typeset=False)}</dd>')
    parts.append('</dl></div></details>')
    author_context = {key: value for key, value in context.items() if key in AUTHOR_CONTEXT_FIELDS and key not in {"title", "essential_scope"}}
    historical_context = {key: value for key, value in context.items() if key not in AUTHOR_CONTEXT_FIELDS and key != "manuscript_labels"}
    if author_context or historical_context:
        parts.append('<details open id="author-context"><summary>Additional authored notes and historical context</summary><div class="detail-content"><p>These notes are authored prose. The reviewed scope and judgments are recorded above.</p>')
        if author_context:
            parts.append(_value_html(author_context))
        if historical_context:
            parts.append('<h3>Historical or additional prose</h3>' + _value_html(historical_context))
        parts.append('</div></details>')
    if p["diagnostics"]:
        parts.append('<h3>Remaining work and unavailable evidence</h3><ul>')
        parts.extend('<li>' + _e(item) + '</li>' for item in p["diagnostics"])
        parts.append('</ul>')
    if p["dependency_edges"]:
        parts.append('<details class="technical" id="dependency-records"><summary>Exact dependency-use judgments</summary><div class="detail-content"><div class="table-wrap"><table><thead><tr><th>Use</th><th>Prerequisite</th><th>Dependent</th><th>Source status</th><th>Application status</th><th>Effective status</th></tr></thead><tbody>')
        for edge in p["dependency_edges"]:
            parts.append('<tr>' + ''.join(f'<td>{_e(edge.get(field))}</td>' for field in ("use_id", "dependency_id", "dependent_unit", "source_status", "applicability_status", "effective_status")) + '</tr>')
        parts.append('</tbody></table></div>')
        for edge in p["dependency_edges"]:
            parts.append(f'<h3>{_e(edge.get("dependent_unit"))}: {_e(edge.get("use_id"))}</h3>')
            parts.append(_value_html({key: edge.get(key) for key in ("compatibility_checks", "prerequisite_map", "source_evidence") if edge.get(key)}))
        parts.append('</div></details>')
    if p["dependency_registry"].get("external_results"):
        parts.append('<details open id="external-results"><summary>External results and their exact applicability context</summary><div class="detail-content"><p>These are the recorded external contracts and evidence locators. Their application judgments are shown separately from their availability.</p>')
        parts.append(_value_html(p["dependency_registry"]["external_results"]) + '</div></details>')
    if p.get("method_interfaces"):
        parts.append('<details open id="method-interfaces"><summary>Method and implementation scope</summary><div class="detail-content">' + _value_html(p["method_interfaces"]) + '</div></details>')
    if p.get("global_checks"):
        parts.append('<details class="technical" id="global-checks"><summary>Global consistency checks</summary><div class="detail-content">' + _value_html(p["global_checks"]) + '</div></details>')
    parts.append('<p class="footnote">This self-contained HTML is a generated view of canonical audit records. Navigation, focusing, and printing do not change a judgment. Saved reports describe their recorded snapshot; use delivery-check to assess current workspace freshness.</p>')
    payload = _json(p).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    script = SCRIPT.replace("/* PROOFCHECK_GRAPH */", _presentation_module("graph").SCRIPT)
    parts.append(f'</main><script type="application/json" id="report-data">{payload}</script><script>{script}</script></body></html>\n')
    return "".join(parts)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[str] = []
        self.remote: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        for field in ("href", "src"):
            value = values.get(field)
            if not value:
                continue
            if value.startswith("#"):
                self.references.append(value[1:])
            elif field == "src" or re.match(r"(?i)^(?:https?:)?//|^(?:javascript|data):", value):
                self.remote.append(value)


def validate_html(value: str, projection: dict) -> list[str]:
    """Validate the complete deterministic document, not only embedded JSON."""
    errors = []
    if value != render_report(projection):
        errors.append("HTML differs from the canonical deterministic report rendering.")
    parser = _Links()
    try:
        parser.feed(value)
    except (ValueError, TypeError) as exc:
        return [*errors, f"Cannot parse report HTML: {exc}"]
    identifiers = set(parser.ids)
    if len(identifiers) != len(parser.ids):
        errors.append("HTML contains duplicate element IDs.")
    missing = sorted(set(parser.references) - identifiers)
    if missing:
        errors.append("HTML has unresolved evidence or result links: " + ", ".join(missing))
    if parser.remote:
        errors.append("HTML requires a remote resource or contains an executable resource link.")
    return errors


def render_markdown(projection: dict) -> str:
    """Accessible optional text export of the same complete report projection."""
    p = _prepare_report_views(projection)
    details = p["summary_details"]
    def link(anchor: str, label: str) -> str:
        return '[' + label.replace('[', '\\[').replace(']', '\\]') + '](#' + anchor + ')'
    def direction_row(direction: dict) -> str:
        target = '; '.join(link(row["anchor"], row["label"]) for row in direction["target_links"]) or direction["target"]
        return ('- ' + link(direction["anchor"], direction["label"]) + ' at ' + target + ': '
                + direction["cost"] + '. ' + direction["verification"] + '. '
                + ' '.join(link(anchor, 'Finding') for anchor in direction["issue_anchors"]) + '.')
    lines = [f'# {p["release"]["status"]} Proofcheck report', '', ASSURANCE, '']
    for key, value in p["summary"].items():
        label = {"overall_judgment": "Overall finding", "main_reason": "Key issues"}.get(key, key.replace("_", " ").capitalize())
        lines.append(f'**{label}:**')
        lines.append('')
        if key == "main_reason" and details["featured_findings"]:
            if not details["source_current"]:
                lines.extend(['Recorded findings; current source evidence is unavailable.', ''])
            for finding in details["featured_findings"]:
                row = '- ' + link(finding["anchor"], finding["label"]) + ' at ' + link(finding["location_anchor"], finding["location"]) + ': ' + finding["text"]
                if finding["result_links"]:
                    row += ' Results: ' + '; '.join(link(r["anchor"], r["label"]) for r in finding["result_links"]) + (f'; {finding["additional_results"]} more in the finding' if finding["additional_results"] else '') + '.'
                lines.append(row)
            if details["remaining_active_findings"]:
                lines.extend(['', str(details["remaining_active_findings"]) + ' additional active ' + ('finding' if details["remaining_active_findings"] == 1 else 'findings') + ' in the ' + link('findings', 'complete findings list') + '.'])
        elif key == "repair_outlook":
            lines.extend(direction_row(row) for row in details["featured_repair_directions"])
            if details["repair_notes"]:
                lines.extend(['', details["repair_notes"]])
        else:
            lines.append(value)
        if key == "overall_judgment" and _dict(p.get("report_context")).get("essential_scope"):
            lines.extend(['', '**Essential scope:** ' + p["report_context"]["essential_scope"]])
        if key == "impact":
            lines.extend(['', '; '.join([*(link(row["anchor"], row["label"]) for row in details["impact_links"]), link('results', 'All result judgments')])])
        if key == "repair_outlook":
            if len(details["repair_directions"]) > len(details["featured_repair_directions"]):
                lines.extend(['', '<details><summary>All recorded repair directions</summary>', ''])
                for direction in details["repair_directions"]:
                    lines.append(direction_row(direction))
                lines.extend(['', '</details>'])
            lines.extend(['', link('findings', 'Full findings, repairs, and rechecks') + '.'])
        lines.append('')
    lines.extend(['; '.join(details["coverage_text"]), '', '<a id="results"></a>', '## Results and impact', ''])
    first_members = {g["result_ids"][0]: g for g in p["result_groups"] if g["result_ids"]}
    for result in p["results"]:
        if result["id"] in first_members:
            lines.extend(['<a id="' + _e(first_members[result["id"]]["id"]) + '"></a>', ''])
        lines.extend(['<a id="' + _e(result["id"]) + '"></a>', ''])
        lines.extend([f'### {result["title"]}', '', str(result["claim"]), ''])
        for key, value in result["judgments"].items():
            lines.append(f'- {FIELD_LABELS[key]}: {_label(value)}')
        lines.extend(['', 'Statement scope and conditions:', ''])
        lines.extend(f'- {row["pointer"]}: {_text(row["value"])}' for row in result["conditions"])
        lines.extend(['', 'Selected support: ' + _text(result["support"]), '', 'Support reasoning: ' + _text(result.get("support_reason")), '',
                      'Independent review: ' + _text(result["independent_check"]), '', 'Initial assessment of this conclusion: ' + _text(result.get("initial_review")), ''])
        if supplement := _dict(result.get("statement_support")):
            lines.extend(['Supplemental statement support (the written argument retains its own judgment):', '',
                          'Usable support: ' + _label(_supplement_status(supplement)), '', _text(supplement), ''])
    lines.extend(['<a id="findings"></a>', '## Findings and repairs', ''])
    for issue in p["issues"]:
        lines.extend(['<a id="' + _e(issue["anchor"]) + '"></a>', '<a id="' + _e(issue["anchor"] + '-path') + '"></a>', ''])
        lines.extend([f'### {issue["id"]} [{issue["severity"]}]: {issue["summary"]}', '',
                      f'Finding: {_label(issue["finding_status"])}; status: {issue["status"]}; confidence: {issue["confidence"]}; load-bearing: {issue["load_bearing"]}.', '',
                      'Affected units: ' + ', '.join(issue['affected_units']), ''])
        if issue['failures']:
            lines.extend([_finding_labels(issue)["heading"] + ':', ''])
        lines.extend(_text(failure['evidence']) if _substantive(failure['evidence']) else 'The recorded finding evidence is unavailable.' for failure in issue['failures'])
        for index, repair in enumerate(issue['repairs'], 1):
            lines.extend(['', '<a id="' + _e(_id("repair", issue["id"], index)) + '"></a>', f'Option {index}: {repair["proposal"]}',
                          f'Scientific cost: {repair["scientific_cost"]}. Verification: {repair["verification_status"]}.',
                          'Required rechecks: ' + ', '.join(repair['required_rechecks'])])
        lines.extend(['', 'Recorded repair search: ' + _text(issue['repair_search']), ''])
        if issue.get("resolution") or issue.get("current_resolution"):
            lines.extend(['The original finding above is historical after resolution.', '', 'Recorded resolution: ' + _text(issue.get("resolution")),
                          'Current mapping: ' + _text(issue.get("current_resolution")), 'Completed rechecks: ' + _text(issue.get("recheck_evidence")), ''])
    lines.extend(['## Exact source evidence', ''])
    for source in p['sources']:
        lines.extend(['<a id="' + _e(source["id"]) + '"></a>', ''])
        lines.extend([f'### {source["file"]}:{source["start_line"]}-{source["end_line"]}', '',
                      'Evidence status: ' + source['status'], '',
                      *('    ' + line for line in _text(source['quote']).splitlines()), ''])
    lines.extend(['<a id="scope"></a>', '<a id="dependency-records"></a>', '<a id="method-interfaces"></a>', '<a id="global-checks"></a>', '## Scope and assurance', '', ASSURANCE, '',
                  'Release: ' + _text(p['release']), '', 'Coverage: ' + _text(p['coverage']), '',
                  _source_review_note(p['audit'].get('source_provenance')), '',
                  'Scope: ' + _text(p['audit']), '', 'Authored context: ' + _text(p['report_context']), '',
                  'Dependency uses: ' + _text(p['dependency_edges']), '', 'Method interfaces: ' + _text(p.get('method_interfaces')), '',
                  'Global checks: ' + _text(p.get('global_checks')), '', 'Graph support: ' + _text(p['graph']), '',
                  'Remaining work: ' + _text(p['diagnostics']), ''])
    return '\n'.join(lines)
