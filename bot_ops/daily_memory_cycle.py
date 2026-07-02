"""铁律 #7：每日 19:35 北京时间（维护窗后）磁盘清理 → 内存落盘（云机 OpenAPI + VPS，不占隧道）。"""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bot_ops.ephemeral_burn import PRESERVE_FILES, burn_capture_tree

log = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))
DISK_SPILL_RETENTION_DAYS = max(1, int(os.environ.get("BOT_DISK_SPILL_RETENTION_DAYS", "7") or 7))


def _beijing_now() -> datetime:
    return datetime.now(BEIJING)


def disk_spill_root(root: Path) -> Path:
    p = root / "data" / "disk-spill"
    p.mkdir(parents=True, exist_ok=True)
    return p


def phase_vps_disk_clean(root: Path) -> dict[str, Any]:
    """阶段 1：清 VPS 磁盘上的过期垃圾（不动长期缓存）。"""
    counts: dict[str, Any] = {"phase": "disk_clean", "target": "vps"}
    spill = disk_spill_root(root)
    cutoff = _beijing_now() - timedelta(days=DISK_SPILL_RETENTION_DAYS)
    removed_dirs = 0
    for child in spill.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        try:
            # YYYYMMDD or YYYYMMDD_HHMMSS
            day = name[:8]
            dt = datetime.strptime(day, "%Y%m%d").replace(tzinfo=BEIJING)
            if dt < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed_dirs += 1
        except ValueError:
            continue
    counts["spill_dirs_removed"] = removed_dirs

    counts["captures_burned"] = burn_capture_tree(root / "data" / "captures")
    counts["physical_feedback_burned"] = _purge_dir_files(root / "artifacts" / "physical-feedback")
    counts["visual_captures_burned"] = _purge_dir_files(root / "logs" / "visual-captures")
    return counts


def phase_vps_memory_spill(root: Path) -> dict[str, Any]:
    """阶段 2：内存/临时文件落盘到 data/disk-spill（长期缓存不动）。"""
    stamp = _beijing_now().strftime("%Y%m%d_%H%M%S")
    dest = disk_spill_root(root) / stamp
    dest.mkdir(parents=True, exist_ok=True)
    moved = 0
    import tempfile

    tmpdir = tempfile.gettempdir()
    patterns = (
        os.path.join(tmpdir, "tess_*"),
        os.path.join(tmpdir, "adb*.png"),
        os.path.join(tmpdir, "closure_*.png"),
        os.path.join(tmpdir, "p8_*.png"),
        os.path.join(tmpdir, "bot_*.png"),
        "/tmp/tess_*",
        "/tmp/adb*.png",
        "/tmp/closure_*.png",
        "/tmp/p8_*.png",
        "/tmp/bot_*.png",
    )
    for pat in patterns:
        for fp in glob.glob(pat):
            base = os.path.basename(fp)
            if base in PRESERVE_FILES:
                continue
            try:
                if os.path.isfile(fp):
                    shutil.move(fp, dest / base)
                    moved += 1
            except OSError as ex:
                log.debug("spill skip %s: %s", fp, ex)

    # 热路径残留 OCR/验真图 → 落盘而非即删
    for rel in ("artifacts/physical-feedback",):
        src = root / rel
        if src.is_dir():
            for fp in list(src.glob("*.png"))[:200]:
                if fp.name in PRESERVE_FILES:
                    continue
                try:
                    shutil.move(str(fp), dest / f"pf_{fp.name}")
                    moved += 1
                except OSError:
                    pass

    try:
        os.sync()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        subprocess_sync()

    return {"phase": "memory_spill", "target": "vps", "dest": str(dest), "files_moved": moved}


def subprocess_sync() -> None:
    import subprocess
    import sys

    if sys.platform == "win32":
        return
    try:
        subprocess.run(["sync"], timeout=30, check=False)
    except (FileNotFoundError, OSError):
        pass


def _purge_dir_files(directory: Path) -> int:
    n = 0
    if not directory.is_dir():
        return 0
    for fp in directory.rglob("*"):
        if fp.is_file() and fp.name not in PRESERVE_FILES:
            try:
                fp.unlink(missing_ok=True)
                n += 1
            except OSError:
                pass
    return n


def _load_pad_codes(root: Path) -> list[str]:
    pads_path = root / "config" / "vmos-pads.json"
    if not pads_path.is_file():
        return []
    pads_cfg = json.loads(pads_path.read_text(encoding="utf-8"))
    codes: list[str] = []
    for side in ("right", "left"):
        pc = (pads_cfg.get(side) or {}).get("pad_code") or (pads_cfg.get(side) or {}).get("padCode")
        if pc:
            codes.append(str(pc))
    return codes


def _vmos_client(root: Path):
    try:
        from bot_tunnel import load_env_file
        from scripts.vmos_api_client import VmosApiClient
    except ImportError:
        return None, []

    api_env = load_env_file(root / "config" / "vmos-api.env")
    ak = api_env.get("VMOS_ACCESS_KEY") or api_env.get("VMOS_AK")
    sk = api_env.get("VMOS_SECRET_KEY") or api_env.get("VMOS_SK")
    if not ak or not sk:
        return None, []
    return VmosApiClient(ak, sk), _load_pad_codes(root)


# 云机阶段 1：清磁盘临时/过期 bot 文件（asyncCmd，不占隧道）
_CLOUD_DISK_CLEAN = (
    "rm -f /sdcard/01.png /sdcard/ui.xml /sdcard/Download/bot_*.png 2>/dev/null;"
    "find /sdcard/bot_spill -type f -mtime +7 -delete 2>/dev/null;"
    "rm -f /sdcard/DCIM/Camera/bot_*.png /sdcard/Pictures/bot_*.png 2>/dev/null;"
    "echo DISK_CLEAN_OK"
)

# 云机阶段 2：内存诊断落盘 + trim cache（asyncCmd）
_CLOUD_MEMORY_SPILL = (
    "mkdir -p /sdcard/bot_spill/$(date +%Y%m%d) 2>/dev/null;"
    "dumpsys meminfo > /sdcard/bot_spill/$(date +%Y%m%d)/meminfo_$(date +%H%M).txt 2>/dev/null;"
    "pm trim-caches 600M 2>/dev/null;"
    "sync;"
    "echo MEM_SPILL_OK"
)


def phase_cloud_disk_clean(root: Path) -> dict[str, Any]:
    """云机阶段 1：OpenAPI cleanAppHome + asyncCmd 清磁盘。"""
    out: dict[str, Any] = {"phase": "disk_clean", "target": "cloud", "tunnel": False}
    client, codes = _vmos_client(root)
    if not client or not codes:
        out["status"] = "skip_no_api_or_pads"
        return out
    try:
        client.post("/vcpcloud/api/padApi/cleanAppHome", {"padCodes": codes})
        out["cleanAppHome"] = "ok"
    except Exception as ex:
        out["cleanAppHome"] = f"fail:{ex}"
    try:
        client.async_cmd(codes, _CLOUD_DISK_CLEAN)
        out["asyncCmd_disk"] = "ok"
    except Exception as ex:
        out["asyncCmd_disk"] = f"fail:{ex}"
    return out


def phase_cloud_memory_spill(root: Path) -> dict[str, Any]:
    """云机阶段 2：内存信息落盘 + trim（不占隧道）。"""
    out: dict[str, Any] = {"phase": "memory_spill", "target": "cloud", "tunnel": False}
    client, codes = _vmos_client(root)
    if not client or not codes:
        out["status"] = "skip_no_api_or_pads"
        return out
    try:
        client.async_cmd(codes, _CLOUD_MEMORY_SPILL)
        out["asyncCmd_spill"] = "ok"
    except Exception as ex:
        out["asyncCmd_spill"] = f"fail:{ex}"
    return out


def run_daily_memory_cycle(root: Path | None = None) -> dict[str, Any]:
    """每日 cron 入口（默认 19:35）：先磁盘清理，再内存落盘。"""
    root = root or Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
    report: dict[str, Any] = {
        "job": "daily_memory_cycle",
        "ts": _beijing_now().isoformat(),
        "retention_days": DISK_SPILL_RETENTION_DAYS,
        "preserve": sorted(PRESERVE_FILES),
        "phases": [],
    }
    log.info("[铁律7] daily cycle start ts=%s", report["ts"])

    disk_vps = phase_vps_disk_clean(root)
    disk_cloud = phase_cloud_disk_clean(root)
    report["phases"].append({"step": 1, "disk_clean": {"vps": disk_vps, "cloud": disk_cloud}})

    spill_vps = phase_vps_memory_spill(root)
    spill_cloud = phase_cloud_memory_spill(root)
    report["phases"].append({"step": 2, "memory_spill": {"vps": spill_vps, "cloud": spill_cloud}})

    report["ok"] = True
    log.info("[铁律7] daily cycle done %s", json.dumps(report, ensure_ascii=False)[:500])
    return report
