#!/usr/bin/env python3
"""最小 Panel 桩：/api/bots + /api/trade-flow（本地与 APS 同接口形状）。"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

HOST = os.environ.get("EDGE_MOCK_PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("EDGE_MOCK_PANEL_PORT", "3000") or 3000)

BOTS = [
    {
        "id": "bot-3",
        "status": "ACTIVE",
        "platform": "55Messenger",
        "associatedGroup": os.environ.get("EDGE_MOCK_GROUP_LEFT", "苍井空测试"),
        "adbHost": f"127.0.0.1:{os.environ.get('BOT_CLICKER_ADB_PORT', '52840')}",
    },
    {
        "id": "bot-4",
        "status": "ACTIVE",
        "platform": "55Messenger",
        "associatedGroup": os.environ.get("EDGE_MOCK_GROUP_RIGHT", "苍井空测试"),
        "adbHost": f"127.0.0.1:{os.environ.get('BOT_LISTENER_ADB_PORT', '58433')}",
    },
]


def _json(handler: BaseHTTPRequestHandler, code: int, body: Any) -> None:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path)
        if path.path == "/api/bots":
            _json(self, 200, BOTS)
            return
        if path.path == "/api/trade-flow":
            qs = parse_qs(path.query)
            period = int((qs.get("period") or ["0"])[0] or 0)
            _json(self, 200, {"period": period, "rows": [], "mock": True})
            return
        _json(self, 404, {"error": "not found"})


def main() -> int:
    srv = HTTPServer((HOST, PORT), Handler)
    print(f"edge_mock_panel http://{HOST}:{PORT}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
