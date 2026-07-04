#!/usr/bin/env python3
"""右机 LISTENER + 左机 CLICKER 拉回目标群（VPS 一键）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

GROUP = os.environ.get("BOT_TARGET_GROUP", "苍井空测试").strip()


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    _load_env_file(ROOT / "config" / "bot-start.env")
    os.environ.setdefault("BOT_ALLOW_LISTENER_NAV", "1")
    os.environ.setdefault("BOT_ALLOW_CLICKER_NAV", "1")

    import bot_55chat_daemon as d  # noqa: WPS433

    listener_port = os.environ.get("BOT_LISTENER_ADB_PORT", "58433")
    clicker_port = os.environ.get("BOT_CLICKER_ADB_PORT", "52840")
    listener_serial = f"127.0.0.1:{listener_port}"
    clicker_serial = f"127.0.0.1:{clicker_port}"
    listener_bot = {"id": "bot-4", "associatedGroup": GROUP}
    clicker_bot = {"id": "bot-3", "associatedGroup": GROUP}

    rc = 0

    print(f"=== LISTENER {listener_serial} -> {GROUP!r} ===", flush=True)
    ok_l = d.recover_listener_to_group_minimal(listener_serial, listener_bot)
    if not ok_l:
        ok_l = d.recover_listener_to_group(listener_serial, GROUP)
    root_l = d.ui_hierarchy(listener_serial)
    in_l = d.in_target_group_chat(root_l, listener_bot, listener_serial)
    ctx_l = d.describe_screen_context(root_l, listener_bot, listener_serial)
    print(f"recover_ok={ok_l} in_group={in_l} page={ctx_l.page} title={ctx_l.title!r}", flush=True)
    print(f"AFTER ok={in_l}", flush=True)
    if not in_l:
        rc = 1

    print(f"\n=== CLICKER {clicker_serial} -> {GROUP!r} ===", flush=True)
    ok_c = d.recover_clicker_to_group_minimal(clicker_serial, clicker_bot)
    root_c = d.ui_hierarchy(clicker_serial)
    in_c = d.in_target_group_chat(root_c, clicker_bot, clicker_serial)
    ctx_c = d.describe_screen_context(root_c, clicker_bot, clicker_serial)
    print(f"recover_ok={ok_c} in_group={in_c} page={ctx_c.page} title={ctx_c.title!r}", flush=True)
    if not in_c:
        rc = 1

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
