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
    api,
    clicker_needs_messenger_restart,
    ensure_clicker_in_group,
    is_55m_foreground,
    is_on_launcher,
    relaunch_clicker_messenger,
    wc,
)

bot = next((b for b in (api("GET", "/api/bots") or []) if str(b.get("id")) == "bot-3"), {})
print("heal_serial", serial, "fg", is_55m_foreground(serial), "launcher", is_on_launcher(serial))
if is_on_launcher(serial) or clicker_needs_messenger_restart(serial) or not is_55m_foreground(serial):
    relaunch_clicker_messenger(serial, reason="deploy-heal")
    wc(1.5, 0.5)
print("ensure_ok", ensure_clicker_in_group(serial, bot, reason="deploy-heal"))
