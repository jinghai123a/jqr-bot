"""Process-wide refresh lock (fcntl on Linux, msvcrt on Windows)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def acquire_refresh_lock(root: Path) -> int | None:
    lock_path = root / "logs" / ".vmos-refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fp = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fp, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fp)
        return None
    return fp