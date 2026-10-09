"""Small authoring helpers over the existing source locks and annotation compiler.

Mathematical judgments are required inputs. This module fills identities and
publishes the compiler's existing records; it does not certify those judgments.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def _read(core: Any, path: Path, description: str) -> dict:
    value, errors = core.load_json_object(path, description)
    if errors:
        raise ValueError(errors[0])
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _uses(registry: dict, unit_id: str) -> list[dict]:
    return [row for row in registry.get("internal_uses", [])
            if row.get("dependent_unit") == unit_id] + [
        row for result in registry.get("external_results", [])
        for row in result.get("uses", []) if row.get("dependent_unit") == unit_id]


def _input_state(core: Any, root: Path, extra: list[Path]) -> dict[Path, str]:
    # Guard evidence, including new/removed files, without reading generated HTML.
    paths = set(extra) | {root / "AUDIT_MANIFEST.json", root / "PROGRESS.json",
                          root / "audit/06_reports/ISSUE_LOG.json"}
    for directory in (root / "audit").iterdir():
        if not directory.is_dir() or directory.name == "06_reports":
            continue
        for path in directory.rglob("*"):
            if path.is_file() and "history" not in path.relative_to(directory).parts:
                if not path.name.startswith("."):
                    paths.add(path)
    manifest = _read(core, root / "AUDIT_MANIFEST.json", "audit manifest")
    for member in manifest.get("source_snapshot", {}).get("files", []):
        paths.add(core.resolve_stored_path(member["file"], root))
    registry = _read(core, root / "audit/03_dependencies/DEPENDENCY_REGISTRY.json", "dependency registry")
    for result in registry.get("external_results", []):
        for evidence in result.get("source_evidence", []):
            if isinstance(evidence, dict) and isinstance(evidence.get("file"), str):
                paths.add(core.resolve_stored_path(evidence["file"], root))
    for path in paths:
        if core.path_redirect_kind(path) is not None:
            raise ValueError(f"Submission input is redirected: {path}")
    return {path: core.sha256_file(path) for path in sorted(paths)}


def _same_inputs(core: Any, root: Path, extra: list[Path], expected: dict) -> None:
    if _input_state(core, root, extra) != expected:
        raise ValueError("Audit or authoring inputs changed during submission; rerun with the current packet")


def _prior_submission_evidence(core: Any, root: Path, receipt: dict) -> Path:
    relative = receipt.get("ledger_relative_file")
    if not isinstance(relative, str):
        raise ValueError("Prior submission receipt lacks its ledger location; inspect it before renewal")
    recorded = (root / relative).resolve()
    directory = (root / "audit/04_local_checks").resolve()
    if not recorded.is_relative_to(directory) or not recorded.name.endswith(".ledger.json"):
        raise ValueError("Prior submission receipt has an invalid ledger location")
    candidates = [recorded] + list((directory / "history").rglob(recorded.name))
    for path in candidates:
        if path.is_file() and core.path_redirect_kind(path) is None:
            record = _read(core, path, "prior primary ledger")
            if (record.get("unit_id") == receipt.get("unit_id") and
                    core.canonical_primary_ledger_sha256(record) == receipt.get("primary_ledger_sha256")):
                return path
    raise ValueError("Prior submitted primary evidence is missing or changed; preserve or recover it before renewal")


def _step_bindings(core: Any, ledger: dict, annotations: dict) -> tuple[dict, dict]:
    units, ranges = core.build_compiled_source_units(ledger, annotations["source_groups"])
    _, keys = core.prepare_compact_step_plans(annotations["steps"], units, ranges)
    uses: dict[str, list[str]] = {}
    for step in annotations["steps"]:
        for premise in step["inputs"]:
            if premise.get("kind") == "dependency":
                uses.setdefault(premise["reference"], []).append(keys[step["key"]])
    return keys, {key: sorted(set(ids)) for key, ids in uses.items()}


def _reviewed_status(core: Any, root: Path, use: dict, projected: dict, *, external: bool) -> str:
    errors: list[str] = []
    prefix = str(use.get("use_id"))
    compatibility, matrix_issues = core.validate_compatibility_matrix(
        use.get("compatibility_checks"), f"{prefix}.compatibility_checks", errors)
    components = [projected.get("source_status", "unchecked"), compatibility]
    required_issues = set(matrix_issues)
    if external:
        prerequisite, issues = core.validate_prerequisite_map(
            use.get("prerequisite_map"), root, f"{prefix}.prerequisite_map", errors)
        components.append(prerequisite)
        required_issues.update(issues)
    if not required_issues.issubset(set(use.get("issue_ids", []))):
        errors.append(f"{prefix}.issue_ids omit reviewed applicability findings")
    status = core.combine_dependency_statuses(components)
    if status == "unchecked":
        errors.append(f"{prefix}: source or applicability review is unfinished")
    if status != "verified" and not use.get("issue_ids"):
        errors.append(f"{prefix}: unresolved or failed dependency requires its authored canonical issues")
    if errors:
        raise ValueError("Cannot submit dependency review: " + "; ".join(errors[:8]))
    return status


def _candidate_registry(core: Any, root: Path, registry: dict, packet: dict,
                        annotations: dict, bindings: dict) -> dict:
    candidate = copy.deepcopy(registry)
    authored = annotations.get("dependencies")
    # This parser also rejects duplicates, unknown fields, and missing statuses.
    direct, _ = core.load_compact_dependencies(authored)
    actual = {row["use_id"]: row for row in direct}
    expected = {row["use_id"]: row for row in
                core.compact_dependencies_from_packet(packet.get("dependencies"))}
    if set(actual) != set(expected) or set(bindings) != set(expected):
        raise ValueError("annotations.dependencies and step inputs must cover the current packet's exact direct-use set")
    projected = {row["use_id"]: (row, field == "direct_external_uses")
                 for field in ("direct_internal_uses", "direct_external_uses")
                 for row in packet["dependencies"].get(field, [])}
    for use in _uses(candidate, str(annotations["unit_id"])):
        use_id = use["use_id"]
        old, new = expected[use_id], actual[use_id]
        changed = {field for field in set(old) | set(new) if old.get(field) != new.get(field)}
        if changed - {"status"}:
            raise ValueError(f"{use_id}: reviewed dependency fields changed: {', '.join(sorted(changed))}; review a fresh packet")
        if changed and old.get("status") != "unchecked":
            raise ValueError(f"{use_id}: submit-unit cannot replace an existing dependency judgment; use explicit review renewal")
        status = _reviewed_status(core, root, use, projected[use_id][0], external=projected[use_id][1])
        if new.get("status") != status:
            raise ValueError(f"{use_id}: authored status {new.get('status')!r} disagrees with reviewed source/applicability status {status!r}")
        use["status"] = new["status"]
        use["step_ids"] = bindings[use_id]
    return candidate


def submit_unit(core: Any, *, ledger_path: Path, annotations_path: Path,
                packet_path: Path) -> dict:
    ledger_path, annotations_path, packet_path = (
        Path(path).resolve() for path in (ledger_path, annotations_path, packet_path))
    root = core.containing_audit_root(ledger_path)
    if root is None or not ledger_path.name.endswith(".skeleton.json"):
        raise ValueError("submit-unit requires a canonical source-locked .skeleton.json")
    if annotations_path.is_relative_to(root) or packet_path.is_relative_to(root):
        raise ValueError("Authoring annotations and packets must remain outside the canonical audit root")
    if annotations_path == packet_path:
        raise ValueError("Annotations and primary packet must be distinct files")
    output = ledger_path.with_name(ledger_path.name[:-len(".skeleton.json")] + ".ledger.json")
    extra = [ledger_path, annotations_path, packet_path]
    before = _input_state(core, root, extra)
    ledger = _read(core, ledger_path, "source-locked skeleton")
    annotations = _read(core, annotations_path, "compact annotations")
    core.validate_compile_skeleton(ledger, ledger_path)
    core.current_calibration_receipt(root)
    unit_id = str(ledger.get("unit_id"))
    receipt_path = root / "audit" / "07_runtime" / ("SUBMISSION_" + core.canonical_sha256(unit_id)[:16] + ".json")
    identity = {"skeleton_sha256": before[ledger_path], "annotation_sha256": before[annotations_path],
                "packet_sha256": before[packet_path]}
    registry_path = root / "audit" / "03_dependencies" / "DEPENDENCY_REGISTRY.json"
    registry = _read(core, registry_path, "dependency registry")
    if output.exists():
        previous = _read(core, receipt_path, "unit submission receipt") if receipt_path.is_file() else {}
        if (previous.get("inputs") == identity and previous.get("primary_ledger_sha256") ==
                core.canonical_primary_ledger_sha256(_read(core, output, "current primary ledger"))
                and previous.get("owned_uses_sha256") == core.canonical_sha256(_uses(registry, unit_id))):
            current = core.build_context_packet(root, unit_id, "primary", for_recompile=True)
            if current.get("work_context_sha256") == previous.get("work_context_sha256"):
                _same_inputs(core, root, extra, before)
                return {"command": "submit-unit", "status": "unchanged", "unit_id": unit_id,
                        "ledger": output.as_posix(), "next_action": "Continue with the independent challenge"}
        raise FileExistsError("A different or stale canonical ledger exists; preserve it through explicit audit renewal before resubmitting")
    prior_receipt = _read(core, receipt_path, "prior unit submission") if receipt_path.exists() else None
    prior_evidence = _prior_submission_evidence(core, root, prior_receipt) if prior_receipt else None
    if prior_evidence is not None and prior_evidence not in before:
        extra.append(prior_evidence)
        before[prior_evidence] = core.sha256_file(prior_evidence)
    packet = core.validate_current_primary_packet(ledger, ledger_path, packet_path)
    if annotations.get("context_binding_sha256") != packet.get("context_binding_sha256"):
        raise ValueError("annotations.context_binding_sha256 does not match the reviewed primary packet")
    # Validate all original mechanical and mathematical inputs before refreshing
    # only the status mirror explicitly authored by the reviewer.
    original = copy.deepcopy(annotations)
    authored_dependencies = original.get("dependencies")
    original["dependencies"] = core.compact_dependencies_from_packet(packet.get("dependencies"))
    diagnostics = core.annotation_preflight_diagnostics(ledger, ledger_path, original, packet, deep_validation=False)
    if diagnostics:
        raise ValueError("Annotation submission is incomplete: " + "; ".join(
            f"{row['pointer']}: {row['message']}" for row in diagnostics[:8]))
    annotations["dependencies"] = authored_dependencies
    keys, bindings = _step_bindings(core, ledger, annotations)
    updated_registry = _candidate_registry(core, root, registry, packet, annotations, bindings)
    candidate_packet = core.build_context_packet(
        root, unit_id, "primary", for_recompile=True, dependency_registry_override=updated_registry)
    prepared = copy.deepcopy(annotations)
    prepared["context_binding_sha256"] = candidate_packet["context_binding_sha256"]
    candidate = core.compile_annotation_data(ledger, prepared, ledger_path, candidate_packet)
    temporary = core._unique_sibling_temp_path(output)
    try:
        temporary.write_text(_json(candidate), encoding="utf-8", newline="\n")
        errors, summary = core.check_ledger_data(temporary, True)
        diagnostics = core.compiled_dependency_binding_diagnostics(candidate, summary, candidate_packet, prepared) if not errors else []
        if errors or diagnostics:
            raise ValueError("Submission validation failed: " + "; ".join(
                [*errors, *(f"{row['pointer']}: {row['message']}" for row in diagnostics)][:12]))
    finally:
        if temporary.exists():
            temporary.unlink()
    # One lock covers only publication. Validation uses an immutable input
    # baseline, so it never holds a workflow lock during expensive source reads.
    _same_inputs(core, root, extra, before)
    lock, lock_payload = core.acquire_migration_update_lock(root, "submit-unit")
    keep_lock = False
    try:
        _same_inputs(core, root, extra, before)
        payload = _json(candidate)
        receipt = {"version": 1, "unit_id": unit_id, "inputs": identity,
                   "ledger_sha256": core.hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                   "ledger_relative_file": output.relative_to(root).as_posix(),
                   "primary_ledger_sha256": core.canonical_primary_ledger_sha256(candidate),
                   "work_context_sha256": candidate["work_context_sha256"],
                   "owned_uses_sha256": core.canonical_sha256(_uses(updated_registry, unit_id))}
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        writes = [(output, payload), (receipt_path, _json(receipt))]
        expected_absent = [output]
        if prior_receipt is None:
            expected_absent.append(receipt_path)
        else:
            history = receipt_path.parent / "history/submissions" / (core.canonical_sha256(prior_receipt) + ".json")
            history.parent.mkdir(parents=True, exist_ok=True)
            if history.exists():
                if history.read_bytes() != receipt_path.read_bytes():
                    raise ValueError(f"Conflicting prior submission history: {history}")
                before[history] = core.sha256_file(history)
            else:
                writes.insert(0, (history, receipt_path.read_bytes()))
                expected_absent.append(history)
        if updated_registry != registry:
            writes.insert(0, (registry_path, _json(updated_registry)))
        core.transactional_write_texts(writes, expected_sha256=before, expected_absent=expected_absent)
    except core.MigrationRecoveryRequired:
        keep_lock = True
        raise
    finally:
        if not keep_lock:
            core.release_migration_update_lock(lock, lock_payload)
    return {"command": "submit-unit", "status": "submitted", "unit_id": unit_id,
            "ledger": output.as_posix(), "steps": len(candidate["steps"]),
            "bound_uses": len(bindings),
            "next_action": ("Archive the preserved prior ledger, then continue with the independent challenge"
                            if prior_evidence and prior_evidence.parent == output.parent
                            else "Continue with the independent challenge")}


def _draft_step_keys(core: Any, ledger: dict, annotations: dict) -> dict[str, str]:
    """Resolve source identities without requiring an authored mathematical review."""
    try:
        units, ranges = core.build_compiled_source_units(ledger, annotations.get("source_groups"))
    except (KeyError, TypeError) as exc:
        raise ValueError("Source lookup requires valid source_groups and locked source records") from exc
    steps = annotations.get("steps")
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")
    by_id = {unit["id"]: unit for unit in units}
    keys: dict[str, str] = {}
    counts: dict[str, int] = {}
    for index, step in enumerate(steps, 1):
        field = f"steps[{index}]"
        if not isinstance(step, dict):
            raise ValueError(f"{field} must be an object")
        key = step.get("key")
        if not core.is_nonempty_string(key):
            raise ValueError(f"{field}.key must be nonempty")
        if key in keys:
            raise ValueError(f"Duplicate compact step key {key}")
        lines = step.get("lines")
        if (not isinstance(lines, list) or len(lines) != 2
                or not all(core.is_int(line) for line in lines)):
            raise ValueError(f"{field}.lines must be [start, end]")
        unit_id = ranges.get(tuple(lines))
        if unit_id is None:
            raise ValueError(f"{field}.lines must exactly match one compiled source unit")
        if by_id[unit_id]["kind"] == "non_substantive":
            raise ValueError(f"{field} cannot annotate a non-substantive source unit")
        # The compiler orders by source unit, then by annotation position within
        # that unit. Other units and unfinished review fields cannot change its ID.
        offset = counts.get(unit_id, 0)
        base_id = "S" + unit_id[1:]
        keys[key] = base_id if offset == 0 else f"{base_id}.{offset}"
        counts[unit_id] = offset + 1
    return keys


def source_lookup(core: Any, *, ledger_path: Path, part: str = "proof",
                  lines: list[int] | None = None, annotations_path: Path | None = None,
                  step_key: str | None = None, packet_path: Path | None = None,
                  reference: str | None = None) -> dict:
    if part not in {"proof", "statement"}:
        raise ValueError("Source part must be proof or statement")
    if lines is not None and (not isinstance(lines, (list, tuple)) or len(lines) != 2
                             or not all(core.is_int(line) for line in lines)
                             or not 1 <= lines[0] <= lines[1]):
        raise ValueError("--lines requires an increasing pair of positive inclusive positions")
    if reference is not None and (lines is not None or step_key is not None
                                   or annotations_path is not None or part != "proof"):
        raise ValueError("--reference cannot be combined with line, step, or statement selection")
    if reference is None and packet_path is not None:
        raise ValueError("--packet is used only with --reference")
    if annotations_path is not None and step_key is None:
        raise ValueError("--annotations requires --step-key")
    if step_key is not None and (lines is not None or part != "proof"):
        raise ValueError("--step-key cannot be combined with --lines or statement selection")
    ledger_path = Path(ledger_path).resolve()
    ledger = _read(core, ledger_path, "source-locked skeleton")
    if (not ledger_path.name.endswith(".skeleton.json") or ledger.get("steps") != []
            or ledger.get("schema_version") != core.SCHEMA_VERSION):
        raise ValueError("Source lookup requires a source-locked .skeleton.json")
    # Reading a source should work before normalization is finished, but never
    # return stale locked prose as though it were the current manuscript.
    try:
        current = core.source_fragment_support().current(core.report_api(), ledger, ledger_path.parent)
        rows = ledger["source_lines"]
        first, last = core.source_coverage_bounds(ledger)
        if (core.sha256_text("\n".join(current)) != ledger["source"]["unit_sha256"]
                or len(rows) != last - first + 1 or len(rows) != len(current)
                or any(not isinstance(row, dict) or row.get("line") != first + offset or row.get("text") != text
                       or row.get("sha256") != core.sha256_text(text)
                       for offset, (row, text) in enumerate(zip(rows, current)))):
            raise ValueError("Source drift: proof text or locked source-line identity changed")
    except (KeyError, TypeError) as exc:
        raise ValueError("Source lookup requires complete, current locked source records") from exc
    if reference is not None:
        if packet_path is None:
            raise ValueError("Source reference lookup requires --packet")
        packet = core.validate_current_primary_packet(ledger, ledger_path, Path(packet_path).resolve())
        matches = [row for row in packet["inventory"]["reference_occurrences"]
                   if row.get("target") == reference or row.get("occurrence_id") == reference]
        if not matches:
            raise ValueError(f"No locked source reference matches {reference!r}")
        return {"unit_id": ledger["unit_id"], "reference": reference, "occurrences": matches}
    if step_key is not None:
        if annotations_path is None:
            raise ValueError("Step lookup requires --annotations")
        annotations = _read(core, Path(annotations_path).resolve(), "compact annotations")
        if not isinstance(ledger.get("obligation"), dict) or not core.is_nonempty_string(ledger.get("unit_id")):
            raise ValueError("Step lookup requires a source-locked obligation and unit identity")
        if (annotations.get("unit_id") != ledger.get("unit_id")
                or annotations.get("source_unit_sha256") != ledger["source"]["unit_sha256"]
                or annotations.get("obligation_sha256") != core.canonical_sha256(ledger["obligation"])):
            raise ValueError("Step lookup annotations do not bind this source-locked obligation")
        keys = _draft_step_keys(core, ledger, annotations)
        if step_key not in keys:
            raise ValueError(f"Unknown draft step key {step_key!r}")
        step = next(row for row in annotations["steps"] if row["key"] == step_key)
        lines = step["lines"]
        part = "proof"
    else:
        keys = {}
    if part == "statement":
        spans = ledger["obligation"].get("statement_spans", [])
        result = []
        for span in spans:
            errors: list[str] = []
            core.validate_locked_span(span, ledger_path.parent, "statement span", errors)
            if errors:
                raise ValueError("; ".join(errors))
            start, end = span["start_line"], span["end_line"]
            if lines is not None:
                start, end = lines
                if not span["start_line"] <= start <= end <= span["end_line"]:
                    continue
            path = core.resolve_stored_path(span["file"], ledger_path.parent)
            selected = core.locked_span(path, start, end, ledger_path.parent)
            result.append({"span": selected, "text": "\n".join(core.read_lines(path)[start - 1:end])})
        if not result:
            raise ValueError("Selected lines do not lie within a locked statement span")
        return {"unit_id": ledger["unit_id"], "part": part, "passages": result}
    if part != "proof":
        raise ValueError("Source part must be proof or statement")
    start, end = lines if lines is not None else core.source_coverage_bounds(ledger)
    records = [row for row in ledger["source_lines"] if start <= row["line"] <= end]
    if not records or len(records) != end - start + 1:
        raise ValueError("Selected coverage positions lie outside the locked proof")
    passages = []
    # Individual locations remain exact even across source fragments or files.
    for row in records:
        location = core.source_unit_location(ledger, {"lines": [row["line"], row["line"]]})
        passages.append({"position": row["line"], "source": location, "text": row["text"]})
    return {"unit_id": ledger["unit_id"], "part": part, "coverage_positions": [start, end],
            **({"step_key": step_key, "step_id": keys[step_key]} if step_key else {}), "lines": passages}
