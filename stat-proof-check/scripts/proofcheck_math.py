"""Compatibility facade for the bundled common formula renderer.

Converter provenance remains available to legacy report identities. Scientific
source-choice compatibility is separate from display candidate detection.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import re
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _common():
    path = Path(__file__).with_name("paper_core") / "math_render.py"
    try:
        from paper_core import math_render
        if Path(math_render.__file__).resolve() == path.resolve():
            return math_render
    except ModuleNotFoundError as exc:
        if exc.name != "paper_core":
            raise
    # Legacy reports load this facade by filename without adding scripts to
    # sys.path. Load only the installed neighboring common implementation.
    key = "_proofcheck_common_math_render_" + hashlib.sha256(
        str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(key, None)
            raise
    return sys.modules[key]


def __getattr__(name):
    return getattr(_common(), name)


def render_text(text: str, diagnostics=None) -> str:
    return _common().render_text(text, diagnostics=diagnostics)


def has_math(text: str) -> bool:
    return _common().has_math(text)


def legacy_reading_has_math(text: str) -> bool:
    """Preserve the old report's primary-claim versus source-wording choice.

    Paired doubled slash delimiters are diagnosed by the common display, but
    never counted as formulas by the old scientific wording selector.
    """
    text = str(text)
    for match in re.finditer(r"\$|\\[([]", text):
        if not _common()._escaped(text, match.start()):
            return True
    return False


def renderer_info() -> dict:
    """Identify the actual shared converter and all its shipped package content."""
    result = {"engine": "latex2mathml", "available": False, "version": None,
              "configuration": dict(_common().CONFIGURATION), "package_sha256": None}
    try:
        spec = importlib.util.find_spec("latex2mathml")
        if spec is None or spec.origin is None:
            return result
        directory = Path(spec.origin).resolve().parent
        rows = [
            [path.relative_to(directory).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()]
            for path in sorted(directory.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ]
        try:
            version = importlib.metadata.version("latex2mathml")
        except importlib.metadata.PackageNotFoundError:
            version = "unrecorded"
        result.update(available=True, version=version,
                      package_sha256=hashlib.sha256(json.dumps(rows, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")).hexdigest())
    except (ImportError, OSError, ValueError):
        pass
    return result
