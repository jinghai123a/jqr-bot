#!/usr/bin/env python3
"""VPS 上 dump 左机 UI（一次性远程诊断）。"""
from __future__ import annotations

import os
import sys

os.chdir("/home/bot/55chat-bot")
sys.path.insert(0, "/home/bot/55chat-bot")

from bot_55chat_daemon import (  # noqa: E402
    api,
    collect_ui_texts,
    describe_screen_context,
    get_chat_title,
    in_target_group_chat,
    is_search_page,
    ui_hierarchy,
)

serial = "localhost:55612"
bot = next((b for b in (api("GET", "/api/bots") or []) if str(b.get("id")) == "bot-3"), {})
root = ui_hierarchy(serial, force=True)
texts = collect_ui_texts(root) if root else []
print("title", repr(get_chat_title(root)))
print("is_search", is_search_page(root, serial))
print("in_target", in_target_group_chat(root, bot, serial))
ctx = describe_screen_context(root, bot, serial)
print("page", ctx.page, "target_group", bot.get("associatedGroup"))
for t in texts[:50]:
    print("T", repr(t[:80]))
