"""用完即焚 — 仅保留认人缓存与业务持久化数据。"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

# 长期保留（认人 + 配置 + 局状态）
PRESERVE_FILES = frozenset(
    {
        "mid_cache.json",
        "gateway_user_cache.json",
        "pinned-coords.json",
        "bot-start.env",
        "settled_rounds.json",
        "round_bets.json",
        "round_open_announced.json",
        "lean-watchdog-state.json",
    }
)

BURN_AFTER_SEND = os.environ.get("BOT_CAPTURE_BURN_AFTER_SEND", "1").strip() not in (
    "0",
    "false",
    "no",
)


def burn_paths(paths: Iterable[str]) -> int:
    n = 0
    for raw in paths:
        p = (raw or "").strip()
        if not p or not os.path.isfile(p):
            continue
        base = os.path.basename(p)
        if base in PRESERVE_FILES:
            continue
        try:
            os.remove(p)
            n += 1
            log.debug("[BURN] file %s", p)
        except OSError as ex:
            log.debug("[BURN] skip %s: %s", p, ex)
    return n


def burn_capture_tree(capture_dir: str | Path | None = None) -> int:
    """结算 PNG / archive — 发群后不再需要。"""
    root = Path(capture_dir or os.environ.get("BOT_CAPTURE_DIR", ""))
    if not root:
        try:
            from board_capture import CAPTURE_DIR

            root = Path(CAPTURE_DIR)
        except Exception:
            return 0
    if not root.is_dir():
        return 0
    n = 0
    for pat in ("*.png", "archive/**/*.png"):
        for fp in root.glob(pat):
            try:
                fp.unlink(missing_ok=True)
                n += 1
            except OSError:
                pass
    archive = root / "archive"
    if archive.is_dir():
        for d in list(archive.rglob("*")):
            if d.is_dir():
                try:
                    shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass
    return n


def purge_gallery_bot_images(serial: str) -> None:
    """云机 DCIM 内 bot_ 推图 — 发完即删。"""
    if not serial:
        return
    try:
        from bot_ops.adb_isolated import adb_cmd

        for remote in (
            "/sdcard/DCIM/Camera/bot_*.png",
            "/sdcard/DCIM/Camera/pc28*.png",
            "/sdcard/DCIM/Camera/*settle*.png",
            "/sdcard/Pictures/bot_*.png",
            "/sdcard/Pictures/pc28*.png",
        ):
            subprocess.run(
                adb_cmd(serial, "shell", f"rm -f {remote}"),
                capture_output=True,
                timeout=15,
                check=False,
            )
    except Exception as ex:
        log.debug("[BURN] gallery %s: %s", serial, ex)


def burn_after_group_images_sent(serial: str, paths: Iterable[str]) -> dict[str, int]:
    """群聊发图验证成功后调用。"""
    if not BURN_AFTER_SEND:
        return {"files": 0, "captures": 0}
    files = burn_paths(paths)
    captures = burn_capture_tree()
    purge_gallery_bot_images(serial)
    out = {"files": files, "captures": captures}
    if files or captures:
        log.info("[BURN] after send serial=%s %s", serial, out)
    return out


def burn_vps_ephemeral(root: Path | None = None) -> dict[str, int]:
    """定时清扫：OCR 临时图、巡检截图、visual 目录。"""
    root = root or Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
    counts: dict[str, int] = {}

    def _rm_glob(label: str, pattern: str) -> None:
        n = 0
        for fp in glob.glob(pattern):
            try:
                if os.path.isfile(fp) and os.path.basename(fp) not in PRESERVE_FILES:
                    os.remove(fp)
                    n += 1
            except OSError:
                pass
        if n:
            counts[label] = n

    _rm_glob("tess_tmp", "/tmp/tess_*")
    _rm_glob("adb_tmp", "/tmp/adb*.png")
    _rm_glob("closure_png", "/tmp/closure_*.png")
    _rm_glob("p8_png", "/tmp/p8_*.png")

    for rel in (
        "artifacts/physical-feedback",
        "logs/visual-captures",
        "data/captures",
    ):
        p = root / rel
        if p.is_dir():
            counts[rel] = burn_capture_tree(p) if "captures" in rel else _purge_dir_files(p)

    return counts


def _purge_dir_files(directory: Path) -> int:
    n = 0
    for fp in directory.rglob("*"):
        if fp.is_file() and fp.name not in PRESERVE_FILES:
            try:
                fp.unlink(missing_ok=True)
                n += 1
            except OSError:
                pass
    return n
