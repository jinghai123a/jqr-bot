#!/usr/bin/env python3
"""左机强制出站：发一条真实「新的一局」公告到群（验收用）。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from bot_ops.runtime import apply_bot_start_env  # noqa: E402

apply_bot_start_env(ROOT)

from bot_ops.adb_isolated import ensure_adb_servers  # noqa: E402

ensure_adb_servers()

import bot_55chat_daemon as d  # noqa: E402


def main() -> int:
    d.api("GET", "/api/bots")  # warm
    bots = d.api("GET", "/api/bots") or []
    bot = next((b for b in bots if str(b.get("id")) == "bot-3"), None)
    if not bot:
        print("FAIL: bot-3 missing")
        return 1
    port = os.environ.get("BOT_CLICKER_ADB_PORT", "55612")
    serial = d.resolve_serial_optional(f"localhost:{port}", label="force-out")
    if not serial:
        print(f"FAIL: clicker offline :{port}")
        return 1
    if not d.ensure_clicker_in_group(serial, bot, reason="force-out"):
        print("FAIL: not in target group")
        return 1
    raw = d.api("GET", "/api/settings") or {}
    settings = d.merge_settings(raw if isinstance(raw, dict) else None)
    snap = d.ui_snapshot(serial, chat=False, channel="force-out")
    rid, _, _ = d.active_round_timing(settings)
    text = d.build_open_announce_text(rid, settings)
    print(f"dispatch open rid={rid} serial={serial}")
    ok = d.dispatch_send(
        serial,
        bot,
        text,
        settings,
        input_xy=snap.input_xy,
        send_xy=snap.inbar_send or snap.keyboard_send,
        group_ok=True,
        prio=d.SEND_PRIO_OPEN,
        kind="open",
        round_id=rid,
    )
    if not ok:
        print("FAIL: dispatch_send returned False")
        return 1
    # 等待 sender 队列出队
    for i in range(40):
        time.sleep(0.5)
        root = d.ui_hierarchy(serial, force=(i % 4 == 0))
        if d._announce_already_visible(serial, bot, text):
            print(f"OK: announce visible in group rid={rid}")
            return 0
    print("WARN: dispatched but not confirmed on screen yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
