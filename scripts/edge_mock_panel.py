#!/usr/bin/env python3
"""本地 Panel 桩：bots/settings/users/流水/28.run 对齐。"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOST = os.environ.get("EDGE_MOCK_PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("EDGE_MOCK_PANEL_PORT", "3000") or 3000)
STATE_PATH = ROOT / "data" / "local-panel-state.json"
KNOWLEDGE = ROOT / "config" / "55m-knowledge" / "announce-templates.json"
CATALOG = ROOT / "config" / "55m-knowledge" / "panel-catalog.json"
_LOCK = threading.Lock()
_CATALOG_CACHE: tuple[list[Any], list[Any]] | None = None


def _default_state() -> dict[str, Any]:
    return {
        "users": [
            {
                "botId": "bot-4",
                "username": "测试用户",
                "balance": 10000.0,
                "customerCode": "10001",
                "messengerId": "",
            }
        ],
        "topup_requests": [],
        "withdraw_requests": [],
        "bills": [],
    }


def _load_state() -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.is_file():
        st = _default_state()
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        return st
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()


def _save_state(st: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _load_catalog() -> tuple[list[Any], list[Any]]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    if not CATALOG.is_file():
        _CATALOG_CACHE = ([], [])
        return _CATALOG_CACHE
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        products = data.get("products") if isinstance(data.get("products"), list) else []
        combo_rules = data.get("combo_rules") if isinstance(data.get("combo_rules"), list) else []
        _CATALOG_CACHE = (products, combo_rules)
        return _CATALOG_CACHE
    except (json.JSONDecodeError, OSError):
        _CATALOG_CACHE = ([], [])
        return _CATALOG_CACHE


def _load_settings() -> dict[str, str]:
    from w49_core.timing import sync_anchor_from_28run

    out = sync_anchor_from_28run()
    if KNOWLEDGE.is_file():
        data = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
        tpls = data.get("templates") or {}
        if (tpls.get("warn") or {}).get("text"):
            out["warnAnnounceTemplate"] = str(tpls["warn"]["text"])
        if (tpls.get("close") or {}).get("text"):
            out["closeAnnounceTemplate"] = str(tpls["close"]["text"])
        if (tpls.get("open") or {}).get("template"):
            out["openAnnounceTemplate"] = str(tpls["open"]["template"])
        timing = data.get("timing") or {}
        if isinstance(timing, dict) and timing.get("interval_sec"):
            out["roundIntervalSec"] = str(timing["interval_sec"])
    return out


BOTS = [
    {
        "id": "bot-3",
        "status": "ACTIVE",
        "platform": "55Messenger",
        "associatedGroup": os.environ.get("EDGE_MOCK_GROUP_LEFT", "苍井空测试"),
        "adbHost": f"127.0.0.1:{os.environ.get('BOT_CLICKER_ADB_PORT', '55612')}",
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


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    n = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(n) if n > 0 else b"{}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path)
        st = _load_state()
        if path.path == "/api/bots":
            _json(self, 200, BOTS)
            return
        if path.path == "/api/settings":
            _json(self, 200, _load_settings())
            return
        if path.path == "/api/users":
            _json(self, 200, st.get("users") or [])
            return
        if path.path == "/api/products":
            products, _ = _load_catalog()
            _json(self, 200, products)
            return
        if path.path == "/api/combo-rules":
            _, combo_rules = _load_catalog()
            _json(self, 200, combo_rules)
            return
        if path.path.startswith("/api/topup-requests"):
            qs = parse_qs(path.query)
            bot_id = (qs.get("botId") or [""])[0]
            rows = [r for r in st.get("topup_requests") or [] if not bot_id or r.get("botId") == bot_id]
            _json(self, 200, rows)
            return
        if path.path.startswith("/api/withdraw-requests"):
            qs = parse_qs(path.query)
            bot_id = (qs.get("botId") or [""])[0]
            rows = [r for r in st.get("withdraw_requests") or [] if not bot_id or r.get("botId") == bot_id]
            _json(self, 200, rows)
            return
        if path.path == "/api/draw/boards":
            from w49_core.draw import fetch_28run_recent

            data = fetch_28run_recent(force=True) or {}
            _json(self, 200, {"recent_results": data.get("recent_results") or [], "mock": False})
            return
        if path.path == "/api/trade-flow":
            qs = parse_qs(path.query)
            period = int((qs.get("period") or ["0"])[0] or 0)
            bills = [b for b in st.get("bills") or [] if not period or int(b.get("period") or 0) == period]
            _json(self, 200, {"period": period, "rows": bills[-10:], "mock": False})
            return
        _json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path)
        body = _read_body(self)
        with _LOCK:
            st = _load_state()
            if path.path == "/api/users":
                users = st.setdefault("users", [])
                users.append(body)
                _save_state(st)
                _json(self, 200, body)
                return
            if path.path == "/api/topup-requests":
                req = {**body, "id": str(uuid4()), "status": "pending"}
                st.setdefault("topup_requests", []).append(req)
                _save_state(st)
                _json(self, 200, req)
                return
            if path.path == "/api/withdraw-requests":
                req = {**body, "id": str(uuid4()), "status": "pending"}
                st.setdefault("withdraw_requests", []).append(req)
                _save_state(st)
                _json(self, 200, req)
                return
            if path.path.endswith("/sent") and "/topup-requests/" in path.path:
                _json(self, 200, {"ok": True})
                return
            if path.path.endswith("/sent") and "/withdraw-requests/" in path.path:
                _json(self, 200, {"ok": True})
                return
            if path.path == "/api/logs":
                _json(self, 200, {"ok": True})
                return
        _json(self, 404, {"error": "not found"})


def main() -> int:
    srv = HTTPServer((HOST, PORT), Handler)
    print(f"edge_mock_panel http://{HOST}:{PORT} state={STATE_PATH}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
