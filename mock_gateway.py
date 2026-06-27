#!/usr/bin/env python3
"""Mock memory gateway: username -> user_id cache with chat routing."""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

USER_ID_CACHE: dict[str, str] = {}

HOST = os.environ.get("MOCK_GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("MOCK_GATEWAY_PORT", "8765"))

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def _highlight(color: str, tag: str, message: str) -> None:
    print(f"{color}{tag}{RESET} {message}", flush=True)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        if self.path == "/api/chat/message":
            self._handle_chat_message()
            return
        if self.path == "/api/chat/update_id":
            self._handle_update_id()
            return
        _send_json(self, 404, {"status": "error", "message": "not found"})

    def _handle_chat_message(self) -> None:
        data = _read_json(self)
        if data is None:
            _send_json(self, 400, {"status": "error", "message": "invalid json"})
            return
        username = str(data.get("username") or "").strip()
        msg = str(data.get("msg") or "")
        if not username:
            _send_json(self, 400, {"status": "error", "message": "username required"})
            return

        user_id = USER_ID_CACHE.get(username)
        if user_id is not None:
            _highlight(GREEN, "[极速放行] 命中缓存", f"username={username} user_id={user_id} msg={msg!r}")
            _send_json(self, 200, {"status": "success", "user_id": user_id})
            return

        _highlight(
            YELLOW,
            "[风控拦截] 未知用户，挂起并下发认人任务",
            f"username={username} msg={msg!r}",
        )
        _send_json(
            self,
            202,
            {"status": "pending", "action": "require_id_fetch", "username": username},
        )

    def _handle_update_id(self) -> None:
        data = _read_json(self)
        if data is None:
            _send_json(self, 400, {"status": "error", "message": "invalid json"})
            return
        username = str(data.get("username") or "").strip()
        user_id = str(data.get("user_id") or "").strip()
        if not username or not user_id:
            _send_json(self, 400, {"status": "error", "message": "username and user_id required"})
            return

        USER_ID_CACHE[username] = user_id
        _highlight(CYAN, "[缓存更新] 成功绑定新用户", f"username={username} user_id={user_id}")
        _send_json(self, 200, {"status": "success", "username": username, "user_id": user_id})


def main() -> None:
    server = HTTPServer((HOST, PORT), GatewayHandler)
    print(f"mock_gateway listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nmock_gateway stopped", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
