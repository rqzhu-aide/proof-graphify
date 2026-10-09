"""Deterministic presentation of the already audited proof graph.

No mathematical records are changed here. Python prepares labels, edge meanings,
connected pages and geometry once; SVG and browser navigation read the same data.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import textwrap
from collections import Counter, deque
from typing import Any, Callable


PALETTE = {
    "assumption": ("Assumption", "#64748b", "#f1f5f9"),
    "definition": ("Definition", "#0891b2", "#ecfeff"),
    "lemma": ("Lemma", "#2563eb", "#eff6ff"),
    "proposition": ("Proposition", "#4f46e5", "#eef2ff"),
    "theorem": ("Theorem", "#7c3aed", "#f5f3ff"),
    "corollary": ("Corollary", "#6d5a9c", "#f4f1f9"),
    "external result": ("External result", "#0e4f6e", "#edf5f8"),
    "argument": ("Proof step", "#737984", "#f7f8fa"),
    "condition": ("Scope condition", "#607b92", "#eff4f8"),
    "counterexample": ("Counterexample", "#47515e", "#f1f3f5"),
    "refutation evidence": ("Refutation evidence", "#47515e", "#f1f3f5"),
    "result": ("Result", "#596a85", "#f2f5fa"),
}
EDGE_COLORS = {"checked": "#28734f", "pending": "#927018", "broken": "#b13c3c", "given": "#8b94a1", "refutation": "#b13c3c"}
EDGE_MEANINGS = {
    "checked": "Checked support under recorded conditions",
    "pending": "Conditional or awaiting review; inspect the recorded status",
    "broken": "Gap or invalid use breaks this support route",
    "given": "Given premise; no proof-validity judgment",
    "refutation": "Explicit evidence refutes this exact statement",
}
STATUSES = {"not_established": "not established", "conditionally_verified": "conditional", "not_checked": "not checked", "not_assessed": "not assessed", "refutation_evidence": "recorded refutation", "not_applicable": "not applicable"}
VARIANTS = {"restricted statement", "supplemented statement"}
AUXILIARY = {"argument", *VARIANTS}
OVERVIEW_FOCUS = "__paper_overview__"


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else "Not recorded"


def _e(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _status(value: Any) -> str:
    return STATUSES.get(value, str(value or "not checked").replace("_", " "))


def _lines(value: Any, width: int = 31, count: int = 2) -> list[str]:
    lines = textwrap.wrap(" ".join(_text(value).split()), width=width, break_long_words=True) or [""]
    if len(lines) > count:
        lines = lines[:count]
        lines[-1] = lines[-1][:width - 1].rstrip() + "…"
    return lines


def edge_presentation(edge: dict, source: dict) -> dict:
    """Color an exact use, never inherit the prerequisite node's verdict."""
    status = edge.get("status")
    applicability = edge.get("applicability_status")
    broken = {"incorrect", "gap", "invalid", "defect", "refuted", "failed"}
    checked = {"verified", "established", "valid", "passed"}
    if edge.get("kind") == "refutation":
        tone, label = "refutation", "refutes"
    elif status in broken or (edge.get("use_id") and applicability in broken):
        tone, label = "broken", "gap" if status == "gap" or applicability == "gap" else "invalid use" if edge.get("use_id") else "invalid argument"
    elif not edge.get("use_id") and source.get("status") == "given" and source.get("kind") in {"assumption", "definition", "condition"}:
        tone, label = "given", "given"
    elif status in checked and (not edge.get("use_id") or applicability in checked):
        tone, label = "checked", "checked use" if edge.get("use_id") else "checked argument"
    else:
        tone = "pending"
        label = "conditional" if status in {"conditionally_verified", "conditional"} or applicability in {"conditionally_verified", "conditional"} else "stale" if status == "stale" or applicability == "stale" else "not checked" if not status or status in checked or status in {"not_checked", "not_assessed"} else _status(status)
    return {"tone": tone, "color": EDGE_COLORS[tone], "short_label": label,
            "meaning": EDGE_MEANINGS[tone], "dash": "6 5" if tone == "refutation" else "",
            "width": 1.3 if tone == "given" else 2.2, "marker": "graph-" + tone + "-arrow"}


def _identity(result: dict) -> str:
    label = result.get("display_label") or result.get("printed_label")
    if label:
        for original, short in (("Theorem", "Thm"), ("Proposition", "Prop."), ("Corollary", "Cor."), ("Definition", "Def."), ("Assumption", "Assump."), ("Lemma", "Lem.")):
            label = re.sub(r"^" + original + r"\b", short, label, flags=re.I)
        return label
    return str(result.get("kind") or "result").capitalize()


def _decorate_nodes(graph: dict, results: list[dict]) -> None:
    result_map = {r["id"]: r for r in results}
    nodes = {n["id"]: n for n in graph["nodes"]}
    outgoing = {key: [] for key in nodes}
    for edge in graph["edges"]:
        if edge["from"] in outgoing:
            outgoing[edge["from"]].append(edge["to"])
    for index, node in enumerate(graph["nodes"]):
        kind = node["kind"]
        result = result_map.get(node["id"], {})
        parent = result_map.get(node.get("result_id"), {})
        target = next((nodes[k] for k in outgoing[node["id"]] if k in nodes), {})
        target_result = result_map.get(target.get("id"), {}) or result_map.get(target.get("result_id"), {})
        type_key = (parent.get("kind") if kind in VARIANTS else kind) or "result"
        type_key = str(type_key).removeprefix("unnumbered ").removesuffix("*")
        if type_key not in PALETTE:
            type_key = "result"
        identity = _identity(result) if result else PALETTE[type_key][0]
        topic = result.get("reader_description") or result.get("manuscript_title")
        locator = ("Manuscript p. " + str(result["display_pdf_page"]) if result.get("display_pdf_page") else None) or result.get("paper_location") or result.get("location") or node.get("location")
        exact_excerpt = False
        if kind in VARIANTS:
            identity = ("Restricted form of " if kind == "restricted statement" else "Supplement for ") + _identity(parent)
            topic = parent.get("reader_description") or parent.get("manuscript_title")
        elif kind == "argument":
            identity = ("Supplemental proof of " if target.get("kind") in VARIANTS else "Proof of ") + _identity(target_result)
            topic = target_result.get("reader_description") or target_result.get("manuscript_title")
        elif kind in {"counterexample", "refutation evidence"}:
            identity = ("Counterexample to " if kind == "counterexample" else "Refutation evidence for ") + _identity(target_result)
            topic = target_result.get("reader_description") or target_result.get("manuscript_title")
        elif not result:
            # Unavailable inputs retain their explicit kind; never invent a number.
            identity = kind.capitalize() if type_key == "result" else identity
            topic = node.get("reader_description") or node.get("description")
        if not topic:
            if result or kind in VARIANTS:
                topic = locator or parent.get("paper_location") or parent.get("location")
            elif kind in AUXILIARY:
                topic = node.get("location") or node.get("label") or target_result.get("paper_location") or target_result.get("location")
            else:
                topic = node.get("claim") or node.get("label")
                exact_excerpt = True
        if exact_excerpt and re.search(r"\$|\\(?:[A-Za-z]+|[\[(])|[_^](?:\{|\w)", _text(topic)):
            # SVG cards cannot typeset TeX. The full audited text remains in
            # the reading preview; a source locator makes a truthful caption.
            topic = locator or "See statement and source details"
            exact_excerpt = False
        judgments = result.get("judgments", {})
        prefix = "Argument" if kind == "argument" else "Evidence" if kind in {"counterexample", "refutation evidence"} else "Given" if node.get("status") == "given" else "Statement"
        status_text = "Given condition" if prefix == "Given" else prefix + ": " + _status(node.get("status"))
        full_title = result.get("title") or node.get("label") or identity
        identity_result = result or parent or target_result
        long_identity = identity_result.get("display_label") or identity_result.get("printed_label")
        equivalent_identity = identity.replace(_identity(identity_result), long_identity) if long_identity else identity
        if identity.casefold() not in full_title.casefold() and equivalent_identity.casefold() not in full_title.casefold():
            full_title = identity + " · " + full_title
        topic_text = ("Exact claim excerpt: " if exact_excerpt else "") + _text(topic)
        heading_topic = (result or parent or target_result).get("reader_description") or (result or parent or target_result).get("manuscript_title") or node.get("reader_description")
        node["display"] = {"type": type_key, "type_label": PALETTE[type_key][0], "accent": PALETTE[type_key][1], "fill": PALETTE[type_key][2],
                           "identity": identity, "identity_lines": _lines(identity, count=2), "topic": " ".join(_lines(topic_text, width=46, count=2)), "topic_lines": _lines(topic_text),
                           "disambiguator_lines": [], "preview_heading": identity + (" · " + heading_topic if heading_topic else ""),
                           "status_text": status_text, "status_lines": _lines(status_text, width=35, count=2), "variant": kind in VARIANTS,
                           "full_title": full_title,
                           "description": result.get("reader_description") or result.get("manuscript_title") or node.get("reader_description"),
                           "reading_claim": result.get("graph_reading_claim"),
                           "location": locator or parent.get("paper_location") or parent.get("location") or "See linked source evidence",
                           "judgments": judgments, "conditions": ([*parent.get("conditions", []), *node.get("conditions", [])] if kind in VARIANTS else result.get("conditions", node.get("conditions", []))),
                           "preview_id": "graph-node-preview-" + str(index)}
    # Multiple audited conclusions can share one manuscript heading. A locator
    # or an explicitly named audit split distinguishes them without paper parts.
    collisions: dict[tuple, list[dict]] = {}
    for result in results:
        if result["id"] not in nodes:
            continue
        display = nodes[result["id"]]["display"]
        key = (tuple(display["identity_lines"]), tuple(display["topic_lines"]))
        collisions.setdefault(key, []).append(result)
    for group in collisions.values():
        if len(group) < 2:
            continue
        locations = [r.get("location") for r in group]
        for index, result in enumerate(group, 1):
            location = result.get("location")
            disambiguator = location if location and location != "Source unavailable" and locations.count(location) == 1 else f"Audit conclusion {index} of {len(group)}"
            related = {result["id"]}
            related.update(n["id"] for n in graph["nodes"] if n.get("result_id") == result["id"])
            related.update(n["id"] for n in graph["nodes"] if n["kind"] in {"argument", "counterexample", "refutation evidence"} and any(target in related for target in outgoing[n["id"]]))
            for key in related:
                display = nodes[key]["display"]
                display["disambiguator"] = disambiguator
                display["disambiguator_lines"] = _lines(disambiguator, width=39, count=2)
                display["topic_lines"] = display["topic_lines"][:1]
                display["topic"] += " · " + disambiguator
                if disambiguator.startswith("Audit conclusion "):
                    display["preview_heading"] += " · " + disambiguator
                elif disambiguator not in display["location"]:
                    display["location"] += "; selected conclusion: " + disambiguator
                display["full_title"] += " · " + disambiguator
    # Keep cards as compact signposts. Full claims and judgments live in the
    # preview; a shared text layout keeps static and interactive cards identical.
    for node in graph["nodes"]:
        display = node["display"]
        rows, y = [], 24
        for line in display["identity_lines"]:
            rows.append({"class": "kind", "text": line, "y": y})
            y += 18
        y += 2
        context = display["disambiguator_lines"] or display["topic_lines"]
        klass = "disambiguator" if display["disambiguator_lines"] else "claim"
        for line in context:
            rows.append({"class": klass, "text": line, "y": y})
            y += 16
        display["card_rows"] = rows
        display["card_height"] = max(64, y)


def _neighborhood(graph: dict, focus: str) -> tuple[list[str], dict[str, list[str]]]:
    nodes = {n["id"]: n for n in graph["nodes"]}
    adjacency = {key: [] for key in nodes}
    for e in graph["edges"]:
        if e["from"] in nodes and e["to"] in nodes:
            adjacency[e["from"]].append(e["to"])
            adjacency[e["to"]].append(e["from"])
    paths = {focus: [focus]}
    queue = deque([focus])
    while queue:
        key = queue.popleft()
        for neighbor in adjacency[key]:
            if neighbor in paths:
                continue
            paths[neighbor] = [*paths[key], neighbor]
            if nodes[neighbor]["kind"] in AUXILIARY:
                queue.append(neighbor)
    return list(paths), paths


def _layout(graph: dict, page: dict) -> None:
    """Store shared geometry; cross-column and cyclic edges use outside lanes."""
    picked = set(page["node_ids"])
    nodes = [n for n in graph["nodes"] if n["id"] in picked]
    edges = [graph["edges"][i] for i in page["edge_indices"]]
    ranks = {n["id"]: 0 for n in nodes}
    incoming = {key: 0 for key in ranks}
    for edge in edges:
        incoming[edge["to"]] += 1
    queue = deque(key for key in ranks if incoming[key] == 0)
    while queue:
        key = queue.popleft()
        for edge in edges:
            if edge["from"] != key:
                continue
            target = edge["to"]
            ranks[target] = max(ranks[target], ranks[key] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    used: dict[int, int] = {}
    positions = {}
    for node in nodes:
        col = ranks[node["id"]]
        top = used.get(col, 24)
        positions[node["id"]] = [24 + col * 368, top]
        used[col] = top + node["display"]["card_height"] + 24
    width = max(760, max(ranks.values(), default=0) * 368 + 308)
    base_height = max(88, max(used.values(), default=0))
    heights = {n["id"]: n["display"]["card_height"] for n in nodes}
    routes = []
    outside = 0
    for index in page["edge_indices"]:
        edge = graph["edges"][index]
        ax, ay = positions[edge["from"]]
        bx, by = positions[edge["to"]]
        x, y, tx, ty = ax + 260, ay + heights[edge["from"]] / 2, bx, by + heights[edge["to"]] / 2
        if ranks[edge["to"]] == ranks[edge["from"]] + 1:
            corridor = (x + tx) / 2
            route = f"M{x} {y} H{corridor:g} V{ty} H{tx}"
            lx, ly = corridor, (y + ty) / 2 - 8
        else:
            bottom = base_height + outside * 32
            outside += 1
            route = f"M{x} {y} H{x+16} V{bottom} H{tx-16} V{ty} H{tx}"
            lx, ly = (x + tx) / 2, bottom - 7
        routes.append({"index": index, "d": route, "label_x": lx, "label_y": ly})
    page.update({"positions": positions, "routes": routes, "width": width, "height": base_height + outside * 32,
                 "node_types": list(dict.fromkeys(n["display"]["type"] for n in nodes)),
                 "edge_tones": list(dict.fromkeys(e["presentation"]["tone"] for e in edges))})


def _pages(graph: dict, focus: str, bound: int = 12) -> list[dict]:
    candidates, paths = _neighborhood(graph, focus)
    candidate_set = set(candidates)
    candidate_edges = [i for i, e in enumerate(graph["edges"]) if e["from"] in candidate_set and e["to"] in candidate_set]
    # Each requirement includes its connecting path. Cover all candidate edges,
    # including cross-links whose endpoints would otherwise land on different pages.
    # Start with evidence and result uses, so bulk given conditions do not
    # push every mathematical dependency onto a continuation page.
    def priority(index: int) -> int:
        edge = graph["edges"][index]
        return 0 if edge.get("kind") == "refutation" else 1 if edge.get("use_id") else 3 if edge["presentation"]["tone"] == "given" else 2
    requirements = [set(paths[graph["edges"][i]["from"]] + paths[graph["edges"][i]["to"]]) for i in sorted(candidate_edges, key=priority)]
    requirements += [set(paths[key]) for key in candidates]
    selections: list[set[str]] = []
    current = {focus}
    for required in requirements:
        if any(required <= selected for selected in selections) or required <= current:
            continue
        if len(current | required) > bound and len(current) > 1:
            selections.append(current)
            current = {focus}
        current |= required
    if current != {focus} or not selections:
        selections.append(current)
    pages = []
    for index, selected in enumerate(selections):
        shown_edges = [i for i in candidate_edges if graph["edges"][i]["from"] in selected and graph["edges"][i]["to"] in selected]
        page = {"focus": focus, "node_ids": [n["id"] for n in graph["nodes"] if n["id"] in selected], "edge_indices": shown_edges,
                "candidate_nodes": len(candidates), "candidate_edges": len(candidate_edges),
                "omitted_nodes": len(candidates) - len(selected), "omitted_edges": len(candidate_edges) - len(shown_edges),
                "page_number": index + 1, "page_count": len(selections), "over_bound": len(selected) > bound}
        _layout(graph, page)
        pages.append(page)
    return pages


def prepare_graph(graph: dict, results: list[dict], preferred_units: list[str] | None = None) -> dict:
    graph = copy.deepcopy(graph)
    _decorate_nodes(graph, results)
    nodes = {n["id"]: n for n in graph["nodes"]}
    for index, edge in enumerate(graph["edges"]):
        edge["presentation"] = {**edge_presentation(edge, nodes.get(edge["from"], {})), "preview_id": "graph-edge-preview-" + str(index)}
    preferences = preferred_units or []
    focus = next((r["id"] for r in results if r.get("unit_id") in preferences and r["id"] in nodes), None)
    focus = focus or next((r["id"] for r in results if r["id"] in nodes), None) or next(iter(nodes), "")
    graph["initial_focus"] = focus
    graph["views"] = {key: _pages(graph, key) for key in nodes}
    graph["convention"] = ("Node colors identify mathematical types; neutral text gives recorded judgments. "
        "Connection colors describe each exact use or argument: checked, conditional or pending, broken, or a given premise. "
        "Premises entering one argument are used jointly. Written and supplemental routes remain separate. "
        "Dashed red arrows show explicit refutation evidence, labeled refutes; a failed route alone does not refute its statement.")
    for pages in graph["views"].values():
        for page in pages:
            page["note"] = page_note(graph, page)
    return graph


def _overview_layout(graph: dict, page: dict) -> None:
    """Arrange source groups, condensing cycles for geometry only.

    Condensation here is not a circularity test. Two results can use different
    conclusions of one another while their exact support graph stays acyclic.
    """
    picked = set(page["node_ids"])
    nodes = [n for n in graph["nodes"] if n["id"] in picked]
    edges = [graph["edges"][i] for i in page["edge_indices"]]
    adjacency = {n["id"]: [] for n in nodes}
    reverse = {key: [] for key in adjacency}
    for edge in edges:
        adjacency[edge["from"]].append(edge["to"])
        reverse[edge["to"]].append(edge["from"])
    seen, finished = set(), []
    for start in adjacency:
        stack = [(start, False)]
        while stack:
            key, returning = stack.pop()
            if returning:
                finished.append(key)
            elif key not in seen:
                seen.add(key)
                stack.append((key, True))
                stack.extend((neighbor, False) for neighbor in reversed(adjacency[key]) if neighbor not in seen)
    component = {}
    for start in reversed(finished):
        if start in component:
            continue
        label, stack = len(component), [start]
        while stack:
            key = stack.pop()
            if key in component:
                continue
            component[key] = label
            stack.extend(reverse[key])
    links = {key: set() for key in component.values()}
    indegree, ranks = {key: 0 for key in links}, {key: 0 for key in links}
    for edge in edges:
        source, target = component[edge["from"]], component[edge["to"]]
        if source != target and target not in links[source]:
            links[source].add(target)
            indegree[target] += 1
    queue = deque(key for key in links if not indegree[key])
    while queue:
        key = queue.popleft()
        for target in sorted(links[key]):
            ranks[target] = max(ranks[target], ranks[key] + 1)
            indegree[target] -= 1
            if not indegree[target]:
                queue.append(target)
    layers = {}
    for node in nodes:
        layers.setdefault(ranks[component[node["id"]]], []).append(node)
    band_counts = Counter(ranks[component[edge["from"]]] for edge in edges
                          if ranks[component[edge["to"]]] == ranks[component[edge["from"]]] + 1)
    positions, heights, row_bounds, top = {}, {}, {}, 24
    max_columns = min(3, max((len(layer) for layer in layers.values()), default=1))
    width = max(308, max_columns * 284 + 24)
    for rank, layer in sorted(layers.items()):
        for offset in range(0, len(layer), 3):
            row = layer[offset:offset + 3]
            row_height = max(node["display"]["card_height"] for node in row)
            left = (width - (len(row) * 284 - 24)) / 2
            for column, node in enumerate(row):
                positions[node["id"]] = [left + column * 284, top]
                heights[node["id"]] = node["display"]["card_height"]
                row_bounds[node["id"]] = (top, top + row_height)
            top += row_height + 24
        top += max(54, band_counts[rank] * 26 + 12)
    routes, outside, band_used = [], 0, Counter()
    label_right = width
    for index in page["edge_indices"]:
        edge = graph["edges"][index]
        show_label = edge.get("use_count", 0) > 1 or edge["presentation"]["tone"] != "checked"
        label = (edge["presentation"]["short_label"] if edge.get("use_count", 0) > 1
                 else "broken" if edge["presentation"]["tone"] == "broken" else "qualified")
        label_width = len(label) * 6
        ax, ay = positions[edge["from"]]
        bx, by = positions[edge["to"]]
        source_rank, target_rank = ranks[component[edge["from"]]], ranks[component[edge["to"]]]
        source_bottom = row_bounds[edge["from"]][1]
        last_source_row = max(row_bounds[node["id"]][1] for node in layers[source_rank])
        first_target_row = min(row_bounds[node["id"]][0] for node in layers[target_rank])
        if target_rank == source_rank + 1 and source_bottom == last_source_row and by == first_target_row:
            x, y, tx, ty = ax + 130, ay + heights[edge["from"]], bx + 130, by
            corridor = last_source_row + 24 + band_used[source_rank] * 26
            band_used[source_rank] += 1
            route = f"M{x:g} {y:g} V{corridor:g} H{tx:g} V{ty:g}"
            lx, ly = (x + tx) / 2, corridor - 7
            anchor = "middle"
            if show_label:
                label_right = max(label_right, lx + label_width / 2 + 12)
        else:
            x, y, tx, ty = ax + 130, ay + heights[edge["from"]], bx + 130, by
            lane = width + outside
            outside += label_width + 14 if show_label else 26
            exit_y, enter_y = source_bottom + 12, by - 12
            route = f"M{x:g} {y:g} V{exit_y:g} H{lane:g} V{enter_y:g} H{tx:g} V{ty:g}"
            lx, ly = lane + 8, (exit_y + enter_y) / 2 - 7
            anchor = "start"
        routes.append({"index": index, "d": route, "label_x": lx, "label_y": ly,
                       "show_label": show_label, "label_anchor": anchor, "label": label})
    page.update({"positions": positions, "routes": routes, "width": max(label_right, width + outside + (16 if outside else 0)),
                 "height": max(100, top - 54), "node_types": list(dict.fromkeys(n["display"]["type"] for n in nodes)),
                 "edge_tones": list(dict.fromkeys(e["presentation"]["tone"] for e in edges))})


def _overview_pages(graph: dict, bound: int = 12, *, focus: str = OVERVIEW_FOCUS) -> list[dict]:
    """Pack readable result pages, retaining every connecting requirement."""
    all_ids = [node["id"] for node in graph["nodes"]]
    if not all_ids:
        return []
    if focus == OVERVIEW_FOCUS:
        candidates, paths = all_ids, {key: [key] for key in all_ids}
        base = set()
    else:
        candidates, paths = _neighborhood(graph, focus)
        base = {focus}
    candidate_set = set(candidates)
    candidate_edges = [i for i, edge in enumerate(graph["edges"])
                       if edge["from"] in candidate_set and edge["to"] in candidate_set]
    cache = {}
    def page(selected: set[str]) -> dict:
        identity = frozenset(selected)
        if identity in cache:
            return cache[identity]
        edge_indices = [i for i in candidate_edges
                        if graph["edges"][i]["from"] in selected and graph["edges"][i]["to"] in selected]
        value = {"focus": focus, "node_ids": [key for key in all_ids if key in selected], "edge_indices": edge_indices,
                 "candidate_nodes": len(candidates), "candidate_edges": len(candidate_edges),
                 "omitted_nodes": len(candidates) - len(selected), "omitted_edges": len(candidate_edges) - len(edge_indices),
                 "page_number": 1, "page_count": 1, "over_bound": False}
        _overview_layout(graph, value)
        cache[identity] = value
        return value
    def readable(value: dict) -> bool:
        return len(value["edge_indices"]) <= 48 and value["height"] <= 900 and value["width"] <= 1300
    complete_bound = 24 if focus == OVERVIEW_FOCUS else bound
    if len(candidates) <= complete_bound and len(candidate_edges) <= 48:
        complete = page(candidate_set)
        if readable(complete):
            return [complete]
    # An edge's two endpoints always travel together. Coverage pages are not
    # presented as separate components or as mathematical independence claims.
    # A focused page also retains each endpoint's existing path to the focus.
    requirements = [set(paths[graph["edges"][i]["from"]] + paths[graph["edges"][i]["to"]]) for i in candidate_edges]
    requirements += [set(paths[key]) for key in candidates]
    selections, current = [], set(base)
    for required in requirements:
        if required <= current or any(required <= selection for selection in selections):
            continue
        proposed = current | required
        if current != base and (len(proposed) > bound or not readable(page(proposed))):
            selections.append(current)
            current = set(base)
        current |= required
    if current != base or not selections:
        selections.append(current)
    pages = [{**page(selected)} for selected in selections]
    for index, value in enumerate(pages, 1):
        value.update(page_number=index, page_count=len(pages),
                     over_bound=len(value["node_ids"]) > bound or not readable(value))
    return pages


def prepare_overview(exact_graph: dict, results: list[dict], result_groups: list[dict]) -> dict:
    """Project display containers and recorded cross-result uses, losslessly.

    Groups come from authenticated source association in the report projection.
    Only selected-support use edges create arrows. Exact edge indices retain
    source forms, target conclusions and alternative routes without copying
    those mathematical records into a second evidence dataset.
    """
    result_map = {result["id"]: result for result in results}
    result_to_group = {key: group["id"] for group in result_groups for key in group["result_ids"]}
    if len(result_to_group) != sum(len(group["result_ids"]) for group in result_groups) or set(result_to_group) != set(result_map):
        raise ValueError("Overview groups must cover each result exactly once")
    exact_nodes = {node["id"]: node for node in exact_graph["nodes"]}
    nodes, displays = {}, []
    for group in result_groups:
        projected = {**group, "conditions": [], "judgments": {}}
        displays.append(projected)
        nodes[group["id"]] = {"id": group["id"], "kind": group["kind"], "label": group.get("manuscript_title") or group.get("display_label") or group["kind"].capitalize(),
                              "claim": group.get("graph_reading_claim") or group.get("claim") or "The complete source statement is unavailable; inspect the individual audited conclusions.",
                              "status": "display_group", "detail_id": group["id"], "source_ids": group.get("statement_source_ids", []),
                              "result_ids": list(group["result_ids"]), "assessment_summary": group.get("assessment_summary", "Assessment details are recorded per conclusion."),
                              "assessment_counts": group.get("assessment_counts", {}), "availability": group.get("availability", "not_recorded")}
    # Associate written and supplemental route nodes using their explicit
    # selected target. This does not follow arbitrary dependency reachability.
    owners = {key: [key] for key in result_map}
    for node in exact_graph["nodes"]:
        if node.get("result_id") in result_map:
            owners[node["id"]] = [node["result_id"]]
    route_kinds, route_targets = {}, {}
    for edge in exact_graph["edges"]:
        if exact_nodes.get(edge["from"], {}).get("kind") == "argument" and edge["to"] in owners:
            owners.setdefault(edge["from"], []).extend(owners[edge["to"]])
            route_kinds[edge["from"]] = "supplemental" if exact_nodes.get(edge["to"], {}).get("kind") in VARIANTS else "written"
            route_targets[edge["from"]] = edge["to"]
    grouped, local_uses = {}, []
    for index, edge in enumerate(exact_graph["edges"]):
        if not edge.get("use_id"):
            continue
        targets = list(dict.fromkeys(owners.get(edge["to"], [])))
        source = exact_nodes.get(edge["from"], {})
        source_owners = owners.get(edge["from"], [])
        if not targets:
            raise ValueError("Recorded dependency use has no selected result target in the overview")
        if len(source_owners) == 1:
            source_id = result_to_group[source_owners[0]]
        else:
            kind = source.get("kind", "internal result")
            # Registry identity, rather than title/needed_form, joins external
            # uses. Missing identities stay distinct instead of guessing.
            dependency = edge.get("dependency_id") or source.get("id")
            selected = edge.get("statement_support") or {}
            identity = (kind, dependency, selected.get("sha256") if kind == "unavailable supplement" else None)
            source_id = "overview-source-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
            if source_id not in nodes:
                nodes[source_id] = {**source, "id": source_id, "detail_id": source.get("detail_id", edge["from"]),
                                    "kind": kind, "overview_stub": True, "exact_node_ids": [], "registered_dependency_id": edge.get("dependency_id")}
            if edge["from"] not in nodes[source_id]["exact_node_ids"]:
                nodes[source_id]["exact_node_ids"].append(edge["from"])
        dependent = edge.get("dependent_unit") or edge.get("unit_id") or result_map[targets[0]].get("unit_id")
        identity = [dependent, edge["use_id"]]
        for target in targets:
            target_id = result_to_group[target]
            if source_id == target_id:
                local_uses.append({"qualified_use": identity, "exact_edge_index": index, "target_result_id": target})
                continue
            entry = grouped.setdefault((source_id, target_id), {"from": source_id, "to": target_id, "kind": "overview_use", "contributors": []})
            entry["contributors"].append({"qualified_use": identity, "exact_edge_index": index, "source_result_id": source_owners[0] if len(source_owners) == 1 else None,
                                          "target_result_id": target, "route_id": edge["to"],
                                          "target_form_id": route_targets.get(edge["to"], target),
                                          "route_kind": route_kinds.get(edge["to"], "written")})
    graph = {"nodes": list(nodes.values()), "edges": list(grouped.values()), "mode": "overview", "result_to_group": result_to_group,
             "selection_ids": [group["id"] for group in result_groups], "local_uses": local_uses, "initial_focus": OVERVIEW_FOCUS}
    _decorate_nodes(graph, displays)
    for index, node in enumerate(graph["nodes"]):
        d = node["display"]
        d["preview_id"] = "overview-node-preview-" + str(index)
        d["judgments"], d["conditions"] = {}, []
        d["reading_claim"] = None
        if node.get("overview_stub"):
            if node["kind"] == "external result":
                summary = "External prerequisite"
            else:
                summary = "Unavailable selected support"
            d["status_text"] = summary
        else:
            summary = node["assessment_summary"]
            d["status_text"] = summary
        group = next((entry for entry in result_groups if entry["id"] == node["id"]), {})
        topic = group.get("manuscript_title") or d.get("description")
        if topic and re.search(r"\$|\\(?:[A-Za-z]+|[\[(])|[_^](?:\{|\w)", _text(topic)):
            topic = None
        verified = group.get("display_label") or group.get("printed_label")
        if not node.get("overview_stub") and not verified:
            heading = d["identity"] + " · " + (d.get("disambiguator") or topic or d["location"])
            heading_rows = _lines(heading, width=32, count=2)
        else:
            heading_rows = _lines(d["identity"], width=32, count=1)
            context = d.get("disambiguator") or topic
            if context:
                heading_rows.extend(_lines(context, width=35, count=1))
        # Concise attention/count text is visible, not hover-dependent. Keep
        # type backgrounds neutral; only exact uses determine edge colors.
        d["card_rows"] = [{"class": "kind", "text": line, "y": 23 + i * 17} for i, line in enumerate(heading_rows)]
        y = 23 + len(heading_rows) * 17
        for line in _lines(summary, width=35, count=2 if len(heading_rows) == 1 else 1):
            d["card_rows"].append({"class": "state", "text": line, "y": y})
            y += 16
        d["card_height"] = max(64, y + 3)
    for index, edge in enumerate(graph["edges"]):
        uses = {}
        for contributor in edge["contributors"]:
            exact = exact_graph["edges"][contributor["exact_edge_index"]]
            tone = edge_presentation(exact, exact_nodes.get(exact["from"], {}))["tone"]
            if nodes[edge["from"]].get("kind") in {"internal result", "unavailable supplement"} and tone != "broken":
                tone = "pending"
            key = tuple(contributor["qualified_use"])
            previous = uses.get(key, "checked")
            uses[key] = "broken" if "broken" in {tone, previous} else "pending" if "pending" in {tone, previous} else "checked"
        counts = Counter(uses.values())
        edge["use_count"], edge["use_counts"] = len(uses), dict(counts)
        tone = "broken" if counts["broken"] else "pending" if counts["pending"] else "checked"
        label = f"{len(uses)} use" + ("s" if len(uses) != 1 else "")
        label += f" · {counts['broken']} broken" if counts["broken"] else f" · {counts['pending']} qualified" if counts["pending"] else " · checked"
        edge["presentation"] = {"tone": tone, "color": EDGE_COLORS[tone], "short_label": label,
                                "meaning": {"broken": "At least one recorded use is broken",
                                            "pending": "At least one use is conditional, pending, stale, or unavailable",
                                            "checked": "Every contributing use is checked under its recorded conditions"}[tone],
                                "dash": "", "width": 2.2, "marker": "graph-" + tone + "-arrow", "preview_id": "overview-edge-preview-" + str(index)}
    graph["views"] = {OVERVIEW_FOCUS: _overview_pages(graph)}
    for key in nodes:
        graph["views"][key] = _overview_pages(graph, focus=key)
    graph["convention"] = ("Nodes group manuscript results; node colors identify their types. "
        "Arrows summarize recorded uses: green checked, yellow qualified or unavailable, red broken. "
        "These colors describe uses, not whole-result truth. Open a node for its conclusions and proof details.")
    for pages in graph["views"].values():
        for page in pages:
            page["note"] = page_note(graph, page)
    return graph


def initial_page(graph: dict) -> dict:
    return next(iter(graph.get("views", {}).get(graph.get("initial_focus"), [])), {})


def page_note(graph: dict, page: dict | None = None) -> str:
    page = initial_page(graph) if page is None else page
    if not page:
        return "No proof graph nodes are available. Complete records are listed below."
    if graph.get("mode") == "overview":
        name = "All results in audit scope" if page["focus"] == OVERVIEW_FOCUS else "Result neighborhood"
        shown = set(page["node_ids"])
        result_count = sum(key in shown for key in graph["selection_ids"])
        remaining_results = len(graph["selection_ids"]) - result_count
        remaining_edges = len(graph["edges"]) - len(page["edge_indices"])
        return (f"{name}. Page {page['page_number']} of {page['page_count']}. "
                f"Showing {result_count} of {len(graph['selection_ids'])} manuscript results, "
                f"{len(shown) - result_count} prerequisite nodes, and {len(page['edge_indices'])} of {len(graph['edges'])} cross-result connections "
                f"({remaining_results} results and {remaining_edges} connections omitted on this page). "
                + ("Continue the overview or select a result to inspect the remaining structure. " if remaining_results or remaining_edges else "")
                + ("This page exceeds the usual display bound to retain a complete connecting path. " if page["over_bound"] else "")
                + "Coverage is the recorded audit scope; disconnected results do not imply mathematical independence. Within-result uses remain in Detailed proof.")
    node = next(n for n in graph["nodes"] if n["id"] == page["focus"])
    note = (f"Focus: {node['display']['identity']}. Page {page['page_number']} of {page['page_count']}. "
            f"Showing {len(page['node_ids'])} of {page['candidate_nodes']} nodes and {len(page['edge_indices'])} of {page['candidate_edges']} connections in this neighborhood "
            f"({page['omitted_nodes']} nodes and {page['omitted_edges']} connections omitted on this page); "
            f"{len(graph['nodes'])} nodes and {len(graph['edges'])} connections in the audit. ")
    if page["omitted_nodes"] or page["omitted_edges"]:
        note += "Continue this focus to inspect omitted joint premises and routes. "
    if page["over_bound"]:
        note += "This page exceeds the usual 12-node bound to retain a complete connecting path. "
    return note + "Complete claims and support are listed below."


def render_legend(graph: dict, page: dict | None = None) -> str:
    page = initial_page(graph) if page is None else page
    parts = ['<div class="graph-legend" id="graph-legend" aria-label="Graph legend">']
    for kind in page.get("node_types", []):
        label, accent, fill = PALETTE[kind]
        parts.append(f'<span><i class="graph-type-key" style="background:{fill};border-color:{accent}"></i>{_e(label)}</span>')
    for tone in page.get("edge_tones", []):
        meaning = next((edge["presentation"]["meaning"] for edge in graph["edges"]
                        if edge.get("presentation", {}).get("tone") == tone), EDGE_MEANINGS[tone])
        parts.append(f'<span><i class="graph-line-key" style="border-color:{EDGE_COLORS[tone]};border-top-style:{"dashed" if tone == "refutation" else "solid"}"></i>{_e(meaning)}</span>')
    return "".join(parts) + '</div>'


def render_graph(graph: dict) -> str:
    if "views" not in graph or any("display" not in node for node in graph.get("nodes", [])):
        graph = prepare_graph(graph, [])
    page = initial_page(graph)
    if not page:
        return '<p>No proof graph nodes are available.</p>'
    nodes = {n["id"]: n for n in graph["nodes"]}
    parts = [f'<svg viewBox="0 0 {page["width"]} {page["height"]}" style="width:{page["width"]}px;min-width:{page["width"]}px" role="group" aria-label="Selected proof support graph"><defs>']
    for tone, color in EDGE_COLORS.items():
        parts.append(f'<marker id="graph-{tone}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="{color}"/></marker>')
    parts.append('</defs>')
    for route in page["routes"]:
        edge = graph["edges"][route["index"]]
        p = edge["presentation"]
        target = nodes[edge["to"]]
        title = p["short_label"] + ": " + p["meaning"]
        parts.append(f'<a class="graph-connection" href="#{_e(target["detail_id"])}" tabindex="0" data-preview="{p["preview_id"]}" aria-label="{_e(title)}"><title>{_e(title)}</title><path class="graph-edge-hit" d="{route["d"]}"/><path class="graph-edge {p["tone"]}" style="stroke:{p["color"]};stroke-width:{p["width"]};stroke-dasharray:{p["dash"] or "none"}" d="{route["d"]}" marker-end="url(#{p["marker"]})"/>')
        if route.get("show_label", True):
            parts.append(f'<text class="graph-edge-label" style="text-anchor:{route.get("label_anchor", "middle")}" x="{route["label_x"]:g}" y="{route["label_y"]:g}">{_e(route.get("label", p["short_label"]))}</text>')
        parts.append('</a>')
    for key in page["node_ids"]:
        node = nodes[key]
        d = node["display"]
        x, y = page["positions"][key]
        aria = d["full_title"] + ". " + d["status_text"]
        parts.append(f'<a class="graph-node type-{d["type"].replace(" ", "-")}{" graph-focal" if key == page["focus"] else ""}" href="#{_e(node["detail_id"])}" tabindex="0" data-preview="{d["preview_id"]}" aria-label="{_e(aria)}"><title>{_e(aria)}</title><rect x="{x}" y="{y}" width="260" height="{d["card_height"]}" rx="9" style="fill:{d["fill"]};stroke:{d["accent"]};stroke-dasharray:{"5 3" if d["variant"] else "none"}"/>')
        for row in d["card_rows"]:
            parts.append(f'<text class="{row["class"]}" x="{x+14}" y="{y+row["y"]}">{_e(row["text"])}</text>')
        parts.append('</a>')
    return "".join(parts) + '</svg>'


def _rich_value(value: Any, rich: Callable[[Any], str]) -> str:
    if isinstance(value, dict):
        return '<dl>' + ''.join('<dt>' + _e(str(k).replace('_', ' ')) + '</dt><dd>' + _rich_value(v, rich) + '</dd>' for k, v in value.items()) + '</dl>'
    if isinstance(value, list):
        return '<ul>' + ''.join('<li>' + _rich_value(v, rich) + '</li>' for v in value) + '</ul>'
    return rich(value)


def render_previews(graph: dict, rich: Callable[[Any], str], *, include_dialog: bool = True,
                    exact_graph: dict | None = None) -> str:
    parts = ['<div id="graph-preview" class="graph-preview" role="dialog" aria-label="Proof graph reading preview" hidden tabindex="-1"></div>'] if include_dialog else []
    nodes = {n["id"]: n for n in graph["nodes"]}
    exact_nodes = {n["id"]: n for n in (exact_graph or graph)["nodes"]}
    for node in graph["nodes"]:
        d = node["display"]
        parts.append(f'<template id="{d["preview_id"]}"><button type="button" class="graph-preview-close" aria-label="Close preview">×</button><h3>{rich(d["preview_heading"])}</h3>')
        if graph.get("mode") == "overview":
            parts.append('<p>' + _e(d["status_text"]) + '.</p>')
            if node.get("overview_stub"):
                parts.append('<p><strong>Recorded consumed forms</strong></p><p>This prerequisite is represented by its recorded uses; these excerpts are not a complete result statement.</p>')
                for key in node["exact_node_ids"]:
                    exact = exact_nodes[key]
                    parts.append('<div class="graph-preview-claim">' + rich(exact.get("claim")) + '</div><p><a href="#' + _e(exact["detail_id"]) + '">Open this consumed form and its evidence</a></p>')
            else:
                parts.append('<p><strong>Manuscript statement</strong></p><div class="graph-preview-claim">' + rich(node["claim"]) + '</div>')
                parts.append('<p>The assessment summarizes recorded conclusions. It does not add a whole-result verdict or extend audit coverage.</p>')
            parts.append('<p class="source-label">' + _e(d["location"]) + '</p><p><a href="#' + _e(node["detail_id"]) + '">Open grouped conclusions and proof details</a></p></template>')
            continue
        reading = d.get("reading_claim")
        claim_label = "Typeset from locked manuscript excerpt" if reading else "Exact selected claim"
        parts.append('<p><strong>' + claim_label + '</strong></p><div class="graph-preview-claim">' + rich(reading or node.get("claim")) + '</div>')
        if d["conditions"]:
            values = [v.get("value", v) if isinstance(v, dict) else v for v in d["conditions"]]
            parts.append('<p><strong>Recorded conditions</strong></p>' + _rich_value(values, rich))
        judgments = d["judgments"]
        if judgments:
            parts.append('<p>Written argument: ' + _e(_status(judgments.get("argument_status"))) + '. Statement: ' + _e(_status(judgments.get("statement_status"))) + '.</p>')
        else:
            parts.append('<p>' + _e(d["status_text"]) + '.</p>')
        if node.get("reason"):
            parts.append('<p>' + rich(node["reason"]) + '</p>')
        parts.append('<p class="source-label">' + _e(d["location"]) + '</p><p><a href="#' + _e(node["detail_id"]) + '">Open full statement and proof details</a></p></template>')
    for edge in graph["edges"]:
        p = edge["presentation"]
        source, target = nodes[edge["from"]], nodes[edge["to"]]
        parts.append(f'<template id="{p["preview_id"]}"><button type="button" class="graph-preview-close" aria-label="Close preview">×</button><h3>{_e(p["short_label"].capitalize())}</h3><p>{_e(source["display"]["identity"])} → {_e(target["display"]["identity"])}</p><p>{_e(p["meaning"])}.</p>')
        if graph.get("mode") == "overview":
            parts.append('<p>Distinct recorded uses: ' + _e(edge["use_count"]) + '. Reuse of one application in several conclusions or routes is counted once.</p><ul>')
            for contributor in edge["contributors"]:
                exact = (exact_graph or graph)["edges"][contributor["exact_edge_index"]]
                consumed = exact_nodes[exact["from"]]
                selected = exact_nodes[contributor["target_result_id"]]
                target_form = exact_nodes[contributor["target_form_id"]]
                route = exact_nodes[contributor["route_id"]]
                parts.append('<li><p><strong>' + _e(contributor["route_kind"].capitalize()) + ' route for ' + _e(selected["display"]["preview_heading"]) + '</strong></p>')
                parts.append('<div class="graph-preview-claim">' + rich(exact.get("needed_form") or consumed.get("claim")) + '</div>')
                parts.append('<p><strong>Used in this ' + ('supplemental form' if contributor["route_kind"] == "supplemental" else 'assessed conclusion') + '</strong></p><div class="graph-preview-claim">' + rich(target_form.get("claim")) + '</div>')
                if target_form.get("conditions"):
                    parts.append('<p>Additional conditions of this target form:</p>' + _rich_value(target_form["conditions"], rich))
                parts.append('<p>Effective support: ' + _e(_status(exact.get("status"))) + '. Application: ' + _e(_status(exact.get("applicability_status"))) + '.</p>')
                if consumed.get("kind") in {"internal result", "unavailable supplement"}:
                    parts.append('<p>The selected source form is unavailable.</p>')
                if exact.get("statement_support_conditions"):
                    parts.append('<p>Conditions checked at this use:</p>' + _rich_value(exact["statement_support_conditions"], rich))
                parts.append('<p><a href="#' + _e(consumed["detail_id"]) + '">Consumed statement</a> · <a href="#' + _e(route["detail_id"]) + '">Application evidence</a> · <a href="#' + _e(selected["detail_id"]) + '" data-graph-detail="' + _e(selected["id"]) + '">Exact detailed proof</a></p></li>')
            parts.append('</ul></template>')
            continue
        parts.append('<p><strong>Consumed form' + (' or refutation evidence' if edge.get('kind') == 'refutation' else '') + '</strong></p><div class="graph-preview-claim">' + rich(edge.get("needed_form") or source.get("claim")) + '</div>')
        if edge.get("use_id"):
            parts.append('<p>Effective support: ' + _e(_status(edge.get("status"))) + '. Application: ' + _e(_status(edge.get("applicability_status"))) + '.</p>')
        elif p["tone"] != "given":
            parts.append('<p>Recorded status: ' + _e(_status(edge.get("status") or ("refutation_evidence" if edge.get("kind") == "refutation" else None))) + '.</p>')
        for field, label in (("statement_support_conditions", "Conditions checked at this use"), ("compatibility_checks", "Applicability evidence"), ("prerequisite_map", "Required premises"), ("source_evidence", "Support evidence"), ("reason", "Recorded reason"), ("label", "Recorded route")):
            if edge.get(field):
                parts.append('<p><strong>' + label + '</strong></p>' + _rich_value(edge[field], rich))
        if not edge.get("use_id") and source.get("reason"):
            parts.append('<p><strong>Recorded argument</strong></p>' + rich(source["reason"]))
        parts.append('<p><a href="#' + _e(source["detail_id"]) + '">Open consumed statement or evidence</a> · <a href="#' + _e(target["detail_id"]) + '">Open application and proof details</a></p></template>')
    return "".join(parts)


CSS = r"""
.graph-card{position:relative;color:#253147}.graph-card .graph-note{color:#596579}
.graph-card .graph-scroll{max-height:560px;overflow:auto;scrollbar-gutter:stable}
.graph-card .graph-scroll svg{margin-inline:auto}
.graph-card .graph-node rect{stroke-width:1.5}.graph-card .graph-node.graph-focal rect{stroke-width:2.8}
.graph-card .graph-node:hover rect,.graph-card .graph-node:focus rect{stroke-width:3.3}
.graph-card .graph-node text{fill:#253147;font-family:'Segoe UI',Arial,sans-serif}
.graph-card .graph-node .kind{font-size:15px;letter-spacing:0;font-weight:700}.graph-card .graph-node .claim{font-size:13px}
.graph-card .graph-node .disambiguator{font-size:11px;fill:#455269}
.graph-card .graph-node .state{font-size:12px;fill:#455269}.graph-card .graph-node:focus{outline:none}
.graph-card .graph-edge{fill:none;pointer-events:none}.graph-edge-hit{fill:none;stroke:transparent;stroke-width:18;pointer-events:stroke}
.graph-connection:hover .graph-edge,.graph-connection:focus .graph-edge{filter:drop-shadow(0 0 1px #546176);stroke-width:3.5!important}
.graph-connection:focus{outline:none}.graph-edge-label{font:11px 'Segoe UI',Arial,sans-serif;fill:#344155;text-anchor:middle;paint-order:stroke;stroke:white;stroke-width:4;stroke-linejoin:round}
.graph-legend{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:12px;margin:10px 0 16px;color:#465368}.graph-legend span{display:inline-flex;align-items:center;gap:7px}
.graph-type-key{width:14px;height:14px;border:2px solid;border-radius:4px;display:inline-block}.graph-line-key{width:26px;height:0;border-top:2px solid;display:inline-block}
.graph-preview{position:fixed;z-index:20;background:#fff;color:#253147;border:1px solid #9ba7b8;border-radius:10px;box-shadow:0 12px 35px #1e293b2b;width:min(450px,calc(100vw - 24px));max-height:min(540px,calc(100vh - 24px));overflow:auto;padding:16px 18px;font-size:14px;line-height:1.55;overflow-wrap:anywhere}
.graph-preview[hidden]{display:none}.graph-preview h3{font:600 17px/1.35 'Segoe UI',Arial,sans-serif;margin:0 26px 12px 0}.graph-preview-close{float:right;padding:0 7px;font-size:19px;color:#455269;border-color:#cbd2dc}
.graph-preview .graph-preview-claim{font-family:Georgia,'Times New Roman',serif;padding:8px 0;max-height:190px;overflow:auto}.graph-preview p{margin:9px 0}.graph-preview dt{font-weight:600}.graph-preview dd{margin:4px 0 10px}.graph-preview ul{padding-left:19px}.graph-preview .math-display{font-size:1.05em}
.graph-preview a{display:inline-block;max-width:100%;overflow-wrap:anywhere}
@media(max-width:760px){.graph-card{padding:12px}.graph-card .graph-scroll svg{min-width:760px}.graph-preview{max-height:60vh}.graph-legend{font-size:11px}}
@media print{.graph-preview,.graph-legend{display:none!important}}
"""


SCRIPT = r"""
let graphPage=0,graphMode=data.overview?'overview':'detail';
let graphData=data.overview||data.graph,graphNodes=new Map(graphData.nodes.map(n=>[n.id,n]));
let graphOverviewFocus=graphData.initial_focus,graphDetailFocus=data.graph.initial_focus;
const graphColors={checked:'#28734f',pending:'#927018',broken:'#b13c3c',given:'#8b94a1',refutation:'#b13c3c'};
const graphSvgNS='http://www.w3.org/2000/svg';
function graphEl(name,attrs,text){const el=document.createElementNS(graphSvgNS,name);Object.entries(attrs||{}).forEach(([key,value])=>el.setAttribute(key,value));if(text!==undefined)el.textContent=text;return el;}
const graphPreview=byId('graph-preview');let graphOwner=null,graphPinned=false,graphTimer;
function dismissGraphPreview(){clearTimeout(graphTimer);graphPreview.hidden=true;if(graphOwner)graphOwner.removeAttribute('aria-expanded');graphOwner=null;graphPinned=false;}
function placeGraphPreview(owner){const box=owner.getBoundingClientRect(),width=graphPreview.offsetWidth,height=graphPreview.offsetHeight;let left=box.right+12,top=box.top;if(left+width>innerWidth-12)left=box.left-width-12;left=Math.max(12,Math.min(left,innerWidth-width-12));top=Math.max(12,Math.min(top,innerHeight-height-12));graphPreview.style.left=left+'px';graphPreview.style.top=top+'px';}
function showGraphPreview(owner,pin=false){clearTimeout(graphTimer);const template=byId(owner.dataset.preview);if(!template)return;if(graphPinned&&!pin&&graphOwner!==owner)return;if(graphOwner!==owner){if(graphOwner)graphOwner.removeAttribute('aria-expanded');graphPreview.replaceChildren(template.content.cloneNode(true));}graphOwner=owner;graphPinned=pin||graphPinned;owner.setAttribute('aria-expanded','true');owner.setAttribute('aria-controls','graph-preview');graphPreview.hidden=false;placeGraphPreview(owner);}
function delayedGraphDismiss(){if(graphPinned)return;clearTimeout(graphTimer);graphTimer=setTimeout(()=>{if(!graphPreview.matches(':hover')&&!graphPreview.contains(document.activeElement)&&graphOwner!==document.activeElement)dismissGraphPreview();},180);}
graphPreview.addEventListener('pointerenter',()=>clearTimeout(graphTimer));graphPreview.addEventListener('pointerleave',delayedGraphDismiss);
graphPreview.addEventListener('focusout',event=>{if(!graphPreview.contains(event.relatedTarget)&&event.relatedTarget!==graphOwner)dismissGraphPreview();});
graphPreview.addEventListener('click',event=>{if(event.target.closest('.graph-preview-close')){const owner=graphOwner;dismissGraphPreview();owner?.focus();dismissGraphPreview();}else if(event.target.closest('a'))dismissGraphPreview();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!graphPreview.hidden){const owner=graphOwner;dismissGraphPreview();if(graphPreview.contains(document.activeElement))owner?.focus();dismissGraphPreview();}});
document.addEventListener('pointerdown',event=>{if(!graphPreview.hidden&&!graphPreview.contains(event.target)&&!event.target.closest('[data-preview]'))dismissGraphPreview();});
window.addEventListener('resize',()=>{if(graphOwner)placeGraphPreview(graphOwner);});
window.addEventListener('scroll',event=>{if(graphOwner&&!graphPreview.contains(event.target))dismissGraphPreview();},true);
byId('graph-canvas').addEventListener('scroll',dismissGraphPreview);
function bindGraphPreview(owner){owner.addEventListener('pointerenter',event=>{if(event.pointerType!=='touch')showGraphPreview(owner);});owner.addEventListener('pointerleave',delayedGraphDismiss);owner.addEventListener('focus',()=>showGraphPreview(owner));owner.addEventListener('blur',event=>{if(!graphPreview.contains(event.relatedTarget))dismissGraphPreview();});owner.addEventListener('keydown',event=>{if(event.key===' '){event.preventDefault();showGraphPreview(owner,true);graphPreview.querySelector('button')?.focus();}});owner.addEventListener('pointerdown',event=>{if(event.pointerType==='touch'){owner.dataset.touchPreview='1';}});owner.addEventListener('click',event=>{if(owner.dataset.touchPreview){delete owner.dataset.touchPreview;event.preventDefault();event.stopPropagation();showGraphPreview(owner,true);}else dismissGraphPreview();});}
function draw(focus){dismissGraphPreview();focus=focus||graphData.initial_focus;const pages=graphData.views[focus]||[];if(!pages.length)return;graphPage%=pages.length;const page=pages[graphPage];const svg=graphEl('svg',{viewBox:'0 0 '+page.width+' '+page.height,style:'width:'+page.width+'px;min-width:'+page.width+'px',role:'group','aria-label':'Selected proof support graph'}),defs=graphEl('defs');
Object.entries(graphColors).forEach(([tone,color])=>{const marker=graphEl('marker',{id:'graph-'+tone+'-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto'});marker.append(graphEl('path',{d:'M0 0 L10 5 L0 10 Z',fill:color}));defs.append(marker);});svg.append(defs);
page.routes.forEach(route=>{const edge=graphData.edges[route.index],p=edge.presentation,target=graphNodes.get(edge.to),title=p.short_label+': '+p.meaning;const a=graphEl('a',{class:'graph-connection',href:'#'+target.detail_id,tabindex:0,'data-preview':p.preview_id,'aria-label':title});a.append(graphEl('title',{},title));a.append(graphEl('path',{class:'graph-edge-hit',d:route.d}));a.append(graphEl('path',{class:'graph-edge '+p.tone,style:'stroke:'+p.color+';stroke-width:'+p.width+';stroke-dasharray:'+(p.dash||'none'),d:route.d,'marker-end':'url(#'+p.marker+')'}));if(route.show_label!==false)a.append(graphEl('text',{class:'graph-edge-label',style:'text-anchor:'+(route.label_anchor||'middle'),x:route.label_x,y:route.label_y},route.label||p.short_label));bindGraphPreview(a);svg.append(a);});
page.node_ids.forEach(key=>{const n=graphNodes.get(key),d=n.display,[x,y]=page.positions[key],title=d.full_title+'. '+d.status_text;const a=graphEl('a',{class:'graph-node type-'+d.type.replaceAll(' ','-')+(key===page.focus?' graph-focal':''),href:'#'+n.detail_id,tabindex:0,'data-preview':d.preview_id,'aria-label':title});a.append(graphEl('title',{},title));a.append(graphEl('rect',{x,y,width:260,height:d.card_height,rx:9,style:'fill:'+d.fill+';stroke:'+d.accent+';stroke-dasharray:'+(d.variant?'5 3':'none')}));d.card_rows.forEach(row=>a.append(graphEl('text',{class:row.class,x:x+14,y:y+row.y},row.text)));bindGraphPreview(a);svg.append(a);});
byId('graph-canvas').replaceChildren(svg);byId('graph-canvas').scrollTop=0;byId('graph-canvas').scrollLeft=0;byId('graph-count').textContent=page.note;byId('graph-more').disabled=pages.length===1;
const legend=byId('graph-legend');if(legend){legend.replaceChildren();page.node_types.forEach(type=>{const n=graphData.nodes.find(n=>n.display.type===type),d=n.display,span=document.createElement('span'),key=document.createElement('i');key.className='graph-type-key';key.style.background=d.fill;key.style.borderColor=d.accent;span.append(key,document.createTextNode(d.type_label));legend.append(span);});page.edge_tones.forEach(tone=>{const p=graphData.edges.find(e=>e.presentation.tone===tone).presentation,span=document.createElement('span'),key=document.createElement('i');key.className='graph-line-key';key.style.borderColor=p.color;key.style.borderTopStyle=tone==='refutation'?'dashed':'solid';span.append(key,document.createTextNode(p.meaning));legend.append(span);});}}
function graphOptions(focus){const select=byId('graph-focus');select.replaceChildren();if(graphMode==='overview'){const option=document.createElement('option');option.value=graphData.initial_focus;option.textContent='All results in audit scope';select.append(option);}const ids=graphMode==='overview'?graphData.selection_ids:graphData.nodes.map(n=>n.id);ids.forEach(key=>{const node=graphNodes.get(key),option=document.createElement('option'),d=node.display;option.value=key;option.textContent=d.identity+' · '+(d.description||d.location||d.topic);select.append(option);});select.value=focus;if(!select.value)select.value=graphData.initial_focus;const label=byId('graph-focus-label');if(label)label.textContent=graphMode==='overview'?'Find a manuscript result':'Focus on a result or input';const convention=byId('graph-convention');if(convention)convention.textContent=graphData.convention;}
function setGraphMode(mode,focus){if(mode==='overview'&&!data.overview)return;if(graphMode==='overview')graphOverviewFocus=byId('graph-focus').value||graphOverviewFocus;else graphDetailFocus=byId('graph-focus').value||graphDetailFocus;graphMode=mode;graphData=mode==='overview'?data.overview:data.graph;graphNodes=new Map(graphData.nodes.map(n=>[n.id,n]));graphPage=0;if(mode==='detail'&&!focus&&data.overview){const group=data.overview.nodes.find(n=>n.id===graphOverviewFocus);focus=group?.result_ids?.includes(graphDetailFocus)?graphDetailFocus:group?.result_ids?.[0]||graphDetailFocus;}if(mode==='overview'&&!focus)focus=data.overview.result_to_group[graphDetailFocus]||graphOverviewFocus;focus=focus||graphData.initial_focus;graphOptions(focus);const control=byId('graph-mode');if(control)control.value=mode;draw(byId('graph-focus').value);}
function resetGraph(){graphPage=0;graphOverviewFocus=data.overview?.initial_focus;graphDetailFocus=data.graph.initial_focus;setGraphMode(data.overview?'overview':'detail',data.overview?.initial_focus||data.graph.initial_focus);}
byId('graph-mode')?.addEventListener('change',event=>setGraphMode(event.target.value));
document.addEventListener('click',event=>{const link=event.target.closest('[data-graph-detail]');if(link){setGraphMode('detail',link.dataset.graphDetail);}});
byId('graph-focus').addEventListener('change',event=>{graphPage=0;draw(event.target.value);if(graphMode==='overview')graphOverviewFocus=event.target.value;else graphDetailFocus=event.target.value;});byId('graph-more').addEventListener('click',()=>{graphPage++;draw(byId('graph-focus').value);});resetGraph();
"""
