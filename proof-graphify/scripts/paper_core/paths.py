"""Path resolution at filesystem input boundaries."""
from pathlib import Path


def resolve_path(value):
    # Some restricted Windows runtimes misresolve relative paths. Make the
    # path absolute first, preserving '..' for normal symlink resolution.
    return Path(value).absolute().resolve()
