"""HTML report publication, kept separate from mathematical work identity."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

HTML_REPORT = "proofcheck-report.html"
LEGACY_HTML_REPORT = "audit/06_reports/FINAL_REPORT.html"
MARKDOWN_REPORT = "audit/06_reports/FINAL_REPORT.md"


def uses_html(manifest: dict[str, Any]) -> bool:
    contract = manifest.get("report_contract")
    return isinstance(contract, dict) and contract.get("version") == 2


def primary_report(manifest: dict[str, Any]) -> str:
    """Use the declared supported location, including already sealed reports."""
    value = manifest.get("report_contract", {}).get("primary")
    if value not in (HTML_REPORT, LEGACY_HTML_REPORT):
        raise ValueError("report_contract.primary must be proofcheck-report.html or audit/06_reports/FINAL_REPORT.html")
    return value


def renderer_identity(pc: Any) -> str:
    directory = Path(pc.__file__).resolve().parent
    identity = {
        name: pc.sha256_portable_text_file(directory / name)
        for name in ("proofcheck_report.py", "proofcheck_release.py", "proofcheck_math.py",
                     "proofcheck_graph.py", "proofcheck_labels.py")
    }
    identity["math_converter"] = pc.report_renderer().math_renderer().renderer_info()
    return pc.canonical_sha256(identity)


def contract(pc: Any, *, markdown: bool = False) -> dict[str, Any]:
    return {"version": 2, "primary": HTML_REPORT,
            "markdown_export": markdown, "renderer_sha256": renderer_identity(pc)}


def declarations(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    paths = [primary_report(manifest)]
    if manifest.get("report_contract", {}).get("markdown_export") is True:
        paths.append(MARKDOWN_REPORT)
    # These files are presentations of one report, with one reconciliation duty.
    return [{"id": "R001", "role": "user_facing_report", "path": path,
             "sha256": "", "issue_ids": [], "overall_verdict": "inconclusive"}
            for path in paths]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _projection(pc: Any, root: Path, manifest: dict[str, Any], *, final: bool,
                when: str | None) -> dict[str, Any]:
    return pc.report_renderer().build_report_projection(
        pc, root, final=final, finalized_at=when,
        report_context=manifest.get("report_context", {}), manifest_override=manifest)


def _render(pc: Any, root: Path, manifest: dict[str, Any], *, final: bool,
            when: str | None) -> tuple[dict[str, Any], dict[str, str]]:
    renderer = pc.report_renderer()
    projection = _projection(pc, root, manifest, final=final, when=when)
    html = renderer.render_report(projection)
    errors = renderer.validate_html(html, projection)
    if errors:
        raise ValueError("Report rendering failed: " + "; ".join(errors))
    outputs = {primary_report(manifest): html}
    if manifest["report_contract"].get("markdown_export") is True:
        outputs[MARKDOWN_REPORT] = renderer.render_markdown(projection)
    return projection, outputs


def _bind_outputs(pc: Any, manifest: dict[str, Any], outputs: dict[str, str],
                  projection: dict[str, Any]) -> None:
    issue_ids = sorted(str(item["id"]) for item in projection.get("issues", [])
                       if isinstance(item, dict) and item.get("id"))
    assessment = manifest.get("audit_scope", {}).get("overall_assessment", "inconclusive")
    manifest["report_deliverables"] = declarations(manifest)
    for record in manifest["report_deliverables"]:
        record.update(sha256=pc.sha256_text(outputs[record["path"]]),
                      issue_ids=issue_ids, overall_verdict=assessment)


def validate(pc: Any, root: Path, manifest: dict[str, Any], *,
             final: bool = True, outputs_override: dict[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    value = manifest.get("report_contract", {})
    if not uses_html(manifest):
        return ["Unsupported report_contract; expected version 2"]
    try:
        primary_report(manifest)
    except ValueError as exc:
        return [str(exc)]
    if type(value.get("markdown_export")) is not bool:
        errors.append("report_contract.markdown_export must be boolean")
    if value.get("renderer_sha256") != renderer_identity(pc):
        errors.append("Report renderer changed; regenerate reports and finalize again")
    release = manifest.get("report_release", {})
    if not isinstance(release, dict):
        return errors + ["report_release must be an object"]
    when = release.get("finalized_at")
    if final and (release.get("status") != "FINAL" or not pc.is_nonempty_string(when)):
        errors.append("HTML report has no finalized snapshot metadata")
    try:
        projection, expected = _render(pc, root, manifest, final=final, when=when)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return errors + [f"Cannot derive HTML report: {exc}"]
    if release.get("projection_sha256") != pc.canonical_sha256(projection):
        errors.append("Report projection is stale or inconsistent with canonical evidence")
    records = manifest.get("report_deliverables")
    if not isinstance(records, list):
        return errors + ["report_deliverables must be a list"]
    expected_records = copy.deepcopy(manifest)
    _bind_outputs(pc, expected_records, expected, projection)
    if records != expected_records["report_deliverables"]:
        errors.append("report_deliverables disagree with the generated report projection")
    for relative, text in expected.items():
        path, valid = pc.canonical_artifact_path(root, relative, "report deliverable", errors)
        if outputs_override is not None:
            if outputs_override.get(relative) != text:
                errors.append(f"{relative} differs from the canonical rendered report")
        elif valid and not path.is_file():
            errors.append(f"Report deliverable missing: {relative}")
        elif valid and path.read_bytes() != text.encode("utf-8"):
            errors.append(f"{relative} differs from the canonical rendered report")
    return errors


def render_working(pc: Any, root: Path) -> dict[str, Any]:
    path, manifest, errors = pc.load_audit_manifest(root)
    if errors:
        raise ValueError("; ".join(errors))
    if not uses_html(manifest):
        raise ValueError("Legacy Markdown audit: run migrate-report explicitly first")
    redirect_errors = pc.audit_internal_redirect_errors(root)
    if redirect_errors:
        raise ValueError("; ".join(redirect_errors))
    baseline = pc.sha256_file(path)
    manifest = copy.deepcopy(manifest)
    manifest["report_contract"]["renderer_sha256"] = renderer_identity(pc)
    projection, outputs = _render(pc, root, manifest, final=False, when=None)
    _bind_outputs(pc, manifest, outputs, projection)
    manifest.setdefault("completion", {})["final_report_ready"] = False
    manifest["report_release"] = {"status": "NONFINAL", "finalized_at": None,
                                  "projection_sha256": pc.canonical_sha256(projection)}
    pc.transactional_write_texts(
        [(root / relative, text) for relative, text in outputs.items()] + [(path, _json(manifest))],
        expected_sha256={path: baseline})
    return {"report": str(root / primary_report(manifest)), "delivery_status": "NONFINAL",
            "projection_sha256": manifest["report_release"]["projection_sha256"]}


def migrate(pc: Any, root: Path, *, markdown: bool = False,
            top_level: bool = False) -> dict[str, Any]:
    path, manifest, errors = pc.load_audit_manifest(root)
    if errors:
        raise ValueError("; ".join(errors))
    if uses_html(manifest) and top_level and primary_report(manifest) != HTML_REPORT:
        return relocate(pc, root)
    if uses_html(manifest):
        return render_working(pc, root)
    redirect_errors = pc.audit_internal_redirect_errors(root)
    if redirect_errors:
        raise ValueError("; ".join(redirect_errors))
    # Migration changes presentation only. It never updates protocol, ledgers,
    # calibration, or independent review records to make stale work look current.
    baseline = pc.sha256_file(path)
    old_report = root / MARKDOWN_REPORT
    archived: list[tuple[Path, str | bytes]] = []
    history = root / "audit/06_reports/history" / ("report-v1-" + baseline[:16])
    for prior in (path, old_report, root / "audit/06_reports/FINALIZATION.json"):
        if prior.is_file():
            target = history / prior.name
            if target.exists():
                raise ValueError(f"Refusing to overwrite report history: {target}")
            archived.append((target, prior.read_bytes()))
    context = copy.deepcopy(manifest.get("report_context", {}))
    if old_report.is_file():
        import re
        old = pc.read_text(old_report)
        for label in ("Files and results checked", "Description of checked scope",
                      "Mathematical confidence", "Final confidence",
                      "Tooling, extraction, or rendering limitations",
                      "Limits of certification", "Mathematical uncertainty"):
            match = re.search(r"^- " + re.escape(label) + r":[ \t]*(.*?)(?=\n- [^\n]+:|\n#{1,6} |\Z)",
                              old, re.MULTILINE | re.DOTALL)
            if match and match[1].strip():
                context.setdefault(label, match[1].strip())
    manifest["report_context"] = context
    # Keep an existing Markdown deliverable as a generated secondary export;
    # its original bytes remain in history. New audits default to HTML only.
    manifest["report_contract"] = contract(pc, markdown=markdown or old_report.is_file())
    manifest["report_deliverables"] = declarations(manifest)
    manifest.setdefault("completion", {})["final_report_ready"] = False
    projection, outputs = _render(pc, root, manifest, final=False, when=None)
    _bind_outputs(pc, manifest, outputs, projection)
    manifest["report_release"] = {"status": "NONFINAL", "finalized_at": None,
                                  "projection_sha256": pc.canonical_sha256(projection)}
    guards = {path: baseline}
    for prior in (old_report, root / "audit/06_reports/FINALIZATION.json"):
        if prior.is_file():
            guards[prior] = pc.sha256_file(prior)
    pc.transactional_write_texts(archived + [(root / relative, text) for relative, text in outputs.items()]
                                 + [(path, _json(manifest))], expected_sha256=guards)
    return {"report": str(root / HTML_REPORT), "delivery_status": "NONFINAL",
            "projection_sha256": manifest["report_release"]["projection_sha256"],
            "history": str(history)}


def relocate(pc: Any, root: Path) -> dict[str, Any]:
    """Explicitly renew a legacy HTML location without changing proof records."""
    path, manifest, errors = pc.load_audit_manifest(root)
    errors.extend(pc.audit_internal_redirect_errors(root))
    if errors:
        raise ValueError("; ".join(errors))
    old_relative = primary_report(manifest)
    if old_relative == HTML_REPORT:
        return render_working(pc, root)
    record_path, errors = pc.finalization_record_path(manifest, root)
    if errors:
        raise ValueError("; ".join(errors))
    if (root / HTML_REPORT).exists():
        raise ValueError("Top-level report already exists outside the active declaration; preserve or remove it explicitly before relocation")
    baseline = pc.audit_state_manifest(root)
    guards = {root / row["file"]: row["sha256"] for row in baseline}
    digest = pc.sha256_file(path)
    history = root / "audit/06_reports/history" / ("report-location-" + digest[:16])
    archived: list[tuple[Path, bytes]] = []
    old_report = root / old_relative
    for prior in (path, old_report, record_path):
        if prior.is_file():
            target = history / prior.name
            if target.exists():
                raise ValueError(f"Refusing to overwrite report history: {target}")
            archived.append((target, prior.read_bytes()))
    manifest = copy.deepcopy(manifest)
    manifest["report_contract"]["primary"] = HTML_REPORT
    manifest["report_contract"]["renderer_sha256"] = renderer_identity(pc)
    manifest.setdefault("completion", {})["final_report_ready"] = False
    projection, outputs = _render(pc, root, manifest, final=False, when=None)
    _bind_outputs(pc, manifest, outputs, projection)
    manifest["report_release"] = {"status": "NONFINAL", "finalized_at": None,
                                  "projection_sha256": pc.canonical_sha256(projection)}
    if pc.audit_state_manifest(root) != baseline:
        raise ValueError("Audit state changed while relocating its report; retry relocation")
    pc.transactional_write_texts(
        archived + [(root / relative, text) for relative, text in outputs.items()]
        + [(path, _json(manifest))], expected_sha256=guards,
        expected_absent=[destination for destination, _ in archived] + [root / HTML_REPORT],
        deletes=[prior for prior in (old_report, record_path) if prior.is_file()])
    return {"report": str(root / HTML_REPORT), "delivery_status": "NONFINAL",
            "projection_sha256": manifest["report_release"]["projection_sha256"],
            "history": str(history), "next_action": "Review the renewed report, then run finalize and delivery-check."}


def presentation_refresh_note(pc: Any, root: Path, freshness: dict[str, Any]) -> str | None:
    """Explain renderer-only staleness only after independent evidence identity checks."""
    errors = freshness.get("current_gate_errors", [])
    report_errors = ("Report renderer changed;", "Report projection is stale or inconsistent",
                     "report_deliverables disagree with the generated report projection",
                     "proofcheck-report.html differs from the canonical rendered report",
                     "audit/06_reports/FINAL_REPORT.html differs from the canonical rendered report",
                     "audit/06_reports/FINAL_REPORT.md differs from the canonical rendered report")
    if not errors or not any(error.startswith(report_errors[0]) for error in errors):
        return None
    if any(not error.startswith(report_errors) for error in errors):
        return None
    changes = freshness.get("artifact_changes")
    if freshness.get("record_status") != "passed" or not isinstance(changes, dict):
        return None
    if any(changes.get(key) != [] for key in ("added", "removed", "changed")):
        return None
    permitted = {"Current finalization-gate result differs from the recorded result",
                 "A passed finalization record no longer passes the full gate"}
    if any(reason not in permitted for reason in freshness.get("stale_reasons", [])):
        return None
    try:
        _, manifest, failures = pc.load_audit_manifest(root)
        source_failures = pc.source_snapshot_freshness_errors(root, manifest) if not failures else failures
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return None
    if source_failures:
        return None
    return ("The sealed audit records and locked sources are unchanged. The report needs "
            "regeneration for the current renderer, followed by finalize and delivery-check. "
            "This does not change the recorded mathematical judgments.")


def finalize(pc: Any, root: Path) -> tuple[list[str], dict[str, Any]]:
    path, manifest, errors = pc.load_audit_manifest(root)
    if errors:
        return errors, {"delivery_status": "NONFINAL", "errors": len(errors)}
    redirect_errors = pc.audit_internal_redirect_errors(root)
    if redirect_errors:
        return redirect_errors, {"delivery_status": "NONFINAL", "errors": len(redirect_errors)}
    pc.sync_workflow_views(root)
    record_path, errors = pc.finalization_record_path(manifest, root)
    if errors or not pc.finalization_target_is_safe(record_path):
        return errors or ["Unsafe finalization path"], {"delivery_status": "NONFINAL"}
    baseline_rows = pc.audit_state_manifest(root, record_path)
    guard = {root / row["file"]: row["sha256"] for row in baseline_rows}
    snapshot = manifest.get("source_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("files"), list):
        return ["source_snapshot.files must be a list"], {"delivery_status": "NONFINAL"}
    for source in snapshot["files"]:
        if not (isinstance(source, dict) and pc.is_nonempty_string(source.get("file"))
                and pc.is_nonempty_string(source.get("sha256"))):
            return ["source_snapshot file entries require file and sha256"], {"delivery_status": "NONFINAL"}
        guard[pc.resolve_stored_path(source["file"], root)] = source["sha256"]
    progress_path = root / "PROGRESS.json"
    recorded, errors = pc.load_json_object(progress_path, "progress state")
    if errors:
        return errors, {"delivery_status": "NONFINAL", "errors": len(errors)}
    _, issues, _, issue_errors = pc.load_issue_log(root)
    with pc.gate_context_snapshot(root):
        derived, derive_errors = pc.derive_progress_records(root, manifest, recorded, issues)
    candidate_progress = copy.deepcopy(recorded)
    for field in ("completed_units", "conditional_units", "in_progress_units", "not_started_units",
                  "blocked_units", "open_high_priority_issues", "source_or_parser_limits"):
        if field in derived:
            candidate_progress[field] = derived[field]
    candidate_progress.update(status="complete", current_pass=8)
    # Preserve the active unit through the gate: unfinished work cannot be hidden
    # by writing a completed checkpoint.
    errors, result = pc.check_audit_finalization(root, progress_override=candidate_progress,
                                                check_reports=False)
    errors.extend(issue_errors + derive_errors)
    if errors:
        result.update(delivery_status="NONFINAL", errors=len(errors))
        return errors, result
    candidate_progress["next_action"] = (
        f"Audit finalized. Deliver {primary_report(manifest)} after delivery-check confirms FINAL.")
    when = pc.utc_now()
    manifest = copy.deepcopy(manifest)
    manifest["report_contract"]["renderer_sha256"] = renderer_identity(pc)
    projection, outputs = _render(pc, root, manifest, final=True, when=when)
    _bind_outputs(pc, manifest, outputs, projection)
    manifest.setdefault("completion", {})["final_report_ready"] = True
    manifest["report_release"] = {"status": "FINAL", "finalized_at": when,
                                  "projection_sha256": pc.canonical_sha256(projection)}
    errors, result = pc.check_audit_finalization(
        root, progress_override=candidate_progress, manifest_override=manifest,
        report_outputs_override=outputs)
    if errors:
        result.update(delivery_status="NONFINAL", errors=len(errors))
        return errors, result
    writes = [(root / relative, text) for relative, text in outputs.items()]
    writes.extend([(path, _json(manifest)), (progress_path, _json(candidate_progress))])
    # Compute the future sealed state in memory; no report embeds this digest.
    future = {row["file"]: row["sha256"] for row in baseline_rows}
    for destination, text in writes:
        future[destination.relative_to(root).as_posix()] = pc.sha256_text(text)
    artifact_rows = [{"file": key, "sha256": future[key]} for key in sorted(future)]
    record = {"finalization_schema_version": 1, "status": "passed", "generated_utc": when,
              "protocol": pc.protocol_identity(),
              "source_snapshot_sha256": manifest.get("source_snapshot", {}).get("sha256"),
              "artifact_manifest": artifact_rows,
              "audit_state_sha256": pc.canonical_sha256(artifact_rows), "errors": []}
    record["record_payload_sha256"] = pc.finalization_payload_sha256(record)
    # A concurrent addition/removal must also prevent publication.
    if pc.audit_state_manifest(root, record_path) != baseline_rows:
        raise ValueError("Audit state changed while preparing the report; retry finalization")
    writes.append((record_path, _json(record)))
    pc.transactional_write_texts(writes, expected_sha256=guard)
    freshness = pc.check_finalization_freshness(root)
    if not freshness.get("usable_finalization"):
        errors = list(freshness.get("current_gate_errors", [])) + list(freshness.get("stale_reasons", []))
        return errors or ["Published state failed delivery-check"], {
            "delivery_status": "NONFINAL", "usable_finalization": False}
    result.update(delivery_status="FINAL", usable_finalization=True,
                  finalization_record=str(record_path), report=str(root / primary_report(manifest)), errors=0)
    return [], result
