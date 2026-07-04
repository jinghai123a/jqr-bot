#!/usr/bin/env python3
"""任务前：dump 云机 UI 上下文并与 config/55m-knowledge/ui-pages.json 对照。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if "fcntl" not in sys.modules:
    import types
    sys.modules["fcntl"] = types.ModuleType("fcntl")

import bot_55chat_daemon as d  # noqa: E402


def _load_bots() -> list[dict]:
    panel = ROOT / "config" / "bot-start.env"
    group = "苍井空测试"
    lport, rport = "52840", "58433"
    if panel.is_file():
        for line in panel.read_text(encoding="utf-8").splitlines():
            if line.startswith("BOT_TARGET_GROUP="):
                group = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("BOT_CLICKER_ADB_PORT="):
                lport = line.split("=", 1)[1].strip()
            elif line.startswith("BOT_LISTENER_ADB_PORT="):
                rport = line.split("=", 1)[1].strip()
    return [
        {"id": "bot-3", "associatedGroup": group, "adbHost": f"127.0.0.1:{lport}"},
        {"id": "bot-4", "associatedGroup": group, "adbHost": f"127.0.0.1:{rport}"},
    ]


def inspect(serial: str, bot: dict) -> dict:
    root = d.ui_hierarchy(serial)
    ctx = d.describe_screen_context(root, bot, serial)
    texts = d.collect_ui_texts(root) if root is not None else []
    act = ""
    try:
        act = d.adb_run(serial, "shell", "dumpsys", "window", "displays")
        for line in act.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                act = line.strip()
                break
    except Exception as ex:
        act = str(ex)
    return {
        "serial": serial,
        "bot_id": bot.get("id"),
        "page": ctx.page,
        "title": ctx.title,
        "target_group": ctx.target_group,
        "in_input": ctx.in_input,
        "in_target_group": d.in_target_group_chat(root, bot, serial),
        "group_chat_activity": d.is_group_chat_activity(serial),
        "foreground_55m": d.is_55m_foreground(serial),
        "activity_line": act[:240],
        "text_sample": texts[:40],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", default="", help="左机 serial，默认 BOT_CLICKER 端口")
    ap.add_argument("--right", default="", help="右机 serial")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pages_path = ROOT / "config" / "55m-knowledge" / "ui-pages.json"
    catalog = json.loads(pages_path.read_text(encoding="utf-8"))

    bots = _load_bots()
    by_id = {b.get("id"): b for b in bots}
    left_bot = by_id.get("bot-3") or bots[0]
    right_bot = by_id.get("bot-4") or (bots[1] if len(bots) > 1 else bots[0])

    left_serial = args.left or left_bot.get("adbHost") or "127.0.0.1:52840"
    right_serial = args.right or right_bot.get("adbHost") or "127.0.0.1:58433"

    report = {
        "catalog": str(pages_path.relative_to(ROOT)),
        "known_pages": list(catalog.get("pages", {}).keys()),
        "left": inspect(left_serial, left_bot),
        "right": inspect(right_serial, right_bot),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for side in ("left", "right"):
            row = report[side]
            print(f"=== {side.upper()} {row['serial']} bot={row['bot_id']} ===")
            print(f"page={row['page']} title={row['title']!r} in_target={row['in_target_group']}")
            print(f"GroupChatActivity={row['group_chat_activity']} 55m_fg={row['foreground_55m']}")
            print(f"activity: {row['activity_line']}")
            if row["page"] not in catalog.get("pages", {}) and row["page"] != "other":
                print(f"WARN: page {row['page']!r} 不在 ui-pages.json")
            if side == "left" and row["in_target_group"] and row["group_chat_activity"]:
                print("OK: 左机在目标群 — 禁止 header_back / 回群 step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
