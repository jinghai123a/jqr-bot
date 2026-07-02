#!/usr/bin/env python3
"""VPS 一次性 heal：同步 gate + 左机出相册（不 restart daemon）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from bot_ops.runtime import apply_bot_start_env

apply_bot_start_env(ROOT)

import bot_55chat_daemon as d


def main() -> int:
    from bot_ops.adb_isolated import ensure_adb_servers

    ensure_adb_servers()
    d.load_round_bets_persisted()
    bots = d.api("GET", "/api/bots") or []
    settings = d.merge_settings(d.api("GET", "/api/settings"))
    active = d.active_messenger_bots(bots)
    d.register_deploy_serial_roles(active)

    listener = next((b for b in active if d.is_send_bot(b)), None)
    clicker = next((b for b in active if d.is_clicker_bot(b)), None)
    if not listener or not clicker:
        print("missing listener/clicker bot")
        return 1

    lserial = d.resolve_serial_optional(str(listener.get("adbHost") or ""), label="heal-L")
    cserial = d.resolve_serial_optional(str(clicker.get("adbHost") or ""), label="heal-C")
    if not lserial or not cserial:
        print("adb serial unavailable", lserial, cserial)
        return 1

    print("listener", lserial, "clicker", cserial)

    # 右机：webview/搜索/选图页 → 关页回群（铁律1 实时在岗）
    lroot = d.ui_hierarchy(lserial, force=True)
    lctx = d.describe_screen_context(lroot, listener, lserial)
    ltexts = d.collect_ui_texts(lroot) if lroot is not None else []
    if lctx.page != "target_group" or not d.in_target_group_chat(lroot, listener, lserial):
        print("listener heal ctx", lctx.page, lctx.summary(lserial))
        if any(t == "发送图片" for t in ltexts):
            d._dismiss_image_picker(lserial)
        d.dismiss_listener_blockers(lserial, lroot)
        if not d.listener_in_group_for_send(d.ui_hierarchy(lserial), listener, lserial):
            d.recover_listener_to_group_minimal(lserial, listener)

    root = d.ui_hierarchy(cserial)
    if not d.in_target_group_chat(root, clicker, cserial):
        d.force_exit_clicker_image_picker(cserial, reason="vps-heal")
        if d.dismiss_clicker_album_stuck(cserial):
            print("clicker album dismissed")
    d.ensure_clicker_in_group(cserial, clicker, reason="vps-heal")

    lroot2 = d.ui_hierarchy(lserial, force=True)
    croot2 = d.ui_hierarchy(cserial, force=True)
    print(
        "post_heal R",
        d.describe_screen_context(lroot2, listener, lserial).page,
        "IN_TARGET",
        d.in_target_group_chat(lroot2, listener, lserial),
    )
    print(
        "post_heal L",
        d.describe_screen_context(croot2, clicker, cserial).page,
        "IN_TARGET",
        d.in_target_group_chat(croot2, clicker, cserial),
    )

    synced = d.sync_open_gate_from_chat(lserial, listener, settings)
    print("gate synced", synced, d._ROUND_OPEN_ANNOUNCED)

    rid, _, rem = d.active_round_timing(settings)
    print("timing rid", rid, "remaining", rem)

    gate_path = ROOT / "data" / "round_open_announced.json"
    if gate_path.is_file():
        print("gate file", gate_path.read_text(encoding="utf-8"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
