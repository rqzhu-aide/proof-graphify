"""Overview presentation using the skill's bundled common formula renderer."""
from __future__ import annotations

import re

def __getattr__(name):
    # Defer core imports until the database entry point has checked its bundle.
    if name in {"CONFIGURATION", "MATHML_NS", "_argument_operator", "_convert",
                "_group_scripted_binomials", "_independence_symbol",
                "_sized_named_bars", "_spans"}:
        from paper_core import math_render
        return getattr(math_render, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def render_text(text: str, diagnostics=None) -> str:
    """Preserve the overview's existing per-expression diagnostic shape."""
    from paper_core.math_render import render_text as _render_text

    local = [] if diagnostics is not None else None
    markup = _render_text(text, diagnostics=local)
    if local:
        diagnostics.extend({key: value for key, value in row.items() if key != "kind"} for row in local)
    return markup


def group_diagnostics(diagnostics) -> list[dict]:
    """Summarize repeated display failures without discarding their locations.

    Reasons already identify an unsupported command when available, so one
    correction can be located across several records. The input's full
    per-expression evidence remains untouched.
    """
    groups = {}
    for row in diagnostics:
        reason = row["reason"]
        group = groups.setdefault(reason, {"reason": reason, "count": 0,
                                           "locations": [], "example": row["excerpt"]})
        group["count"] += 1
        location = {key: row[key] for key in ("collection", "id", "field") if key in row}
        if location and location not in group["locations"]:
            group["locations"].append(location)
    return list(groups.values())


def render_scope(text: str, diagnostics=None) -> dict[str, str]:
    """Render a first-paragraph preview and optional full scope disclosure.

    The preview keeps the existing 100-word limit, extending a cutoff to the
    end of any explicit math it crosses. Paragraph breaks inside math are
    ignored. A shortened lead retains the full original in the disclosure;
    otherwise only later paragraphs are disclosed. Repeated preview formulas
    are displayed twice but diagnosed only once, in the complete disclosure.
    """
    from paper_core.math_render import _spans

    original = str(text or "").strip()
    spans = list(_spans(original))
    paragraph = next((match for match in re.finditer(r"\n\s*\n", original)
                      if not any(start < match.end() and end > match.start()
                                 for start, end, _, _ in spans)), None)
    lead = original[:paragraph.start()] if paragraph else original
    remainder = original[paragraph.end():].strip() if paragraph else ""
    words = list(re.finditer(r"\S+", lead))
    if len(words) > 100:
        cutoff = words[100].start()
        for start, end, _, _ in spans:
            if start < cutoff < end:
                cutoff = end
                break
        preview = lead[:cutoff].rstrip()
        if cutoff < len(lead):
            preview += "…"
        return {"lead_html": render_text(preview),
                "details_html": render_text(original, diagnostics=diagnostics)}
    return {"lead_html": render_text(lead.strip(), diagnostics=diagnostics),
            "details_html": render_text(remainder, diagnostics=diagnostics)}
