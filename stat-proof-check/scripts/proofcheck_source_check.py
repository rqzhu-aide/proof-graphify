#!/usr/bin/env python3
"""Read-only source-layout triage using the unchanged proofcheck parser.

This helper neither authors audit records nor decides mathematical validity.
Its observations must be reviewed before they become manuscript advice.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


_CORE: Any = None
LIMITATION = (
    "This checks recognized source structure only. A recognized region may still "
    "omit part of an argument; inspect the statement and surrounding source. "
    "Mathematical review and audit finalization have not been performed."
)


def core() -> Any:
    global _CORE
    if _CORE is None:
        # A read-only probe should not create __pycache__ in the installation.
        sys.dont_write_bytecode = True
        path = Path(__file__).with_name("proofcheck.py")
        spec = importlib.util.spec_from_file_location("_proofcheck_source_core", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load parser: {path}")
        _CORE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CORE)
    return _CORE


def result_title(unit: dict[str, Any]) -> str:
    kind = str(unit.get("semantic_kind") or unit["environment"]).capitalize()
    title = " ".join(str(unit.get("statement_title") or "").split())
    return f'{kind} "{title}"' if title else kind


def location_text(span: dict[str, Any]) -> str:
    return f'{span["file"]}:{span["start_line"]}-{span["end_line"]}'


def outside_target_headings(
    inventory: dict[str, Any], files: list[Path], base: Path
) -> dict[str, list[dict[str, Any]]]:
    """Find inspection hints, never infer that a heading contains a proof."""
    parser = core()
    units = {unit["id"]: unit for unit in inventory["units"]}
    owners = inventory["label_owners"]
    found: dict[str, list[dict[str, Any]]] = {}
    for path in files:
        try:
            headings = parser.scan_section_headings(parser.read_text(path))
        except UnicodeError:
            continue  # The inventory retains the exact source decoding warning.
        shown = parser.relative_or_absolute(path, base)
        for index, heading in enumerate(headings):
            targets = {
                owners[label]["owner_unit_id"]
                for label in heading["target_labels"]
                if label in owners
                and owners[label].get("status") == "unique"
                and owners[label].get("owner_region") == "statement"
            }
            for target in sorted(targets):
                unit = units.get(target)
                if unit is None or not unit.get("proof_required"):
                    continue
                proof = unit.get("proof")
                if proof and proof["file"] == shown:
                    if proof["start_line"] <= heading["start_line"] <= proof["end_line"]:
                        continue
                    # The normal named heading immediately above its proof is
                    # not an additional passage. Do not skip intervening headings.
                    next_start = (headings[index + 1]["start_line"]
                                  if index + 1 < len(headings) else float("inf"))
                    if (heading["end_line"] < proof["start_line"]
                            <= heading["end_line"] + 4
                            and proof["start_line"] < next_start):
                        continue
                found.setdefault(target, []).append({
                    "file": shown,
                    "start_line": heading["start_line"],
                    "end_line": heading["end_line"],
                    "title": heading["title"],
                    "target_labels": heading["target_labels"],
                })
    return found


def check_source(args: argparse.Namespace) -> dict[str, Any]:
    parser = core()
    paper = args.paper.resolve()
    if paper.suffix.lower() == ".pdf":
        raise ValueError("Raw PDF is not parsed source. Supply LaTeX or a UTF-8 PDF transcription.")
    if not parser.read_text(paper).strip():
        raise ValueError(f"Source is empty: {paper}")
    project, entries, fls = parser.resolve_source_discovery_inputs(
        paper, args.input_kind, additional_source=args.additional_source,
        fls=args.fls, project_root=args.project_root,
    )
    if args.input_kind == "latex":
        closure = parser.discover_source_closure(
            paper, additional_files=[entry[0] for entry in entries], fls_file=fls,
            project_root=project, warning_path_base=paper.parent,
        )
    else:
        closure = {"files": [paper], "warnings": [parser.PDF_TRANSCRIPTION_WARNING],
                   "outside_project_inputs": []}
    files = closure["files"]
    inventory = parser.scan_formal_units(
        paper, source_files=files, source_warnings=closure["warnings"],
        path_identity_base=paper.parent,
    )
    identity_errors = parser.inventory_identity_errors(inventory["units"])
    if identity_errors:
        raise ValueError("; ".join(identity_errors))
    headings = outside_target_headings(inventory, files, paper.parent)
    results = []
    for unit in inventory["units"]:
        if not unit.get("proof_required"):
            continue
        proof = unit.get("proof")
        reasons = []
        boundary = None
        if proof is None:
            reasons.append({
                "kind": "unrecognized_association",
                "cause": "No proof passage was associated automatically. This does not establish that a proof is missing.",
            })
        else:
            boundary = parser.analyze_proof_region(
                parser.resolve_stored_path(proof["file"], paper.parent),
                proof["start_line"], target_unit_id=unit["id"], source_files=files,
            )
            if not (boundary.get("status") == "accepted"
                    and boundary.get("start_line") == proof["start_line"]
                    and boundary.get("end_line") == proof["end_line"]):
                reasons.append({
                    "kind": "unsupported_boundary",
                    "cause": "The associated span does not equal a complete region accepted by the current boundary checker.",
                })
            if unit["proof_association"].get("status") != "associated":
                reasons.append({
                    "kind": "association_needs_review",
                    "cause": "The parser requires source review to confirm this association.",
                })
        candidates = headings.get(unit["id"], [])
        if candidates:
            reasons.append({
                "kind": "target_heading_outside_proof",
                "cause": "Other headings refer to this result outside its recognized proof. They may be discussion or additional argument; inspect their contents.",
            })
        results.append({
            "unit_id": unit["id"], "result": result_title(unit),
            "statement": unit["statement"], "recognized_proof": proof,
            "boundary": boundary, "review_reasons": reasons,
            "candidate_headings": candidates,
        })
    warnings = list(dict.fromkeys(inventory["warnings"]))
    layout_warnings = [
        {"kind": "ambiguous_label_owner", "label": label,
         "locations": owner["locations"],
         "cause": "This label does not identify one source location and owner; inspect it before associating a proof."}
        for label, owner in inventory["label_owners"].items()
        if owner["status"] in {"duplicate", "ambiguous"}
    ]
    outside = closure["outside_project_inputs"]
    review = bool(warnings or layout_warnings or outside or not results
                  or any(row["review_reasons"] for row in results))
    return {
        "status": "review_required" if review else "no_layout_flags",
        "paper": paper.as_posix(), "input_kind": args.input_kind,
        "validator_sha256": parser.protocol_identity()["validator_sha256"],
        "source_files": [{"file": parser.relative_or_absolute(path, paper.parent),
                          "sha256": parser.sha256_file(path)} for path in files],
        "formal_units": len(inventory["units"]), "proof_required_units": len(results),
        "results": results, "parser_warnings": warnings,
        "layout_warnings": layout_warnings,
        "outside_project_inputs": outside,
        "limitation": LIMITATION,
        "next_action": (
            "Inspect flagged source locations before detailed proof review. Distinguish an omitted proof from an unsupported layout; test any proposed formatting revision on a temporary copy."
            if review else
            "Review the recognized inventory against the full source, then continue the normal calibrated audit."
        ),
    }


def markdown(report: dict[str, Any]) -> str:
    if report["status"] == "check_failed":
        return ("Source check could not run. Mathematical review was not performed.\n\n"
                + report["error"] + "\n\n" + report["next_action"] + "\n")
    flagged = [row for row in report["results"] if row["review_reasons"]]
    title = ("Source layout needs review before detailed proof checking."
             if report["status"] == "review_required" else "No automatic source-layout flags.")
    lines = [title, "", f'{report["formal_units"]} formal results or assumptions; '
             f'{report["proof_required_units"]} proof obligations; '
             f'{len(flagged)} result(s) flagged.', ""]
    for row in flagged[:5]:
        lines.append(f'- {row["result"]} ({location_text(row["statement"])}): '
                     + " ".join(reason["cause"] for reason in row["review_reasons"]))
        if row["candidate_headings"]:
            lines.append("  Inspect headings: " + ", ".join(
                location_text(item) for item in row["candidate_headings"][:5]) + ".")
    if len(flagged) > 5:
        lines.append(f'- {len(flagged) - 5} further result(s); use --format json for all locations.')
    if report["parser_warnings"]:
        lines.extend(["", f'{len(report["parser_warnings"])} parser warning(s). '
                      'Use --format json for the exact warnings and recognized ranges.'])
        for warning in report["parser_warnings"][:3]:
            shown = warning
            for row in sorted(report["results"], key=lambda item: len(item["unit_id"]), reverse=True):
                shown = shown.replace(row["unit_id"], row["result"])
            lines.append("- " + shown)
    if report["layout_warnings"]:
        lines.extend(["", f'{len(report["layout_warnings"])} label-association warning(s):'])
        for warning in report["layout_warnings"][:3]:
            places = ", ".join(f'{item["file"]}:{item["line"]}' for item in warning["locations"][:5])
            lines.append(f'- Label `{warning["label"]}` ({places}): {warning["cause"]}')
        lines.append("Use --format json for every label-association warning.")
    if report["outside_project_inputs"]:
        lines.extend(["", "Some recorder inputs are outside the project and excluded; inspect --format json."])
    if not report["proof_required_units"]:
        lines.extend(["", "No proof obligations were recognized. Check source completeness and the inventory manually."])
    lines.extend(["", report["next_action"], "", report["limitation"], ""])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", required=True, type=Path)
    parser.add_argument("--input-kind", required=True, choices=("latex", "pdf_transcription"))
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--additional-source", action="append", nargs=3,
                        metavar=("PATH", "REASON", "EVIDENCE"))
    parser.add_argument("--fls", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    started = time.perf_counter()
    try:
        report = check_source(args)
    except Exception as exc:
        # Diagnostic failure is never a successful source check. Keep the error
        # type for reproducibility without flooding the reader with a traceback.
        report = {"status": "check_failed", "error_type": type(exc).__name__,
                  "error": str(exc), "limitation": LIMITATION,
                  "next_action": "Resolve the source/access error and rerun this check. For an unexpected software error, preserve this diagnostic and stop dependent work."}
    report["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    print(json.dumps(report, ensure_ascii=False, indent=2)
          if args.format == "json" else markdown(report), end="\n")
    return {"no_layout_flags": 0, "review_required": 2, "check_failed": 1}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
