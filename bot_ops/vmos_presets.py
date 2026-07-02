"""VMOS OpenAPI asyncCmd 预设 — 对应控制台「ADB命令」，免占 SSH 隧道。"""
from __future__ import annotations

from typing import Any

# 控制台常用命令 → scriptContent（多条用英文分号 ; 分隔）
# API: POST /vcpcloud/api/padApi/asyncCmd  body: padCodes + scriptContent
VMOS_ASYNC_PRESETS: dict[str, str] = {
    "screenshot": "screencap -p /sdcard/01.png",
    "wake_screen": "input keyevent 224",
    "ui_dump": "uiautomator dump /sdcard/ui.xml",
    "device_model": "getprop ro.product.model",
    "device_brand": "getprop ro.product.brand",
    "device_serial": "getprop ro.serialno",
    "wm_size": "wm size",
    "wm_density": "wm density",
    "wifi_enable": "svc wifi enable",
    "wifi_disable": "svc wifi disable",
    "go_home": "input keyevent HOME",
    "back": "input keyevent 4",
    "disk_clean_bot": (
        "rm -f /sdcard/01.png /sdcard/ui.xml /sdcard/Download/bot_*.png 2>/dev/null;"
        "find /sdcard/bot_spill -type f -mtime +7 -delete 2>/dev/null;"
        "rm -f /sdcard/DCIM/Camera/bot_*.png /sdcard/Pictures/bot_*.png 2>/dev/null"
    ),
    "memory_spill": (
        "mkdir -p /sdcard/bot_spill/$(date +%Y%m%d) 2>/dev/null;"
        "dumpsys meminfo > /sdcard/bot_spill/$(date +%Y%m%d)/meminfo_$(date +%H%M).txt 2>/dev/null;"
        "pm trim-caches 600M 2>/dev/null;sync"
    ),
    "resolution_720": "wm size 720x1280 && wm density 360",
    "resolution_query": "wm size;wm density",
    "resolution_reset": "wm size reset;wm density reset",
    "statusbar_expand": "service call statusbar 1",
    "statusbar_collapse": "service call statusbar 2",
    "reboot": "reboot",
}


def async_cmd_preset(
    client: Any,
    pad_codes: list[str],
    preset: str,
    *,
    extra: str = "",
) -> list[dict[str, Any]]:
    """经 OpenAPI asyncCmd 执行预设，不经过 ADB 隧道。"""
    script = VMOS_ASYNC_PRESETS.get(preset)
    if not script:
        raise ValueError(f"unknown preset: {preset}")
    if extra:
        script = f"{script};{extra}"
    return client.async_cmd(pad_codes, script)
