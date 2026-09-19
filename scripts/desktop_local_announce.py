#!/usr/bin/env python3
"""本机 68助手桌面协议：公告全流程 + Panel/edge_brain 对接。"""
from __future__ import annotations

import base64
import json
import logging
import msvcrt
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [desktop] %(message)s")
log = logging.getLogger("desktop_announce")

BRAIN = os.environ.get("EDGE_BRAIN_URL", "http://127.0.0.1:8790").rstrip("/")
PANEL = os.environ.get("BOT_PANEL_URL", "http://127.0.0.1:3000").rstrip("/")
WS_URL = os.environ.get("BOT_55WS_URL", "ws://127.0.0.1:5600")
TARGET_GROUP = os.environ.get("BOT_TARGET_GROUP", "苍井空测试").strip() or "苍井空测试"
GROUP_NAME_FALLBACK = "苍井空测试"
LOOP_SEC = float(os.environ.get("DESKTOP_ANNOUNCE_LOOP_SEC", "0.25") or 0.25)
_SINGLETON_FP = None


def _acquire_singleton() -> None:
    """禁止多实例抢 WS（多开时群聊无气泡 / 重复发送）。"""
    global _SINGLETON_FP
    path = ROOT / "data" / ".desktop_announce.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 文件缺失则原子创建空文件，绝不截断既有 PID。
    if not path.exists():
        try:
            open(path, "x", encoding="utf-8").close()
        except FileExistsError:
            pass
    # 用 r+ 打开（不截断，支持 seek 覆盖）。抢到 OS 字节锁之前绝不动文件内容，
    # 避免中途失败 / 竞态留下空 lock（self-heal 判定为「announce 未写入 lock」而反复重启）。
    fp = open(path, "r+", encoding="utf-8")
    try:
        fp.seek(0)
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        try:
            old = int((fp.read() or "").strip() or "0")
        except (OSError, ValueError):
            old = 0
        fp.close()
        log.error("已有 desktop_local_announce pid=%s 在跑，本次退出（请只保留一个实例）", old or "?")
        sys.exit(0)
    # 独占锁到手后再写 PID：先覆盖再截断，任何时刻文件都至少含新 PID，杜绝空 lock 窗口。
    fp.seek(0)
    fp.write(str(os.getpid()))
    fp.truncate()
    fp.flush()
    _SINGLETON_FP = fp


def _is_target_group(d: dict) -> bool:
    gid = int(d.get("groupId") or d.get("id") or 0)
    if _group_id and gid == _group_id:
        return True
    gname = str(d.get("groupName") or d.get("name") or "")
    for needle in (TARGET_GROUP, GROUP_NAME_FALLBACK):
        if needle and needle in gname:
            return True
    return False

_warn_sent: set[int] = set()
_close_sent: set[int] = set()
_settled: set[int] = set()
_open_announced: dict[str, int] = {}
_group_id: int | None = int(os.environ["DESKTOP_GROUP_ID"]) if os.environ.get("DESKTOP_GROUP_ID") else None
_ws_lock = threading.Lock()


def _jwt_headers() -> dict[str, str]:
    from edge_brain.jwt_auth import authorization_header

    return authorization_header()


def brain_get(path: str) -> dict:
    req = urllib.request.Request(f"{BRAIN}{path}", headers=_jwt_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def brain_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BRAIN}{path}",
        data=data,
        method="POST",
        headers={**_jwt_headers(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def panel_get(path: str) -> Any:
    req = urllib.request.Request(f"{PANEL}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def panel_post(path: str, body: dict) -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{PANEL}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_settings() -> dict[str, str]:
    import bot_55chat_daemon as d

    raw = panel_get("/api/settings")
    return d.merge_settings(raw if isinstance(raw, dict) else None)


def load_bot() -> dict:
    bots = panel_get("/api/bots") or []
    for b in bots:
        if isinstance(b, dict) and str(b.get("id")) == "bot-4":
            return b
    return {"id": "bot-4", "associatedGroup": TARGET_GROUP}


def ensure_panel_user(nick: str, uid: str = "") -> list[dict]:
    users = panel_get("/api/users") or []
    if not isinstance(users, list):
        users = []
    nick = str(nick or "").strip()
    mid = str(uid or "").strip()
    for u in users:
        if not isinstance(u, dict):
            continue
        if str(u.get("username") or "") == nick or (mid and str(u.get("messengerId") or "") == mid):
            changed = False
            if mid and str(u.get("messengerId") or "") != mid:
                u["messengerId"] = mid
                changed = True
            if nick and str(u.get("username") or "") != nick:
                u["username"] = nick
                changed = True
            if changed:
                try:
                    panel_post("/api/users", u)
                except Exception:
                    pass
            return users
    code = str(10001 + len(users))
    new_u = {
        "botId": "bot-4",
        "username": nick,
        "balance": 10000.0,
        "customerCode": code,
        "messengerId": mid,
    }
    try:
        panel_post("/api/users", new_u)
    except Exception:
        users.append(new_u)
    else:
        users.append(new_u)
    return users


class Ws55:
    def __init__(self) -> None:
        import websocket  # type: ignore

        self._ws_mod = websocket
        self._ws = None
        self._ready = threading.Event()
        self._daemon: Any = None
        self._ctx_lock = threading.Lock()
        self._settings: dict[str, str] = {}
        self._bot: dict = {}

    def set_context(self, daemon: Any, settings: dict[str, str], bot: dict) -> None:
        with self._ctx_lock:
            self._daemon = daemon
            self._settings = settings
            self._bot = bot

    def start(self) -> None:
        t = threading.Thread(target=self._run, name="ws55", daemon=True)
        t.start()
        if not self._ready.wait(timeout=15):
            raise RuntimeError(f"WS 连接超时: {WS_URL}")

    def _run(self) -> None:
        global _group_id

        def on_message(_ws: object, message: str) -> None:
            global _group_id
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                return
            if msg.get("message") == "Hello":
                self._ready.set()
                try:
                    self._send({"id": "bind-groups", "type": "getGroups"})
                except Exception:
                    pass
                return
            if msg.get("type") == "getGroups" and isinstance(msg.get("data"), list):
                for g in msg["data"]:
                    gname = str(g.get("name") or "")
                    if (TARGET_GROUP in gname or GROUP_NAME_FALLBACK in gname) and not _group_id:
                        _group_id = int(g.get("id") or 0) or None
                        if _group_id:
                            log.info("getGroups 群 ID=%s name=%s", _group_id, gname)
                return
            if msg.get("operator") == "msgNew" and msg.get("data", {}).get("type") == "group":
                d = msg["data"]
                if _is_target_group(d) and _group_id is None:
                    _group_id = int(d.get("groupId") or d.get("id") or 0) or None
                    if _group_id:
                        log.info("群 ID=%s name=%s", _group_id, d.get("groupName") or d.get("name"))
                if _is_target_group(d):
                    self._on_group_message(d)

        def on_open(ws: object) -> None:
            self._ws = ws

        while True:
            try:
                self._ws_mod.WebSocketApp(
                    WS_URL,
                    on_message=on_message,
                    on_open=on_open,
                ).run_forever(ping_interval=30, ping_timeout=10)
            except Exception as ex:
                log.warning("WS 断开: %s", ex)
            self._ready.clear()
            time.sleep(3)

    def _send(self, payload: dict) -> None:
        with _ws_lock:
            if not self._ws:
                raise RuntimeError("WS 未连接")
            self._ws.send(json.dumps(payload, ensure_ascii=False))

    def send_text(self, gid: int, text: str) -> None:
        self._send({
            "id": str(uuid4()),
            "type": "sendMsg",
            "data": {
                "id": gid,
                "type": "group",
                "list": [{"type": "text", "values": {"chatType": 0, "content": text}}],
                "quoteInfo": None,
            },
        })

    def send_file(self, gid: int, path: str) -> None:
        win_path = str(Path(path).resolve()).replace("/", "\\")
        self._send({
            "id": str(uuid4()),
            "type": "sendFile",
            "data": {"file": win_path, "type": "group", "id": gid},
        })

    def _on_group_message(self, d: dict) -> None:
        if d.get("isSelf"):
            return
        with self._ctx_lock:
            daemon = self._daemon
            settings = dict(self._settings)
            bot = dict(self._bot)
        if not daemon:
            return
        content = str(d.get("content") or "").strip()
        nick = (
            d.get("sendMember", {}).get("user", {}).get("nickName")
            or d.get("user", {}).get("nickName")
            or ""
        )
        msg_type = int(d.get("msgType") or d.get("chatType") or 0)
        if not content or msg_type not in (0,):
            return
        log.info("IN cmd nick=%s content=%s", nick or "?", content[:40])
        uid = str(d.get("sendUid") or d.get("UserID") or "")
        try:
            users = ensure_panel_user(str(nick), uid)
            if uid:
                daemon.store_mid_cache(
                    "desktop-ws", str(nick), daemon.normalize_messenger_id(uid), str(bot.get("id") or "bot-4"),
                )
            products = panel_get("/api/products") or []
            combos = panel_get("/api/combo-rules") or []
            reply = daemon.handle_command(
                content, bot, users, products, combos, settings, str(nick), serial="desktop-ws",
            )
            if reply:
                gid = require_group_id()
                self.send_text(gid, reply)
                log.info("OUT cmd %s -> %s", content[:20], reply.split("\n")[0][:60])
        except Exception as ex:
            log.warning("cmd %s: %s", content[:30], ex)


def require_group_id() -> int:
    global _group_id
    if _group_id:
        return _group_id
    if os.environ.get("DESKTOP_GROUP_ID"):
        _group_id = int(os.environ["DESKTOP_GROUP_ID"])
        return _group_id
    raise RuntimeError(f"未知群 ID — 请在「{TARGET_GROUP}」发一条消息，或设 DESKTOP_GROUP_ID")


def try_open(d: object, ws: Ws55, bot: dict, settings: dict[str, str], *, force_rid: int | None = None) -> None:
    group = (bot.get("associatedGroup") or TARGET_GROUP).strip()
    rid, interval, remaining = d.active_round_timing(settings)
    if force_rid:
        rid = force_rid
    elapsed = interval - remaining
    if elapsed < d.OPEN_ANNOUNCE_AFTER_SEC and force_rid is None:
        return
    if _open_announced.get(group, 0) >= rid:
        return
    pending = d.pending_settle_round_id(rid)
    if pending and pending not in _settled:
        return
    tpl = (settings.get("openAnnounceTemplate") or d.DEFAULT_ROUND_OPEN_ANNOUNCE).strip()
    period_start = d.beijing_now() - timedelta(seconds=elapsed)
    open_at = period_start + timedelta(seconds=d.OPEN_ANNOUNCE_AFTER_SEC)
    text = d.apply_template(tpl, round_id=rid, round_time=d.format_group_display_time(open_at))
    gid = require_group_id()
    ws.send_text(gid, text)
    _open_announced[group] = rid
    log.info("OUT open rid=%s", rid)


def try_warn(d: object, ws: Ws55, bot: dict, settings: dict[str, str]) -> None:
    group = (bot.get("associatedGroup") or TARGET_GROUP).strip()
    rid, _, remaining = d.active_round_timing(settings)
    if remaining > d.WARN_ANNOUNCE_BEFORE_SEC or remaining <= d.CLOSE_ANNOUNCE_BEFORE_SEC:
        return
    if rid in _warn_sent:
        return
    if _open_announced.get(group, 0) != rid:
        return
    tpl = d.sanitize_announce_text((settings.get("warnAnnounceTemplate") or d.DEFAULT_WARN_ANNOUNCE).strip())
    text = d.apply_template(tpl, round_id=rid, seconds_left=int(remaining))
    ws.send_text(require_group_id(), text)
    _warn_sent.add(rid)
    log.info("OUT warn rid=%s rem=%.0fs", rid, remaining)


def try_close(d: object, ws: Ws55, bot: dict, settings: dict[str, str]) -> None:
    group = (bot.get("associatedGroup") or TARGET_GROUP).strip()
    rid, _, remaining = d.active_round_timing(settings)
    if remaining > d.CLOSE_ANNOUNCE_BEFORE_SEC or remaining <= 0:
        return
    if rid in _close_sent:
        return
    if rid not in _warn_sent:
        return
    if _open_announced.get(group, 0) != rid:
        return
    tpl = (settings.get("closeAnnounceTemplate") or d.DEFAULT_CLOSE_ANNOUNCE).strip()
    text = d.apply_template(tpl, round_id=rid)
    ws.send_text(require_group_id(), text)
    _close_sent.add(rid)
    log.info("OUT close rid=%s rem=%.0fs", rid, remaining)


def try_settle(d: object, ws: Ws55, settings: dict[str, str], *, recover: bool = False) -> None:
    rid, _, _ = d.active_round_timing(settings)
    data = d.fetch_28run_recent()
    pending = d.pending_settle_round_id(rid, data)
    if not pending or pending in _settled:
        return
    if not recover and pending not in _close_sent:
        return
    try:
        bundle = brain_get(f"/settle-bundle?period={pending}")
    except urllib.error.HTTPError as ex:
        log.debug("settle-bundle skip rid=%s: %s", pending, ex)
        return
    images = bundle.get("images") or []
    if not images:
        return
    gid = require_group_id()
    td = Path(tempfile.mkdtemp(prefix="desktop_settle_"))
    ok = True
    for img in images:
        kind = str(img.get("kind") or "img")
        raw = base64.standard_b64decode(img.get("b64") or "")
        p = td / f"{pending}_{kind}.png"
        p.write_bytes(raw)
        try:
            ws.send_file(gid, str(p))
            time.sleep(0.35)
        except Exception as ex:
            log.warning("sendFile %s: %s", p.name, ex)
            ok = False
    brain_post("/settle-done", {"period": pending, "images_ok": ok, "device": "desktop-local"})
    if ok:
        _settled.add(pending)
        log.info("OUT settle 3img rid=%s", pending)


def bootstrap_recover(d: object, ws: Ws55, settings: dict[str, str]) -> None:
    """冷启动：上期待结算且 28.run 已开奖 → 跳过封盘门闸直接三图+新一局。"""
    rid, _, _ = d.active_round_timing(settings)
    pending = d.pending_settle_round_id(rid)
    if not pending or pending in _settled:
        return
    if not d.find_draw_for_round(pending):
        return
    log.info("冷启动恢复：先结算 rid=%s 再开 rid=%s", pending, rid)
    _close_sent.add(pending)
    try_settle(d, ws, settings, recover=True)


def try_open_after_settle(d: object, ws: Ws55, bot: dict, settings: dict[str, str]) -> None:
    try:
        job = brain_get("/edge/open-job")
    except Exception:
        return
    gates = job.get("gates") or {}
    if not gates.get("open"):
        return
    open_rid = int(gates.get("open_rid") or 0)
    group = (bot.get("associatedGroup") or TARGET_GROUP).strip()
    if open_rid <= 0 or _open_announced.get(group, 0) >= open_rid:
        return
    text = str(job.get("open_text") or "").strip()
    if not text:
        try_open(d, ws, bot, settings, force_rid=open_rid)
        return
    ws.send_text(require_group_id(), text)
    _open_announced[group] = open_rid
    log.info("OUT open-after-settle rid=%s", open_rid)


def main() -> int:
    _acquire_singleton()
    os.environ.setdefault("EDGE_BRAIN_JWT_SECRET", "w49-local-desktop-test")
    os.environ.setdefault("BOT_ANNOUNCE_LOCKED", "1")
    os.environ.setdefault("BOT_API_BASE", PANEL)
    os.environ.setdefault("BOT_PANEL_URL", PANEL)
    import bot_55chat_daemon as d  # noqa: WPS433

    d.API_BASE = PANEL

    try:
        import websocket  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "websocket-client"])
        import websocket  # noqa: F401

    # JWT for brain
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "edge_issue_jwt.py")],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(ROOT),
    )
    for line in (r.stdout or "").splitlines():
        if line.startswith("EDGE_BRAIN_JWT="):
            os.environ["EDGE_BRAIN_JWT"] = line.split("=", 1)[1].strip()

    ws = Ws55()
    ws.start()
    log.info("WS OK %s panel=%s brain=%s group=%s", WS_URL, PANEL, BRAIN, TARGET_GROUP)

    settings = load_settings()
    bot = load_bot()
    ws.set_context(d, settings, bot)
    if os.environ.get("DESKTOP_STARTUP_PING", "").lower() in ("1", "true", "yes"):
        try:
            gid = require_group_id()
            ws.send_text(gid, "[bot] 本地桌面栈在线 — 请发 扣1 或 1 测试回复")
            log.info("OUT ping gid=%s", gid)
        except Exception as ex:
            log.warning("startup ping: %s", ex)
    rid, _, rem = d.active_round_timing(settings)
    group = (bot.get("associatedGroup") or TARGET_GROUP).strip()
    if not d.in_maintenance_window():
        try:
            bootstrap_recover(d, ws, settings)
            rid, _, _ = d.active_round_timing(settings)
            if _open_announced.get(group, 0) < rid:
                try_open(d, ws, bot, settings, force_rid=rid)
        except Exception as ex:
            log.warning("bootstrap: %s", ex)

    settings_ts = 0.0
    wait_log = 0.0
    while True:
        try:
            if _group_id is None:
                if time.time() - wait_log > 30:
                    log.info("等待群 ID — 请在「%s」发任意一条消息", TARGET_GROUP)
                    wait_log = time.time()
                time.sleep(LOOP_SEC)
                continue
            if time.time() - settings_ts > 30:
                settings = load_settings()
                bot = load_bot()
                ws.set_context(d, settings, bot)
                settings_ts = time.time()
            if d.in_maintenance_window():
                time.sleep(LOOP_SEC)
                continue
            try_open(d, ws, bot, settings)
            try_warn(d, ws, bot, settings)
            try_close(d, ws, bot, settings)
            try_settle(d, ws, settings)
            try_open_after_settle(d, ws, bot, settings)
        except Exception as ex:
            log.warning("loop: %s", ex)
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
