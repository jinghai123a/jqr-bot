#!/usr/bin/env python3
"""安全清理本机临时/日志/产物（保留本地测试必需文件）。"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 只删这些目录内的文件，不删目录本身
WIPE_DIRS = [
    ROOT / "logs",
    ROOT / "artifacts",
    ROOT / "data" / "edge_brain",
]

# 递归删 __pycache__ / .pytest_cache
PRUNE_NAMES = {"__pycache__", ".pytest_cache", "desktop_settle_*"}

KEEP_ROOT_FILES = {
    "config/bot-start.env",
    "config/tunnel-creds.local.env",
    "config/pinned-coords.json",
    "config/vmos-pads.json",
    "data/local-panel-state.json",
}


def _wipe_dir(d: Path, *, dry: bool) -> tuple[int, int]:
    files, freed = 0, 0
    if not d.is_dir():
        return files, freed
    for p in d.iterdir():
        if p.is_file():
            files += 1
            freed += p.stat().st_size
            if not dry:
                p.unlink(missing_ok=True)
    return files, freed


def _prune_pycache(base: Path, *, dry: bool) -> int:
    n = 0
    for p in base.rglob("__pycache__"):
        if p.is_dir():
            n += 1
            if not dry:
                shutil.rmtree(p, ignore_errors=True)
    for p in base.glob("scripts/_*"):
        if p.is_file() and p.name.startswith("_audit_"):
            n += 1
            if not dry:
                p.unlink(missing_ok=True)
    return n


def _clean_temp_settle(*, dry: bool) -> int:
    n = 0
    td = Path(tempfile.gettempdir())
    for p in td.glob("desktop_settle_*"):
        if p.is_dir():
            n += 1
            if not dry:
                shutil.rmtree(p, ignore_errors=True)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run
    total_files, total_bytes = 0, 0

    for d in WIPE_DIRS:
        f, b = _wipe_dir(d, dry=dry)
        total_files += f
        total_bytes += b
        print(f"{'[dry] ' if dry else ''}wipe {d.relative_to(ROOT)}: {f} files")

    pyc = _prune_pycache(ROOT, dry=dry)
    print(f"{'[dry] ' if dry else ''}prune __pycache__: {pyc} dirs")

    tmp = _clean_temp_settle(dry=dry)
    print(f"{'[dry] ' if dry else ''}temp desktop_settle_*: {tmp} dirs")

    mb = total_bytes / (1024 * 1024)
    print(f"CLEANUP_OK files={total_files} freed≈{mb:.1f}MB keep={','.join(KEEP_ROOT_FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
