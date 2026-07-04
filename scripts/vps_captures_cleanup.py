#!/usr/bin/env python3
"""VPS + 双云机：清理过期结算截图、相册 bot 残留、disk-spill。"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BOT_ROOT = Path(os.environ.get("BOT_ROOT", "/home/bot/55chat-bot"))
CAPTURES = BOT_ROOT / "data" / "captures"
SPILL = BOT_ROOT / "data" / "disk-spill"
RETENTION_DAYS = max(1, int(os.environ.get("BOT_CAPTURES_RETENTION_DAYS", "1") or 1))
SPILL_DAYS = max(1, int(os.environ.get("BOT_DISK_SPILL_RETENTION_DAYS", "7") or 7))
MAX_PNG_FILES = max(9, int(os.environ.get("BOT_CAPTURES_MAX_FILES", "30") or 30))


def _read_ports() -> tuple[str, str]:
    env = BOT_ROOT / "config" / "bot-start.env"
    rport, lport = "58433", "52840"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("BOT_LISTENER_ADB_PORT="):
                rport = line.split("=", 1)[1].strip()
            elif line.startswith("BOT_CLICKER_ADB_PORT="):
                lport = line.split("=", 1)[1].strip()
    return rport, lport


def _sh(cmd: str) -> str:
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, check=False,
    ).stdout.strip()


def _du(path: Path) -> str:
    if not path.exists():
        return "0"
    return _sh(f"du -sh {path} 2>/dev/null | cut -f1") or "?"


def _delete_old_png(directory: Path, days: int, label: str) -> int:
    if not directory.is_dir():
        return 0
    pattern = re.compile(r"^(pc28|mark6|trade)_\d+_\d+\.png$")
    removed = 0
    cutoff = days * 86400
    now = __import__("time").time()
    for p in directory.glob("*.png"):
        if not pattern.match(p.name):
            continue
        try:
            if now - p.stat().st_mtime >= cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    print(f"[captures-cleanup] {label}: removed {removed} (mtime>={days}d)")
    return removed


def _trim_excess_png(directory: Path, max_files: int, label: str) -> int:
    if not directory.is_dir() or max_files <= 0:
        return 0
    pattern = re.compile(r"^(pc28|mark6|trade)_\d+_\d+\.png$")
    files = [p for p in directory.glob("*.png") if pattern.match(p.name)]
    if len(files) <= max_files:
        return 0
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for p in files[max_files:]:
        try:
            p.unlink(missing_ok=True)
            removed += 1
        except OSError:
            pass
    print(f"[captures-cleanup] {label}: trimmed {removed} (keep newest {max_files})")
    return removed


def _clean_dcim(serials: list[str]) -> None:
    try:
        from bot_ops.ephemeral_burn import purge_gallery_bot_images, _mediastore_image_count
    except ImportError:
        purge_gallery_bot_images = None
        _mediastore_image_count = None
    for ser in serials:
        if purge_gallery_bot_images:
            before = _mediastore_image_count(ser) if _mediastore_image_count else -1
            pruned = purge_gallery_bot_images(ser)
            after = _mediastore_image_count(ser) if _mediastore_image_count else -1
            print(f"[captures-cleanup] DCIM {ser}: mediastore {before}->{after} pruned={pruned}")
            continue


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=RETENTION_DAYS, help="captures 保留天数")
    ap.add_argument("--max-files", type=int, default=MAX_PNG_FILES, help="最多保留 png 数")
    ap.add_argument("--skip-adb", action="store_true")
    args = ap.parse_args()

    print(f"[captures-cleanup] before captures={_du(CAPTURES)} spill={_du(SPILL)}")
    n = _delete_old_png(CAPTURES, args.days, "data/captures")
    n += _trim_excess_png(CAPTURES, args.max_files, "data/captures")
    if SPILL.is_dir():
        spill_rm = _sh(f"find {SPILL} -type f -mtime +{SPILL_DAYS} -delete 2>/dev/null; echo ok")
        print(f"[captures-cleanup] disk-spill trim >{SPILL_DAYS}d: {spill_rm or 'ok'}")
    print(f"[captures-cleanup] after captures={_du(CAPTURES)} (png_removed={n})")

    if not args.skip_adb:
        rport, lport = _read_ports()
        serials = []
        for port in (rport, lport):
            for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
                if "device" in _sh(f"adb -s {host} get-state 2>/dev/null"):
                    serials.append(host)
                    break
        _clean_dcim(serials)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
