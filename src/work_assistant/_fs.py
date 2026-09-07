from __future__ import annotations

import os
from pathlib import Path


def owner_write(path: Path, data: bytes, *, append: bool = False) -> None:
    """Write bytes so only the owner can read them (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    # O_EXCL is intentionally not used here: callers like backup/restore and
    # knowledge export overwrite their own files. Secrecy comes from 0600.
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if os.name != "nt":
        os.chmod(path, 0o600)


def assert_owner_only(path: Path, *, what: str = "secret file") -> None:
    """Fail closed when a secret file is readable by others."""
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{what} must be a regular file: {path}")
    if os.name == "nt":
        return
    stat = path.stat()
    try:
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ValueError(f"{what} must be owner-only (0600): {path}")
    except AttributeError:
        return
