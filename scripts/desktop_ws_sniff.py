#!/usr/bin/env python3
"""嗅探 68助手 WS 全部 inbound JSON（独占连接，10s）。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WS = os.environ.get("BOT_55WS_URL", "ws://127.0.0.1:5600")
GID = int(os.environ.get("DESKTOP_GROUP_ID", "492316") or 492316)


def main() -> int:
    import uuid

    import websocket  # type: ignore

    token = f"SNIFF-{int(time.time())}"
    lines: list[str] = []

    def on_msg(_w, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        lines.append(json.dumps(msg, ensure_ascii=False)[:500])
        if msg.get("message") == "Hello":
            _w.send(
                json.dumps(
                    {
                        "id": str(uuid.uuid4()),
                        "type": "sendMsg",
                        "data": {
                            "id": GID,
                            "type": "group",
                            "list": [{"type": "text", "values": {"chatType": 0, "content": token}}],
                            "quoteInfo": None,
                        },
                    },
                    ensure_ascii=False,
                )
            )

    ws = websocket.WebSocketApp(WS, on_message=on_msg)
    import threading

    threading.Thread(target=lambda: ws.run_forever(ping_interval=20, ping_timeout=8), daemon=True).start()
    time.sleep(8)
    ws.close()
    out = ROOT / "logs" / "ws_sniff.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"SNIFF_OK n={len(lines)} token={token} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
