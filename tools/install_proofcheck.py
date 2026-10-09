"""Install the validated proofcheck runtime in selected user-wide skill roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone


SKILL_NAME = "stat-proof-check"
LEGACY_SKILL_NAME = "stat-paper-proofcheck"
CACHES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
DEVELOPMENT_ROOTS = {"tests", "evals"}
SURFACES = ("agents", "claude")


def excluded(path: Path, *, runtime: bool = False) -> bool:
    return (bool(CACHES.intersection(path.parts)) or path.suffix in {".pyc", ".pyo"}
            or (runtime and bool(path.parts) and path.parts[0] in DEVELOPMENT_ROOTS))


def files(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if excluded(relative):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Package links are not supported: {path}")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[relative.as_posix()] = digest.hexdigest()
    if "SKILL.md" not in result or "scripts/proofcheck.py" not in result:
        raise ValueError(f"Not a complete proofcheck package: {root}")
    return result


def delivery(package: Path) -> dict:
    # Current database packages validate their own runtime. Legacy audit
    # finalization is a different claim and must not be renewed by installation.
    entry = package / "scripts/paper_audit.py"
    if entry.exists() or (package / "scripts/paper_core").exists():
        run = subprocess.run([sys.executable, "-X", "utf8", "-B", str(entry), "version"],
                             cwd=package, capture_output=True, text=True, encoding="utf-8")
        if run.returncode:
            raise ValueError(f"Database runtime failed at {package}:\n{run.stdout}\n{run.stderr}")
        result = json.loads(run.stdout)
        bundle = result.get("bundle", {})
        version = re.search(r'^  version:\s*[\"\']?([^\s\"\']+)',
                            (package / "SKILL.md").read_text(encoding="utf-8"), re.MULTILINE)
        if (result.get("command") != "version" or bundle.get("present") is not True
                or bundle.get("ok") is not True or bundle.get("constants_match") is not True
                or version is None or result.get("core_version") != version.group(1)):
            raise ValueError(f"Database runtime or skill version is inconsistent: {result}")
        return result
    command = [sys.executable, "-X", "utf8", "-B",
               str(package / "scripts/proofcheck.py"), "delivery-check", "--root",
               str(package / "assets/reference-audit/proofcheck-audit")]
    run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if run.returncode:
        raise ValueError(f"Bundled reference failed at {package}:\n{run.stdout}\n{run.stderr}")
    result = json.loads(run.stdout)
    if (result.get("delivery_status") != "FINAL"
            or result.get("usable_finalization") is not True
            or result.get("freshness") != "current"):
        raise ValueError(f"Bundled reference is not FINAL, current and usable: {result}")
    return result


def confined(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    if resolved == parent or not resolved.is_relative_to(parent):
        raise ValueError(f"Installation path escapes the selected directory: {path}")


def install(source: Path, user_root: Path, upgrade: bool = False, *,
            surface: str = "agents", allow_duplicates: bool = False) -> dict:
    if surface not in SURFACES:
        raise ValueError(f"Unknown installation surface: {surface}")
    source, user_root = source.resolve(), user_root.resolve()
    if user_root == source or user_root.is_relative_to(source):
        raise ValueError("The selected user root must be outside the source package.")
    skill_root = user_root / f".{surface}"
    target = skill_root / "skills" / SKILL_NAME
    for path in (skill_root, target.parent, target):
        if path.is_symlink():
            raise ValueError(f"Installation links are not supported: {path}")
        confined(path, user_root)
    # The old name must leave skill discovery before the renamed skill is installed.
    duplicates = [
        user_root / f".{surface_name}" / "skills" / LEGACY_SKILL_NAME
        for surface_name in (*SURFACES, "codex")
    ] + [user_root / ".codex" / "skills" / SKILL_NAME]
    found = [str(path) for path in duplicates if os.path.lexists(path)]
    if found and not allow_duplicates:
        raise ValueError("Other discoverable copies exist; preserve and relocate them first: "
                         + ", ".join(found))
    if target.exists() and not upgrade:
        raise ValueError(f"Installation exists at {target}; use --upgrade to archive and replace it.")
    if source == target or source.is_relative_to(target):
        raise ValueError("Choose a separate validated source package, not the installation.")
    previous = files(target) if target.exists() else None
    source_before = files(source)
    expected = {name: digest for name, digest in source_before.items()
                if not excluded(Path(name), runtime=True)}
    source_delivery = delivery(source)
    skill_root.mkdir(parents=True, exist_ok=True)
    stage_parent = Path(tempfile.mkdtemp(prefix="proofcheck-install-", dir=skill_root))
    stage = stage_parent / SKILL_NAME
    backup = None
    published = False
    try:
        shutil.copytree(source, stage, ignore=lambda folder, names: [
            name for name in names
            if excluded((Path(folder) / name).relative_to(source), runtime=True)])
        if files(stage) != expected or files(source) != source_before:
            raise ValueError("Package changed during copying; installation was not replaced.")
        delivery(stage)
        if files(source) != source_before or files(stage) != expected:
            raise ValueError("Package changed during validation; installation was not replaced.")
        target.parent.mkdir(parents=True, exist_ok=True)
        confined(target, skill_root.resolve())
        if previous is not None:
            if not target.exists() or files(target) != previous:
                raise ValueError("Installation changed during preparation; retry from current state.")
            backup_candidate = skill_root / "skill-backups" / SKILL_NAME / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
            backup_candidate.parent.mkdir(parents=True, exist_ok=True)
            confined(backup_candidate, skill_root.resolve())
            target.rename(backup_candidate)
            backup = backup_candidate
        elif os.path.lexists(target):
            raise ValueError(f"Installation appeared during preparation: {target}")
        stage.rename(target)
        published = True
        installed_delivery = delivery(target)
        if files(target) != expected:
            raise ValueError("Installed files differ from the validated package.")
        return {"installed": str(target), "backup": str(backup) if backup else None,
                "surface": surface, "duplicates_explicitly_allowed": allow_duplicates,
                "runtime_files_match": True, "files": expected,
                "excluded_top_level_directories": sorted(DEVELOPMENT_ROOTS),
                "source_non_bytecode_file_count": len(source_before),
                "duplicate_locations_checked": [str(path) for path in duplicates],
                "source_delivery": source_delivery, "installed_delivery": installed_delivery,
                "python": sys.executable}
    except Exception:
        if published:
            # Retain a failed candidate outside skill discovery for diagnosis.
            confined(target, skill_root.resolve())
            target.rename(stage)
        if backup is not None:
            confined(backup, skill_root.resolve())
            backup.rename(target)
        raise
    finally:
        # Remove only an empty staging directory. Failed candidates stay available.
        if stage_parent.exists() and not any(stage_parent.iterdir()):
            stage_parent.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path(__file__).resolve().parents[1] / SKILL_NAME)
    parser.add_argument("--user-root", type=Path, default=Path.home(),
                        help="Selected user's home directory; override for a temporary exercise")
    parser.add_argument("--upgrade", action="store_true",
                        help="Preserve each existing copy outside discovery, then replace it")
    parser.add_argument("--target", choices=SURFACES, action="append",
                        help="Explicit user-wide destination; repeat for multiple copies. "
                             "Defaults to both Agents and Claude.")
    args = parser.parse_args()
    try:
        # Each destination has its own validated staging area and rollback,
        # with an immediate receipt if a later destination fails.
        for surface in dict.fromkeys(args.target or SURFACES):
            print(json.dumps(install(args.source, args.user_root, args.upgrade,
                                     surface=surface), indent=2), flush=True)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
