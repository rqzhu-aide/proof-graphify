"""Resolve optional reviewed PDF labels without changing mathematical records.

The review note is an authored assertion of source/PDF correspondence. Hash and
anchor checks establish freshness and binding, not that the review is correct.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path, PureWindowsPath
from typing import Any


_KINDS = {"assumption", "definition", "lemma", "proposition", "theorem", "corollary"}
_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = r"(?:[A-Z]|[IVXLCDM]+|[0-9]+)(?:\.[A-Z0-9]+)*[a-z]?"
_PART = r"(?:\s?\([a-z0-9ivxlcdm]+\))?"
_ANCHOR_FIELDS = ("file", "start_line", "end_line", "sha256")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _relative_file(value: Any) -> bool:
    # Reject drive paths and alternate streams even when running on POSIX.
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and ":" not in value and "\x00" not in value
            and not Path(value).is_absolute() and not PureWindowsPath(value).drive
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def _anchor(value: Any) -> tuple | None:
    if (not isinstance(value, dict) or not _relative_file(value.get("file"))
            or type(value.get("start_line")) is not int
            or type(value.get("end_line")) is not int
            or not 1 <= value["start_line"] <= value["end_line"]
            or not _digest(value.get("sha256"))):
        return None
    return tuple(value.get(field) for field in _ANCHOR_FIELDS)


def resolve_labels(root: Path, mapping: Any, source_snapshot_sha256: str,
                   results: list[dict], sources: list[dict]) -> dict:
    """Return valid reviewed labels by exact result id, plus display-only notes.

    Callers retain independently authenticated literal headings first. No input
    is mutated, no PDF or TeX parser runs, and no mathematical status is derived.
    """
    resolved: dict[str, dict] = {}
    notes: list[str] = []
    output = {"labels": resolved, "notes": notes}

    def note(reason: str, index: int | None = None) -> None:
        target = "Manuscript labels" if index is None else f"Manuscript label entry {index}"
        notes.append(f"{target}: {reason} Retained any independent literal heading; otherwise used the title and source location.")

    if mapping is None:
        return output
    if not isinstance(mapping, dict) or type(mapping.get("version")) is not int or mapping["version"] != 1:
        note("Ignored an unsupported or malformed display mapping.")
        return output
    if (not _digest(source_snapshot_sha256)
            or mapping.get("source_snapshot_sha256") != source_snapshot_sha256):
        note("Ignored a stale or unbound source snapshot.")
        return output
    pdf = mapping.get("pdf")
    if not isinstance(pdf, dict) or not _relative_file(pdf.get("path")) or not _digest(pdf.get("sha256")):
        note("Ignored a missing or invalid audit-relative PDF path or fingerprint.")
        return output
    try:
        base = root.resolve()
        path = (base / pdf["path"]).resolve(strict=True)
        if not path.is_relative_to(base) or not path.is_file():
            raise ValueError("PDF is outside the audit or is not a file")
        with path.open("rb") as stream:
            if re.fullmatch(rb"%PDF-[12]\.[0-9]", stream.read(8)) is None:
                raise ValueError("PDF header is unavailable")
            stream.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            fingerprint = digest.hexdigest()
        if fingerprint != pdf["sha256"]:
            raise ValueError("PDF fingerprint changed")
    except (OSError, ValueError, RuntimeError):
        note("Ignored an unavailable, changed, invalid, or externally redirected PDF.")
        return output
    entries = mapping.get("entries")
    if not isinstance(entries, list):
        note("Ignored a mapping whose entries are not a list.")
        return output

    result_groups: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            result_groups[row["id"]].append(row)
    source_groups: dict[str, list[dict]] = defaultdict(list)
    for row in sources:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            source_groups[row["id"]].append(row)
    duplicates = Counter(row["result_id"] for row in entries
                         if isinstance(row, dict) and isinstance(row.get("result_id"), str))
    candidates: list[dict] = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("result_id"), str):
            note("Ignored a malformed result binding.", index)
            continue
        result_id = entry["result_id"]
        matching = result_groups.get(result_id, [])
        if duplicates[result_id] != 1 or len(matching) != 1:
            note("Ignored a duplicate or unknown result binding.", index)
            continue
        result = matching[0]
        if (not isinstance(entry.get("unit_id"), str) or not entry["unit_id"]
                or not isinstance(entry.get("conclusion_id"), str) or not entry["conclusion_id"]
                or entry["unit_id"] != result.get("unit_id")
                or entry["conclusion_id"] != result.get("conclusion_id")):
            note("Ignored a unit or conclusion binding that does not match the result.", index)
            continue
        kind = result.get("kind")
        if (not isinstance(kind, str) or kind not in _KINDS or str(result.get("source_environment", "")).endswith("*")
                or result.get("separate_assertion") is True):
            note("Ignored numbering for an unnumbered, separate, or non-manuscript result.", index)
            continue
        anchor = _anchor(entry.get("statement_anchor"))
        source_ids = result.get("statement_source_ids")
        bound_sources = [source_groups[sid][0] for sid in source_ids
                         if isinstance(sid, str) and len(source_groups.get(sid, [])) == 1] if isinstance(source_ids, list) else []
        locked = [source for source in bound_sources
                  if anchor is not None and _anchor(source) == anchor and source.get("status") == "locked"
                  and isinstance(source.get("quote"), str)
                  and hashlib.sha256(source["quote"].encode("utf-8")).hexdigest() == anchor[3]]
        if len(locked) != 1:
            note("Ignored a missing, changed, or ambiguous locked statement anchor.", index)
            continue
        label, page = entry.get("label"), entry.get("pdf_page")
        label_match = re.fullmatch(re.escape(kind.capitalize()) + r" (" + _IDENTIFIER + r")" + _PART, label) if isinstance(label, str) else None
        if label_match is None or type(page) is not int or page < 1:
            note("Ignored an invalid printed label or physical PDF page.", index)
            continue
        review = entry.get("review")
        if (not isinstance(review, dict) or review.get("status") != "matched"
                or not isinstance(review.get("note"), str)
                or review["note"].strip().lower() in {"", "none", "n/a", "pending", "not reviewed", "not recorded"}):
            note("Ignored a label without a recorded source/PDF matching review.", index)
            continue
        literal = result.get("printed_label")
        if literal and label != literal:
            note("Ignored a PDF label that conflicts with an independent literal heading.", index)
            continue
        base_label = kind.capitalize() + " " + label_match[1]
        if any(other.get("unit_id") != entry["unit_id"]
               and other.get("printed_label") == base_label
               for group in result_groups.values() for other in group):
            note("Ignored a PDF number already assigned to another literal manuscript heading.", index)
            continue
        candidates.append({"index": index, "result_id": result_id, "unit_id": entry["unit_id"],
                           "anchor": anchor, "label": label, "base_label": base_label,
                           "pdf_page": page, "review_note": review["note"]})

    # Distinct conclusions may share a heading, but unrelated statements may
    # not borrow its identity. Parts may differ only under the same base label.
    label_bindings: dict[str, set[tuple]] = defaultdict(set)
    statement_labels: dict[tuple, set[str]] = defaultdict(set)
    label_pages: dict[str, set[int]] = defaultdict(set)
    for row in candidates:
        binding = (row["unit_id"], row["anchor"])
        label_bindings[row["base_label"]].add(binding)
        statement_labels[binding].add(row["base_label"])
        label_pages[row["label"]].add(row["pdf_page"])
    for row in candidates:
        if (len(label_bindings[row["base_label"]]) != 1
                or len(statement_labels[(row["unit_id"], row["anchor"])]) != 1
                or len(label_pages[row["label"]]) != 1):
            note("Ignored conflicting labels, statement bindings, or PDF pages.", row["index"])
            continue
        resolved[row["result_id"]] = {
            "label": row["label"], "pdf_page": row["pdf_page"],
            "provenance": {"kind": "reviewed_pdf", "source_snapshot_sha256": source_snapshot_sha256,
                           "pdf_path": pdf["path"], "pdf_sha256": pdf["sha256"],
                           "statement_anchor": dict(zip(_ANCHOR_FIELDS, row["anchor"])),
                           "review": {"status": "matched", "note": row["review_note"]}},
        }
    return output
