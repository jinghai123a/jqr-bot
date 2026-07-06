#!/usr/bin/env python3
"""独占 WS 探针：发一条带 token 的消息，等 msgNew(isSelf) 回显才算群 OUT 成功。"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WS_URL = os.environ.get("BOT_55WS_URL", "ws://127.0.0.1:5600")
TARGET = os.environ.get("BOT_TARGET_GROUP", "苍井空测试")
GID_ENV = os.environ.get("DESKTOP_GROUP_ID", "")
TOKEN = f"W49-VERIFY-{int(time.time())}"


def main() -> int:
    try:
        import websocket  # type: ignore
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "websocket-client"])
        import websocket  # type: ignore

    group_id: int | None = int(GID_ENV) if GID_ENV else None
    groups_raw: list = []
    seen_self = False
    done = {"ok": False}

    def on_message(_ws: object, raw: str) -> None:
        nonlocal group_id, seen_self
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        if msg.get("type") == "getGroups" and isinstance(msg.get("data"), list):
            groups_raw.clear()
            groups_raw.extend(msg["data"])
            for g in msg["data"]:
                name = str(g.get("name") or "")
                if TARGET in name and not group_id:
                    group_id = int(g.get("id") or 0) or None
            return

        if msg.get("operator") == "msgNew":
            d = msg.get("data") or {}
            content = str(d.get("content") or "")
            if TOKEN in content and (d.get("isSelf") or d.get("type") == "group"):
                seen_self = True
                done["ok"] = True
                _ws.close()

    def on_open(ws: object) -> None:
        ws.send(json.dumps({"id": "vg", "type": "getGroups"}))

    print(f"VERIFY connect {WS_URL} token={TOKEN}", flush=True)
    ws_app = websocket.WebSocketApp(WS_URL, on_message=on_message, on_open=on_open)
    import threading

    t = threading.Thread(target=lambda: ws_app.run_forever(ping_interval=20, ping_timeout=8), daemon=True)
    t.start()
    time.sleep(2)

    if not group_id and groups_raw:
        print("GROUPS:", json.dumps(groups_raw, ensure_ascii=False)[:500], flush=True)
    if not group_id:
        print("VERIFY_FAIL no group_id — set DESKTOP_GROUP_ID or fix getGroups", flush=True)
        return 2

    payload = {
        "id": str(uuid.uuid4()),
        "type": "sendMsg",
        "data": {
            "id": group_id,
            "type": "group",
            "list": [{"type": "text", "values": {"chatType": 0, "content": TOKEN}}],
            "quoteInfo": None,
        },
    }
    ws_app.send(json.dumps(payload, ensure_ascii=False))
    print(f"VERIFY sent gid={group_id} wait msgNew echo...", flush=True)

    deadline = time.time() + 12
    while time.time() < deadline and not done["ok"]:
        time.sleep(0.2)

    if done["ok"]:
        print(f"VERIFY_OK group={group_id} echo_seen={seen_self}", flush=True)
        return 0
    print("VERIFY_FAIL no msgNew echo — 68助手未把消息写入群聊", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
