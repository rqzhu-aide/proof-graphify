"""Small UTF-8 helpers for proofcheck examples and coordinator scripts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value, *, replace=False):
    """Write a UTF-8 artifact; replacement must be explicit."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w" if replace else "x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return destination


def run_audit(script, *arguments):
    """Decode both streams explicitly, independently of the parent Windows codepage."""
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(script), *map(str, arguments)],
                             capture_output=True, text=True, encoding="utf-8", errors="strict",
                             env=environment, check=False)
    return {"returncode": process.returncode, "result": json.loads(process.stdout),
            "stderr": process.stderr}


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
