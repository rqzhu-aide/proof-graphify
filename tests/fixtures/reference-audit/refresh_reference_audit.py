"""Prepare review packets or publish an already checked reference audit as HTML.

This helper never updates a work hash, changes a mathematical judgment, invents
an initial challenge response, or rebinds a historical challenge. Protocol
upgrades and any newly required source review must be completed explicitly
before publishing. Packet output must be outside the canonical audit root.

Usage:
    python tests/fixtures/reference-audit/refresh_reference_audit.py prepare ROOT OUTPUT
    python tests/fixtures/reference-audit/refresh_reference_audit.py publish ROOT
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "stat-proof-check" / "scripts" / "proofcheck.py"
_SPEC = importlib.util.spec_from_file_location("proofcheck_refresh", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load {_SCRIPT}")
proofcheck = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(proofcheck)

UNITS = {
    "lem:growing-max": "lem-growing-max",
    "thm:main": "thm-main",
}


def _manifest(root: Path) -> dict:
    _, manifest, errors = proofcheck.load_audit_manifest(root)
    if errors:
        raise ValueError("Reference audit is not current: " + "; ".join(errors))
    actual = set(manifest.get("audit_scope", {}).get("in_scope_units", []))
    if actual != set(UNITS):
        raise ValueError("This helper requires exactly the bundled reference units")
    return manifest


def prepare(root: Path, output: Path) -> dict:
    """Write current packets without changing any canonical audit artifact."""
    root, output = root.resolve(), output.resolve()
    _manifest(root)
    if output.is_relative_to(root):
        raise ValueError("Review packets must be outside the canonical audit root")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite review packets: {output}")
    # Build every packet before creating the output directory so a bad source
    # or contract does not leave a misleading partial review assignment.
    packets = {
        f"{stem}.{mode}.json": proofcheck.build_context_packet(root, unit, mode)
        for unit, stem in UNITS.items()
        for mode in ("primary", "challenge")
    }
    output.mkdir(parents=True)
    for name, packet in packets.items():
        proofcheck.atomic_create_json(output / name, packet, "reference review packet")
    assignment = {
        "audit_root": str(root),
        "packets": [
            {"unit_id": unit,
             "primary": str(output / f"{stem}.primary.json"),
             "challenge": str(output / f"{stem}.challenge.json")}
            for unit, stem in UNITS.items()
        ],
        "instruction": (
            "Give each fresh challenger only its challenge packet and the current "
            "challenge response instructions. Do not expose primary packets, ledgers, "
            "past challenges, or the issue log. Independently review and, if needed, "
            "recompile the primary work. Regenerate packets after any semantic change. "
            "Preserve each genuine initial response with record-challenge before "
            "reconciliation. This assignment is not evidence that a review occurred."
        ),
    }
    proofcheck.atomic_create_json(output / "ASSIGNMENT.json", assignment, "review assignment")
    return assignment


def _command(function, args: argparse.Namespace, label: str) -> None:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        status = function(args)
    if status != 0:
        raise RuntimeError(f"{label} failed: {buffer.getvalue()}")


def refresh(root: Path, *, quiet: bool = True,
            allow_historical_challenges: bool = False) -> None:
    """Publish checked evidence; refuse to manufacture freshness for stale work."""
    root = root.resolve()
    manifest = _manifest(root)
    if proofcheck.challenge_contract_version(manifest) != 3 and not allow_historical_challenges:
        raise ValueError(
            "Historical challenge contract: obtain genuine initial responses for "
            "contract 3, or explicitly allow historical challenges for a presentation-only "
            "migration. Historical records must not be described as new reviews."
        )
    # Check every non-report gate before the first write. Publication cannot
    # repair missing mathematical work or manufacture review freshness.
    errors, _ = proofcheck.check_audit_finalization(root, check_reports=False)
    if errors:
        raise ValueError(
            "Reference evidence needs actual review before publication; no records "
            "were rebound: " + "; ".join(errors)
        )
    if not proofcheck.uses_html_report(manifest):
        _command(proofcheck.cmd_migrate_report,
                 argparse.Namespace(root=root, markdown=True), "report migration")
    _command(proofcheck.cmd_finalize, argparse.Namespace(root=root), "finalization")
    _command(proofcheck.cmd_delivery_check, argparse.Namespace(root=root), "delivery check")
    if not quiet:
        print(f"Checked reference published at {root / proofcheck.preferred_report_path(_manifest(root))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="Write read-only review assignments")
    prepare_parser.add_argument("root", type=Path)
    prepare_parser.add_argument("output", type=Path)
    publish_parser = subparsers.add_parser("publish", help="Publish already validated evidence as HTML")
    publish_parser.add_argument("root", type=Path)
    publish_parser.add_argument("--allow-historical-challenges", action="store_true",
                                help="Retain legacy challenge evidence without claiming a fresh review")
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(args.root, args.output), indent=2))
    else:
        refresh(args.root, quiet=False,
                allow_historical_challenges=args.allow_historical_challenges)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
