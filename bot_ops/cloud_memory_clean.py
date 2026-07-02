"""双云机内存/后台清理 — ADB + VMOS 云集 API（不杀 55M）。"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# 轻量 shell：杀第三方后台 + trim cache，保留 wuwu.*
_TRIM_SCRIPT = r"""
for pkg in $(pm list packages -3 2>/dev/null | cut -d: -f2); do
  case "$pkg" in wuwu.*|com.android.adbkeyboard|com.zx.adbkeyboard) continue ;; esac
  am force-stop "$pkg" 2>/dev/null
done
pm trim-caches 800M 2>/dev/null || true
am kill-all 2>/dev/null || true
input keyevent KEYCODE_HOME 2>/dev/null || true
echo MEM_CLEAN_OK
"""


def adb_trim_device(serial: str) -> bool:
    from bot_ops.adb_isolated import adb_cmd

    try:
        r = subprocess.run(
            adb_cmd(serial, "shell", _TRIM_SCRIPT),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        out = (r.stdout or "") + (r.stderr or "")
        ok = "MEM_CLEAN_OK" in out
        log.info("[MEM-CLEAN] serial=%s ok=%s", serial, ok)
        return ok
    except Exception as ex:
        log.warning("[MEM-CLEAN] adb %s: %s", serial, ex)
        return False


def trim_both_cloud_phones(root: Path | None = None) -> dict[str, bool]:
    from bot_ops.runtime import load_bot_runtime

    rt = load_bot_runtime(root)
    return {
        "listener": adb_trim_device(rt.listener_serial),
        "clicker": adb_trim_device(rt.clicker_serial),
    }


def vmos_clean_app_home(root: Path | None = None) -> dict[str, str]:
    """云集 VMOS：cleanAppHome + asyncCmd 兜底。"""
    import json
    import os
    import sys

    root = root or Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(root))
    from bot_tunnel import load_env_file
    from scripts.vmos_api_client import VmosApiClient

    api_env = load_env_file(root / "config" / "vmos-api.env")
    ak = api_env.get("VMOS_ACCESS_KEY") or api_env.get("VMOS_AK")
    sk = api_env.get("VMOS_SECRET_KEY") or api_env.get("VMOS_SK")
    if not ak or not sk:
        return {"vmos": "skip_no_api_env"}
    pads_cfg = {}
    pads_path = root / "config" / "vmos-pads.json"
    if pads_path.is_file():
        pads_cfg = json.loads(pads_path.read_text(encoding="utf-8"))
    codes: list[str] = []
    for side in ("right", "left"):
        pc = (pads_cfg.get(side) or {}).get("pad_code") or (pads_cfg.get(side) or {}).get("padCode")
        if pc:
            codes.append(str(pc))
    if not codes:
        return {"vmos": "skip_no_pad_codes"}
    client = VmosApiClient(ak, sk)
    out: dict[str, str] = {}
    try:
        client.post("/vcpcloud/api/padApi/cleanAppHome", {"padCodes": codes})
        out["cleanAppHome"] = "ok"
    except Exception as ex:
        out["cleanAppHome"] = f"fail:{ex}"
    try:
        client.async_cmd(codes, _TRIM_SCRIPT)
        out["asyncCmd"] = "ok"
    except Exception as ex:
        out["asyncCmd"] = f"fail:{ex}"
    return out
