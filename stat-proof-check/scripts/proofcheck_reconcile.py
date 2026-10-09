"""Submit authored reconciliation through the existing challenge contracts.

The validator namespace is supplied by proofcheck.py. This convenience layer
never revises primary judgments or supplies missing mathematical reasoning.
"""
from __future__ import annotations

import json
import posixpath
from pathlib import Path
from types import SimpleNamespace
from typing import Any


FIELDS = {"reconciliation_schema_version", "unit_id", "status", "reconciled_verdict",
          "conclusions", "disagreements", "resolution", "issue_assessments"}
DECISIONS = ("verdict", "argument_status", "statement_status")


def _fail(errors: list[str]) -> None:
    if errors:
        raise ValueError("Cannot submit reconciliation: " + "; ".join(errors[:12]))


def validate_review(review: dict, packet: dict, ledger: dict, initial: dict,
                    pc: Any) -> list[str]:
    """Reuse exact conclusion/anchor checks; assess no mathematical proposition."""
    errors = []
    if set(review) != FIELDS:
        errors.append("Review needs exactly: " + ", ".join(sorted(FIELDS)))
    if type(review.get("reconciliation_schema_version")) is not int or review.get("reconciliation_schema_version") != 1:
        errors.append("reconciliation_schema_version must be 1")
    status = review.get("status")
    if not isinstance(status, str) or status not in {"agreed", "resolved", "unresolved"}:
        errors.append("status must be agreed, resolved, or unresolved")
        status = "invalid"
    disagreements = review.get("disagreements")
    if not isinstance(disagreements, list) or any(not pc.is_substantive_string(x) for x in disagreements):
        errors.append("disagreements must be a list of substantive reviewer accounts")
    if status == "agreed" and (disagreements != [] or review.get("resolution") != ""):
        errors.append("agreed requires no disagreements and an empty resolution")
    if status == "resolved" and (not disagreements or not pc.is_substantive_string(review.get("resolution"))):
        errors.append("resolved requires explicit disagreements and a substantive resolution")
    if status == "unresolved" and (not disagreements or review.get("resolution") != "" or review.get("reconciled_verdict") != "not_checked"):
        errors.append("unresolved requires explicit disagreements, empty resolution, and reconciled_verdict not_checked")
    rows = review.get("conclusions")
    verdicts = [r.get("verdict") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    aggregate = pc.expected_unit_status(verdicts) if verdicts and all(pc.is_enum_value(v, pc.UNIT_STATUSES) for v in verdicts) else "not_checked"
    response = {"response_schema_version": 2, "unit_id": review.get("unit_id"),
                "independence_level": initial["response"]["independence_level"],
                "challenger_verdict": aggregate if status == "unresolved" else review.get("reconciled_verdict"),
                "conclusions": rows, "issue_assessments": review.get("issue_assessments")}
    errors.extend(pc.validate_initial_challenge_response(response, packet))
    if status in {"agreed", "resolved"}:
        primary = pc.primary_challenge_snapshot(ledger)
        if primary["unit_status"] != review.get("reconciled_verdict"):
            errors.append("reconciled_verdict differs from primary judgment; revise and validate the primary ledger first")
        final = {r["conclusion_id"]: r for r in primary["conclusions"]}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            for field in DECISIONS:
                if row.get(field) != final.get(row.get("conclusion_id"), {}).get(field):
                    errors.append(f"{row.get('conclusion_id')}.{field} differs from primary judgment; revise and validate the primary ledger first")
    return errors


def render_review(review: dict, packet: dict, initial_ref: dict,
                  previous: dict | None, pc: Any) -> str:
    """Render the submitted reasons once with authenticated manuscript locations."""
    spans = pc.challenge_source_spans(packet)
    lines = [f"# Independent reconciliation of {review['unit_id']}", "",
             f"Reconciliation: {review['status']}. Final primary verdict: {review['reconciled_verdict']}.", "",
             f"Preserved first response: [{Path(initial_ref['artifact']).name}]({Path(initial_ref['artifact']).name}).",
             f"First-response SHA-256: `{initial_ref['sha256']}`.", ""]
    if previous:
        previous_link = posixpath.relpath(previous["artifact"], "audit/05_adversarial")
        lines += [f"Previous reconciliation retained: [{Path(previous['artifact']).name}]({previous_link}) (SHA-256 `{previous['sha256']}`).", ""]
    for row in review["conclusions"]:
        claim = next(r["claim"] for r in packet["obligation"]["conclusions"] if r["id"] == row["conclusion_id"])
        lines += [f"## {row['conclusion_id']}: {claim}", "",
                  f"Verdict: {row['verdict']}; written argument: {row['argument_status']}; statement: {row['statement_status']}.",
                  "", row["decisive_reason"], "", "Source evidence:", ""]
        for ref in row["source_refs"]:
            span = spans[ref["packet_pointer"]]
            name = span.get("source_member", span.get("source"))["name"]
            lines.append(f"- `{name}:{ref['start_line']}-{ref['end_line']}` (packet `{ref['packet_pointer']}`).")
        lines.append("")
    if review["disagreements"]:
        lines += ["## Disagreements", "", *["- " + x for x in review["disagreements"]], ""]
    if review["resolution"]:
        lines += ["## Resolution", "", review["resolution"], ""]
    if review["status"] == "unresolved":
        lines += ["This disagreement remains unresolved. Independent review is unfinished and cannot satisfy final delivery.", ""]
    for row in review["issue_assessments"]:
        lines += [f"## {row['issue_id']}: {row['assessment']}", "", row["target_assessment"], "", row["downstream_assessment"], ""]
    return "\n".join(lines).rstrip() + "\n"


def external_evidence_guards(root: Path, packet: dict, pc: Any) -> dict[Path, str]:
    """Guard the exact external documents in the reviewed packet, wherever stored."""
    results = packet.get("dependencies", {}).get("external_results", [])
    if not results:
        return {}
    registry, errors = pc.load_json_object(root / "audit/03_dependencies/DEPENDENCY_REGISTRY.json", "dependency registry")
    _fail(errors)
    catalog = {row["id"]: row for row in registry.get("external_results", [])}
    guards = {}
    for result in results:
        recorded = catalog.get(result["id"], {}).get("source_evidence", [])
        projected = result.get("source_evidence", [])
        if len(recorded) != len(projected):
            _fail([f"{result['id']}: external source set differs from the reviewed packet"])
        for row, selected in zip(recorded, projected):
            path = pc.resolve_stored_path(row["file"], root)
            digest = row.get("sha256")
            if digest != selected.get("sha256") or not path.is_file() or pc.sha256_file(path) != digest:
                _fail([f"{result['id']}: external source differs from the reviewed packet"])
            guards[path] = digest
    return guards


def unresolved_fields(review: dict, packet: dict, manifest: dict, initial: dict,
                      initial_ref: dict, primary: str) -> dict:
    targets = {r["id"]: r["target_contract_sha256"] for r in packet.get("issue_triggers", [])}
    return dict(required=True, status="disagreed", reconciled_verdict="not_checked",
                independence_level=initial["response"]["independence_level"],
                challenger_verdict=initial["response"]["challenger_verdict"],
                initial_response=initial_ref, disagreements=review["disagreements"], resolution="",
                issue_assessments=[dict(r, target_contract_sha256=targets[r["issue_id"]]) for r in review["issue_assessments"]],
                covered_issue_ids=sorted(targets), source_snapshot_sha256=manifest["source_snapshot"]["sha256"],
                challenged_ledger_sha256=primary, challenge_context_sha256=packet["context_binding_sha256"])


def cmd_submit_reconciliation(args: Any, pc: dict[str, Any]) -> int:
    api = SimpleNamespace(**pc)
    root = args.root.resolve()
    _fail(api.audit_internal_redirect_errors(root))
    lock_error = api.migration_update_lock_error(root)
    _fail([lock_error] if lock_error else [])
    baseline = api.audit_state_manifest(root)
    review_path = args.review.resolve()
    review_bytes = review_path.read_bytes()
    review, errors = api.load_json_object(review_path, "authored reconciliation")
    _fail(errors)
    unit_id = review.get("unit_id")
    _fail([] if api.is_nonempty_string(unit_id) else ["unit_id must name one existing proof unit"])
    _, manifest, errors = api.load_audit_manifest(root)
    _fail(errors)
    _fail(api.source_snapshot_freshness_errors(root, manifest))
    if api.challenge_contract_version(manifest) != 3:
        _fail(["submit-reconciliation requires challenge contract 3 with explicit original argument and statement judgments"])
    ledger_path, ledger = api.packet_ledger(root, unit_id)
    if ledger_path is None or not isinstance(ledger, dict):
        _fail(["Review requires one canonical primary ledger"])
    packet = api.build_context_packet(root, unit_id, "challenge")
    initial, initial_ref, errors = api.load_initial_challenge(root, unit_id, packet, ledger.get("independent_check") or {})
    _fail(errors)
    _fail(validate_review(review, packet, ledger, initial, api))
    external_guards = external_evidence_guards(root, packet, api)
    original_primary = api.canonical_primary_ledger_sha256(ledger)
    digest = api.canonical_sha256({"review": review, "initial_response": initial_ref,
                                  "primary_ledger_sha256": original_primary})
    relative = f"audit/05_adversarial/reconciliation-{api.canonical_sha256(unit_id)[:16]}-{digest}.md"
    artifact_path, valid = api.canonical_challenge_artifact_path(root, relative, "Submitted reconciliation", errors)
    _fail(errors)
    if not valid or artifact_path is None:
        _fail(["Cannot resolve the reconciliation destination"])
    old_check = ledger.get("independent_check") or {}
    old_relative = old_check.get("artifact")
    previous = None
    if old_relative:
        old_path, valid = api.canonical_challenge_artifact_path(root, old_relative, "Previous reconciliation", errors)
        _fail(errors)
        if not valid or old_path is None or not old_path.is_file() or api.sha256_file(old_path) != old_check.get("challenge_artifact_sha256"):
            _fail(["Previous reconciliation is missing or changed; restore its recorded evidence"])
        previous = {"artifact": old_relative, "sha256": old_check["challenge_artifact_sha256"]}
    if artifact_path.exists():
        if old_relative != relative:
            _fail(["This submission already exists outside the active reconciliation; retain its history and review the current evidence"])
        # The content-derived name binds the authored input, first response, and
        # full primary evidence. Current validation still checks source freshness.
        if review["status"] != "unresolved":
            _fail(api.challenge_semantic_freshness_errors(root, unit_id, old_check, old_check.get("covered_issue_ids", [])))
            _fail(api.challenge_artifact_binding_errors(artifact_path, unit_id, old_check))
        else:
            expected = unresolved_fields(review, packet, manifest, initial, initial_ref, original_primary)
            errors = [f"Existing unresolved {field} differs from the authored review or current context"
                      for field, value in expected.items() if old_check.get(field) != value]
            api.validate_independent_check(old_check, False, errors, primary_ledger_sha256=original_primary, current_contract=True)
            if not api.is_utc_timestamp(old_check.get("generated_utc")):
                errors.append("Existing unresolved review time is missing or invalid")
            _fail(errors)
        print(json.dumps({"command": "submit-reconciliation", "status": "unchanged",
                          "unit_id": unit_id, "review_status": review["status"], "artifact": str(artifact_path)}, indent=2))
        return 0
    narrative = render_review(review, packet, initial_ref, previous, api)
    candidate = json.loads(json.dumps(ledger))
    check = candidate["independent_check"]
    check.update(required=True, status="disagreed" if review["status"] == "unresolved" else review["status"],
                 independence_level=initial["response"]["independence_level"],
                 challenger_verdict=initial["response"]["challenger_verdict"],
                 reconciled_verdict=review["reconciled_verdict"], artifact=relative,
                 disagreements=review["disagreements"], resolution=review["resolution"],
                 issue_assessments=json.loads(json.dumps(review["issue_assessments"])), initial_response=initial_ref)
    if review["status"] != "unresolved":
        prepared = api.prepare_challenge_binding(root, unit_id, ledger_override=candidate, artifact_text=narrative)
        candidate, narrative = prepared["ledger"], prepared["artifact_text"]
        if candidate["independent_check"]["status"] != review["status"]:
            _fail(["The requested reconciliation status disagrees with the recorded initial and primary judgments"])
    else:
        # Unresolved accounts retain every authored assessment and the original
        # judgments, but deliberately carry no completed independent-check seal.
        check.update(unresolved_fields(review, packet, manifest, initial, initial_ref, original_primary),
                     challenge_artifact_sha256=api.sha256_text(narrative), generated_utc=api.utc_now())
        errors = []
        api.validate_independent_check(check, False, errors, primary_ledger_sha256=original_primary, current_contract=True)
        _fail(errors)
    # Every captured existing file is a guard, including immutable first response
    # and prerequisites. A failed multi-file publication uses existing rollback.
    guards = {root / r["file"]: r["sha256"] for r in baseline}
    guards.update({api.resolve_stored_path(r["file"], root): r["sha256"]
                   for r in manifest["source_snapshot"]["files"]})
    guards.update(external_guards)
    guards[review_path] = api.hashlib.sha256(review_bytes).hexdigest()
    lock, payload = api.acquire_migration_update_lock(root, "cmd_submit_reconciliation")
    release = True
    try:
        if api.audit_state_manifest(root, lock) != baseline or review_path.read_bytes() != review_bytes:
            _fail(["Audit or reviewer input changed during submission; review the current input and retry"])
        if artifact_path.exists():
            _fail(["Reconciliation destination appeared during submission; no evidence was overwritten"])
        api.transactional_write_texts([(artifact_path, narrative),
                                       (ledger_path, json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")],
                                      expected_sha256=guards, expected_absent=[artifact_path])
    except api.MigrationRecoveryRequired:
        release = False
        raise
    finally:
        if release:
            api.release_migration_update_lock(lock, payload)
    print(json.dumps({"command": "submit-reconciliation", "status": "written", "unit_id": unit_id,
                      "review_status": review["status"], "artifact": str(artifact_path),
                      "next_action": "Resolve the recorded disagreement before finalization." if review["status"] == "unresolved"
                      else "Continue remaining independent reviews or run final reconciliation and delivery checks."}, indent=2))
    return 0
