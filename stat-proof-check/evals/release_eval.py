#!/usr/bin/env python3
"""Offline release evaluation. No model calls and no mathematical auto-grader."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ARGUMENTS = {"valid", "conditional", "gap", "invalid", "unclear", "not_checked"}
STATEMENTS = {"established", "conditional", "refuted", "not_established", "unclear", "not_assessed"}
ROLES = {"baseline", "current", "revised", "plain_expert"}
INDEPENDENCE = {"fresh_context_same_model", "different_model", "independent_human"}
TOKEN_FIELDS = ("input", "cached_input", "output", "reasoning")
SCORER_VERSION = 2


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded(value))


def required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def file_identities(paths: list[Path]) -> list[dict]:
    return [{"path": str(path.resolve()), "sha256": digest_file(path)}
            for path in sorted(set(paths))]


def implementation_identities(directory: Path) -> list[dict]:
    # Include role instructions and renderer/release helpers, not just the entrypoint.
    paths = [directory / "SKILL.md", directory / "scripts" / "proofcheck.py"]
    for folder in ("references", "scripts", "assets/templates", "assets/canaries", "agents"):
        paths.extend(path for path in (directory / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    return file_identities(paths)


def prospective_allocation(corpus: Path, cases: dict[str, dict]) -> dict:
    path = corpus / "prospective-allocation-v2.json"
    if not path.exists():
        return {"version": None, "status": "unrecorded", "effective_splits": {}, "known_exposures": []}
    value = read_json(path)
    if value.get("allocation_version") != 2:
        raise ValueError("Unsupported prospective allocation version")
    overrides = value.get("split_overrides", {})
    if any(case_id not in cases or split not in {"development", "heldout"}
           for case_id, split in overrides.items()):
        raise ValueError("Invalid prospective split override")
    for exposure in value.get("known_exposures", []):
        case_id = exposure["case_id"]
        if case_id not in cases or exposure["problem_sha256"] != cases[case_id]["problem_sha256"]:
            raise ValueError("Exposure identity does not match the corpus problem")
        if overrides.get(case_id, cases[case_id]["split"]) == "heldout":
            raise ValueError("Known exposed material cannot remain prospective heldout")
    effective = {case_id: overrides.get(case_id, row["split"]) for case_id, row in cases.items()}
    pairs = {}
    for case_id, row in cases.items():
        pairs.setdefault(row["pair_id"], set()).add(effective[case_id])
    if any(len(splits) > 1 for splits in pairs.values()):
        raise ValueError("Prospective allocation must keep matched pairs together")
    return {"version": 2, "path": str(path.resolve()), "sha256": digest_file(path),
            "status": "known exposures recorded; absence is not proof of no exposure",
            "effective_splits": effective, "known_exposures": value.get("known_exposures", [])}


def rows_by_id(rows: Any, expected: set[str], label: str) -> dict[str, dict]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} must be a list of objects")
    result = {row.get("conclusion_id"): row for row in rows}
    if len(result) != len(rows) or set(result) != expected:
        raise ValueError(f"{label} must cover each expected conclusion exactly once")
    return result


def load_corpus(corpus: Path = ROOT) -> dict[str, dict]:
    catalog = read_json(corpus / "catalog.json")
    result = {}
    for row in catalog["cases"]:
        case_id = row["case_id"]
        if case_id in result or row["split"] not in {"development", "heldout"}:
            raise ValueError("Corpus has duplicate case IDs or an invalid split")
        problem_path = corpus / "problems" / f"{case_id}.json"
        key_path = corpus / "keys" / f"{case_id}.json"
        problem, key = read_json(problem_path), read_json(key_path)
        if problem["case_id"] != case_id or key["case_id"] != case_id:
            raise ValueError(f"Mismatched corpus identity for {case_id}")
        required_text(problem["source"], f"{case_id}.source")
        ids = {item["conclusion_id"] for item in problem["conclusions"]}
        if len(ids) != len(problem["conclusions"]):
            raise ValueError(f"Duplicate problem conclusions in {case_id}")
        expected = rows_by_id(key["conclusions"], ids, f"{case_id}.key")
        line_count = len(problem["source"].splitlines())
        for item in expected.values():
            if not item["argument_status"] or not set(item["argument_status"]) <= ARGUMENTS:
                raise ValueError(f"Invalid argument key in {case_id}")
            if not item["statement_status"] or not set(item["statement_status"]) <= STATEMENTS:
                raise ValueError(f"Invalid statement key in {case_id}")
            if item["statement_truth"] not in {"true", "false", "unknown"}:
                raise ValueError(f"Invalid truth key in {case_id}")
            if any(type(n) is not int or n < 1 or n > line_count for n in item["defect_lines"]):
                raise ValueError(f"Invalid defect location in {case_id}")
            required_text(item["rationale"], f"{case_id}.rationale")
        review = key["expert_review"]
        if review["status"] not in {"pending", "reviewed"}:
            raise ValueError(f"Invalid expert review status in {case_id}")
        if review["status"] == "reviewed":
            required_text(review.get("reviewer"), "expert reviewer")
            required_text(review.get("reviewed_utc"), "expert review time")
        result[case_id] = {
            **row, "problem": problem, "key": key,
            "problem_sha256": digest_file(problem_path), "key_sha256": digest_file(key_path),
        }
    return result


def prepare(run: Path, configuration: dict, split: str, seed: int,
            case_ids: list[str] | None = None, corpus: Path = ROOT) -> dict:
    if run.exists():
        raise ValueError("Run directory already exists; use a new directory")
    if configuration.get("role") not in ROLES:
        raise ValueError(f"configuration.role must be one of {sorted(ROLES)}")
    for field in ("configuration_id", "checker_id", "description"):
        required_text(configuration.get(field), f"configuration.{field}")
    implementation = configuration.get("implementation_path")
    configuration = dict(configuration)
    configuration["implementation_files"] = []
    if implementation:
        configuration["implementation_files"] = implementation_identities(Path(implementation).resolve())
    supplied = configuration.get("supplied_files", [])
    if not isinstance(supplied, list) or any(not isinstance(path, str) for path in supplied):
        raise ValueError("configuration.supplied_files must be a list of actual instruction or script paths")
    configuration["supplied_file_identities"] = file_identities([Path(path) for path in supplied])
    cases = load_corpus(corpus)
    allocation = prospective_allocation(corpus, cases)
    if case_ids and (len(case_ids) != len(set(case_ids)) or not set(case_ids) <= set(cases)):
        raise ValueError("Requested case IDs must be unique corpus cases")
    selected = [row for row in cases.values()
                if (split == "all" or allocation["effective_splits"].get(row["case_id"], row["split"]) == split)
                and (not case_ids or row["case_id"] in case_ids)]
    if not selected or (case_ids and len(selected) != len(case_ids)):
        raise ValueError("The case selection is empty or crosses the requested split")
    random.Random(seed).shuffle(selected)
    packets = []
    for row in selected:
        packet_id = digest_bytes(f"proofcheck-pilot-v1:{seed}:{row['case_id']}".encode())[:16]
        problem = row["problem"]
        packet = {
            "packet_version": 1, "packet_id": packet_id,
            "instructions": [
                "Audit every listed conclusion against the written assumptions and proof, including dependency uses.",
                "Separate argument validity from statement falsity. Established means established by the submitted derivation; do not replace a defective proof with a new proof to award this status.",
                "Ordinary explicitly invoked algebra or logical rules may be reconstructed with their side conditions. A defective proof alone does not refute its conclusion.",
                "Return only the response object below, replacing placeholders. Give exact source line numbers for defects, not every downstream line. Include a source-backed mathematical justification.",
                "Use only this packet in a fresh checking context. Do not inspect evaluation keys, catalog, paired exercises, or other responses.",
            ],
            "source_lines": [{"line": n, "text": text} for n, text in enumerate(problem["source"].splitlines(), 1)],
            "conclusions": problem["conclusions"],
            "response_format": {
                "packet_id": packet_id,
                "conclusions": [{"conclusion_id": item["conclusion_id"],
                    "argument_status": "valid|conditional|gap|invalid|unclear|not_checked",
                    "statement_status": "established|conditional|refuted|not_established|unclear|not_assessed",
                    "defect_lines": [], "justification": "mathematical reasoning and source anchors",
                    "counterexample": None, "repair": None} for item in problem["conclusions"]],
            },
        }
        path = Path("packets") / f"{packet_id}.json"
        write_new(run / path, packet)
        packets.append({"packet_id": packet_id, "case_id": row["case_id"], "path": path.as_posix(),
                        "packet_sha256": digest_file(run / path),
                        "problem_sha256": row["problem_sha256"], "key_sha256": row["key_sha256"]})
    manifest = {
        "run_version": 2, "scorer_version": SCORER_VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": configuration, "split": split, "seed": seed,
        "allocation": allocation,
        "evaluator_files": file_identities([Path(__file__), ROOT.parent / "scripts" / "proofcheck_usage.py", corpus / "rubric.json"]
                                            + ([corpus / "rubric-v2.json"] if (corpus / "rubric-v2.json").exists() else [])),
        "corpus_path": str(corpus.resolve()), "packets": packets,
        "limitation": "Checker and assessor identities are declarations. Ground truth remains provisional until each key receives real expert review.",
    }
    write_new(run / "run.json", manifest)
    return {"run": str(run), "packets": len(packets), "share_with_checker": str(run / "packets"),
            "ground_truth": "consult key review status; pending keys are provisional"}


def validate_response(response: dict, packet: dict) -> dict[str, dict]:
    if response.get("packet_id") != packet["packet_id"]:
        raise ValueError("Response does not match the packet")
    rows = rows_by_id(response.get("conclusions"),
                      {row["conclusion_id"] for row in packet["conclusions"]}, "response.conclusions")
    for row in rows.values():
        if row.get("argument_status") not in ARGUMENTS or row.get("statement_status") not in STATEMENTS:
            raise ValueError("Response has an invalid judgment")
        lines = row.get("defect_lines")
        if not isinstance(lines, list) or any(type(n) is not int or not 1 <= n <= len(packet["source_lines"]) for n in lines) or len(set(lines)) != len(lines):
            raise ValueError("Defect lines must be distinct source line numbers")
        required_text(row.get("justification"), "response justification")
        for field in ("counterexample", "repair"):
            if row.get(field) is not None:
                required_text(row[field], field)
    return rows


def assessment_template(response_path: Path, output: Path) -> None:
    response = read_json(response_path)
    write_new(output, {
        "packet_id": response["packet_id"], "response_sha256": digest_file(response_path),
        "assessor": {"assessor_id": None, "independence": None},
        "conclusions": [{"conclusion_id": row["conclusion_id"], "rationale_score": None,
                         "counterexample_score": None, "repair_score": None,
                         "reason": None} for row in response["conclusions"]],
    })


def validate_assessment(assessment: dict, response: dict, response_hash: str,
                        checker_id: str) -> dict[str, dict]:
    if assessment.get("packet_id") != response["packet_id"] or assessment.get("response_sha256") != response_hash:
        raise ValueError("Assessment must bind the exact response bytes and packet")
    assessor = assessment.get("assessor", {})
    if required_text(assessor.get("assessor_id"), "assessor_id") == checker_id:
        raise ValueError("Rationale scores require a separate declared assessor")
    if assessor.get("independence") not in INDEPENDENCE:
        raise ValueError("A declared independent assessment context is required")
    rows = rows_by_id(assessment.get("conclusions"),
                     {row["conclusion_id"] for row in response["conclusions"]}, "assessment.conclusions")
    for row in rows.values():
        for field in ("rationale_score", "counterexample_score", "repair_score"):
            score = row.get(field)
            if field != "rationale_score" and score is None:
                continue
            if type(score) is not int or score not in {0, 1, 2}:
                raise ValueError(f"{field} must be an independently assigned 0, 1, or 2")
        required_text(row.get("reason"), "assessor reason")
    return rows


def score_conclusion(response: dict, assessment: dict, key: dict, version: int = SCORER_VERSION) -> dict:
    if version not in {1, 2}:
        raise ValueError("Unsupported scorer version")
    argument_match = response["argument_status"] in key["argument_status"]
    statement_match = response["statement_status"] in key["statement_status"]
    predicted, gold = set(response["defect_lines"]), set(key["defect_lines"])
    defective = "valid" not in key["argument_status"]
    result = {
        "conclusion_id": response["conclusion_id"], "argument_match": argument_match,
        "statement_match": statement_match, "label_match": argument_match and statement_match,
        "rationale_score": assessment["rationale_score"],
        "supported_label_match": argument_match and statement_match and assessment["rationale_score"] == 2,
        "counterexample_score": assessment.get("counterexample_score"), "repair_score": assessment.get("repair_score"),
        "localization": {"true_positive_lines": len(predicted & gold), "predicted_lines": len(predicted), "gold_lines": len(gold)},
        "defective_argument": defective,
        "supported_defect_detection": defective and argument_match and assessment["rationale_score"] == 2 and bool(predicted & gold),
        "false_alarm": not defective and (response["argument_status"] != "valid" or response["statement_status"] == "refuted" or bool(predicted)),
        "serious_false_verification": defective and response["argument_status"] == "valid",
        "serious_false_refutation": key["statement_truth"] == "true" and response["statement_status"] == "refuted",
    }
    if version >= 2:
        result["serious_false_establishment"] = key["statement_truth"] == "false" and response["statement_status"] == "established"
        result["inconsistent_establishment"] = response["statement_status"] == "established" and response["argument_status"] != "valid"
    return result


def validated_usage(value: dict) -> dict:
    module_path = ROOT.parent / "scripts" / "proofcheck_usage.py"
    spec = importlib.util.spec_from_file_location("proofcheck_eval_usage", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_usage_record(value)


def read_usage(path: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    value = validated_usage(json.loads(text))
    return {"path": str(path.resolve()), "sha256": digest_bytes(raw),
            "source_utf8": text, "events": value["events"]}


def usage_events(observed: dict) -> list[dict] | None:
    text = observed.get("source_utf8")
    if text is None:
        # Older records did not retain source content. Verify the original if available.
        path = Path(observed["path"])
        if not path.is_file() or digest_file(path) != observed["sha256"]:
            return None
        text = path.read_bytes().decode("utf-8")
    if digest_bytes(text.encode("utf-8")) != observed["sha256"]:
        raise ValueError("Captured usage source content changed")
    events = validated_usage(json.loads(text))["events"]
    if events != observed["events"]:
        raise ValueError("Captured usage events disagree with their source content")
    return events


def collect_usage(observations: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    files, events, unavailable = {}, {}, {}
    for observed in observations:
        verified = usage_events(observed)
        if verified is None:
            unavailable[(observed["path"], observed["sha256"])] = observed
            continue
        files.setdefault(observed["sha256"], observed)
        for event in verified:
            previous = events.setdefault(event["event_id"], event)
            if previous != event:
                raise ValueError(f"Conflicting usage observations for event {event['event_id']}")
    return list(files.values()), list(events.values()), list(unavailable.values())


def record(run: Path, response_path: Path, assessment_path: Path,
           usage_paths: list[Path], wall_seconds: float | None,
           workflow_paths: list[Path] | None = None) -> dict:
    if wall_seconds is not None and (not math.isfinite(wall_seconds) or wall_seconds < 0):
        raise ValueError("Measured case wall time must be finite and nonnegative")
    manifest = read_json(run / "run.json")
    if manifest.get("run_version", 1) >= 2:
        implementation = manifest["configuration"].get("implementation_path")
        if implementation and implementation_identities(Path(implementation).resolve()) != manifest["configuration"]["implementation_files"]:
            raise ValueError("Prepared implementation file set changed; prepare a new run")
        identities = (manifest["configuration"]["implementation_files"]
                      + manifest["configuration"].get("supplied_file_identities", [])
                      + manifest.get("evaluator_files", []))
        if any(digest_file(Path(item["path"])) != item["sha256"] for item in identities):
            raise ValueError("Prepared implementation, supplied instructions, or evaluator changed; prepare a new run")
    response, assessment = read_json(response_path), read_json(assessment_path)
    binding = next((row for row in manifest["packets"] if row["packet_id"] == response.get("packet_id")), None)
    if binding is None:
        raise ValueError("Response is not for this run")
    packet_path = run / binding["path"]
    if digest_file(packet_path) != binding["packet_sha256"]:
        raise ValueError("The checker packet changed after preparation")
    case = load_corpus(Path(manifest["corpus_path"]))[binding["case_id"]]
    if any(case[name] != binding[name] for name in ("problem_sha256", "key_sha256")):
        raise ValueError("Corpus problem or key changed; prepare a new run")
    response_rows = validate_response(response, read_json(packet_path))
    assessment_rows = validate_assessment(assessment, response, digest_file(response_path), manifest["configuration"]["checker_id"])
    key_rows = {row["conclusion_id"]: row for row in case["key"]["conclusions"]}
    scorer_version = manifest.get("scorer_version", 1)
    result = {
        "record_version": 2, "scorer_version": scorer_version,
        "packet_id": binding["packet_id"], "case_id": binding["case_id"],
        "packet_sha256": binding["packet_sha256"], "key_sha256": binding["key_sha256"],
        "response_sha256": digest_file(response_path), "assessment_sha256": digest_file(assessment_path),
        "response_payload_sha256": digest_bytes(encoded(response)),
        "assessment_payload_sha256": digest_bytes(encoded(assessment)),
        "response": response, "assessment": assessment,
        "expert_review": case["key"]["expert_review"],
        "scores": [score_conclusion(row, assessment_rows[cid], key_rows[cid], scorer_version) for cid, row in response_rows.items()],
        "usage_files": [read_usage(path) for path in usage_paths], "case_wall_seconds": wall_seconds,
        "workflow_evidence": file_identities(workflow_paths or []),
    }
    prior_usage = [observed for path in (run / "records").glob("*.json")
                   for observed in read_json(path)["usage_files"]]
    collect_usage(prior_usage + result["usage_files"])
    write_new(run / "records" / f"{binding['packet_id']}.json", result)
    return {"recorded_packet": binding["packet_id"], "conclusions": len(result["scores"]),
            "expert_review": result["expert_review"]["status"]}


def summarize(run: Path) -> dict:
    manifest = read_json(run / "run.json")
    cases = load_corpus(Path(manifest["corpus_path"]))
    records, all_scores, observations = [], [], []
    for binding in manifest["packets"]:
        path = run / "records" / f"{binding['packet_id']}.json"
        if not path.exists():
            continue
        row = read_json(path)
        case = cases[binding["case_id"]]
        if row["packet_id"] != binding["packet_id"] or row["packet_sha256"] != binding["packet_sha256"] or any(binding[field] != case[field] for field in ("problem_sha256", "key_sha256")) or row["key_sha256"] != case["key_sha256"]:
            raise ValueError("An evaluation record or its candidate key is stale")
        packet = read_json(run / binding["path"])
        if digest_file(run / binding["path"]) != binding["packet_sha256"]:
            raise ValueError("An evaluation packet is stale")
        if any(row[f"{field}_payload_sha256"] != digest_bytes(encoded(row[field])) for field in ("response", "assessment")):
            raise ValueError("A stored response or independent assessment changed")
        response_rows = validate_response(row["response"], packet)
        assessment_rows = validate_assessment(row["assessment"], row["response"], row["response_sha256"], manifest["configuration"]["checker_id"])
        keys = {item["conclusion_id"]: item for item in case["key"]["conclusions"]}
        version = row.get("scorer_version", 1)
        if version != manifest.get("scorer_version", 1):
            raise ValueError("Evaluation record scorer version differs from its run")
        scores = [score_conclusion(value, assessment_rows[cid], keys[cid], version) for cid, value in response_rows.items()]
        if scores != row["scores"]:
            raise ValueError("Stored evaluation scores disagree with response and assessment")
        for score in scores:
            all_scores.append({**score, "packet_id": row["packet_id"]})
        observations.extend(row["usage_files"])
        records.append(row)
    n = len(all_scores)
    defective = sum(row["defective_argument"] for row in all_scores)
    metrics = {}
    for name in ("argument_match", "statement_match", "label_match", "supported_label_match"):
        metrics[name] = {"numerator": sum(row[name] for row in all_scores), "denominator": n}
    metrics["supported_defect_detection"] = {"numerator": sum(row["supported_defect_detection"] for row in all_scores), "denominator": defective}
    metrics["false_alarm"] = {"numerator": sum(row["false_alarm"] for row in all_scores), "denominator": n - defective}
    for field in ("rationale_score", "counterexample_score", "repair_score"):
        observed = [row[field] for row in all_scores if row[field] is not None]
        metrics[field] = {"counts": {str(score): observed.count(score) for score in (0, 1, 2)}, "denominator": len(observed), "unassessed": n - len(observed)}
    localization = {field: sum(row["localization"][field] for row in all_scores)
                    for field in ("true_positive_lines", "predicted_lines", "gold_lines")}
    serious = {field: [{"packet_id": row["packet_id"], "conclusion_id": row["conclusion_id"]}
                      for row in all_scores if row.get(field, False)]
               for field in ("serious_false_verification", "serious_false_establishment", "serious_false_refutation", "inconsistent_establishment")}
    if manifest.get("scorer_version", 1) < 2:
        serious["serious_false_establishment"] = None
        serious["inconsistent_establishment"] = None
    usage, events, unavailable = collect_usage(observations)
    tokens = {}
    for field in TOKEN_FIELDS:
        values = [event["tokens"][field] for event in events if event["tokens"][field] is not None]
        tokens[field] = {"observed_sum": sum(values) if values else None,
                         "events_with_value": len(values), "events_total": len(events)}
    walls = [row["case_wall_seconds"] for row in records if row["case_wall_seconds"] is not None]
    return {
        "configuration": manifest["configuration"], "split": manifest["split"], "seed": manifest["seed"],
        "scorer_version": manifest.get("scorer_version", 1),
        "allocation": manifest.get("allocation", {"version": None, "status": "historical allocation; exposure not tracked"}),
        "workflow_evidence": {"records_with_attachments": sum(bool(row.get("workflow_evidence")) for row in records),
                              "records_without_attachments": sum(not row.get("workflow_evidence") for row in records),
                              "status": "Attachments identify declared execution evidence; they do not attest workflow compliance."},
        "prepared_packets": len(manifest["packets"]), "recorded_packets": len(records),
        "unrecorded_packets": len(manifest["packets"]) - len(records),
        "prepared_conclusions": sum(len(cases[row["case_id"]]["key"]["conclusions"]) for row in manifest["packets"]),
        "scored_conclusions": n, "expert_review_pending_packets": sum(cases[row["case_id"]]["key"]["expert_review"]["status"] == "pending" for row in manifest["packets"]),
        "metrics": metrics, "localization": localization, **serious,
        "correct_labels_with_unsupported_rationale": [{"packet_id": row["packet_id"], "conclusion_id": row["conclusion_id"], "rationale_score": row["rationale_score"]}
            for row in all_scores if row["label_match"] and row["rationale_score"] < 2],
        "usage": {"files": [{"path": value["path"], "sha256": value["sha256"]} for value in usage],
                  "unverifiable_legacy_files": [{"path": value["path"], "sha256": value["sha256"]} for value in unavailable],
                  "unique_events": len(events),
                  "records_without_usage_files": sum(not row["usage_files"] for row in records), "tokens": tokens,
                  "token_sources": {source: sum(event["tokens"]["source"] == source for event in events) for source in ("measured", "reported", "unavailable")},
                  "sum_of_observed_case_wall_seconds": sum(walls) if walls else None,
                  "cases_with_wall_time": len(walls), "cases_without_wall_time": len(records) - len(walls),
                  "financial_cost": None},
        "limitations": ["Pending expert review makes the corresponding ground truth and performance conclusions provisional.",
                        "Rationale scores are supplied by a separately declared assessor, not inferred from labels or automatically proved correct.",
                        "Observed token sums may be partial; missing values are unknown. Case durations may overlap and are not total elapsed run time.",
                        "Legacy scorer v1 did not measure false establishment separately. Historical scores are preserved, not upgraded.",
                        "Known exposure records are not proof of an untouched holdout. Prior run allocations remain historical.",
                        "Unavailable legacy usage sources are excluded from totals because their stored events cannot be authenticated.",
                        "The small pilot is not a mathematical soundness guarantee. No financial cost is estimated."],
    }


def compare(runs: list[Path]) -> dict:
    if len(runs) < 2 or len({str(run.resolve()) for run in runs}) != len(runs):
        raise ValueError("Compare at least two distinct evaluation runs")
    summaries = [summarize(run) for run in runs]
    if len({summary["scorer_version"] for summary in summaries}) > 1:
        raise ValueError("Comparison requires the same scorer version; preserve old scores and prepare a new evaluation")
    manifests = [read_json(run / "run.json") for run in runs]
    prepared = [{row["case_id"]: (row["problem_sha256"], row["key_sha256"])
                 for row in manifest["packets"]} for manifest in manifests]
    common = set.intersection(*(set(rows) for rows in prepared))
    if any(len({rows[case_id] for rows in prepared}) != 1 for case_id in common):
        raise ValueError("Matched comparison cases must use identical problem and candidate key bytes")
    recorded = [{row["case_id"] for row in manifest["packets"]
                 if (run / "records" / f"{row['packet_id']}.json").exists()}
                for run, manifest in zip(runs, manifests)]
    return {
        "configurations": summaries,
        "same_prepared_cases": all(rows == prepared[0] for rows in prepared[1:]),
        "common_prepared_cases": sorted(common),
        "common_recorded_cases": sorted(set.intersection(*recorded)),
        "comparison_limitations": [
            "Each configuration summary retains its own explicit denominators; unmatched or unrecorded cases are not treated as failures or successes.",
            "Use the same cases, split, checker settings, and execution conditions for an interpretable comparison. No superiority or statistical significance is inferred here.",
            "Pending expert review and missing telemetry remain limitations in every configuration.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare")
    command.add_argument("--run-dir", type=Path, required=True)
    command.add_argument("--configuration", type=Path, required=True)
    command.add_argument("--split", choices=("development", "heldout", "all"), default="development")
    command.add_argument("--seed", type=int, default=20260904)
    command.add_argument("--case-id", action="append")
    command = commands.add_parser("assessment-template")
    command.add_argument("--response", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("record")
    command.add_argument("--run-dir", type=Path, required=True)
    command.add_argument("--response", type=Path, required=True)
    command.add_argument("--assessment", type=Path, required=True)
    command.add_argument("--usage-file", type=Path, action="append", default=[])
    command.add_argument("--workflow-evidence-file", type=Path, action="append", default=[])
    command.add_argument("--wall-seconds", type=float)
    command = commands.add_parser("summary")
    command.add_argument("--run-dir", type=Path, required=True)
    command.add_argument("--output", type=Path)
    command = commands.add_parser("compare")
    command.add_argument("--run-dir", type=Path, action="append", required=True)
    command.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.run_dir.resolve(), read_json(args.configuration), args.split, args.seed, args.case_id)
        elif args.command == "assessment-template":
            assessment_template(args.response, args.output)
            result = {"assessment_template": str(args.output), "scores": "await independent assessment"}
        elif args.command == "record":
            result = record(args.run_dir, args.response, args.assessment, args.usage_file, args.wall_seconds, args.workflow_evidence_file)
        elif args.command == "summary":
            result = summarize(args.run_dir)
            if args.output:
                write_new(args.output, result)
        else:
            result = compare(args.run_dir)
            if args.output:
                write_new(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
