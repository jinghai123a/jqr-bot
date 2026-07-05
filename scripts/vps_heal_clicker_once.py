#!/usr/bin/env python3
"""VPS 单次左机 heal（production_deploy_run 调用）。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from bot_ops.vps_ports import dual_adb_ports  # noqa: E402

_, clicker_port = dual_adb_ports(ROOT)
adb_p = os.environ.get("BOT_CLICKER_ADB_SERVER_PORT", "5039")
out = subprocess.check_output(["adb", "-P", adb_p, "devices", "-l"], text=True)
serial = next(
    (ln.split()[0] for ln in out.splitlines() if f":{clicker_port}" in ln and " device" in ln),
    f"localhost:{clicker_port}",
)
from bot_55chat_daemon import (  # noqa: E402
    _return_from_gallery_to_chat,
    _verify_gallery_picker_open_serial,
    api,
    clicker_needs_messenger_restart,
    clicker_return_to_group,
    ensure_clicker_in_group,
    force_restart_messenger,
    in_target_group_chat,
    is_55m_foreground,
    is_on_launcher,
    relaunch_clicker_messenger,
    ui_hierarchy,
    wc,
)

bot = next((b for b in (api("GET", "/api/bots") or []) if str(b.get("id")) == "bot-3"), {})
print("heal_serial", serial, "fg", is_55m_foreground(serial), "launcher", is_on_launcher(serial))
if is_on_launcher(serial) or clicker_needs_messenger_restart(serial) or not is_55m_foreground(serial):
    relaunch_clicker_messenger(serial, reason="deploy-heal")
    wc(1.5, 0.5)
if _verify_gallery_picker_open_serial(serial):
    print("gallery_open", True)
    _return_from_gallery_to_chat(serial, bot)
    wc(0.8, 0.3)
ok = ensure_clicker_in_group(serial, bot, reason="deploy-heal")
if not ok:
    clicker_return_to_group(serial, bot, label="deploy-heal-retry")
    wc(0.6, 0.25)
    ok = in_target_group_chat(ui_hierarchy(serial), bot, serial)
if not ok:
    force_restart_messenger(serial, reason="deploy-heal-hard")
    wc(2.0, 0.8)
    ok = ensure_clicker_in_group(serial, bot, reason="deploy-heal-hard")
print("ensure_ok", ok)
