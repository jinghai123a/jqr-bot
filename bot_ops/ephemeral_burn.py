"""用完即焚 — 仅保留认人缓存与业务持久化数据。"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
import threading
import time
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
BURN_DELAY_SEC = max(
    60.0,
    min(120.0, float(os.environ.get("BOT_CAPTURE_BURN_DELAY_SEC", "90") or 90)),
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


def _adb_cmd(serial: str, *args: str) -> list[str]:
    """左/右机隔离 ADB server（VPS 5038/5039）。"""
    port = os.environ.get("BOT_LISTENER_ADB_SERVER_PORT", "5038")
    if ":55612" in serial or serial.endswith(
        (os.environ.get("BOT_CLICKER_ADB_PORT", "55612"))
    ):
        port = os.environ.get("BOT_CLICKER_ADB_SERVER_PORT", "5039")
    return ["adb", "-P", str(port), "-s", serial, *args]


def _adb_shell(serial: str, *args: str, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _adb_cmd(serial, *args),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def purge_gallery_bot_images(serial: str) -> int:
    """云机 DCIM 内 bot 推图 + MediaStore 索引 — 发完即删。"""
    if not serial:
        return 0
    before = _mediastore_image_count(serial)
    removed = 0
    try:
        for remote in (
            "/sdcard/DCIM/Camera/bot_*.png",
            "/sdcard/DCIM/Camera/pc28*.png",
            "/sdcard/DCIM/Camera/mark6*.png",
            "/sdcard/DCIM/Camera/trade*.png",
            "/sdcard/DCIM/Camera/*settle*.png",
            "/sdcard/Pictures/bot_*.png",
            "/sdcard/Pictures/pc28*.png",
            "/sdcard/Pictures/mark6*.png",
            "/sdcard/Pictures/trade*.png",
        ):
            _adb_shell(serial, "shell", f"rm -f {remote}", timeout=15)
        # 幽灵图：文件已删但 MediaStore 仍显示数千条
        if before > 200:
            _adb_shell(
                serial,
                "shell",
                "find /sdcard/DCIM/Camera -maxdepth 1 -type f \\( -name '*.png' -o -name '*.jpg' \\) -delete",
                timeout=120,
            )
            _adb_shell(
                serial,
                "shell",
                "find /sdcard/Pictures -maxdepth 2 -type f \\( -name 'pc28*' -o -name 'mark6*' -o -name 'trade*' -o -name 'bot_*' \\) -delete",
                timeout=120,
            )
        removed += _purge_mediastore_bot_entries(serial)
        after = _mediastore_image_count(serial)
        if after > 30 and after >= before - 5:
            removed += _purge_mediastore_all_external(serial, batch=120, max_rounds=200)
            after = _mediastore_image_count(serial)
        pruned = max(0, before - after)
        if pruned:
            log.info("[BURN] gallery serial=%s %d -> %d (pruned %d)", serial, before, after, pruned)
        return max(removed, pruned)
    except Exception as ex:
        log.debug("[BURN] gallery %s: %s", serial, ex)
    return removed


def _mediastore_image_ids(serial: str, *, limit: int = 80) -> list[str]:
    import re

    r = _adb_shell(
        serial,
        "shell",
        "content",
        "query",
        "--uri",
        "content://media/external/images/media",
        "--projection",
        "_id",
        timeout=60,
    )
    if r.returncode != 0 and not r.stdout:
        log.warning(
            "[BURN] mediastore query fail serial=%s rc=%s err=%s",
            serial,
            r.returncode,
            (r.stderr or "")[:120],
        )
        return []
    ids: list[str] = []
    for line in (r.stdout or "").splitlines():
        if "Row:" not in line and "_id=" not in line:
            continue
        m = re.search(r"_id[=:](\d+)", line)
        if m:
            ids.append(m.group(1))
        if len(ids) >= limit:
            break
    return ids


def _purge_mediastore_shell_batch(serial: str, *, batch: int = 100) -> int:
    """VMOS 上 Python content delete 偶发无效，走 shell 批删。"""
    script = (
        f"content query --uri content://media/external/images/media --projection _id "
        f"| grep -oE '_id=[0-9]+' | head -{batch} | cut -d= -f2 | while read id; do "
        f"content delete --uri content://media/external/images/media/$id 2>/dev/null; done; "
        f"echo done"
    )
    r = _adb_shell(serial, "shell", script, timeout=180)
    return 1 if "done" in (r.stdout or "") else 0


def _purge_mediastore_by_ids(serial: str, ids: list[str]) -> int:
    n = 0
    for mid in ids:
        r = _adb_shell(
            serial,
            "shell",
            "content",
            "delete",
            "--uri",
            f"content://media/external/images/media/{mid}",
            timeout=15,
        )
        if r.returncode == 0:
            n += 1
    return n


def _purge_mediastore_all_external(serial: str, *, batch: int = 80, max_rounds: int = 150) -> int:
    """按 _id 批量删 external/images（LIKE 删不动时的核清理）。"""
    before = _mediastore_image_count(serial)
    if before <= 3:
        return 0
    removed = 0
    for rnd in range(max_rounds):
        if _mediastore_image_count(serial) <= 3:
            break
        ids = _mediastore_image_ids(serial, limit=batch)
        if ids:
            removed += _purge_mediastore_by_ids(serial, ids)
        else:
            _purge_mediastore_shell_batch(serial, batch=max(batch, 100))
        if rnd % 10 == 9:
            _adb_shell(
                serial,
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_MOUNTED",
                "-d",
                "file:///sdcard",
                timeout=15,
            )
    after = _mediastore_image_count(serial)
    pruned = max(0, before - after)
    if pruned:
        log.info(
            "[BURN] mediastore nuclear serial=%s %d -> %d (pruned %d)",
            serial,
            before,
            after,
            pruned,
        )
    return pruned


def _purge_mediastore_bot_entries(serial: str) -> int:
    """清理 MediaProvider 中 bot/结算图索引（文件已删但相册仍显示数千张的根因）。"""
    before = _mediastore_image_count(serial)
    clauses = (
        "_data LIKE '%/bot_%'",
        "_data LIKE '%/pc28_%'",
        "_data LIKE '%/mark6_%'",
        "_data LIKE '%/trade_%'",
        "_data LIKE '%/probe_%'",
        "_display_name LIKE 'bot_%'",
        "_display_name LIKE 'pc28_%'",
        "_display_name LIKE 'mark6_%'",
        "_display_name LIKE 'trade_%'",
        "_display_name LIKE 'probe_%'",
    )
    for where in clauses:
        _adb_shell(
            serial,
            "shell",
            "content",
            "delete",
            "--uri",
            "content://media/external/images/media",
            "--where",
            where,
            timeout=60,
        )
    _adb_shell(
        serial,
        "shell",
        "am",
        "broadcast",
        "-a",
        "android.intent.action.MEDIA_MOUNTED",
        "-d",
        "file:///sdcard",
        timeout=15,
    )
    after = _mediastore_image_count(serial)
    pruned = max(0, before - after)
    if pruned:
        log.info("[BURN] mediastore serial=%s %d -> %d (pruned %d)", serial, before, after, pruned)
        return pruned
    if before > 30:
        return _purge_mediastore_all_external(serial)
    return 0


def purge_gallery_if_swollen(serial: str, *, threshold: int = 80) -> int:
    """相册幽灵图超阈值时主动核清理（左机 DCIM/MediaStore）。"""
    count = _mediastore_image_count(serial)
    if count <= threshold:
        return 0
    log.warning("[BURN] mediastore swollen serial=%s count=%d → purge", serial, count)
    return purge_gallery_bot_images(serial)


def _mediastore_image_count(serial: str) -> int:
    r = _adb_shell(
        serial,
        "shell",
        "content",
        "query",
        "--uri",
        "content://media/external/images/media",
        "--projection",
        "_id",
        timeout=45,
    )
    if r.returncode != 0:
        return 0
    return sum(1 for line in r.stdout.splitlines() if "Row:" in line)


def burn_after_group_images_sent(serial: str, paths: Iterable[str]) -> dict[str, int]:
    """群聊发图验证成功后调用。"""
    if not BURN_AFTER_SEND:
        return {"files": 0, "captures": 0}
    files = burn_paths(paths)
    captures = burn_capture_tree()
    gallery = purge_gallery_bot_images(serial)
    out = {"files": files, "captures": captures, "gallery": gallery}
    if files or captures:
        log.info("[BURN] after send serial=%s %s", serial, out)
    return out


def defer_burn_after_group_images_sent(
    serial: str,
    paths: Iterable[str],
    *,
    delay_sec: float | None = None,
) -> None:
    """延后烧图：给 55M 异步上传留窗口（默认 90s）。"""
    if not BURN_AFTER_SEND:
        return
    delay = delay_sec if delay_sec is not None else BURN_DELAY_SEC
    paths_list = [p for p in paths if p]
    if not paths_list:
        return

    def _job() -> None:
        try:
            time.sleep(delay)
            burn_after_group_images_sent(serial, paths_list)
            log.info("[BURN] deferred %.0fs serial=%s done", delay, serial)
        except Exception as ex:
            log.debug("[BURN] deferred serial=%s: %s", serial, ex)

    threading.Thread(
        target=_job,
        name=f"burn-defer-{serial}",
        daemon=True,
    ).start()
    log.info("[BURN] scheduled %.0fs serial=%s n=%d", delay, serial, len(paths_list))


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
