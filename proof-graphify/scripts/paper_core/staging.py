"""Operation-local staging in an already authorized output parent."""
from __future__ import annotations

from contextlib import contextmanager
from os import mkdir as _mkdir
from pathlib import Path
from secrets import token_hex as _token_hex
from shutil import rmtree as _rmtree
import os


def _create(parent: Path, prefix: str, *, platform: str | None = None) -> Path:
    path = Path(parent) / (prefix + _token_hex(16))
    # Windows inherits the approved parent's permissions; POSIX stays private.
    if (os.name if platform is None else platform) == "nt":
        _mkdir(path)
    else:
        _mkdir(path, 0o700)
    return path


def _cleanup(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return  # Freeze moved the directory to its final name.
    _rmtree(path)


@contextmanager
def staging_directory(parent: Path, prefix: str):
    """Create one exclusive sibling directory; cleanup never masks its first error."""
    path = _create(parent, prefix)
    try:
        yield path
    except BaseException as primary:
        try:
            _cleanup(path)
        except Exception as cleanup:
            primary.add_note(f"Staging cleanup also failed at {path}: {cleanup}")
        raise
    else:
        _cleanup(path)
