"""Disposable overview directories beside an explicit database or HTML path.

Windows directories inherit their parent's ACL; POSIX directories are private.
Cleanup is explicit and reports failures to the operation's existing wrapper.
There is no permission repair or garbage-collection cleanup fallback.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil


def create_directory(parent, *, prefix):
    """Create one exclusive random sibling without reusing a collided path."""
    path = Path(parent) / (prefix + secrets.token_hex(16))
    if os.name == "nt":
        os.mkdir(path)
    else:
        os.mkdir(path, 0o700)
    return path


def cleanup_directory(path):
    """Remove owned staging contents, allowing cleanup errors to stay visible."""
    shutil.rmtree(path)
