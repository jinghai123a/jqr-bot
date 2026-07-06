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
BUNDLE = ROOT / "config" / "55m-knowledge" / "panel-bundle.json"
SPEC = ROOT / "config" / "55m-knowledge" / "panel-ui-spec.json"
COMMANDS = ROOT / "config" / "55m-knowledge" / "chat-commands.json"
USER_REPLIES = ROOT / "config" / "55m-knowledge" / "user-commands-replies.json"
ANNOUNCE_SEQ = ROOT / "config" / "55m-knowledge" / "announce-sequence.json"
GAME_RULES = ROOT / "config" / "55m-knowledge" / "game-rules.json"
FINANCE = ROOT / "config" / "55m-knowledge" / "finance-algorithms.json"
_LOCK = threading.Lock()
_CATALOG_CACHE: tuple[list[Any], list[Any]] | None = None


def _default_state() -> dict[str, Any]:
    bundle = _load_bundle()
    users = (bundle or {}).get("users") if isinstance((bundle or {}).get("users"), list) else []
    fq = (bundle or {}).get("finance_queues") or {}
    return {
        "users": users or [
            {
                "botId": "bot-4",
                "username": "测试用户",
                "balance": 10000.0,
                "customerCode": "10001",
                "messengerId": "",
            }
        ],
        "topup_requests": fq.get("topup_requests") or [],
        "withdraw_requests": fq.get("withdraw_requests") or [],
        "bills": fq.get("bills") or [],
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


def _load_bundle() -> dict[str, Any] | None:
    if not BUNDLE.is_file():
        return None
    try:
        data = json.loads(BUNDLE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_catalog() -> tuple[list[Any], list[Any]]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    bundle = _load_bundle()
    if bundle and isinstance(bundle.get("products"), list):
        products = bundle["products"]
        combo_rules = bundle.get("combo_rules") if isinstance(bundle.get("combo_rules"), list) else []
        _CATALOG_CACHE = (products, combo_rules)
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

    bundle = _load_bundle()
    if bundle and isinstance(bundle.get("settings"), dict):
        out = {str(k): str(v) for k, v in bundle["settings"].items()}
        anchor = sync_anchor_from_28run()
        for k in ("roundAnchorPeriod", "roundAnchorBeijing", "draw28_latest_rid", "draw28_next_rid"):
            if k in anchor:
                out[k] = str(anchor[k])
        return out
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


def _get_bots() -> list[dict[str, Any]]:
    bundle = _load_bundle()
    if bundle and isinstance(bundle.get("bots"), list):
        return bundle["bots"]
    return [
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


def _html(handler: BaseHTTPRequestHandler, code: int, body: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _load_announce() -> dict[str, Any]:
    if not KNOWLEDGE.is_file():
        return {}
    try:
        return json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_commands() -> dict[str, Any]:
    if not COMMANDS.is_file():
        return {}
    try:
        return json.loads(COMMANDS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _dashboard_html() -> str:
    st = _load_state()
    products, combo_rules = _load_catalog()
    ann = _load_announce()
    cmds = _load_commands()
    tpls = ann.get("templates") or {}
    warn = str((tpls.get("warn") or {}).get("text") or "")
    close = str((tpls.get("close") or {}).get("text") or "")
    open_tpl = str((tpls.get("open") or {}).get("template") or "")
    users = st.get("users") or []
    finance = cmds.get("finance") or {}
    bet = cmds.get("bet_rules") or {}
    rows_users = "".join(
        f"<tr><td>{_esc(str(u.get('username','')))}</td>"
        f"<td>{_esc(str(u.get('customerCode','')))}</td>"
        f"<td>{_esc(str(u.get('messengerId','')))}</td>"
        f"<td>{u.get('balance','')}</td></tr>"
        for u in users
    )
    rows_prod = "".join(
        f"<tr><td>{_esc(str(p.get('code','')))}</td>"
        f"<td>{_esc(str(p.get('name','')))}</td>"
        f"<td>{_esc(str(p.get('kind','')))}</td></tr>"
        for p in products
    )
    rows_fin = "".join(
        f"<tr><td><code>{_esc(k)}</code></td><td>{_esc(str(v))}</td></tr>"
        for k, v in finance.items()
    )
    rows_bet = "".join(
        f"<tr><td><code>{_esc(str(f.get('pattern','')))}</code></td>"
        f"<td>{_esc(str(f.get('desc','')))}</td></tr>"
        for f in (bet.get("formats") or [])
    )
    api_links = "".join(
        f'<li><a href="{p}">{p}</a></li>'
        for p in (
            "/api/bots",
            "/api/settings",
            "/api/users",
            "/api/products",
            "/api/combo-rules",
            "/api/spec",
        )
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>55M 控制面板 · 核对栏（本地 mock）</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#0f1117;color:#e6edf3}}
h1,h2{{color:#58a6ff}} section{{margin:24px 0;padding:16px;background:#161b22;border-radius:8px}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #30363d;padding:8px;text-align:left}}
pre{{white-space:pre-wrap;background:#0d1117;padding:12px;border-radius:6px;font-size:13px;max-height:320px;overflow:auto}}
code{{color:#79c0ff}} a{{color:#58a6ff}} .tag{{display:inline-block;background:#238636;padding:2px 8px;border-radius:4px;font-size:12px}}
</style></head><body>
<h1>55M 控制面板 <span class="tag">本地 mock · 核对栏</span></h1>
<p>生产 APS <code>195.114.193.136:3000</code> 本机不可达时，以此页 + JSON API 为准。规格源：<code>docs/用户使用.md</code></p>
<section><h2>① 机器人实例</h2><table><tr><th>ID</th><th>角色</th><th>群</th><th>ADB</th></tr>
<tr><td>bot-3</td><td>CLICKER 左机</td><td>苍井空测试</td><td>发图/ADD</td></tr>
<tr><td>bot-4</td><td>LISTENER 右机</td><td>苍井空测试</td><td>读屏/文字 OUT</td></tr></table></section>
<section><h2>② 客户核对栏（users）</h2><table><tr><th>昵称</th><th>编号</th><th>messengerId</th><th>余额</th></tr>
{rows_users or '<tr><td colspan="4">（空）</td></tr>'}</table></section>
<section><h2>③ 玩法 products（{len(products)}）</h2><table><tr><th>道</th><th>名称</th><th>类型</th></tr>{rows_prod}</table>
<p>combo-rules：{len(combo_rules)} 条 · <a href="/api/combo-rules">/api/combo-rules</a></p></section>
<section><h2>④ 群内指令</h2><table><tr><th>指令</th><th>说明</th></tr>{rows_fin}</table>
<table style="margin-top:12px"><tr><th>下注格式</th><th>说明</th></tr>{rows_bet}</table>
<p>金额后缀只认「各」；封盘后：<code>{_esc(str(bet.get('closed_reply','')))}</code></p></section>
<section><h2>⑤ 公告正文（发群原文）</h2>
<h3>warn · 封盘前70s窗</h3><pre>{_esc(warn)}</pre>
<h3>close · 封盘前15s窗</h3><pre>{_esc(close)}</pre>
<h3>open · 三图后新一局</h3><pre>{_esc(open_tpl)}</pre></section>
<section><h2>⑥ API</h2><ul>{api_links}</ul></section>
</body></html>"""


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
            _json(self, 200, _get_bots())
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
        if path.path == "/api/spec":
            if SPEC.is_file():
                _json(self, 200, json.loads(SPEC.read_text(encoding="utf-8")))
            else:
                _json(self, 404, {"error": "panel-ui-spec.json missing"})
            return
        if path.path == "/api/bundle":
            bundle = _load_bundle()
            if bundle:
                _json(self, 200, bundle)
            else:
                _json(self, 404, {"error": "panel-bundle.json missing"})
            return
        for spec_path, spec_file in (
            ("/api/knowledge/commands", USER_REPLIES),
            ("/api/knowledge/announce", ANNOUNCE_SEQ),
            ("/api/knowledge/rules", GAME_RULES),
            ("/api/knowledge/finance", FINANCE),
        ):
            if path.path == spec_path and spec_file.is_file():
                _json(self, 200, json.loads(spec_file.read_text(encoding="utf-8")))
                return
        if path.path in ("/", "/panel", "/dashboard"):
            _html(self, 200, _dashboard_html())
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
