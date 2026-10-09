"""Build both skill bundles from the maintained shared backend.

The maintained source is ``shared/paper_core/`` in the proof-graphify repository.
This builder copies it (without caches or byte-compiled files) into both skill packages,
writes identical manifests, and verifies each bundle against that source.
Generated bundles are never edited by hand. Workflow entrypoints belong to each product
and need not be identical.

Commands::

    python tools/build_paper_core_bundles.py                  # rebuild both bundles, then verify
    python tools/build_paper_core_bundles.py --check          # verify only (exit 1 on any mismatch)
    python tools/build_paper_core_bundles.py --release-manifest PATH
        # also record the repository revision and dirty-file content identities

One JSON object is printed on stdout.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared" / "paper_core"
PACKAGES = {
    "proof-graphify": ROOT / "proof-graphify",
    "stat-proof-check": ROOT / "stat-proof-check",
}
REPOSITORIES = {
    "proof-graphify": ROOT,
}
WRAPPER = Path("scripts") / "paper_audit.py"
REQUIRED_ENTRYPOINTS = {
    "proof-graphify": ("scripts/paper_database.py", "scripts/proof_overview.py", "scripts/render.mjs"),
    "stat-proof-check": ("scripts/paper_audit.py",),
}
BUNDLE_DIR = Path("scripts") / "paper_core"

sys.path.insert(0, str(ROOT / "shared"))
from paper_core import CORE_VERSION, bundle  # noqa: E402


def _rmtree(path: Path) -> None:
    def onexc(func, target, exc):  # read-only files on Windows
        Path(target).chmod(0o666)
        func(target)
    shutil.rmtree(path, onexc=onexc)


def build(packages: dict[str, Path]) -> dict:
    files = bundle.bundle_files(SOURCE)
    if "cli.py" not in files or "schema.sql" not in files or "renderer/render_projection.mjs" not in files:
        raise SystemExit(f"{SOURCE} is not a complete paper_core source tree")
    manifest = bundle.build_manifest(files)
    text = bundle.manifest_text(manifest)
    for name, package in packages.items():
        target = package / BUNDLE_DIR
        if not package.is_dir():
            raise SystemExit(f"package folder missing: {package}")
        if target.exists() and not target.is_dir():
            raise SystemExit(f"bundle path is not a directory: {target}")
        if target.resolve() != package.resolve() / BUNDLE_DIR or target.is_symlink():
            raise SystemExit(f"bundle path must remain inside its package: {target}")
        if target.exists():
            _rmtree(target)
        for relative in files:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
        with (target / bundle.MANIFEST_NAME).open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    result = check(packages)
    if not result["ok"]:
        raise SystemExit("bundle verification failed right after building: " + json.dumps(result))
    return {"command": "build", "ok": result["ok"], "core_version": CORE_VERSION,
            "source_identity": manifest["source_identity"], "file_count": manifest["file_count"],
            "bundles": {n: str(p / BUNDLE_DIR) for n, p in packages.items()}, "check": result}


def check(packages: dict[str, Path]) -> dict:
    source_files = bundle.bundle_files(SOURCE)
    source_identity = bundle.content_identity(source_files)
    bundles, wrappers, entrypoints = {}, {}, {}
    for name, package in packages.items():
        target = package / BUNDLE_DIR
        entry = {"path": str(target), "exists": target.is_dir()}
        if target.is_dir():
            verification = bundle.verify_bundle(target)
            actual = bundle.bundle_files(target)
            entry.update(verification)
            entry["matches_source"] = actual == source_files
            entry["manifest_bytes"] = bundle.sha256_file(target / bundle.MANIFEST_NAME) if (target / bundle.MANIFEST_NAME).is_file() else None
            entry["ok"] = bool(verification["ok"]) and entry["matches_source"]
        else:
            entry["ok"] = False
        bundles[name] = entry
        wrapper = package / WRAPPER
        wrappers[name] = bundle.sha256_file(wrapper) if wrapper.is_file() else None
        required = REQUIRED_ENTRYPOINTS.get(name, (WRAPPER.as_posix(),))
        entrypoints[name] = {relative: bundle.sha256_file(package / relative)
                             if (package / relative).is_file() else None for relative in required}
    identical = len({b.get("manifest_bytes") for b in bundles.values()}) == 1 and all(b["ok"] for b in bundles.values())
    wrappers_identical = len(set(wrappers.values())) == 1 and None not in wrappers.values()
    entrypoints_present = all(value is not None for entries in entrypoints.values() for value in entries.values())
    return {"ok": identical and entrypoints_present, "source_identity": source_identity,
            "bundles_identical": identical, "wrappers_identical": wrappers_identical,
            "entrypoints_present": entrypoints_present, "entrypoints": entrypoints,
            "bundles": bundles, "wrappers": wrappers}


def _git(repo: Path, *args: str) -> str | None:
    try:
        run = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    return run.stdout if run.returncode == 0 else None


_C_ESCAPES = {"n": b"\n", "t": b"\t", "r": b"\r", "a": b"\a", "b": b"\b", "f": b"\f", "v": b"\v",
              '"': b'"', "\\": b"\\"}


def _unquote(path: str) -> str:
    """Undo git's C-style quoting of porcelain paths (octal escapes carry UTF-8 bytes)."""
    if not (len(path) >= 2 and path[0] == '"' and path[-1] == '"'):
        return path
    body, out, i = path[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            digits = body[i + 1:i + 4]
            if len(digits) == 3 and all(d in "01234567" for d in digits):
                out.append(int(digits, 8) & 0xFF)
                i += 4
                continue
            if nxt in _C_ESCAPES:
                out += _C_ESCAPES[nxt]
                i += 2
                continue
        out += ch.encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="surrogateescape")


def repository_state(repo: Path) -> dict:
    head = _git(repo, "rev-parse", "HEAD")
    head = head.strip() if head is not None else None
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    dirty = []
    if status is not None:
        for line in status.splitlines():  # porcelain rows are "XY path"; leading blanks are significant
            if len(line) < 4:
                continue
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            path = _unquote(path)
            full = repo / path
            dirty.append({"path": path, "status": line[:2],
                          "sha256": bundle.sha256_file(full) if full.is_file() else None})
    return {"path": str(repo), "is_repository": head is not None, "head": head,
            "dirty_count": len(dirty), "dirty_files": dirty}


def release_manifest(check_result: dict) -> dict:
    node = None
    try:
        run = subprocess.run(["node", "--version"], capture_output=True, text=True, encoding="utf-8")
        node = run.stdout.strip() if run.returncode == 0 else None
    except OSError:
        node = None
    return {
        "kind": "paper_core release input manifest",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "node": node,
        "platform": platform.platform(),
        "core_version": CORE_VERSION,
        "source_identity": check_result["source_identity"],
        "bundles": {name: {"source_identity": b.get("source_identity"), "file_count": b.get("file_count"),
                           "manifest_bytes": b.get("manifest_bytes"), "ok": b["ok"]}
                    for name, b in check_result["bundles"].items()},
        "wrappers": check_result["wrappers"],
        "entrypoints": check_result["entrypoints"],
        "repositories": {name: repository_state(repo) for name, repo in REPOSITORIES.items()},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify the existing bundles instead of rebuilding")
    parser.add_argument("--package", action="append", choices=sorted(PACKAGES), default=None,
                        help="limit the build/check to one package (repeatable)")
    parser.add_argument("--release-manifest", type=Path, default=None,
                        help="write the release input manifest (repository revision, dirty-file identities) here")
    args = parser.parse_args(argv)
    packages = {name: PACKAGES[name] for name in (args.package or sorted(PACKAGES))}
    result = check(packages) if args.check else build(packages)
    result["command"] = "check" if args.check else "build"
    if args.release_manifest is not None:
        manifest = release_manifest(result if args.check else result["check"])
        args.release_manifest.parent.mkdir(parents=True, exist_ok=True)
        with args.release_manifest.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=1, sort_keys=True)
            stream.write("\n")
        result["release_manifest"] = {"path": str(args.release_manifest),
                                      "repositories": {n: {"head": r["head"], "dirty_count": r["dirty_count"]}
                                                       for n, r in manifest["repositories"].items()}}
    print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
