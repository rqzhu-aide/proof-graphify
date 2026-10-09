#!/usr/bin/env python3
"""Optional, non-gating usage telemetry for stat-paper-proofcheck.

This helper deliberately lives outside ``proofcheck.py`` so recording usage
does not change the proof validator identity. The stored data is observational:
it is never evidence for a mathematical verdict or an audit completion gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


USAGE_SCHEMA_VERSION = 1
USAGE_KIND = "stat-paper-proofcheck-usage"
USAGE_RELATIVE_PATH = Path("audit") / "07_runtime" / "RUN_USAGE.json"
TOKEN_FIELDS = ("input", "cached_input", "output", "reasoning")
TOKEN_SOURCES = {"measured", "reported", "unavailable"}
CACHE_OUTCOMES = {"hit", "miss", "not_used"}
_PROOFCHECK_MODULE: ModuleType | None = None


def configure_console_errors() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except OSError:
            pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return parsed


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} must not contain control characters")
    return value


def resolve_audit_root(value: Path) -> Path:
    root = Path(value).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Audit root not found: {root}")
    manifest = root / "AUDIT_MANIFEST.json"
    audit = root / "audit"
    if not manifest.is_file():
        raise FileNotFoundError(f"Audit manifest not found: {manifest}")
    if not audit.is_dir():
        raise FileNotFoundError(f"Audit directory not found: {audit}")
    if manifest.is_symlink() or audit.is_symlink():
        raise ValueError("Refusing a redirected audit manifest or audit directory")
    if not audit.resolve().is_relative_to(root):
        raise ValueError("Audit directory resolves outside the audit root")
    return root


def usage_path(root: Path) -> Path:
    path = root / USAGE_RELATIVE_PATH
    runtime = path.parent
    if runtime.exists() and runtime.is_symlink():
        raise ValueError("Refusing a redirected telemetry directory")
    if path.exists() and path.is_symlink():
        raise ValueError("Refusing a redirected telemetry file")
    if not runtime.resolve().is_relative_to(root):
        raise ValueError("Telemetry path resolves outside the audit root")
    return path


def empty_usage_record() -> dict[str, Any]:
    return {
        "schema_version": USAGE_SCHEMA_VERSION,
        "kind": USAGE_KIND,
        "observational_only": True,
        "events": [],
    }


def validate_token_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    source = value.get("source")
    if source not in TOKEN_SOURCES:
        raise ValueError(f"{label}.source is invalid")
    result: dict[str, Any] = {"source": source}
    present = 0
    for field in TOKEN_FIELDS:
        count = value.get(field)
        if count is not None and not is_nonnegative_int(count):
            raise ValueError(f"{label}.{field} must be null or a nonnegative integer")
        if count is not None:
            present += 1
        result[field] = count
    if source == "unavailable" and present:
        raise ValueError(
            f"{label}: unavailable token source requires every token field to be null"
        )
    if source in {"measured", "reported"} and not present:
        raise ValueError(
            f"{label}: {source} token source requires at least one token count"
        )
    return result


def validate_event(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    event_id = require_text(value.get("event_id"), f"{label}.event_id")
    stage = require_text(value.get("stage"), f"{label}.stage")
    recorded_utc = require_text(value.get("recorded_utc"), f"{label}.recorded_utc")
    try:
        parsed_time = datetime.fromisoformat(recorded_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}.recorded_utc must be ISO 8601") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() != timezone.utc.utcoffset(
        parsed_time
    ):
        raise ValueError(f"{label}.recorded_utc must be a UTC timestamp")
    work_packets = value.get("work_packets")
    if not is_nonnegative_int(work_packets):
        raise ValueError(f"{label}.work_packets must be a nonnegative integer")
    unit_ids_value = value.get("unit_ids")
    if not isinstance(unit_ids_value, list):
        raise ValueError(f"{label}.unit_ids must be a list")
    unit_ids = [
        require_text(unit_id, f"{label}.unit_ids[{index}]")
        for index, unit_id in enumerate(unit_ids_value, 1)
    ]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError(f"{label}.unit_ids must not contain duplicates")
    cache_outcome = value.get("cache_outcome")
    if cache_outcome not in CACHE_OUTCOMES:
        raise ValueError(f"{label}.cache_outcome is invalid")
    tokens = validate_token_record(value.get("tokens"), f"{label}.tokens")
    result = {
        "event_id": event_id,
        "recorded_utc": recorded_utc,
        "stage": stage,
        "work_packets": work_packets,
        "unit_ids": unit_ids,
        "tokens": tokens,
        "cache_outcome": cache_outcome,
    }
    if "notes" in value:
        notes = value.get("notes")
        if not isinstance(notes, str):
            raise ValueError(f"{label}.notes must be a string")
        result["notes"] = notes
    return result


def validate_usage_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("RUN_USAGE.json root must be an object")
    if value.get("schema_version") != USAGE_SCHEMA_VERSION:
        raise ValueError("RUN_USAGE.json has an unsupported schema_version")
    if value.get("kind") != USAGE_KIND:
        raise ValueError("RUN_USAGE.json kind is invalid")
    if value.get("observational_only") is not True:
        raise ValueError("RUN_USAGE.json observational_only must be true")
    raw_events = value.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("RUN_USAGE.json events must be a list")
    events: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    for index, raw_event in enumerate(raw_events, 1):
        event = validate_event(raw_event, f"events[{index}]")
        if event["event_id"] in event_ids:
            raise ValueError(
                f"RUN_USAGE.json contains duplicate event ID: {event['event_id']}"
            )
        event_ids.add(event["event_id"])
        events.append(event)
    return {
        "schema_version": USAGE_SCHEMA_VERSION,
        "kind": USAGE_KIND,
        "observational_only": True,
        "events": events,
    }


def load_usage_record(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return empty_usage_record(), False
    if not path.is_file():
        raise ValueError(f"Telemetry path is not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"RUN_USAGE.json is malformed JSON: {exc}") from exc
    return validate_usage_record(value), True


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Refusing a redirected telemetry destination")
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".proofcheck.tmp", dir=str(path.parent)
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_proofcheck_module() -> ModuleType:
    global _PROOFCHECK_MODULE
    if _PROOFCHECK_MODULE is not None:
        return _PROOFCHECK_MODULE
    script = Path(__file__).resolve().with_name("proofcheck.py")
    specification = importlib.util.spec_from_file_location(
        "_stat_paper_proofcheck_usage_guard", script
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load proofcheck validator: {script}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    _PROOFCHECK_MODULE = module
    return module


def current_usable_finalization(root: Path) -> bool:
    try:
        freshness = load_proofcheck_module().check_finalization_freshness(root)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(
            f"Cannot determine finalization freshness safely: {exc}"
        ) from exc
    return freshness.get("usable_finalization") is True


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def event_from_args(args: argparse.Namespace) -> dict[str, Any]:
    event_id = require_text(args.event_id, "event-id")
    stage = require_text(args.stage, "stage")
    if not is_nonnegative_int(args.work_packets):
        raise ValueError("work-packets must be a nonnegative integer")
    unit_ids = [
        require_text(unit_id, f"unit-id[{index}]")
        for index, unit_id in enumerate(args.unit_id or [], 1)
    ]
    unit_ids = unique_preserving_order(unit_ids)
    token_record = validate_token_record(
        {
            "source": args.token_source,
            "input": args.input_tokens,
            "cached_input": args.cached_input_tokens,
            "output": args.output_tokens,
            "reasoning": args.reasoning_tokens,
        },
        "tokens",
    )
    if args.cache_outcome not in CACHE_OUTCOMES:
        raise ValueError("cache-outcome is invalid")
    event: dict[str, Any] = {
        "event_id": event_id,
        "recorded_utc": utc_now(),
        "stage": stage,
        "work_packets": args.work_packets,
        "unit_ids": unit_ids,
        "tokens": token_record,
        "cache_outcome": args.cache_outcome,
    }
    if args.notes is not None:
        event["notes"] = args.notes
    return event


def cmd_record(args: argparse.Namespace) -> int:
    configure_console_errors()
    root = resolve_audit_root(args.root)
    event = event_from_args(args)
    if current_usable_finalization(root):
        raise ValueError(
            "Refusing to mutate usage telemetry after a current usable "
            "FINALIZATION exists"
        )
    path = usage_path(root)
    record, _ = load_usage_record(path)
    event_ids = {row["event_id"] for row in record["events"]}
    if event["event_id"] in event_ids:
        raise ValueError(f"Duplicate telemetry event ID: {event['event_id']}")
    updated = dict(record)
    updated["events"] = [*record["events"], event]
    atomic_write_json(path, updated)
    result = {
        "command": "record",
        "status": "recorded",
        "observational_only": True,
        "usage_file": USAGE_RELATIVE_PATH.as_posix(),
        "event_id": event["event_id"],
        "events": len(updated["events"]),
    }
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def summarize(record: dict[str, Any], present: bool) -> dict[str, Any]:
    events = record["events"]
    token_summary: dict[str, dict[str, int | None]] = {}
    for field in TOKEN_FIELDS:
        values = [event["tokens"][field] for event in events]
        known = [value for value in values if value is not None]
        token_summary[field] = {
            "total": sum(known) if known else None,
            "events_with_value": len(known),
            "events_without_value": len(values) - len(known),
        }
    stage_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"events": 0, "work_packets": 0}
    )
    for event in events:
        stage_counts[event["stage"]]["events"] += 1
        stage_counts[event["stage"]]["work_packets"] += event["work_packets"]
    token_sources = Counter(event["tokens"]["source"] for event in events)
    cache_outcomes = Counter(event["cache_outcome"] for event in events)
    return {
        "command": "summary",
        "status": "present" if present else "absent",
        "observational_only": True,
        "usage_file": USAGE_RELATIVE_PATH.as_posix(),
        "events": len(events),
        "work_packets": sum(event["work_packets"] for event in events),
        "unit_ids": sorted(
            {unit_id for event in events for unit_id in event["unit_ids"]}
        ),
        "tokens": token_summary,
        "token_sources": {
            source: token_sources.get(source, 0) for source in sorted(TOKEN_SOURCES)
        },
        "cache_outcomes": {
            outcome: cache_outcomes.get(outcome, 0)
            for outcome in sorted(CACHE_OUTCOMES)
        },
        "stages": {stage: stage_counts[stage] for stage in sorted(stage_counts)},
    }


def markdown_summary(summary: dict[str, Any]) -> str:
    rows = [
        "# Proofcheck Usage Summary",
        "",
        f"- Telemetry status: {summary['status']}",
        "- Observational only: true",
        f"- Events: {summary['events']}",
        f"- Model work packets: {summary['work_packets']}",
        "",
        "## Token counts",
        "",
        "| Kind | Known total | Events with value | Events without value |",
        "|---|---:|---:|---:|",
    ]
    for field in TOKEN_FIELDS:
        values = summary["tokens"][field]
        total = values["total"]
        rows.append(
            f"| {field} | {'unavailable' if total is None else total} | "
            f"{values['events_with_value']} | {values['events_without_value']} |"
        )
    rows.extend(
        [
            "",
            "## Stages",
            "",
            "| Stage | Events | Work packets |",
            "|---|---:|---:|",
        ]
    )
    if summary["stages"]:
        for stage, values in summary["stages"].items():
            safe_stage = str(stage).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
            rows.append(
                f"| {safe_stage} | {values['events']} | {values['work_packets']} |"
            )
    else:
        rows.append("| none | 0 | 0 |")
    rows.append("")
    return "\n".join(rows)


def cmd_summary(args: argparse.Namespace) -> int:
    configure_console_errors()
    root = resolve_audit_root(args.root)
    path = usage_path(root)
    record, present = load_usage_record(path)
    result = summarize(record, present)
    if args.format == "markdown":
        print(markdown_summary(result), end="")
    else:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def write_new_json(path: Path, value: Any) -> None:
    """Create a durable receipt without replacing an earlier observation."""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def command_output_summary(path: Path) -> dict[str, Any]:
    """Expose small reported fields; the complete output remains on disk."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    fields = (
        "status", "workflow_state", "errors", "error_count", "warnings",
        "readiness", "primary_work_packet_ready", "delivery_status",
        "usable_finalization",
    )
    return {
        field: value[field]
        for field in fields
        if field in value
        and (value[field] is None or type(value[field]) in (bool, int, float)
             or isinstance(value[field], str) and len(value[field]) <= 160)
    }


def cmd_run(args: argparse.Namespace) -> int:
    """Run the existing CLI once, retaining output outside the audited tree."""
    configure_console_errors()
    root = resolve_audit_root(args.root)
    records = args.records.resolve()
    if records.is_relative_to(root):
        raise ValueError("Command records must be outside the audit root")
    stage = require_text(args.stage, "stage")
    command_args = list(args.proofcheck_args)
    if command_args[:1] == ["--"]:
        command_args.pop(0)
    if not command_args:
        raise ValueError("Supply a proofcheck command after --")
    for index, value in enumerate(command_args):
        if value == "--root":
            if index + 1 >= len(command_args):
                raise ValueError("The child --root requires an audit path")
            child_root = command_args[index + 1]
        elif value.startswith("--root="):
            child_root = value.partition("=")[2]
        else:
            continue
        if not child_root or Path(child_root).resolve() != root:
            raise ValueError("The child --root must match the recorded audit root")
    script = Path(__file__).resolve().with_name("proofcheck.py")
    command = [
        sys.executable, "-X", "utf8", "-B",
        str(script),
        *command_args,
    ]
    records.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    run_directory = records / run_id
    run_directory.mkdir()
    stdout_path = run_directory / "stdout.txt"
    stderr_path = run_directory / "stderr.txt"
    start = {
        "kind": "stat-paper-proofcheck-command", "schema_version": 1,
        "observational_only": True, "run_id": run_id, "stage": stage,
        "audit_root": str(root), "cwd": str(Path.cwd()),
        "core_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "started_utc": utc_now(), "command": command,
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
    }
    write_new_json(run_directory / "start.json", start)
    began = time.perf_counter()
    exit_code = None
    failure = None
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            try:
                exit_code = subprocess.run(
                    command, stdout=stdout, stderr=stderr, check=False,
                ).returncode
            finally:
                stdout.flush()
                stderr.flush()
                os.fsync(stdout.fileno())
                os.fsync(stderr.fileno())
    except OSError as exc:
        failure = f"Could not execute or retain command output: {exc}"
    except KeyboardInterrupt:
        failure = "Command interrupted; exit code unavailable"
    end = {
        **start, "ended_utc": utc_now(),
        "elapsed_seconds": time.perf_counter() - began, "exit_code": exit_code,
        "reported_summary": command_output_summary(stdout_path),
        "failure": failure,
    }
    write_new_json(run_directory / "end.json", end)
    print(json.dumps({
        "command": "run", "observational_only": True, "run_id": run_id,
        "stage": stage, "exit_code": exit_code,
        "elapsed_seconds": end["elapsed_seconds"],
        "reported_summary": end["reported_summary"],
        "record_directory": str(run_directory),
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
        "failure": failure,
    }, ensure_ascii=True, indent=2))
    return exit_code if failure is None and exit_code is not None else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record optional, observational usage telemetry for a proofcheck audit"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="Append one usage event")
    record.add_argument("--root", type=Path, required=True)
    record.add_argument("--event-id", required=True)
    record.add_argument("--stage", required=True)
    record.add_argument("--work-packets", type=nonnegative_int, required=True)
    record.add_argument("--input-tokens", type=nonnegative_int)
    record.add_argument("--cached-input-tokens", type=nonnegative_int)
    record.add_argument("--output-tokens", type=nonnegative_int)
    record.add_argument("--reasoning-tokens", type=nonnegative_int)
    record.add_argument(
        "--token-source", choices=sorted(TOKEN_SOURCES), default="unavailable"
    )
    record.add_argument(
        "--cache-outcome", choices=sorted(CACHE_OUTCOMES), default="not_used"
    )
    record.add_argument("--unit-id", action="append", default=[])
    record.add_argument("--notes")
    record.set_defaults(func=cmd_record)

    summary = subparsers.add_parser("summary", help="Summarize recorded usage")
    summary.add_argument("--root", type=Path, required=True)
    summary.add_argument("--format", choices=("json", "markdown"), default="json")
    summary.set_defaults(func=cmd_summary)

    run = subparsers.add_parser(
        "run", help="Run proofcheck once with durable receipts and compact output"
    )
    run.add_argument("--root", type=Path, required=True)
    run.add_argument(
        "--records", type=Path, required=True,
        help="Receipt directory outside the audit root; each run gets a new folder",
    )
    run.add_argument("--stage", required=True)
    run.add_argument("proofcheck_args", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)
    return parser


def main() -> int:
    configure_console_errors()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (FileNotFoundError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
