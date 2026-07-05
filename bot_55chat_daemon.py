#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""55Chat 真实 ADB 守护进程 — 读屏 + API + 物理回复"""
from __future__ import annotations

import base64
import heapq
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import html
try:
    import fcntl
except ModuleNotFoundError:  # Windows 本地 Gate 无 fcntl
    import types as _types

    _fcntl = _types.ModuleType("fcntl")
    _fcntl.LOCK_EX = 2
    _fcntl.LOCK_NB = 4

    def _flock(_fd: int, _op: int) -> None:
        return None

    _fcntl.flock = _flock  # type: ignore[attr-defined]
    fcntl = _fcntl  # type: ignore[assignment]
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import queue
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
from collections import Counter, deque, defaultdict
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any, Callable

from bot_backend import BackendApiTransport, fetch_user_bills as _fetch_user_bills_impl, record_bill as _record_bill_impl
import bot_probe

try:
    from board_capture import (
        render_mark6_board_png,
        render_pc28_board_png,
        render_trade_flow_png,
    )
    _HAS_BOARD_CAPTURE = True
except ImportError:
    _HAS_BOARD_CAPTURE = False

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("55chat")

FAST = os.environ.get("BOT_FAST_MODE", "1").lower() in ("1", "true", "yes")
ORCHESTRATOR = os.environ.get("BOT_ORCHESTRATOR", "1").lower() in ("1", "true", "yes")
BOT_LISTENER_ID = os.environ.get("BOT_LISTENER_ID", "bot-4").strip()
CLICKER_BOT_IDS = {
    x.strip()
    for x in os.environ.get("BOT_CLICKER_IDS", "bot-3").split(",")
    if x.strip()
}
CLICKER_OPTIONAL = os.environ.get("BOT_CLICKER_OPTIONAL", "0").lower() in ("1", "true", "yes")
# 左机仅负责 UI 发图（+→图片→勾选→发送）
CLICKER_SEND_IMAGES = os.environ.get("BOT_CLICKER_SEND_IMAGES", "0").lower() in ("1", "true", "yes")
# 左机 CLICKER 负责 warn/close/open 文字公告；右机 LISTENER 仅热路径用户回复
CLICKER_SEND_ANNOUNCE = os.environ.get("BOT_CLICKER_SEND_ANNOUNCE", "1").lower() in ("1", "true", "yes")
# 左机 CLICKER 进程内闭环：28.run → 截图 → UI 发图 → 三图后新一局（同机公告线程）
CLICKER_SETTLE_ENABLED = os.environ.get("BOT_CLICKER_SETTLE", "0").lower() in ("1", "true", "yes")
# 左机驻留群聊：慢任务/发图全程在 55M 内完成，禁止系统 Back 退出 App
CLICKER_STAY_IN_CHAT = os.environ.get("BOT_CLICKER_STAY_IN_CHAT", "1").lower() in ("1", "true", "yes")
CLICKER_STAY_SEC = max(15.0, float(os.environ.get("BOT_CLICKER_STAY_SEC", "30") or 30))
CLICKER_FAST = os.environ.get("BOT_CLICKER_FAST", "1").lower() in ("1", "true", "yes")
# DEPLOY LOCK: 左机 CLICKER | 右机 LISTENER（端口见 env，云机重启后可能变）
_LISTENER_ADB_PORT = os.environ.get("BOT_LISTENER_ADB_PORT", "60478").strip()
_CLICKER_ADB_PORT = os.environ.get("BOT_CLICKER_ADB_PORT", "52840").strip()
DEPLOY_ADB_ROLES = {
    "bot-3": (_CLICKER_ADB_PORT, "CLICKER"),
    "bot-4": (_LISTENER_ADB_PORT, "LISTENER"),
}
_DEPLOY_SERIAL_ROLE: dict[str, str] = {}
_CLICKER_DEPLOY: dict[str, object] = {}  # serial, bot — 左机 UI 发图路由
SKIP_BOT_IDS = {
    x.strip()
    for x in os.environ.get("BOT_SKIP_BOT_IDS", "").split(",")
    if x.strip()
}
UI_CACHE_TTL = max(0.03, float(os.environ.get("BOT_UI_CACHE_MS", "120") or 120) / 1000.0)
UI_ENGINE = os.environ.get("BOT_UI_ENGINE", "auto").lower()  # auto | u2 | adb
LISTENER_UI_ENGINE = os.environ.get("BOT_LISTENER_UI_ENGINE", "adb").lower()  # 右机强制 adb dump
TICK_MIN_SEC = max(0.04, float(os.environ.get("BOT_TICK_MIN_SEC", "0.05") or 0.05))
LISTENER_TICK_SEC = max(0.02, float(os.environ.get("BOT_LISTENER_TICK_SEC", "0.03") or 0.03))
LISTENER_IDLE_TICK_SEC = max(
    LISTENER_TICK_SEC,
    float(os.environ.get("BOT_LISTENER_IDLE_TICK_SEC", "0.03") or 0.03),
)
# 空闲时 ROI 无变化也须周期性完整扫屏，否则漏掉「1」等短消息
LISTENER_FORCE_SCAN_SEC = max(
    0.8,
    float(os.environ.get("BOT_LISTENER_FORCE_SCAN_SEC", "2.0") or 2.0),
)
LISTENER_CMDS_PER_TICK = max(1, int(os.environ.get("BOT_LISTENER_CMDS_PER_TICK", "5") or 5))
CLICKER_IDLE_SEC = max(0.05, float(os.environ.get("BOT_CLICKER_IDLE_SEC", "0.08") or 0.08))
# 单机部署身份：LISTENER | CLICKER | HYBRID（双机编排时仍按 bot-id 分角色）
BOT_ROLE = os.environ.get("BOT_ROLE", "").strip().upper()
GATEWAY_ENABLED = os.environ.get("BOT_GATEWAY_ENABLED", "1").lower() in ("1", "true", "yes")
GATEWAY_BASE_URL = os.environ.get("BOT_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")
GATEWAY_TIMEOUT_SEC = max(1.0, float(os.environ.get("BOT_GATEWAY_TIMEOUT_SEC", "3") or 3))
LOG_WORKER_THREADS = max(1, int(os.environ.get("BOT_LOG_WORKERS", "4") or 4))
# 公告/回复并发：有界线程池上限（后续 Hook / 剪贴板快发任务统一入口）
OUTBOUND_POOL_MAX = max(1, min(10, int(os.environ.get("BOT_OUTBOUND_POOL_MAX", "10") or 10)))
CONTEXT_REFRESH_SEC = max(1.0, float(os.environ.get("BOT_CONTEXT_REFRESH_SEC", "2") or 2))
SEND_DEBOUNCE_SEC = max(0.02, float(os.environ.get("BOT_SEND_DEBOUNCE_SEC", "0.03") or 0.03))
POST_PANEL_LOG = os.environ.get("BOT_POST_PANEL_LOG", "0" if FAST else "1").lower() in ("1", "true", "yes")
# 全自动昵称：用历史别名识别到用户后，自动把面板群昵称更新为当前群昵称（无需发「绑定」）
AUTO_NICK_SYNC = os.environ.get("BOT_AUTO_NICK_SYNC", "1").lower() in ("1", "true", "yes")
AUTO_FRIEND_ACCEPT = os.environ.get("BOT_AUTO_FRIEND_ACCEPT", "0").lower() in ("1", "true", "yes")
# 大工程 Phase1/2：右机 ROI 帧差 + ADB Keyboard 快发（不改业务逻辑）
FAST_DETECT_ENABLED = os.environ.get("BOT_FAST_DETECT", "1").lower() in ("1", "true", "yes")
LISTENER_FAST_SEND = os.environ.get("BOT_LISTENER_FAST_SEND", "1").lower() in ("1", "true", "yes")
# 填字+点发送后立即返回，不做 u2 全量 dump 验证（热路径亚秒级）
LISTENER_TRUST_SEND = os.environ.get("BOT_LISTENER_TRUST_SEND", "1").lower() in ("1", "true", "yes")
# 用户回复：填字后用 Enter/IME 发送，避免坐标 tap inbar（~200ms+ 且触发 u2 缓存失效）
LISTENER_SEND_ENTER_FIRST = os.environ.get("BOT_LISTENER_SEND_ENTER_FIRST", "1").lower() in (
    "1", "true", "yes",
)
# 右机纯管道：大脑给文本 → b64+Enter 即发，零等待、零 u2 验草稿
LISTENER_PURE_PIPE = os.environ.get("BOT_LISTENER_PURE_PIPE", "1").lower() in ("1", "true", "yes")
# 出站文本打断 IM 自动链接（28.run 等），避免误触跳转开奖页
LISTENER_BREAK_IM_LINKS = os.environ.get("BOT_LISTENER_BREAK_IM_LINKS", "1").lower() in (
    "1", "true", "yes",
)
# 右机发送键钉死坐标（itel 等不跑 u2 扫描，避免点到加号/相机）
LISTENER_PINNED_SEND = os.environ.get("BOT_LISTENER_PINNED_SEND", "1").lower() in ("1", "true", "yes")
LISTENER_SEND_X = int(os.environ.get("BOT_LISTENER_SEND_X", "674") or 674)
LISTENER_SEND_Y = int(os.environ.get("BOT_LISTENER_SEND_Y", "1234") or 1234)
# 右机永久只允许钉死「发送」键一次点击（禁止输入框/+ /表情/麦克风/键盘其它键）
LISTENER_STAY_SANITIZE = os.environ.get("BOT_LISTENER_STAY_SANITIZE", "0").lower() in (
    "1", "true", "yes",
)
LISTENER_COMPOSER_CLEAN_DELAY_SEC = max(
    60.0,
    min(120.0, float(os.environ.get("BOT_LISTENER_COMPOSER_CLEAN_DELAY_SEC", "90") or 90)),
)
_COMPOSER_CLEAN_TIMERS: dict[str, threading.Timer] = {}
_COMPOSER_CLEAN_LOCK = threading.Lock()
LISTENER_TICK_HIDE_KB = os.environ.get("BOT_LISTENER_TICK_HIDE_KB", "0").lower() in (
    "1", "true", "yes",
)
ADB_HEAL_DURING_SEND = os.environ.get("BOT_ADB_HEAL_DURING_SEND", "0").lower() in (
    "1", "true", "yes",
)
LISTENER_SEND_TAP_ONLY = os.environ.get("BOT_LISTENER_SEND_TAP_ONLY", "1").lower() in (
    "1", "true", "yes",
)
LISTENER_SEND_TAP_TOL = max(20, int(os.environ.get("BOT_LISTENER_SEND_TOL", "42") or 42))
# 右机禁止 Tab/群名/左上角等导航点击
LISTENER_ZERO_NAV = os.environ.get("BOT_LISTENER_ZERO_NAV", "1").lower() in ("1", "true", "yes")
# 右机读屏/空闲时强制收起键盘，避免 Gboard 遮挡气泡导致认不到指令
LISTENER_HIDE_KEYBOARD = os.environ.get("BOT_LISTENER_HIDE_KEYBOARD", "0").lower() in (
    "1", "true", "yes",
)
# 右机 b64 后：灌字完成即点钉死发送键，不做多轮 dump 等箭头
LISTENER_BLUE_SEND_POLLS = max(
    1, min(3, int(os.environ.get("BOT_LISTENER_BLUE_SEND_POLLS", "1") or 1)),
)
LISTENER_SEND_FIRE = os.environ.get("BOT_LISTENER_SEND_FIRE", "1").lower() in (
    "1", "true", "yes",
)
LISTENER_ANNOUNCE_VERIFY_MAX_MS = max(
    3000.0,
    float(os.environ.get("BOT_LISTENER_ANNOUNCE_VERIFY_MAX_MS", "35000") or 35000),
)
# 读屏资源 1：每 serial 单线程 dump，按 channel 优先级分发（1.1 listener / 1.2 announce …）
UI_COLLECTOR_ENABLED = os.environ.get("BOT_UI_COLLECTOR", "1").lower() in ("1", "true", "yes")
UI_COLLECTOR_TIMEOUT = max(3.0, float(os.environ.get("BOT_UI_COLLECTOR_TIMEOUT", "25") or 25))
UI_CHANNEL_PRIO: dict[str, int] = {
    "sender": 1,
    "listener": 2,
    "clicker": 3,
    "clicker-img": 3,
    "refresh": 5,
    "default": 5,
    "announce": 6,
    "settle": 6,
    "stay": 8,
}
LISTENER_SEND_MODE = os.environ.get("BOT_LISTENER_SEND_MODE", "auto").lower()  # auto|adb_b64|u2
ROI_DIFF_THRESHOLD = float(os.environ.get("BOT_ROI_DIFF_THRESHOLD", "0.015") or 0.015)
ROI_CACHE_SEC = max(0.04, float(os.environ.get("BOT_ROI_CACHE_MS", "80") or 80) / 1000.0)
IME_READY_SEC = max(10.0, float(os.environ.get("BOT_IME_READY_SEC", "30") or 30))
PROBE_ENABLED = os.environ.get("BOT_PROBE_ENABLED", "0").lower() in ("1", "true", "yes")
PROBE_PORT = int(os.environ.get("BOT_PROBE_PORT", "3910") or 3910)
TRIME_PKG = "com.osfans.trime"
TRIME_APK_URL = os.environ.get(
    "BOT_TRIME_APK_URL",
    "https://github.com/osfans/trime/releases/download/v3.2.11/trime-3.2.11-arm64-v8a-release.apk",
)
_PROBE_DEDUP: dict[str, float] = {}
_COMMAND_CLAIM: dict[str, float] = {}
_OUTBOUND_TEXT_DEDUP: dict[str, float] = {}
PROBE_CMD_DEDUP_SEC = max(1.0, float(os.environ.get("BOT_PROBE_CMD_DEDUP_SEC", "5") or 5))
OUTBOUND_DEDUP_SEC = max(2.0, float(os.environ.get("BOT_OUTBOUND_DEDUP_SEC", "8") or 8))

# 左机发图/加好友：W49 钉死坐标（config/pinned-coords.json），禁止 u2 乱扫
IMG_PINNED = os.environ.get("BOT_IMG_PINNED", "1").lower() in ("1", "true", "yes")
IMG_LOCKED = os.environ.get("BOT_IMG_LOCKED", "1").lower() in ("1", "true", "yes")
CLICK_VERIFY = os.environ.get("BOT_CLICK_VERIFY", "1").lower() in ("1", "true", "yes")
# W49：55M 自定义 UI 导致 uiautomator 验证不可靠，信任钉死坐标点击，跳过验证
IMG_TRUST_CLICK = os.environ.get("BOT_IMG_TRUST_CLICK", "1").lower() in ("1", "true", "yes")
IMG_UPLOAD_WAIT_SEC = max(5.0, float(os.environ.get("BOT_IMG_UPLOAD_WAIT_SEC", "10") or 10))
IMG_UPLOAD_POLL_SEC = max(0.25, float(os.environ.get("BOT_IMG_UPLOAD_POLL_SEC", "0.35") or 0.35))
IMG_UPLOAD_MIN_SETTLE_SEC = max(1.5, float(os.environ.get("BOT_IMG_UPLOAD_MIN_SETTLE_SEC", "2.5") or 2.5))
IMG_UPLOAD_GALLERY_FAST = os.environ.get("BOT_IMG_UPLOAD_GALLERY_FAST", "1").lower() in (
    "1",
    "true",
    "yes",
)
IMG_FAST = os.environ.get("BOT_IMG_FAST", "1").lower() in ("1", "true", "yes")
CLICK_VERIFY_TRIES = max(1, int(os.environ.get("BOT_CLICK_VERIFY_TRIES", "3") or 3))
# W49 截图：点 + 后附件栏应出现的锚点（至少命中「图片」）
ATTACH_MENU_MARKERS = ("图片", "拍摄", "名片", "文件", "红包", "群聊转账")
CLICKER_TAP_MS = max(40, int(os.environ.get("BOT_CLICKER_TAP_MS", "80") or 80))
# 左机发图流程内仅允许 purpose=clicker-pinned-* 的钉死坐标 tap（禁止聊天区/u2 乱点）
CLICKER_IMG_TAP_ONLY = os.environ.get("BOT_CLICKER_IMG_TAP_ONLY", "1").lower() in ("1", "true", "yes")
CLICKER_IMG_TAP_TOL = max(24, int(os.environ.get("BOT_CLICKER_IMG_TAP_TOL", "52") or 52))
_CLICKER_IMG_FLOW_SERIALS: set[str] = set()
_CLICKER_ATTACH_IME_RESTORE: dict[str, str] = {}
_CLICKER_ATTACH_IME_DISABLED: dict[str, list[str]] = {}


def _pinned_coords_path() -> str:
    root = os.environ.get("BOT_ROOT") or os.path.dirname(os.path.abspath(__file__))
    override = os.environ.get("BOT_PINNED_COORDS_PATH", "").strip()
    if override:
        return override
    return os.path.join(root, "config", "pinned-coords.json")


def _load_pinned_coords() -> dict:
    path = _pinned_coords_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            log.info("已加载钉死坐标 %s", path)
            return data
    except FileNotFoundError:
        log.warning("钉死坐标文件不存在: %s", path)
    except Exception as ex:
        log.warning("读取钉死坐标失败: %s", ex)
    return {}


_PINNED_COORDS: dict = _load_pinned_coords()


def pinned_xy(role: str, key: str, index: int | None = None) -> tuple[int, int] | None:
    """role: clicker|listener；key 见 config/pinned-coords.json。"""
    block = _PINNED_COORDS.get(role) or {}
    val = block.get(key)
    if index is not None and isinstance(val, list) and val and isinstance(val[0], list):
        if 0 <= index < len(val):
            val = val[index]
        else:
            return None
    if isinstance(val, list) and len(val) >= 2:
        return int(val[0]), int(val[1])
    return None


def pinned_attach_image_xy() -> tuple[int, int]:
    """左机附件栏「图片」：IMG_LOCKED 时优先 attach_image_bottom (90,1110)。"""
    if IMG_LOCKED or IMG_PINNED:
        pt = pinned_xy("clicker", "attach_image_bottom") or pinned_xy("clicker", "attach_image")
    else:
        pt = pinned_xy("clicker", "attach_image") or pinned_xy("clicker", "attach_image_bottom")
    return pt or (90, 1110)


def clicker_w(fast_sec: float = 0.12, slow_sec: float = 0.35) -> None:
    """左机点击间隔（亚秒）。"""
    w(CLICKER_TAP_MS / 1000.0 if CLICKER_FAST else fast_sec, slow_sec)


def _orchestrator_peer_bot_ids() -> set[str]:
    """双机编排：Listener + Clicker 共享同一群用户池。"""
    if not ORCHESTRATOR:
        return set()
    peers = {BOT_LISTENER_ID}
    peers.update(CLICKER_BOT_IDS)
    peers.discard("")
    return peers


def user_in_bot_scope(user: dict, bot_id: str) -> bool:
    ub = str(user.get("botId") or "")
    if not ub:
        return False
    if ub == bot_id:
        return True
    peers = _orchestrator_peer_bot_ids()
    return bool(peers) and ub in peers and bot_id in peers
LISTENER_STAY_IN_GROUP = os.environ.get("BOT_LISTENER_STAY_IN_GROUP", "1").lower() in ("1", "true", "yes")
MANUAL_IN_GROUP = os.environ.get("BOT_MANUAL_IN_GROUP", "0").lower() in ("1", "true", "yes")
LISTENER_STAY_RECOVER_SEC = max(3, int(os.environ.get("BOT_LISTENER_STAY_RECOVER_SEC", "5") or 5))
LISTENER_CHAT_SCROLL_SEC = max(0.8, float(os.environ.get("BOT_LISTENER_CHAT_SCROLL_SEC", "2") or 2))
_LISTENER_LAST_CHAT_SCROLL: dict[str, float] = {}
_LISTENER_LAST_RECOVER: dict[str, float] = {}
_MESSENGER_PKG_CACHE: dict[str, str] = {}
# 上次成功的发送策略 (serial -> (name, x, y))
_SEND_CACHE: dict[str, tuple[str, int, int]] = {}
_LAST_FRIEND_CHECK: dict[str, float] = {}
_GROUP_ACTIVITY_CACHE: dict[str, tuple[float, bool]] = {}
GROUP_ACTIVITY_CACHE_SEC = ROI_CACHE_SEC
_ROI_GRAY_PREV: dict[str, Any] = {}
_IME_READY_TS: dict[str, float] = {}
_U2_DEVICES: dict[str, Any] = {}
_UI_CACHE: dict[str, tuple[float, ET.Element | None]] = {}
_STEP_VERIFY_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}
STEP_VERIFY_CACHE_MS = max(
    0.05, float(os.environ.get("BOT_STEP_VERIFY_CACHE_MS", "220") or 220) / 1000.0
)
_UI_SERIAL_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)
_SNAP_CACHE: dict[str, tuple[float, Any]] = {}
_MID_CACHE: dict[str, tuple[str, float]] = {}
MID_CACHE_TTL = max(60, int(os.environ.get("BOT_MID_CACHE_SEC", "900") or 900))
MID_CACHE_FILE = os.environ.get(
    "BOT_MID_CACHE_FILE", "/home/bot/55chat-bot/data/mid_cache.json"
)
BOT_LOCK_FILE = os.environ.get(
    "BOT_LOCK_FILE", "/home/bot/55chat-bot/data/bot.lock"
)
_LOCK_FP = None
_REPLY_COOLDOWN: dict[str, float] = {}
REPLY_COOLDOWN_SEC = max(0.0, float(os.environ.get("BOT_REPLY_COOLDOWN_SEC", "0") or 0))
# 仅防探针+读屏同一气泡双触发（亚秒级），不挡用户连发相同指令
CMD_CLAIM_RACE_SEC = max(0.3, float(os.environ.get("BOT_CMD_CLAIM_RACE_SEC", "0.8") or 0.8))
BOT_QUERY_REPLY_COOLDOWN_SEC = max(
    0.0,
    float(os.environ.get("BOT_QUERY_REPLY_COOLDOWN_SEC", "0") or 0),
)
CMD_SAME_SCREEN_Y_PX = max(60, int(os.environ.get("BOT_CMD_SAME_SCREEN_Y_PX", "140") or 140))
CMD_Y_BUCKET = max(40, int(os.environ.get("BOT_CMD_Y_BUCKET", "100") or 100))
CMD_Y_RESCAN_MARGIN = max(15, int(os.environ.get("BOT_CMD_Y_RESCAN_MARGIN", "25") or 25))
INCOMING_X_RATIO = float(os.environ.get("BOT_INCOMING_X_RATIO", "0.55") or 0.55)
_SENDING: dict[str, float] = {}
_LISTENER_SEND_LOCK: dict[str, bool] = {}
# 右机专用：仅 adb tap 发送键，不与 dump/读屏抢 ADB
_LISTENER_FIRE_QUEUES: dict[str, queue.SimpleQueue] = {}
_LISTENER_FIRE_THREADS: dict[str, threading.Thread] = {}
_LISTENER_FIRE_LOCK = threading.Lock()


class OutboundTaskPool:
    """公告 + 回复侧任务的有界并发池（ThreadPoolExecutor max_workers=10）。"""

    __slots__ = ("_executor", "max_workers")

    def __init__(self, max_workers: int = OUTBOUND_POOL_MAX) -> None:
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="outbound-pool",
        )

    def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        return self._executor.submit(fn, *args, **kwargs)

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


_OUTBOUND_TASK_POOL: OutboundTaskPool | None = None
_OUTBOUND_TASK_POOL_LOCK = threading.Lock()


def get_outbound_task_pool() -> OutboundTaskPool:
    global _OUTBOUND_TASK_POOL
    with _OUTBOUND_TASK_POOL_LOCK:
        if _OUTBOUND_TASK_POOL is None:
            _OUTBOUND_TASK_POOL = OutboundTaskPool()
        return _OUTBOUND_TASK_POOL


def shutdown_outbound_task_pool() -> None:
    global _OUTBOUND_TASK_POOL
    with _OUTBOUND_TASK_POOL_LOCK:
        if _OUTBOUND_TASK_POOL is not None:
            _OUTBOUND_TASK_POOL.shutdown(wait=False)
            _OUTBOUND_TASK_POOL = None


def submit_outbound_hook(
    fn: Callable[..., Any],
    /,
    *args: Any,
    label: str = "",
    **kwargs: Any,
) -> Future[Any]:
    """Panel Hook 非阻塞投递：局部失败仅记日志，不拖垮 Orchestrator 主循环。"""
    tag = label or getattr(fn, "__name__", "outbound-hook")

    def _run() -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("出站池任务异常 hook=%s", tag)
            return None

    return get_outbound_task_pool().submit(_run)


@dataclass
class _ListenerFireTap:
    serial: str
    x: int
    y: int
    done: threading.Event = field(default_factory=threading.Event)


def _listener_fire_worker(serial: str) -> None:
    q = _LISTENER_FIRE_QUEUES[serial]
    while True:
        cmd = q.get()
        if cmd is None:
            break
        try:
            adb_run(cmd.serial, "shell", "input", "tap", str(cmd.x), str(cmd.y))
            invalidate_ui_cache(cmd.serial)
            log.info("右机 fire 线程点发送 @(%d,%d)", cmd.x, cmd.y)
        except Exception:
            log.exception("右机 fire 线程 tap 异常 @(%d,%d)", cmd.x, cmd.y)
        finally:
            cmd.done.set()


def listener_ensure_fire_worker(serial: str) -> None:
    with _LISTENER_FIRE_LOCK:
        th = _LISTENER_FIRE_THREADS.get(serial)
        if th is not None and th.is_alive():
            return
        q = queue.SimpleQueue()
        _LISTENER_FIRE_QUEUES[serial] = q
        th = threading.Thread(
            target=_listener_fire_worker,
            args=(serial,),
            name=f"listener-fire-{serial.split(':')[-1]}",
            daemon=True,
        )
        th.start()
        _LISTENER_FIRE_THREADS[serial] = th


def listener_fire_send_tap(
    serial: str,
    settings: dict[str, str] | None = None,
    *,
    repeat: int = 1,
) -> tuple[int, int]:
    """零 dump：钉死坐标经专用 fire 线程立即 tap（不与读屏 dump 串行）。"""
    sx, sy = listener_pinned_send_xy(settings, None)
    listener_ensure_fire_worker(serial)
    q = _LISTENER_FIRE_QUEUES[serial]
    for i in range(max(1, repeat)):
        cmd = _ListenerFireTap(serial, sx, sy)
        q.put(cmd)
        if not cmd.done.wait(timeout=3.0):
            log.warning("右机 fire tap 超时 @(%d,%d) attempt=%d", sx, sy, i + 1)
    return sx, sy


# 左机专用：发图热路径 tap，不与 dump 抢 ADB
_CLICKER_FIRE_QUEUES: dict[str, queue.SimpleQueue] = {}
_CLICKER_FIRE_THREADS: dict[str, threading.Thread] = {}
_CLICKER_FIRE_LOCK = threading.Lock()


@dataclass
class _ClickerFireTap:
    serial: str
    x: int
    y: int
    done: threading.Event = field(default_factory=threading.Event)


def _clicker_fire_worker(serial: str) -> None:
    q = _CLICKER_FIRE_QUEUES[serial]
    while True:
        cmd = q.get()
        if cmd is None:
            break
        try:
            adb_run(cmd.serial, "shell", "input", "tap", str(cmd.x), str(cmd.y))
            invalidate_ui_cache(cmd.serial)
            log.info("左机 fire 线程点 @(%d,%d)", cmd.x, cmd.y)
        except Exception:
            log.exception("左机 fire tap 异常 @(%d,%d)", cmd.x, cmd.y)
        finally:
            cmd.done.set()


def clicker_ensure_fire_worker(serial: str) -> None:
    with _CLICKER_FIRE_LOCK:
        th = _CLICKER_FIRE_THREADS.get(serial)
        if th is not None and th.is_alive():
            return
        q = queue.SimpleQueue()
        _CLICKER_FIRE_QUEUES[serial] = q
        th = threading.Thread(
            target=_clicker_fire_worker,
            args=(serial,),
            name=f"clicker-fire-{serial.split(':')[-1]}",
            daemon=True,
        )
        th.start()
        _CLICKER_FIRE_THREADS[serial] = th


def clicker_fire_tap(serial: str, x: int, y: int) -> None:
    """左机发图热 tap：专用线程，零 dump。"""
    if serial_role(serial) == "LISTENER" or BOT_ROLE == "LISTENER":
        log.info("LISTENER 角色隔离：禁止 clicker_fire_tap @(%d,%d)", x, y)
        return
    if not is_clicker_serial(serial):
        adb_tap_raw(serial, x, y, purpose="clicker-fire")
        return
    clicker_ensure_fire_worker(serial)
    cmd = _ClickerFireTap(serial, x, y)
    _CLICKER_FIRE_QUEUES[serial].put(cmd)
    if not cmd.done.wait(timeout=3.0):
        log.warning("左机 fire tap 超时 @(%d,%d)", x, y)


@dataclass
class _UiCollectJob:
    kind: str  # root | snapshot
    force: bool
    chat: bool
    channel: str
    done: threading.Event = field(default_factory=threading.Event)
    root: ET.Element | None = None
    snap: UiSnapshot | None = None


class _UiResourceCollector:
    """资源 1：单 serial 读屏收集器；缓存命中即返，否则立即唤醒 worker dump 并 fan-out。"""

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = 0
        self._root_cache: tuple[float, ET.Element | None] | None = None
        self._snap_cache: dict[bool, tuple[float, UiSnapshot]] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._dump_lock = threading.Lock()


_UI_COLLECTORS: dict[str, _UiResourceCollector] = {}
_UI_COLLECTOR_THREADS: dict[str, threading.Thread] = {}
_UI_COLLECTOR_REG_LOCK = threading.Lock()


def _ui_collector_worker(serial: str) -> None:
    coll = _UI_COLLECTORS[serial]
    while True:
        if not coll._wake.wait(timeout=0.05):
            continue
        coll._wake.clear()
        while True:
            try:
                _, _, job = coll._q.get_nowait()
            except queue.Empty:
                break
            now = time.time()
            with coll._lock:
                if not job.force and job.kind == "root" and coll._root_cache:
                    ts, root = coll._root_cache
                    if now - ts < UI_CACHE_TTL:
                        job.root = root
                        job.done.set()
                        continue
                if not job.force and job.kind == "snapshot":
                    hit = coll._snap_cache.get(job.chat)
                    if hit and now - hit[0] < UI_CACHE_TTL:
                        job.snap = hit[1]
                        job.done.set()
                        continue
            batch = [job]
            while True:
                try:
                    _, _, j2 = coll._q.get_nowait()
                    batch.append(j2)
                except queue.Empty:
                    break
            force = any(j.force for j in batch)
            now2 = time.time()
            root: ET.Element | None = None
            with coll._lock:
                if not force and coll._root_cache and now2 - coll._root_cache[0] < UI_CACHE_TTL:
                    root = coll._root_cache[1]
            if root is None:
                with coll._dump_lock:
                    root = _ui_hierarchy_impl(serial, force=force)
                    ts = time.time()
                    with coll._lock:
                        coll._root_cache = (ts, root)
            chat_flags = {j.chat for j in batch if j.kind == "snapshot"}
            for chat_flag in chat_flags:
                snap = _ui_snapshot_from_root(root, chat=chat_flag)
                with coll._lock:
                    coll._snap_cache[chat_flag] = (time.time(), snap)
                    _SNAP_CACHE[serial] = (time.time(), snap)
            for j in batch:
                if j.done.is_set():
                    continue
                if j.kind == "root":
                    j.root = root
                else:
                    with coll._lock:
                        hit = coll._snap_cache.get(j.chat)
                    j.snap = hit[1] if hit else _ui_snapshot_from_root(root, chat=j.chat)
                j.done.set()
        if not coll._q.empty():
            coll._wake.set()


def _ui_collector_try_cache(
    coll: _UiResourceCollector,
    job: _UiCollectJob,
) -> bool:
    """缓存命中：立刻完成 job，不入队。"""
    now = time.time()
    with coll._lock:
        if not job.force and job.kind == "root" and coll._root_cache:
            ts, root = coll._root_cache
            if now - ts < UI_CACHE_TTL:
                job.root = root
                job.done.set()
                return True
        if not job.force and job.kind == "snapshot":
            hit = coll._snap_cache.get(job.chat)
            if hit and now - hit[0] < UI_CACHE_TTL:
                job.snap = hit[1]
                job.done.set()
                return True
    return False


def ui_collector_prewarm(serial: str) -> None:
    """启动后后台预采 listener+stay 快照，各线程首包不等 dump。"""
    def _go() -> None:
        try:
            _ui_collector_snapshot(serial, force=True, chat=True, channel="listener")
            _ui_collector_snapshot(serial, force=False, chat=False, channel="stay")
            log.info("ui-collect 预热完成 serial=%s", serial)
        except Exception:
            log.exception("ui-collect 预热失败 serial=%s", serial)

    threading.Thread(
        target=_go,
        name=f"ui-prewarm-{serial.split(':')[-1]}",
        daemon=True,
    ).start()


def ensure_ui_collector(serial: str) -> _UiResourceCollector:
    with _UI_COLLECTOR_REG_LOCK:
        coll = _UI_COLLECTORS.get(serial)
        if coll is not None:
            return coll
        coll = _UiResourceCollector(serial)
        _UI_COLLECTORS[serial] = coll
        th = threading.Thread(
            target=_ui_collector_worker,
            args=(serial,),
            name=f"ui-collect-{serial.split(':')[-1]}",
            daemon=True,
        )
        th.start()
        _UI_COLLECTOR_THREADS[serial] = th
        return coll


def _ui_collector_submit(
    serial: str,
    *,
    kind: str,
    force: bool,
    chat: bool,
    channel: str,
) -> _UiCollectJob:
    coll = ensure_ui_collector(serial)
    job = _UiCollectJob(kind, force, chat, channel)
    if _ui_collector_try_cache(coll, job):
        return job
    with coll._lock:
        coll._seq += 1
        prio = UI_CHANNEL_PRIO.get(channel, UI_CHANNEL_PRIO["default"])
        coll._q.put((prio, coll._seq, job))
    coll._wake.set()
    return job


def _ui_collector_root(
    serial: str,
    *,
    force: bool = False,
    channel: str = "default",
) -> ET.Element | None:
    coll = ensure_ui_collector(serial)
    now = time.time()
    with coll._lock:
        if not force and coll._root_cache and now - coll._root_cache[0] < UI_CACHE_TTL:
            return coll._root_cache[1]
    job = _ui_collector_submit(serial, kind="root", force=force, chat=False, channel=channel)
    if not job.done.wait(timeout=UI_COLLECTOR_TIMEOUT):
        log.warning("ui-collect root 超时 serial=%s channel=%s", serial, channel)
        return _ui_hierarchy_impl(serial, force=force)
    return job.root


def _ui_collector_snapshot(
    serial: str,
    *,
    force: bool,
    chat: bool,
    channel: str,
) -> UiSnapshot:
    coll = ensure_ui_collector(serial)
    now = time.time()
    with coll._lock:
        hit = coll._snap_cache.get(chat)
        if not force and hit and now - hit[0] < UI_CACHE_TTL:
            return hit[1]
    job = _ui_collector_submit(serial, kind="snapshot", force=force, chat=chat, channel=channel)
    if not job.done.wait(timeout=UI_COLLECTOR_TIMEOUT):
        log.warning("ui-collect snapshot 超时 serial=%s channel=%s", serial, channel)
        return _ui_snapshot_build(serial, force=force, chat=chat)
    return job.snap or UiSnapshot([], None, None, "", None, None, [], None)


_TAP_NEAR_Y: dict[str, int] = {}
_LOG_QUEUE: queue.SimpleQueue = queue.SimpleQueue()
_HAS_U2 = False
try:
    import uiautomator2 as u2  # type: ignore

    _HAS_U2 = True
except ImportError:
    u2 = None  # type: ignore

_HAS_CV2 = False
try:
    import numpy as np  # type: ignore
    import cv2  # type: ignore

    _HAS_CV2 = True
except ImportError:
    np = None  # type: ignore
    cv2 = None  # type: ignore


def w(sec: float, fast: float | None = None) -> None:
    """可配置等待：FAST 模式用更短间隔"""
    time.sleep(fast if FAST and fast is not None else sec)


def wc(sec: float, fast: float | None = None) -> None:
    """左机点击链路：比右机更激进的短等待。"""
    if CLICKER_FAST and FAST:
        time.sleep(fast if fast is not None else sec * 0.45)
    else:
        w(sec, fast)

API_BASE = os.environ.get("BOT_API_BASE", "http://127.0.0.1:3000").rstrip("/")
_BACKEND = BackendApiTransport(API_BASE, timeout=10)
DEFAULT_ADB = os.environ.get("VITE_DEFAULT_ADB_HOST", "localhost:56313")
DEFAULT_GROUP_USER = os.environ.get("BOT_GROUP_DEFAULT_USER", "qwer")
GROUP_TITLE_RE = re.compile(r"^.+\(\d+\)$")

DEFAULT_SETTINGS: dict[str, str] = {
    "botKeyword": "购买",
    "replyTemplate": (
        "用户：[{username}] / 交易成功 / 购买：{goods_name} / 实扣：{price}元 / 余额：{new_balance}元"
    ),
    "balanceReplyTemplate": (
        "用户：[{username}] / 积分：{balance_int} / 冻结：{frozen} / 余额：{balance_int} / 编号：{customer_code}"
    ),
    "insufficientTemplate": (
        "用户：[{username}] / {goods_name} / (无效,余额不足) / 当前余额：{balance}"
    ),
    "comboSuccessTemplate": (
        "{round_id}局 / 用户：[{username}] / 下单成功 / {package_name}[{items_display}] / "
        "下注总额：{total_cost} / 余额：{new_balance}"
    ),
    "topupPendingTemplate": (
        "用户：[{username}]\n上分:{amount}\n等待操作"
    ),
    "topupSuccessTemplate": (
        "用户：[{username}]\n已同意总上分:{amount}\n余额:{new_balance}\n编号:{customer_code}"
    ),
    "withdrawPendingTemplate": (
        "用户：[{username}]\n下分:{amount}\n等待操作"
    ),
    "withdrawSuccessTemplate": (
        "用户：[{username}]\n已同意下分:{amount}\n余额:{new_balance}\n编号:{customer_code}"
    ),
    "cancelSuccessTemplate": "{round_id}局 / 用户：[{username}] / 取消成功 / 返回积分：{return_amount}",
    "slashBetFailTemplate": (
        "{round_id}局 / 用户：[{username}] / {cmd} / (无效,余额不足) / 当前余额：{balance}"
    ),
    "inbarSendX": "674",
    "inbarSendY": "732",
    "keyboardSendX": "675",
    "keyboardSendY": "1190",
    "roundAnchorPeriod": "3445908",
    "roundAnchorBeijing": "2026-06-17 05:17:30",
    "roundIntervalSec": "210",
}

BALANCE_RE = re.compile(r"^(?:扣)?1$|^查$|^查余额$|^余额查询$")
TOPUP_RE = re.compile(r"^(?:上(?:分)?|如上)(\d+(?:\.\d+)?)$")
WITHDRAW_RE = re.compile(r"^(?:下(?:分)?|如下)(\d+(?:\.\d+)?)$")
BIND_RE = re.compile(r"^绑定(?:UID[- ]?)?(\d+)$", re.I)
MESSENGER_ID_RE = re.compile(r"^[a-z0-9]{6,16}$", re.I)
CANCEL_RE = re.compile(r"^(?:扣)?取消$")
QUERY_ROUND_BETS_RE = re.compile(r"^扣2$")
QUERY_FLOW_RE = re.compile(r"^扣查$")
QUERY_HISTORY_RE = re.compile(r"^扣历史$")
REBATE_RE = re.compile(r"^扣反水$")
ADD_FINANCE_CMD = os.environ.get("BOT_ADD_FINANCE_CMD", "添加")
ADD_FINANCE_RE = re.compile(
    rf"^[（(\[]?{re.escape(ADD_FINANCE_CMD)}[）)\]]?$"
)
LANE_SLASH_BET_RE = re.compile(r"^([1-4])/(.+)/(\d+(?:\.\d+)?)$")
MARK6_SLASH_BET_RE = re.compile(r"^5/(.+?)(\d+(?:\.\d+)?)$")
SLASH_BET_RE = LANE_SLASH_BET_RE
TIME_RE = re.compile(
    r"^\d{1,2}:\d{2}$|^\d+月\d+日$|^\d+局$|^\d+/\d+$|星期|周[一二三四五六日]"
)


QUERY_SYNTHETIC_CMD_Y = 1  # 短指令 UI 树无 Y 时占位，须非零以通过 tick/stage


def is_query_command(cmd: str) -> bool:
    """扣1/扣查等查询类：允许无 cmd_y，有发送者即可处理。"""
    c = (cmd or "").strip()
    return bool(
        BALANCE_RE.match(c)
        or CANCEL_RE.match(c)
        or QUERY_ROUND_BETS_RE.match(c)
        or QUERY_FLOW_RE.match(c)
        or QUERY_HISTORY_RE.match(c)
        or REBATE_RE.match(c)
    )


def normalize_cmd_key(cmd: str) -> str:
    """去重/冷却用 canonical 指令（1 与 扣1 等同）。"""
    c = (cmd or "").strip()
    if BALANCE_RE.match(c):
        return "__balance__"
    if CANCEL_RE.match(c):
        return "__cancel__"
    if QUERY_ROUND_BETS_RE.match(c):
        return "__round_bets__"
    if QUERY_FLOW_RE.match(c):
        return "__flow__"
    if QUERY_HISTORY_RE.match(c):
        return "__history__"
    if REBATE_RE.match(c):
        return "__rebate__"
    if ADD_FINANCE_RE.match(c):
        return "__add_finance__"
    if BIND_RE.match(c):
        return f"__bind__{BIND_RE.match(c).group(1)}"
    return c


_PENDING: dict[str, dict] = {}
_ROUND_BETS: dict[str, list[dict]] = {}
_ROUND_STAKES: dict[str, float] = {}
_ROUND_POOL: dict[str, list[dict]] = {}
_SETTLED_ROUNDS: set[int] = set()
_SETTLE_DISPATCHED: set[int] = set()
_CAPTURE_SUCCEEDED: set[int] = set()
_PAYOUT_DONE_ROUNDS: set[int] = set()
_SETTLE_SEND_ATTEMPT: dict[int, float] = {}
SETTLE_SEND_RETRY_SEC = max(1.0, float(os.environ.get("BOT_SETTLE_SEND_RETRY_SEC", "2") or 2))
SETTLE_OPEN_DEFER_MAX_SEC = max(
    60.0,
    float(os.environ.get("BOT_SETTLE_OPEN_DEFER_MAX_SEC", "120") or 120),
)
_DRAW_CACHE: tuple[float, dict] | None = None
_LAST_SEEN_DRAWN_RID: int = 0
ROUND_BETS_FILE = os.environ.get(
    "BOT_ROUND_BETS_FILE", "/home/bot/55chat-bot/data/round_bets.json",
)
SETTLED_ROUNDS_FILE = os.environ.get(
    "BOT_SETTLED_ROUNDS_FILE", "/home/bot/55chat-bot/data/settled_rounds.json",
)
ROUND_OPEN_ANNOUNCED_FILE = os.environ.get(
    "BOT_ROUND_OPEN_FILE", "/home/bot/55chat-bot/data/round_open_announced.json",
)
OPEN_AFTER_CAPTURE_FALLBACK_SEC = max(
    0.0, float(os.environ.get("BOT_OPEN_FALLBACK_SEC", "0") or 0),
)
SETTLE_ENABLED = os.environ.get("BOT_SETTLE", "1").lower() in ("1", "true", "yes")
SETTLE_HISTORY_ROWS = max(1, int(os.environ.get("BOT_SETTLE_HISTORY_ROWS", "10") or 10))
SETTLE_MARK6_TREND_ROWS = max(1, int(os.environ.get("BOT_MARK6_TREND_ROWS", "20") or 20))
SETTLE_MARK6_TREND_ENABLED = os.environ.get("BOT_MARK6_TREND", "0").lower() in ("1", "true", "yes")
SETTLE_CAPTURE_ENABLED = os.environ.get("BOT_SETTLE_CAPTURE", "1").lower() in ("1", "true", "yes")
CLICKER_IMG_SEND_RETRIES = max(
    1, int(os.environ.get("BOT_CLICKER_IMG_SEND_RETRIES", "1") or 1),
)
SETTLE_LOOP_SEC = max(0.1, float(os.environ.get("BOT_SETTLE_LOOP_SEC", "0.25") or 0.25))
ANNOUNCE_LOOP_SEC = max(0.1, float(os.environ.get("BOT_ANNOUNCE_LOOP_SEC", "0.25") or 0.25))
ANNOUNCE_TEMPLATE_LOCKED = os.environ.get("BOT_ANNOUNCE_LOCKED", "1").lower() in ("1", "true", "yes")
EDGE_LEFT_JS = os.environ.get("BOT_EDGE_LEFT_JS", "0").lower() in ("1", "true", "yes")
EDGE_BRAIN_URL = os.environ.get("BOT_EDGE_BRAIN_URL", "http://127.0.0.1:8790").rstrip("/")


def edge_brain_auth_headers() -> dict[str, str]:
    from edge_brain.jwt_auth import authorization_header

    return authorization_header()
_CLICKER_EXPECT_MODEL = os.environ.get("BOT_CLICKER_EXPECT_MODEL", "Pixel XL").strip()
SEND_QUEUE_ENABLED = os.environ.get("BOT_SEND_QUEUE", "1").lower() in ("1", "true", "yes")
# 发送优先级：数字越小越优先（用户指令 > 上分 > 公告 > 结算）
SEND_PRIO_CMD = 0
SEND_PRIO_BRAIN = 1
SEND_PRIO_TOPUP = 2
SEND_PRIO_OPEN_AFTER_SETTLE = 5
SEND_PRIO_OPEN_CATCHUP = 8
SEND_PRIO_WARN = 10
SEND_PRIO_CLOSE = 11
SEND_PRIO_OPEN = 12
SEND_PRIO_CAPTURE = 19
SEND_PRIO_SETTLE = 20
SEND_PRIO_TREND = 21
DRAW_API_URL = os.environ.get(
    "BOT_DRAW_API_URL", "https://28.run/api/lottery/recent/6",
)
DRAW_FETCH_INTERVAL = max(0.25, float(os.environ.get("BOT_DRAW_FETCH_SEC", "0.35") or 0.35))
SETTLE_TRADE_FLOW_TIMEOUT = max(
    0.8,
    float(
        os.environ.get(
            "BOT_SETTLE_TRADE_FLOW_TIMEOUT",
            "1.5" if os.environ.get("BOT_IMG_FAST", "0") in ("1", "true", "yes") else "3",
        )
        or 1.5,
    ),
)
YEAR_ZODIAC_IDX = int(os.environ.get("BOT_YEAR_ZODIAC_IDX", "6") or 6)  # 2026马年
ODDS_LANE_SINGLE = float(os.environ.get("BOT_ODDS_LANE_SINGLE", "9.63") or 9.63)
ODDS_LANE_DXDS = float(os.environ.get("BOT_ODDS_LANE_DXDS", "1.924") or 1.924)
ODDS_MARK6_NUMBER = float(os.environ.get("BOT_ODDS_MARK6_NUMBER", "46") or 46)
ODDS_PC28_DXDS = float(os.environ.get("BOT_ODDS_PC28_DXDS", "1.99") or 1.99)
# 花果山六合彩赔率（截图表）
ODDS_M6_DX: dict[str, float] = {"大": 1.84, "小": 1.91, "单": 1.84, "双": 1.91}
ODDS_M6_COMBO: dict[str, float] = {"大单": 3.5, "大双": 3.8, "小单": 3.8, "小双": 3.8}
ODDS_M6_HE: dict[str, float] = {"合单": 1.84, "合双": 1.91}
ODDS_M6_ZODIAC_HORSE = float(os.environ.get("BOT_ODDS_M6_ZODIAC_HORSE", "9.2") or 9.2)
ODDS_M6_ZODIAC_OTHER = float(os.environ.get("BOT_ODDS_M6_ZODIAC_OTHER", "11.5") or 11.5)
ODDS_M6_WAVE: dict[str, float] = {"红波": 2.7, "蓝波": 2.87, "绿波": 2.87}
ODDS_M6_HEAD: dict[int, float] = {0: 5.1, 1: 4.6, 2: 4.6, 3: 4.6, 4: 4.6}
ODDS_M6_TAIL_0 = 11.5
ODDS_M6_TAIL_OTHER = 9.2
ODDS_M6_WUXING: dict[str, float] = {"金": 4.6, "木": 4.6, "水": 5.1, "火": 3.8, "土": 5.7}
ODDS_PC28_1314_DXDS = float(os.environ.get("BOT_ODDS_PC28_1314_DXDS", "1.6") or 1.6)
ODDS_PC28_COMBO_A = float(os.environ.get("BOT_ODDS_PC28_COMBO_A", "4.58") or 4.58)  # 小单/大双
ODDS_PC28_COMBO_B = float(os.environ.get("BOT_ODDS_PC28_COMBO_B", "4.18") or 4.18)  # 小双/大单
PC28_SPECIAL_1314 = {13, 14}
LANE_DXDS_PICKS = frozenset({"大", "小", "单", "双"})
PC28_DXDS_PICKS = LANE_DXDS_PICKS
PC28_COMBO_PICKS = frozenset({"大单", "小单", "大双", "小双"})
ROUND_SYNC_API = os.environ.get("BOT_ROUND_SYNC_API", "1").lower() in ("1", "true", "yes")
_ROUND_API_CACHE: tuple[float, int] | None = None
PC28_POINT_ODDS: dict[int, float] = {
    0: 688, 27: 688, 1: 188, 26: 188, 2: 68, 25: 68, 3: 48, 24: 48,
    4: 38, 23: 38, 5: 28, 22: 28, 6: 17, 21: 17, 7: 16, 20: 16,
    8: 15, 19: 15, 9: 14, 18: 14, 10: 13, 17: 13, 11: 13, 16: 13,
    12: 12, 15: 12, 13: 12, 14: 12,
}
WAVE_RED = {1, 2, 7, 8, 12, 13, 18, 19, 23, 24, 29, 30, 34, 35, 40, 45, 46}
WAVE_BLUE = {3, 4, 9, 10, 14, 15, 20, 25, 26, 31, 36, 37, 41, 42, 47, 48}
WAVE_GREEN = {5, 6, 11, 16, 17, 21, 22, 27, 28, 32, 33, 38, 39, 43, 44, 49}
WUXING_MAP: dict[str, set[int]] = {
    "金": {3, 4, 11, 12, 25, 26, 33, 34, 41, 42},
    "木": {7, 8, 15, 16, 23, 24, 37, 38, 45, 46},
    "水": {13, 14, 21, 22, 29, 30, 43, 44},
    "火": {1, 2, 9, 10, 17, 18, 31, 32, 39, 40, 47, 48},
    "土": {5, 6, 19, 20, 27, 28, 35, 36, 49},
}
DEFAULT_SETTLE_ANNOUNCE = """[第{round_id}期]
================
--开奖号码为--
{number1} + {number2} + {number3} = {final_result} {pc28_combo}
================
{mark6_block}"""

MARK_SIX_MIN = 1
MARK_SIX_MAX = 49
PC28_MIN = 0
PC28_MAX = 27
LIMIT_LANE_UNIT = 5000
LIMIT_PC28_DXDS = 20000
LIMIT_PC28_COMBO = 10000
LIMIT_ROUND_USER = 100000
LIMIT_ROUND_PAYOUT = int(os.environ.get("BOT_LIMIT_ROUND_PAYOUT", "500000") or 500000)
# 花果山六合彩单注限额（截图）
LIMIT_M6_SPECIAL_MIN, LIMIT_M6_SPECIAL_MAX = 5, 1500
LIMIT_M6_DXDS_MIN, LIMIT_M6_DXDS_MAX = 20, 10000
LIMIT_M6_COMBO_MIN, LIMIT_M6_COMBO_MAX = 20, 10000
LIMIT_M6_ZODIAC_MIN, LIMIT_M6_ZODIAC_MAX = 20, 10000
LIMIT_M6_WAVE_MIN, LIMIT_M6_WAVE_MAX = 20, 50000
LIMIT_M6_HEAD_MIN, LIMIT_M6_HEAD_MAX = 20, 25000
LIMIT_M6_TAIL_MIN, LIMIT_M6_TAIL_MAX = 20, 10000
LIMIT_M6_WUXING_MIN, LIMIT_M6_WUXING_MAX = 20, 25000
# 总群当期限额
LIMIT_GROUP_M6_SPECIAL = 20000
LIMIT_GROUP_M6_ZODIAC = 50000
LIMIT_GROUP_M6_DXDS = 500000
LIMIT_GROUP_M6_COMBO = 250000
LIMIT_GROUP_M6_WAVE = 200000
LIMIT_GROUP_M6_HEAD = 100000
LIMIT_GROUP_M6_TAIL = 50000
LIMIT_GROUP_M6_WUXING = 50000
_ROUND_GROUP_STAKES: dict[str, float] = {}


ZODIAC_ANIMALS = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
WUXING_NAMES = ("金", "木", "水", "火", "土")
WAVE_NAMES = ("红波", "蓝波", "绿波")
DXDS_NAMES = (
    "大单", "小单", "大双", "小双", "合单", "合双",
    "大", "小", "单", "双",
)
HEAD_NAMES = tuple(f"{i}头" for i in range(5))
TAIL_NAMES = tuple(f"{i}尾" for i in range(10))
MARK6_KNOWN_TOKENS = sorted(
    list(ZODIAC_ANIMALS) + list(WUXING_NAMES) + list(WAVE_NAMES)
    + list(DXDS_NAMES) + list(HEAD_NAMES) + list(TAIL_NAMES),
    key=len,
    reverse=True,
)
BEIJING_TZ = timezone(timedelta(hours=8))
DEFAULT_ROUND_ANCHOR_PERIOD = 3445908
DEFAULT_ROUND_INTERVAL_SEC = 210  # 3分30秒
DEFAULT_ROUND_ANCHOR_BEIJING = "2026-06-17 05:17:30"

CLOSE_ANNOUNCE_ENABLED = os.environ.get("BOT_CLOSE_ANNOUNCE", "1").lower() in ("1", "true", "yes")
CLOSE_ANNOUNCE_BEFORE_SEC = max(1, int(os.environ.get("BOT_CLOSE_ANNOUNCE_SEC", "15") or 15))
OPEN_ANNOUNCE_AFTER_SEC = max(
    1.0,
    float(os.environ.get("BOT_OPEN_ANNOUNCE_AFTER_SEC", "10") or 10),
)
# 每期时序（期号与 28.run 对齐，正文见 docs/固定-公告顺序与内容文本.md）：
# 1) 封盘前 WARN → 封盘提醒
# 2) 封盘前 CLOSE → 封盘公告
# 3) 28.run 出新结果 → 左机三图 → 右机「新的一局」（禁止开奖文字、禁止 +10s 开局）
# 4) 封盘后至下一期 → 下单回复「已封盘，下单无效」
WARN_ANNOUNCE_ENABLED = os.environ.get("BOT_WARN_ANNOUNCE", "1").lower() in ("1", "true", "yes")
WARN_ANNOUNCE_BEFORE_SEC = max(1, int(os.environ.get("BOT_WARN_ANNOUNCE_SEC", "70") or 70))
MAINTENANCE_START = (18, 56)  # 北京时间停机维护开始（含）
MAINTENANCE_END = (19, 32)    # 北京时间停机维护结束（含），19:33 起恢复正常

DEFAULT_CLOSE_ANNOUNCE = """[禁]已封盘停止下注[禁]
-----------------------
线上有效 线下无效'一切以机器人核对栏为准。
未经核对，一律无效。
-----------------------
以PC28为开奖结果的定位胆玩法
第一道冠军
第二道亚军
第三道季军
下注格式如下：
比如下冠军买12345各100如:1/12345/100
前面123即冠亚季军/后面为下注内容，下注内容后/为金额
定位胆玩法01234为小，56789为大
第四道PC28特码需以空格键隔开，如下：
4/1 2 3/100=4道P C特码123号各100
第123道定位胆玩法单个数字限额5000
第4道PC28玩法，大小单双限额2万，组合限额10000
当期个人总注限额100000，单期最高派彩500000

--------------------------------------------------------------六合彩玩法:特码赔率46倍
冠军:代表特码头01234头 5=0头 6=1头
7=2头 8=3头 9=4头
亚军代表尾0-9
遇到5-0或者0-0保本，不输不赢退回本金。不算流水

下注格式
特码例如，5/1.2.3.4.5.6.7.8.9.10各100

生肖：例如5/鼠牛虎100=鼠100 牛100 虎100
五行：例如5/金木土100=金100 木100 土100
波段：例如5/红波100= 红波100
大小单双：例如5/大100 =大100
大单小单大双小双：例如5/大单100=大单100
合单合双：例如5/合单100
头尾：例如5/0头100 =0头100  5/1尾100=1尾100
------------------------
如遇官网已开奖，群机器人卡顿尚未封盘，进行下注的玩家不予赔偿，只吃不赔！
------------------------
温馨提示：每天18：56-19：32时间段停机维护时间！！！
------------------------
开奖网：
28.run
pc28.am"""

DEFAULT_WARN_ANNOUNCE = """[钱]距离封盘还有60秒[抱拳]
-----------------
【定位胆 1-3道】单点9.63 · 大小单双1.924
01234为小，56789为大（无视1314）

【第4道 PC28】大小单双1.99（1314→1.6）
小单/大双4.58（1314退本）小双/大单4.18
特码点杀见封盘公告表

【六合彩赔率】
特码1-49：46倍（单注5-1500）
大小单双：大/单1.84 小/双1.91
组合：大单3.5 大双/小单/小双3.8
合单1.84 合双1.91
生肖：马9.2 其他11.5
波色：红2.7 蓝/绿2.87
头：0头5.1 1-4头4.6
尾：0尾11.5 1-9尾9.2
五行：金木4.6 水5.1 火3.8 土5.7
保本：5-0或0-0退本不算流水
开奖以28.run为准"""

DEFAULT_ROUND_OPEN_ANNOUNCE = """【{round_id}期】 新的一局开始
----------------------------
群内指令:
上1000 / 下1000  上分下分
扣反水  群内反水
扣1 查余额编号 | 扣2 本期下注 | 扣查 流水 | 扣历史 走势图
扣取消 取消下注
----------------------------
下注格式:
1/12345/100  冠军定位胆
4/1.2.3/100  第4道PC特码（点分隔）
5/鼠牛虎100  六合彩（5开头）
开奖结果以28.run为准
（{round_time}）"""

_CLOSE_ANNOUNCED_ROUND: dict[str, int] = {}
_WARN_ANNOUNCED_ROUND: dict[str, int] = {}

OPEN_ANNOUNCE_ENABLED = os.environ.get("BOT_OPEN_ANNOUNCE", "1").lower() in ("1", "true", "yes")

_ROUND_OPEN_ANNOUNCED: dict[str, int] = {}
_OPEN_AFTER_CAPTURE_TS: dict[int, float] = {}
_CAPTURE_GALLERY_PUSHED: set[int] = set()
_OPEN_DEFER_LOG: dict[tuple[str, int], float] = {}
_OPEN_RECOVERY_LOG: dict[tuple[str, int], float] = {}
_OPEN_DISPATCH_SENT: set[tuple[str, int]] = set()
_WARN_DISPATCH_SENT: set[tuple[str, int]] = set()
_CLOSE_DISPATCH_SENT: set[tuple[str, int]] = set()
_ANNOUNCE_FAIL_UNTIL: dict[tuple[str, str, int], float] = {}
ANNOUNCE_FAIL_COOLDOWN_SEC = max(
    30.0, float(os.environ.get("BOT_ANNOUNCE_FAIL_COOLDOWN_SEC", "90") or 90),
)
_ANNOUNCE_BUSY_DEFER_UNTIL: dict[str, float] = {}
ANNOUNCE_BUSY_DEFER_SEC = max(2.0, float(os.environ.get("BOT_ANNOUNCE_BUSY_DEFER_SEC", "4") or 4))
_MAINT_WAS_ACTIVE = False
_MAINT_RESUME_AT: float = 0.0

IGNORE_TEXT = {
    "发送", "在线", "离线", "消息", "联系人", "通讯录", "发现", "我", "搜索", "返回",
    "相册", "拍摄", "语音", "表情", "更多", "确定", "复制", "粘贴",
    "V03", "云机信息", "本地调试", "基本信息", "输入消息", "上拉加载更多", "刚刚在线",
    "1条新消息", "条新消息", "新消息", "条相关聊天记录",
    "CMCC", "CSL", "5G", "4G", "LTE",
    "关闭功能菜单", "功能菜单",
}
UI_SENDER_BLOCK = (
    "ADB Keyboard", "ADB IME", "键盘", "通讯录", "联系人", "消息", "发现", "我",
    "云机", "本地调试", "输入消息", "上拉加载", "关闭功能菜单", "功能菜单",
)

FRIEND_ACCEPT_LABELS = ("通过", "接受", "Accept", "确认")
FRIEND_ACCEPT_EXACT = ("验证", "通过", "接受", "Accept", "accept", "确认")
CONTACTS_TAB_LABELS = ("通讯录", "联系人", "Contacts")
MESSAGES_TAB_LABELS = ("消息", "Chats", "会话")
NEW_FRIEND_LABELS = ("新的朋友", "好友申请", "新朋友")
GROUP_CHAT_LABELS = ("群聊", "Group Chats", "Groups")
NEW_FRIENDS_PAGE_MARKERS = ("新的朋友", "待处理", "近期请求")
FRIEND_DONE_LABELS = ("已同意", "已添加", "已拒绝")
FRIEND_PASS_VERIFY_LABELS = ("通过验证",)
FRIEND_VERIFY_LIST_LABEL = "验证"
FRIEND_DETAIL_MARKERS = ("通过验证", "请求添加好友", "加入黑名单")
ADD_FRIEND_LABELS = ("添加好友", "加好友", "Add Friend", "添加为好友")
ADD_STRANGER_BTN = ("添加", "添加好友", "加好友", "添加为好友")
SEND_MESSAGE_LABELS = ("发送消息", "发消息", "Send message", "Send Message")
ADD_VERIFY_DONE = ("完成", "Done")
ADD_VERIFY_TITLE_MARKERS = ("添加验证",)
FRIEND_REQUEST_SENT_MARKERS = ("已向对方发送添加申请", "已发送")
FRIEND_REQUEST_MSG = os.environ.get("BOT_FRIEND_REQUEST_MSG", "我是记账财务")
ADD_FINANCE_REPLY = os.environ.get("BOT_ADD_FINANCE_REPLY", "已发送请求，刷新后请同意")
ADD_FINANCE_FAIL_REPLY = os.environ.get(
    "BOT_ADD_FINANCE_FAIL_REPLY",
    "添加失败请检查是否开启允许添加功能，或联系群主关闭群内禁止添加好友功能",
)
UNREGISTERED_REPLY = os.environ.get(
    "BOT_UNREGISTERED_REPLY",
    "未登记，请联系群主添加账号，或发送 添加",
)
BET_FORMAT_MSG = os.environ.get(
    "BOT_BET_FORMAT_REPLY",
    "指令格式错误，请检查后重试",
)
BET_CLOSED_MSG = os.environ.get("BOT_BET_CLOSED_REPLY", "已封盘，下单无效")
MAINTENANCE_MSG = os.environ.get(
    "BOT_MAINTENANCE_REPLY",
    "停机维护中...",
)
ADD_FINANCE_ALREADY_REPLY = os.environ.get("BOT_ADD_FINANCE_ALREADY_REPLY", "您已是好友，无需重复添加")
PANEL_FRIEND_ACCEPT = False  # 已移除控制面板好友验证功能
MESSENGER_APP_LABELS = ("55", "55Messenger", "55 Messenger")
MESSENGER_MARKERS = (
    "输入消息", "Enter message", "消息", "通讯录", "联系人", "新的朋友",
    "群聊", "Group Chats", "Groups", "Chats", "会话",
)
# 官方/系统会话，禁止在此发送业务回复
SYSTEM_CHAT_BLOCK = ("V03", "云机信息", "本地调试", "系统通知", "官方", "Messenger")
SEARCH_PAGE_MARKERS = ("支持搜索联系人", "支持搜索", "频道别名", "群别名")
SEARCH_CANCEL_LABELS = ("取消", "Cancel")
SECRET_KEY_MARKERS = ("加密密钥", "秘密聊天加密密钥", "端到端加密")
# 消息/通讯录顶栏搜索框大致 Y 区间，禁止在此区域盲点
SEARCH_BAR_Y_MAX = int(os.environ.get("BOT_SEARCH_BAR_Y_MAX", "220") or 220)
# 底部 ADB 键盘条 + 系统导航栏（黑条）禁止点击，否则会退出 55M
NAV_BAR_RESERVE_PX = max(80, int(os.environ.get("BOT_NAV_RESERVE_PX", "130") or 130))
CHAT_INPUT_Y_MAX = int(os.environ.get("BOT_CHAT_INPUT_Y_MAX", "1150") or 1150)


def chat_message_y_bounds(
    root: ET.Element | None = None,
    *,
    sh: int | None = None,
    input_bounds: tuple[int, int, int, int] | None = None,
) -> tuple[int, int]:
    """聊天消息可读 Y 区间：紧贴输入框上方，避免裁掉底部气泡（itel 1280 屏）。"""
    if sh is None:
        sh = screen_height(root) if root is not None else 1280
    top = int(sh * 0.11)
    input_top: int | None = input_bounds[1] if input_bounds else None
    if input_top is None and root is not None:
        for node in root.iter("node"):
            if "EditText" not in node.attrib.get("class", ""):
                continue
            b = parse_bounds(node.attrib.get("bounds", ""))
            if b:
                input_top = b[1] if input_top is None else min(input_top, b[1])
    if input_top and input_top > top + 100:
        bottom = input_top - 10
    else:
        bottom = min(max(CHAT_INPUT_Y_MAX, int(sh * 0.88)), sh - NAV_BAR_RESERVE_PX)
    return top, max(top + 80, bottom)


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()


def _knowledge_announce_templates() -> dict[str, str]:
    """§4 锁定正文：config/55m-knowledge/announce-templates.json"""
    path = Path(__file__).resolve().parent / "config" / "55m-knowledge" / "announce-templates.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tpls = data.get("templates") or {}
        out: dict[str, str] = {}
        if (tpls.get("warn") or {}).get("text"):
            out["warnAnnounceTemplate"] = str(tpls["warn"]["text"])
        if (tpls.get("close") or {}).get("text"):
            out["closeAnnounceTemplate"] = str(tpls["close"]["text"])
        if (tpls.get("open") or {}).get("template"):
            out["openAnnounceTemplate"] = str(tpls["open"]["template"])
        return out
    except Exception as ex:
        log.warning("读取 announce-templates.json 失败: %s", ex)
        return {}


def _apply_locked_announce_templates(out: dict[str, str]) -> dict[str, str]:
    if not ANNOUNCE_TEMPLATE_LOCKED:
        return out
    for key, val in _knowledge_announce_templates().items():
        if val.strip():
            out[key] = val.strip()
    return out


def merge_settings(raw: dict | None) -> dict[str, str]:
    out = dict(DEFAULT_SETTINGS)
    if raw:
        for k in DEFAULT_SETTINGS:
            if raw.get(k):
                out[k] = str(raw[k])
    env_tpl = os.environ.get("BOT_REPLY_TEMPLATE")
    if env_tpl and not (raw or {}).get("replyTemplate"):
        out["replyTemplate"] = env_tpl
    for key in (
        "topupPendingTemplate",
        "topupSuccessTemplate",
        "withdrawPendingTemplate",
        "withdrawSuccessTemplate",
    ):
        if raw and raw.get(key):
            out[key] = str(raw[key])
    for key in ("roundAnchorPeriod", "roundAnchorBeijing", "roundIntervalSec"):
        if raw and raw.get(key) is not None and str(raw.get(key)).strip() != "":
            out[key] = str(raw[key])
    if raw and raw.get("closeAnnounceTemplate"):
        out["closeAnnounceTemplate"] = str(raw["closeAnnounceTemplate"])
    elif not out.get("closeAnnounceTemplate"):
        out["closeAnnounceTemplate"] = DEFAULT_CLOSE_ANNOUNCE
    if raw and raw.get("warnAnnounceTemplate"):
        out["warnAnnounceTemplate"] = str(raw["warnAnnounceTemplate"])
    elif not out.get("warnAnnounceTemplate"):
        out["warnAnnounceTemplate"] = DEFAULT_WARN_ANNOUNCE
    if raw and raw.get("openAnnounceTemplate"):
        out["openAnnounceTemplate"] = str(raw["openAnnounceTemplate"])
    elif not out.get("openAnnounceTemplate"):
        out["openAnnounceTemplate"] = DEFAULT_ROUND_OPEN_ANNOUNCE
    if raw and raw.get("settleAnnounceTemplate"):
        out["settleAnnounceTemplate"] = str(raw["settleAnnounceTemplate"])
    elif not out.get("settleAnnounceTemplate"):
        out["settleAnnounceTemplate"] = DEFAULT_SETTLE_ANNOUNCE
    return _apply_locked_announce_templates(out)


def sanitize_announce_text(text: str) -> str:
    """去掉面板缓存里的旧群名/副标题，避免封盘提醒串字。"""
    out = (text or "").replace("花果山综合群", "").replace("赛车PC六合一体", "")
    out = re.sub(r"[ ·•]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def apply_template(tpl: str, **kwargs: Any) -> str:
    out = tpl
    for key, val in kwargs.items():
        out = out.replace("{" + key + "}", str(val))
    return sanitize_announce_text(out)


def finance_pending_reply(kind: str, username: str, amount: float, settings: dict[str, str]) -> str:
    if kind == "withdraw":
        tpl = settings.get("withdrawPendingTemplate") or DEFAULT_SETTINGS["withdrawPendingTemplate"]
    else:
        tpl = settings.get("topupPendingTemplate") or DEFAULT_SETTINGS["topupPendingTemplate"]
    return apply_template(tpl, username=username, amount=str(int(amount)))


def user_reply(username: str, *parts: str) -> str:
    """用户：[昵称]\\n段1\\n段2 …（竖列）"""
    uname = (username or "").strip()
    segs = [str(p).strip() for p in parts if p is not None and str(p).strip()]
    if uname:
        return "\n".join([f"用户：[{uname}]"] + segs) if segs else f"用户：[{uname}]"
    return "\n".join(segs)


def round_user_reply(round_id: int | str, username: str, *parts: str) -> str:
    """{期号}期\\n用户：[昵称]\\n…"""
    rid = int(round_id)
    body = user_reply(username, *parts)
    return f"{rid}期\n{body}" if body else f"{rid}期"


def with_user_header(text: str, username: str) -> str:
    """回复首行加上 用户：[群昵称]（正文已有则不再重复）。"""
    t = (text or "").strip()
    if not t:
        return t
    uname = (username or "").strip()
    if not uname:
        return t
    if re.search(r"用户[：:]\[", t):
        return t
    return f"用户：[{uname}]\n{t}"


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def format_group_display_time(dt: datetime | None = None) -> str:
    """与 55M 群聊 12 小时制对齐，如 6:55:40（不含前导零小时）。"""
    dt = dt or beijing_now()
    h12 = dt.hour % 12 or 12
    return f"{h12}:{dt.strftime('%M:%S')}"


def format_group_display_hm(dt: datetime | None = None) -> str:
    """12 小时制 h:MM，与群消息气泡时间一致。"""
    dt = dt or beijing_now()
    h12 = dt.hour % 12 or 12
    return f"{h12}:{dt.strftime('%M')}"


def parse_beijing_dt(text: str) -> datetime:
    raw = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=BEIJING_TZ)
        except ValueError:
            continue
    raise ValueError(f"invalid beijing datetime: {text}")


def current_round_id(settings: dict[str, str] | None = None) -> int:
    """当前投注期号：与 28.run next_prediction / active_round_timing 对齐。"""
    rid, _, _ = active_round_timing(settings)
    return rid


def round_timing(settings: dict[str, str] | None = None) -> tuple[int, int, float]:
    """返回 (期号, 周期秒数, 距本期结束的剩余秒数)。"""
    cfg = settings or {}
    anchor_period = int(cfg.get("roundAnchorPeriod") or DEFAULT_ROUND_ANCHOR_PERIOD)
    interval = int(cfg.get("roundIntervalSec") or DEFAULT_ROUND_INTERVAL_SEC)
    anchor_str = cfg.get("roundAnchorBeijing") or DEFAULT_ROUND_ANCHOR_BEIJING
    if interval <= 0:
        interval = DEFAULT_ROUND_INTERVAL_SEC
    anchor = parse_beijing_dt(anchor_str)
    elapsed = max(0.0, (beijing_now() - anchor).total_seconds())
    rounds_passed = int(elapsed // interval)
    round_id = anchor_period + rounds_passed
    remaining = interval - (elapsed - rounds_passed * interval)
    return round_id, interval, remaining


def active_round_timing(settings: dict[str, str] | None = None) -> tuple[int, int, float]:
    """期号+倒计时：优先 28.run API，避免锚点漂移导致封盘/开局公告期号错乱。"""
    cfg = settings or {}
    interval = int(cfg.get("roundIntervalSec") or DEFAULT_ROUND_INTERVAL_SEC)
    if interval <= 0:
        interval = DEFAULT_ROUND_INTERVAL_SEC
    data = fetch_28run_recent()
    if data:
        rows = data.get("recent_results") or []
        nxt = data.get("next_prediction") or {}
        rid = 0
        try:
            rid = int(nxt.get("expect") or 0)
        except (TypeError, ValueError):
            rid = 0
        if not rid and rows:
            try:
                rid = int(rows[-1].get("expect", 0)) + 1
            except (TypeError, ValueError):
                rid = 0
        if rid > 0 and rows:
            try:
                last_open = parse_beijing_dt(str(rows[-1].get("opentime") or ""))
                now = beijing_now()
                period_start = last_open + timedelta(seconds=interval)
                if now < period_start:
                    remaining = max(0.0, (period_start - now).total_seconds())
                    return rid, interval, remaining
                elapsed = (now - period_start).total_seconds()
                extra = int(elapsed // interval)
                rid = rid + extra
                rem = interval - (elapsed - extra * interval)
                if rem <= 0:
                    rem = interval
                return rid, interval, rem
            except (ValueError, TypeError):
                pass
        if rid > 0:
            _, _, rem = round_timing(cfg)
            return rid, interval, rem
    return round_timing(cfg)


def pending_settle_round_id(rid: int, data: dict | None = None) -> int | None:
    """上一期已开奖但尚未播报的期号（须先于「新的一局」发出）。"""
    last = latest_drawn_round_id(data)
    if last and last > 0 and last not in _SETTLED_ROUNDS:
        if data is not None:
            if find_draw_in_data(data, last):
                return last
        elif find_draw_for_round(last):
            return last
    prev = rid - 1
    if prev > 0 and prev not in _SETTLED_ROUNDS:
        if data is not None:
            if find_draw_in_data(data, prev):
                return prev
        elif find_draw_for_round(prev):
            return prev
    return None


def open_announce_recovery_needed(
    group: str, rid: int, data: dict | None = None,
) -> bool:
    """open 门闸落后 ≥2 期且无待结算期时才恢复；禁止抢在三图前发新一局。"""
    announced = int(_ROUND_OPEN_ANNOUNCED.get(group) or 0)
    if announced <= 0 or rid < announced + 2:
        return False
    return pending_settle_round_id(rid, data) is None


def settle_open_defer_expired(pending: int, data: dict | None = None) -> bool:
    """仅当结算发图已结案（非进行中）且超时，才允许降级发「新的一局」。"""
    if pending <= 0 or pending in _SETTLED_ROUNDS:
        return False
    try:
        from bot_ops.capture_ipc import capture_in_progress_for_rid, capture_terminal_for_rid

        if capture_in_progress_for_rid(pending):
            return False
        if not capture_terminal_for_rid(pending):
            return False
    except Exception:
        return False
    if pending in _SETTLE_DISPATCHED:
        age = time.time() - _SETTLE_SEND_ATTEMPT.get(pending, 0.0)
        if age >= SETTLE_OPEN_DEFER_MAX_SEC:
            return True
    draw = find_draw_in_data(data, pending) if data else None
    if draw is None:
        draw = find_draw_for_round(pending, data)
    if draw:
        try:
            ot = str(draw.get("opentime") or "")
            if ot:
                lag = (beijing_now() - parse_beijing_dt(ot)).total_seconds()
                if lag >= SETTLE_OPEN_DEFER_MAX_SEC:
                    return True
        except Exception:
            pass
    return False


def next_round_start(settings: dict[str, str] | None = None) -> tuple[int, datetime]:
    """下一期期号及其开始的北京时间（与锚点对齐）。"""
    cfg = settings or {}
    anchor_period = int(cfg.get("roundAnchorPeriod") or DEFAULT_ROUND_ANCHOR_PERIOD)
    interval = int(cfg.get("roundIntervalSec") or DEFAULT_ROUND_INTERVAL_SEC)
    anchor_str = cfg.get("roundAnchorBeijing") or DEFAULT_ROUND_ANCHOR_BEIJING
    if interval <= 0:
        interval = DEFAULT_ROUND_INTERVAL_SEC
    anchor = parse_beijing_dt(anchor_str)
    elapsed = max(0.0, (beijing_now() - anchor).total_seconds())
    next_idx = int(elapsed // interval) + 1
    next_rid = anchor_period + next_idx
    next_start = anchor + timedelta(seconds=next_idx * interval)
    return next_rid, next_start


def current_round_start(settings: dict[str, str] | None = None) -> tuple[int, datetime]:
    """当前期号及其开始的北京时间。"""
    cfg = settings or {}
    anchor_period = int(cfg.get("roundAnchorPeriod") or DEFAULT_ROUND_ANCHOR_PERIOD)
    interval = int(cfg.get("roundIntervalSec") or DEFAULT_ROUND_INTERVAL_SEC)
    anchor_str = cfg.get("roundAnchorBeijing") or DEFAULT_ROUND_ANCHOR_BEIJING
    if interval <= 0:
        interval = DEFAULT_ROUND_INTERVAL_SEC
    anchor = parse_beijing_dt(anchor_str)
    elapsed = max(0.0, (beijing_now() - anchor).total_seconds())
    idx = int(elapsed // interval)
    rid = anchor_period + idx
    start = anchor + timedelta(seconds=idx * interval)
    return rid, start


def in_maintenance_window(now: datetime | None = None) -> bool:
    """每天北京时间 18:56–19:32（含）仅停公告/结算/下注；19:33 起恢复。"""
    now = now or beijing_now()
    cur = now.hour * 60 + now.minute
    start = MAINTENANCE_START[0] * 60 + MAINTENANCE_START[1]
    end = MAINTENANCE_END[0] * 60 + MAINTENANCE_END[1]
    return start <= cur <= end


def maintenance_blocks_bet(now: datetime | None = None) -> bool:
    """维护时段仅禁止下注，其余指令（查余额/上分/取消等）正常。"""
    return in_maintenance_window(now)


def maintenance_just_ended() -> bool:
    """维护窗口刚结束（19:33）→ 触发恢复「新的一局」。"""
    global _MAINT_WAS_ACTIVE, _MAINT_RESUME_AT
    active = in_maintenance_window()
    ended = _MAINT_WAS_ACTIVE and not active
    _MAINT_WAS_ACTIVE = active
    if ended:
        now = time.time()
        if now - _MAINT_RESUME_AT >= 20:
            _MAINT_RESUME_AT = now
            return True
    return False


def process_maintenance_resume(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    users: list[dict],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
) -> None:
    """维护结束：不补停机期间漏发的封盘/开奖公告，仅恢复当前期「新的一局」与正常接单。"""
    if not runs_announce_loop(bot):
        return
    group = (bot.get("associatedGroup") or "").strip()
    rid, _, _ = active_round_timing(settings)
    log.info("维护结束，恢复新的一局 bot=%s rid=%s group=%s", bot.get("id"), rid, group)
    if group:
        _ROUND_OPEN_ANNOUNCED.pop(group, None)
    data = fetch_28run_recent(force=True)
    process_round_open_announce(
        serial, bot, settings, input_xy, send_xy, data=data,
    )
    post_log(f"[ADB] 维护结束恢复 rid={rid}", "INFO")


def is_betting_open(settings: dict[str, str] | None = None) -> bool:
    """封盘前10秒至下一期开局后10秒内禁止下单（回复：已封盘，下单无效）。"""
    if maintenance_blocks_bet():
        return False
    _, interval, remaining = active_round_timing(settings)
    if remaining <= CLOSE_ANNOUNCE_BEFORE_SEC:
        return False
    elapsed = interval - remaining
    return elapsed >= OPEN_ANNOUNCE_AFTER_SEC


def pending_key(bot_id: str, user: dict) -> str:
    ck = str(user.get("customerCode") or user.get("messengerId") or user.get("username") or "")
    return f"{bot_id}:{ck}"


def parse_slash_bet(msg: str) -> tuple[str, str, float] | None:
    m = SLASH_BET_RE.match(msg.strip())
    if not m:
        return None
    return m.group(1), m.group(2), float(m.group(3))


def parse_combo(msg: str) -> tuple[str, list[str], int] | None:
    """解析自由组合：{code}/{item1}/{item2}各{qty} 或 {code}/{a}.{b}.{c}各{qty}"""
    t = msg.strip()
    last_each = t.rfind("各")
    if last_each == -1:
        return None
    after = t[last_each + 1 :].strip().lstrip(",，").strip()
    m_qty = re.match(r"^(\d+)", after)
    if not m_qty:
        return None
    qty = int(m_qty.group(1))
    if qty <= 0:
        return None
    before = t[:last_each].strip().rstrip("/.").strip()
    slash = before.find("/")
    if slash == -1:
        return None
    code = before[:slash].strip()
    items_str = before[slash + 1 :].strip()
    if not items_str:
        return None
    items: list[str] = []
    for sep in ("/", ".", "、", " "):
        if sep in items_str:
            items = [x.strip() for x in items_str.split(sep) if x.strip()]
            break
    if not items:
        items = [items_str]
    return code, items, qty


@dataclass
class BetOrder:
    kind: str
    code: str
    picks: list[str]
    unit_stake: float
    total: float
    raw: str
    round_id: int | None = None


def _parse_pc28_pick(token: str) -> int | None:
    t = token.strip()
    if not t.isdigit():
        return None
    n = int(t)
    if 0 <= n <= PC28_MAX:
        return n
    return None


def _parse_mark6_number(token: str) -> int | None:
    t = token.strip()
    if not t.isdigit():
        return None
    n = int(t)
    if MARK_SIX_MIN <= n <= MARK_SIX_MAX:
        return n
    return None


def split_mark6_body(body: str) -> list[str] | None:
    """解析 5/鼠牛虎100 或 5/1.2.3 中的选项列表。"""
    text = (body or "").strip().strip("/.")
    if not text:
        return None
    if any(sep in text for sep in (".", "、", "/", " ")):
        parts = re.split(r"[./、\s]+", text)
        return [p for p in parts if p] or None
    tokens: list[str] = []
    i = 0
    while i < len(text):
        matched = False
        for k in MARK6_KNOWN_TOKENS:
            if text.startswith(k, i):
                tokens.append(k)
                i += len(k)
                matched = True
                break
        if matched:
            continue
        m = re.match(r"\d{1,2}", text[i:])
        if m:
            tokens.append(m.group(0))
            i += len(m.group(0))
            continue
        return None
    return tokens or None


def is_pc28_pick_token(pick: str) -> bool:
    return (
        _parse_pc28_pick(pick) is not None
        or pick in PC28_DXDS_PICKS
        or pick in PC28_COMBO_PICKS
    )


def parse_lane_pick_tokens(pick_raw: str, *, lane: str) -> list[str] | None:
    text = (pick_raw or "").strip()
    if not text:
        return None
    if lane in ("1", "2", "3"):
        compact = text.replace(" ", "")
        if compact in LANE_DXDS_PICKS:
            return [compact]
        if compact.isdigit():
            return list(compact)
        tokens: list[str] = []
        i = 0
        while i < len(compact):
            if compact[i].isdigit():
                tokens.append(compact[i])
                i += 1
                continue
            matched = False
            for k in sorted(LANE_DXDS_PICKS, key=len, reverse=True):
                if compact.startswith(k, i):
                    tokens.append(k)
                    i += len(k)
                    matched = True
                    break
            if not matched:
                return None
        return tokens or None
    # 第4道：空格分隔特码，或大小单双/组合
    if text in PC28_DXDS_PICKS or text in PC28_COMBO_PICKS:
        return [text]
    tokens = text.split()
    if len(tokens) == 1 and not is_pc28_pick_token(tokens[0]):
        return None
    picks: list[str] = []
    for tok in tokens:
        if is_pc28_pick_token(tok):
            pn = _parse_pc28_pick(tok)
            if pn is not None:
                picks.append(f"{pn:02d}" if pn < 10 and len(tok) >= 2 else str(pn))
            else:
                picks.append(tok)
        else:
            return None
    return picks or None


def lane_digit_attrs(digit: int) -> dict[str, bool]:
    d = int(digit)
    return {
        "小": d <= 4,
        "大": d >= 5,
        "单": d % 2 == 1,
        "双": d % 2 == 0,
    }


def parse_lane_slash_bet(msg: str) -> BetOrder | None:
    m = LANE_SLASH_BET_RE.match((msg or "").strip())
    if not m:
        return None
    lane, pick_raw, stake_s = m.group(1), m.group(2).strip(), m.group(3)
    unit = float(stake_s)
    if unit <= 0:
        return None
    picks = parse_lane_pick_tokens(pick_raw, lane=lane)
    if not picks:
        return None
    total = unit * len(picks)
    kind = "pc28" if lane == "4" else "lane"
    return BetOrder(kind, lane, picks, unit, total, msg.strip())


def parse_mark6_slash_bet(msg: str) -> BetOrder | None:
    t = (msg or "").strip()
    if "各" in t:
        return None
    m = MARK6_SLASH_BET_RE.match(t)
    if not m:
        return None
    body, stake_s = m.group(1), m.group(2)
    unit = float(stake_s)
    if unit <= 0:
        return None
    picks = split_mark6_body(body)
    if not picks:
        return None
    total = unit * len(picks)
    return BetOrder("mark6", "5", picks, unit, total, t)


def parse_combo_bet(msg: str) -> BetOrder | None:
    parsed = parse_combo(msg)
    if not parsed:
        return None
    code, items, qty = parsed
    if qty <= 0:
        return None
    code_s = str(code)
    total = float(qty) * len(items)
    if code_s == "5":
        return BetOrder("combo", "5", items, float(qty), total, msg.strip())
    if code_s == "4":
        for it in items:
            if not is_pc28_pick_token(it):
                return None
        return BetOrder("pc28", "4", items, float(qty), total, msg.strip())
    if code_s in ("1", "2", "3"):
        for it in items:
            if it not in LANE_DXDS_PICKS and it not in "0123456789":
                return None
        return BetOrder("lane", code_s, items, float(qty), total, msg.strip())
    return None


def validate_mark6_pick(pick: str) -> bool:
    if pick in MARK6_KNOWN_TOKENS:
        return True
    return _parse_mark6_number(pick) is not None


def validate_bet_order(order: BetOrder, user: dict, bot_id: str, settings: dict[str, str]) -> str:
    if order.unit_stake < 1 or order.total < 1:
        return "金额最低1元起"
    if order.kind == "lane":
        if order.code not in ("1", "2", "3"):
            return "道次无效"
        for p in order.picks:
            if p not in "0123456789" and p not in LANE_DXDS_PICKS:
                return "定位胆仅0-9或大小单双"
        has_dxds = any(p in LANE_DXDS_PICKS for p in order.picks)
        cap = LIMIT_PC28_DXDS if has_dxds else LIMIT_LANE_UNIT
        if order.unit_stake > cap:
            return f"单注限额{cap}"
    elif order.kind == "pc28":
        for p in order.picks:
            if not is_pc28_pick_token(p):
                return "PC28仅00-27或大小单双组合"
        if any(p in PC28_COMBO_PICKS for p in order.picks):
            if order.unit_stake > LIMIT_PC28_COMBO:
                return f"组合单注限额{LIMIT_PC28_COMBO}"
        elif any(p in PC28_DXDS_PICKS for p in order.picks):
            if order.unit_stake > LIMIT_PC28_DXDS:
                return f"大小单双单注限额{LIMIT_PC28_DXDS}"
        elif order.unit_stake > LIMIT_PC28_DXDS:
            return f"特码单注限额{LIMIT_PC28_DXDS}"
    elif order.kind in ("mark6", "combo"):
        if str(order.code) != "5":
            return "六合玩法请用5开头"
        for p in order.picks:
            if not validate_mark6_pick(p):
                return f"特码仅1-{MARK_SIX_MAX}或生肖/波色/头尾"
            lo, hi = mark6_unit_limits(p)
            if order.unit_stake < lo:
                return f"{p}单注最低{int(lo)}"
            if order.unit_stake > hi:
                return f"{p}单注限额{int(hi)}"
        rid = order.round_id or current_round_id(settings)
        gerr = mark6_group_stake_check(bot_id, rid, order.picks, order.unit_stake)
        if gerr:
            return gerr
    else:
        return "玩法未识别"
    rid = order.round_id or current_round_id(settings)
    pk = f"{bot_id}:{user.get('customerCode') or user.get('username')}:{rid}"
    used = _ROUND_STAKES.get(pk, 0.0) + order.total
    if used > LIMIT_ROUND_USER:
        return f"当期个人总注限额{LIMIT_ROUND_USER}"
    return ""


def round_stake_add(bot_id: str, user: dict, round_id: int, amount: float, picks: list[str] | None = None) -> None:
    pk = f"{bot_id}:{user.get('customerCode') or user.get('username')}:{round_id}"
    _ROUND_STAKES[pk] = _ROUND_STAKES.get(pk, 0.0) + amount
    if picks:
        unit = amount / max(1, len(picks))
        mark6_group_stake_add(bot_id, round_id, picks, unit)


def round_bet_append(
    bot_id: str,
    user: dict,
    round_id: int,
    cmd: str,
    amount: float,
    order: BetOrder | None = None,
    username: str = "",
) -> None:
    key = pending_key(bot_id, user)
    rec: dict[str, Any] = {
        "round_id": round_id,
        "cmd": cmd,
        "amount": amount,
        "ts": time.time(),
        "bot_id": bot_id,
        "username": username or str(user.get("username") or ""),
        "customer_code": str(user.get("customerCode") or ""),
    }
    if order:
        rec.update({
            "kind": order.kind,
            "code": order.code,
            "picks": list(order.picks),
            "unit_stake": order.unit_stake,
        })
    _ROUND_BETS.setdefault(key, []).append(rec)
    _ROUND_POOL.setdefault(str(round_id), []).append(rec)
    save_round_bets_persisted()


def normalize_bet_cmd(cmd: str) -> str:
    """OCR/手输容错：各,1000 → 各1000；粘连金额 5/1.2.31000 → 5/1.2.3各1000"""
    t = (cmd or "").strip()
    t = re.sub(r"各\s*[,，]\s*", "各", t)
    t = re.sub(r"\s+各", "各", t)
    if "各" not in t and re.match(r"^[1-5]/", t):
        compact = re.sub(r"\s+", "", t)
        m = re.match(r"^([1-5]/.*?[./\d、]+?)(\d{2,6})$", compact)
        if m and "/" in m.group(1):
            body = m.group(1).rstrip("/.")
            t = f"{body}各{m.group(2)}"
    return t


def merge_split_bet_staged(
    staged: dict[tuple, tuple[str, str, int, int]],
) -> None:
    """OCR 把「5/1.2.3」与「1000」拆成两行时合并。"""
    rows = sorted(staged.values(), key=lambda r: (r[1].lower(), r[2]))
    remove: list[tuple[str, str, int, int]] = []
    for i in range(len(rows) - 1):
        c, snd, cy, cx = rows[i]
        c2, snd2, cy2, cx2 = rows[i + 1]
        if snd.lower() != snd2.lower() or not (0 < cy2 - cy <= 180):
            continue
        head, tail = c.strip(), c2.strip()
        if not re.match(r"^[1-5]/", head) or "各" in head:
            continue
        if not re.fullmatch(r"\d{2,6}", tail):
            continue
        merged = normalize_bet_cmd(f"{head}各{tail}")
        dedup = (merged, snd.lower(), cy // CMD_Y_BUCKET)
        staged[dedup] = (merged, snd, cy, cx)
        remove.extend([rows[i], rows[i + 1]])
    for row in remove:
        for k, v in list(staged.items()):
            if v == row:
                del staged[k]


def parse_any_bet(cmd: str) -> BetOrder | None:
    cmd = normalize_bet_cmd(cmd)
    for fn in (parse_lane_slash_bet, parse_mark6_slash_bet, parse_combo_bet):
        order = fn(cmd)
        if order:
            return order
    return None


def looks_like_bet_attempt(cmd: str) -> bool:
    """形似下注但 parse 失败 → 应回复格式错误（非静默忽略）。"""
    t = normalize_bet_cmd(cmd)
    if not t:
        return False
    if LANE_SLASH_BET_RE.match(t) or MARK6_SLASH_BET_RE.match(t):
        return True
    if re.match(r"^[1-5]/", t):
        return True
    if "各" in t and "/" in t:
        return True
    return False


def is_bet_command(cmd: str) -> bool:
    """下注/形似下注 → 不做同人同文去重（封盘/停机另判）。"""
    c = (cmd or "").strip()
    return bool(parse_any_bet(c) or looks_like_bet_attempt(c))


def needs_registration_reply(cmd: str) -> bool:
    """未登记用户发了业务指令 → 应提示联系群主。"""
    t = (cmd or "").strip()
    if BALANCE_RE.match(t):
        return True
    if TOPUP_RE.match(t) or WITHDRAW_RE.match(t) or CANCEL_RE.match(t):
        return True
    if QUERY_ROUND_BETS_RE.match(t) or QUERY_FLOW_RE.match(t) or QUERY_HISTORY_RE.match(t):
        return True
    if parse_any_bet(t) or looks_like_bet_attempt(t):
        return True
    return False


def fetch_user_bills(bot_id: str, username: str, limit: int = 15) -> list[dict]:
    return _fetch_user_bills_impl(_BACKEND, bot_id, username, limit)


def format_round_bets_reply(user: dict, bot_id: str, settings: dict[str, str], username: str) -> str:
    rid = current_round_id(settings)
    key = pending_key(bot_id, user)
    bets = [b for b in _ROUND_BETS.get(key, []) if b.get("round_id") == rid]
    if not bets:
        return user_reply(username, f"{rid}期暂无下注")
    detail = "\n".join(f"{b['cmd']}({int(b['amount'])})" for b in bets)
    total = sum(float(b["amount"]) for b in bets)
    return user_reply(username, "本期下注明细", detail, f"合计：{int(total)}")


def format_flow_reply(bot_id: str, username: str) -> str:
    bills = fetch_user_bills(bot_id, username, 12)
    if not bills:
        return user_reply(username, "暂无流水")
    lines = []
    for b in bills[:10]:
        typ = b.get("type", "")
        amt = b.get("amount", 0)
        detail = (b.get("detail") or "")[:40]
        lines.append(f"{typ}{amt:+.0f} {detail}".strip())
    return user_reply(username, "近期流水", *lines)


def format_history_reply(username: str) -> str:
    return user_reply(username, "28.run", "pc28.am")


# ── 开奖抓取与六合结算 ──────────────────────────────────────────────

def save_round_bets_persisted() -> None:
    try:
        os.makedirs(os.path.dirname(ROUND_BETS_FILE), exist_ok=True)
        with open(ROUND_BETS_FILE, "w", encoding="utf-8") as f:
            json.dump({"pool": _ROUND_POOL, "bets": _ROUND_BETS}, f, ensure_ascii=False)
    except Exception as ex:
        log.warning("保存下注记录失败: %s", ex)


def save_settled_rounds_persisted() -> None:
    try:
        os.makedirs(os.path.dirname(SETTLED_ROUNDS_FILE), exist_ok=True)
        with open(SETTLED_ROUNDS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(_SETTLED_ROUNDS), f)
    except Exception as ex:
        log.warning("保存已结算期号失败: %s", ex)


def save_round_open_announced_persisted() -> None:
    try:
        os.makedirs(os.path.dirname(ROUND_OPEN_ANNOUNCED_FILE), exist_ok=True)
        with open(ROUND_OPEN_ANNOUNCED_FILE, "w", encoding="utf-8") as f:
            json.dump(_ROUND_OPEN_ANNOUNCED, f, ensure_ascii=False)
    except Exception as ex:
        log.warning("保存开局公告状态失败: %s", ex)


def load_round_bets_persisted() -> None:
    global _ROUND_POOL, _ROUND_BETS, _SETTLED_ROUNDS
    try:
        if os.path.isfile(ROUND_BETS_FILE):
            with open(ROUND_BETS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("pool"), dict):
                _ROUND_POOL = data["pool"]
            if isinstance(data.get("bets"), dict):
                _ROUND_BETS = data["bets"]
    except Exception as ex:
        log.warning("加载下注记录失败: %s", ex)
    try:
        if os.path.isfile(SETTLED_ROUNDS_FILE):
            with open(SETTLED_ROUNDS_FILE, encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                _SETTLED_ROUNDS = {int(x) for x in rows}
    except Exception as ex:
        log.warning("加载已结算期号失败: %s", ex)
    try:
        if os.path.isfile(ROUND_OPEN_ANNOUNCED_FILE):
            with open(ROUND_OPEN_ANNOUNCED_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _ROUND_OPEN_ANNOUNCED.update(
                    {str(k): int(v) for k, v in data.items() if v}
                )
    except Exception as ex:
        log.warning("加载开局公告状态失败: %s", ex)
    _sync_open_gate_from_settled_on_boot()


def _sync_open_gate_from_settled_on_boot() -> None:
    """仅诊断：settled 与 announced 脱节时打日志，禁止无公告抬门闸。"""
    if not _SETTLED_ROUNDS or not _ROUND_OPEN_ANNOUNCED:
        return
    floor = max(_SETTLED_ROUNDS)
    for group, announced in list(_ROUND_OPEN_ANNOUNCED.items()):
        if announced < floor:
            log.warning(
                "gate 脱节 group=%s announced=%s settled_max=%s（须靠右机实发 open 推进）",
                group, announced, floor,
            )


def reload_round_state_from_disk() -> None:
    """双进程：LISTENER 公告环 reload 磁盘态，避免门闸/待结算期号陈旧。"""
    global _SETTLED_ROUNDS
    try:
        if os.path.isfile(SETTLED_ROUNDS_FILE):
            with open(SETTLED_ROUNDS_FILE, encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                _SETTLED_ROUNDS = {int(x) for x in rows}
    except Exception as ex:
        log.debug("reload settled: %s", ex)
    try:
        if os.path.isfile(ROUND_OPEN_ANNOUNCED_FILE):
            with open(ROUND_OPEN_ANNOUNCED_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _ROUND_OPEN_ANNOUNCED.update(
                    {str(k): int(v) for k, v in data.items() if v}
                )
    except Exception as ex:
        log.debug("reload open_announced: %s", ex)


def champion_digit_to_head(digit: int) -> int:
    """六合头：第一位从5起算第1档(0头)，5→0,6→1,7→2,8→3,9→4；0-4 直接对应头."""
    d = int(digit)
    if 0 <= d <= 4:
        return d
    if 5 <= d <= 9:
        return d - 5
    return d


def number_head(n: int) -> int:
    return 0 if n <= 9 else n // 10


def number_tail(n: int) -> int:
    return n % 10


def number_to_zodiac(n: int) -> str:
    return ZODIAC_ANIMALS[(YEAR_ZODIAC_IDX - (n - 1)) % 12]


def zodiac_number_set(zodiac: str) -> set[int]:
    return {n for n in range(MARK_SIX_MIN, MARK_SIX_MAX + 1) if number_to_zodiac(n) == zodiac}


def mark6_is_push(n1: int, n2: int) -> bool:
    """0-0、5-0 保本退本金，不输不赢."""
    return (n1 == 0 and n2 == 0) or (n1 == 5 and n2 == 0)


def mark6_he_parity(final_result: int) -> str:
    """合单/合双：特码(和值)十位+个位之和的奇偶."""
    fr = int(final_result)
    digit_sum = (fr // 10) + (fr % 10)
    return "合单" if digit_sum % 2 == 1 else "合双"


def mark6_winning_numbers(n1: int, n2: int) -> set[int]:
    head = champion_digit_to_head(n1)
    tail = int(n2)
    return {
        n for n in range(MARK_SIX_MIN, MARK_SIX_MAX + 1)
        if number_head(n) == head and number_tail(n) == tail
    }


def mark6_head_tail_labels(n1: int, n2: int) -> tuple[str, str, str]:
    head = champion_digit_to_head(n1)
    tail = int(n2)
    push = "（保本）" if mark6_is_push(n1, n2) else ""
    return str(head), str(tail), push


def format_opentime_hm(opentime: str) -> str:
    text = (opentime or "").strip()
    if " " in text:
        return text.split(" ", 1)[1][:5]
    if len(text) >= 5 and ":" in text:
        return text[:5]
    return beijing_now().strftime("%H:%M")


def format_opentime_md_hm(opentime: str) -> str:
    """06-07 6:03（12 小时制，与群聊对齐）"""
    text = (opentime or "").strip()
    try:
        if " " in text:
            d, t = text.split(" ", 1)
            parts = d.split("-")
            if len(parts) >= 3:
                hm = t[:8] if len(t) >= 8 else t[:5]
                if ":" in hm:
                    h, m, *rest = hm.split(":")
                    h24 = int(h)
                    h12 = h24 % 12 or 12
                    sec = f":{rest[0]}" if rest else ""
                    return f"{parts[1]}-{parts[2]} {h12}:{m}{sec}"
                return f"{parts[1]}-{parts[2]} {t[:5]}"
    except Exception:
        pass
    return beijing_now().strftime("%m-%d ") + format_group_display_hm()


def collect_recent_draw_rows(
    round_id: int,
    draw: dict,
    recent_rows: list[dict] | None,
    limit: int,
) -> list[dict]:
    table_rows: list[dict] = []
    seen: set[int] = set()
    if recent_rows:
        for raw in recent_rows[-max(limit, SETTLE_HISTORY_ROWS, SETTLE_MARK6_TREND_ROWS):]:
            norm = normalize_draw_row(raw) if "number1" in raw else dict(raw)
            rid = int(norm.get("round_id", 0))
            if rid and rid not in seen:
                table_rows.append(norm)
                seen.add(rid)
    cur_rid = int(draw.get("round_id", round_id))
    if cur_rid not in seen:
        table_rows.append(draw)
    table_rows.sort(key=lambda r: int(r.get("round_id", 0)), reverse=True)
    return table_rows[:limit]


def number_wuxing(n: int) -> str:
    for name, nums in WUXING_MAP.items():
        if n in nums:
            return name
    return "-"


def number_wave_label(n: int) -> str:
    if n in WAVE_RED:
        return "红"
    if n in WAVE_BLUE:
        return "蓝"
    if n in WAVE_GREEN:
        return "绿"
    return "-"


def special_number_for_draw(n1: int, n2: int) -> int | None:
    if mark6_is_push(n1, n2):
        return None
    winners = mark6_winning_numbers(n1, n2)
    return min(winners) if winners else None


def format_mark6_trend_row(row: dict, *, current_rid: int | None = None) -> str:
    rid = int(row.get("round_id") or row.get("expect") or 0)
    n1 = int(row.get("n1", row.get("number1", 0)))
    n2 = int(row.get("n2", row.get("number2", 0)))
    t = format_opentime_md_hm(str(row.get("opentime") or ""))
    mark = "►" if current_rid and rid == current_rid else " "
    if mark6_is_push(n1, n2):
        return f"{mark}{t:<12}{rid:<9}保本    -   -   - -  -  -  -"
    sp = special_number_for_draw(n1, n2)
    if sp is None:
        return f"{mark}{t:<12}{rid:<9}-      -   -   - -  -  -  -"
    zodiac = number_to_zodiac(sp)
    te = f"{sp:02d}{zodiac}" if sp < 10 else f"{sp}{zodiac}"
    dx = "单" if sp % 2 else "双"
    da = "大" if sp >= 25 else "小"
    hd = number_head(sp)
    tl = number_tail(sp)
    he = "单" if (hd + tl) % 2 else "双"
    wx = number_wuxing(sp)
    wave = number_wave_label(sp)
    return (
        f"{mark}{t:<12}{rid:<9}{te:<6}{dx:<4}{da:<4}"
        f"{hd:<3}{tl:<3}{he:<3}{wx:<3}{wave}"
    )


def format_mark6_trend_table(
    round_id: int,
    draw: dict,
    recent_rows: list[dict] | None = None,
) -> str:
    rows = collect_recent_draw_rows(round_id, draw, recent_rows, SETTLE_MARK6_TREND_ROWS)
    header = (
        f"{'时间':<12}{'期号':<9}{'特':<6}{'单双':<4}{'大小':<4}"
        f"{'头':<3}{'尾':<3}{'合':<3}{'五行':<3}{'波色'}"
    )
    body = [format_mark6_trend_row(r, current_rid=int(draw.get("round_id", round_id))) for r in rows]
    return "六合彩走势图\n" + header + "\n" + "\n".join(body)


def pc28_dxds_labels(final_result: int) -> tuple[str, str]:
    fr = int(final_result)
    return ("大" if fr >= 14 else "小", "单" if fr % 2 else "双")


def pc28_combo_label(final_result: int) -> str:
    dx, ds = pc28_dxds_labels(final_result)
    return f"{dx}{ds}"


def _fmt_odds(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def format_settle_compact_announce(round_id: int, draw: dict) -> str:
    n1 = int(draw["n1"])
    n2 = int(draw["n2"])
    n3 = int(draw["n3"])
    fr = int(draw["final_result"])
    combo = pc28_combo_label(fr)
    lines = [
        f"[第{round_id}期]",
        "================",
        "--开奖号码为--",
        f"{n1} + {n2} + {n3} = {fr} {combo}",
        "================",
    ]
    if mark6_is_push(n1, n2):
        lines.append("开:保本")
        return "\n".join(lines)
    sp = special_number_for_draw(n1, n2)
    if sp is None:
        return "\n".join(lines)
    zodiac = number_to_zodiac(sp)
    da = "大" if sp >= 25 else "小"
    dx = "单" if sp % 2 else "双"
    wave = number_wave_label(sp)
    hd = number_head(sp)
    tl = number_tail(sp)
    he = "合单" if (hd + tl) % 2 else "合双"
    wx = number_wuxing(sp)
    wave_key = f"{wave}波" if wave in ("红", "蓝", "绿") else wave
    wave_odds = ODDS_M6_WAVE.get(wave_key, 2.87)
    lines.append(f"开:({sp})({zodiac})({da})({dx})({wave})")
    lines.append(
        f"倍:({_fmt_odds(ODDS_MARK6_NUMBER)})({_fmt_odds(mark6_zodiac_odds(zodiac))})"
        f"({_fmt_odds(ODDS_M6_DX[da])})({_fmt_odds(ODDS_M6_DX[dx])})({_fmt_odds(wave_odds)})"
    )
    lines.append(f"开:({hd}头)({tl}尾)({he})({wx})")
    lines.append(
        f"倍:({_fmt_odds(mark6_head_odds(hd))})({_fmt_odds(mark6_tail_odds(tl))})"
        f"({_fmt_odds(ODDS_M6_HE[he])})({_fmt_odds(ODDS_M6_WUXING.get(wx, 4.6))})"
    )
    return "\n".join(lines)


def build_open_announce_text(rid: int, settings: dict[str, str]) -> str:
    tpl = sanitize_announce_text((settings.get("openAnnounceTemplate") or DEFAULT_ROUND_OPEN_ANNOUNCE).strip())
    round_time = format_group_display_time(beijing_now())
    return apply_template(tpl, round_id=rid, round_time=round_time)


def fetch_panel_draw_boards(count: int = 15) -> dict:
    return api("GET", f"/api/draw/boards?count={count}&refresh=1&_={int(time.time())}") or {}


def fetch_panel_trade_flow(period: int) -> dict:
    return api(
        "GET",
        f"/api/trade-flow?period={period}&botIds=bot-3,bot-4&_={int(time.time())}",
    ) or {}


def generate_settle_capture_paths(round_id: int, draw: dict | None = None) -> list[str]:
    if not SETTLE_CAPTURE_ENABLED or not _HAS_BOARD_CAPTURE:
        return []
    boards = fetch_panel_draw_boards()
    flow = fetch_panel_trade_flow(round_id)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as pool:
        paths = [
            pool.submit(render_pc28_board_png, boards, round_id=round_id).result(),
            pool.submit(render_mark6_board_png, boards, round_id=round_id).result(),
            pool.submit(render_trade_flow_png, flow, round_id=round_id).result(),
        ]
    if draw:
        log.info(
            "结算截图 rid=%s draw=%s+%s+%s=%s files=%s",
            round_id, draw["n1"], draw["n2"], draw["n3"], draw.get("final_result"),
            ", ".join(os.path.basename(p) for p in paths),
        )
    try:
        from board_capture import archive_settle_captures
        archive_settle_captures(round_id, paths)
    except Exception as ex:
        log.debug("截图归档跳过: %s", ex)
    return paths


def format_draw_result_row(row: dict, *, current_rid: int | None = None) -> str:
    rid = int(row.get("round_id") or row.get("expect") or 0)
    n1 = int(row.get("n1", row.get("number1", 0)))
    n2 = int(row.get("n2", row.get("number2", 0)))
    n3 = int(row.get("n3", row.get("number3", 0)))
    fr = int(row.get("final_result", n1 + n2 + n3))
    dx, ds = pc28_dxds_labels(fr)
    t = format_opentime_md_hm(str(row.get("opentime") or ""))
    mark = "►" if current_rid and rid == current_rid else " "
    return f"{mark}{rid:<9}{t:<12}{n1} {n2} {n3}  {fr:>2}   {dx}   {ds}"


def format_settle_result_table(
    round_id: int,
    draw: dict,
    recent_rows: list[dict] | None = None,
) -> str:
    """仿 28.run 走势图：期数/时间/三位结果/总和/大小/单双。"""
    cur_rid = int(draw.get("round_id", round_id))
    table_rows = collect_recent_draw_rows(round_id, draw, recent_rows, SETTLE_HISTORY_ROWS)
    return "\n".join(format_draw_result_row(r, current_rid=cur_rid) for r in table_rows)


def fetch_28run_recent(*, force: bool = False) -> dict | None:
    global _DRAW_CACHE
    now = time.time()
    if not force and _DRAW_CACHE and now - _DRAW_CACHE[0] < DRAW_FETCH_INTERVAL:
        return _DRAW_CACHE[1]
    try:
        req = urllib.request.Request(
            DRAW_API_URL,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://28.run/",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict):
            _DRAW_CACHE = (now, data)
            return data
    except Exception as ex:
        log.warning("拉取28.run开奖失败: %s", ex)
    return None


def find_draw_in_data(data: dict | None, round_id: int) -> dict | None:
    if not data:
        return None
    rows = data.get("recent_results") or []
    for row in rows:
        try:
            if int(row.get("expect", 0)) == int(round_id):
                return normalize_draw_row(row)
        except (TypeError, ValueError):
            continue
    return None


def find_draw_for_round(round_id: int, data: dict | None = None) -> dict | None:
    if data is not None:
        hit = find_draw_in_data(data, round_id)
        if hit:
            return hit
    payload = data if data is not None else fetch_28run_recent()
    if not payload:
        return None
    rows = payload.get("recent_results") or []
    for row in rows:
        try:
            if int(row.get("expect", 0)) == int(round_id):
                return normalize_draw_row(row)
        except (TypeError, ValueError):
            continue
    if rows:
        last = rows[-1]
        try:
            if int(last.get("expect", 0)) == int(round_id):
                return normalize_draw_row(last)
        except (TypeError, ValueError):
            pass
    return None


def normalize_draw_row(row: dict) -> dict:
    n1 = int(row.get("number1", 0))
    n2 = int(row.get("number2", 0))
    n3 = int(row.get("number3", 0))
    final_result = int(row.get("final_result", n1 + n2 + n3))
    return {
        "round_id": int(row.get("expect", 0)),
        "n1": n1,
        "n2": n2,
        "n3": n3,
        "final_result": final_result,
        "opentime": str(row.get("opentime") or ""),
    }




def mark6_zodiac_odds(animal: str) -> float:
    return ODDS_M6_ZODIAC_HORSE if animal == "马" else ODDS_M6_ZODIAC_OTHER


def mark6_head_odds(head: int) -> float:
    return ODDS_M6_HEAD.get(int(head), 4.6)


def mark6_tail_odds(tail: int) -> float:
    return ODDS_M6_TAIL_0 if int(tail) == 0 else ODDS_M6_TAIL_OTHER


def mark6_pick_category(pick: str) -> str:
    if _parse_mark6_number(pick) is not None:
        return "special"
    if pick in ZODIAC_ANIMALS:
        return "zodiac"
    if pick in WUXING_MAP:
        return "wuxing"
    if pick in ("红波", "蓝波", "绿波"):
        return "wave"
    if pick.endswith("头") and pick[:-1].isdigit():
        return "head"
    if pick.endswith("尾") and pick[:-1].isdigit():
        return "tail"
    if pick in ODDS_M6_COMBO:
        return "combo"
    if pick in ODDS_M6_HE:
        return "heds"
    if pick in ODDS_M6_DX:
        return "dxds"
    return "other"


def mark6_unit_limits(pick: str) -> tuple[float, float]:
    cat = mark6_pick_category(pick)
    if cat == "special":
        return float(LIMIT_M6_SPECIAL_MIN), float(LIMIT_M6_SPECIAL_MAX)
    if cat == "zodiac":
        return float(LIMIT_M6_ZODIAC_MIN), float(LIMIT_M6_ZODIAC_MAX)
    if cat == "wuxing":
        return float(LIMIT_M6_WUXING_MIN), float(LIMIT_M6_WUXING_MAX)
    if cat == "wave":
        return float(LIMIT_M6_WAVE_MIN), float(LIMIT_M6_WAVE_MAX)
    if cat == "head":
        return float(LIMIT_M6_HEAD_MIN), float(LIMIT_M6_HEAD_MAX)
    if cat == "tail":
        return float(LIMIT_M6_TAIL_MIN), float(LIMIT_M6_TAIL_MAX)
    if cat == "combo":
        return float(LIMIT_M6_COMBO_MIN), float(LIMIT_M6_COMBO_MAX)
    return float(LIMIT_M6_DXDS_MIN), float(LIMIT_M6_DXDS_MAX)


def mark6_group_limit(cat: str) -> float:
    return {
        "special": LIMIT_GROUP_M6_SPECIAL,
        "zodiac": LIMIT_GROUP_M6_ZODIAC,
        "dxds": LIMIT_GROUP_M6_DXDS,
        "heds": LIMIT_GROUP_M6_DXDS,
        "combo": LIMIT_GROUP_M6_COMBO,
        "wave": LIMIT_GROUP_M6_WAVE,
        "head": LIMIT_GROUP_M6_HEAD,
        "tail": LIMIT_GROUP_M6_TAIL,
        "wuxing": LIMIT_GROUP_M6_WUXING,
    }.get(cat, LIMIT_GROUP_M6_DXDS)


def mark6_group_stake_key(bot_id: str, round_id: int, cat: str) -> str:
    return f"{bot_id}:{round_id}:m6:{cat}"


def mark6_group_stake_add(bot_id: str, round_id: int, picks: list[str], unit: float) -> None:
    for p in picks:
        cat = mark6_pick_category(p)
        k = mark6_group_stake_key(bot_id, round_id, cat)
        _ROUND_GROUP_STAKES[k] = _ROUND_GROUP_STAKES.get(k, 0.0) + unit


def mark6_group_stake_check(bot_id: str, round_id: int, picks: list[str], unit: float) -> str:
    by_cat: dict[str, float] = {}
    for p in picks:
        cat = mark6_pick_category(p)
        by_cat[cat] = by_cat.get(cat, 0.0) + unit
    for cat, add in by_cat.items():
        k = mark6_group_stake_key(bot_id, round_id, cat)
        used = _ROUND_GROUP_STAKES.get(k, 0.0) + add
        cap = mark6_group_limit(cat)
        if used > cap:
            labels = {
                "special": "特码", "zodiac": "生肖", "dxds": "大小单双",
                "heds": "合单合双", "combo": "组合", "wave": "波色",
                "head": "头", "tail": "尾", "wuxing": "五行",
            }
            return f"当期总群{labels.get(cat, cat)}限额{cap}"
    return ""


def calc_lane_payout(code: str, picks: list[str], unit: float, draw: dict) -> float:
    lane_map = {"1": draw["n1"], "2": draw["n2"], "3": draw["n3"]}
    digit = lane_map.get(str(code))
    if digit is None:
        return 0.0
    ds = str(digit)
    attrs = lane_digit_attrs(int(digit))
    payout = 0.0
    for pick in picks:
        if pick == ds:
            payout += unit * ODDS_LANE_SINGLE
        elif pick in LANE_DXDS_PICKS and attrs.get(pick):
            payout += unit * ODDS_LANE_DXDS
    return payout


def calc_pc28_payout(picks: list[str], unit: float, final_result: int) -> float:
    payout = 0.0
    fr = int(final_result)
    is_1314 = fr in PC28_SPECIAL_1314
    is_big = fr >= 14
    is_odd = fr % 2 == 1
    dxds_odds = ODDS_PC28_1314_DXDS if is_1314 else ODDS_PC28_DXDS
    for pick in picks:
        pn = _parse_pc28_pick(pick)
        if pn is not None and pn == fr:
            payout += unit * PC28_POINT_ODDS.get(fr, 12.0)
            continue
        if pick == "大" and is_big:
            payout += unit * dxds_odds
        elif pick == "小" and not is_big:
            payout += unit * dxds_odds
        elif pick == "单" and is_odd:
            payout += unit * dxds_odds
        elif pick == "双" and not is_odd:
            payout += unit * dxds_odds
        elif pick == "小单" and not is_big and is_odd:
            payout += unit if is_1314 else unit * ODDS_PC28_COMBO_A
        elif pick == "大双" and is_big and not is_odd:
            payout += unit if is_1314 else unit * ODDS_PC28_COMBO_A
        elif pick == "小双" and not is_big and not is_odd:
            payout += unit * ODDS_PC28_COMBO_B
        elif pick == "大单" and is_big and is_odd:
            payout += unit * ODDS_PC28_COMBO_B
    return payout


def calc_mark6_payout(picks: list[str], unit: float, draw: dict) -> float:
    n1, n2 = draw["n1"], draw["n2"]
    if mark6_is_push(n1, n2):
        return unit * len(picks)
    winners = mark6_winning_numbers(n1, n2)
    head = champion_digit_to_head(n1)
    tail = int(n2)
    fr = int(draw["final_result"])
    is_big = fr >= 14
    is_odd = fr % 2 == 1
    he = mark6_he_parity(fr)
    payout = 0.0
    for pick in picks:
        num = _parse_mark6_number(pick)
        if num is not None:
            if num in winners:
                payout += unit * ODDS_MARK6_NUMBER
            continue
        if pick.endswith("头") and pick[:-1].isdigit():
            if int(pick[:-1]) == head:
                payout += unit * mark6_head_odds(head)
            continue
        if pick.endswith("尾") and pick[:-1].isdigit():
            if int(pick[:-1]) == tail:
                payout += unit * mark6_tail_odds(tail)
            continue
        if pick in ZODIAC_ANIMALS:
            if winners & zodiac_number_set(pick):
                payout += unit * mark6_zodiac_odds(pick)
            continue
        if pick in WUXING_MAP and winners & WUXING_MAP[pick]:
            payout += unit * ODDS_M6_WUXING.get(pick, 4.6)
            continue
        if pick == "红波" and winners & WAVE_RED:
            payout += unit * ODDS_M6_WAVE["红波"]
        elif pick == "蓝波" and winners & WAVE_BLUE:
            payout += unit * ODDS_M6_WAVE["蓝波"]
        elif pick == "绿波" and winners & WAVE_GREEN:
            payout += unit * ODDS_M6_WAVE["绿波"]
        elif pick == "大" and is_big:
            payout += unit * ODDS_M6_DX["大"]
        elif pick == "小" and not is_big:
            payout += unit * ODDS_M6_DX["小"]
        elif pick == "单" and is_odd:
            payout += unit * ODDS_M6_DX["单"]
        elif pick == "双" and not is_odd:
            payout += unit * ODDS_M6_DX["双"]
        elif pick == "大单" and is_big and is_odd:
            payout += unit * ODDS_M6_COMBO["大单"]
        elif pick == "小单" and not is_big and is_odd:
            payout += unit * ODDS_M6_COMBO["小单"]
        elif pick == "大双" and is_big and not is_odd:
            payout += unit * ODDS_M6_COMBO["大双"]
        elif pick == "小双" and not is_big and not is_odd:
            payout += unit * ODDS_M6_COMBO["小双"]
        elif pick == he:
            payout += unit * ODDS_M6_HE.get(he, 1.84)
    return payout


def calc_bet_payout(bet: dict, draw: dict) -> float:
    kind = str(bet.get("kind") or "")
    picks = [str(p) for p in (bet.get("picks") or [])]
    unit = float(bet.get("unit_stake") or bet.get("amount") or 0)
    if not picks:
        order = parse_any_bet(str(bet.get("cmd") or ""))
        if not order:
            return 0.0
        kind = order.kind
        picks = order.picks
        unit = order.unit_stake
    if kind == "lane":
        return calc_lane_payout(str(bet.get("code") or ""), picks, unit, draw)
    if kind == "pc28":
        return calc_pc28_payout(picks, unit, draw["final_result"])
    if kind in ("mark6", "combo"):
        return calc_mark6_payout(picks, unit, draw)
    return 0.0


def clicker_settle_enabled() -> bool:
    """双进程：结算链在左机 spawn 内执行，不经右机 settlement 线程。"""
    if EDGE_LEFT_JS:
        return False
    return CLICKER_SETTLE_ENABLED and CLICKER_SEND_IMAGES


def should_run_settlement(bot: dict | None, serial: str) -> bool:
    """按 BOT_CLICKER_SETTLE 决定结算线程挂在左机还是右机。"""
    on_clicker = is_clicker_bot(bot) or is_clicker_serial(serial, bot)
    if clicker_settle_enabled():
        return on_clicker
    return not on_clicker


def clicker_announce_enabled() -> bool:
    return CLICKER_SEND_ANNOUNCE


def runs_announce_loop(bot: dict | None) -> bool:
    if not bot:
        return False
    if clicker_announce_enabled():
        return is_clicker_bot(bot)
    return is_send_bot(bot)


def announce_serial_skipped(bot: dict, serial: str) -> bool:
    """公告线程：本机是否应跳过（休眠）。"""
    if clicker_announce_enabled():
        return not (is_clicker_bot(bot) or is_clicker_serial(serial, bot))
    return is_clicker_bot(bot) or is_clicker_serial(serial, bot)


def outbound_uses_queue(bot: dict) -> bool:
    if not SEND_QUEUE_ENABLED:
        return False
    if is_send_bot(bot):
        return True
    return clicker_announce_enabled() and is_clicker_bot(bot)


def resolve_open_announce_target(settings: dict[str, str] | None = None) -> tuple[str, dict]:
    """三图后「新的一局」目标 serial/bot（左机公告模式走 CLICKER）。"""
    if clicker_announce_enabled():
        from bot_ops.runtime import load_bot_runtime

        _ = settings
        rt = load_bot_runtime()
        cp = (rt.clicker_adb_port or _CLICKER_ADB_PORT).strip()
        clicker_bot: dict = {"id": next(iter(CLICKER_BOT_IDS), "bot-3"), "associatedGroup": ""}
        try:
            bots = api("GET", "/api/bots") or []
            for bid in CLICKER_BOT_IDS:
                hit = next((x for x in bots if str(x.get("id") or "") == bid), None)
                if hit:
                    clicker_bot = dict(hit)
                    break
        except Exception:
            pass
        if cp:
            for host in (f"localhost:{cp}", f"127.0.0.1:{cp}"):
                resolved = resolve_serial_optional(host, label="clicker-open-announce")
                if resolved:
                    return resolved, clicker_bot
            return f"localhost:{cp}", clicker_bot
        return "", clicker_bot
    return resolve_listener_settle_target(settings)


def resolve_listener_settle_target(settings: dict[str, str] | None = None) -> tuple[str, dict]:
    """左机结算完成后，右机 open_after_settle 目标（跨进程 capture-ipc done，非左机公告模式）。"""
    from bot_ops.runtime import load_bot_runtime

    _ = settings
    rt = load_bot_runtime()
    lp = (rt.listener_adb_port or _LISTENER_ADB_PORT).strip()
    listener_bot: dict = {"id": BOT_LISTENER_ID, "associatedGroup": ""}
    try:
        bots = api("GET", "/api/bots") or []
        hit = next((x for x in bots if str(x.get("id") or "") == BOT_LISTENER_ID), None)
        if hit:
            listener_bot = dict(hit)
    except Exception:
        pass
    if lp:
        for host in (f"localhost:{lp}", f"127.0.0.1:{lp}"):
            resolved = resolve_serial_optional(host, label="listener-open-announce")
            if resolved:
                return resolved, listener_bot
        return f"localhost:{lp}", listener_bot
    return "", listener_bot


def find_panel_user(users: list[dict], bot_id: str, bet: dict) -> dict | None:
    cc = str(bet.get("customer_code") or "")
    uname = str(bet.get("username") or "")
    for u in users:
        if not user_in_bot_scope(u, bot_id):
            continue
        if cc and str(u.get("customerCode") or "") == cc:
            return dict(u)
        if uname and str(u.get("username") or "") == uname:
            return dict(u)
    return None


def settle_round(
    round_id: int,
    draw: dict,
    bot: dict,
    users: list[dict],
    settings: dict[str, str],
    serial: str,
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
) -> None:
    global _SETTLED_ROUNDS, _PAYOUT_DONE_ROUNDS, _SETTLE_SEND_ATTEMPT, _SETTLE_DISPATCHED
    if round_id in _SETTLED_ROUNDS or round_id in _CAPTURE_SUCCEEDED:
        return
    try:
        from bot_ops.capture_ipc import capture_done_for_rid, capture_in_progress_for_rid

        if capture_done_for_rid(round_id):
            return
        if capture_in_progress_for_rid(round_id):
            return
    except Exception:
        pass
    if round_id in _SETTLE_DISPATCHED:
        try:
            from bot_ops.capture_ipc import capture_done_for_rid, capture_in_progress_for_rid

            if capture_in_progress_for_rid(round_id) or capture_done_for_rid(round_id):
                return
            _SETTLE_DISPATCHED.discard(round_id)
        except Exception:
            return
    now = time.time()
    last_try = _SETTLE_SEND_ATTEMPT.get(round_id, 0.0)
    if now - last_try < SETTLE_SEND_RETRY_SEC:
        return
    _SETTLE_SEND_ATTEMPT[round_id] = now
    bets = list(_ROUND_POOL.get(str(round_id), []))
    settle_bot_id = (
        BOT_LISTENER_ID
        if clicker_settle_enabled() and (is_clicker_bot(bot) or is_clicker_serial(serial, bot))
        else bot["id"]
    )
    user_payouts: dict[str, float] = defaultdict(float)
    winner_lines: list[str] = []
    if round_id not in _PAYOUT_DONE_ROUNDS:
        for bet in bets:
            if str(bet.get("bot_id") or settle_bot_id) != settle_bot_id:
                continue
            payout = calc_bet_payout(bet, draw)
            if payout <= 0:
                continue
            uname = str(bet.get("username") or "")
            user_payouts[uname] = min(
                user_payouts.get(uname, 0.0) + payout,
                float(LIMIT_ROUND_PAYOUT),
            )
            winner_lines.append(f"{uname} +{int(payout)} ({bet.get('cmd', '')[:30]})")
        for uname, payout in user_payouts.items():
            u = next(
                (x for x in users if user_in_bot_scope(x, settle_bot_id) and str(x.get("username") or "") == uname),
                None,
            )
            if not u:
                continue
            u = dict(u)
            new_bal = float(u.get("balance", 0)) + payout
            u["balance"] = new_bal
            u["lastActive"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_user(u)
            record_bill(
                settle_bot_id, uname, "中奖",
                payout, new_bal,
                f"{round_id}期 {draw['n1']}+{draw['n2']}+{draw['n3']}={draw['final_result']}",
                str(u.get("customerCode") or ""),
            )
        _PAYOUT_DONE_ROUNDS.add(round_id)
        _ROUND_POOL.pop(str(round_id), None)
        save_round_bets_persisted()
    log.info("结算 rid=%s %s+%s+%s=%s 中奖%d人", round_id, draw["n1"], draw["n2"], draw["n3"], draw["final_result"], len(user_payouts))
    next_rid, _, _ = active_round_timing(settings)
    open_rid = max(next_rid, round_id + 1)
    open_text = build_open_announce_text(open_rid, settings)
    group = (bot.get("associatedGroup") or "").strip()
    capture_paths: list[str] = []
    try:
        capture_paths = generate_settle_capture_paths(round_id, draw)
    except Exception as ex:
        log.warning("结算截图生成失败 rid=%s: %s", round_id, ex)

    if clicker_settle_enabled() and (is_clicker_bot(bot) or is_clicker_serial(serial, bot)):
        ls, lb = resolve_open_announce_target(settings)
        if not ls:
            log.warning("左机结算：公告目标机不可用 rid=%s", round_id)
            return
        open_job = OutboundSend(
            ls, lb, open_text, settings,
            input_xy=input_xy, send_xy=send_xy,
            prio=SEND_PRIO_OPEN_AFTER_SETTLE, kind="open_after_settle", round_id=open_rid,
            group_ok=True,
        )
        from bot_ops.capture_ipc import mark_capture_done, outbound_to_dict

        if not capture_paths:
            mark_capture_done(round_id, images_ok=True, open_job=outbound_to_dict(open_job))
            _SETTLE_DISPATCHED.add(round_id)
            post_log(f"[ADB] 结算 rid={round_id} 无截图 → 新一局", "SUCCESS")
            return
        snap = ui_snapshot(serial, chat=True, channel="settle")
        ix = snap.input_xy
        sy = snap.inbar_send or snap.keyboard_send
        outbound_enqueue(
            OutboundSend(
                serial, bot, "", settings,
                input_xy=ix, send_xy=sy,
                prio=SEND_PRIO_CAPTURE, kind="capture_batch", round_id=round_id,
                image_paths=list(capture_paths), group_ok=True,
            )
        )
        with _CLICKER_SETTLE_OPEN_LOCK:
            _CLICKER_SETTLE_OPEN_BY_RID[round_id] = outbound_to_dict(open_job)
        _SETTLE_DISPATCHED.add(round_id)
        log.info(
            "左机内结算 rid=%s paths=%d → 本进程发图",
            round_id, len(capture_paths),
        )
        post_log(f"[ADB] 结算队列 rid={round_id} 截图{len(capture_paths)}张（左机内）", "SUCCESS")
        return

    listener_queued = SEND_QUEUE_ENABLED and is_send_bot(bot)

    def _image_outbound_serial_bot() -> tuple[str, dict]:
        """结算截图：委派左机 CLICKER；禁止回落右机 LISTENER。"""
        from bot_ops.runtime import load_bot_runtime

        rt = load_bot_runtime()
        hit = _clicker_image_target()
        if hit:
            cs, cb = hit
            if _adb_port_from_serial(cs) == rt.clicker_adb_port:
                return cs, cb
        if CLICKER_SEND_IMAGES:
            cp = rt.clicker_adb_port
            if cp and cp != rt.listener_adb_port:
                cb = bot
                try:
                    bots = api("GET", "/api/bots") or []
                    for bid in CLICKER_BOT_IDS:
                        b = next((x for x in bots if str(x.get("id")) == bid), None)
                        if b:
                            cb = b
                            break
                except Exception:
                    pass
                for host in (f"localhost:{cp}", f"127.0.0.1:{cp}"):
                    resolved = resolve_serial_optional(host, label="clicker-settle")
                    if resolved:
                        return resolved, cb
            log.warning("左机发图不可用，本批截图跳过（右机仅发文字公告）")
            return "", bot
        return serial, bot

    open_job = OutboundSend(
        serial, bot, open_text, settings,
        input_xy=input_xy, send_xy=send_xy,
        prio=SEND_PRIO_OPEN_AFTER_SETTLE, kind="open_after_settle", round_id=open_rid,
        group_ok=True,
    )

    def _enqueue_open_now() -> None:
        outbound_enqueue(open_job)
        log.info("结算入队新的一局 rid=%s → 展示期 %s", round_id, next_rid)

    if listener_queued:
        img_serial, img_bot = _image_outbound_serial_bot()
        if capture_paths and img_serial:
            try:
                from bot_ops.capture_ipc import (
                    enqueue_capture_ipc,
                    needs_capture_ipc,
                    outbound_to_dict,
                )

                if needs_capture_ipc(img_serial, serial):
                    if not enqueue_capture_ipc({
                        "round_id": round_id,
                        "image_paths": list(capture_paths),
                        "clicker_serial": img_serial,
                        "open_job": outbound_to_dict(open_job),
                        "gallery_preloaded": False,
                    }):
                        from bot_ops.capture_ipc import (
                            capture_terminal_for_rid,
                            has_inflight_for_rid,
                            has_pending_for_rid,
                        )

                        if capture_terminal_for_rid(round_id):
                            return
                        if has_pending_for_rid(round_id) or has_inflight_for_rid(round_id):
                            return
                        log.info("结算 IPC 推迟 rid=%s（左机队列忙）", round_id)
                        return
                    log.info(
                        "结算 IPC 左机发图 rid=%s serial=%s %s",
                        round_id, img_serial,
                        ", ".join(os.path.basename(p) for p in capture_paths),
                    )
                    try:
                        ot = str(draw.get("opentime") or "")
                        if ot:
                            lag_s = (beijing_now() - parse_beijing_dt(ot)).total_seconds()
                            log.info(
                                "结算时序 rid=%s opentime=%s api_lag=%.1fs",
                                round_id, ot, lag_s,
                            )
                    except Exception:
                        pass
                else:
                    outbound_enqueue(
                        OutboundSend(
                            img_serial, img_bot, "", settings,
                            input_xy=input_xy, send_xy=send_xy,
                            prio=SEND_PRIO_CAPTURE, kind="capture_batch", round_id=round_id,
                            image_paths=list(capture_paths), group_ok=True,
                        )
                    )
                    stash_open_after_capture(round_id, open_job)
                    log.info(
                        "结算入队批量截图 rid=%s serial=%s（同进程）",
                        round_id, img_serial,
                    )
            except Exception as ex:
                log.warning("capture-ipc 失败 rid=%s: %s", round_id, ex)
                outbound_enqueue(
                    OutboundSend(
                        img_serial, img_bot, "", settings,
                        input_xy=input_xy, send_xy=send_xy,
                        prio=SEND_PRIO_CAPTURE, kind="capture_batch", round_id=round_id,
                        image_paths=list(capture_paths), group_ok=True,
                    )
                )
                stash_open_after_capture(round_id, open_job)
            _SETTLE_DISPATCHED.add(round_id)
        else:
            if capture_paths and not img_serial:
                log.warning("结算截图未入队 rid=%s（左机 offline），直接发新的一局", round_id)
            _enqueue_open_now()
            _SETTLE_DISPATCHED.add(round_id)
        post_log(f"[ADB] 结算队列 rid={round_id} 截图{len(capture_paths)}张", "SUCCESS")
        return

    ok_all = True
    if capture_paths:
        img_serial, img_bot = _image_outbound_serial_bot()
        img_serial = img_serial or serial
        if not send_chat_images_batch(
            img_serial, img_bot if img_serial != serial else bot,
            capture_paths, input_xy, send_xy, settings, group_ok=True,
        ):
            log.warning("批量截图发送失败 rid=%s", round_id)
            ok_all = False
    if not send_chat_reply(serial, bot, open_text, input_xy, send_xy, settings, skip_fast=True, group_ok=True):
        log.warning("新的一局发送失败 rid=%s (结算后)", next_rid)
        return
    _SETTLED_ROUNDS.add(round_id)
    save_settled_rounds_persisted()
    if group:
        _ROUND_OPEN_ANNOUNCED[group] = next_rid
        save_round_open_announced_persisted()
    if ok_all:
        post_log(f"[ADB] 结算 rid={round_id} 截图{len(capture_paths)}张+新的一局", "SUCCESS")
    post_log(f"[ADB] 结算 rid={round_id} 中奖{len(user_payouts)}人", "SUCCESS")


def process_round_settlement(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    users: list[dict],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    *,
    data: dict | None = None,
    force_draw: bool = False,
) -> None:
    """28.run 出新结果 → 左机三图 → 右机「新的一局」（固定顺序，禁止 +10s 开局）。"""
    global _LAST_SEEN_DRAWN_RID
    if not SETTLE_ENABLED or in_maintenance_window():
        return
    if not should_run_settlement(bot, serial):
        return
    if data is None:
        data = fetch_28run_recent(force=force_draw)
        if not force_draw:
            last = latest_drawn_round_id(data)
            if last and last != _LAST_SEEN_DRAWN_RID:
                _LAST_SEEN_DRAWN_RID = last
                data = fetch_28run_recent(force=True)
    rid, _, _ = active_round_timing(settings)
    pending = pending_settle_round_id(rid, data)
    if pending:
        draw = find_draw_for_round(pending, data)
        if draw:
            settle_round(pending, draw, bot, users, settings, serial, input_xy, send_xy)


def execute_bet_order(
    order: BetOrder,
    user: dict,
    bot: dict,
    username: str,
    cc: str,
    settings: dict[str, str],
) -> str:
    rid = order.round_id or current_round_id(settings)
    if maintenance_blocks_bet():
        return user_reply(username, MAINTENANCE_MSG)
    if not is_betting_open(settings):
        return round_user_reply(rid, username, BET_CLOSED_MSG)
    err = validate_bet_order(order, user, bot["id"], settings)
    if err:
        bal = float(user.get("balance", 0))
        return round_user_reply(
            rid, username, order.raw, "(无效,余额不足)", f"当前余额：{bal:.3f}", err,
        )
    bal = float(user["balance"])
    if bal < order.total:
        return round_user_reply(
            rid, username, order.raw, "(无效,余额不足)", f"当前余额：{bal:.3f}",
        )
    order.round_id = rid
    new_bal = bal - order.total
    user["balance"] = new_bal
    user["lastActive"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_user(user)
    record_bill(bot["id"], username, "下注", -order.total, new_bal, order.raw, cc)
    round_stake_add(
        bot["id"], user, rid, order.total,
        order.picks if order.kind in ("mark6", "combo") else None,
    )
    round_bet_append(bot["id"], user, rid, order.raw, order.total, order=order, username=username)
    _PENDING[pending_key(bot["id"], user)] = {
        "amount": order.total,
        "cmd": order.raw,
        "ts": time.time(),
        "round_id": rid,
    }
    picks_show = ".".join(order.picks) if order.kind in ("mark6", "combo") else "".join(order.picks)
    pkg = {"lane": "定位胆", "pc28": "PC28", "mark6": "六合", "combo": "六合", "lottery": order.code}.get(
        order.kind, order.code,
    )
    play_label = (
        f"玩法{order.code}道{pkg}[{picks_show}]"
        if order.kind == "lane"
        else f"玩法{order.code}[{picks_show}]"
    )
    return round_user_reply(
        rid, username, "下单成功", play_label,
        f"下注总额：{order.total:.0f}", f"余额：{new_bal:.0f}",
    )


# 下注规则（BOT_PURCHASE_RULES=0 可关闭）
PURCHASE_RULES_ENABLED = os.environ.get(
    "BOT_PURCHASE_RULES", "1",
).lower() in ("1", "true", "yes")


def is_command(text: str, settings: dict[str, str], products: list[dict], bot_id: str) -> bool:
    t = text.strip()
    if not t or TIME_RE.match(t) or t in IGNORE_TEXT:
        return False
    if is_bot_reply_fragment(t):
        return False
    if "条新消息" in t or "相关聊天记录" in t:
        return False
    if BALANCE_RE.match(t):
        return True
    if TOPUP_RE.match(t) or WITHDRAW_RE.match(t) or BIND_RE.match(t) or CANCEL_RE.match(t):
        return True
    if QUERY_ROUND_BETS_RE.match(t) or QUERY_FLOW_RE.match(t) or QUERY_HISTORY_RE.match(t):
        return True
    if ADD_FINANCE_RE.match(t):
        return True
    if not PURCHASE_RULES_ENABLED:
        return False
    return parse_any_bet(t) is not None or looks_like_bet_attempt(t)


def _adjacent_time(texts: list[str], i: int) -> str | None:
    for j in (i - 1, i + 1):
        if 0 <= j < len(texts) and TIME_RE.match(texts[j].strip()):
            return texts[j].strip()
    return None


def _is_ui_noise_label(t: str) -> bool:
    """过滤标题栏角标、未读数等，避免把「24」当成昵称。"""
    s = (t or "").strip()
    if not s or s in IGNORE_TEXT:
        return True
    if TIME_RE.match(s) or TIME_RE.search(s) or GROUP_TITLE_RE.match(s):
        return True
    if re.fullmatch(r"\d{1,3}", s):
        return True
    if s in ("CSL", "5G", "在线", "离线") or re.fullmatch(r"\d{1,2}:\d{2}", s):
        return True
    if len(s) <= 2 and s.isdigit():
        return True
    if any(x in s for x in UI_SENDER_BLOCK):
        return True
    if "{" in s or "}" in s:
        return True
    if s.startswith("用户：[") or "积分：" in s or "冻结：" in s:
        return True
    if "余额查询" in s or "可用:" in s or "客户:" in s or "交易成功" in s or "交易失败" in s:
        return True
    if "等待" in s or "上庄" in s or "上分" in s or "下分" in s:
        return True
    if s.startswith("发送 ") and "下单" in s:
        return True
    if TOPUP_RE.match(s) or BALANCE_RE.match(s):
        return True
    if ADD_FINANCE_RE.match(s):
        return True
    if "已封盘停止下注" in s or s.startswith("[禁]"):
        return True
    if "距离封盘还有" in s or s.startswith("[钱]"):
        return True
    if "新的一局开始" in s or re.match(r"^【\d+期】", s):
        return True
    if "下一期" in s or s in ("结果", "开奖", "封盘") or s.startswith("最新"):
        return True
    if re.match(r"^\d+期", s) or re.match(r"^第\d+期", s):
        return True
    if s.endswith(":") and len(s) <= 12 and not re.search(r"[\u4e00-\u9fff]{2,}", s.replace(":", "")):
        return True
    if len(s) > 28:
        return True
    return False


def is_plausible_sender(
    nick: str,
    settings: dict[str, str] | None = None,
    products: list[dict] | None = None,
    bot_id: str = "",
) -> bool:
    """聊天消息发送者昵称是否可信（非系统 UI / 键盘 / 日期 / 机器人回复）。"""
    s = (nick or "").strip()
    if not s or _is_ui_noise_label(s):
        return False
    st = settings or DEFAULT_SETTINGS
    if is_command(s, st, products or [], bot_id or "bot-3"):
        return False
    return True


def parse_aliases(user: dict) -> list[str]:
    raw = user.get("nickAliases")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return []


def nickname_pool(users: list[dict], bot_id: str) -> dict[str, list[dict]]:
    """群昵称/历史昵称 → 用户列表（用于识别与重复检测）。"""
    pool: dict[str, list[dict]] = {}
    for u in users:
        if not user_in_bot_scope(u, bot_id):
            continue
        names = [str(u.get("username") or "").strip()]
        names.extend(parse_aliases(u))
        seen: set[str] = set()
        for nick in names:
            if not nick or nick in seen:
                continue
            seen.add(nick)
            pool.setdefault(nick, []).append(u)
    return pool


def user_matches_nick(user: dict, nick: str) -> bool:
    n = (nick or "").strip()
    if not n:
        return False
    if str(user.get("username") or "").strip() == n:
        return True
    return n in parse_aliases(user)


def normalize_customer_code(code: str) -> str:
    c = (code or "").strip().upper()
    if c.startswith("UID-"):
        return c
    if c.startswith("UID"):
        return "UID-" + c[3:].lstrip("-")
    return f"UID-{c}" if c else ""


def find_user_by_code(users: list[dict], bot_id: str, code: str) -> dict | None:
    target = normalize_customer_code(code)
    digits = re.sub(r"\D", "", code or "")
    for u in users:
        if not user_in_bot_scope(u, bot_id):
            continue
        cc = str(u.get("customerCode") or "")
        if cc.upper() == target or cc.upper() == f"UID-{digits}" or cc.replace("UID-", "") == digits:
            return u
    return None


def normalize_messenger_id(mid: str) -> str:
    return (mid or "").strip().lower().lstrip("@")


def find_user_by_messenger_id(users: list[dict], bot_id: str, mid: str) -> dict | None:
    target = normalize_messenger_id(mid)
    if not target:
        return None
    for u in users:
        if not user_in_bot_scope(u, bot_id):
            continue
        if normalize_messenger_id(str(u.get("messengerId") or "")) == target:
            return u
    return None


def invalidate_ui_cache(serial: str) -> None:
    _UI_CACHE.pop(serial, None)
    _SNAP_CACHE.pop(serial, None)
    coll = _UI_COLLECTORS.get(serial)
    if coll is not None:
        with coll._lock:
            coll._root_cache = None
            coll._snap_cache.clear()
    keys = [k for k in _STEP_VERIFY_CACHE if k[0] == serial]
    for k in keys:
        _STEP_VERIFY_CACHE.pop(k, None)


def invalidate_step_verify_cache(serial: str) -> None:
    keys = [k for k in _STEP_VERIFY_CACHE if k[0] == serial]
    for k in keys:
        _STEP_VERIFY_CACHE.pop(k, None)


def _parse_hierarchy_xml(raw: str) -> ET.Element | None:
    if not raw:
        return None
    start = raw.find("<?xml")
    if start < 0:
        start = raw.find("<hierarchy")
    if start < 0:
        return None
    chunk = raw[start:]
    end = chunk.find("</hierarchy>")
    if end >= 0:
        chunk = chunk[: end + len("</hierarchy>")]
    try:
        return ET.fromstring(chunk.strip())
    except ET.ParseError:
        return None


def _get_u2_device(serial: str) -> Any | None:
    if LISTENER_UI_ENGINE == "adb" and is_listener_send_only_serial(serial):
        return None
    if not _HAS_U2 or UI_ENGINE == "adb":
        return None
    dev = _U2_DEVICES.get(serial)
    if dev is not None:
        return dev
    try:
        dev = u2.connect(serial)  # type: ignore[union-attr]
        _U2_DEVICES[serial] = dev
        log.info("uiautomator2 已连接 %s（~200ms/dump）", serial)
        return dev
    except Exception as ex:
        log.warning("uiautomator2 连接失败 %s: %s", serial, ex)
        return None


def u2_fill_input(serial: str, text: str) -> bool:
    """u2 直接填输入框，不依赖坐标。"""
    if is_listener_send_only_serial(serial) and LISTENER_SEND_TAP_ONLY:
        log.info("右机禁止 u2 点输入框")
        return False
    dev = _get_u2_device(serial)
    if dev is None:
        return False
    try:
        et = dev(className="android.widget.EditText")
        if not et.exists(timeout=1.5):
            return False
        et.click()
        w(0.15, 0.06)
        try:
            et.clear_text()
        except Exception:
            pass
        et.set_text(text)
        w(0.25, 0.1)
        invalidate_ui_cache(serial)
        return True
    except Exception as ex:
        log.warning("u2 填字失败: %s", ex)
        _U2_DEVICES.pop(serial, None)
        return False


def u2_click_send(serial: str) -> bool:
    if is_listener_send_only_serial(serial) and LISTENER_SEND_TAP_ONLY:
        log.info("右机禁止 u2 扫描点击，请用钉死发送键")
        return False
    dev = _get_u2_device(serial)
    if dev is None:
        return False
    try:
        for sel in (
            dev(text="发送"),
            dev(description="发送"),
            dev(textMatches="(?i)send"),
            dev(resourceIdMatches="(?i).*send.*"),
            dev(resourceIdMatches="(?i).*imageViewAudio.*"),
        ):
            if sel.exists(timeout=0.5):
                sel.click()
                w(0.35, 0.15)
                invalidate_ui_cache(serial)
                return True
    except Exception as ex:
        log.warning("u2 点发送失败: %s", ex)
        _U2_DEVICES.pop(serial, None)
    return False


def u2_scrape_messenger_id(serial: str) -> str | None:
    """u2 直接抓资料页 @ID，比全量 dump 更快。"""
    dev = _get_u2_device(serial)
    if dev is None:
        return None
    try:
        for sel in (
            dev(textMatches=r"@[a-z0-9]{6,16}"),
            dev(descriptionMatches=r"@[a-z0-9]{6,16}"),
        ):
            if sel.exists(timeout=0.6):
                raw = (sel.get_text() or sel.info.get("contentDescription") or "").strip()
                cand = raw.lstrip("@").lower()
                if MESSENGER_ID_RE.match(cand):
                    return cand
    except Exception:
        _U2_DEVICES.pop(serial, None)
    return None


def load_mid_cache() -> None:
    global _MID_CACHE
    try:
        if not os.path.isfile(MID_CACHE_FILE):
            return
        raw = json.load(open(MID_CACHE_FILE, encoding="utf-8"))
        now = time.time()
        for k, v in raw.items():
            if isinstance(v, list) and len(v) >= 2 and now < float(v[1]):
                _MID_CACHE[k] = (str(v[0]), float(v[1]))
        if _MID_CACHE:
            log.info("ID 缓存加载 %d 条", len(_MID_CACHE))
    except Exception as ex:
        log.warning("ID 缓存加载失败: %s", ex)


def save_mid_cache() -> None:
    global _MID_DIRTY
    if not _MID_DIRTY:
        return
    try:
        os.makedirs(os.path.dirname(MID_CACHE_FILE) or ".", exist_ok=True)
        payload = {k: [v[0], v[1]] for k, v in _MID_CACHE.items() if time.time() < v[1]}
        json.dump(payload, open(MID_CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        _MID_DIRTY = False
    except Exception as ex:
        log.warning("ID 缓存保存失败: %s", ex)


_PREWARM_LAST: dict[str, float] = {}
_PREWARM_QUEUE: dict[str, deque[str]] = {}
PREWARM_IDLE_SEC = max(15, int(os.environ.get("BOT_PREWARM_IDLE_SEC", "20") or 20))
PREWARM_BATCH_MAX = max(2, int(os.environ.get("BOT_PREWARM_BATCH_MAX", "5") or 5))
PREWARM_ENABLED = os.environ.get("BOT_PREWARM", "0").lower() in ("1", "true", "yes")
_MID_DIRTY = False


def reply_cooldown_key(bot_id: str, sender: str, cmd: str) -> str:
    return f"{bot_id}|{(sender or '').strip().lower()}|{normalize_cmd_key(cmd)}"


def cmd_spatial_key(cmd: str, sender: str, cmd_y: int) -> tuple[str, str, int]:
    """同屏同发送者同指令按 Y 分桶，防止坐标漂移重复触发。"""
    return (
        (cmd or "").strip(),
        (sender or "").strip().lower(),
        max(0, int(cmd_y)) // CMD_Y_BUCKET,
    )


def cmd_baseline_key(cmd: str, sender: str, cmd_y: int) -> tuple[str, str, int]:
    """启动基线：仅精确坐标，避免整桶屏蔽后续新消息（如重复扣1）。"""
    return (
        (cmd or "").strip(),
        (sender or "").strip().lower(),
        max(0, int(cmd_y)),
    )


def record_handled_cmd_y(store: dict[tuple[str, str], int], cmd: str, sender: str, cmd_y: int) -> None:
    key = ((cmd or "").strip(), (sender or "").strip().lower())
    if not key[0] or not key[1] or cmd_y <= 0:
        return
    store[key] = max(store.get(key, 0), int(cmd_y))


def is_rescan_command(
    cmd: str,
    sender: str,
    cmd_y: int,
    handled_y: dict[tuple[str, str], int],
    baseline: set[tuple[str, str, int]],
) -> bool:
    """非下注：同屏 OCR 重扫同气泡 → 跳过。下注不走此逻辑。"""
    snd = (sender or "").strip()
    c = (cmd or "").strip()
    if cmd_y <= 0 or not snd or not c:
        return True
    if is_bet_command(c):
        return False
    key = (c, snd.lower())
    last_y = handled_y.get(key, 0)
    if last_y:
        # 底部新消息 Y 明显更大 → 用户再次发送，应回复
        if cmd_y > last_y + CMD_SAME_SCREEN_Y_PX:
            return False
        # 同屏第二条或 OCR 抖动 / 上滑重扫
        if cmd_y > last_y + 10:
            return True
        if cmd_y <= last_y + CMD_Y_RESCAN_MARGIN or cmd_y < last_y - CMD_Y_RESCAN_MARGIN:
            return True
    return (c, snd.lower(), cmd_y) in baseline


def is_incoming_message_node(node: ChatTextNode, sw: int) -> bool:
    """群聊他人消息在左侧；右侧多为本机/机器人发出，不应当作新指令。"""
    width = sw or 720
    return node.cx <= int(width * INCOMING_X_RATIO)


def is_bot_reply_fragment(text: str) -> bool:
    """机器人已发回复/公告片段，不得再当作用户指令。"""
    t = (text or "").strip()
    if not t:
        return True
    if re.search(r"用户[：:]\[", t):
        return True
    if any(x in t for x in (
        "未登记", "请联系群主", "积分：", "冻结：", "下单成功", "已封盘",
        "新的一局", "已发送请求", "绑定成功", "绑定失败", "添加失败",
        "停机维护", "指令格式错误", "取消成功", "取消失败", "28.run",
    )):
        return True
    if t.startswith("[禁]") or t.startswith("[钱]") or t.startswith("【"):
        return True
    return False


def in_reply_cooldown(bot_id: str, sender: str, cmd: str) -> bool:
    until = _REPLY_COOLDOWN.get(reply_cooldown_key(bot_id, sender, cmd), 0)
    return time.time() < until


def set_reply_cooldown(bot_id: str, sender: str, cmd: str) -> None:
    sec = command_dedup_window(cmd)
    _REPLY_COOLDOWN[reply_cooldown_key(bot_id, sender, cmd)] = time.time() + sec


def mark_cmds_seen(
    seen: set[str],
    msgs: list[tuple[str, ...]],
    cmd: str,
    sender: str,
    hint: str = "",
) -> None:
    """同发送者+同指令的全部可见消息标记已处理（防止 ID 漂移重复回）。"""
    c = cmd.strip()
    sl = (sender or hint or "").strip().lower()
    for row in msgs:
        mid, c2, s2 = row[0], row[1], row[2]
        if c2.strip() != c:
            continue
        if (s2 or hint or "").strip().lower() == sl:
            seen.add(mid)


def fair_queue_pending(
    pending: list[tuple[str, str, str, int, int]],
    hint: str = "",
) -> list[tuple[str, str, str, int, int]]:
    """同屏同人同文（非下注）只留最新一条；下注全接；添加优先。"""
    latest: dict[tuple[str, str], tuple[str, str, str, int, int]] = {}
    bets: list[tuple[str, str, str, int, int]] = []
    for mid, cmd, sender, idx, cmd_y in pending:
        snd = (sender or hint or "").strip().lower()
        c = cmd.strip()
        row = (mid, cmd, sender or snd, idx, cmd_y)
        if is_bet_command(c):
            bets.append(row)
            continue
        key = (c, snd)
        prev = latest.get(key)
        if prev is None or idx >= prev[3]:
            latest[key] = row
    ordered = sorted(latest.values(), key=lambda x: x[3])
    priority = [x for x in ordered if ADD_FINANCE_RE.match(x[1].strip())]
    normal = [x for x in ordered if not ADD_FINANCE_RE.match(x[1].strip())]
    return priority + normal + sorted(bets, key=lambda x: x[3])


def panel_nicks_for_bot(users: list[dict], bot_id: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for u in users:
        if not user_in_bot_scope(u, bot_id):
            continue
        nick = str(u.get("username") or "").strip()
        if nick and nick not in seen:
            seen.add(nick)
            out.append(nick)
    return out


def schedule_batch_prewarm(
    serial: str,
    bot_id: str,
    users: list[dict],
    texts: list[str],
) -> None:
    """仅预缓存当前屏内可见的面板用户（不离开群聊乱点）。"""
    if not PREWARM_ENABLED:
        return
    panel = panel_nicks_for_bot(users, bot_id)
    if not panel:
        return
    text_set = {t.strip() for t in texts}
    visible = [n for n in panel if n in text_set and is_plausible_sender(n)]
    if not visible:
        return
    q: deque[str] = deque()
    for nick in visible[:PREWARM_BATCH_MAX]:
        if mid_cache_get(serial, nick, users, bot_id):
            continue
        q.append(nick)
    if q:
        _PREWARM_QUEUE[serial] = q
        log.info("屏内预缓存 %d 人: %s", len(q), ", ".join(list(q)[:5]))


def batch_prewarm_step(
    serial: str,
    bot_id: str,
    users: list[dict],
    bot: dict | None = None,
) -> None:
    """空闲时每次 tick 预读 1 人 ID（不阻塞消息回复）。"""
    if not PREWARM_ENABLED:
        return
    if bot and not in_target_group_chat(ui_hierarchy(serial), bot, serial):
        return
    now = time.time()
    if now - _PREWARM_LAST.get(serial, 0) < PREWARM_IDLE_SEC:
        return
    q = _PREWARM_QUEUE.get(serial)
    if not q:
        return
    while q:
        nick = q.popleft()
        if not is_plausible_sender(nick):
            continue
        if mid_cache_get(serial, nick, users, bot_id):
            continue
        read_messenger_id_for_nick(serial, nick, users, bot_id, bot=bot)
        if bot:
            ensure_group_chat(serial, bot)
        _PREWARM_LAST[serial] = now
        log.info("屏内预缓存 ← %s (剩 %d)", nick, len(q))
        return
    _PREWARM_QUEUE.pop(serial, None)


def post_log(msg: str, typ: str = "INFO") -> None:
    if not POST_PANEL_LOG:
        return
    try:
        _LOG_QUEUE.put_nowait((msg, typ))
    except Exception:
        pass


def store_mid_cache(serial: str, nick: str, mid: str, bot_id: str | None = None) -> None:
    global _MID_DIRTY
    nick_key = (nick or "").strip().lower()
    if not nick_key or not mid:
        return
    cache_key = f"{serial}|{nick_key}"
    exp = time.time() + MID_CACHE_TTL
    _MID_CACHE[cache_key] = (mid, exp)
    if bot_id:
        _MID_CACHE[f"g|{bot_id}|{nick_key}"] = (mid, exp)
    _MID_DIRTY = True


def _global_mid_cache_get(bot_id: str, nick: str) -> str | None:
    key = f"g|{bot_id}|{(nick or '').strip().lower()}"
    cached = _MID_CACHE.get(key)
    if not cached or time.time() >= cached[1]:
        return None
    return cached[0]


def _validate_cached_mid(mid: str, nick: str, users: list[dict] | None, bot_id: str | None) -> bool:
    if not users or not bot_id:
        return True
    row = panel_user_by_nick(users, bot_id, nick)
    if row:
        panel_mid = normalize_messenger_id(str(row.get("messengerId") or ""))
        if panel_mid and panel_mid != normalize_messenger_id(mid):
            return False
    return find_user_by_messenger_id(users, bot_id, mid) is not None


def panel_user_by_nick(users: list[dict], bot_id: str, nick: str) -> dict | None:
    n = (nick or "").strip()
    if not n:
        return None
    pool = nickname_pool(users, bot_id)
    owners = pool.get(n, [])
    if len(owners) == 1:
        return owners[0]
    if len(owners) > 1:
        codes = ", ".join(str(u.get("customerCode") or u.get("id")) for u in owners)
        log.warning("昵称重复「%s」，涉及编号 %s，禁止仅按昵称认人", n, codes)
        return None
    return None


def mid_cache_get(
    serial: str,
    nick: str,
    users: list[dict] | None,
    bot_id: str | None,
) -> str | None:
    """缓存命中：优先全局 nick→ID（跨 Listener/Clicker），再按 serial。"""
    if bot_id:
        gmid = _global_mid_cache_get(bot_id, nick)
        if gmid and _validate_cached_mid(gmid, nick, users, bot_id):
            return gmid
        if gmid:
            _MID_CACHE.pop(f"g|{bot_id}|{(nick or '').strip().lower()}", None)
    cache_key = f"{serial}|{(nick or '').strip().lower()}"
    cached = _MID_CACHE.get(cache_key)
    if not cached or time.time() >= cached[1]:
        return None
    mid = cached[0]
    if not _validate_cached_mid(mid, nick, users, bot_id):
        _MID_CACHE.pop(cache_key, None)
        return None
    if bot_id:
        store_mid_cache(serial, nick, mid, bot_id)
    return mid


def _ui_hierarchy_u2(serial: str) -> ET.Element | None:
    dev = _get_u2_device(serial)
    if dev is None:
        return None
    try:
        xml = dev.dump_hierarchy(compressed=True)
        return _parse_hierarchy_xml(xml if isinstance(xml, str) else str(xml))
    except Exception as ex:
        log.warning("u2 dump 失败，重连: %s", ex)
        _U2_DEVICES.pop(serial, None)
        return None


def _ui_hierarchy_adb(serial: str) -> ET.Element | None:
    cmd = ["adb", "-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=10)
        raw = (out.stdout or b"").decode("utf-8", "replace")
        root = _parse_hierarchy_xml(raw)
        if root is not None:
            return root
    except Exception:
        pass
    adb_run(serial, "shell", "uiautomator", "dump", "/data/local/tmp/window_dump.xml")
    raw = adb_run(serial, "shell", "cat", "/data/local/tmp/window_dump.xml")
    return _parse_hierarchy_xml(raw)


def ui_engine_for_serial(serial: str) -> str:
    """右机 LISTENER 只用 adb shell uiautomator dump，不连 u2.jar / 不装 uiautomator App。"""
    if is_listener_send_only_serial(serial):
        return LISTENER_UI_ENGINE if LISTENER_UI_ENGINE in ("adb", "u2", "auto") else "adb"
    return UI_ENGINE


def _ui_hierarchy_impl(serial: str, *, force: bool = False) -> ET.Element | None:
    with _UI_SERIAL_LOCKS[serial]:
        now = time.time()
        if not force:
            cached = _UI_CACHE.get(serial)
            if cached and now - cached[0] < UI_CACHE_TTL:
                return cached[1]
        root: ET.Element | None = None
        engine = ui_engine_for_serial(serial)
        if engine in ("auto", "u2"):
            root = _ui_hierarchy_u2(serial)
        if root is None:
            root = _ui_hierarchy_adb(serial)
        _UI_CACHE[serial] = (now, root)
        return root


def ui_hierarchy(serial: str, *, force: bool = False, channel: str = "default") -> ET.Element | None:
    """读屏 dump：启用收集器时走资源 1 队列，仅 ui-collect 线程直调 impl。"""
    if threading.current_thread().name.startswith("ui-collect-"):
        return _ui_hierarchy_impl(serial, force=force)
    if UI_COLLECTOR_ENABLED:
        return _ui_collector_root(serial, force=force, channel=channel)
    return _ui_hierarchy_impl(serial, force=force)


def scrape_messenger_id(root: ET.Element | None) -> str | None:
    """资料页读取 @bz38if3dx9 或 ID号。"""
    if root is None:
        return None
    for node in root.iter("node"):
        for raw in (node.attrib.get("text") or "", node.attrib.get("content-desc") or ""):
            v = raw.strip()
            if not v:
                continue
            if v.startswith("@"):
                cand = v.lstrip("@").lower()
                if MESSENGER_ID_RE.match(cand):
                    return cand
            if MESSENGER_ID_RE.match(v.lstrip("@").lower()):
                return v.lstrip("@").lower()
    texts: list[str] = []
    for node in root.iter("node"):
        t = node_label(node)
        if t:
            texts.append(t.strip())
    for i, t in enumerate(texts):
        if ("ID" in t and "号" in t) or t in ("ID号", "ID"):
            for j in range(i + 1, min(i + 4, len(texts))):
                cand = texts[j].strip().lstrip("@")
                if MESSENGER_ID_RE.match(cand):
                    return cand.lower()
    for t in texts:
        if t.startswith("@") and MESSENGER_ID_RE.match(t[1:]):
            return t[1:].lower()
    return None


@dataclass
class ChatTextNode:
    text: str
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def cx(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2


@dataclass
class ScreenContext:
    page: str
    title: str
    target_group: str
    in_input: bool

    def summary(self) -> str:
        return f"页面={self.page} 标题={self.title!r} 目标群={self.target_group!r}"


def collect_chat_text_nodes(root: ET.Element | None) -> list[ChatTextNode]:
    """聊天区域内文字节点，按 Y 从上到下排序（定位发送者/指令用）。"""
    if root is None:
        return []
    sh = screen_height(root)
    top, bottom = chat_message_y_bounds(root, sh=sh)
    out: list[ChatTextNode] = []
    seen: set[tuple[str, int, int]] = set()
    for node in root.iter("node"):
        t = node_label(node).strip()
        if not t or t in IGNORE_TEXT or len(t) > 220:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < top or cy > bottom:
            continue
        key = (t, cy // 8, x1 // 12)
        if key in seen:
            continue
        seen.add(key)
        out.append(ChatTextNode(t, x1, y1, x2, y2))
    out.sort(key=lambda n: (n.y1, n.x1))
    return out


def get_chat_title(root: ET.Element | None) -> str:
    headers = chat_header_texts(root)
    for h in headers:
        if h and not is_system_chat_title(h) and h not in IGNORE_TEXT and not TIME_RE.match(h.strip()):
            return h
    for h in headers:
        if h and not is_system_chat_title(h) and h not in IGNORE_TEXT:
            return h
    return headers[0] if headers else ""


def describe_screen_context(root: ET.Element | None, bot: dict, serial: str = "") -> ScreenContext:
    group = (bot.get("associatedGroup") or "").strip()
    title = get_chat_title(root)
    texts = collect_ui_texts(root) if root is not None else []
    in_input = any(t == "输入消息" or t == "Enter message" for t in texts)
    if is_group_settings_page(root):
        page = "group_settings"
    elif is_search_page(root, serial):
        page = "search"
    elif is_target_group_surface(root, bot, serial) or in_target_group_chat(root, bot, serial):
        page = "target_group"
    elif is_secret_key_page(root):
        page = "secret_key"
    elif any(t in MESSAGES_TAB_LABELS for t in texts):
        page = "message_list"
    elif is_in_app_webview(root):
        page = "webview"
    elif in_group_chat(root, bot, serial):
        page = "wrong_chat"
    elif any(label_matches(t, ADD_FRIEND_LABELS) for t in texts) or any(
        t == "通过验证" for t in texts
    ):
        page = "profile"
    else:
        page = "other"
    return ScreenContext(page, title, group, in_input)


def spatial_sender_for_command(
    nodes: list[ChatTextNode],
    cmd: ChatTextNode,
    pool: dict[str, list[dict]],
    settings: dict[str, str],
    products: list[dict],
    bot_id: str,
) -> str:
    """按屏幕坐标：指令正上方、左侧消息区内的昵称。"""
    if not nodes:
        return ""
    sw = max((n.x2 for n in nodes), default=720)
    left_max = int(sw * 0.58)
    above = [
        n for n in nodes
        if n.y2 <= cmd.y1 - 4 and cmd.y1 - n.y2 <= 280
    ]
    above.sort(key=lambda n: n.y1, reverse=True)
    fallback = ""
    for n in above:
        if is_command(n.text, settings, products, bot_id):
            break
        if not is_plausible_sender(n.text, settings, products, bot_id):
            continue
        if n.text in pool and len(pool[n.text]) == 1:
            log.debug("坐标认人 %s ← 指令 %s @y=%d (nick_y=%d)", n.text, cmd.text, cmd.y1, n.y1)
            return n.text
        if n.text in pool and len(pool[n.text]) > 1:
            log.warning("坐标认人跳过重复昵称「%s」cmd=%s", n.text, cmd.text)
            continue
        if n.cx <= left_max and not fallback:
            fallback = n.text
    if fallback:
        log.debug("坐标认人(未登记) %s ← 指令 %s @y=%d", fallback, cmd.text, cmd.y1)
    return fallback


def _effective_near_y(near_y: int | None) -> int | None:
    if near_y is None or near_y < 100:
        return None
    return near_y


def scroll_chat_toward_bottom(serial: str, steps: int = 2) -> None:
    """群聊内上滑，尽量露出最新消息（Listener/Clicker 均可用，不离开群聊）。"""
    root = ui_hierarchy(serial)
    if root is None:
        return
    sw, sh = screen_width(root), screen_height(root)
    x, y1, y2 = sw // 2, int(sh * 0.62), int(sh * 0.38)
    for _ in range(max(1, steps)):
        subprocess.run(
            ["adb", "-s", serial, "shell", "input", "swipe", str(x), str(y1), str(x), str(y2), "280"],
            capture_output=True,
            timeout=8,
        )
        w(0.35, 0.12)
    invalidate_ui_cache(serial)


def listener_refresh_chat_view(serial: str, *, reason: str = "") -> None:
    """右机读指令前滚到底，避免气泡在屏外或懒加载未展开。"""
    listener_hide_keyboard(serial, reason=f"before-read-{reason or 'scroll'}")
    now = time.time()
    if now - _LISTENER_LAST_CHAT_SCROLL.get(serial, 0.0) < LISTENER_CHAT_SCROLL_SEC:
        return
    _LISTENER_LAST_CHAT_SCROLL[serial] = now
    tag = f" ({reason})" if reason else ""
    scroll_chat_toward_bottom(serial, 1)
    w(0.15, 0.06)
    invalidate_ui_cache(serial)
    _SNAP_CACHE.pop(serial, None)
    log.info("右机群聊滚底重读%s serial=%s", tag, serial)


def chat_scan_needs_scroll(snap: "UiSnapshot") -> bool:
    """存在未读占位或完全读不到聊天节点时，需要滚底/点未读。"""
    if snap.root is not None and _find_unread_placeholder(snap.root):
        return True
    for t in snap.texts:
        if "未读" in t or t in ("<未读>", "未读"):
            return True
    return len(snap.chat_nodes) == 0


def _find_unread_placeholder(root: ET.Element) -> tuple[int, int] | None:
    """左侧「未读」占位气泡中心坐标（短消息未展开时无正文）。"""
    sh = screen_height(root)
    top, bottom = chat_message_y_bounds(root, sh=sh)
    sw = screen_width(root)
    best: tuple[int, int, int] | None = None
    for node in root.iter("node"):
        label = node_label(node).strip()
        if label not in ("<未读>", "未读") and "未读" not in label:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        cx = (x1 + x2) // 2
        if cy < top or cy > bottom or cx > int(sw * INCOMING_X_RATIO):
            continue
        if best is None or cy > best[2]:
            best = (cx, cy, cy)
    return (best[0], best[1]) if best else None


def expand_unread_chat_messages(serial: str, root: ET.Element | None) -> bool:
    """点击未读占位，让 itel 等设备把短消息正文暴露到无障碍树。"""
    if root is None:
        return False
    tapped = False
    while True:
        pt = _find_unread_placeholder(root)
        if not pt:
            break
        cx, cy = pt
        log.info("点击未读占位 (%d,%d) 展开消息", cx, cy)
        adb_tap_raw(serial, cx, cy)
        tapped = True
        w(0.35, 0.12)
        invalidate_ui_cache(serial)
        _SNAP_CACHE.pop(serial, None)
        root = ui_hierarchy(serial, force=True)
    return tapped


def find_add_finance_y_for_nick(
    serial: str,
    bot: dict,
    nick: str,
    users: list | None = None,
    products: list | None = None,
    settings: dict[str, str] | None = None,
) -> int | None:
    """在本机群聊 UI 中定位指定用户最近一条「添加」指令的 Y（不用右机坐标）。"""
    target = (nick or "").strip()
    if not target:
        return None
    st = settings or DEFAULT_SETTINGS
    prods = products or []
    for attempt in range(3):
        snap = ui_snapshot(serial)
        if not in_target_group_chat(snap.root, bot, serial):
            return None
        msgs = chat_message_ids(
            snap.chat_nodes, snap.texts, st, prods, bot.get("id") or "", users or [],
        )
        hits = [
            cmd_y for _mid, cmd, sender, _idx, cmd_y in msgs
            if ADD_FINANCE_RE.match(cmd.strip())
            and (sender or "").strip().lower() == target.lower()
            and cmd_y > 0
        ]
        if hits:
            y = max(hits)
            log.info("本机定位添加指令 y=%s nick=%s attempt=%s", y, target, attempt + 1)
            return y
        if attempt < 2:
            scroll_chat_toward_bottom(serial, 1)
    return None


def resolve_add_near_y(
    serial: str,
    bot: dict,
    nick: str,
    near_y: int | None,
    users: list | None = None,
    products: list | None = None,
    settings: dict[str, str] | None = None,
) -> int | None:
    """Clicker 仅使用本机群聊扫描到的 Y；Listener 可用传入 near_y。"""
    local = find_add_finance_y_for_nick(serial, bot, nick, users, products, settings)
    if local:
        return local
    if is_clicker_bot(bot):
        log.warning("Clicker 本机未找到 %s 的「添加」指令，忽略右机 y=%s", nick, near_y)
        return None
    return _effective_near_y(near_y)


def find_tap_for_nick(
    root: ET.Element,
    nick: str,
    near_y: int | None = None,
) -> tuple[int, int] | None:
    """群聊内点击发送者昵称；near_y 为指令行 Y，避免误点其他区域。"""
    target = nick.strip()
    if not target:
        return None
    near_y = _effective_near_y(near_y)
    sw = screen_width(root)
    sh = screen_height(root)
    chat_top, chat_bottom = chat_message_y_bounds(root, sh=sh)
    left_max = int(sw * 0.58)
    hits: list[tuple[int, int, int, bool, int]] = []
    for node in root.iter("node"):
        label = node_label(node).strip()
        if label != target:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < chat_top or cy > chat_bottom:
            continue
        if near_y is not None and (cy >= near_y - 4 or near_y - y2 > 280):
            continue
        cx = (x1 + x2) // 2
        clickable = node.attrib.get("clickable") == "true"
        dy = (near_y - cy) if near_y is not None else 0
        left_bonus = 0 if cx <= left_max else 1
        hits.append((left_bonus, dy, y1, cx, cy, clickable, x1))
    if not hits:
        log.warning("未找到昵称「%s」可点击区域 (near_y=%s)", target, near_y)
        return None
    hits.sort(key=lambda h: (h[0], h[1], -h[2]))
    _, _, _, cx, cy, clickable, x1 = hits[0]
    if not clickable and x1 > 80:
        tap_x = max(48, x1 - 40)
        log.info("定位点头像 (%d,%d) nick=%s near_y=%s", tap_x, cy, target, near_y)
        return (tap_x, cy)
    log.info("定位点昵称 (%d,%d) nick=%s near_y=%s", cx, cy, target, near_y)
    return (cx, cy)


def find_tap_avatar_for_sender(
    root: ET.Element,
    nick: str,
    near_y: int | None = None,
) -> tuple[int, int] | None:
    """群聊内点发送者头像（优先头像区域，非昵称文字）。"""
    target = nick.strip()
    if not target:
        return None
    near_y = _effective_near_y(near_y)
    sw = screen_width(root)
    sh = screen_height(root)
    chat_top, chat_bottom = chat_message_y_bounds(root, sh=sh)
    avatar_max_x = int(sw * 0.28)
    best_img: tuple[int, int, int] | None = None
    for node in root.iter("node"):
        cls = node.attrib.get("class", "")
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        cx = (x1 + x2) // 2
        if cy < chat_top or cy > chat_bottom or cx > avatar_max_x:
            continue
        if near_y is not None and abs(cy - near_y) > 160 and near_y - y2 > 240:
            continue
        bw, bh = x2 - x1, y2 - y1
        if ("Image" in cls or node.attrib.get("clickable") == "true") and 28 <= bw <= 120 and 28 <= bh <= 120:
            dy = abs(cy - near_y) if near_y else 0
            key = (dy, -bw)
            if best_img is None or key < (best_img[0], -best_img[1]):
                best_img = (dy, cx, cy)
    if best_img:
        log.info("定位头像 (%d,%d) nick=%s near_y=%s", best_img[1], best_img[2], target, near_y)
        return (best_img[1], best_img[2])
    pt = find_tap_for_nick(root, target, near_y)
    if pt and pt[0] <= avatar_max_x + 40:
        return pt
    return None


def u2_tap_nick(serial: str, nick: str, near_y: int | None = None) -> bool:
    dev = _get_u2_device(serial)
    if dev is None:
        return False
    try:
        sw = 720
        root = ui_hierarchy(serial)
        if root is not None:
            sw = screen_width(root)
        near_y = _effective_near_y(near_y)
        sel = dev(text=nick)
        if not sel.exists(timeout=0.8):
            return False
        best = None
        best_key = (9999, 9999)
        for item in sel:
            info = item.info
            b = info.get("bounds") or {}
            if not b:
                continue
            cy = (b.get("top", 0) + b.get("bottom", 0)) // 2
            cx = (b.get("left", 0) + b.get("right", 0)) // 2
            if cy < 120 or cy > CHAT_INPUT_Y_MAX:
                continue
            if near_y is not None and (cy >= near_y - 4 or near_y - b.get("bottom", cy) > 280):
                continue
            key = (0 if cx <= sw * 0.58 else 1, abs(near_y - cy) if near_y else 0)
            if key < best_key:
                best_key = key
                best = item
        if best is not None:
            best.click()
            w(0.35, 0.12)
            invalidate_ui_cache(serial)
            log.info("u2 定位点昵称 %s near_y=%s", nick, near_y)
            return True
    except Exception as ex:
        log.warning("u2 点昵称失败: %s", ex)
        _U2_DEVICES.pop(serial, None)
    return False


def node_tap_center(node: ET.Element) -> tuple[int, int] | None:
    b = parse_bounds(node.attrib.get("bounds", ""))
    if not b:
        return None
    x1, y1, x2, y2 = b
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def label_matches(label: str, candidates: tuple[str, ...], *, exact: bool = False) -> bool:
    t = (label or "").strip()
    if not t:
        return False
    if exact:
        low = t.lower()
        return t in candidates or low in {c.lower() for c in candidates}
    low = t.lower()
    for c in candidates:
        if t == c or c in t or c.lower() in low:
            return True
    return False


def collect_ui_texts(root: ET.Element | None) -> list[str]:
    if root is None:
        return []
    out: list[str] = []
    for node in root.iter("node"):
        t = node_label(node)
        if t:
            out.append(t.strip())
    return out


def chat_header_texts(root: ET.Element | None) -> list[str]:
    """聊天页顶部标题区文字（用于判断当前是否在目标群）。"""
    if root is None:
        return []
    sh = screen_height(root)
    max_y = int(sh * 0.17)
    out: list[str] = []
    for node in root.iter("node"):
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[1] > max_y:
            continue
        t = node_label(node).strip()
        if t and len(t) <= 48:
            out.append(t)
    return out


def is_system_chat_title(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if t in IGNORE_TEXT:
        return True
    return any(b in t for b in SYSTEM_CHAT_BLOCK)


def _chat_surface_open(root: ET.Element | None, serial: str = "") -> bool:
    """群聊界面：输入框占位符可见，或键盘已弹出且当前为群聊 Activity。"""
    if root is None:
        return bool(serial and is_group_chat_activity(serial))
    texts = collect_ui_texts(root)
    if any(t == "输入消息" or t == "Enter message" for t in texts):
        return True
    return bool(serial and is_group_chat_activity(serial))


def in_group_chat(root: ET.Element | None, bot: dict, serial: str = "") -> bool:
    """是否在任意聊天页（含输入框或群聊 Activity）。"""
    return _chat_surface_open(root, serial)


def title_band_texts(root: ET.Element | None) -> list[str]:
    """标题栏区域文字（排除状态栏运营商角标）。"""
    if root is None:
        return []
    sh = screen_height(root)
    min_y = int(sh * 0.04)
    max_y = int(sh * 0.14)
    out: list[str] = []
    for node in root.iter("node"):
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        y1, y2 = b[1], b[3]
        cy = (y1 + y2) // 2
        if cy < min_y or cy > max_y:
            continue
        t = node_label(node).strip()
        if not t or t in IGNORE_TEXT or is_system_chat_title(t):
            continue
        out.append(t)
    return out


def _group_title_matches(title: str, group: str) -> bool:
    from bot_ops.nav_guard import matches_group_header

    return matches_group_header(title, group)


def is_target_group_surface(root: ET.Element | None, bot: dict, serial: str = "") -> bool:
    """群聊页硬特征：抬头群名(人数)+输入框（W49）。已在群内，禁止回群导航。"""
    from bot_ops.nav_guard import is_target_group_surface as _surface

    if root is None:
        return bool(serial and is_group_chat_activity(serial))
    group = (bot.get("associatedGroup") or "").strip()
    return _surface(
        collect_ui_texts(root),
        chat_header_texts(root) + title_band_texts(root),
        configured_group=group,
    )


def in_target_group_chat(root: ET.Element | None, bot: dict, serial: str = "") -> bool:
    """是否在当前 bot 配置的目标群聊内（禁止 V03 等系统频道）。"""
    if is_target_group_surface(root, bot, serial):
        return True
    group = (bot.get("associatedGroup") or "").strip()
    if root is None:
        if serial and is_group_chat_activity(serial):
            return True
        return False
    if serial and is_group_chat_activity(serial):
        title = get_chat_title(root)
        if not group or _group_title_matches(title, group):
            return True
    if not _chat_surface_open(root, serial):
        return False
    header = [h for h in chat_header_texts(root) if h and h not in IGNORE_TEXT]
    if any(is_system_chat_title(h) for h in header):
        if group and any(_group_title_matches(h, group) for h in header):
            return True
        return False
    if not group:
        return any(GROUP_TITLE_RE.match(t) for t in header)
    title = get_chat_title(root)
    if _group_title_matches(title, group):
        return True
    title_band = title_band_texts(root)
    for h in header + title_band:
        if _group_title_matches(h, group):
            return True
    sh = screen_height(root)
    top_max = int(sh * 0.22)
    for node in root.iter("node"):
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[1] > top_max:
            continue
        t = node_label(node).strip()
        if not t or t in IGNORE_TEXT or is_system_chat_title(t):
            continue
        if _group_title_matches(t, group):
            return True
    for t in collect_ui_texts(root):
        if _group_title_matches(t, group):
            return True
    if serial and is_group_chat_activity(serial):
        return True
    return False


def find_group_chat_entry(root: ET.Element, group: str) -> tuple[int, int] | None:
    """消息列表里点目标群（避开 V03 等系统会话）。"""
    group = (group or "").strip()
    if not group or root is None:
        return None
    hits: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        t = node_label(node).strip()
        if not t or is_system_chat_title(t):
            continue
        if t != group and group not in t:
            continue
        if t != group and len(t) > max(len(group) + 8, 28):
            continue
        if t != group and not GROUP_TITLE_RE.match(t):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < SEARCH_BAR_Y_MAX + 20 or cy > 1500:
            continue
        exact = 1 if t == group else 0
        hits.append((exact, y1, (x1 + x2) // 2, cy))
    if not hits:
        return None
    hits.sort(key=lambda h: (-h[0], h[1]))
    return (hits[0][2], hits[0][3])


def dismiss_message_list_overlay(serial: str) -> bool:
    """消息列表转发/分享提示层会挡住会话列表，点「消息」Tab 刷新。"""
    root = ui_hierarchy(serial)
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if not any("最近转发" in t or "快速分享" in t for t in texts):
        return False
    log.info("消息列表有转发提示层，点「消息」Tab 刷新")
    tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
    w(0.7, 0.3)
    invalidate_ui_cache(serial)
    return True


def is_in_app_webview(root: ET.Element | None) -> bool:
    """55M 内打开的开奖网/外链页（28.run 等），会导致回群失败。"""
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if any(t == "输入消息" or t == "Enter message" for t in texts):
        return False
    if any("System Tools" in t or "文件夹" in t for t in texts):
        return False
    from bot_ops.nav_guard import is_message_list_surface

    headers = chat_header_texts(root)
    if is_message_list_surface(texts, headers):
        return False
    if any(t in MESSAGES_TAB_LABELS for t in texts):
        return False
    joined = " ".join(texts)
    low = joined.lower()
    if "luck h5" in low or "luckh5" in low:
        return True
    if "加拿大28" in joined or "加拿大 28" in joined:
        return True
    if "28.run" in low or "pc28.am" in low:
        return True
    if "开奖网" in joined or "专业彩票" in joined:
        return True
    if "V03 HK" in joined or "v03 hk" in low:
        return True
    if ("http://" in low or "https://" in low) and not any(t in MESSAGES_TAB_LABELS for t in texts):
        return True
    for el in root.iter("node"):
        cls = el.attrib.get("class", "") or ""
        if "WebView" in cls or "webkit" in cls.lower():
            # 群聊 Activity 内常有 WebView 组件，不能单凭 class 判外链
            return False
    return False


def listener_in_group_for_send(root: ET.Element | None, bot: dict, serial: str) -> bool:
    """右机可否发公告/回复：已在目标群聊页，非消息列表/桌面。"""
    if is_target_group_surface(root, bot, serial):
        if root is not None and (
            is_secret_key_page(root)
            or is_search_page(root, serial)
            or is_group_settings_page(root)
        ):
            return False
        return True
    if listener_send_blocked(root, serial):
        return False
    if serial and is_group_chat_activity(serial):
        return True
    if in_target_group_chat(root, bot, serial):
        return True
    return False


def dismiss_listener_blockers(serial: str, root: ET.Element | None = None) -> bool:
    """右机关闭密钥/搜索等遮挡（需 BOT_ALLOW_LISTENER_NAV 或临时开启）。"""
    prev = os.environ.get("BOT_ALLOW_LISTENER_NAV")
    os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
    changed = False
    try:
        root = root or ui_hierarchy(serial)
        if is_secret_key_page(root):
            changed = dismiss_secret_key_page(serial) or changed
            root = ui_hierarchy(serial)
        if is_search_page(root, serial):
            changed = dismiss_search_page(serial) or changed
            root = ui_hierarchy(serial)
        if is_group_settings_page(root):
            listener_system_back(serial, reason="退出群设置")
            changed = True
        elif is_in_app_webview(root) and not is_group_chat_activity(serial):
            changed = dismiss_in_app_webview(serial, max_steps=2) or changed
    finally:
        if prev is None:
            os.environ.pop("BOT_ALLOW_LISTENER_NAV", None)
        else:
            os.environ["BOT_ALLOW_LISTENER_NAV"] = prev
    invalidate_ui_cache(serial)
    return changed


def is_group_settings_page(root: ET.Element | None) -> bool:
    """群资料/设置页（误点标题栏进入）：禁止 Tab/通讯录导航。"""
    if root is None:
        return False
    texts = collect_ui_texts(root)
    markers = ("群成员", "删除并退出", "群别名", "群简介", "清空聊天记录")
    hits = sum(1 for m in markers if any(m in t for t in texts))
    return hits >= 2


def listener_system_back(serial: str, *, reason: str = "") -> None:
    """右机恢复专用：仅 Android 返回，不用左上角坐标（易误触标题进设置）。"""
    root = ui_hierarchy(serial)
    if root is not None and ui_shows_exit_app_warning(root):
        log.warning("右机禁止 Back（再按一次将退出 55M），改按 Home 保活")
        android_home(serial, reason=reason or "退出程序提示")
        return
    if reason:
        log.info("右机系统返回：%s", reason)
    try:
        adb_run(serial, "shell", "input", "keyevent", "4")
    except Exception:
        pass
    w(0.55, 0.2)
    invalidate_ui_cache(serial)


def ui_shows_exit_app_warning(root: ET.Element | None) -> bool:
    from bot_ops.nav_guard import ui_texts_show_exit_warning

    if root is None:
        return False
    return ui_texts_show_exit_warning(collect_ui_texts(root))


def android_home(serial: str, *, reason: str = "") -> None:
    """回桌面保活：VMOS 底部黑条中间圆点 = KEYCODE_HOME，禁止杀 55M 进程。"""
    if reason:
        log.info("按 Home 回桌面（保活）：%s", reason)
    try:
        adb_run(serial, "shell", "input", "keyevent", "3")
    except Exception:
        pass
    w(0.45, 0.15)
    invalidate_ui_cache(serial)


def bring_messenger_foreground(serial: str) -> bool:
    """温启动 55M：REORDER_TO_FRONT，避免冷启动触发升级弹窗。"""
    if is_55m_foreground(serial):
        return True
    pkg = resolve_messenger_pkg(serial)
    if not pkg:
        return False
    try:
        adb_run(
            serial,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "-p",
            pkg,
            "-f",
            "0x20000",
        )
        w(1.2, 0.4)
        dismiss_upgrade_popup(serial)
        ok = is_55m_foreground(serial) or in_messenger_app(ui_hierarchy(serial), serial)
        if ok:
            _MESSENGER_PKG_CACHE[serial] = pkg
            log.info("温启动前台 %s", pkg)
        return ok
    except Exception:
        return False


def recover_listener_to_group_minimal(serial: str, bot: dict, *, max_steps: int = 6) -> bool:
    """右机离群时最小恢复：零导航模式下仅系统 Back，禁止 Tab/群名点击。"""
    group = (bot.get("associatedGroup") or "").strip()
    dismiss_upgrade_popup(serial)
    dismiss_navigation_drawer(serial)
    if not is_55m_foreground(serial):
        launch_messenger_app(serial)
        if not is_55m_foreground(serial) and not in_messenger_app(ui_hierarchy(serial), serial):
            force_restart_messenger(serial, reason="拉起失败大退重进")
    if is_send_only_listener(bot) and LISTENER_ZERO_NAV:
        prev = os.environ.get("BOT_ALLOW_LISTENER_NAV")
        os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
        try:
            if listener_in_group_for_send(ui_hierarchy(serial), bot, serial):
                return True
            # 零导航：禁止连按 Back（会退到桌面/文件管理），只拉起 55M + 点群
            launch_messenger_app(serial)
            w(1.2, 0.4)
            tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
            w(0.7, 0.25)
            if group:
                tap_target_group_in_list(serial, bot, scrolls=5)
                w(1.0, 0.35)
            return listener_in_group_for_send(ui_hierarchy(serial), bot, serial)
        finally:
            if prev is None:
                os.environ.pop("BOT_ALLOW_LISTENER_NAV", None)
            else:
                os.environ["BOT_ALLOW_LISTENER_NAV"] = prev
    tab_tried = False
    prev = os.environ.get("BOT_ALLOW_LISTENER_NAV")
    os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
    try:
        for step in range(max_steps):
            root = ui_hierarchy(serial)
            if ui_shows_exit_app_warning(root):
                log.warning("检测到「再按一次退出」，禁止 Back，直接点群")
                if group and tap_target_group_in_list(serial, bot, scrolls=2):
                    w(0.8, 0.3)
                    continue
                android_home(serial, reason="取消退出程序提示")
                bring_messenger_foreground(serial)
                w(0.8, 0.3)
                continue
            if in_target_group_chat(root, bot, serial):
                log.info("右机已在目标群 %s", group or "?")
                return True
            if is_group_settings_page(root):
                log.warning("右机误进群设置页，系统返回 step=%d", step + 1)
                listener_system_back(serial, reason="退出群设置")
                continue
            if is_in_app_webview(root):
                log.warning("右机误开内嵌网页，关闭 step=%d", step + 1)
                if dismiss_in_app_webview(serial, max_steps=2):
                    continue
                listener_system_back(serial, reason="退出网页")
                continue
            if is_search_page(root, serial) or is_secret_key_page(root):
                listener_system_back(serial, reason="退出搜索/密钥页")
                continue
            ctx = describe_screen_context(root, bot, serial)
            if ctx.page == "wrong_chat":
                listener_system_back(serial, reason="退出错误会话")
                continue
            if ctx.page == "message_list" and group:
                if tap_target_group_in_list(serial, bot, scrolls=3):
                    w(0.8, 0.3)
                    continue
                scroll_message_list(serial, "up")
                w(0.5, 0.2)
                continue
            if not tab_tried:
                tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
                tab_tried = True
                w(0.7, 0.25)
                continue
            if group and tap_target_group_in_list(serial, bot, scrolls=1):
                w(0.8, 0.3)
                continue
            android_home(serial, reason="兜底回桌面保活")
            bring_messenger_foreground(serial)
            w(0.8, 0.3)
        return in_target_group_chat(ui_hierarchy(serial), bot, serial)
    finally:
        if prev is None:
            os.environ.pop("BOT_ALLOW_LISTENER_NAV", None)
        else:
            os.environ["BOT_ALLOW_LISTENER_NAV"] = prev


def tap_webview_done(serial: str) -> bool:
    """内嵌开奖页左上角「完成」。"""
    root = ui_hierarchy(serial)
    if root is None:
        return False
    sh = screen_height(root)
    max_y = int(sh * 0.18)
    for node in root.iter("node"):
        label = (node.attrib.get("text") or "").strip()
        if label not in ("完成", "Done", "关闭", "Close"):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        cy = (b[1] + b[3]) // 2
        if cy > max_y:
            continue
        cx = (b[0] + b[2]) // 2
        log.info("点开奖页 [%s] (%d,%d)", label, cx, cy)
        adb_run(serial, "shell", "input", "tap", str(cx), str(cy))
        invalidate_ui_cache(serial)
        w(0.35, 0.12)
        return True
    return False


def dismiss_in_app_webview(serial: str, *, max_steps: int = 4) -> bool:
    """从内嵌网页退回 55M（误点公告里的 28.run 链接时）。"""
    if not is_55m_foreground(serial):
        log.warning("跳过关外链：55M 不在前台 serial=%s", serial)
        return False
    if MANUAL_IN_GROUP:
        root = ui_hierarchy(serial)
        if not is_in_app_webview(root):
            return False
        if tap_webview_done(serial):
            return True
        log.warning("BOT_MANUAL_IN_GROUP=1 禁止 Back 关外链，已尝试「完成」")
        return False
    prev = os.environ.get("BOT_ALLOW_LISTENER_NAV")
    os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
    closed = False
    try:
        for step in range(max_steps):
            root = ui_hierarchy(serial)
            if not is_in_app_webview(root):
                if closed:
                    log.info("已退出内嵌网页")
                    invalidate_ui_cache(serial)
                return closed
            log.warning("检测到内嵌网页(28.run 等)，系统返回 step=%d", step + 1)
            listener_system_back(serial, reason="关闭开奖外链")
            closed = True
        return closed
    finally:
        if prev is None:
            os.environ.pop("BOT_ALLOW_LISTENER_NAV", None)
        else:
            os.environ["BOT_ALLOW_LISTENER_NAV"] = prev


def scroll_message_list(serial: str, direction: str = "up") -> None:
    """消息列表滑动：up=内容上移，露出下方会话。"""
    if block_listener_navigation(serial, "消息列表滑动"):
        return
    root = ui_hierarchy(serial)
    if root is None:
        return
    sw, sh = screen_width(root), screen_height(root)
    x = sw // 2
    if direction == "up":
        y1, y2 = int(sh * 0.72), int(sh * 0.32)
    else:
        y1, y2 = int(sh * 0.32), int(sh * 0.72)
    adb_run(serial, "shell", "input", "swipe", str(x), str(y1), str(x), str(y2), "300")
    w(0.4, 0.15)
    invalidate_ui_cache(serial)


def tap_target_group_in_list(serial: str, bot: dict, *, scrolls: int = 5) -> bool:
    """在消息/群聊列表中点目标群，必要时滑动查找。"""
    group = (bot.get("associatedGroup") or "").strip()
    if not group:
        return False
    dismiss_message_list_overlay(serial)
    for i in range(scrolls + 1):
        root = ui_hierarchy(serial)
        if root is None:
            continue
        pt = find_group_chat_entry(root, group)
        if not pt:
            pt = find_tap_contains(root, group, min_y=80, max_y=1500)
        if pt:
            adb_tap(serial, pt[0], pt[1])
            w(1.0, 0.45)
            if in_target_group_chat(ui_hierarchy(serial), bot, serial):
                log.info("列表已进入目标群 %s", group)
                return True
            log.warning("点击 %s 后仍未进入目标群，重试", group)
        if i < scrolls:
            scroll_message_list(serial, "up")
    return False


def find_tap_for_labels(
    root: ET.Element,
    labels: tuple[str, ...],
    *,
    min_y: int = 0,
    max_y: int = 9999,
    bottom_tab: bool = False,
    exact: bool = False,
    max_label_len: int = 12,
) -> tuple[int, int] | None:
    hits: list[tuple[int, int, int, bool]] = []
    for node in root.iter("node"):
        label = node_label(node)
        if not label_matches(label, labels, exact=exact):
            continue
        if exact and len(label.strip()) > max_label_len:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < min_y or cy > max_y:
            continue
        if bottom_tab and y1 < 1500:
            continue
        clickable = node.attrib.get("clickable") == "true"
        hits.append((y1 if bottom_tab else y1, (x1 + x2) // 2, cy, clickable))
    if not hits:
        return None
    hits.sort(key=lambda h: (not h[3], h[0]))
    return (hits[0][1], hits[0][2])


def find_tap_contains(root: ET.Element, needle: str, min_y: int = 100, max_y: int = 1600) -> tuple[int, int] | None:
    needle = (needle or "").strip()
    if not needle:
        return None
    hits: list[tuple[int, int, int]] = []
    for node in root.iter("node"):
        t = node_label(node)
        if needle not in t:
            continue
        if len(t) > max(len(needle) + 8, 28):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < min_y or cy > max_y:
            continue
        hits.append((y1, (x1 + x2) // 2, cy))
    if not hits:
        return None
    hits.sort(key=lambda h: h[0])
    return (hits[0][1], hits[0][2])


def screen_height(root: ET.Element) -> int:
    max_y = 0
    for node in root.iter("node"):
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b:
            max_y = max(max_y, b[3])
    return max_y or 1920


def screen_width(root: ET.Element) -> int:
    max_x = 0
    for node in root.iter("node"):
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b:
            max_x = max(max_x, b[2])
    return max_x or 1080


def tap_bottom_tab_index(serial: str, index: int, total: int = 4) -> bool:
    """55M 底部 Tab 有时无文字，按序号点：0消息 1通讯录 2通话 3我"""
    if block_listener_navigation(serial, f"底部Tab[{index}]"):
        return False
    root = ui_hierarchy(serial)
    if root is None:
        return False
    sw, sh = screen_width(root), screen_height(root)
    safe_max = app_safe_max_y(root)
    x = int(sw * (index + 0.5) / total)
    y = min(int(sh * 0.915), safe_max - 12)
    y = max(int(sh * 0.82), y)
    log.info("底部 Tab[%d] @ (%d,%d) screen=%dx%d safe_max=%d", index, x, y, sw, sh, safe_max)
    adb_run(serial, "shell", "input", "tap", str(x), str(y))
    w(1.0, 0.4)
    return True


def tap_bottom_tab(serial: str, labels: tuple[str, ...]) -> bool:
    if block_listener_navigation(serial, f"底部Tab{labels}"):
        return False
    root = ui_hierarchy(serial)
    if root is None:
        return False
    safe_max = app_safe_max_y(root)
    cutoff = int(screen_height(root) * 0.78)
    hits: list[tuple[int, int, int, bool]] = []
    for node in root.iter("node"):
        label = node_label(node)
        if not label_matches(label, labels):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if y1 < cutoff or cy > safe_max:
            continue
        clickable = node.attrib.get("clickable") == "true"
        hits.append((y1, (x1 + x2) // 2, cy, clickable))
    if hits:
        hits.sort(key=lambda h: (not h[3], h[0]))
        adb_tap(serial, hits[0][1], hits[0][2])
        w(1.0, 0.4)
        return True
    # 坐标兜底：通讯录=1，消息=0
    if label_matches("通讯录", labels) or label_matches("联系人", labels):
        return tap_bottom_tab_index(serial, 1)
    if label_matches("消息", labels):
        return tap_bottom_tab_index(serial, 0)
    log.warning("未找到底部 Tab %s", labels)
    return False


def app_safe_max_y(root: ET.Element | None) -> int:
    sh = screen_height(root) if root is not None else 1280
    return max(900, sh - NAV_BAR_RESERVE_PX)


def adb_tap_raw(serial: str, x: int, y: int, *, invalidate: bool = True, purpose: str = "") -> None:
    """输入框/发送键等固定 UI 坐标，不做导航栏上移。"""
    if clicker_forbidden_tap(serial, x, y, purpose):
        log.info("左机发图禁止点击 @(%d,%d) purpose=%s", x, y, purpose or "other")
        return
    if listener_forbidden_tap(serial, x, y, purpose):
        log.info("右机禁止点击 @(%d,%d) purpose=%s", x, y, purpose or "other")
        return
    adb_run(serial, "shell", "input", "tap", str(int(x)), str(int(y)))
    if invalidate:
        invalidate_ui_cache(serial)


def adb_tap_listener_send(serial: str, bot: dict | None, x: int, y: int) -> None:
    """右机唯一允许的坐标点击：钉死的发送键（内联栏蓝钮 / 键盘纸飞机）。"""
    if listener_forbidden_tap(serial, x, y, "pinned-send"):
        log.info("右机禁止点击(非钉死发送) @(%d,%d)，已跳过", x, y)
        return
    if not listener_may_tap(serial, bot, "pinned-send"):
        log.info("右机禁止点击(策略) @(%d,%d)，已跳过", x, y)
        return
    adb_run(serial, "shell", "input", "tap", str(int(x)), str(int(y)))
    invalidate_ui_cache(serial)


def fire_listener_send_key(serial: str) -> str:
    """右机 LISTENER：默认禁止 IME Enter，只允许点钉死发送键。"""
    if LISTENER_SEND_TAP_ONLY and is_listener_send_only_serial(serial):
        return "tap-only-blocked"
    if LISTENER_SEND_ENTER_FIRST or LISTENER_PURE_PIPE:
        adb_run(serial, "shell", "am", "broadcast", "-a", "ADB_KEYBOARD_SMART_ENTER")
        return "IME-SMART_ENTER"
    return "tap-skipped"


def slow_send_should_yield() -> bool:
    """仅用户指令插队，认人回复/公告结算不走让路。"""
    return outbound_pending_cmd_jobs() > 0


def _coord_valid(x: int, y: int, max_y: int, max_x: int = 2000) -> bool:
    return 20 <= x <= max_x and 120 <= y <= max_y


def _chat_input_defaults(snap: UiSnapshot | None = None) -> tuple[int, int, int]:
    """(input_x, input_y, safe_max_y) 按屏幕尺寸估算。"""
    sh = 1280
    sw = 720
    if snap and snap.input_bounds:
        sh = max(sh, snap.input_bounds[3] + 400)
    safe_y = min(CHAT_INPUT_Y_MAX, sh - NAV_BAR_RESERVE_PX - 24)
    input_y = min(DEFAULT_CHAT_INPUT[1], int(sh * 0.57))
    input_x = sw // 2
    return input_x, input_y, safe_y


def resolve_chat_input_xy(
    snap: UiSnapshot,
    settings: dict[str, str] | None,
    bot: dict | None = None,
) -> tuple[int, int]:
    """ADB 键盘弹出时 EditText 常被误识别到底部，回退到安全固定坐标。"""
    ix, iy, safe_y = _chat_input_defaults(snap)
    fx, fy = ix, iy
    if bot:
        bx = bot.get("inputCoordinateX") or bot.get("sendCoordinateX")
        by = bot.get("inputCoordinateY") or bot.get("sendCoordinateY")
        if bx is not None and by is not None:
            cx, cy = int(bx), int(by)
            if _coord_valid(cx, cy, safe_y, max_x=900):
                fx, fy = cx, cy
            else:
                log.warning("面板坐标 (%d,%d) 超出安全区 (max_y=%d)，忽略", cx, cy, safe_y)
    if snap.input_xy:
        x, y = snap.input_xy
        if y <= safe_y:
            return (x, y)
        if _coord_valid(x, iy, safe_y, max_x=900):
            log.info("输入框 Y=%d 异常，保留 X=%d 使用 Y=%d", y, x, iy)
            return (x, iy)
        log.info("输入框 Y=%d 异常，改用固定坐标 (%d,%d)", y, fx, fy)
    if not _coord_valid(fx, fy, safe_y, max_x=900):
        fx, fy = ix, iy
    return (fx, fy)


def effective_input_bounds(
    snap: UiSnapshot,
    settings: dict[str, str] | None,
    bot: dict | None = None,
) -> tuple[int, int, int, int] | None:
    """为发送键定位提供可靠的输入栏行界。"""
    if snap.input_bounds and snap.input_bounds[3] <= CHAT_INPUT_Y_MAX:
        return snap.input_bounds
    ix, iy = resolve_chat_input_xy(snap, settings, bot)
    return (max(0, ix - 220), iy - 28, ix + 220, iy + 28)


def adb_tap(serial: str, x: int, y: int) -> None:
    if block_listener_navigation(serial, f"导航点击@({x},{y})"):
        return
    if serial_role(serial) == "LISTENER" or BOT_ROLE == "LISTENER":
        if listener_forbidden_tap(serial, x, y):
            log.info("LISTENER 角色隔离：禁止 tap @(%d,%d)", x, y)
            return
    if clicker_forbidden_tap(serial, x, y):
        log.info("左机发图禁止点击 @(%d,%d)", x, y)
        return
    if listener_forbidden_tap(serial, x, y):
        log.info("右机禁止点击 @(%d,%d)", x, y)
        return
    root = ui_hierarchy(serial)
    max_y = app_safe_max_y(root)
    if y > max_y:
        log.warning("点击 Y=%d 接近系统导航栏，上移至 %d", y, max_y - 8)
        y = max_y - 8
    adb_run(serial, "shell", "input", "tap", str(x), str(y))
    invalidate_ui_cache(serial)


def tap_header_back(serial: str) -> bool:
    """点 App 左上角返回箭头。禁止用系统 Back 键（会退出软件）。"""
    if block_listener_navigation(serial, "左上角返回"):
        return False
    if is_clicker_serial(serial) and IMG_PINNED:
        pt = pinned_xy("clicker", "add_header_back")
        if pt:
            log.info("左机钉死返回 @ (%d,%d)", pt[0], pt[1])
            adb_run(serial, "shell", "input", "tap", str(pt[0]), str(pt[1]))
            invalidate_ui_cache(serial)
            clicker_w(0.08, 0.35)
            return True
    if dismiss_search_page(serial):
        return True
    root = ui_hierarchy(serial)
    if root is None:
        return False
    sw, sh = screen_width(root), screen_height(root)
    texts = collect_ui_texts(root)
    max_y = int(sh * 0.22)
    max_x = int(sw * 0.30)
    hits: list[tuple[int, int, int, bool, int]] = []
    for node in root.iter("node"):
        label = node_label(node)
        rid = (node.attrib.get("resource-id") or "").lower()
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if cy > max_y or cx > max_x:
            continue
        if label.strip() in ("搜索", "Search") or "search" in rid:
            continue
        is_back = (
            label in ("返回", "Back", "back")
            or "back" in rid
            or (
                node.attrib.get("clickable") == "true"
                and x1 < max_x
                and y2 < max_y
                and (x2 - x1) <= 110
                and (y2 - y1) <= 110
            )
        )
        if not is_back:
            continue
        hits.append((y1, cx, cy, node.attrib.get("clickable") == "true", x1))
    if hits:
        hits.sort(key=lambda h: (not h[3], h[4], h[0]))
        x, y = hits[0][1], hits[0][2]
        log.info("点左上角返回 @ (%d,%d)", x, y)
        adb_run(serial, "shell", "input", "tap", str(x), str(y))
        invalidate_ui_cache(serial)
        w(0.35, 0.12)
        return True
    if any(t in MESSAGES_TAB_LABELS for t in texts) or any(t in CONTACTS_TAB_LABELS for t in texts):
        log.warning("列表页无返回箭头，跳过左上角兜底（防误点搜索）")
        return False
    pt = (max(36, sw // 16), max(64, int(sh * 0.07)))
    log.info("点左上角返回 兜底 @ (%d,%d)", pt[0], pt[1])
    adb_run(serial, "shell", "input", "tap", str(pt[0]), str(pt[1]))
    invalidate_ui_cache(serial)
    w(0.35, 0.12)
    return True


def press_back(serial: str, times: int = 1) -> None:
    """返回：仅点 App 内左上角箭头，不用系统 Back。"""
    for _ in range(times):
        tap_header_back(serial)
        w(0.35, 0.15)


def is_group_chat_activity(serial: str) -> bool:
    """当前 Activity 是否为群聊页（群名常为图片时 UI 文字无法匹配）。"""
    if not serial:
        return False
    now = time.time()
    cached = _GROUP_ACTIVITY_CACHE.get(serial)
    if cached and now - cached[0] < GROUP_ACTIVITY_CACHE_SEC:
        return cached[1]
    ok = False
    try:
        out = adb_run(serial, "shell", "dumpsys", "window", "displays")
        for line in out.splitlines():
            if "mCurrentFocus" not in line:
                continue
            low = line.lower()
            if "groupchatactivity" in low or "group.chat" in low:
                ok = True
                break
            # PopupWindow/IME 浮层盖住群聊时，焦点行不含 GroupChatActivity
            if "popupwindow" in low and "wuwu." in low:
                ok = _resumed_activity_is_group_chat(serial)
                break
    except Exception:
        pass
    _GROUP_ACTIVITY_CACHE[serial] = (now, ok)
    return ok


def _resumed_activity_is_group_chat(serial: str) -> bool:
    try:
        out = adb_run(serial, "shell", "dumpsys", "activity", "activities")
        return "groupchatactivity" in out.lower()
    except Exception:
        return False


def _window_focus_line(serial: str) -> str:
    try:
        out = adb_run(serial, "shell", "dumpsys", "window", "displays")
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line
    except Exception:
        pass
    return ""


def dismiss_clicker_popup_overlay(serial: str) -> bool:
    """收起 PopupWindow/IME 浮层，避免误判离群、点+无效。"""
    if not is_clicker_serial(serial):
        return False
    line = _window_focus_line(serial).lower()
    if "popupwindow" not in line and "inputmethod" not in line:
        return False
    log.info("左机关闭 PopupWindow/IME 浮层")
    for _ in range(2):
        try:
            adb_run(serial, "shell", "input", "keyevent", "111")
        except Exception:
            pass
        w(0.12, 0.06)
    dismiss_soft_keyboard(serial)
    invalidate_ui_cache(serial)
    invalidate_step_verify_cache(serial)
    return True


def dismiss_navigation_drawer(serial: str) -> bool:
    """侧拉抽屉挡住消息列表时关一层（单次 Back，不会触发「再按一次退出」）。"""
    root = ui_hierarchy(serial)
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if not any("侧拉抽屉" in t for t in texts):
        return False
    log.info("关闭侧拉抽屉")
    try:
        adb_run(serial, "shell", "input", "keyevent", "4")
    except Exception:
        pass
    w(0.45, 0.15)
    invalidate_ui_cache(serial)
    return True


def dismiss_upgrade_popup(serial: str) -> bool:
    """升级弹窗（发现新版本）：W49 铁律 — 大退一次马上重进，禁止点「立即升级」。"""
    root = ui_hierarchy(serial, force=True, channel="upgrade-check")
    if not is_upgrade_popup(root):
        return False
    log.info("检测到升级弹窗，大退一次马上重进")
    return force_restart_messenger(serial, reason="绕过升级弹窗")


def is_upgrade_popup(root: ET.Element | None) -> bool:
    from bot_ops.nav_guard import ui_texts_show_upgrade_popup

    if root is None:
        return False
    texts = collect_ui_texts(root)
    if ui_texts_show_upgrade_popup(texts):
        return True
    for node in root.iter("node"):
        rid = node.attrib.get("resource-id", "")
        if "fullPopupContainer" in rid or "tvUploadCommit" in rid:
            return True
    return False


def resolve_messenger_pkg(serial: str) -> str | None:
    cached = _MESSENGER_PKG_CACHE.get(serial)
    if cached:
        return cached
    for line in adb_run(serial, "shell", "pm", "list", "packages").splitlines():
        cand = line.split(":")[-1].strip() if ":" in line else ""
        if cand.startswith("wuwu."):
            return cand
    return None


def _launch_messenger_pkg(serial: str, pkg: str) -> bool:
    """拉起 55M：resolve-activity / monkey（wuwu 包 am start -p 常失败）。"""
    if not pkg:
        return False
    component = ""
    try:
        out = adb_run(serial, "shell", "cmd", "package", "resolve-activity", "--brief", pkg)
        for line in out.splitlines():
            line = line.strip()
            if "/" in line and not line.startswith("priority"):
                component = line
                break
    except Exception:
        component = ""
    if component:
        adb_run(serial, "shell", "am", "start", "-n", component)
        w(2.0, 0.65)
        if is_55m_foreground(serial) or in_messenger_app(ui_hierarchy(serial), serial):
            return True
    adb_run(
        serial, "shell", "monkey", "-p", pkg,
        "-c", "android.intent.category.LAUNCHER", "1",
    )
    w(2.0, 0.65)
    return is_55m_foreground(serial) or in_messenger_app(ui_hierarchy(serial), serial)


def force_restart_messenger(serial: str, *, reason: str = "") -> bool:
    """am force-stop 后立刻 launcher 重进（仅用于升级弹窗等 W49 指定场景）。"""
    pkg = resolve_messenger_pkg(serial)
    if not pkg:
        return False
    if reason:
        log.info("55M 大退重进：%s", reason)
    try:
        adb_run(serial, "shell", "am", "force-stop", pkg)
    except Exception:
        pass
    w(0.4, 0.15)
    ok = _launch_messenger_pkg(serial, pkg)
    _MESSENGER_PKG_CACHE[serial] = pkg
    invalidate_ui_cache(serial)
    root = ui_hierarchy(serial)
    if is_upgrade_popup(root):
        log.warning("大退重进后仍见升级弹窗")
        return False
    if ok:
        log.info("大退重进成功 %s", pkg)
    return ok


def is_55m_foreground(serial: str) -> bool:
    """55M 实际包名为 wuwu.* / telegram.business。"""
    try:
        for sub in ("displays", ""):
            if sub:
                out = adb_run(serial, "shell", "dumpsys", "window", sub)
            else:
                out = adb_run(serial, "shell", "dumpsys", "window")
            for line in out.splitlines():
                if "mCurrentFocus" not in line:
                    continue
                low = line.lower()
                if "wuwu." in low or "telegram.business" in low:
                    return True
    except Exception:
        pass
    return False


def in_messenger_app(root: ET.Element | None, serial: str = "") -> bool:
    if serial and is_55m_foreground(serial):
        return True
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if any(t in texts for t in MESSENGER_MARKERS):
        return True
    if any(label_matches(t, GROUP_CHAT_LABELS, exact=True) for t in texts):
        return True
    return any(GROUP_TITLE_RE.match(t) for t in texts)


def launch_messenger_app(serial: str) -> bool:
    dismiss_upgrade_popup(serial)
    if is_55m_foreground(serial):
        return True
    root = ui_hierarchy(serial)
    if in_messenger_app(root, serial):
        return True
    log.info("55M 不在前台，尝试温启动")
    if bring_messenger_foreground(serial):
        return True
    log.info("温启动失败，尝试 launcher 拉起（最后手段）")
    cached = _MESSENGER_PKG_CACHE.get(serial)
    if cached:
        adb_run(
            serial, "shell", "monkey", "-p", cached,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        w(2.5, 1.0)
        if in_messenger_app(ui_hierarchy(serial), serial) or is_55m_foreground(serial):
            log.info("已启动(缓存) %s", cached)
            return True
    pkg_keys = ("wuwu", "telegram.business", "messenger", "55chat", "chat55", "im55", "fivefive")
    pkgs: list[str] = []
    for line in adb_run(serial, "shell", "pm", "list", "packages").splitlines():
        pkg = line.split(":")[-1].strip() if ":" in line else ""
        low = pkg.lower()
        if not any(k in low for k in pkg_keys):
            continue
        pkgs.append(pkg)
    pkgs.sort(key=lambda p: (0 if "wuwu" in p.lower() else 1, len(p)))
    for pkg in pkgs:
        adb_run(
            serial, "shell", "monkey", "-p", pkg,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        w(2.5, 1.0)
        if in_messenger_app(ui_hierarchy(serial), serial) or is_55m_foreground(serial):
            _MESSENGER_PKG_CACHE[serial] = pkg
            log.info("已启动 %s", pkg)
            return True
    for pkg in pkgs:
        try:
            adb_run(
                serial, "shell", "am", "start",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
                "-p", pkg,
            )
            w(2.0, 0.8)
            if in_messenger_app(ui_hierarchy(serial), serial) or is_55m_foreground(serial):
                _MESSENGER_PKG_CACHE[serial] = pkg
                log.info("已启动(am) %s", pkg)
                return True
        except Exception:
            pass
    texts = collect_ui_texts(root) if root is not None else []
    if any("system tools" in t.lower() or "文件" in t for t in texts):
        log.warning("当前在桌面/文件管理，尝试继续启动 55M")
    if force_restart_messenger(serial, reason="launcher 末手段"):
        return True
    return False


def is_on_launcher(serial: str) -> bool:
    """是否在桌面 Launcher（左机离群常见状态）。"""
    try:
        out = adb_run(serial, "shell", "dumpsys", "window", "displays")
        for line in out.splitlines():
            if "mCurrentFocus" not in line:
                continue
            low = line.lower()
            if "launcher" in low and "wuwu." not in low:
                return True
    except Exception:
        pass
    return False


def _current_focus_line(serial: str) -> str:
    try:
        out = adb_run(serial, "shell", "dumpsys", "window", "displays")
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
    except Exception:
        pass
    return ""


def clicker_needs_messenger_restart(serial: str) -> bool:
    """左机卡在联系人编辑/非主界面等深层页，需大退重进。"""
    if is_on_launcher(serial):
        return True
    focus = _current_focus_line(serial).lower()
    if not focus:
        return False
    if "wuwu." not in focus and "telegram.business" not in focus:
        return True
    bad = (
        "contactedit",
        "contactactivity",
        "addfriend",
        "profileactivity",
        "secretkey",
        "webviewactivity",
        "picker",
        "gallery",
    )
    return any(b in focus for b in bad)


def relaunch_clicker_messenger(serial: str, *, reason: str = "") -> bool:
    if clicker_needs_messenger_restart(serial):
        return force_restart_messenger(serial, reason=reason or "clicker-relaunch")
    if not is_55m_foreground(serial):
        return launch_messenger_app(serial)
    return True


def dismiss_clicker_contact_compose(serial: str) -> bool:
    """左机误进「搜索或新建 / 联系人编辑」等阻塞页，退回消息列表。"""
    root = ui_hierarchy(serial)
    if root is None:
        return False
    title = get_chat_title(root)
    texts = collect_ui_texts(root)
    blob = " ".join(texts)
    stuck = (
        "搜索或新建" in title
        or "搜索或新建" in blob
        or "contactedit" in _current_focus_line(serial).lower()
        or clicker_needs_messenger_restart(serial)
    )
    if not stuck and not any(t.startswith("搜索或新") for t in texts):
        if "contactedit" not in _current_focus_line(serial).lower():
            return False
    log.info("左机退出阻塞页 title=%r", title[:24] if title else "")
    for _ in range(3):
        clicker_safe_back(serial, reason="退出搜索/联系人")
        clicker_w(0.35, 0.12)
    dismiss_search_page(serial)
    tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
    wc(0.55, 0.2)
    return True


def dismiss_clicker_dialogs(serial: str) -> bool:
    """左机：强制更新/退出确认等弹窗 — 点稍后/取消，不杀进程。"""
    root = ui_hierarchy(serial)
    if root is None:
        return False
    texts = collect_ui_texts(root)
    blob = " ".join(texts)
    if not any(
        m in blob
        for m in (
            "发现新版本", "强制更新", "立即更新", "版本更新", "退出应用", "要退出", "再按一次",
            "安全密码", "还未设置安全密码",
        )
    ):
        return False
    for labels in (
        ("稍后", "暂不", "取消", "知道了", "关闭"),
        ("退出", "后台", "最小化"),
    ):
        pt = find_tap_for_labels(root, labels, min_y=0, max_y=2000, exact=False)
        if pt:
            log.info("左机关闭弹窗 %s @ (%d,%d)", labels[0], pt[0], pt[1])
            adb_tap_raw(serial, pt[0], pt[1])
            w(0.45, 0.15)
            invalidate_ui_cache(serial)
            return True
    return False


def _clicker_header_back_allowed_in_group(reason: str) -> bool:
    """群聊 Activity 内仅允许退出错页/设置/网页，禁止「相册」子串误放行。"""
    if not reason:
        return False
    allowed_prefixes = ("退出群设置", "退出网页", "退出wrong_chat", "退出profile")
    return any(reason.startswith(p) for p in allowed_prefixes)


def clicker_safe_back(serial: str, *, reason: str = "") -> None:
    """左机返回：群聊内禁止 header 返回（会退出群）；相册/设置页才点箭头。"""
    if is_clicker_serial(serial) and is_group_chat_activity(serial):
        gallery = _verify_gallery_picker_open_serial(serial)
        attach = _verify_attach_menu_open_serial(serial)
        allow_exit = _clicker_header_back_allowed_in_group(reason)
        if gallery:
            if reason:
                log.info("左机 UI 返回：%s", reason)
            tap_header_back(serial)
            return
        if attach:
            if reason:
                log.info("左机群聊收起附件：%s", reason)
            _dismiss_clicker_attach_menu(serial)
            return
        if not allow_exit:
            if reason:
                log.info("左机群聊内跳过 header 返回：%s", reason)
            dismiss_soft_keyboard(serial)
            return
    if reason:
        log.info("左机 UI 返回：%s", reason)
    tap_header_back(serial)


def dismiss_soft_keyboard(serial: str) -> None:
    """收起输入法：右机/左机禁止点聊天区；ESC 收起。"""
    if is_listener_send_only_serial(serial) or is_clicker_serial(serial):
        try:
            adb_run(serial, "shell", "input", "keyevent", "111")  # ESC 收起键盘
        except Exception:
            pass
        w(0.12, 0.06)
        invalidate_ui_cache(serial)
        return
    snap = ui_snapshot(serial, chat=False)
    sw = screen_width(snap.root) if snap.root is not None else 720
    sh = screen_height(snap.root) if snap.root is not None else 1280
    if snap.input_bounds:
        y = max(100, snap.input_bounds[1] - 90)
        adb_tap_raw(serial, sw // 2, y)
    else:
        adb_tap_raw(serial, sw // 2, sh // 3)
    w(0.15, 0.06)
    invalidate_ui_cache(serial)


def clicker_suspend_adb_ime_for_attach(serial: str) -> None:
    """发图前暂切系统 IME 并 disable ADB Keyboard（浮层会挡 +）。"""
    if not is_clicker_serial(serial):
        return
    try:
        cur = adb_run(serial, "shell", "settings", "get", "secure", "default_input_method").strip()
    except Exception:
        cur = ""
    _CLICKER_ATTACH_IME_RESTORE[serial] = cur
    disabled: list[str] = []
    try:
        listed = adb_run(serial, "shell", "ime", "list", "-s")
        for ime in ADB_IMES:
            if ime not in listed:
                continue
            adb_run(serial, "shell", "ime", "disable", ime)
            disabled.append(ime)
    except Exception:
        pass
    if disabled:
        _CLICKER_ATTACH_IME_DISABLED[serial] = disabled
        log.info("发图暂禁 ADB IME serial=%s n=%d", serial, len(disabled))
    low = cur.lower()
    if "adbkeyboard" not in low and "uiautomator" not in low and not disabled:
        return
    listed = adb_run(serial, "shell", "ime", "list", "-s")
    fallback = None
    for line in listed.splitlines():
        ime = line.strip()
        if not ime or ime.startswith("user"):
            continue
        il = ime.lower()
        if "adbkeyboard" in il or "uiautomator" in il:
            continue
        fallback = ime
        break
    if fallback and set_active_ime(serial, fallback):
        log.info("发图暂切 IME serial=%s → %s", serial, fallback.split("/")[-1])


def clicker_restore_adb_ime_after_attach(serial: str) -> None:
    if not is_clicker_serial(serial):
        return
    for ime in _CLICKER_ATTACH_IME_DISABLED.pop(serial, []):
        try:
            adb_run(serial, "shell", "ime", "enable", ime)
        except Exception:
            pass
    prev = _CLICKER_ATTACH_IME_RESTORE.pop(serial, None)
    if not prev:
        return
    if "adbkeyboard" in prev.lower() or "uiautomator" in prev.lower():
        ensure_adb_ime(serial)
    else:
        set_active_ime(serial, prev)


def clicker_hide_keyboard_for_attach(serial: str) -> None:
    """左机发图前收起键盘并暂离 ADB IME，否则 + 不展开附件栏。"""
    if not is_clicker_serial(serial):
        return
    clicker_suspend_adb_ime_for_attach(serial)
    dismiss_clicker_popup_overlay(serial)
    for _ in range(2):
        try:
            adb_run(serial, "shell", "cmd", "input_method", "hide")
            adb_run(serial, "shell", "input", "keyevent", "111")
        except Exception:
            pass
        dismiss_soft_keyboard(serial)
        clicker_w(0.12, 0.06)
    clicker_w(0.2, 0.1)
    invalidate_ui_cache(serial)
    invalidate_step_verify_cache(serial)


def listener_send_protected(serial: str) -> bool:
    """右机正在/即将发公告或结算文字 — 禁止清栏、收键盘、全量隧道重建。"""
    if _LISTENER_SEND_LOCK.get(serial):
        return True
    return outbound_pending_announce_text(serial)


def listener_composer_dirty(draft: str | None) -> bool:
    d = (draft or "").strip()
    if not d:
        return False
    # 待发公告/结算长文不是 OCR 垃圾，禁止 stay-watch 清栏
    if listener_draft_looks_like_outgoing(d):
        return False
    if len(d) > 120:
        return True
    if d.count("by ") >= 4 or d.count("by") >= 8:
        return True
    if d.count("BB ") >= 3:
        return True
    return False


def listener_draft_looks_like_outgoing(draft: str) -> bool:
    d = (draft or "").strip()
    if len(d) < 8:
        return False
    markers = (
        "已封盘", "距离封盘", "距封盘", "封盘", "新的一局", "期】", "28.run", "开奖网",
        "禁]", "钱]", "抱拳", "停止下注", "六合", "定位胆",
    )
    return any(m in d for m in markers)


def defer_listener_composer_clean(serial: str, *, reason: str = "after-send") -> None:
    """右机输入栏延后清理（默认 90s），避免立刻清掉待发草稿。"""
    if is_clicker_serial(serial):
        return
    delay = LISTENER_COMPOSER_CLEAN_DELAY_SEC

    def _run() -> None:
        try:
            listener_sanitize_composer(serial, reason=f"deferred-{reason}", force=True)
        except Exception as ex:
            log.debug("deferred composer clean %s: %s", serial, ex)

    with _COMPOSER_CLEAN_LOCK:
        old = _COMPOSER_CLEAN_TIMERS.pop(serial, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(delay, _run)
        timer.daemon = True
        _COMPOSER_CLEAN_TIMERS[serial] = timer
        timer.start()
    log.info("右机输入栏清理已排程 %.0fs serial=%s (%s)", delay, serial, reason)


def listener_sanitize_composer(serial: str, *, reason: str = "", force: bool = False) -> bool:
    """右机：清理输入栏草稿/键盘；force 或 BOT_LISTENER_STAY_SANITIZE 时执行。"""
    if is_clicker_serial(serial):
        return False
    if not force and not LISTENER_STAY_SANITIZE:
        return False
    if listener_send_protected(serial):
        return False
    snap = ui_snapshot(serial, chat=False)
    draft = snap.draft or ""
    wrong_ime = ime_family(serial) == "other"
    keyboard_up = listener_keyboard_visible(serial, snap)
    dirty = listener_composer_dirty(draft)
    if not dirty and not wrong_ime and not keyboard_up:
        return False
    tag = reason or ("dirty_draft" if dirty else "keyboard_up" if keyboard_up else "wrong_ime")
    log.info(
        "右机清理输入栏 serial=%s reason=%s draft_len=%d ime=%s keyboard=%s",
        serial, tag, len(draft), ime_family(serial), keyboard_up,
    )
    ensure_adb_ime(serial)
    adb_clear_input_fast(serial, instant=True)
    listener_hide_keyboard(serial, reason=tag)
    invalidate_ui_cache(serial)
    return True


def device_safe_back(serial: str, *, reason: str = "") -> None:
    """右机/通用可用系统 Back；左机强制 UI 返回。"""
    if is_clicker_serial(serial):
        clicker_safe_back(serial, reason=reason)
        return
    root = ui_hierarchy(serial)
    if root is not None and ui_shows_exit_app_warning(root):
        log.warning("禁止 Back（再按一次将退出 55M），改按 Home")
        android_home(serial, reason=reason or "退出程序提示")
        return
    if reason:
        log.info("系统返回：%s", reason)
    try:
        adb_run(serial, "shell", "input", "keyevent", "4")
    except Exception:
        pass
    w(0.35, 0.12)
    invalidate_ui_cache(serial)


def recover_clicker_to_group_minimal(serial: str, bot: dict, *, max_steps: int = 4) -> bool:
    """左机离群最小恢复（固定文档 §1.3）：消息 Tab → 点群名，禁止连环 Back。"""
    group = (bot.get("associatedGroup") or "").strip()
    prev = os.environ.get("BOT_ALLOW_CLICKER_NAV")
    os.environ["BOT_ALLOW_CLICKER_NAV"] = "1"
    try:
        dismiss_clicker_stuck_surface(serial)
        relaunch_clicker_messenger(serial, reason="clicker-recover")
        wc(0.9, 0.3)
        dismiss_clicker_contact_compose(serial)
        if _verify_chat_composer_ready_serial(serial):
            root0 = ui_hierarchy(serial)
            if in_target_group_chat(root0, bot, serial):
                return True
            title = get_chat_title(root0)
            group = (bot.get("associatedGroup") or "").strip()
            if title and group and not _group_title_matches(title, group):
                log.warning("左机 recover 在错误群 %s，返回列表", title)
                clicker_safe_back(serial, reason="recover-退出错误群")
                wc(0.55, 0.2)
        root = ui_hierarchy(serial)
        if in_target_group_chat(root, bot, serial):
            return True
        dismiss_message_list_overlay(serial)
        tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
        wc(0.55, 0.2)
        if group:
            tap_target_group_in_list(serial, bot, scrolls=3)
            wc(0.6, 0.25)
        return bool(
            _verify_chat_composer_ready_serial(serial)
            or in_target_group_chat(ui_hierarchy(serial), bot, serial)
        )
    finally:
        if prev is None:
            os.environ.pop("BOT_ALLOW_CLICKER_NAV", None)
        else:
            os.environ["BOT_ALLOW_CLICKER_NAV"] = prev


def clicker_back_to_group(serial: str, bot: dict, *, max_steps: int = 6) -> bool:
    """左机回群：仅 UI 返回 + 消息列表点群名，禁止通讯录/系统 Back。"""
    group = (bot.get("associatedGroup") or "").strip()
    dismiss_clicker_dialogs(serial)
    dismiss_upgrade_popup(serial)
    if is_on_launcher(serial) or not is_55m_foreground(serial):
        log.warning("左机不在 55M，重新拉起")
        launch_messenger_app(serial)
        w(0.9, 0.35)
    for step in range(max_steps):
        root = ui_hierarchy(serial)
        if in_target_group_chat(root, bot, serial):
            log.info("左机已在目标群 %s", group or "?")
            return True
        if is_group_settings_page(root):
            clicker_safe_back(serial, reason="退出群设置")
            continue
        if is_in_app_webview(root):
            clicker_safe_back(serial, reason="退出网页")
            continue
        if is_search_page(root, serial):
            dismiss_search_page(serial)
            continue
        if is_secret_key_page(root):
            dismiss_secret_key_page(serial)
            continue
        ctx = describe_screen_context(root, bot, serial)
        if ctx.page in ("profile", "wrong_chat"):
            clicker_safe_back(serial, reason=f"退出{ctx.page}")
            continue
        if ctx.page == "message_list" and group:
            if tap_target_group_in_list(serial, bot, scrolls=2):
                w(0.6, 0.25)
                continue
        if is_group_chat_activity(serial):
            clicker_safe_back(serial, reason="退出wrong_chat")
            continue
        tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
        w(0.45, 0.18)
        if group and tap_target_group_in_list(serial, bot, scrolls=2):
            w(0.5, 0.2)
            continue
        clicker_safe_back(serial, reason=f"退出other step={step + 1}")
    root = ui_hierarchy(serial)
    if in_target_group_chat(root, bot, serial):
        return True
    tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
    w(0.55, 0.22)
    if group and tap_target_group_in_list(serial, bot, scrolls=3):
        return True
    ok = in_target_group_chat(ui_hierarchy(serial), bot, serial)
    if not ok:
        log.warning("左机未能回到目标群 %s", group)
    return ok


def dismiss_clicker_group_settings(serial: str) -> bool:
    """左机误进群资料/设置页时返回聊天或列表。"""
    if not is_group_settings_page(ui_hierarchy(serial)):
        return False
    log.info("左机退出群资料/设置页")
    for _ in range(5):
        root = ui_hierarchy(serial)
        if not is_group_settings_page(root):
            invalidate_ui_cache(serial)
            return True
        try:
            adb_run(serial, "shell", "input", "keyevent", "4")
        except Exception:
            tap_header_back(serial)
        wc(0.45, 0.15)
        invalidate_ui_cache(serial)
    root2 = ui_hierarchy(serial)
    if is_group_settings_page(root2):
        tap_header_back(serial)
        wc(0.5, 0.2)
        invalidate_ui_cache(serial)
    return not is_group_settings_page(ui_hierarchy(serial))


def ensure_clicker_in_group(serial: str, bot: dict, *, reason: str = "") -> bool:
    """左机入群/驻群：消息 Tab + 点群名，不走通讯录绕路。"""
    if reason:
        log.info("左机驻群检查 (%s)", reason)
    dismiss_clicker_dialogs(serial)
    dismiss_clicker_popup_overlay(serial)
    for _ in range(3):
        if not dismiss_clicker_group_settings(serial):
            break
    dismiss_search_page(serial)
    relaunch_clicker_messenger(serial, reason=reason or "ensure-clicker")
    wc(0.8, 0.25)
    dismiss_clicker_contact_compose(serial)
    dismiss_search_page(serial)
    root0 = ui_hierarchy(serial)
    if root0 is not None:
        texts0 = collect_ui_texts(root0)
        if any("群相册" in t for t in texts0):
            log.info("左机退出群相册页")
            for _ in range(4):
                try:
                    adb_run(serial, "shell", "input", "keyevent", "4")
                except Exception:
                    tap_header_back(serial)
                wc(0.4, 0.15)
                invalidate_ui_cache(serial)
                if not any("群相册" in t for t in collect_ui_texts(ui_hierarchy(serial) or root0)):
                    break
            tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
            wc(0.5, 0.15)
    root = ui_hierarchy(serial)
    if in_target_group_chat(root, bot, serial):
        return True
    if _verify_chat_composer_ready_serial(serial):
        root2 = ui_hierarchy(serial)
        if in_target_group_chat(root2, bot, serial):
            log.info("左机已在群聊输入态，跳过群名导航")
            return True
        title = get_chat_title(root2)
        group = (bot.get("associatedGroup") or "").strip()
        if title and group and not _group_title_matches(title, group):
            log.warning("左机在错误群 %s（目标=%s），返回列表", title, group)
            clicker_safe_back(serial, reason="退出错误群")
            wc(0.6, 0.25)
    if in_target_group_chat(ui_hierarchy(serial), bot, serial):
        return True
    dismiss_message_list_overlay(serial)
    group = (bot.get("associatedGroup") or "").strip()
    for _ in range(5):
        root = ui_hierarchy(serial)
        if in_target_group_chat(root, bot, serial):
            return True
        title = get_chat_title(root)
        if title and group and not _group_title_matches(title, group):
            if _verify_chat_composer_ready_serial(serial) or is_group_chat_activity(serial):
                log.warning("左机在错误群 %s（目标=%s），返回列表", title, group)
                clicker_safe_back(serial, reason="退出错误群")
                wc(0.55, 0.2)
                tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
                wc(0.45, 0.15)
                continue
        break
    tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
    wc(0.5, 0.15)
    if group and tap_target_group_in_list(serial, bot, scrolls=6):
        return True
    if enter_group_via_contacts(serial, bot):
        return True
    return clicker_back_to_group(serial, bot, max_steps=8)


def ensure_group_chat(serial: str, bot: dict) -> bool:
    """回到目标群聊（associatedGroup）；若在 V03 等错误会话则先退出。"""
    if is_listener_send_only_serial(serial, bot):
        ok = in_target_group_chat(ui_hierarchy(serial), bot, serial)
        if not ok:
            log.warning(
                "右机未在目标群 %s，禁止自动导航（请手动停留在群聊）",
                bot.get("associatedGroup"),
            )
        return ok
    if is_clicker_serial(serial, bot):
        return ensure_clicker_in_group(serial, bot, reason="ensure_group_chat")
    dismiss_secret_key_page(serial)
    dismiss_search_page(serial)
    dismiss_in_app_webview(serial)
    if not launch_messenger_app(serial):
        log.warning("无法启动 55M")
        return False
    group = (bot.get("associatedGroup") or "").strip()
    dismiss_message_list_overlay(serial)
    tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
    w(0.6, 0.25)
    if enter_group_via_contacts(serial, bot):
        return True
    for attempt in range(6):
        root = ui_hierarchy(serial)
        if in_target_group_chat(root, bot, serial):
            log.info("已在目标群 %s", group or "?")
            return True
        texts = collect_ui_texts(root) if root is not None else []
        if is_secret_key_page(root):
            dismiss_secret_key_page(serial)
            continue
        if is_in_app_webview(root):
            dismiss_in_app_webview(serial)
            continue
        # 在错误聊天页（有输入框但不是目标群）→ 左上角返回
        if in_group_chat(root, bot, serial):
            log.warning("当前在错误会话，返回 (目标群=%s)", group)
            tap_header_back(serial)
            w(0.7, 0.3)
            continue
        if group and tap_target_group_in_list(serial, bot, scrolls=3):
            return True
        if enter_group_via_contacts(serial, bot):
            return True
        tap_bottom_tab(serial, MESSAGES_TAB_LABELS)
        w(0.8, 0.35)
        if group and tap_target_group_in_list(serial, bot, scrolls=4):
            return True
    ok = in_target_group_chat(ui_hierarchy(serial), bot, serial)
    if not ok:
        log.warning("无法进入目标群 %s", group)
    return ok


def is_search_page(root: ET.Element | None, serial: str = "") -> bool:
    if root is None:
        return False
    if is_group_settings_page(root):
        return False
    if serial and is_group_chat_activity(serial):
        return False
    texts = collect_ui_texts(root)
    if any(m in t for t in texts for m in SEARCH_PAGE_MARKERS):
        return True
    has_search = any(t == "搜索" or t.startswith("搜索") for t in texts)
    has_cancel = any(t in SEARCH_CANCEL_LABELS for t in texts)
    return has_search and has_cancel


def is_secret_key_page(root: ET.Element | None) -> bool:
    if root is None:
        return False
    texts = collect_ui_texts(root)
    return any(
        any(m in t for m in SECRET_KEY_MARKERS)
        for t in texts
        if t and t.strip()
    )


def listener_send_blocked(root: ET.Element | None, serial: str = "") -> bool:
    """右机当前 UI 是否挡住发消息（密钥/搜索/设置/浏览器/桌面）。"""
    if serial and (is_on_launcher(serial) or not is_55m_foreground(serial)):
        return True
    if root is None:
        return not (serial and is_group_chat_activity(serial))
    texts = collect_ui_texts(root)
    if any(
        m in t
        for t in texts
        for m in ("System Tools", "Chrome", "扩展的通知", "Files", "文件管理", "Downloads")
    ):
        return True
    return (
        is_secret_key_page(root)
        or is_search_page(root, serial)
        or is_group_settings_page(root)
    )


def dismiss_secret_key_page(serial: str) -> bool:
    """误进端到端加密密钥详情页时返回。"""
    if block_listener_navigation(serial, "关闭加密密钥页"):
        return False
    root = ui_hierarchy(serial)
    if not is_secret_key_page(root):
        return False
    log.info("关闭加密密钥页")
    tap_header_back(serial)
    w(0.6, 0.25)
    invalidate_ui_cache(serial)
    return True


def dismiss_search_page(serial: str) -> bool:
    """误进全局搜索页时点「取消」退出。"""
    if block_listener_navigation(serial, "关闭搜索页"):
        return False
    root = ui_hierarchy(serial)
    if not is_search_page(root, serial):
        return False
    pt = find_tap_for_labels(
        root, SEARCH_CANCEL_LABELS, min_y=0, max_y=350, exact=True,
    ) if root is not None else None
    if not pt and root is not None:
        for node in root.iter("node"):
            if node_label(node).strip() not in SEARCH_CANCEL_LABELS:
                continue
            b = parse_bounds(node.attrib.get("bounds", ""))
            if not b:
                continue
            pt = node_center(b)
            break
    if pt:
        log.info("关闭搜索页 @ (%d,%d)", pt[0], pt[1])
        adb_tap_raw(serial, pt[0], pt[1])
        w(0.6, 0.25)
        invalidate_ui_cache(serial)
        return True
    log.warning("在搜索页但未找到「取消」按钮")
    press_back(serial, 1)
    return True


def safe_nav_guard(serial: str) -> bool:
    """导航后检查：若在搜索页则关闭。"""
    return dismiss_search_page(serial)


def on_contacts_home(root: ET.Element | None) -> bool:
    """通讯录首页：标题 + 新的朋友 + 群聊。"""
    if root is None:
        return False
    texts = collect_ui_texts(root)
    has_title = any(t in CONTACTS_TAB_LABELS for t in texts)
    has_new = any(label_matches(t, NEW_FRIEND_LABELS) for t in texts)
    has_groups = any(label_matches(t, GROUP_CHAT_LABELS, exact=True) for t in texts)
    return has_title and has_new and has_groups


def tap_contacts_menu_row(
    serial: str,
    labels: tuple[str, ...],
    *,
    contains: str = "",
) -> bool:
    """点通讯录列表行（新的朋友 / 群聊），避开顶部搜索栏。"""
    root = ui_hierarchy(serial)
    if root is None:
        return False
    min_y = SEARCH_BAR_Y_MAX + 28
    pt = find_tap_for_labels(root, labels, min_y=min_y, max_y=1500, exact=True)
    if not pt and contains:
        pt = find_tap_contains(root, contains, min_y=min_y, max_y=1500)
    if not pt:
        log.warning("通讯录未找到入口 %s", labels)
        return False
    log.info("点通讯录入口 %s @ (%d,%d)", contains or labels[0], pt[0], pt[1])
    adb_tap(serial, pt[0], pt[1])
    w(1.0, 0.45)
    safe_nav_guard(serial)
    return True


def open_contacts_home(serial: str) -> bool:
    """打开通讯录 Tab 并确认在首页。"""
    dismiss_search_page(serial)
    root = ui_hierarchy(serial)
    if on_contacts_home(root):
        return True
    tap_bottom_tab(serial, CONTACTS_TAB_LABELS)
    w(0.9, 0.4)
    safe_nav_guard(serial)
    ok = on_contacts_home(ui_hierarchy(serial))
    if not ok:
        log.warning("未能进入通讯录首页")
    return ok


def enter_group_via_contacts(serial: str, bot: dict) -> bool:
    """通讯录 → 群聊 → 目标测试群。"""
    group = (bot.get("associatedGroup") or "").strip()
    if not group:
        log.warning("未配置 associatedGroup")
        return False
    if not open_contacts_home(serial):
        return False
    if not tap_contacts_menu_row(serial, GROUP_CHAT_LABELS, contains="群聊"):
        return False
    root = ui_hierarchy(serial)
    if root is None or is_search_page(root, serial):
        dismiss_search_page(serial)
        return False
    if tap_target_group_in_list(serial, bot, scrolls=5):
        log.info("已进入测试群 %s", group)
        return True
    log.warning("群聊列表未找到 %s", group)
    return False


def back_to_contacts_home(serial: str, max_steps: int = 4) -> bool:
    """左上角返回直到通讯录首页（资料页/新的朋友 → 通讯录）。"""
    for i in range(max_steps):
        root = ui_hierarchy(serial)
        if is_search_page(root, serial):
            dismiss_search_page(serial)
            continue
        if on_contacts_home(root):
            log.info("已回到通讯录首页")
            return True
        log.info("好友导航返回 step=%d", i + 1)
        tap_header_back(serial)
        w(0.6, 0.25)
        safe_nav_guard(serial)
    return on_contacts_home(ui_hierarchy(serial))


def on_new_friends_page(root: ET.Element | None) -> bool:
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if any("待处理" in t for t in texts):
        return True
    if any(t == "验证" for t in texts):
        return True
    if any("近期请求" in t for t in texts):
        return True
    return False


def go_to_message_list(serial: str) -> None:
    """从群聊退到消息列表：点左上角返回箭头。"""
    for _ in range(4):
        root = ui_hierarchy(serial)
        if is_search_page(root, serial):
            dismiss_search_page(serial)
            continue
        texts = collect_ui_texts(root) if root is not None else []
        if not any(t == "输入消息" or t == "Enter message" for t in texts):
            if any(t in MESSAGES_TAB_LABELS for t in texts) or any(
                GROUP_TITLE_RE.match(t) for t in texts
            ):
                return
        tap_header_back(serial)
        w(0.8, 0.35)
        safe_nav_guard(serial)


def open_new_friends_page(serial: str) -> bool:
    """通讯录 → 新的朋友。"""
    dismiss_search_page(serial)
    root = ui_hierarchy(serial)
    if on_new_friends_page(root) or on_friend_detail_page(root):
        return True
    if not open_contacts_home(serial):
        return False
    if not tap_contacts_menu_row(serial, NEW_FRIEND_LABELS, contains="新的朋友"):
        return False
    root = ui_hierarchy(serial)
    if is_search_page(root, serial):
        dismiss_search_page(serial)
        return False
    ok = on_new_friends_page(root) or on_friend_detail_page(root)
    if not ok:
        log.warning("点击新的朋友后未进入好友申请页")
    return ok


def on_friend_detail_page(root: ET.Element | None) -> bool:
    if root is None:
        return False
    return any(t == "通过验证" for t in collect_ui_texts(root))


def on_friend_profile_page(root: ET.Element | None) -> bool:
    """已是好友的资料页：发送消息 / ID号 / 语音通话 等，且无添加按钮。"""
    if root is None:
        return False
    if on_already_friend_profile(root):
        return True
    texts = collect_ui_texts(root)
    if any(t == "通过验证" for t in texts):
        return False
    if profile_has_add_button(texts):
        return False
    markers = ("ID号", "备注名", "语音通话", "视频通话", "发消息", "发送消息")
    return sum(1 for m in markers if any(m in t for t in texts)) >= 2


def profile_has_add_button(texts: list[str]) -> bool:
    return any(label_matches(t, ADD_STRANGER_BTN, exact=True) for t in texts)


def profile_has_send_message(texts: list[str]) -> bool:
    return any(label_matches(t, SEND_MESSAGE_LABELS, exact=True) for t in texts)


def on_already_friend_profile(root: ET.Element | None) -> bool:
    """步骤1后：有「发送消息」且无「添加」→ 已是好友，直接返回群聊。"""
    if root is None:
        return False
    if on_add_verify_page(root):
        return False
    texts = collect_ui_texts(root)
    return profile_has_send_message(texts) and not profile_has_add_button(texts)


def on_stranger_profile_page(root: ET.Element | None) -> bool:
    """陌生人资料页：有「添加」按钮。"""
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if any(t == "ID号" for t in texts) or any(t == "通过验证" for t in texts):
        return False
    if on_already_friend_profile(root):
        return False
    return profile_has_add_button(texts)


def on_partial_member_profile_page(root: ET.Element | None, nick: str = "") -> bool:
    """
    群成员资料卡（点头像/昵称后的轻量页）：有昵称+在线状态，但尚无「添加」按钮。
    55M 点头像行左侧头像可进完整页；仅点昵称文字常停在此页。
    """
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if on_stranger_profile_page(root) or on_friend_profile_page(root) or on_add_verify_page(root):
        return False
    target = (nick or "").strip()
    has_nick = bool(target and any(t == target or target in t for t in texts))
    has_online = any("在线" in t for t in texts)
    no_action = not any(
        label_matches(t, ADD_STRANGER_BTN + ("发消息", "语音通话", "视频通话", "ID号"), exact=True)
        for t in texts
    )
    return has_online and no_action and (has_nick or not target)


def tap_member_profile_avatar(serial: str, root: ET.Element | None) -> bool:
    """资料卡上点头像区域，进入带「添加」的完整资料页。"""
    if root is None:
        return False
    sw, sh = screen_width(root), screen_height(root)
    hits: list[tuple[int, int, int]] = []
    for node in root.iter("node"):
        cls = node.attrib.get("class", "")
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy > int(sh * 0.28) or cy < 80:
            continue
        bw, bh = x2 - x1, y2 - y1
        if ("Image" in cls or node.attrib.get("clickable") == "true") and 40 <= bw <= 140 and 40 <= bh <= 140:
            hits.append((x1, (x1 + x2) // 2, cy))
    if hits:
        hits.sort(key=lambda h: -h[0])
        x, y = hits[0][1], hits[0][2]
    else:
        x, y = int(sw * 0.82), int(sh * 0.14)
    log.info("资料卡点头像 (%d,%d)", x, y)
    adb_tap(serial, x, y)
    w(0.8, 0.3)
    invalidate_ui_cache(serial)
    return True


def on_add_verify_page(root: ET.Element | None) -> bool:
    """添加验证页：填写验证消息 + 完成。"""
    if root is None:
        return False
    texts = collect_ui_texts(root)
    if any(m in t for t in texts for m in ADD_VERIFY_TITLE_MARKERS):
        return True
    return any(t in ADD_VERIFY_DONE for t in texts) and any(
        "财务" in t or "记账" in t for t in texts
    )


def tap_prominent_button(serial: str, labels: tuple[str, ...]) -> bool:
    """点屏幕中部/底部大按钮（添加 / 完成）。"""
    root = ui_hierarchy(serial)
    if root is None:
        return False
    sh = screen_height(root)
    hits: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        t = node_label(node).strip()
        if t not in labels:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < SEARCH_BAR_Y_MAX + 40 or cy > int(sh * 0.88):
            continue
        bw = x2 - x1
        hits.append((bw, cy, (x1 + x2) // 2, cy))
    if not hits:
        return False
    hits.sort(key=lambda h: (-h[0], h[1]))
    x, y = hits[0][2], hits[0][3]
    log.info("点按钮 %s @ (%d,%d)", labels[0], x, y)
    adb_tap(serial, x, y)
    w(0.6, 0.25)
    invalidate_ui_cache(serial)
    return True


def fill_add_verify_message(serial: str, message: str) -> None:
    """添加验证页填写「我是记账财务」。"""
    msg = (message or FRIEND_REQUEST_MSG).strip()
    if not msg:
        return
    if u2_fill_input(serial, msg):
        w(0.3, 0.1)
        return
    snap = ui_snapshot(serial)
    if snap.input_xy and draft_filled(snap.draft, msg):
        return
    if snap.input_xy:
        fill_input_box(serial, snap.input_xy[0], snap.input_xy[1], msg)


def find_cmd_y_in_root(root: ET.Element | None, cmd: str) -> int:
    """取屏幕上最下方（最新）一条指令的 Y 坐标。"""
    if root is None:
        return 0
    target = cmd.strip()
    best = 0
    for node in root.iter("node"):
        if node_label(node).strip() != target:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b and b[1] > SEARCH_BAR_Y_MAX:
            best = max(best, b[1])
    return best


def profile_missing_add_and_message(root: ET.Element | None) -> bool:
    """资料页上「发送消息」和「添加」都没有。"""
    if root is None:
        return False
    if on_add_verify_page(root):
        return False
    texts = collect_ui_texts(root)
    return not profile_has_send_message(texts) and not profile_has_add_button(texts)


def _classify_profile_after_avatar(
    root: ET.Element | None,
    target: str,
    bot: dict | None = None,
) -> str | None:
    """资料页状态：friend / stranger / verify / partial / no_buttons / None(待重试)"""
    if root is None:
        return None
    if on_add_verify_page(root):
        return "verify"
    if on_already_friend_profile(root) or on_friend_profile_page(root):
        return "friend"
    if on_stranger_profile_page(root):
        return "stranger"
    if on_partial_member_profile_page(root, target):
        return "partial"
    in_group = in_target_group_chat(root, bot, "") if bot else False
    if not in_group and profile_missing_add_and_message(root):
        return "no_buttons"
    return None


def open_group_sender_profile(
    serial: str,
    nick: str,
    near_y: int | None = None,
    bot: dict | None = None,
) -> tuple[bool, str]:
    """
    步骤1：群聊内点击发送「添加」用户的头像，进入资料页。
    返回 (成功, 状态)：stranger / friend / verify / fail
    """
    target = (nick or "").strip()
    if not target:
        return False, "fail"

    y = _effective_near_y(near_y) or 0
    for scroll_try in range(3):
        invalidate_ui_cache(serial)
        root = ui_hierarchy(serial, force=True)
        if y < 100 and root is not None:
            y = find_cmd_y_in_root(root, ADD_FINANCE_CMD) or y
        eff_y = y if y >= 100 else None

        pt = find_tap_avatar_for_sender(root, target, eff_y) if root is not None else None
        if not pt:
            log.warning("未找到 %s 头像 near_y=%s attempt=%s", target, eff_y, scroll_try + 1)
            if scroll_try < 2:
                scroll_chat_toward_bottom(serial, 1)
                wc(0.25, 0.08)
            continue

        log.info("添加步骤1：点头像 (%d,%d) nick=%s", pt[0], pt[1], target)
        adb_tap(serial, pt[0], pt[1])
        wc(0.75, 0.18)
        invalidate_ui_cache(serial)
        root = ui_hierarchy(serial)

        if bot and in_target_group_chat(root, bot, serial):
            log.warning("点头像后仍在群聊页 nick=%s", target)
            if scroll_try < 2:
                scroll_chat_toward_bottom(serial, 1)
            continue

        state = _classify_profile_after_avatar(root, target, bot)
        if state == "partial":
            log.info("轻量资料卡，再点头像进入完整页 nick=%s", target)
            tap_member_profile_avatar(serial, root)
            wc(0.6, 0.15)
            root = ui_hierarchy(serial, force=True)
            state = _classify_profile_after_avatar(root, target, bot)

        if state == "no_buttons":
            log.warning("添加步骤1：无「发送消息」也无「添加」 nick=%s", target)
            tap_header_back(serial)
            wc(0.4, 0.1)
            return True, "no_buttons"

        if state in ("friend", "stranger", "verify"):
            log.info("添加步骤1完成 state=%s nick=%s", state, target)
            return True, state

        if scroll_try < 2:
            tap_header_back(serial)
            wc(0.4, 0.1)
            scroll_chat_toward_bottom(serial, 1)

    log.warning("添加步骤1失败：无法打开 %s 资料页", target)
    return False, "fail"


def add_finance_back_to_group(serial: str, bot: dict) -> bool:
    """步骤4：点左上角箭头返回群聊界面。"""
    group = (bot.get("associatedGroup") or "").strip()
    for step in range(5):
        root = ui_hierarchy(serial)
        if in_target_group_chat(root, bot, serial):
            log.info("添加步骤4：已回群 %s", group)
            return True
        log.info("添加步骤4：点左上角返回 step=%s", step + 1)
        tap_header_back(serial)
        wc(0.55, 0.12)
        safe_nav_guard(serial)
    if in_target_group_chat(ui_hierarchy(serial), bot, serial):
        return True
    if is_clicker_bot(bot):
        return clicker_back_to_group(serial, bot)
    return ensure_group_chat(serial, bot)


def _reply_add_finance_result(
    serial: str,
    bot: dict,
    nick: str,
    settings: dict[str, str] | None,
) -> None:
    if is_clicker_bot(bot):
        log.info("Clicker 禁止群回复，跳过 add_finance 结果 nick=%s", nick)
        return
    if not in_target_group_chat(ui_hierarchy(serial), bot, serial):
        ensure_group_chat(serial, bot)
    if not in_target_group_chat(ui_hierarchy(serial), bot, serial):
        return
    snap = ui_snapshot(serial)
    send_xy = snap.inbar_send or snap.keyboard_send
    reply = user_reply(nick, ADD_FINANCE_REPLY)
    send_chat_reply(
        serial, bot, reply, snap.input_xy, send_xy, settings or {},
        group_ok=in_target_group_chat(snap.root, bot, serial),
    )
    post_log(f"[ADB] 已回复: {reply}", "SUCCESS")


def send_friend_add_request(
    serial: str,
    bot: dict,
    nick: str,
    near_y: int | None = None,
    settings: dict[str, str] | None = None,
    *,
    skip_group_reply: bool = False,
) -> str:
    """
    群内「添加」四步流程（左机 Clicker 执行）：
    1. 群聊点头像  2. 点添加  3. 点完成  4. 左上角返回群聊
    已是好友（有发送消息、无添加）→ 直接步骤4返回，右机回复。
    """
    nick = (nick or "").strip()
    if not nick:
        log.warning("添加财务：无发送者昵称")
        return "fail"
    if is_clicker_bot(bot):
        skip_group_reply = True
    log.info("添加流程开始 ← %s near_y=%s", nick, near_y)

    if not in_target_group_chat(ui_hierarchy(serial), bot, serial):
        ensure_group_chat(serial, bot)

    opened, state = open_group_sender_profile(serial, nick, near_y, bot)
    if not opened:
        log.warning("添加步骤1失败：无法打开 %s 资料页", nick)
        clicker_return_to_group(serial, bot, label=f"open_fail nick={nick}")
        return "fail"

    if state == "no_buttons":
        log.warning("添加：资料页无「发送消息」也无「添加」← %s", nick)
        add_finance_back_to_group(serial, bot)
        return "fail"

    if state == "friend":
        log.info("添加：%s 已是好友（发送消息/无添加），直接返回群聊", nick)
        if not add_finance_back_to_group(serial, bot):
            clicker_return_to_group(serial, bot, label=f"friend_back nick={nick}")
            return "fail"
        if skip_group_reply:
            return "already"
        if in_target_group_chat(ui_hierarchy(serial), bot, serial):
            snap = ui_snapshot(serial)
            send_xy = snap.inbar_send or snap.keyboard_send
            reply = user_reply(nick, ADD_FINANCE_ALREADY_REPLY)
            send_chat_reply(
                serial, bot, reply, snap.input_xy, send_xy, settings or {},
                group_ok=True,
            )
            post_log(f"[ADB] 已回复: {reply}", "SUCCESS")
        return "already"

    if state != "verify" and not on_stranger_profile_page(ui_hierarchy(serial)):
        log.warning("添加步骤1后未见到「添加」按钮 nick=%s state=%s", nick, state)
        tap_header_back(serial)
        clicker_return_to_group(serial, bot, label=f"no_add_ui nick={nick}")
        return "fail"

    if state != "verify":
        log.info("添加步骤2：点「添加」 nick=%s", nick)
        if not tap_prominent_button(serial, ADD_STRANGER_BTN):
            log.warning("添加步骤2失败：未找到「添加」")
            tap_header_back(serial)
            clicker_return_to_group(serial, bot, label=f"no_add_btn nick={nick}")
            return "fail"
        wc(0.55, 0.12)

    root = ui_hierarchy(serial)
    if on_add_verify_page(root):
        fill_add_verify_message(serial, FRIEND_REQUEST_MSG)
        log.info("添加步骤3：点「完成」 nick=%s", nick)
        if not tap_prominent_button(serial, ADD_VERIFY_DONE):
            log.warning("添加步骤3失败：未找到「完成」")
            tap_header_back(serial)
            clicker_return_to_group(serial, bot, label=f"no_done_btn nick={nick}")
            return "fail"
        wc(0.75, 0.18)
    else:
        log.info("添加步骤3：无验证页，尝试点「完成」 nick=%s", nick)
        tap_prominent_button(serial, ADD_VERIFY_DONE)
        wc(0.5, 0.12)

    root = ui_hierarchy(serial)
    texts = collect_ui_texts(root) if root else []
    if any(any(m in t for m in FRIEND_REQUEST_SENT_MARKERS) for t in texts):
        log.info("好友申请已发送 ← %s", nick)

    if not add_finance_back_to_group(serial, bot):
        log.warning("添加步骤4失败：未能回到群聊")
        clicker_return_to_group(serial, bot, label=f"back_fail nick={nick}")
        return "fail"

    log.info("添加流程完成，已回群 %s", bot.get("associatedGroup"))
    post_log(f"[ADB] 已发送好友申请: {nick}", "SUCCESS")
    if not skip_group_reply:
        _reply_add_finance_result(serial, bot, nick, settings)
    return "ok"


def tap_verify_list_button(serial: str) -> bool:
    root = ui_hierarchy(serial)
    if root is None:
        return False
    hits: list[tuple[int, int, int, bool, int]] = []
    for node in root.iter("node"):
        if node_label(node).strip() != FRIEND_VERIFY_LIST_LABEL:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < 180 or cy > 1750:
            continue
        bw = x2 - x1
        hits.append((y1, (x1 + x2) // 2, cy, node.attrib.get("clickable") == "true", bw))
    if not hits:
        return False
    hits.sort(key=lambda h: (h[4] > 140, not h[3], -h[2], h[0]))
    x, y = hits[0][1], hits[0][2]
    log.info("点验证 @(%d,%d)", x, y)
    adb_tap(serial, x, y)
    w(0.9, 0.35)
    return True


def tap_pass_verify_button(serial: str) -> bool:
    root = ui_hierarchy(serial)
    if root is None:
        return False
    sh, sw = screen_height(root), screen_width(root)
    hits: list[tuple[int, int, int]] = []
    for node in root.iter("node"):
        if node_label(node).strip() != "通过验证":
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x, y = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        if y < SEARCH_BAR_Y_MAX:
            continue
        hits.append((y, x, y))
    if hits:
        hits.sort(key=lambda h: -h[0])
        x, y = hits[0][1], hits[0][2]
        log.info("点通过验证 @(%d,%d)", x, y)
        adb_tap(serial, x, y)
        w(0.8, 0.35)
        safe_nav_guard(serial)
        return True
    y = int(sh * 0.72)
    log.info("点通过验证 兜底 @(%d,%d)", sw // 2, y)
    adb_tap(serial, sw // 2, y)
    w(0.8, 0.35)
    safe_nav_guard(serial)
    return True


def accept_friend_requests(serial: str, bot: dict) -> int:
    """通讯录 → 新的朋友 → 验证 → 通过验证 → 返回 → 群聊 → 测试群。"""
    dismiss_search_page(serial)
    total = 0

    if not open_new_friends_page(serial):
        log.warning("无法进入「新的朋友」")
        enter_group_via_contacts(serial, bot)
        return 0

    for _ in range(8):
        root = ui_hierarchy(serial)
        if is_search_page(root, serial):
            dismiss_search_page(serial)
            open_new_friends_page(serial)
            continue
        texts = collect_ui_texts(root) if root else []

        # 已通过：资料页左上角返回 → 新的朋友列表
        if on_friend_profile_page(root):
            log.info("资料页，左上角返回")
            tap_header_back(serial)
            w(0.6, 0.25)
            safe_nav_guard(serial)
            continue

        # 资料页：点通过验证 → 左上角返回
        if on_friend_detail_page(root):
            tap_pass_verify_button(serial)
            total += 1
            w(0.5, 0.2)
            tap_header_back(serial)
            w(0.6, 0.25)
            safe_nav_guard(serial)
            if not on_new_friends_page(ui_hierarchy(serial)):
                open_new_friends_page(serial)
            continue

        # 新的朋友列表：点「验证」→ 通过验证
        if on_new_friends_page(root) and FRIEND_VERIFY_LIST_LABEL in texts:
            if tap_verify_list_button(serial):
                w(0.7, 0.3)
                safe_nav_guard(serial)
                root2 = ui_hierarchy(serial)
                if on_friend_detail_page(root2):
                    tap_pass_verify_button(serial)
                    total += 1
                    w(0.5, 0.2)
                    tap_header_back(serial)
                    w(0.6, 0.25)
                    safe_nav_guard(serial)
                continue
            break

        if on_new_friends_page(root):
            log.info("新的朋友：暂无待验证")
            break

        open_new_friends_page(serial)

    if total:
        log.info("手动通过好友 %d 条", total)
        post_log(f"[ADB] 通过好友 {total} 个", "SUCCESS")

    # 左上角返回到通讯录 → 群聊 → 测试群
    back_to_contacts_home(serial)
    if not enter_group_via_contacts(serial, bot):
        ensure_group_chat(serial, bot)
    return total


def maybe_accept_friends(serial: str, bot: dict) -> None:
    """已废弃定时自动通过，改由控制面板触发 process_friend_accept_outbox。"""
    if AUTO_FRIEND_ACCEPT:
        key = str(bot.get("id") or serial)
        now = time.time()
        if now - _LAST_FRIEND_CHECK.get(key, 0) < FRIEND_ACCEPT_INTERVAL:
            return
        _LAST_FRIEND_CHECK[key] = now
        try:
            accept_friend_requests(serial, bot)
        except Exception as ex:
            log.warning("好友自动通过异常: %s", ex)
            try:
                ensure_group_chat(serial, bot)
            except Exception:
                pass


def read_messenger_id_for_nick(
    serial: str,
    nick: str,
    users: list[dict] | None = None,
    bot_id: str | None = None,
    bot: dict | None = None,
    near_y: int | None = None,
) -> str | None:
    """UserIdResolver：点昵称 → 资料页 @ID → 返回；面板交叉校验 + 持久缓存。"""
    nick = (nick or "").strip()
    if not nick or not is_plausible_sender(nick):
        log.info("无效昵称，跳过读 ID: %r", nick)
        return None
    if bot and is_send_only_listener(bot):
        log.info("右机禁止点头像读 ID（由 Clicker 执行）: %s", nick)
        return None

    hit = mid_cache_get(serial, nick, users, bot_id)
    if hit:
        log.info("ID 缓存命中 %s ← %s", hit, nick)
        return hit

    invalidate_ui_cache(serial)
    root = ui_hierarchy(serial, force=True)
    near_y = _effective_near_y(near_y if near_y is not None else _TAP_NEAR_Y.pop(serial, None))
    tapped = u2_tap_nick(serial, nick, near_y)
    if not tapped:
        pt = find_tap_for_nick(root, nick, near_y) if root is not None else None
        if not pt:
            log.warning("无法定位昵称「%s」用于读取 ID (near_y=%s)", nick, near_y)
            return None
        adb_tap(serial, pt[0], pt[1])
    w(0.4, 0.15)
    invalidate_ui_cache(serial)

    mid = u2_scrape_messenger_id(serial)
    root = ui_hierarchy(serial, force=True) if mid is None else root
    texts = collect_ui_texts(root) if root is not None else []
    if any(label_matches(t, ADD_FRIEND_LABELS) for t in texts):
        log.info("资料页需好友关系，请先手动添加好友")
        tap_header_back(serial)
        w(0.2, 0.08)
        if bot:
            if is_clicker_bot(bot):
                clicker_back_to_group(serial, bot)
            else:
                ensure_group_chat(serial, bot)
        return None
    if not mid and root is not None:
        mid = scrape_messenger_id(root)
    tap_header_back(serial)
    w(0.2, 0.08)
    invalidate_ui_cache(serial)
    if not mid:
        log.warning("资料页未读到 ID（昵称 %s）", nick)
        if bot:
            if is_clicker_bot(bot):
                clicker_back_to_group(serial, bot)
            else:
                ensure_group_chat(serial, bot)
        return None

    if users and bot_id:
        u = find_user_by_messenger_id(users, bot_id, mid)
        if not u:
            log.info("ID %s 未在面板登记 (nick=%s)，不写入缓存", mid, nick)
            return mid
        panel_row = panel_user_by_nick(users, bot_id, nick)
        if panel_row:
            panel_mid = normalize_messenger_id(str(panel_row.get("messengerId") or ""))
            if panel_mid and panel_mid != mid:
                log.warning("资料页 ID %s 与面板 %s 不符，拒绝认人", mid, panel_mid)
                return None

    store_mid_cache(serial, nick, mid, bot_id)
    save_mid_cache()
    if GATEWAY_ENABLED:
        if gateway_update_id(nick, mid):
            log.info("[缓存更新] 成功绑定新用户 username=%s user_id=%s", nick, mid)
    log.info("读取 55M ID %s ← 昵称 %s（认人缓存已写入）", mid, nick)
    if bot:
        if is_clicker_bot(bot):
            clicker_back_to_group(serial, bot)
        else:
            ensure_group_chat(serial, bot)
    return mid


def prewarm_visible_nick(
    serial: str,
    bot_id: str,
    users: list[dict],
    texts: list[str],
    bot: dict | None = None,
) -> None:
    """兼容入口：初始化队列 + 推进一步。"""
    if serial not in _PREWARM_QUEUE:
        schedule_batch_prewarm(serial, bot_id, users, texts)
    batch_prewarm_step(serial, bot_id, users, bot)


def update_display_name(user: dict, display_nick: str) -> dict:
    """同步面板群昵称为当前称呼（认人仍以 messengerId 为准）。"""
    nick = (display_nick or "").strip()
    current = str(user.get("username") or "").strip()
    if not nick or nick == current or not is_plausible_sender(nick):
        return user
    aliases = parse_aliases(user)
    if current and current not in aliases:
        aliases.append(current)
    aliases = [a for a in aliases if a and a != nick]
    user = dict(user)
    user["username"] = nick
    user["nickAliases"] = json.dumps(aliases, ensure_ascii=False)
    user["lastActive"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_user(user)
    log.info("昵称同步 %s → %s (id=%s)", current, nick, user.get("messengerId"))
    return user


def reply_display_name(display_nick: str, user: dict | None) -> str:
    return (display_nick or "").strip() or str((user or {}).get("username") or "")


def is_registered_user(serial: str, bot_id: str, display_nick: str) -> bool:
    return panel_user(bot_id, display_nick, serial) is not None


def _sender_from_texts_list(
    texts: list[str],
    idx: int,
    pool: dict[str, list[dict]],
    settings: dict[str, str],
    products: list[dict],
    bot_id: str,
) -> str:
    sender = _sender_for_index(texts, idx, pool)
    if sender:
        return sender
    for j in range(idx - 1, max(-1, idx - 15), -1):
        t = texts[j].strip()
        if not is_plausible_sender(t, settings, products, bot_id):
            continue
        return t
    return ""


def chat_message_ids(
    nodes: list[ChatTextNode],
    texts: list[str],
    settings: dict[str, str],
    products: list[dict],
    bot_id: str,
    users: list[dict] | None = None,
) -> list[tuple[str, str, str, int, int]]:
    """每条聊天指令 → (id, 指令, 发送者, 序号, 指令Y坐标)；nodes + texts 双通道防漏检。"""
    pool = nickname_pool(users or [], bot_id)
    out: list[tuple[str, str, str, int, int]] = []
    staged: dict[tuple, tuple[str, str, int, int]] = {}
    seq: Counter[str] = Counter()
    ord_idx = 0
    sw = max((n.x2 for n in nodes), default=720)

    def stage_cmd(cmd: str, sender: str, cmd_y: int, cmd_cx: int = 0) -> None:
        c = cmd.strip()
        snd = (sender or "").strip()
        if cmd_y <= 0:
            if is_query_command(c) and snd:
                cmd_y = QUERY_SYNTHETIC_CMD_Y
            else:
                return
        if cmd_cx > 0 and cmd_cx > int(sw * INCOMING_X_RATIO):
            return
        # 非下注：同屏同人同文只留 Y 最大（最靠下）一条
        if is_bet_command(c):
            dedup: tuple = (c, snd.lower(), cmd_y // CMD_Y_BUCKET)
        else:
            dedup = (c, snd.lower())
        prev = staged.get(dedup)
        if prev and prev[2] >= cmd_y:
            return
        staged[dedup] = (c, snd, cmd_y, cmd_cx)

    for cn in nodes:
        if not is_command(cn.text, settings, products, bot_id):
            continue
        if not is_incoming_message_node(cn, sw):
            continue
        sender = spatial_sender_for_command(nodes, cn, pool, settings, products, bot_id)
        if not sender and not BIND_RE.match(cn.text.strip()) and not ADD_FINANCE_RE.match(
            cn.text.strip()
        ):
            for n in sorted(
                [x for x in nodes if x.y2 <= cn.y1 - 4 and cn.y1 - x.y2 <= 280],
                key=lambda x: x.y1,
                reverse=True,
            ):
                t = n.text.strip()
                if is_plausible_sender(t, settings, products, bot_id):
                    sender = t
                    break
            if not sender:
                log.info("指令缺发送者，跳过解析 cmd=%s y=%s", cn.text, cn.y1)
                continue
        stage_cmd(cn.text, sender, cn.y1, cn.cx)

    for i, raw in enumerate(texts):
        cmd = raw.strip()
        if not is_command(cmd, settings, products, bot_id):
            continue
        cmd_y = 0
        cmd_cx = 0
        sender = ""
        best_n = None
        for n in nodes:
            if n.text.strip() == cmd:
                if best_n is None or n.y1 > best_n.y1:
                    best_n = n
        if best_n is not None:
            cmd_y = best_n.y1
            cmd_cx = best_n.cx
            sender = spatial_sender_for_command(nodes, best_n, pool, settings, products, bot_id)
        if cmd_y <= 0:
            sender = sender or _sender_from_texts_list(
                texts, i, pool, settings, products, bot_id,
            )
            if is_query_command(cmd) and sender:
                for n in nodes:
                    if n.text.strip() == sender:
                        cmd_y = max(n.y2, n.y1) + 8
                        cmd_cx = n.cx
                        break
                if cmd_y <= 0:
                    cmd_y = QUERY_SYNTHETIC_CMD_Y
            else:
                continue
        if cmd_cx > int(sw * INCOMING_X_RATIO):
            continue
        if not sender:
            sender = _sender_from_texts_list(texts, i, pool, settings, products, bot_id)
        if not sender and not BIND_RE.match(cmd) and not ADD_FINANCE_RE.match(cmd):
            continue
        stage_cmd(cmd, sender, cmd_y, cmd_cx)

    merge_split_bet_staged(staged)

    for c, snd, cmd_y, _cmd_cx in sorted(staged.values(), key=lambda row: row[2]):
        ts = f"y{cmd_y}"
        base = f"{c}@{snd or '?'}@{ts}"
        seq[base] += 1
        out.append((f"{base}#{seq[base]}", c, snd, ord_idx, cmd_y))
        ord_idx += 1

    return out


def _raw_sender_for_index(texts: list[str], idx: int) -> str:
    """取指令上方可见昵称（不要求已在面板登记）。"""
    for j in range(idx - 1, max(-1, idx - 12), -1):
        t = texts[j].strip()
        if not is_plausible_sender(t):
            continue
        return t
    return ""


def _sender_for_index(texts: list[str], idx: int, pool: dict[str, list[dict]]) -> str:
    """取指令正上方昵称；重复昵称时拒绝识别。"""
    for j in range(idx - 1, max(-1, idx - 12), -1):
        t = texts[j].strip()
        if _is_ui_noise_label(t):
            continue
        if is_command(t, DEFAULT_SETTINGS, [], "bot-3"):
            continue
        if t not in pool:
            continue
        owners = pool[t]
        if len(owners) == 1:
            return t
        codes = ", ".join(
            str(u.get("customerCode") or u.get("id")) for u in owners
        )
        log.warning("昵称重复「%s」，涉及编号 %s，请让用户发 绑定+编号", t, codes)
        return ""
    return ""


def api(method: str, path: str, body: Any = None) -> Any:
    return _BACKEND.request(method, path, body)


def gateway_post_json(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """记忆网关 HTTP POST（纯 stdlib，对接 mock_gateway）。"""
    url = f"{GATEWAY_BASE_URL}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
            return resp.status, body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"status": "error", "message": raw[:200]}
        return ex.code, body if isinstance(body, dict) else {}
    except Exception as ex:
        log.warning("网关请求失败 %s: %s", path, ex)
        return 0, {}


def gateway_chat_message(username: str, msg: str) -> tuple[int, dict[str, Any]]:
    return gateway_post_json("/api/chat/message", {"username": username, "msg": msg})


def gateway_update_id(username: str, user_id: str) -> bool:
    status, body = gateway_post_json(
        "/api/chat/update_id",
        {"username": username, "user_id": user_id},
    )
    return status == 200 and body.get("status") == "success"


def listener_gateway_resolve(
    serial: str,
    bot_id: str,
    username: str,
    msg: str,
) -> str:
    """网关认人：hit=已缓存 user_id | pending=202 待 Clicker | skip=未启用/失败。"""
    if not GATEWAY_ENABLED:
        return "skip"
    status, body = gateway_chat_message(username, msg)
    if status == 200 and body.get("status") == "success":
        uid = str(body.get("user_id") or "").strip()
        if uid:
            store_mid_cache(serial, username, uid, bot_id)
            save_mid_cache()
            log.info("[极速放行] 命中缓存 username=%s user_id=%s", username, uid)
        return "hit"
    if status == 202 and body.get("action") == "require_id_fetch":
        log.info("[风控拦截] 未知用户，挂起并下发认人任务 username=%s", username)
        return "pending"
    return "skip"


def record_bill(
    bot_id: str,
    username: str,
    bill_type: str,
    amount: float,
    balance_after: float,
    detail: str = "",
    customer_code: str = "",
) -> None:
    _record_bill_impl(
        _BACKEND,
        log,
        bot_id,
        username,
        bill_type,
        amount,
        balance_after,
        detail,
        customer_code,
    )


def adb_run(serial: str, *args: str, timeout: int = 20) -> str:
    cmd = ["adb", "-s", serial] + list(args)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (out.stdout or "") + (out.stderr or "")
    except subprocess.TimeoutExpired:
        return ""


def adb_exec_out_bytes(serial: str, *args: str, timeout: int = 12) -> bytes | None:
    cmd = ["adb", "-s", serial, "exec-out"] + list(args)
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if out.returncode == 0 and out.stdout and len(out.stdout) > 512:
            return out.stdout
    except Exception:
        pass
    return None


def adb_screencap_png(serial: str) -> bytes | None:
    return adb_exec_out_bytes(serial, "screencap", "-p", timeout=10)


def invalidate_roi_cache(serial: str) -> None:
    _ROI_GRAY_PREV.pop(serial, None)
    _GROUP_ACTIVITY_CACHE.pop(serial, None)


def _chat_roi_gray(png_bytes: bytes) -> Any | None:
    if not _HAS_CV2 or np is None or cv2 is None:
        return None
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h = img.shape[0]
    y0 = int(h * 0.52)
    roi = img[y0:h, :]
    return cv2.resize(roi, (96, 48), interpolation=cv2.INTER_AREA)


def _screencap_bottom_fingerprint(serial: str) -> bytes | None:
    """无 OpenCV 时：raw screencap 底部区域降采样指纹（~5–15ms）。"""
    size_out = adb_run(serial, "shell", "wm", "size")
    m = re.search(r"(\d+)x(\d+)", size_out)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    raw = adb_exec_out_bytes(serial, "screencap", timeout=10)
    if not raw or len(raw) < w * h * 4:
        return None
    y0 = int(h * 0.52)
    step = max(4, w // 48)
    fp = bytearray()
    for y in range(y0, h, step):
        row = y * w * 4
        for x in range(0, w, step):
            i = row + x * 4
            if i + 2 >= len(raw):
                continue
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            fp.append((r + g + g + b) >> 2)
    return bytes(fp)


def chat_bottom_roi_changed(serial: str) -> bool:
    """群聊底部 ROI 帧差：True=可能有新消息，需完整 ui_snapshot。"""
    now = time.time()
    cached = _GROUP_ACTIVITY_CACHE.get(serial)
    if cached and now - cached[0] < ROI_CACHE_SEC:
        return cached[1]
    if not FAST_DETECT_ENABLED:
        _GROUP_ACTIVITY_CACHE[serial] = (now, True)
        return True

    gray = None
    png = adb_screencap_png(serial) if _HAS_CV2 else None
    if png:
        gray = _chat_roi_gray(png)
    fp = None if gray is not None else _screencap_bottom_fingerprint(serial)
    if gray is None and not fp:
        _GROUP_ACTIVITY_CACHE[serial] = (now, True)
        return True

    prev = _ROI_GRAY_PREV.get(serial)
    changed = True
    if gray is not None:
        if prev is not None and hasattr(prev, "shape") and prev.shape == gray.shape:
            diff = float(np.mean(np.abs(gray.astype(np.float32) - prev.astype(np.float32)))) / 255.0
            changed = diff >= ROI_DIFF_THRESHOLD
        _ROI_GRAY_PREV[serial] = gray
    else:
        if isinstance(prev, bytes) and fp and len(prev) == len(fp):
            diff = sum(abs(a - b) for a, b in zip(prev, fp)) / (len(fp) * 255.0)
            changed = diff >= ROI_DIFF_THRESHOLD
        _ROI_GRAY_PREV[serial] = fp

    _GROUP_ACTIVITY_CACHE[serial] = (now, changed)
    return changed


def _adb_port(host: str) -> str:
    return host.split(":")[-1] if ":" in host else "56313"


def _tunnel_open(port: str) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1.5):
            return True
    except OSError:
        return False


def reconnect_adb(host: str) -> None:
    port = _adb_port(host)
    for serial in (f"127.0.0.1:{port}", f"localhost:{port}"):
        subprocess.run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=5)
    time.sleep(0.4)
    for h in (f"localhost:{port}", f"127.0.0.1:{port}", host):
        subprocess.run(["adb", "connect", h], capture_output=True, text=True, timeout=10)
    time.sleep(0.5)


def resolve_serial(preferred: str) -> str:
    port = _adb_port(preferred)

    def pick_device() -> str | None:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10).stdout
        found: list[str] = []
        for line in out.splitlines():
            if "\tdevice" not in line:
                continue
            serial = line.split()[0]
            if port in serial:
                found.append(serial)
        if not found:
            return None
        for s in found:
            if s.startswith("localhost"):
                return s
        return found[0]

    serial = pick_device()
    if serial and _adb_probe_port(port):
        return serial

    if _tunnel_open(port):
        reconnect_adb(preferred)
        serial = pick_device()
        if serial and _adb_probe_port(port):
            log.info("ADB 重连成功: %s", serial)
            return serial

    if not _tunnel_open(port) or not _adb_probe_port(port):
        log.warning("ADB/隧道异常 port=%s，触发自愈", port)
        root = os.path.dirname(os.path.abspath(__file__))
        heal_sh = os.path.join(root, "scripts", "tunnel-heal.sh")
        if os.name != "nt" and os.path.isfile(heal_sh):
            try:
                subprocess.run(
                    ["bash", heal_sh], cwd=root, capture_output=True, text=True, timeout=180,
                )
            except OSError:
                reconnect_adb(preferred)
        else:
            reconnect_adb(preferred)
        serial = pick_device()
        if serial and _adb_probe_port(port):
            log.info("ADB 自愈成功: %s", serial)
            return serial

    if not _tunnel_open(port):
        raise RuntimeError(
            f"SSH 隧道已断开(端口{port})，自动自愈未恢复。检查 logs/tunnel-watch.log"
        )

    reconnect_adb(preferred)
    serial = pick_device()
    if serial and _adb_probe_port(port):
        log.info("ADB 重连成功: %s", serial)
        return serial

    raise RuntimeError(
        f"ADB 端口 {port} 无可用 device。检查 VMOS 本地调试与 logs/tunnel-watch.log"
    )


def resolve_serial_optional(preferred: str, *, label: str = "") -> str | None:
    """解析 serial；隧道/设备不可用时返回 None（不抛错）。"""
    try:
        return resolve_serial(preferred)
    except (RuntimeError, subprocess.TimeoutExpired) as ex:
        log.warning("ADB 不可用 %s: %s", label or preferred, ex)
        return None


def _adb_probe_port(port: str) -> bool:
    for serial in (f"127.0.0.1:{port}", f"localhost:{port}"):
        r = subprocess.run(
            ["adb", "-s", serial, "shell", "echo", "OK"],
            capture_output=True, text=True, timeout=12,
        )
        if r.returncode == 0 and "OK" in (r.stdout or ""):
            return True
    return False


def _cleanup_stale_adb() -> None:
    try:
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            if "\toffline" not in line:
                continue
            serial = line.split()[0]
            if serial:
                subprocess.run(
                    ["adb", "disconnect", serial],
                    capture_output=True, text=True, timeout=5,
                )
    except Exception:
        pass


_TUNNEL_HEAL_LAST = 0.0
_TUNNEL_HEAL_MIN_SEC = max(30.0, float(os.environ.get("BOT_TUNNEL_HEAL_MIN_SEC", "60") or 60))


def heal_adb_tunnels(active: list[dict] | None = None, *, force: bool = False) -> bool:
    """SSH 隧道 + ADB 全链路自愈（仅 adb connect 无法修复 SSH 断线/凭证过期）。"""
    global _TUNNEL_HEAL_LAST
    if not ADB_HEAL_DURING_SEND and active:
        for bot in active:
            if not is_send_bot(bot):
                continue
            serial = str(bot.get("adbHost") or "").strip()
            if serial and listener_send_protected(serial):
                log.info("隧道全量自愈跳过：右机公告发送中")
                return False
    now = time.time()
    if not force and now - _TUNNEL_HEAL_LAST < _TUNNEL_HEAL_MIN_SEC:
        return False
    _TUNNEL_HEAL_LAST = now
    _cleanup_stale_adb()
    root = os.path.dirname(os.path.abspath(__file__))
    heal_sh = os.path.join(root, "scripts", "tunnel-heal.sh")
    if not os.path.isfile(heal_sh):
        if active:
            heal_adb_hosts(active)
        return False
    log.warning("ADB 隧道自愈：执行 tunnel-heal.sh")
    try:
        r = subprocess.run(
            ["bash", heal_sh],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        tail = (r.stdout or r.stderr or "").strip().splitlines()[-6:]
        for ln in tail:
            log.info("tunnel-heal: %s", ln[:200])
        return r.returncode == 0
    except Exception as ex:
        log.warning("tunnel-heal 失败: %s", ex)
        if active:
            heal_adb_hosts(active)
        return False


def heal_adb_hosts(active: list[dict]) -> None:
    """轻量 adb connect（隧道正常时的 offline 恢复）。"""
    seen: set[str] = set()
    need_full_heal = False
    for bot in active:
        host = str(bot.get("adbHost") or "").strip()
        if not host or host in seen:
            continue
        seen.add(host)
        port = _adb_port(host)
        if not _tunnel_open(port):
            need_full_heal = True
            continue
        try:
            out = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=10,
            ).stdout
        except Exception:
            need_full_heal = True
            continue
        has_device = any(
            port in line and "\tdevice" in line for line in out.splitlines()
        )
        has_offline = any(
            port in line and "\toffline" in line for line in out.splitlines()
        )
        if has_device and not has_offline and _adb_probe_port(port):
            continue
        if not _adb_probe_port(port):
            need_full_heal = True
            continue
        log.warning("ADB 自愈 reconnect host=%s port=%s", host, port)
        try:
            reconnect_adb(host)
        except Exception as ex:
            log.warning("ADB 自愈失败 %s: %s", host, ex)
            need_full_heal = True
    if need_full_heal:
        heal_adb_tunnels(active, force=True)


def _clicker_image_target() -> tuple[str, dict] | None:
    """左机 UI 发图目标；不可用则 None（禁止回落到右机）。"""
    if not CLICKER_SEND_IMAGES:
        return None
    cs = str(_CLICKER_DEPLOY.get("serial") or "")
    cb = _CLICKER_DEPLOY.get("bot")
    if cs and isinstance(cb, dict):
        return cs, cb
    return None


def parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    return tuple(map(int, m.groups())) if m else None


DEFAULT_KEYBOARD_SEND = (
    int(os.environ.get("BOT_KEYBOARD_SEND_X", "675")),
    int(os.environ.get("BOT_KEYBOARD_SEND_Y", "1190")),
)
INBAR_SEND = (
    int(os.environ.get("BOT_INBAR_SEND_X", "674")),
    int(os.environ.get("BOT_INBAR_SEND_Y", "1234")),
)
DEFAULT_CHAT_INPUT = (
    int(os.environ.get("BOT_INPUT_X", "360")),
    int(os.environ.get("BOT_INPUT_Y", "1234")),
)

SEND_LABEL_HINTS = ("发送", "send", "arrow", "plane", "纸飞机", "enter", "完成")
VOICE_HINTS = ("语音", "说话", "按住", "麦克风", "voice", "mic", "录音", "松手")
VOICE_RECORDING_MARKERS = ("剩余", "左滑取消", "松开", "按住说话", "录音", "取消发送", "松开发送")
EMOJI_BUTTON_HINTS = ("表情", "emoji", "sticker", "face", "Emoji")


def is_voice_button(label: str) -> bool:
    if not label:
        return False
    low = label.lower()
    return any(h in label or h in low for h in VOICE_HINTS)


def _listener_voice_ui_active(root: ET.Element | None) -> bool:
    """右机卡在语音录制条（剩余Xs / 左滑取消）。"""
    if root is None:
        return False
    texts = collect_ui_texts(root)
    return any(m in t for t in texts for m in VOICE_RECORDING_MARKERS)


def listener_cancel_voice_mode(serial: str) -> bool:
    """退出语音录制：只用系统返回，禁止点麦克风区域。"""
    root = ui_hierarchy(serial)
    if not _listener_voice_ui_active(root):
        return False
    log.warning("右机检测到语音录制态，系统返回取消(不点击)")
    listener_system_back(serial, reason="cancel-voice-record")
    return True


@dataclass
class SendCoords:
    inbar: tuple[int, int]
    keyboard: tuple[int, int]

    @classmethod
    def from_settings(cls, settings: dict[str, str]) -> SendCoords:
        def pt(kx: str, ky: str, ex: str, ey: str, dx: int, dy: int) -> tuple[int, int]:
            return (
                int(settings.get(kx) or os.environ.get(ex, str(dx))),
                int(settings.get(ky) or os.environ.get(ey, str(dy))),
            )

        return cls(
            inbar=pt("inbarSendX", "inbarSendY", "BOT_INBAR_SEND_X", "BOT_INBAR_SEND_Y", 674, 1234),
            keyboard=pt("keyboardSendX", "keyboardSendY", "BOT_KEYBOARD_SEND_X", "BOT_KEYBOARD_SEND_Y", 675, 1190),
        )


def listener_pinned_send_pair(
    settings: dict[str, str] | None = None,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """右机钉死：内联栏发送键 + 键盘纸飞机（W49 截图红圈）。"""
    inbar = pinned_xy("listener", "send")
    kb = pinned_xy("listener", "keyboard_send")
    coords = SendCoords.from_settings(settings or {})
    if not inbar:
        if settings:
            inbar = (
                int(settings.get("inbarSendX") or LISTENER_SEND_X),
                int(settings.get("inbarSendY") or LISTENER_SEND_Y),
            )
        else:
            inbar = (LISTENER_SEND_X, LISTENER_SEND_Y)
    if not kb:
        kb = coords.keyboard
    return inbar, kb


def listener_keyboard_visible(serial: str, snap: UiSnapshot | None = None) -> bool:
    if ime_family(serial) == "other":
        return True
    root = snap.root if snap else ui_hierarchy(serial)
    if root is None:
        return False
    sh = screen_height(root)
    band = collect_ui_texts_in_band(root, int(sh * 0.70), sh - 8)
    return any(
        t in ("QWERTY", "分词", "符", "123", "?123") or "Gboard" in t
        for t in band
    )


def listener_hide_keyboard(serial: str, *, reason: str = "") -> bool:
    """右机：收起 Gboard/本地键盘，恢复全屏读聊天气泡（不点输入框）。"""
    if listener_send_protected(serial):
        return False
    if not LISTENER_HIDE_KEYBOARD or not is_listener_send_only_serial(serial):
        return False
    snap = ui_snapshot(serial, chat=False)
    keyboard_up = listener_keyboard_visible(serial, snap)
    wrong_ime = ime_family(serial) == "other"
    if not keyboard_up and not wrong_ime:
        return False
    tag = reason or ("gboard" if keyboard_up else "wrong_ime")
    log.info("右机收起键盘 serial=%s reason=%s ime=%s", serial, tag, ime_family(serial))
    if wrong_ime:
        ensure_adb_ime(serial)
    try:
        adb_run(serial, "shell", "cmd", "input_method", "hide")
    except Exception:
        pass
    dismiss_soft_keyboard(serial)
    try:
        adb_run(serial, "shell", "input", "keyevent", "111")
    except Exception:
        pass
    w(0.1, 0.05)
    invalidate_ui_cache(serial)
    _SNAP_CACHE.pop(serial, None)
    return True


def listener_active_send_xy(
    serial: str,
    settings: dict[str, str] | None = None,
    snap: UiSnapshot | None = None,
) -> tuple[int, int]:
    inbar, kb = listener_pinned_send_pair(settings)
    # 钉死模式只用内联栏蓝箭头，不因键盘弹出改点纸飞机（防坐标乱跳）
    if LISTENER_SEND_TAP_ONLY and is_listener_send_only_serial(serial):
        return inbar
    if listener_keyboard_visible(serial, snap):
        return kb
    return inbar


def _find_composer_emoji_center(root: ET.Element | None) -> tuple[int, int] | None:
    """输入栏同行表情钮 😀（仅读屏定位，不点击）。"""
    if root is None:
        return None
    sh = screen_height(root)
    y_lo = int(sh * 0.52)
    best: tuple[int, int, int] | None = None
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        rid = (node.attrib.get("resource-id") or "").lower()
        label = node_label(node)
        low = label.lower()
        if not any(h in rid or h in label or h in low for h in EMOJI_BUTTON_HINTS):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[1] < y_lo:
            continue
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        if best is None or b[2] > best[0]:
            best = (b[2], cx, cy)
    return (best[1], best[2]) if best else None


def _mic_at_xy(root: ET.Element, sx: int, sy: int, tol: int = 90) -> bool:
    for node in root.iter("node"):
        rid = (node.attrib.get("resource-id") or "").lower()
        label = node_label(node)
        if "imageviewaudio" not in rid and not is_voice_button(label):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        if _near_xy(cx, cy, (sx, sy), tol):
            return True
    return False


def _send_icon_at_pin(root: ET.Element, sx: int, sy: int, tol: int = 80) -> bool:
    """钉死发送位上是蓝箭头（非麦克风）；dump 常漏 clickable，ImageView 也算。"""
    for node in root.iter("node"):
        rid = (node.attrib.get("resource-id") or "").lower()
        label = node_label(node)
        if is_voice_button(label) or "imageviewaudio" in rid or "mic" in rid:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        if not _near_xy(cx, cy, (sx, sy), tol):
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        if "send" in rid or is_send_label(label):
            return True
        cls = node.attrib.get("class", "")
        if w <= 140 and h <= 140:
            if node.attrib.get("clickable") == "true":
                return True
            if "Image" in cls:
                return True
    return False


def _near_xy(x: int, y: int, pt: tuple[int, int], tol: int) -> bool:
    return abs(x - pt[0]) <= tol and abs(y - pt[1]) <= tol


def clicker_img_flow_begin(serial: str) -> None:
    if is_clicker_serial(serial) and CLICKER_IMG_TAP_ONLY:
        _CLICKER_IMG_FLOW_SERIALS.add(serial)


def clicker_img_flow_end(serial: str) -> None:
    _CLICKER_IMG_FLOW_SERIALS.discard(serial)


def _clicker_img_flow_active(serial: str) -> bool:
    return is_clicker_serial(serial) and serial in _CLICKER_IMG_FLOW_SERIALS


def clicker_tap_pinned(
    serial: str,
    x: int,
    y: int,
    key: str,
    *,
    invalidate: bool = True,
) -> None:
    """左机发图唯一合法 tap 入口（须带 clicker-pinned-* purpose）。"""
    # +/附件/相册勾选必须同步 tap；fire 异步会导致验真抢跑、附件栏假失败
    sync_key = (
        key.startswith("chat_plus")
        or key.startswith("attach")
        or key.startswith("gallery")
    )
    if (
        _clicker_img_flow_active(serial)
        and CLICKER_SEND_IMAGES
        and not sync_key
    ):
        clicker_fire_tap(serial, x, y)
        return
    adb_tap_raw(serial, x, y, invalidate=invalidate, purpose=f"clicker-pinned-{key}")


def clicker_forbidden_tap(serial: str, x: int, y: int, purpose: str = "") -> bool:
    """左机发图流程：仅 purpose=clicker-pinned-* 时允许 tap。"""
    if not CLICKER_IMG_TAP_ONLY or not _clicker_img_flow_active(serial):
        return False
    if purpose.startswith("clicker-pinned-"):
        return False
    log.warning("左机发图禁止乱点 @(%d,%d) purpose=%s", x, y, purpose or "other")
    return True


def listener_forbidden_tap(serial: str, x: int, y: int, purpose: str = "") -> bool:
    """右机 LISTENER：仅钉死发送键或钉死输入框（composer-focus）允许 tap。"""
    role = serial_role(serial)
    if role == "LISTENER" or BOT_ROLE == "LISTENER":
        if purpose in ("pinned-send", "composer-focus", "listener-fire"):
            return False
        return True
    if not is_listener_send_only_serial(serial) or not LISTENER_ZERO_NAV:
        return False
    if purpose == "composer-focus":
        inp = pinned_xy("listener", "input")
        if inp and _near_xy(x, y, inp, LISTENER_SEND_TAP_TOL):
            return False
        return True
    if purpose != "pinned-send":
        return True
    inbar, kb = listener_pinned_send_pair()
    tol = LISTENER_SEND_TAP_TOL
    if _near_xy(x, y, inbar, tol) or _near_xy(x, y, kb, tol):
        return False
    log.warning("右机发送坐标偏离钉死位 @(%d,%d)", x, y)
    return True


def _listener_blue_send_ready(
    snap: UiSnapshot | None,
    sx: int,
    sy: int,
    *,
    allow_draft: bool = True,
) -> bool:
    """内联栏蓝箭头已出现；draft 优先，避免 emoji 误判挡住发送。"""
    if allow_draft and LISTENER_SEND_TAP_ONLY and snap is not None:
        draft = re.sub(r"\s+", "", snap.draft or "")
        if len(draft) >= 2:
            return True
    if snap is None or snap.root is None:
        return False
    if _listener_voice_ui_active(snap.root):
        return False
    root = snap.root
    if _mic_at_xy(root, sx, sy):
        return False
    if _send_icon_at_pin(root, sx, sy):
        return True
    return False


def listener_prepare_b64_outgoing(serial: str, text: str) -> bool:
    """右机 b64 灌字；先钉死聚焦输入框，灌字后再读 draft。"""
    announce = _outgoing_is_announce(text)
    ensure_adb_ime(serial)
    focus = pinned_xy("listener", "input") or (360, 1234)
    tap_only = is_listener_send_only_serial(serial) and LISTENER_SEND_TAP_ONLY
    if tap_only and focus:
        adb_tap_raw(serial, focus[0], focus[1], purpose="composer-focus")
        w(0.02 if LISTENER_SEND_FIRE else 0.1, 0.01)
    outgoing_clean = re.sub(r"\s+", "", message_snip(text))
    # 公告禁止 adb-clip paste（会注入字面量 set / 与脏 draft 拼接）；仅 b64
    if announce:
        listener_sanitize_composer(serial, reason="pre-announce-b64", force=True)
        adb_clear_input_fast(serial, instant=False, announce=True)
    b64_instant = bool(LISTENER_SEND_FIRE and tap_only and LISTENER_TRUST_SEND and not announce)
    for attempt in range(3 if announce else 2):
        if attempt:
            w(0.12, 0.06)
            if tap_only and focus:
                adb_tap_raw(serial, focus[0], focus[1], purpose="composer-focus")
                w(0.08, 0.04)
        if announce or attempt > 0:
            adb_clear_input_fast(serial, instant=not announce and bool(LISTENER_SEND_FIRE and tap_only), announce=announce)
        adb_send_b64(serial, text, fast=True, instant=b64_instant, announce=announce)
        if LISTENER_SEND_FIRE and tap_only and LISTENER_TRUST_SEND and not announce:
            return True
        w(0.08 if announce else 0.04, 0.03)
        snap = ui_snapshot(serial, chat=False, force=True)
        draft = re.sub(r"\s+", "", snap.draft or "")
        if len(draft) >= max(2, min(8, len(outgoing_clean) // 3)):
            if announce:
                log.info("公告灌字 [b64] snip=%s", message_snip(text)[:32])
            return True
        if attempt >= 1 and not announce and _set_clipboard_text(serial, text):
            adb_tap_raw(serial, focus[0], focus[1], purpose="composer-focus")
            w(0.06, 0.03)
            try:
                adb_run(serial, "shell", "input", "keyevent", "279")  # KEYCODE_PASTE
                w(0.18 if announce else 0.15, 0.08)
                snap = ui_snapshot(serial, chat=False, force=True)
                draft = re.sub(r"\s+", "", snap.draft or "")
                if len(draft) >= max(2, min(8, len(outgoing_clean) // 3)):
                    return True
            except Exception:
                pass
        log.warning(
            "b64 灌字 draft 未就绪 serial=%s attempt=%s draft=%r announce=%s",
            serial, attempt + 1, (snap.draft or "")[:24], announce,
        )
    return False


def wuwu_send_button_xy(root: ET.Element | None) -> tuple[int, int] | None:
    """55M 内联栏蓝发送键（resource-id imageViewSend / imageSend）。"""
    if root is None:
        return None
    sh = screen_height(root)
    min_y = int(sh * 0.78)
    for prefer in ("imageViewSend", "imageSend"):
        best: tuple[int, int, int] | None = None
        for node in root.iter("node"):
            rid = node.attrib.get("resource-id") or ""
            if prefer not in rid:
                continue
            if prefer == "imageSend" and "imageViewSend" in rid:
                continue
            b = parse_bounds(node.attrib.get("bounds", ""))
            if not b or b[1] < min_y:
                continue
            cx, cy = node_center(b)
            score = b[2]
            if best is None or score > best[0]:
                best = (score, cx, cy)
        if best:
            return (best[1], best[2])
    return None


def wuwu_composer_input_xy(root: ET.Element | None) -> tuple[int, int] | None:
    if root is None:
        return None
    for node in root.iter("node"):
        rid = node.attrib.get("resource-id") or ""
        if "editTextMessage" not in rid:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b:
            return node_center(b)
    return None


def listener_resolve_send_xy(
    serial: str,
    settings: dict[str, str] | None = None,
    snap: UiSnapshot | None = None,
) -> tuple[int, int]:
    """右机发送键：dump 识别 imageViewSend 优先，否则钉死坐标。"""
    root = snap.root if snap else None
    if root is None:
        root = ui_hierarchy(serial)
    pt = wuwu_send_button_xy(root)
    if pt:
        return pt
    return listener_pinned_send_xy(settings, snap)


def listener_tap_pinned_send_now(
    serial: str,
    bot: dict | None,
    settings: dict[str, str] | None = None,
) -> tuple[int, int]:
    """钉死坐标立即点发送；fire 模式走专用线程，禁止发前 dump。"""
    if LISTENER_SEND_FIRE and is_listener_send_only_serial(serial, bot):
        sx, sy = listener_fire_send_tap(serial, settings)
        log.info("右机立即点发送 @(%d,%d) [fire-thread]", sx, sy)
        return sx, sy
    sx, sy = listener_pinned_send_xy(settings, None)
    adb_tap_listener_send(serial, bot, sx, sy)
    log.info("右机立即点发送 @(%d,%d) [fire]", sx, sy)
    return sx, sy


def listener_tap_blue_send_once(
    serial: str,
    bot: dict | None,
    settings: dict[str, str] | None,
    *,
    wait_draft: bool = True,
    allow_pinned_fallback: bool = False,
) -> bool:
    """右机唯一允许 tap：蓝发送箭头已出现才点一次。"""
    if LISTENER_PINNED_SEND and LISTENER_SEND_FIRE and is_listener_send_only_serial(serial):
        listener_tap_pinned_send_now(serial, bot, settings)
        return True
    sx, sy = listener_active_send_xy(serial, settings, None)
    snap: UiSnapshot | None = None
    snap = ui_snapshot(serial, chat=False, force=True)
    sx, sy = listener_active_send_xy(serial, settings, snap)
    if (
        snap.inbar_send
        and is_listener_send_only_serial(serial)
        and not (LISTENER_SEND_TAP_ONLY and LISTENER_PINNED_SEND)
    ):
        sx, sy = snap.inbar_send
    if _listener_blue_send_ready(snap, sx, sy):
        adb_tap_listener_send(serial, bot, sx, sy)
        log.info("右机点击蓝发送箭头 @(%d,%d) [fast]", sx, sy)
        return True
    polls = LISTENER_BLUE_SEND_POLLS if wait_draft else 1
    for i in range(polls):
        if i:
            w(0.02, 0.01)
        snap = ui_snapshot(serial, chat=False, force=True)
        sx, sy = listener_active_send_xy(serial, settings, snap)
        if (
            snap.inbar_send
            and is_listener_send_only_serial(serial)
            and not (LISTENER_SEND_TAP_ONLY and LISTENER_PINNED_SEND)
        ):
            sx, sy = snap.inbar_send
        if _listener_blue_send_ready(snap, sx, sy):
            break
    if snap is None or not _listener_blue_send_ready(snap, sx, sy):
        if allow_pinned_fallback and is_group_chat_activity(serial):
            listener_tap_pinned_send_now(serial, bot, settings)
            return True
        draft_hint = (snap.draft or "")[:24] if snap else ""
        log.warning(
            "右机蓝箭头未出现，禁止点击 @(%d,%d) draft=%r",
            sx, sy, draft_hint,
        )
        return False
    adb_tap_listener_send(serial, bot, sx, sy)
    log.info("右机点击蓝发送箭头 @(%d,%d)", sx, sy)
    return True


def _listener_send_button_ready(
    serial: str,
    snap: UiSnapshot | None,
    sx: int,
    sy: int,
) -> bool:
    return _listener_blue_send_ready(snap, sx, sy)


def listener_pinned_send_xy(
    settings: dict[str, str] | None = None,
    snap: UiSnapshot | None = None,
) -> tuple[int, int]:
    """右机 LISTENER：内联栏发送键坐标（禁止 u2 动态扫描）。"""
    inbar, _ = listener_pinned_send_pair(settings)
    return inbar


def resolve_listener_send_xy(
    bot: dict,
    settings: dict[str, str] | None,
    snap: UiSnapshot | None,
) -> tuple[int, int]:
    if is_send_only_listener(bot):
        return listener_pinned_send_xy(settings, snap)
    if snap and (snap.inbar_send or snap.keyboard_send):
        return snap.inbar_send or snap.keyboard_send  # type: ignore
    return listener_pinned_send_xy(settings, snap)


def listener_may_tap(serial: str, bot: dict | None, purpose: str) -> bool:
    """右机零导航：仅允许钉死发送键一次点击。"""
    if not is_send_only_listener(bot) and not is_listener_send_only_serial(serial, bot):
        return True
    if not LISTENER_ZERO_NAV:
        return True
    if not LISTENER_SEND_TAP_ONLY:
        return purpose == "pinned-send"
    return purpose in ("pinned-send", "composer-focus")


@dataclass
class UiSnapshot:
    texts: list[str]
    input_xy: tuple[int, int] | None
    input_bounds: tuple[int, int, int, int] | None
    draft: str
    inbar_send: tuple[int, int] | None
    keyboard_send: tuple[int, int] | None
    chat_nodes: list[ChatTextNode]
    root: ET.Element | None = None


def node_center(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def node_label(node: ET.Element) -> str:
    return (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()


def is_send_label(label: str) -> bool:
    if not label or is_voice_button(label):
        return False
    low = label.lower()
    return label in ("发送", "Send") or any(h in label or h in low for h in SEND_LABEL_HINTS)


def find_labeled_send(
    root: ET.Element,
    min_y: int,
    max_y: int | None = None,
    min_x: int = 0,
) -> tuple[int, int] | None:
    for node in root.iter("node"):
        label = node_label(node)
        if not is_send_label(label):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        if b[1] >= min_y and b[0] >= min_x and (max_y is None or b[3] <= max_y):
            return node_center(b)
    return None


def find_inbar_send(root: ET.Element, input_bounds: tuple[int, int, int, int] | None) -> tuple[int, int] | None:
    """输入栏同行最右侧可点击键（蓝箭头 / imageViewSend）"""
    pt = wuwu_send_button_xy(root)
    if pt:
        return pt
    if not input_bounds:
        return None
    x1, y1, x2, y2 = input_bounds
    for node in root.iter("node"):
        rid = node.attrib.get("resource-id") or ""
        if "imageViewAudio" in rid:
            continue
        if "send" not in rid.lower():
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        bx1, by1, bx2, by2 = b
        if bx1 >= 560 and by1 >= y1 - 40 and by2 <= y2 + 50:
            return node_center(b)
    labeled = find_labeled_send(root, y1 - 40, y2 + 50, min_x=560)
    if labeled:
        return labeled
    candidates: list[tuple[int, int, int]] = []
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        bx1, by1, bx2, by2 = b
        if bx1 >= 560 and by1 >= y1 - 40 and by2 <= y2 + 50:
            candidates.append((bx2, (bx1 + bx2) // 2, (by1 + by2) // 2))
    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        return (candidates[0][1], candidates[0][2])
    return None


def find_keyboard_send(root: ET.Element, input_bounds: tuple[int, int, int, int] | None) -> tuple[int, int] | None:
    """键盘区域右下角发送键（纸飞机）"""
    input_bottom = input_bounds[3] if input_bounds else 764
    labeled = find_labeled_send(root, input_bottom + 60)
    if labeled and labeled[1] > input_bottom + 60:
        return labeled
    keyboard: list[tuple[int, int, int]] = []
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        if is_voice_button(node_label(node)):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        bx1, by1, bx2, by2 = b
        bw, bh = bx2 - bx1, by2 - by1
        if by1 <= input_bottom + 40:
            continue
        if bx1 < 400 or bw > 200 or bh > 200:
            continue
        keyboard.append((by2, bx2, (bx1 + bx2) // 2, (by1 + by2) // 2))
    if keyboard:
        keyboard.sort(key=lambda c: (c[0], c[1]), reverse=True)
        return (keyboard[0][2], keyboard[0][3])
    return None


def collect_send_strategies(snap: UiSnapshot, coords: SendCoords) -> list[tuple[str, int, int]]:
    """发送策略：元素定位 → Enter 前需坐标；返回唯一点击目标"""
    out: list[tuple[str, int, int]] = []
    seen: set[tuple[int, int]] = set()

    def add(name: str, pt: tuple[int, int] | None) -> None:
        if not pt or pt in seen:
            return
        seen.add(pt)
        out.append((name, pt[0], pt[1]))

    if snap.inbar_send and snap.inbar_send[1] <= CHAT_INPUT_Y_MAX + 40:
        add("元素-输入栏发送", snap.inbar_send)
    add("兜底-输入栏坐标", coords.inbar)
    if not LISTENER_FAST_SEND:
        if snap.keyboard_send:
            add("元素-键盘发送", snap.keyboard_send)
        add("兜底-键盘坐标", coords.keyboard)
    return out


def _ui_snapshot_from_root(root: ET.Element | None, *, chat: bool = True) -> UiSnapshot:
    if root is None:
        return UiSnapshot([], None, None, "", None, None, [], None)

    texts: list[str] = []
    input_xy: tuple[int, int] | None = None
    input_bounds: tuple[int, int, int, int] | None = None
    input_draft = ""
    sh = screen_height(root)
    chat_top, chat_bottom = chat_message_y_bounds(root, sh=sh)
    chat_nodes: list[ChatTextNode] = []
    chat_seen: set[tuple[str, int, int]] = set()

    for node in root.iter("node"):
        cls = node.attrib.get("class", "")
        bounds = node.attrib.get("bounds", "")
        label = node_label(node)
        if bounds:
            b = parse_bounds(bounds)
            if b:
                x1, y1, x2, y2 = b
                if "EditText" in cls:
                    input_xy = ((x1 + x2) // 2, (y1 + y2) // 2)
                    input_bounds = b
                    chat_top, chat_bottom = chat_message_y_bounds(
                        root, sh=sh, input_bounds=b,
                    )
                    cleaned = re.sub(r"\s+", "", html.unescape(label))
                    if cleaned and cleaned not in ("输入消息",):
                        input_draft = cleaned
                if chat:
                    t = label.strip()
                    if t and t not in IGNORE_TEXT and len(t) <= 120:
                        cy = (y1 + y2) // 2
                        if chat_top <= cy <= chat_bottom:
                            key = (t, cy // 8, x1 // 12)
                            if key not in chat_seen:
                                chat_seen.add(key)
                                chat_nodes.append(ChatTextNode(t, x1, y1, x2, y2))
        for attr in ("text", "content-desc"):
            val = (node.attrib.get(attr) or "").strip()
            if val and val not in IGNORE_TEXT and len(val) <= 120:
                texts.append(val)

    if chat and chat_nodes:
        chat_nodes.sort(key=lambda n: (n.y1, n.x1))
    inbar = find_inbar_send(root, input_bounds)
    keyboard = find_keyboard_send(root, input_bounds)
    return UiSnapshot(
        texts, input_xy, input_bounds, input_draft, inbar, keyboard, chat_nodes, root,
    )


def _ui_snapshot_build(serial: str, *, force: bool = False, chat: bool = True) -> UiSnapshot:
    t0 = time.perf_counter()
    root = _ui_hierarchy_impl(serial, force=force) if UI_COLLECTOR_ENABLED else ui_hierarchy(serial, force=force)
    snap = _ui_snapshot_from_root(root, chat=chat)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if elapsed_ms > 450:
        log.info(
            "ui_snapshot %dms engine=%s nodes=%d chat=%s",
            elapsed_ms, "u2" if serial in _U2_DEVICES else "adb",
            len(snap.chat_nodes), chat,
        )
    _SNAP_CACHE[serial] = (time.time(), snap)
    return snap


def ui_snapshot(
    serial: str,
    *,
    force: bool = False,
    chat: bool = True,
    channel: str = "default",
) -> UiSnapshot:
    now = time.time()
    if not force:
        cached = _SNAP_CACHE.get(serial)
        if cached and now - cached[0] < UI_CACHE_TTL:
            snap = cached[1]
            if chat or not snap.chat_nodes:
                return snap
    if UI_COLLECTOR_ENABLED:
        return _ui_collector_snapshot(serial, force=force, chat=chat, channel=channel)
    return _ui_snapshot_build(serial, force=force, chat=chat)


def probe_send_targets(serial: str, settings: dict[str, str] | None = None) -> dict[str, Any]:
    """供控制面板探测：当前屏幕识别到的发送键"""
    coords = SendCoords.from_settings(settings or {})
    snap = ui_snapshot(serial)
    strategies = collect_send_strategies(snap, coords)
    return {
        "input": {"x": snap.input_xy[0], "y": snap.input_xy[1]} if snap.input_xy else None,
        "inbarSend": {"x": snap.inbar_send[0], "y": snap.inbar_send[1]} if snap.inbar_send else None,
        "keyboardSend": {"x": snap.keyboard_send[0], "y": snap.keyboard_send[1]} if snap.keyboard_send else None,
        "fallbackInbar": {"x": coords.inbar[0], "y": coords.inbar[1]},
        "fallbackKeyboard": {"x": coords.keyboard[0], "y": coords.keyboard[1]},
        "strategies": [{"name": n, "x": x, "y": y} for n, x, y in strategies],
        "draft": snap.draft[:80],
    }


def find_send_button(
    root: ET.Element,
    input_bounds: tuple[int, int, int, int] | None,
    has_draft: bool = False,
) -> tuple[int, int] | None:
    if has_draft:
        pt = find_inbar_send(root, input_bounds)
        if pt:
            return pt
    return find_keyboard_send(root, input_bounds) or (DEFAULT_KEYBOARD_SEND if has_draft else None)


def send_button_xy(root: ET.Element, input_bounds: tuple[int, int, int, int] | None) -> tuple[int, int] | None:
    return find_send_button(root, input_bounds, has_draft=False)


def ui_dump(serial: str) -> tuple[list[str], tuple[int, int] | None, tuple[int, int] | None, str]:
    snap = ui_snapshot(serial)
    send_xy = snap.inbar_send or snap.keyboard_send
    return snap.texts, snap.input_xy, send_xy, snap.draft


ADB_IMES = (
    "com.android.adbkeyboard/.AdbIME",
    "com.github.uiautomator/.AdbKeyboard",
    "com.zx.adbkeyboard/.AdbIME",
)


def ensure_adb_ime(serial: str) -> str | None:
    ensure_adb_keyboard_installed(serial)
    pkgs = adb_run(serial, "shell", "pm", "list", "packages")
    listed = adb_run(serial, "shell", "ime", "list", "-s")
    for ime in ADB_IMES:
        pkg = ime.split("/")[0]
        if pkg not in pkgs and ime not in listed:
            continue
        if ime not in listed:
            adb_run(serial, "shell", "ime", "enable", ime)
            w(0.12, 0.06)
        adb_run(serial, "shell", "ime", "enable", ime)
        adb_run(serial, "shell", "ime", "set", ime)
        w(0.25, 0.08)
        current = adb_run(serial, "shell", "settings", "get", "secure", "default_input_method")
        if pkg in current:
            return ime
    return None


def active_adb_ime(serial: str) -> str | None:
    current = adb_run(serial, "shell", "settings", "get", "secure", "default_input_method")
    for ime in ADB_IMES:
        if ime in current:
            return ime
    return ensure_adb_ime(serial)


def ime_family(serial: str) -> str:
    ime = active_adb_ime(serial) or ""
    if "uiautomator" in ime:
        return "uiautomator"
    if "adbkeyboard" in ime:
        return "senzhk"
    return "other"


def ensure_adb_keyboard_installed(serial: str) -> bool:
    pkgs = adb_run(serial, "shell", "pm", "list", "packages")
    if "com.android.adbkeyboard" in pkgs:
        return True
    apk = "/data/local/tmp/ADBKeyboard.apk"
    if "No such file" in adb_run(serial, "shell", "ls", apk):
        adb_run(
            serial, "shell", "curl", "-fsSL", "-o", apk,
            "https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk",
        )
    out = adb_run(serial, "shell", "pm", "install", "-r", apk)
    return "Success" in out


def ensure_trime_installed(serial: str) -> bool:
    """安装同文输入法 Trime（人工/cloud 手打用；自动化仍走 ADB Keyboard）。"""
    pkgs = adb_run(serial, "shell", "pm", "list", "packages")
    if TRIME_PKG in pkgs:
        return True
    apk = "/data/local/tmp/trime.apk"
    if "No such file" in adb_run(serial, "shell", "ls", apk):
        adb_run(serial, "shell", "curl", "-fsSL", "-L", "-o", apk, TRIME_APK_URL)
    out = adb_run(serial, "shell", "pm", "install", "-r", apk)
    ok = "Success" in out
    if ok:
        log.info("Trime 已安装 serial=%s", serial)
    else:
        log.warning("Trime 安装失败: %s", out[:200])
    return ok


def set_active_ime(serial: str, ime: str) -> bool:
    try:
        adb_run(serial, "shell", "ime", "enable", ime)
        adb_run(serial, "shell", "ime", "set", ime)
        w(0.2, 0.08)
        cur = adb_run(serial, "shell", "settings", "get", "secure", "default_input_method")
        return ime.split("/")[0] in cur
    except Exception:
        return False


def benchmark_ime_send(serial: str, sample: str | None = None, *, live_send: bool | None = None) -> dict[str, Any]:
    """对比 Trime / ADB Keyboard / u2 填字+发送耗时（ms）。默认 dry-run 不向群内真发。"""
    live = live_send if live_send is not None else os.environ.get("BOT_BENCH_LIVE_SEND", "").lower() in ("1", "true", "yes")
    text = sample or "user probe bal 100.00 code UID-TEST"
    group = os.environ.get("BOT_TARGET_GROUP", "苍井空测试").strip()
    bench_bot = {
        "id": BOT_LISTENER_ID,
        "botName": "bench",
        "associatedGroup": group,
    }
    _DEPLOY_SERIAL_ROLE[serial] = "LISTENER"
    if os.environ.get("BOT_ALLOW_LISTENER_NAV") == "1":
        ensure_group_chat(serial, bench_bot)
    snap = ui_snapshot(serial, chat=False)
    ix, iy = resolve_chat_input_xy(snap, None, None)
    results: dict[str, Any] = {"serial": serial, "modes": {}}

    def run_mode(name: str, fn) -> None:
        t0 = time.perf_counter()
        try:
            ok = fn()
            ms = int((time.perf_counter() - t0) * 1000)
            results["modes"][name] = {"ok": bool(ok), "ms": ms}
        except Exception as ex:
            results["modes"][name] = {"ok": False, "ms": -1, "error": str(ex)[:80]}

    ensure_adb_ime(serial)
    texts0, draft0 = snap.texts, snap.draft or ""

    def adb_b64_send() -> bool:
        adb_tap_raw(serial, ix, iy)
        adb_clear_input_fast(serial)
        adb_send_b64(serial, text, fast=True)
        w(0.15, 0.06)
        if not live:
            snap2 = ui_snapshot(serial, chat=False)
            ok = text[:12].replace(" ", "") in _norm_cmp("".join(snap2.texts) + (snap2.draft or ""))
            adb_clear_input_fast(serial)
            return ok
        return send_chat_reply_fast_adb_listener(
            serial, bench_bot, text, (ix, iy), None, {},
            texts_before=texts0, draft_before=draft0,
        )

    def u2_send() -> bool:
        if not live:
            adb_tap_raw(serial, ix, iy)
            adb_clear_input_fast(serial)
            adb_send_b64(serial, text, fast=True)
            w(0.2, 0.08)
            snap2 = ui_snapshot(serial, chat=False)
            ok = text[:12].replace(" ", "") in _norm_cmp("".join(snap2.texts) + (snap2.draft or ""))
            adb_clear_input_fast(serial)
            return ok
        return send_chat_reply_fast_u2(serial, text, texts0, draft0)

    def trime_plus_adb_send() -> bool:
        ensure_trime_installed(serial)
        trime_ime = f"{TRIME_PKG}/.Trime"
        listed = adb_run(serial, "shell", "ime", "list", "-s")
        if trime_ime not in listed:
            for line in listed.splitlines():
                if TRIME_PKG in line:
                    trime_ime = line.strip()
                    break
        set_active_ime(serial, trime_ime)
        w(0.25, 0.1)
        set_active_ime(serial, "com.android.adbkeyboard/.AdbIME")
        adb_tap_raw(serial, ix, iy)
        adb_clear_input_fast(serial)
        adb_send_b64(serial, text, fast=True)
        w(0.15, 0.06)
        if not live:
            snap2 = ui_snapshot(serial, chat=False)
            ok = text[:12].replace(" ", "") in _norm_cmp("".join(snap2.texts) + (snap2.draft or ""))
            adb_clear_input_fast(serial)
            return ok
        adb_run(serial, "shell", "input", "keyevent", "66")
        w(0.25, 0.1)
        snap2 = ui_snapshot(serial, chat=False)
        return send_succeeded(snap2.texts, snap2.draft or "", text, texts0, draft0)

    run_mode("adb_b64", adb_b64_send)
    run_mode("u2", u2_send)
    run_mode("trime_adb_hybrid", trime_plus_adb_send)
    results["active_ime"] = adb_run(serial, "shell", "settings", "get", "secure", "default_input_method").strip()
    results["live_send"] = live
    return results


def recover_listener_to_group(serial: str, group: str | None = None) -> bool:
    """维护用：临时允许右机最小路径回目标群（setup/bench）。"""
    g = (group or os.environ.get("BOT_TARGET_GROUP", "苍井空测试")).strip()
    bot = {"id": BOT_LISTENER_ID, "botName": "recover", "associatedGroup": g}
    prev = os.environ.get("BOT_ALLOW_LISTENER_NAV")
    os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
    try:
        ok = recover_listener_to_group_minimal(serial, bot)
        ctx = describe_screen_context(ui_hierarchy(serial), bot, serial)
        log.info("右机回群 %s → %s", g, "OK" if ok else ctx.summary())
        return ok
    finally:
        if prev is None:
            os.environ.pop("BOT_ALLOW_LISTENER_NAV", None)
        else:
            os.environ["BOT_ALLOW_LISTENER_NAV"] = prev


def _probe_dedup_key(sender: str, cmd: str) -> str:
    return f"{(sender or '').strip().lower()}|{normalize_cmd_key(cmd)}"


def command_dedup_window(cmd: str) -> float:
    """仅探针/读屏抢同一气泡时的亚秒防双发窗口。"""
    return CMD_CLAIM_RACE_SEC


def try_claim_command(
    bot_id: str, sender: str, cmd: str, cmd_y: int = 0,
) -> bool:
    """探针/读屏抢同一气泡；下注永远认领。"""
    c = (cmd or "").strip()
    snd = (sender or "").strip()
    if not c:
        return False
    if is_bet_command(c):
        return True
    if cmd_y > 0:
        key = f"{bot_id}|{snd.lower()}|{c}|{cmd_y // CMD_Y_BUCKET}"
    else:
        key = f"{bot_id}|{_probe_dedup_key(snd, c)}"
    now = time.time()
    win = CMD_CLAIM_RACE_SEC
    if now - _COMMAND_CLAIM.get(key, 0) < win:
        return False
    _COMMAND_CLAIM[key] = now
    return True


def drain_probe_events() -> list[dict[str, Any]]:
    return bot_probe.drain_events()


def probe_events_pending() -> bool:
    return bot_probe.events_pending()


def start_probe_server() -> None:
    bot_probe.start_probe_server(port=PROBE_PORT, enabled=PROBE_ENABLED)


def setup_probe_adb_reverse(serial: str) -> None:
    """云手机 → VPS 探针端口转发。"""
    if not PROBE_ENABLED:
        return
    try:
        adb_run(serial, "reverse", f"tcp:{PROBE_PORT}", f"tcp:{PROBE_PORT}")
        log.info("adb reverse 探针 %s tcp:%d", serial, PROBE_PORT)
    except Exception as ex:
        log.warning("adb reverse 探针失败 %s: %s", serial, ex)


def enable_probe_accessibility(serial: str) -> bool:
    svc = "com.w49.chatprobe/com.w49.chatprobe.ProbeAccessibilityService"
    try:
        adb_run(
            serial, "shell", "settings", "put", "secure", "enabled_accessibility_services", svc,
        )
        adb_run(serial, "shell", "settings", "put", "secure", "accessibility_enabled", "1")
        out = adb_run(serial, "shell", "settings", "get", "secure", "enabled_accessibility_services")
        ok = "chatprobe" in out
        log.info("探针无障碍 %s", "已启用" if ok else "需手动开启")
        return ok
    except Exception as ex:
        log.warning("启用探针无障碍失败: %s", ex)
        return False


def collect_ime_send_attempts(outgoing: str) -> list[tuple[str, list[str]]]:
    """ADB Keyboard 触发发送（禁止整段 TEXT+\\n，55M 会留在输入框）"""
    return [
        ("KEYEVENT_66", ["shell", "input", "keyevent", "66"]),
        ("IME-KEYCODE_66", ["shell", "am", "broadcast", "-a", "ADB_KEYBOARD_INPUT_KEYCODE", "--ei", "code", "66"]),
        ("IME-SMART_ENTER", ["shell", "am", "broadcast", "-a", "ADB_KEYBOARD_SMART_ENTER"]),
        ("IME-EDITOR_SEND", ["shell", "am", "broadcast", "-a", "ADB_KEYBOARD_EDITOR_CODE", "--ei", "code", "4"]),
    ]


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _norm_announce(s: str) -> str:
    """公告气泡比对：去空白/括号/常见 emoji。"""
    t = re.sub(r"[\U00010000-\U0010ffff]", "", s or "")
    t = re.sub(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]", "", t)
    return re.sub(r"[\s\[\]【】禁🚫:：|｜\-—]", "", t)


def _norm_cmp(s: str) -> str:
    """比对输入框草稿：忽略空白与常见标点差异"""
    return re.sub(r"[\s:：.,，!！?？、\-+()（）]", "", s)


def message_snip(text: str) -> str:
    """跳过 emoji，取可用于屏幕比对的文字片段"""
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    cleaned = re.sub(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]", "", cleaned)
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.*+\-]", "", cleaned)
    return cleaned[:16]


def break_im_auto_links(text: str) -> str:
    """打断 IM 自动识别为可点超链的片段（仍可读，避免误触进开奖页）。"""
    if not text or not LISTENER_BREAK_IM_LINKS:
        return text
    zw = "\u200b"
    out = text
    out = re.sub(r"(\d+)\.run\b", rf"\1{zw}.run", out, flags=re.I)
    out = re.sub(r"(\w+)\.am\b", rf"\1{zw}.am", out, flags=re.I)
    out = re.sub(r"(https?://)", rf"http{zw}://", out, flags=re.I)
    return out


def for_adb_send(text: str) -> str:
    """ADB 发送用：去 emoji；多行保留换行，单行合并空白"""
    raw = text.replace("\r", "").strip()
    if "\n" in raw:
        lines = []
        for ln in raw.split("\n"):
            ln = re.sub(r"[\U00010000-\U0010ffff]", "", ln)
            ln = re.sub(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]", "", ln)
            ln = ln.strip()
            if ln:
                lines.append(ln)
        return "\n".join(lines) if lines else raw
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    no_emoji = []
    for ln in lines:
        ln = re.sub(r"[\U00010000-\U0010ffff]", "", ln)
        ln = re.sub(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]", "", ln)
        if ln.strip():
            no_emoji.append(ln.strip())
    return " ".join(no_emoji) if no_emoji else raw


def _draft_has(draft: str, text: str) -> bool:
    d = _norm_cmp(draft)
    t = _norm_cmp(text)
    if not t or not d:
        return False
    n = min(8, len(t), len(d))
    return t[:n] in d or d[:n] in t or t in d or d in t


def input_filled(texts: list[str], draft: str, text: str) -> bool:
    snip = message_snip(text)
    if not snip:
        return False
    if _draft_has(draft, snip) or _draft_has(draft, text):
        return True
    return False


def draft_filled(draft: str, text: str) -> bool:
    return input_filled([], draft, text)


def count_snip(texts: list[str], text: str) -> int:
    sn = message_snip(text)
    if not sn:
        return 0
    return sum(1 for t in texts if sn[:8] in _norm(t))


def draft_is_empty(draft: str) -> bool:
    d = draft.strip()
    return not d or d in ("输入消息", "Enter message")


def draft_cleared_after_fill(draft_before: str, draft_after: str, outgoing: str) -> bool:
    """快发后草稿已空 → 视为已发出，禁止再走完整路径（防公告/回复双份）。"""
    out = (outgoing or "").strip()
    if not out:
        return False
    before = (draft_before or "").strip()
    after = (draft_after or "").strip()
    if before and _draft_has(before, out) and draft_is_empty(after):
        return True
    if before and _draft_has(before, out) and not _draft_has(after, out):
        return True
    return False


def send_succeeded(
    texts_after: list[str],
    draft_after: str,
    outgoing: str,
    before: list[str],
    draft_before: str = "",
) -> bool:
    # 草稿仍在输入框 → 未发出（55M 假成功的主要来源）
    if not draft_is_empty(draft_after) and _draft_has(draft_after, outgoing):
        return False

    if count_snip(texts_after, outgoing) > count_snip(before, outgoing):
        return draft_is_empty(draft_after) or not _draft_has(draft_after, outgoing)

    snip = message_snip(outgoing)
    if snip:
        before_set = set(before)
        for t in texts_after:
            if t in before_set:
                continue
            if snip[:8] in _norm(t) or _norm(t)[:8] in snip:
                return draft_is_empty(draft_after) or not _draft_has(draft_after, outgoing)

    if draft_before and _draft_has(draft_before, outgoing) and draft_is_empty(draft_after):
        return True

    new_msgs = [t for t in texts_after if t not in set(before)]
    if snip and new_msgs:
        for t in new_msgs:
            if snip[:6] in _norm(t):
                return draft_is_empty(draft_after) or not _draft_has(draft_after, outgoing)
    return False


def adb_safe_text(text: str) -> str:
    one = text.replace("\n", " ").strip()
    safe = re.sub(r"[^\w\s.+-]", "", one)
    return (safe[:120] if safe else "OK").strip()


def adb_send_text(serial: str, text: str) -> None:
    one_line = text.replace("\n", " ")
    ensure_adb_ime(serial)
    adb_run(
        serial, "shell", "am", "broadcast",
        "-a", "ADB_INPUT_TEXT", "--es", "msg", one_line,
    )
    w(0.9 if not one_line.isascii() else 0.35, 0.45 if not one_line.isascii() else 0.12)


def _set_clipboard_text(serial: str, text: str) -> bool:
    """写入云机系统剪贴板（多策略，供 55M KEYCODE_PASTE 使用）。"""
    one_line = text.replace("\n", " ")
    if not one_line:
        return False
    _ensure_clipboard_helper(serial)
    binp = "/data/local/tmp/clip"
    try:
        if "No such file" not in adb_run(serial, "shell", "ls", binp):
            adb_run(serial, "shell", binp, "set", one_line)
            return True
    except Exception:
        pass
    try:
        out = adb_run(serial, "shell", "cmd", "clipboard", "set-text", one_line)
        if out and "error" not in out.lower():
            return True
    except Exception:
        pass
    try:
        adb_run(
            serial, "shell", "am", "broadcast",
            "-a", "clipper.set", "-e", "text", one_line,
        )
        return True
    except Exception:
        return False


def adb_paste_text(serial: str, text: str) -> None:
    one_line = text.replace("\n", " ")
    _set_clipboard_text(serial, one_line)
    w(0.25, 0.08)
    adb_run(serial, "shell", "input", "keyevent", "279")
    w(0.7, 0.25)


def adb_send_b64(serial: str, text: str, *, fast: bool = False, instant: bool = False, announce: bool = False) -> None:
    ensure_adb_ime(serial)
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    adb_run(
        serial, "shell", "am", "broadcast",
        "-a", "ADB_INPUT_B64", "--es", "msg", b64,
    )
    if instant or (LISTENER_PURE_PIPE and LISTENER_TRUST_SEND and not announce):
        return
    w(0.2 if announce else (0.06 if fast else 1.0), 0.1 if announce else (0.02 if fast else 0.35))


def adb_clear_input_fast(serial: str, *, instant: bool = False, announce: bool = False) -> None:
    ensure_adb_ime(serial)
    adb_run(serial, "shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT")
    if instant or (LISTENER_PURE_PIPE and LISTENER_TRUST_SEND and not announce):
        return
    w(0.1 if announce else 0.04, 0.05 if announce else 0.02)


def adb_clear_input(serial: str) -> None:
    ensure_adb_ime(serial)
    adb_run(serial, "shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT")
    for _ in range(8):
        adb_run(serial, "shell", "input", "keyevent", "67")
    w(0.2, 0.05)


def adb_set_text(serial: str, text: str) -> None:
    """整段写入输入框（senzhk ADB_INPUT_TEXT / B64）"""
    ensure_adb_ime(serial)
    if "\n" in text:
        adb_send_b64(serial, text)
        return
    adb_run(
        serial, "shell", "am", "broadcast",
        "-a", "ADB_INPUT_TEXT", "--es", "msg", text,
    )
    w(0.5 if FAST else 0.9, 0.12 if FAST else 0.35)
    if FAST:
        return
    snap = ui_snapshot(serial)
    if not draft_filled(snap.draft, text):
        adb_send_b64(serial, text)
        w(0.9, 0.35)


def fill_input_box(serial: str, x: int, y: int, text: str) -> tuple[list[str], str, bool]:
    outgoing = for_adb_send(text).strip()
    multiline = "\n" in outgoing

    def snap_draft() -> tuple[list[str], str]:
        s = ui_snapshot(serial)
        return s.texts, s.draft

    snap0 = ui_snapshot(serial)
    fx, fy = resolve_chat_input_xy(snap0, None, None)
    if snap0.input_xy and snap0.input_xy[1] <= CHAT_INPUT_Y_MAX:
        fx, fy = snap0.input_xy
    adb_tap_raw(serial, fx, fy)
    w(0.85, 0.25)
    adb_clear_input(serial)

    if u2_fill_input(serial, outgoing):
        texts, draft = snap_draft()
        if draft_filled(draft, outgoing):
            return texts, outgoing, True

    ascii_only = outgoing.isascii() and not any(ord(c) > 127 for c in outgoing)
    if ascii_only:
        safe = adb_safe_text(outgoing)
        adb_run(serial, "shell", "input", "text", safe.replace(" ", "%s"))
        w(0.75, 0.2)
        outgoing = safe
    elif multiline:
        adb_send_b64(serial, outgoing)
        w(0.5, 0.2)
    else:
        fill_fns = (adb_set_text,) if FAST else (adb_set_text, adb_send_b64)
        for fill_fn in fill_fns:
            adb_clear_input(serial)
            adb_tap_raw(serial, fx, fy)
            w(0.3, 0.1)
            try:
                fill_fn(serial, outgoing)
            except Exception:
                continue
            if FAST:
                break
            _, draft = snap_draft()
            if draft_filled(draft, outgoing):
                break

    texts, draft = snap_draft()
    ok = draft_filled(draft, outgoing)
    if not ok and outgoing:
        adb_tap_raw(serial, fx, fy)
        w(0.2, 0.08)
        adb_paste_text(serial, outgoing)
        w(0.6, 0.25)
        texts, draft = snap_draft()
        ok = draft_filled(draft, outgoing)
    if not ok and draft.strip():
        if outgoing:
            ok = len(_norm_cmp(draft)) >= 6 and _norm_cmp(outgoing)[:6] in _norm_cmp(draft)
        else:
            ok = len(_norm_cmp(draft)) >= 6
        if ok:
            outgoing = draft
    if not ok:
        log.warning("填字失败 @(%d,%d) draft=%r want=%r", fx, fy, draft[:40], outgoing[:40])
    return texts, outgoing if ok else "", ok


def press_enter(serial: str) -> None:
    adb_run(serial, "shell", "input", "keyevent", "66")
    w(0.7, 0.25)


def execute_send_round(
    serial: str,
    input_xy: tuple[int, int],
    strategies: list[tuple[str, int, int]],
    outgoing: str,
    texts_before: list[str],
    draft_before: str,
) -> bool:
    """一轮发送：缓存策略 → 发送键 → Enter → IME"""
    adb_tap_raw(serial, input_xy[0], input_xy[1])
    w(0.35, 0.12)

    inbar_pts = [(n, x, y) for n, x, y in strategies if "输入栏" in n]
    kb_pts = [(n, x, y) for n, x, y in strategies if "键盘" in n]

    def check() -> bool:
        snap = ui_snapshot(serial)
        return send_succeeded(snap.texts, snap.draft, outgoing, texts_before, draft_before)

    def try_tap(name: str, sx: int, sy: int) -> bool:
        if slow_send_should_yield():
            log.info("慢发送让路(用户队列): 中止 [%s]", name)
            return False
        log.info("尝试发送 [%s] (%d, %d)", name, sx, sy)
        adb_tap_raw(serial, sx, sy)
        w(0.8, 0.3)
        if check():
            _SEND_CACHE[serial] = (name, sx, sy)
            log.info("已回复 [%s]", name)
            return True
        return False

    cached = _SEND_CACHE.get(serial)
    if cached:
        cn, cx, cy = cached
        if try_tap(f"缓存-{cn}", cx, cy):
            return True

    if u2_click_send(serial) and check():
        log.info("已回复 [u2-发送]")
        return True

    for name, args in collect_ime_send_attempts(outgoing):
        log.info("尝试发送 [%s]", name)
        active_adb_ime(serial)
        adb_run(serial, *args)
        w(0.8, 0.28)
        if check():
            log.info("已回复 [%s]", name)
            return True

    for name, sx, sy in inbar_pts:
        if try_tap(name, sx, sy):
            return True

    if inbar_pts and kb_pts and not FAST:
        _, ix, iy = inbar_pts[0]
        _, kx, ky = kb_pts[0]
        log.info("组合发送 输入栏(%d,%d) + 键盘(%d,%d)", ix, iy, kx, ky)
        adb_tap(serial, input_xy[0], input_xy[1])
        w(0.4, 0.12)
        adb_tap(serial, ix, iy)
        w(0.5, 0.15)
        adb_tap(serial, kx, ky)
        w(1.0, 0.35)
        if check():
            log.info("已回复 [组合发送]")
            return True

    if not FAST:
        for name, sx, sy in kb_pts:
            if (sx, sy) in {(x, y) for _, x, y in inbar_pts}:
                continue
            if try_tap(name, sx, sy):
                return True

    log.info("尝试发送 [Enter键]")
    press_enter(serial)
    if check():
        log.info("已回复 [Enter键]")
        return True
    return False


def _outgoing_is_announce(text: str) -> bool:
    """封盘提醒/封盘公告/新的一局 — 必须验群聊气泡，禁止 trust-only。"""
    t = (text or "").strip()
    return any(
        m in t
        for m in ("封盘", "新的一局", "停止下注", "距离封盘", "抱拳", "禁]", "钱]")
    )


def _any_clicker_img_flow_busy() -> bool:
    return bool(_CLICKER_IMG_FLOW_SERIALS)


def _wait_clicker_img_idle(timeout: float = 5.0) -> None:
    """右机公告发送前让出 ADB，避免与左机发图抢线。"""
    deadline = time.time() + timeout
    while _any_clicker_img_flow_busy() and time.time() < deadline:
        w(0.12, 0.06)


def _announce_match_keys(outgoing: str) -> list[str]:
    t = (outgoing or "").strip()
    keys: list[str] = []
    if "60" in t or "距" in t:
        keys.extend(["封盘", "60", "距", "抱拳", "钱"])
    if "停止" in t or "下注" in t or "已封盘" in t or "禁]" in t:
        keys.extend(["停止", "下注", "封盘", "已封盘", "禁", "核对"])
    if "新的一局" in t:
        keys.append("新的一局")
    m = re.search(r"(\d{6,8})", t)
    if m and "期" in t:
        keys.append(m.group(1))
    sn = message_snip(t)
    if sn and sn not in keys:
        keys.append(sn[:6])
    return [k for k in keys if k]


def _announce_rid_key(outgoing: str) -> str:
    m = re.search(r"(\d{6,8})", outgoing or "")
    return m.group(1) if m and "期" in (outgoing or "") else ""


def _announce_in_chat(
    texts_after: list[str],
    texts_before: list[str],
    outgoing: str,
    draft_after: str = "",
) -> bool:
    if send_succeeded(texts_after, draft_after, outgoing, texts_before, ""):
        return True
    keys = _announce_match_keys(outgoing)
    if not keys:
        return False
    rid_key = _announce_rid_key(outgoing)
    before_set = set(texts_before)
    blob_after = re.sub(r"\s+", "", "".join(texts_after))
    if rid_key and rid_key in blob_after and "新的一局" in outgoing:
        for t in texts_after:
            if t in before_set:
                continue
            if "新的一局" in t:
                return True
    for t in texts_after:
        if t in before_set:
            continue
        nt = _norm_announce(t)
        if rid_key and rid_key not in re.sub(r"\s+", "", t):
            continue
        if any(k in nt for k in keys):
            return True
    return False


def _open_gate_satisfied(group: str, open_rid: int) -> bool:
    """当期或更晚「新的一局」已上闸，禁止重复入队。"""
    return bool(group) and open_rid > 0 and int(_ROUND_OPEN_ANNOUNCED.get(group) or 0) >= open_rid


def _announce_visible_in_chat(
    serial: str,
    texts_before: list[str],
    outgoing: str,
) -> bool:
    try:
        scroll_chat_toward_bottom(serial, 1)
        snap = ui_snapshot(serial, chat=True, force=False)
        return _announce_in_chat(
            snap.texts or [], texts_before, outgoing, snap.draft or "",
        )
    except Exception:
        return False


def _announce_already_visible(
    serial: str,
    bot: dict,
    outgoing: str,
) -> bool:
    """dispatch 前读屏：气泡已在群则跳过重复发送（须含当期期号）。"""
    rid_key = _announce_rid_key(outgoing)
    if not rid_key:
        return False
    try:
        scroll_chat_toward_bottom(serial, 1)
        snap = ui_snapshot(serial, chat=True, force=False)
        return _announce_in_chat(snap.texts or [], [], outgoing, snap.draft or "")
    except Exception:
        return False


def _listener_announce_enter_nudge(serial: str) -> None:
    """公告专用：钉死 tap 无效时补 IME Enter（不放开普通回复）。"""
    try:
        adb_run(serial, "shell", "am", "broadcast", "-a", "ADB_KEYBOARD_SMART_ENTER")
    except Exception:
        pass


def listener_announce_fire_send(
    serial: str,
    bot: dict,
    settings: dict[str, str] | None,
) -> tuple[int, int]:
    """公告：IME Enter → fire 内联发送 → 键盘发送 → 再 Enter（禁止因 draft OCR 空而跳过 tap）。"""
    inbar, kb = listener_pinned_send_pair(settings)
    _listener_announce_enter_nudge(serial)
    w(0.10, 0.05)
    sx, sy = listener_fire_send_tap(serial, settings, repeat=1)
    w(0.10, 0.05)
    _listener_announce_enter_nudge(serial)
    w(0.08, 0.04)
    adb_tap_listener_send(serial, bot, kb[0], kb[1])
    w(0.08, 0.04)
    _listener_announce_enter_nudge(serial)
    w(0.06, 0.03)
    return sx, sy


def listener_tap_resolved_send(
    serial: str,
    bot: dict | None,
    settings: dict[str, str] | None = None,
) -> tuple[int, int]:
    """读屏 imageViewSend 后同步 tap（公告不走 fire 盲坐标）。"""
    snap = ui_snapshot(serial, chat=False, force=True)
    sx, sy = listener_resolve_send_xy(serial, settings, snap)
    adb_tap_listener_send(serial, bot, sx, sy)
    log.info("右机解析发送键 @(%d,%d) [resolved]", sx, sy)
    return sx, sy


def listener_verify_announce_sent(
    serial: str,
    bot: dict,
    settings: dict[str, str] | None,
    outgoing: str,
    texts_before: list[str],
    draft_before: str,
    send_xy: tuple[int, int],
) -> bool:
    """公告：加长轮询 + 关键词匹配，容忍 emoji/标点差异。"""
    sx, sy = send_xy
    w(0.08, 0.04)
    deadline = time.time() + LISTENER_ANNOUNCE_VERIFY_MAX_MS / 1000.0
    attempt = 0
    while time.time() < deadline:
        if attempt > 0:
            adb_tap_listener_send(serial, bot, sx, sy)
            w(0.08, 0.04)
        scroll_chat_toward_bottom(serial, 1)
        snap = ui_snapshot(serial, chat=True, force=attempt >= 3)
        draft_after = snap.draft or ""
        if draft_cleared_after_fill(draft_before, draft_after, outgoing):
            if _announce_in_chat(snap.texts, texts_before, outgoing, draft_after):
                return True
        if _announce_in_chat(snap.texts, texts_before, outgoing, draft_after):
            return True
        if draft_cleared_after_fill(draft_before, draft_after, outgoing):
            w(0.12, 0.06)
            scroll_chat_toward_bottom(serial, 1)
            snap2 = ui_snapshot(serial, chat=True, force=False)
            if _announce_in_chat(snap2.texts, texts_before, outgoing, snap2.draft or ""):
                return True
        attempt += 1
        w(0.15, 0.08)
    return False


def listener_verify_sent_after_tap(
    serial: str,
    bot: dict,
    settings: dict[str, str] | None,
    outgoing: str,
    texts_before: list[str],
    draft_before: str,
    send_xy: tuple[int, int],
) -> bool:
    """点击发送后：短轮询 draft 清空；仍卡住则立即补点。"""
    sx, sy = send_xy
    w(0.08, 0.04)
    for attempt in range(3):
        if attempt:
            adb_tap_listener_send(serial, bot, sx, sy)
            w(0.06, 0.03)
        snap = ui_snapshot(serial, chat=False, force=True)
        draft_after = snap.draft or ""
        if send_succeeded(
            snap.texts, draft_after, outgoing, texts_before, draft_before,
        ) or draft_cleared_after_fill(draft_before, draft_after, outgoing):
            return True
    return False


def send_chat_reply_fast_adb_listener(
    serial: str,
    bot: dict,
    text: str,
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    settings: dict[str, str] | None = None,
    *,
    texts_before: list[str] | None = None,
    draft_before: str = "",
) -> bool:
    """右机 LISTENER：b64 填字 + 仅点钉死发送键（禁止点输入框/麦克风/表情）。"""
    if block_clicker_send(serial, bot, text, where="adb-fast"):
        return False
    outgoing = break_im_auto_links(for_adb_send(text).strip())
    if not outgoing:
        return False
    if is_listener_send_only_serial(serial, bot) and LISTENER_SEND_TAP_ONLY:
        now = time.time()
        if now - _IME_READY_TS.get(serial, 0) > IME_READY_SEC:
            ensure_adb_ime(serial)
            _IME_READY_TS[serial] = now
        texts_before = list(texts_before or [])
        draft_before = draft_before or ""
        if not texts_before and not draft_before:
            snap0 = ui_snapshot(serial, chat=False, force=False)
            texts_before = list(snap0.texts or [])
            draft_before = snap0.draft or ""
        if _draft_has(draft_before, outgoing) and len(re.sub(r"\s+", "", draft_before)) >= 2:
            prepared = True
        else:
            prepared = listener_prepare_b64_outgoing(serial, outgoing)
        if not prepared:
            prepared = listener_prepare_b64_outgoing(serial, outgoing)
        if not prepared:
            log.warning("发送失败 [b64 draft未就绪]: %s", message_snip(outgoing)[:40])
            return False
        announce = _outgoing_is_announce(outgoing)
        if announce and listener_composer_dirty(draft_before) and not _draft_has(draft_before, outgoing):
            listener_sanitize_composer(serial, reason="pre-announce-dirty", force=True)
            snap0 = ui_snapshot(serial, chat=False, force=True)
            draft_before = snap0.draft or ""
            texts_before = list(snap0.texts or [])
        if announce:
            _wait_clicker_img_idle(max(90.0, IMG_UPLOAD_WAIT_SEC + 15.0))
            snap_d = ui_snapshot(serial, chat=False, force=True)
            if not _draft_has(snap_d.draft or "", outgoing):
                prepared = listener_prepare_b64_outgoing(serial, outgoing)
                if not prepared:
                    log.warning("公告 draft 二次灌字失败: %s", message_snip(outgoing)[:40])
                    return False
            sx, sy = listener_announce_fire_send(serial, bot, settings)
            w(0.15, 0.08)
            snap_post = ui_snapshot(serial, chat=False, force=True)
            if draft_cleared_after_fill(draft_before, snap_post.draft or "", outgoing):
                scroll_chat_toward_bottom(serial, 1)
                snap_chat = ui_snapshot(serial, chat=True, force=False)
                if _announce_in_chat(
                    snap_chat.texts, texts_before, outgoing, snap_chat.draft or "",
                ):
                    defer_listener_composer_clean(serial, reason="announce-draft-clear")
                    log.info(
                        "发送完成 [b64+announce-draft-clear]: %s",
                        message_snip(outgoing)[:40],
                    )
                    return True
            if _announce_visible_in_chat(serial, texts_before, outgoing):
                defer_listener_composer_clean(serial, reason="announce-already")
                log.info("发送完成 [b64+announce-already]: %s", message_snip(outgoing)[:40])
                return True
            if listener_verify_announce_sent(
                serial, bot, settings, outgoing, texts_before, draft_before, (sx, sy),
            ):
                defer_listener_composer_clean(serial, reason="announce-ok")
                log.info("发送完成 [b64+announce-verified]: %s", message_snip(outgoing)[:40])
                return True
            for round_i in range(4):
                if _announce_visible_in_chat(serial, texts_before, outgoing):
                    defer_listener_composer_clean(serial, reason="announce-already")
                    log.info(
                        "发送完成 [b64+announce-already r=%d]: %s",
                        round_i + 1, message_snip(outgoing)[:40],
                    )
                    return True
                sx, sy = listener_announce_fire_send(serial, bot, settings)
                w(0.15, 0.08)
                if listener_verify_announce_sent(
                    serial, bot, settings, outgoing, texts_before, draft_before, (sx, sy),
                ):
                    defer_listener_composer_clean(serial, reason="announce-retap")
                    log.info(
                        "发送完成 [b64+announce-retap r=%d]: %s",
                        round_i + 1, message_snip(outgoing)[:40],
                    )
                    return True
            log.warning("公告未出现在群聊 [b64+announce]: %s", message_snip(outgoing)[:40])
            return False
        sx, sy = listener_tap_pinned_send_now(serial, bot, settings)
        if LISTENER_TRUST_SEND or LISTENER_SEND_FIRE:
            defer_listener_composer_clean(serial, reason="fire-trust")
            log.info("发送完成 [b64+fire-thread]: %s", message_snip(outgoing)[:40])
            return True
        if listener_verify_sent_after_tap(
            serial, bot, settings, outgoing, texts_before, draft_before, (sx, sy),
        ):
            defer_listener_composer_clean(serial, reason="fire-verified")
            log.info("发送完成 [b64+fire]: %s", message_snip(outgoing)[:40])
            return True
        listener_fire_send_tap(serial, settings, repeat=1)
        if listener_verify_sent_after_tap(
            serial, bot, settings, outgoing, texts_before, draft_before, (sx, sy),
        ):
            defer_listener_composer_clean(serial, reason="fire-retap")
            log.info("发送完成 [b64+fire+retap]: %s", message_snip(outgoing)[:40])
            return True
        log.warning(
            "发送失败 [b64 未验证]: %s",
            message_snip(outgoing)[:40],
        )
        return False

    if is_listener_send_only_serial(serial, bot):
        log.warning("右机禁止 legacy 发送路径(含点输入框)，请开 LISTENER_SEND_TAP_ONLY")
        return False

    pipe = LISTENER_PURE_PIPE and LISTENER_TRUST_SEND
    now = time.time()
    if now - _IME_READY_TS.get(serial, 0) > IME_READY_SEC:
        ensure_adb_ime(serial)
        _IME_READY_TS[serial] = now

    if pipe:
        adb_send_b64(serial, outgoing, fast=True, instant=True)
        sx, sy = listener_active_send_xy(serial, settings, None)
        adb_tap_listener_send(serial, bot, sx, sy)
        log.info(
            "发送完成 [pipe+b64+send@(%d,%d)]: %s",
            sx, sy, message_snip(outgoing)[:40],
        )
        return True

    before = list(texts_before or [])
    draft0 = draft_before or ""
    coords = SendCoords.from_settings(settings or {})
    ix, iy = input_xy or DEFAULT_CHAT_INPUT
    adb_tap_raw(serial, ix, iy, invalidate=not LISTENER_TRUST_SEND)
    w(0.02, 0.01)
    adb_clear_input_fast(serial)
    adb_send_b64(serial, outgoing, fast=True)

    def verified(method: str) -> bool:
        snap = ui_snapshot(serial, chat=False)
        draft_after = snap.draft or ""
        if send_succeeded(snap.texts, draft_after, outgoing, before, draft0):
            log.info("发送完成 [adb-fast+%s]: %s", method, message_snip(outgoing)[:40])
            _SEND_CACHE[serial] = ("enter", 0, 0)
            return True
        if draft_cleared_after_fill(draft0, draft_after, outgoing):
            log.info("发送完成 [adb-fast+%s-draft-clear]: %s", method, message_snip(outgoing)[:40])
            _SEND_CACHE[serial] = ("enter", 0, 0)
            return True
        return False

    if LISTENER_TRUST_SEND and (LISTENER_SEND_ENTER_FIRST or LISTENER_PURE_PIPE):
        method = fire_listener_send_key(serial)
        log.info("发送完成 [adb-fast+fire+%s]: %s", method, message_snip(outgoing)[:40])
        return True

    sx, sy = coords.inbar
    adb_tap_raw(serial, sx, sy, invalidate=not LISTENER_TRUST_SEND)
    if LISTENER_TRUST_SEND:
        log.info("发送完成 [adb-fast+fire]: %s", message_snip(outgoing)[:40])
        _SEND_CACHE[serial] = ("inbar", sx, sy)
        return True
    w(0.05, 0.02)
    if verified("tap-inbar"):
        return True
    adb_run(serial, "shell", "input", "keyevent", "66")
    w(0.05, 0.02)
    if verified("KEYEVENT_66"):
        return True

    cached = _SEND_CACHE.get(serial)
    if cached:
        _, sx, sy = cached
        adb_tap_raw(serial, sx, sy)
        w(0.15, 0.06)
        if verified("cache"):
            return True
    if send_xy:
        sx, sy = send_xy
    else:
        sx, sy = coords.inbar
    adb_tap_raw(serial, sx, sy)
    w(0.15, 0.06)
    if verified("tap"):
        return True
    for name, args in collect_ime_send_attempts(outgoing):
        adb_run(serial, *args)
        w(0.25, 0.1)
        if verified(name):
            return True
    if u2_click_send(serial):
        w(0.2, 0.08)
        if verified("u2-fallback"):
            return True
    return False


def send_chat_reply_fast_u2(
    serial: str,
    text: str,
    texts_before: list[str],
    draft_before: str,
) -> bool:
    if is_listener_send_only_serial(serial) and LISTENER_SEND_TAP_ONLY:
        return False
    if block_clicker_send(serial, None, text, where="u2-fast"):
        return False
    outgoing = for_adb_send(text).strip()
    if not outgoing:
        return False
    if not u2_fill_input(serial, outgoing):
        return False
    if not u2_click_send(serial):
        return False
    if LISTENER_TRUST_SEND:
        log.info("发送完成 [u2-fast+fire]: %s", message_snip(outgoing)[:40])
        return True
    w(0.12, 0.05)
    snap = ui_snapshot(serial, chat=False)
    draft_after = snap.draft or ""
    if send_succeeded(snap.texts, draft_after, outgoing, texts_before, draft_before):
        log.info("发送完成 [u2-fast]: %s", message_snip(outgoing)[:40])
        return True
    if draft_cleared_after_fill(draft_before, draft_after, outgoing):
        log.info("发送完成 [u2-fast-draft-clear]: %s", message_snip(outgoing)[:40])
        return True
    log.warning("发送未确认 [u2-fast]: %s", message_snip(outgoing)[:40])
    return False


def _dismiss_clicker_attach_menu(serial: str) -> None:
    """收起附件栏：点聊天区中部。"""
    root = ui_hierarchy(serial)
    sw = screen_width(root) if root is not None else 720
    sh = screen_height(root) if root is not None else 1280
    adb_tap_raw(serial, sw // 2, int(sh * 0.38), purpose="clicker-pinned-dismiss-attach")
    clicker_w(0.12, 0.08)
    invalidate_step_verify_cache(serial)


def dismiss_clicker_stuck_surface(serial: str) -> None:
    """关闭附件栏/相册/预览，回到群聊 composer（heal/发图失败用）。"""
    if MANUAL_IN_GROUP and not is_clicker_serial(serial):
        return
    for i in range(3):
        root = ui_hierarchy(serial)
        if root is not None and _verify_chat_composer_ready_root(root, serial):
            if not _verify_attach_menu_open_serial(serial) and not _verify_gallery_picker_open_serial(serial):
                return
        if root is not None and _verify_gallery_picker_open_serial(serial):
            clicker_safe_back(serial, reason=f"关闭相册 step={i + 1}")
            clicker_w(0.22, 0.08)
            continue
        if root is not None and _verify_attach_menu_open_serial(serial):
            _dismiss_clicker_attach_menu(serial)
            clicker_w(0.18, 0.08)
            continue
        if is_clicker_serial(serial) and is_group_chat_activity(serial):
            log.info("左机群聊内收起叠层（禁止 header 退出群）")
            _dismiss_clicker_attach_menu(serial)
            dismiss_soft_keyboard(serial)
            clicker_w(0.18, 0.08)
            continue
        if is_clicker_serial(serial):
            clicker_safe_back(serial, reason=f"关闭叠层 step={i + 1}")
        else:
            device_safe_back(serial, reason=f"关闭叠层 step={i + 1}")
        clicker_w(0.22, 0.06)


def _dismiss_image_picker(serial: str) -> None:
    """相册/预览/附件层退回群聊输入态（左机禁止系统 Back）。"""
    dismiss_clicker_stuck_surface(serial)


BOT_IMG_SEND_MODE = os.environ.get("BOT_IMG_SEND_MODE", "ui").lower()  # ui | auto | in_app_copy | paste(废弃)
BOT_IMG_LONG_PRESS_MS = max(600, int(os.environ.get("BOT_IMG_LONG_PRESS_MS", "1100") or 1100))
BOT_IMG_NEWEST_AT = os.environ.get("BOT_IMG_NEWEST_AT", "top").lower()  # top | bottom — W49：55M 相册最新图在最上
_CLIP_HELPER_READY: dict[str, bool] = {}


def _messenger_pkg(serial: str) -> str | None:
    try:
        out = adb_run(serial, "shell", "dumpsys", "window", "displays")
        for line in out.splitlines():
            if "mCurrentFocus" not in line:
                continue
            m = re.search(r"([a-zA-Z][\w.]*wuwu[\w.]*)", line)
            if m:
                return m.group(1)
            m = re.search(r"(wuwu\.[a-zA-Z0-9._]+)", line)
            if m:
                return m.group(1)
    except Exception:
        pass
    for line in adb_run(serial, "shell", "pm", "list", "packages").splitlines():
        pkg = line.split(":")[-1].strip() if ":" in line else ""
        if pkg.startswith("wuwu."):
            return pkg
    return None


def _media_content_uri(serial: str, remote: str) -> str | None:
    """扫描后解析或插入 MediaStore，返回 content:// URI。"""
    adb_run(
        serial, "shell", "am", "broadcast",
        "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", f"file://{remote}",
    )
    w(0.45, 0.12)
    esc = remote.replace("'", "\\'")
    out = adb_run(
        serial, "shell", "content", "query",
        "--uri", "content://media/external/images/media",
        "--projection", "_id",
        "--where", f"_data='{esc}'",
    )
    m = re.search(r"_id=(\d+)", out)
    if m:
        return f"content://media/external/images/media/{m.group(1)}"
    ins = adb_run(
        serial, "shell", "content", "insert",
        "--uri", "content://media/external/images/media",
        "--bind", f"_display_name:s:{os.path.basename(remote)}",
        "--bind", "mime_type:s:image/png",
        "--bind", f"_data:s:{remote}",
    )
    m2 = re.search(r"content://\S+", ins)
    return m2.group(0).strip() if m2 else None


def _ensure_clipboard_helper(serial: str) -> bool:
    """推送 adb-clip（文本剪贴板）；图片走 URI + paste。"""
    if _CLIP_HELPER_READY.get(serial):
        return True
    jar = "/data/local/tmp/clip.jar"
    binp = "/data/local/tmp/clip"
    try:
        if "No such file" in adb_run(serial, "shell", "ls", jar):
            base = "https://github.com/polygraphene/adb-clip/releases/download/v0.0.3"
            adb_run(serial, "shell", "curl", "-fsSL", "-o", jar, f"{base}/clip.jar")
            adb_run(serial, "shell", "curl", "-fsSL", "-o", binp, f"{base}/clip")
            adb_run(serial, "shell", "chmod", "755", binp)
        ok = "No such file" not in adb_run(serial, "shell", "ls", binp)
        _CLIP_HELPER_READY[serial] = ok
        return ok
    except Exception as ex:
        log.warning("clip helper 安装失败: %s", ex)
        return False


def _set_clipboard_image_best_effort(
    serial: str, remote: str, content_uri: str | None,
) -> bool:
    """把 PNG 放进系统剪贴板（多策略，供 KEYCODE_PASTE 使用）。"""
    file_uri = f"file://{remote}"
    uri = content_uri or file_uri
    pkg = _messenger_pkg(serial)

    # 1) ShareToClipboard（若已装）接受 image/png SEND
    for comp in (
        "com.tengu.sharetoclipboard/.SendActivity",
        "com.tengu.sharetoclipboard/.MainActivity",
    ):
        try:
            adb_run(
                serial, "shell", "am", "start",
                "-a", "android.intent.action.SEND",
                "-t", "image/png",
                "--eu", "android.intent.extra.STREAM", file_uri,
                "-n", comp,
                "-f", "0x10000000",
            )
            w(0.35, 0.12)
            return True
        except Exception:
            continue

    # 2) cmd clipboard（部分 ROM 支持 URI / 文本）
    for args in (
        ("cmd", "clipboard", "write", uri),
        ("cmd", "clipboard", "set-text", uri),
    ):
        try:
            out = adb_run(serial, "shell", *args)
            if out and "error" not in out.lower() and "unknown" not in out.lower():
                return True
        except Exception:
            continue

    # 3) clipper 广播（文本 URI，少数 ROM 可识别）
    try:
        adb_run(
            serial, "shell", "am", "broadcast",
            "-a", "clipper.set", "-e", "text", uri,
        )
        w(0.15, 0.06)
    except Exception:
        pass

    # 4) 直接 SEND 到 55M（部分版本等同「粘贴到当前会话」）
    if pkg:
        try:
            adb_run(
                serial, "shell", "am", "start",
                "-a", "android.intent.action.SEND",
                "-t", "image/png",
                "--eu", "android.intent.extra.STREAM", file_uri,
                "-p", pkg,
                "-f", "0x14000000",
            )
            w(0.55, 0.18)
            return True
        except Exception:
            pass
    return False


def _adb_long_press(
    serial: str, x: int, y: int, ms: int | None = None,
) -> None:
    dur = ms if ms is not None else BOT_IMG_LONG_PRESS_MS
    adb_run(serial, "shell", "input", "swipe", str(x), str(y), str(x), str(y), str(dur))


def _tap_copy_in_context_menu(serial: str) -> bool:
    """55M 相册/聊天内长按后的「复制」（须应用内复制，系统剪贴板无效）。"""
    copy_labels = ("复制", "拷贝", "Copy")
    dev = _get_u2_device(serial)
    if dev:
        for label in copy_labels:
            for kwargs in (
                {"text": label},
                {"textContains": label},
                {"description": label},
                {"descriptionContains": label},
            ):
                try:
                    node = dev(**kwargs)
                    if node.exists(timeout=1.8):
                        node.click()
                        log.info("发图点复制 u2 %s", kwargs)
                        return True
                except Exception:
                    continue
        try:
            for node in dev(className="android.widget.TextView"):
                info = node.info or {}
                t = (info.get("text") or "").strip()
                d = (info.get("contentDescription") or "").strip()
                if t in copy_labels or d in copy_labels:
                    node.click()
                    log.info("发图点复制 TextView text=%r desc=%r", t, d)
                    return True
                if any(lbl in t or lbl in d for lbl in copy_labels):
                    node.click()
                    log.info("发图点复制 TextView 含复制 text=%r", t)
                    return True
        except Exception:
            pass
    root = ui_hierarchy(serial, force=True)
    if root is not None:
        for label in copy_labels:
            pt = find_tap_contains(root, label, min_y=200, max_y=1200)
            if pt:
                adb_tap_raw(serial, pt[0], pt[1])
                log.info("发图点复制 (坐标 %s)", label)
                return True
    return False


def _gallery_thumb_centers_top_down(
    dev, serial: str, count: int,
) -> list[tuple[int, int]]:
    """相册网格缩略图中心点，自上而下（最新 push 的 index=0 在最上，W49 保底规格）。"""
    cells: list[tuple[int, int, int, int, int]] = []
    try:
        sw, sh = dev.window_size()
        for cls in (
            "android.widget.FrameLayout",
            "android.widget.RelativeLayout",
            "android.widget.ImageView",
        ):
            coll = dev(className=cls)
            for i in range(coll.count):
                b = _u2_bounds_dict(coll[i])
                if not b:
                    continue
                x1, y1, x2, y2 = b
                cw, ch = x2 - x1, y2 - y1
                area = cw * ch
                if cw < 80 or ch < 80 or cw > 440 or ch > 440:
                    continue
                if area < 10000 or area > 180000:
                    continue
                if y1 < sh * 0.14 or y2 > sh * 0.93:
                    continue
                cy, cx = (y1 + y2) // 2, (x1 + x2) // 2
                cells.append((cy, cx, x1, y1, x2, y2))
    except Exception as ex:
        log.warning("枚举相册缩略图失败: %s", ex)
        return []

    order = (lambda t: (t[0], t[1])) if BOT_IMG_NEWEST_AT == "top" else (lambda t: (-t[0], t[1]))
    uniq: list[tuple[int, int, int, int, int]] = []
    for cy, cx, x1, y1, x2, y2 in sorted(cells, key=order):
        if any(abs(cy - u[0]) < 38 and abs(cx - u[1]) < 38 for u in uniq):
            continue
        uniq.append((cy, cx, x1, y1, x2, y2))

    out: list[tuple[int, int]] = []
    for _cy, _cx, x1, y1, x2, y2 in uniq[: max(1, count)]:
        out.append(((x1 + x2) // 2, (y1 + y2) // 2))
    return out


def _gallery_thumb_centers_bottom_up(
    dev, serial: str, count: int,
) -> list[tuple[int, int]]:
    """兼容旧名：实际按 BOT_IMG_NEWEST_AT 排序。"""
    return _gallery_thumb_centers_top_down(dev, serial, count)


def _messenger_foreground(serial: str) -> bool:
    pkg = _messenger_pkg(serial)
    if not pkg:
        return False
    try:
        out = adb_run(serial, "shell", "dumpsys", "window", "displays")
        return pkg in out
    except Exception:
        return False


def _scroll_picker_to_bottom(serial: str, times: int = 3) -> None:
    """相册列表滚到最底部（仅 BOT_IMG_NEWEST_AT=bottom 时用）。"""
    try:
        out = adb_run(serial, "shell", "wm", "size").strip()
        m = re.search(r"(\d+)x(\d+)", out)
        sw, sh = (720, 1280) if not m else (int(m.group(1)), int(m.group(2)))
        for _ in range(times):
            adb_run(
                serial, "shell", "input", "swipe",
                str(sw // 2), str(int(sh * 0.82)),
                str(sw // 2), str(int(sh * 0.28)), "280",
            )
            w(0.35, 0.1)
    except Exception:
        pass


def _scroll_picker_for_newest(serial: str, times: int = 2) -> None:
    """按 W49 规格：默认最新图在相册最上，不滚到底；bottom 模式才滚到底。"""
    if BOT_IMG_NEWEST_AT == "bottom":
        _scroll_picker_to_bottom(serial, times=times)
        return
    # 轻微下滑确保回到列表顶部（手指从上往下拉）
    try:
        out = adb_run(serial, "shell", "wm", "size").strip()
        m = re.search(r"(\d+)x(\d+)", out)
        sw, sh = (720, 1280) if not m else (int(m.group(1)), int(m.group(2)))
        adb_run(
            serial, "shell", "input", "swipe",
            str(sw // 2), str(int(sh * 0.28)),
            str(sw // 2), str(int(sh * 0.72)), "220",
        )
        w(0.35, 0.1)
    except Exception:
        pass


def _gallery_coord_for_index(
    serial: str, index: int, *, cols: int = 3,
) -> tuple[int, int]:
    """相册网格坐标兜底（index=0 为最新一张，位置取决于 BOT_IMG_NEWEST_AT）。"""
    try:
        out = adb_run(serial, "shell", "wm", "size").strip()
        m = re.search(r"(\d+)x(\d+)", out)
        sw, sh = (720, 1280) if not m else (int(m.group(1)), int(m.group(2)))
    except Exception:
        sw, sh = 720, 1280
    row = index // cols
    col = index % cols
    cell_w = sw // cols
    top = int(sh * 0.22)
    bottom = int(sh * 0.9)
    row_h = max(120, (bottom - top) // 4)
    cx = col * cell_w + cell_w // 2
    if BOT_IMG_NEWEST_AT == "top":
        cy = top + row * row_h + row_h // 2
    else:
        cy = bottom - row * row_h - row_h // 2
    return cx, max(top + 60, min(bottom - 60, cy))


def _gallery_coord_bottom_center(
    serial: str, index_from_bottom: int, *, cols: int = 3,
) -> tuple[int, int]:
    """兼容旧名。"""
    idx = index_from_bottom if BOT_IMG_NEWEST_AT == "bottom" else index_from_bottom
    return _gallery_coord_for_index(serial, idx, cols=cols)


def _return_from_gallery_to_chat(serial: str, bot: dict) -> bool:
    """从相册/预览退回群聊输入栏（最多 2 次返回，防止退出 55M）。"""
    for _ in range(2):
        root = ui_hierarchy(serial)
        if in_target_group_chat(root, bot, serial):
            texts = collect_ui_texts(root) if root is not None else []
            if any(t in ("输入消息", "Enter message") for t in texts):
                return True
        device_safe_back(serial, reason="相册返回群聊")
        w(0.38, 0.12)
    root = ui_hierarchy(serial)
    if in_target_group_chat(root, bot, serial):
        return True
    if not _messenger_foreground(serial):
        log.warning("返回后不在 55M，尝试拉回应用")
        launch_messenger_app(serial)
        w(0.8, 0.25)
    root = ui_hierarchy(serial)
    return in_target_group_chat(root, bot, serial)


def _recover_after_image_ops(serial: str, bot: dict) -> None:
    """发图流程结束后回到目标群聊。"""
    if is_clicker_bot(bot) or is_clicker_serial(serial, bot):
        clicker_restore_adb_ime_after_attach(serial)
        if in_target_group_chat(ui_hierarchy(serial), bot, serial):
            return
        clicker_return_to_group(serial, bot, label="after-image")
        return
    if in_target_group_chat(ui_hierarchy(serial), bot, serial):
        return
    log.warning("发图后偏离群聊，尝试自动回群「%s」", bot.get("associatedGroup"))
    try_recover_listener_to_group(serial, bot, reason="after-image")


def _is_chat_media_class(cls: str) -> bool:
    return any(k in cls for k in ("ImageView", "Image", "Texture", "Video"))


def _count_chat_media_bubbles(
    root: ET.Element | None,
    y_max: int,
    *,
    min_size: int = 70,
) -> int:
    if root is None:
        return 0
    n = 0
    for node in root.iter("node"):
        if not _is_chat_media_class(node.attrib.get("class") or ""):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[3] > y_max or b[1] < 60:
            continue
        bw, bh = b[2] - b[0], b[3] - b[1]
        if bw >= min_size and bh >= min_size:
            n += 1
    return n


_FAIL_SEND_MARKERS = (
    "重试",
    "重新发送",
    "发送失败",
    "retry",
    "resend",
    "failed to send",
    "tap to retry",
)
_UPLOADING_MARKERS = ("发送中", "上传中", "sending", "uploading", "进度")


def _node_ui_blob(node: ET.Element) -> str:
    label = node_label(node)
    desc = node.attrib.get("content-desc") or ""
    rid = node.attrib.get("resource-id") or ""
    text = node.attrib.get("text") or ""
    return f"{label} {desc} {rid} {text}".lower()


def _chat_outgoing_image_send_failed(root: ET.Element | None, y_max: int) -> bool:
    """聊天区存在出站图片发送失败标记（红圈重试）。"""
    if root is None or y_max <= 0:
        return False
    sw = screen_width(root)
    for node in root.iter("node"):
        blob = _node_ui_blob(node)
        if not any(m in blob for m in _FAIL_SEND_MARKERS):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b and b[3] <= y_max and b[1] >= 60:
            return True
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        cls = node.attrib.get("class") or ""
        if "Image" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[3] > y_max or b[1] < 60:
            continue
        bw, bh = b[2] - b[0], b[3] - b[1]
        if bw > 88 or bh > 88:
            continue
        cx = (b[0] + b[2]) // 2
        rid = (node.attrib.get("resource-id") or "").lower()
        if cx > int(sw * 0.32) and any(k in rid for k in ("fail", "retry", "error", "status")):
            return True
    return False


def _chat_outgoing_images_still_uploading(root: ET.Element | None, y_max: int) -> bool:
    if root is None or y_max <= 0:
        return False
    for node in root.iter("node"):
        blob = _node_ui_blob(node)
        if not any(m in blob for m in _UPLOADING_MARKERS):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b and b[3] <= y_max and b[1] >= 60:
            return True
    return False


def _wait_outgoing_images_delivered(
    serial: str,
    *,
    expected: int = 1,
    timeout_sec: float | None = None,
    gallery_handoff: bool = False,
) -> bool:
    """等 55M 从相册发出：仅验红圈失败 + 气泡出现（不点重试）。"""
    deadline = time.time() + (timeout_sec or IMG_UPLOAD_WAIT_SEC)
    started = time.time()
    stable_ok = 0
    while time.time() < deadline:
        poll = IMG_UPLOAD_POLL_SEC
        if is_clicker_serial(serial):
            clicker_w(poll, poll * 0.3)
        else:
            w(poll, poll * 0.3)
        root = ui_hierarchy(serial, channel="clicker-img" if is_clicker_serial(serial) else "default")
        snap = ui_snapshot(serial, chat=False)
        ib = snap.input_bounds
        if not ib:
            continue
        y_max = ib[1] - 16
        if _chat_outgoing_image_send_failed(root, y_max):
            if _count_chat_media_bubbles(root, y_max) >= expected:
                log.info(
                    "发图红圈但群聊已有 %d 张媒体气泡，视为成功",
                    _count_chat_media_bubbles(root, y_max),
                )
                return True
            log.warning("发图上传失败(红圈)，他端不可见")
            return False
        if _chat_outgoing_images_still_uploading(root, y_max):
            stable_ok = 0
            continue
        if _count_chat_media_bubbles(root, y_max) >= expected:
            elapsed = time.time() - started
            if gallery_handoff and IMG_UPLOAD_GALLERY_FAST:
                if elapsed >= IMG_UPLOAD_MIN_SETTLE_SEC:
                    stable_ok += 1
                    if stable_ok >= 2:
                        log.info(
                            "发图相册交棒验收 ok expected=%d elapsed=%.1fs",
                            expected,
                            elapsed,
                        )
                        return True
            else:
                stable_ok += 1
                if stable_ok >= 2:
                    return True
        else:
            stable_ok = 0
        scroll_chat_toward_bottom(serial, steps=1)
    return False


def _verify_image_send_in_chat(
    serial: str,
    bot: dict,
    fp_before: str,
    input_bounds: tuple[int, int, int, int] | None,
) -> bool:
    """须在目标群且聊天区出现新图片气泡（含自己右侧发送）。"""
    fast = CLICKER_FAST and is_clicker_serial(serial)
    w(0.28, 0.1) if fast else w(1.0, 0.3)
    scroll_chat_toward_bottom(serial, steps=2 if fast else 3)
    w(0.15, 0.08) if fast else w(0.45, 0.15)
    root = ui_hierarchy(serial, channel="clicker-img" if fast else "default")
    if is_clicker_serial(serial):
        if not _verify_chat_composer_ready_root(root, serial) and not clicker_img_task_surface_ready(serial, root):
            fp_after = _screencap_bottom_fingerprint(serial)
            if fp_before and fp_after and fp_before != fp_after:
                log.info("发图区指纹变化(非标准媒体节点)，视为成功")
                return True
            return False
    elif not in_target_group_chat(root, bot, serial):
        return False
    snap = ui_snapshot(serial, chat=False)
    root = snap.root
    ib = input_bounds or snap.input_bounds
    if root is None or not ib:
        fp_after = _screencap_bottom_fingerprint(serial)
        if fp_before and fp_after and fp_before != fp_after:
            log.info("发图区指纹变化，视为成功")
            return True
        return False
    y_max = ib[1] - 16
    if _chat_outgoing_image_send_failed(root, y_max):
        if ib and _count_chat_media_bubbles(root, y_max) >= 1:
            log.info("发图红圈但群聊已有媒体气泡，视为成功")
            return True
        log.warning("发图验收到失败重试图标(红圈)，他端不可见")
        return False
    if _wait_outgoing_images_delivered(
        serial, expected=1, timeout_sec=IMG_UPLOAD_WAIT_SEC, gallery_handoff=True,
    ):
        return True
    if _count_chat_media_bubbles(root, y_max) >= 1:
        return True
    scroll_chat_toward_bottom(serial, steps=1 if fast else 2)
    w(0.12, 0.06) if fast else w(0.35, 0.12)
    root = ui_hierarchy(serial, channel="clicker-img" if fast else "default")
    if root is not None and _count_chat_media_bubbles(root, y_max) >= 1:
        return True
    fp_after = _screencap_bottom_fingerprint(serial)
    if fp_before and fp_after and fp_before != fp_after:
        log.info("发图区指纹变化，视为成功")
        return True
    return False


def send_chat_image_in_app_copy(
    serial: str,
    bot: dict,
    image_path: str,
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    settings: dict[str, str] | None = None,
    *,
    group_ok: bool = False,
    thumb_index_from_bottom: int = 0,
    gallery_preloaded: bool = False,
) -> bool:
    """55M 内复制粘贴：相册长按缩略图→复制→回聊天→粘贴→发送（外部剪贴板无效）。"""
    if is_clicker_serial(serial) and IMG_PINNED and CLICKER_IMG_TAP_ONLY:
        log.warning("左机禁止 in_app_copy 发图，请走 ui 钉死路径")
        return False
    if not image_path or not os.path.isfile(image_path):
        return False
    if block_clicker_send(serial, bot, image_path, where="send-image-in-app-copy"):
        return False
    if not group_ok and not ensure_group_for_send(serial, bot):
        log.warning("不在目标群，取消应用内复制发图")
        return False

    snap0 = ui_snapshot(serial, chat=False)
    fp_before = _screencap_bottom_fingerprint(serial)
    input_bounds = snap0.input_bounds

    if not gallery_preloaded:
        if not _push_images_to_gallery(serial, [image_path]):
            return False
        w(1.1, 0.35)

    if not _open_chat_image_picker(serial, bot, settings, input_xy):
        log.warning("无法打开相册选择器")
        return False
    w(1.2, 0.35)
    _scroll_picker_for_newest(serial, times=2)
    w(0.8, 0.25)

    dev = _get_u2_device(serial)
    if not dev:
        log.warning("u2 不可用，无法应用内复制发图")
        _dismiss_image_picker(serial)
        _recover_after_image_ops(serial, bot)
        return False

    centers = _gallery_thumb_centers_top_down(
        dev, serial, thumb_index_from_bottom + 1,
    )
    if not centers:
        cx, cy = _gallery_coord_for_index(serial, thumb_index_from_bottom)
        log.info("相册坐标兜底 长按 (%d,%d) idx=%d newest_at=%s", cx, cy, thumb_index_from_bottom, BOT_IMG_NEWEST_AT)
    else:
        idx = min(thumb_index_from_bottom, len(centers) - 1)
        cx, cy = centers[idx]
        log.info(
            "应用内复制发图 长按 (%d,%d) idx_bottom=%d file=%s",
            cx, cy, idx, os.path.basename(image_path),
        )
    press_xy = (cx, cy)
    _adb_long_press(serial, cx, cy)
    w(0.55, 0.18)
    _close_image_preview_if_open(serial)
    w(0.25, 0.08)

    copied = _tap_copy_in_context_menu(serial)
    if not copied:
        log.info("首次未命中复制菜单，加长长按重试")
        _adb_long_press(serial, cx, cy, ms=BOT_IMG_LONG_PRESS_MS + 350)
        w(0.55, 0.18)
        _close_image_preview_if_open(serial)
        w(0.25, 0.08)
        copied = _tap_copy_in_context_menu(serial)

    if not copied:
        log.warning("未找到「复制」菜单（须 55M 内复制） idx=%s @%s", thumb_index_from_bottom, press_xy)
        _dismiss_image_picker(serial)
        _recover_after_image_ops(serial, bot)
        return False
    w(0.4, 0.12)

    if not _return_from_gallery_to_chat(serial, bot):
        log.warning("复制后未能回到群聊输入栏")
        _recover_after_image_ops(serial, bot)
        return False

    _paste_into_chat_input(serial, bot, settings, input_xy)
    snap1 = ui_snapshot(serial, chat=False)
    if not _composer_ready_to_send(snap1):
        log.warning("应用内复制后输入栏无图片附件")
        return False
    if not _tap_composer_send(serial, snap1, send_xy):
        log.warning("应用内复制发图未点到发送")
        return False
    w(0.7, 0.25)

    ok = _verify_image_send_in_chat(serial, bot, fp_before, input_bounds)
    _recover_after_image_ops(serial, bot)
    if ok:
        log.info("应用内复制发图成功: %s", os.path.basename(image_path))
        post_log(f"[ADB] 应用内复制发图成功 {os.path.basename(image_path)}", "SUCCESS")
        return True
    log.warning("应用内复制发图未确认: %s", os.path.basename(image_path))
    return False


def _find_paste_popup_send(root: ET.Element | None) -> tuple[int, int] | None:
    """粘贴图片后浮层「发送到当前聊天」。"""
    if root is None:
        return None
    for node in root.iter("node"):
        label = node_label(node)
        if not label or "发送到当前聊天" not in label:
            continue
        if node.attrib.get("clickable") != "true":
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b and b[1] >= 650:
            return node_center(b)
    return None


def _composer_has_image_attachment(
    root: ET.Element | None,
    input_bounds: tuple[int, int, int, int] | None,
) -> bool:
    """输入栏上方/内部出现图片缩略图（粘贴后）。"""
    if root is None or not input_bounds:
        return False
    x1, y1, x2, y2 = input_bounds
    zone_y1 = max(0, y1 - 160)
    zone_y2 = y2 + 60
    for node in root.iter("node"):
        cls = node.attrib.get("class", "")
        if "ImageView" not in cls:
            continue
        rid = (node.attrib.get("resource-id") or "").lower()
        if any(k in rid for k in ("face", "attachment", "audio", "emoji", "keyboard")):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        bx1, by1, bx2, by2 = b
        bw, bh = bx2 - bx1, by2 - by1
        if bw < 28 or bh < 28:
            continue
        if by2 >= zone_y1 and by1 <= zone_y2 and bx1 >= x1 - 40:
            return True
    return False


def _composer_ready_to_send(snap: UiSnapshot) -> bool:
    if _composer_has_image_attachment(snap.root, snap.input_bounds):
        return True
    if snap.root is not None and _find_paste_popup_send(snap.root):
        return True
    if snap.draft and not draft_is_empty(snap.draft):
        return True
    if snap.root is not None and find_inbar_send(snap.root, snap.input_bounds):
        return True
    return False


def _paste_into_chat_input(
    serial: str,
    bot: dict,
    settings: dict[str, str] | None,
    input_xy: tuple[int, int] | None,
) -> None:
    snap = ui_snapshot(serial, chat=False)
    fx, fy = resolve_chat_input_xy(snap, settings, bot)
    if input_xy and input_xy[1] <= CHAT_INPUT_Y_MAX:
        fx, fy = input_xy
    adb_tap_raw(serial, fx, fy)
    w(0.28, 0.1)
    adb_run(serial, "shell", "input", "keyevent", "279")
    w(0.65, 0.22)
    invalidate_ui_cache(serial)


def _tap_composer_send(
    serial: str,
    snap: UiSnapshot,
    send_xy: tuple[int, int] | None,
) -> bool:
    root = snap.root
    pt = _find_paste_popup_send(root) if root is not None else None
    if pt:
        adb_tap_raw(serial, pt[0], pt[1])
        return True
    if root is not None and snap.input_bounds:
        x1, y1, x2, y2 = snap.input_bounds
        pt = find_labeled_send(root, y1 - 40, y2 + 50, min_x=560)
        if pt:
            adb_tap_raw(serial, pt[0], pt[1])
            return True
    pt = find_inbar_send(root, snap.input_bounds) if root is not None else None
    if pt:
        adb_tap_raw(serial, pt[0], pt[1])
        return True
    if send_xy:
        adb_tap_raw(serial, send_xy[0], send_xy[1])
        return True
    return u2_click_send(serial)


def send_chat_image_paste(
    serial: str,
    bot: dict,
    image_path: str,
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    settings: dict[str, str] | None = None,
    *,
    group_ok: bool = False,
) -> bool:
    """单张图：push → 剪贴板 → 输入框 PASTE(279) → 点发送。"""
    if not image_path or not os.path.isfile(image_path):
        return False
    if block_clicker_send(serial, bot, image_path, where="send-image-paste"):
        return False
    if not group_ok and not ensure_group_for_send(serial, bot):
        log.warning("不在目标群，取消粘贴发图")
        return False

    snap0 = ui_snapshot(serial, chat=False)
    texts_before = list(snap0.texts)
    fp_before = _screencap_bottom_fingerprint(serial)

    remote = f"/sdcard/Download/bot_paste_{int(time.time() * 1000)}.png"
    try:
        adb_run(serial, "push", image_path, remote)
        adb_run(serial, "shell", "chmod", "644", remote)
    except Exception as ex:
        log.warning("粘贴发图 push 失败: %s", ex)
        return False

    content_uri = _media_content_uri(serial, remote)
    _ensure_clipboard_helper(serial)
    _set_clipboard_image_best_effort(serial, remote, content_uri)

    _paste_into_chat_input(serial, bot, settings, input_xy)
    snap1 = ui_snapshot(serial, chat=False)
    if not _composer_ready_to_send(snap1):
        log.warning("粘贴后输入栏无附件/草稿，可能剪贴板未写入图片")
        return False

    if not _tap_composer_send(serial, snap1, send_xy):
        log.warning("粘贴发图未点到发送键")
        return False
    w(0.75, 0.28)

    ok = _verify_chat_send(fp_before, texts_before, serial)
    if ok:
        log.info("粘贴发图成功: %s", os.path.basename(image_path))
        post_log(f"[ADB] 粘贴发图成功 {os.path.basename(image_path)}", "SUCCESS")
        return True
    log.warning("粘贴发图未确认: %s", os.path.basename(image_path))
    return False


def _send_chat_images_ui_batch(
    serial: str,
    bot: dict,
    paths: list[str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    settings: dict[str, str] | None,
    *,
    group_ok: bool,
    gallery_preloaded: bool = False,
    settle_rid: int = 0,
) -> bool:
    """+ → 图片 → 勾选顶行 N 张 → 右下蓝钮发送。"""
    dismiss_clicker_popup_overlay(serial)
    clicker_img_flow_begin(serial)
    ok = False
    try:
        snap0 = ui_snapshot(serial, chat=False)
        fp_before = _screencap_bottom_fingerprint(serial)
        ib0 = snap0.input_bounds
        bubbles_before = (
            _count_chat_media_bubbles(snap0.root, ib0[1] - 16)
            if ib0 and snap0.root
            else 0
        )

        def _batch_newly_visible_in_chat() -> bool:
            scroll_chat_toward_bottom(serial, steps=1)
            snap_chk = ui_snapshot(serial, chat=False, channel="clicker-img")
            ib = snap_chk.input_bounds
            if not ib or not snap_chk.root:
                return False
            delta = _count_chat_media_bubbles(snap_chk.root, ib[1] - 16) - bubbles_before
            if delta >= len(paths):
                log.info(
                    "批量发图群聊已新增 %d/%d 张（验真未过仍视为成功）",
                    delta, len(paths),
                )
                return True
            return False

        if not gallery_preloaded and not _push_images_to_gallery(serial, paths):
            return False
        if settle_rid > 0:
            _CAPTURE_GALLERY_PUSHED.add(settle_rid)
        if gallery_preloaded:
            w(0.18, 0.08) if (CLICKER_FAST and is_clicker_serial(serial)) else w(0.5, 0.15)
        invalidate_ui_cache(serial)
        invalidate_step_verify_cache(serial)
        dismiss_clicker_popup_overlay(serial)
        clicker_hide_keyboard_for_attach(serial)
        already_gallery = _verify_gallery_picker_open(serial)
        if not already_gallery and _verify_attach_menu_open(serial):
            ix, iy = pinned_attach_image_xy()
            clicker_tap_pinned(serial, ix, iy, "attach_image_from_menu")
            clicker_w(0.35, 0.55) if IMG_FAST else clicker_w(0.8, 1.0)
            already_gallery = _verify_gallery_picker_open(serial)
        if not already_gallery and not _open_chat_image_picker(serial, bot, settings, input_xy):
            log.warning("发图：相册未打开，取消批量发送")
            return False
        _scroll_picker_for_newest(serial, times=1)
        clicker_w(0.1, 0.12) if is_clicker_serial(serial) else w(0.35, 0.12)

        n = _select_gallery_image_checkboxes(serial, len(paths))
        if n < len(paths):
            log.warning("勾选图片 %d/%d，取消批量发送（禁止假成功）", n, len(paths))
            return False
        clicker_w(0.12, 0.1) if is_clicker_serial(serial) else w(0.4, 0.12)

        if not _tap_image_batch_send(serial, send_xy):
            log.warning("批量发图未点到发送按钮")
            return False
        clicker_w(0.22, 0.34) if is_clicker_serial(serial) else w(0.45, 0.15)
        if is_clicker_serial(serial):
            for _ in range(3):
                if not _verify_gallery_picker_open_serial(serial):
                    break
                device_safe_back(serial, reason="gallery-send→群聊")
                clicker_w(0.28, 0.45)
                invalidate_step_verify_cache(serial)

        if IMG_TRUST_CLICK and is_clicker_serial(serial):
            if _wait_outgoing_images_delivered(
                serial, expected=len(paths), gallery_handoff=True,
            ):
                log.info("批量发图成功 %d 张（相册交棒已确认）", len(paths))
                post_log(f"[ADB] 批量发图成功 {len(paths)}张", "SUCCESS")
                try:
                    from bot_ops.ephemeral_burn import defer_burn_after_group_images_sent
                    defer_burn_after_group_images_sent(serial, paths)
                except Exception:
                    pass
                ok = True
                return True
            if _batch_newly_visible_in_chat():
                post_log(f"[ADB] 批量发图成功 {len(paths)}张(群聊已见)", "SUCCESS")
                ok = True
                return True
            fp_after = _screencap_bottom_fingerprint(serial)
            if fp_before and fp_after and fp_before != fp_after:
                log.info("批量发图区指纹变化，视为成功 %d 张", len(paths))
                post_log(f"[ADB] 批量发图成功 {len(paths)}张(指纹)", "SUCCESS")
                ok = True
                return True
            log.warning("批量发图上传未确认(可能红圈失败)，他端不可见")
            post_log("[ADB] 批量发图失败(上传未确认)", "WARNING")
            return False

        ok = _verify_image_send_in_chat(serial, bot, fp_before, snap0.input_bounds)
        if ok:
            log.info("批量发图成功 %d 张", len(paths))
            post_log(f"[ADB] 批量发图成功 {len(paths)}张", "SUCCESS")
            return True
        if _batch_newly_visible_in_chat():
            post_log(f"[ADB] 批量发图成功 {len(paths)}张(群聊已见)", "SUCCESS")
            ok = True
            return True
        log.warning("批量发图未确认")
        post_log("[ADB] 批量发图失败(未确认)", "WARNING")
        return False
    finally:
        clicker_img_flow_end(serial)
        _recover_after_image_ops(serial, bot)
        if not ok:
            _dismiss_image_picker(serial)


def _push_images_to_gallery(serial: str, paths: list[str]) -> bool:
    """推送 PNG 到 DCIM。

    BOT_IMG_NEWEST_AT=top：逆序 push，使 paths[0](PC28) 时间戳最新；顶行反序勾选后
    群聊顺序 = paths：PC28 → 六合 → 流水。
    """
    try:
        adb_run(serial, "shell", "mkdir", "-p", "/sdcard/DCIM/Camera")
        base_ts = int(time.time())
        ordered = list(reversed(paths)) if BOT_IMG_NEWEST_AT == "top" else list(paths)
        if len(ordered) > 1:
            log.info(
                "gallery push order newest_at=%s chat→ %s",
                BOT_IMG_NEWEST_AT,
                " → ".join(os.path.basename(p) for p in paths),
            )
        for i, path in enumerate(ordered):
            if not path or not os.path.isfile(path):
                log.warning("图片不存在: %s", path)
                return False
            remote = f"/sdcard/DCIM/Camera/bot_{base_ts + i}_{os.path.basename(path)}"
            adb_run(serial, "push", path, remote)
            adb_run(
                serial, "shell", "am", "broadcast",
                "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d", f"file://{remote}",
            )
        clicker_w(0.12, 0.2) if is_clicker_serial(serial) else w(0.5, 0.25)
        return True
    except Exception as ex:
        log.warning("adb push 图片失败: %s", ex)
        return False


def _ui_text_blob(root: ET.Element | None) -> str:
    if root is None:
        return ""
    return " ".join(collect_ui_texts(root))


def collect_ui_texts_in_band(
    root: ET.Element | None,
    min_y: int,
    max_y: int,
) -> list[str]:
    if root is None:
        return []
    out: list[str] = []
    for node in root.iter("node"):
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        cy = (b[1] + b[3]) // 2
        if cy < min_y or cy > max_y:
            continue
        t = node_label(node).strip()
        if t and t not in IGNORE_TEXT:
            out.append(t)
    return out


def _composer_band(root: ET.Element | None) -> tuple[int, int]:
    sh = screen_height(root) if root is not None else 1280
    return int(sh * 0.62), sh - 28


def _attach_menu_band(root: ET.Element | None) -> tuple[int, int]:
    sh = screen_height(root) if root is not None else 1280
    return int(sh * 0.52), int(sh * 0.88)


def _verify_chat_composer_ready_root(root: ET.Element | None, serial: str = "") -> bool:
    """群聊输入栏就绪：只认「输入消息」或底部 EditText，不认群名。"""
    if root is None:
        return bool(serial and is_group_chat_activity(serial))
    sh = screen_height(root)
    y1, y2 = _composer_band(root)
    if any(
        t in ("输入消息", "Enter message")
        for t in collect_ui_texts_in_band(root, y1, y2)
    ):
        return True
    texts = collect_ui_texts(root)
    if any(t in MESSAGES_TAB_LABELS for t in texts):
        return False
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "EditText" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if b and b[1] >= int(sh * 0.70):
            return True
    return bool(serial and is_group_chat_activity(serial))


def _verify_chat_composer_ready(serial: str) -> bool:
    return cached_step_verify(serial, "img_composer", _verify_chat_composer_ready_serial)


def _verify_chat_composer_ready_serial(serial: str) -> bool:
    root = ui_hierarchy(serial)
    return _verify_chat_composer_ready_root(root, serial)


def _marker_hits_in_band(
    root: ET.Element | None,
    markers: tuple[str, ...],
    min_y: int,
    max_y: int,
) -> int:
    texts = collect_ui_texts_in_band(root, min_y, max_y)
    return sum(1 for m in markers if any(m in t for t in texts))


def _attach_menu_icon_count(root: ET.Element | None) -> int:
    """附件栏网格图标数（不依赖中文 OCR）。"""
    if root is None:
        return 0
    y_lo, y_hi = _attach_menu_band(root)
    n = 0
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        cls = node.attrib.get("class") or ""
        if "Image" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cy = (y1 + y2) // 2
        if cy < y_lo or cy > y_hi:
            continue
        cw, ch = x2 - x1, y2 - y1
        if 40 <= cw <= 180 and 40 <= ch <= 180:
            n += 1
    return n


def _attach_menu_label_hits(texts: list[str]) -> int:
    """附件栏短标签命中数（排除群聊长文案误含「图片」）。"""
    hits = 0
    for t in texts:
        s = t.strip()
        if not s or len(s) > 20:
            continue
        if s in ATTACH_MENU_MARKERS:
            hits += 1
            continue
        if s in ("图片", "拍摄", "照片", "图库"):
            hits += 1
    return hits


def _verify_attach_menu_open_serial(serial: str) -> bool:
    root = ui_hierarchy(serial, force=True, channel="clicker-img")
    if root is None:
        return False
    if _clicker_emoji_panel_open(root):
        return False
    sh = screen_height(root)
    texts = collect_ui_texts_in_band(root, int(sh * 0.45), sh - 40)
    label_hits = _attach_menu_label_hits(texts)
    icons = _attach_menu_icon_count(root)
    if label_hits >= 2:
        return True
    if label_hits >= 1 and icons >= 1:
        return True
    if icons >= 3:
        return True
    if icons >= 2 and label_hits >= 1:
        return True
    # W49: 55M 附件菜单用自定义视图，uiautomator 无法检测图标。
    # 备选方案：检测输入栏是否被顶到中间（菜单打开时 y < 0.55*sh，关闭时 y > 0.85*sh）
    # 但需要排除键盘打开的情况（键盘有很多单字母按钮，附件菜单没有）
    input_bounds = _clicker_input_row_bounds(root)
    if input_bounds:
        input_y = input_bounds[1]  # y1
        if input_y < int(sh * 0.55):
            # 检查是否是键盘（键盘有很多短文本按钮如 q w e r t y）
            keyboard_chars = 0
            for node in root.iter("node"):
                text = (node.attrib.get("text") or "").strip()
                if len(text) == 1 and text.isalpha():
                    keyboard_chars += 1
            if keyboard_chars >= 10:
                log.debug("附件菜单检测: 输入栏在中间但检测到键盘(%d个字母键)", keyboard_chars)
                return False
            if label_hits >= 1 or icons >= 2:
                log.debug(
                    "附件菜单检测(输入栏位置): y=%d labels=%d icons=%d",
                    input_y, label_hits, icons,
                )
                return True
    return False


def _verify_attach_menu_open(serial: str) -> bool:
    return cached_step_verify(serial, "img_attach_menu", _verify_attach_menu_open_serial)


def _clicker_input_row_bounds(root: ET.Element | None) -> tuple[int, int, int, int] | None:
    """当前输入栏 EditText 边界（+ 在其左侧）。"""
    if root is None:
        return None
    sh = screen_height(root)
    best: tuple[int, int, int, int] | None = None
    for node in root.iter("node"):
        if "EditText" not in (node.attrib.get("class") or ""):
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        if y1 < int(sh * 0.22):
            continue
        if y2 > sh - 6:
            pass
        elif y1 > int(sh * 0.90):
            continue
        if best is None or y1 > best[1]:
            best = b
    return best


def _clicker_composer_raised(root: ET.Element | None) -> bool:
    """输入栏被顶到屏幕中段（表情/附件面板占用底部时 + 在中间）。"""
    b = _clicker_input_row_bounds(root)
    if not b:
        return False
    return b[1] < int(screen_height(root) * 0.62)


def _clicker_emoji_panel_open(root: ET.Element | None) -> bool:
    """底部表情/贴纸面板已开（非附件「图片/拍摄」菜单）。"""
    if root is None:
        return False
    sh = screen_height(root)
    texts = collect_ui_texts_in_band(root, int(sh * 0.40), sh - 36)
    if any("图片" in t for t in texts) and any(
        any(m in t for t in texts) for m in ATTACH_MENU_MARKERS[1:3]
    ):
        return False
    icons = 0
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "Image" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cw, ch = x2 - x1, y2 - y1
        if y1 < int(sh * 0.46):
            continue
        if 22 <= cw <= 115 and 22 <= ch <= 115:
            icons += 1
    return icons >= 10


def _plus_left_of_input_row(root: ET.Element | None) -> tuple[int, int] | None:
    """+ 在输入框左侧（读屏算坐标，不点标识）。"""
    if root is None:
        return None
    sh = screen_height(root)
    inp = _clicker_input_row_bounds(root)
    if inp:
        x1, y1, x2, y2 = inp
        cy = (y1 + y2) // 2
        y_lo, y_hi = max(0, y1 - 28), min(sh, y2 + 28)
        for node in root.iter("node"):
            if node.attrib.get("clickable") != "true":
                continue
            cls = node.attrib.get("class") or ""
            if "Image" not in cls:
                continue
            b = parse_bounds(node.attrib.get("bounds", ""))
            if not b:
                continue
            ix1, iy1, ix2, iy2 = b
            if iy1 < y_lo or iy1 > y_hi or ix2 > x1 + 36:
                continue
            if (ix2 - ix1) > 90:
                continue
            return (ix1 + ix2) // 2, (iy1 + iy2) // 2
        off = int(os.environ.get("BOT_IMG_PLUS_OFFSET_X", "50") or 50)
        return max(32, x1 - off), cy
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        cls = node.attrib.get("class") or ""
        if "Image" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        if y1 < int(sh * 0.88) or x1 > 120:
            continue
        if (x2 - x1) > 90:
            continue
        return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def _clicker_plus_coord_candidates(serial: str) -> list[tuple[int, int, str]]:
    """+ 候选坐标：只用钉死坐标（W49: 禁用动态读屏，避免误算）。"""
    root = ui_hierarchy(serial, force=True, channel="clicker-img")
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int, str]] = []

    def add(x: int, y: int, tag: str) -> None:
        key = (x, y)
        if key in seen:
            return
        seen.add(key)
        out.append((x, y, tag))

    raised = _clicker_composer_raised(root) or _clicker_emoji_panel_open(root)
    if raised:
        for pin_key, tag in (("chat_plus_raised", "plus_raised"), ("chat_plus", "plus_bottom_fb")):
            pt = pinned_xy("clicker", pin_key)
            if pt:
                add(pt[0], pt[1], tag)
    else:
        for pin_key, tag in (("chat_plus", "plus_bottom"), ("chat_plus_raised", "plus_raised_fb")):
            pt = pinned_xy("clicker", pin_key)
            if pt:
                add(pt[0], pt[1], tag)
    if not out:
        add(45, 1234, "plus_default")
    return out


def resolve_clicker_attach_image_xy(serial: str) -> tuple[int, int]:
    """附件栏「图片」：读屏定位优先，底栏/顶起两种布局回退钉死。"""
    root = ui_hierarchy(serial, force=True)
    if root is not None:
        y_lo, y_hi = _attach_menu_band(root)
        for node in root.iter("node"):
            label = node_label(node)
            if "图片" not in label:
                continue
            b = parse_bounds(node.attrib.get("bounds", ""))
            if not b:
                continue
            cy = (b[1] + b[3]) // 2
            if y_lo <= cy <= y_hi:
                cx, cyy = node_center(b)
                log.info("发图读屏定位「图片」@(%d,%d)", cx, cyy)
                return cx, cyy
        icons: list[tuple[int, int, int]] = []
        for node in root.iter("node"):
            if node.attrib.get("clickable") != "true":
                continue
            cls = node.attrib.get("class") or ""
            if "Image" not in cls:
                continue
            b = parse_bounds(node.attrib.get("bounds", ""))
            if not b:
                continue
            x1, y1, x2, y2 = b
            cy = (y1 + y2) // 2
            if cy < y_lo or cy > y_hi or x1 > 220:
                continue
            cw, ch = x2 - x1, y2 - y1
            if 40 <= cw <= 160 and 40 <= ch <= 160:
                icons.append((x1, *node_center(b)))
        if icons:
            icons.sort(key=lambda t: (t[1], t[0]))
            cx, cy = icons[0][1], icons[0][2]
            log.info("发图读屏定位附件图标 @(%d,%d)", cx, cy)
            return cx, cy
    if root is not None and not _clicker_composer_raised(root):
        pt = pinned_attach_image_xy()
    else:
        pt = (
            pinned_xy("clicker", "attach_image_raised")
            or pinned_attach_image_xy()
        )
    return pt


def clicker_fire_attach_image(serial: str) -> bool:
    """附件栏已开：立即点「图片」，不做多轮 recover。"""
    candidates: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()

    def add(x: int, y: int, tag: str) -> None:
        key = (x, y)
        if key in seen:
            return
        seen.add(key)
        candidates.append((x, y, tag))

    root = ui_hierarchy(serial, force=True, channel="clicker-img")
    if root is not None:
        y_lo, y_hi = _attach_menu_band(root)
        icons: list[tuple[int, int, int]] = []
        for node in root.iter("node"):
            if node.attrib.get("clickable") != "true":
                continue
            cls = node.attrib.get("class") or ""
            if "Image" not in cls:
                continue
            b = parse_bounds(node.attrib.get("bounds", ""))
            if not b:
                continue
            x1, y1, x2, y2 = b
            cy = (y1 + y2) // 2
            if cy < y_lo or cy > y_hi:
                continue
            cw, ch = x2 - x1, y2 - y1
            if 40 <= cw <= 180 and 40 <= ch <= 180:
                icons.append((x1, cy, *node_center(b)))
        if icons:
            icons.sort(key=lambda t: (t[1], t[0]))
            cx, cy = icons[0][2], icons[0][3]
            add(cx, cy, "screen_icon0")
    ix, iy = resolve_clicker_attach_image_xy(serial)
    add(ix, iy, "resolve")
    for pt, tag in (
        (pinned_xy("clicker", "attach_image"), "pinned"),
        (pinned_xy("clicker", "attach_image_bottom"), "pinned_bottom"),
        ((72, 720), "legacy_raised"),
        (pinned_xy("clicker", "attach_image_raised"), "pinned_raised"),
        ((90, 800), "mid_fb"),
    ):
        if pt:
            add(pt[0], pt[1], tag)
    for ix, iy, tag in candidates:
        clicker_tap_pinned(serial, ix, iy, f"attach_image_{tag}")
        clicker_w(0.8, 1.2)
        invalidate_step_verify_cache(serial)
        if _verify_gallery_picker_open(serial):
            log.info("点图片进相册 @(%d,%d) tag=%s", ix, iy, tag)
            return True
        root2 = ui_hierarchy(serial, force=True, channel="clicker-img")
        if _is_gallery_fullscreen_viewer(root2):
            device_safe_back(serial, reason="单张浏览→网格")
            clicker_w(0.55, 0.70)
            invalidate_step_verify_cache(serial)
            if _verify_gallery_picker_open(serial):
                log.info("点图片进相册(单张返回) @(%d,%d) tag=%s", ix, iy, tag)
                return True
        if _count_gallery_thumbnails(root2) >= 3:
            log.info("点图片见缩略图网格 @(%d,%d) tag=%s", ix, iy, tag)
            return True
    return False


def resolve_clicker_chat_plus_xy(serial: str) -> tuple[int, int]:
    """左机 + 坐标：读屏 EditText 左侧优先；顶起时用中段钉死。"""
    root = ui_hierarchy(serial)
    dyn = _plus_left_of_input_row(root)
    if dyn:
        return dyn
    raised = _clicker_composer_raised(root) or _clicker_emoji_panel_open(root)
    if raised:
        pt = pinned_xy("clicker", "chat_plus_raised")
        if pt:
            return pt
    pt = pinned_xy("clicker", "chat_plus")
    if pt:
        return pt
    snap = ui_snapshot(serial, chat=False)
    fx, fy = resolve_chat_input_xy(snap, None, None)
    sh = screen_height(snap.root) if snap.root is not None else 1280
    sw = 720
    if snap.input_bounds:
        sw = max(sw, snap.input_bounds[2] + 40)
    plus_off = int(os.environ.get("BOT_IMG_PLUS_OFFSET_X", "72") or 72)
    return min(sw - 36, fx + plus_off), min(sh - 80, fy)


def clicker_tap_plus_until_attach_menu(
    serial: str,
    max_tries: int | None = None,
) -> bool:
    """点 + 直到附件菜单出现「图片」；每次重算 + 位置，禁止乱点。"""
    tries = max(1, max_tries if max_tries is not None else CLICK_VERIFY_TRIES)
    plus_wait = max(0.22, CLICKER_TAP_MS / 1000.0 * 2.5) if CLICKER_FAST else 0.28
    for attempt in range(tries):
        if attempt == 0:
            clicker_hide_keyboard_for_attach(serial)
        else:
            dismiss_soft_keyboard(serial)
        invalidate_step_verify_cache(serial)
        if _verify_attach_menu_open_serial(serial):
            if attempt:
                log.info("附件菜单已开，跳过点+")
            return True
        if _verify_gallery_picker_open(serial):
            return True
        root = ui_hierarchy(serial, force=True, channel="clicker-img")
        sh = screen_height(root) if root is not None else 1280
        band_texts = collect_ui_texts_in_band(root, int(sh * 0.45), sh - 40) if root else []
        if _attach_menu_icon_count(root) >= 3 and _attach_menu_label_hits(band_texts) >= 1:
            log.info("附件菜单已开(图标+标签)，跳过点+")
            return True
        layout = "raised" if (_clicker_composer_raised(root) or _clicker_emoji_panel_open(root)) else "bottom"
        coords_try = _clicker_plus_coord_candidates(serial)
        opened = False
        last_xy = coords_try[0][:2] if coords_try else (0, 0)
        for cpx, cpy, purpose in coords_try:
            last_xy = (cpx, cpy)
            # W49: 按用户反馈，55M 第一次点+可能只滚页面，需再点一次
            clicker_tap_pinned(serial, cpx, cpy, f"chat_plus_{purpose}")
            clicker_w(plus_wait, plus_wait + 0.12)
            # 强制再点一次（用户反馈：点击+好后没有看到图片再点击一次即可）
            clicker_tap_pinned(serial, cpx, cpy, f"chat_plus_{purpose}_force2nd")
            clicker_w(plus_wait + 0.04, plus_wait + 0.16)
            invalidate_step_verify_cache(serial)
            if _verify_attach_menu_open_serial(serial):
                log.info("点+展开附件菜单 @(%d,%d) tag=%s layout=%s retry=%d", cpx, cpy, purpose, layout, attempt)
                opened = True
                break
            clicker_tap_pinned(serial, cpx, cpy, f"chat_plus_{purpose}_toggle")
            clicker_w(plus_wait + 0.04, plus_wait + 0.16)
            invalidate_step_verify_cache(serial)
            if _verify_attach_menu_open_serial(serial):
                log.info("点+三次切换附件菜单 @(%d,%d) tag=%s layout=%s retry=%d", cpx, cpy, purpose, layout, attempt)
                opened = True
                break
        if opened:
            return True
        root_after = ui_hierarchy(serial, force=True, channel="clicker-img")
        px, py = (coords_try[0][0], coords_try[0][1]) if coords_try else (45, 1234)
        if _clicker_emoji_panel_open(root_after) or (
            not _verify_attach_menu_open_serial(serial)
            and _marker_hits_in_band(root_after, ("[",), int(screen_height(root_after) * 0.45), screen_height(root_after) - 40) >= 3
        ):
            log.info("点+打开表情面板，再点+切附件栏 @(%d,%d) attempt=%d/%d", px, py, attempt + 1, tries)
            clicker_tap_pinned(serial, px, py, "chat_plus_toggle")
            clicker_w(plus_wait + 0.06, plus_wait + 0.2)
            invalidate_step_verify_cache(serial)
            if _verify_attach_menu_open_serial(serial):
                return True
        else:
            log.warning(
                "点+未出附件菜单(无「图片」) @(%d,%d) layout=%s attempt=%d/%d tried=%d",
                last_xy[0], last_xy[1], layout, attempt + 1, tries, len(coords_try),
            )
    return False


def _count_gallery_thumbnails(root: ET.Element | None) -> int:
    """相册网格缩略图（排除聊天区气泡）。"""
    if root is None:
        return 0
    sh = screen_height(root)
    y_lo, y_hi = int(sh * 0.10), int(sh * 0.52)
    n = 0
    for node in root.iter("node"):
        cls = node.attrib.get("class", "")
        if "Image" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cw, ch = x2 - x1, y2 - y1
        if 70 <= cw <= 420 and 70 <= ch <= 420 and y_lo < y1 < y_hi:
            n += 1
    return n


def cached_step_verify(serial: str, step_id: str, fn: Callable[[str], bool]) -> bool:
    """步骤识别缓存：同一步骤短 TTL 内复用 dump 结论。"""
    if not CLICK_VERIFY or not is_clicker_serial(serial):
        return fn(serial)
    key = (serial, step_id)
    now = time.time()
    hit = _STEP_VERIFY_CACHE.get(key)
    if hit and now - hit[0] < STEP_VERIFY_CACHE_MS:
        return hit[1]
    ok = fn(serial)
    _STEP_VERIFY_CACHE[key] = (now, ok)
    return ok


def clicker_composer_or_gallery_ready(serial: str, root: ET.Element | None = None) -> bool:
    """发图前就绪：群聊 composer 或相册网格（附件栏 alone 不算）。"""
    if _verify_gallery_picker_open(serial):
        return True
    if root is None:
        root = ui_hierarchy(serial)
    if root is None:
        return False
    if _verify_attach_menu_open_serial(serial):
        return False
    return _verify_chat_composer_ready_root(root, serial)


def clicker_img_task_surface_ready(serial: str, root: ET.Element | None = None) -> bool:
    """发图任务界面：输入栏 / 附件栏 / 相册，不认群名。"""
    if root is None:
        root = ui_hierarchy(serial)
    if root is None:
        return False
    if _verify_chat_composer_ready_root(root, serial):
        return True
    y1, y2 = _attach_menu_band(root)
    if _marker_hits_in_band(root, ("图片",), y1, y2) >= 1:
        return True
    blob = _ui_text_blob(root).replace(" ", "")
    if "/9" in blob:
        return True
    return _count_gallery_thumbnails(root) >= 3


def _clicker_left_task_surface(serial: str) -> bool:
    """离开 55M 或只剩桌面导航层。"""
    if is_on_launcher(serial) or not is_55m_foreground(serial):
        return True
    root = ui_hierarchy(serial)
    if root is None:
        return False
    if clicker_img_task_surface_ready(serial, root):
        return False
    if _verify_chat_composer_ready_root(root, serial):
        return False
    sh = screen_height(root)
    nav_y = sh - min(NAV_BAR_RESERVE_PX, int(sh * 0.12))
    nav_hits = 0
    for node in root.iter("node"):
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[1] < nav_y:
            continue
        desc = (node.attrib.get("content-desc") or node.attrib.get("text") or "").strip()
        if desc in ("返回", "主屏幕", "概览", "Back", "Home", "Overview"):
            nav_hits += 1
    return nav_hits >= 2


def clicker_tap_chat_neutral(serial: str) -> None:
    """点聊天区空白收起附件栏（发图流程内禁止）。"""
    if _clicker_img_flow_active(serial):
        log.warning("左机发图流程禁止点聊天区空白")
        return
    root = ui_hierarchy(serial)
    sw = screen_width(root) if root is not None else 720
    sh = screen_height(root) if root is not None else 1280
    adb_tap_raw(serial, sw // 2, int(sh * 0.40))
    clicker_w(0.1, 0.15)
    invalidate_step_verify_cache(serial)


def clicker_recover_one_step(serial: str, step: str) -> None:
    """任务中界面偏离：退回上一步，禁止点系统三角/圆/方导航键。"""
    invalidate_step_verify_cache(serial)
    if _clicker_img_flow_active(serial):
        if _clicker_left_task_surface(serial):
            log.warning("左机发图偏离 55M，尝试拉起")
            launch_messenger_app(serial)
            clicker_w(0.5, 0.25)
        else:
            log.warning("左机发图流程禁止 recover(%s)，仅同点重试", step)
        return
    if _clicker_left_task_surface(serial):
        log.warning("左机偏离 55M/任务面，尝试拉起")
        launch_messenger_app(serial)
        clicker_w(0.5, 0.25)
        return
    if _verify_gallery_picker_open(serial):
        clicker_safe_back(serial, reason="关闭相册")
    elif step.startswith("gallery"):
        clicker_tap_chat_neutral(serial)
    elif step == "chat_plus" or _verify_attach_menu_open(serial):
        clicker_tap_chat_neutral(serial)
    else:
        clicker_tap_chat_neutral(serial)
    clicker_w(0.12, 0.18)


def _attach_menu_visible(root: ET.Element | None) -> bool:
    if root is None:
        return False
    sh = screen_height(root)
    texts = collect_ui_texts_in_band(root, int(sh * 0.45), sh - 40)
    return _attach_menu_label_hits(texts) >= 2


def _verify_gallery_picker_open_serial(serial: str) -> bool:
    root = ui_hierarchy(serial, force=True)
    if root is None:
        return False
    if _attach_menu_visible(root):
        return False
    if _is_gallery_fullscreen_viewer(root):
        return False
    sh = screen_height(root)
    blob = _ui_text_blob(root).replace(" ", "")
    if "/9" in blob:
        return True
    top_texts = collect_ui_texts_in_band(root, int(sh * 0.06), int(sh * 0.20))
    if any(k in t for t in top_texts for k in ("相册", "全部", "最近", "相机胶卷", "发送图片")):
        thumbs = _count_gallery_thumbnails(root)
        return thumbs >= 3
    thumbs = _count_gallery_thumbnails(root)
    return thumbs >= 3


def _verify_gallery_picker_open(serial: str) -> bool:
    return cached_step_verify(serial, "img_gallery", _verify_gallery_picker_open_serial)


def clicker_tap_until_verify(
    serial: str,
    x: int,
    y: int,
    *,
    verify: Callable[[str], bool],
    label: str,
    max_tries: int | None = None,
    fast_wait: float = 0.1,
    slow_wait: float = 0.18,
    recover_on_fail: bool = True,
) -> bool:
    """W49：只点钉死坐标；标识仅用于读屏验证，禁止点标识本身。"""
    tries = max_tries if max_tries is not None else CLICK_VERIFY_TRIES
    use_verify = CLICK_VERIFY and is_clicker_serial(serial)
    if _clicker_img_flow_active(serial):
        recover_on_fail = False
    if use_verify and verify(serial):
        log.info("步骤标识已存在 %s，跳过点击", label)
        return True
    for attempt in range(tries):
        if use_verify and _clicker_left_task_surface(serial):
            if not _clicker_img_flow_active(serial):
                clicker_recover_one_step(serial, label)
            continue
        if is_clicker_serial(serial) and CLICKER_IMG_TAP_ONLY:
            clicker_tap_pinned(serial, x, y, label)
        else:
            adb_tap_raw(serial, x, y, invalidate=True)
        invalidate_step_verify_cache(serial)
        if is_clicker_serial(serial):
            clicker_w(fast_wait, slow_wait)
        else:
            w(slow_wait, fast_wait)
        if not use_verify or verify(serial):
            if use_verify and attempt:
                log.info("点击验证通过 %s @ (%d,%d) retry=%d", label, x, y, attempt)
            return True
        log.warning("点击未达预期 %s @ (%d,%d) attempt=%d/%d", label, x, y, attempt + 1, tries)
        if use_verify and recover_on_fail:
            clicker_recover_one_step(serial, label)
    return False


def _clicker_wrong_for_image_task(serial: str) -> bool:
    """发图任务中的错屏：消息列表/离开 55M（不认群名）。"""
    if _clicker_left_task_surface(serial):
        return True
    root = ui_hierarchy(serial)
    if root is None:
        return True
    texts = collect_ui_texts(root)
    return any(t in MESSAGES_TAB_LABELS for t in texts)


def _resolve_plus_xy(
    serial: str,
    snap: UiSnapshot,
    settings: dict[str, str] | None,
    bot: dict | None,
    input_xy: tuple[int, int] | None,
) -> tuple[int, int]:
    """输入栏左侧 + 按钮坐标（W49：+ 在左；底栏/中段两种布局）。"""
    if IMG_PINNED and is_clicker_serial(serial):
        return resolve_clicker_chat_plus_xy(serial)
    fx, fy = resolve_chat_input_xy(snap, settings, bot)
    if input_xy:
        ix, iy = input_xy
        _, _, safe_y = _chat_input_defaults(snap)
        if iy <= safe_y:
            fx, fy = ix, iy
    plus_off = int(os.environ.get("BOT_IMG_PLUS_OFFSET_X", "72") or 72)
    plus_y = int(os.environ.get("BOT_IMG_PLUS_OFFSET_Y", "0") or 0)
    sh = screen_height(snap.root) if snap.root is not None else 1280
    sw = 720
    if snap.input_bounds:
        sw = max(sw, snap.input_bounds[2] + 40)
    px = min(sw - 36, fx + plus_off)
    py = min(sh - 80, fy + plus_y)
    return px, py


def _gallery_open_confirmed(serial: str) -> bool:
    root = ui_hierarchy(serial, force=True, channel="clicker-img")
    if root is not None and _is_gallery_fullscreen_viewer(root):
        device_safe_back(serial, reason="单张浏览→网格")
        clicker_w(0.55, 0.70)
        invalidate_step_verify_cache(serial)
        root = ui_hierarchy(serial, force=True, channel="clicker-img")
    if _verify_gallery_picker_open(serial):
        return True
    return _count_gallery_thumbnails(root) >= 3


def _open_chat_image_picker_trust(serial: str) -> bool:
    """W49：信任钉死 + fire 进相册；须见到网格才继续（禁止盲勾选）。"""
    if _gallery_open_confirmed(serial):
        log.info("发图信任模式：已在相册网格")
        return True
    for attempt in range(3):
        if attempt:
            dismiss_soft_keyboard(serial)
            clicker_hide_keyboard_for_attach(serial)
            invalidate_step_verify_cache(serial)
        if _gallery_open_confirmed(serial):
            log.info("发图信任模式：已确认相册网格 try=%d", attempt + 1)
            return True
        if clicker_fire_attach_image(serial) and _gallery_open_confirmed(serial):
            log.info("发图信任模式：快速 fire 进相册 try=%d", attempt + 1)
            return True
        if _verify_attach_menu_open(serial):
            ix, iy = resolve_clicker_attach_image_xy(serial)
            log.info("发图信任模式：附件栏已开，点图片 @(%d,%d) try=%d", ix, iy, attempt + 1)
            if clicker_fire_attach_image(serial) and _gallery_open_confirmed(serial):
                log.info("发图信任模式：附件栏 fire 进相册 try=%d", attempt + 1)
                return True
            clicker_tap_pinned(serial, ix, iy, "trust_image_from_menu")
            clicker_w(0.8, 1.2)
            invalidate_step_verify_cache(serial)
        else:
            px, py = resolve_clicker_chat_plus_xy(serial)
            ix, iy = resolve_clicker_attach_image_xy(serial)
            log.info("发图信任模式: + @(%d,%d) 图片 @(%d,%d) try=%d", px, py, ix, iy, attempt + 1)
            clicker_tap_plus_until_attach_menu(serial, max_tries=2)
        if clicker_fire_attach_image(serial) and _gallery_open_confirmed(serial):
            log.info("发图信任模式：fire 进相册 try=%d", attempt + 1)
            return True
        ix, iy = resolve_clicker_attach_image_xy(serial)
        clicker_tap_pinned(serial, ix, iy, "trust_image_direct")
        clicker_w(0.8, 1.2)
        invalidate_step_verify_cache(serial)
        if _gallery_open_confirmed(serial):
            log.info("发图信任模式：直接点图片进相册 try=%d", attempt + 1)
            return True
        log.warning("发图信任模式：相册未确认 try=%d/3", attempt + 1)
    return False


def _open_chat_image_picker(
    serial: str,
    bot: dict,
    settings: dict[str, str] | None,
    input_xy: tuple[int, int] | None,
) -> bool:
    """群聊：输入栏左侧 + → 附件「图片」（钉死坐标优先，禁止 u2 乱扫）。"""
    # 左机发图与键盘无关：第一步只点 +，不 ESC/不收键盘
    if not is_clicker_serial(serial):
        try:
            adb_run(serial, "shell", "input", "keyevent", "4")
            w(0.2, 0.06)
        except Exception:
            pass

    if IMG_PINNED and is_clicker_serial(serial):
        clicker_hide_keyboard_for_attach(serial)
        # W49：55M 验证不可靠，直接走信任点击路径
        if IMG_TRUST_CLICK:
            return _open_chat_image_picker_trust(serial)
        if not _verify_chat_composer_ready_serial(serial):
            if not ensure_clicker_in_group(serial, bot, reason="image-picker"):
                log.warning("发图：输入栏未就绪且回群失败")
                return False
            clicker_hide_keyboard_for_attach(serial)
            if not _verify_chat_composer_ready_serial(serial):
                log.warning("发图：群聊输入栏仍未就绪")
                return False
        if _clicker_wrong_for_image_task(serial):
            if not ensure_clicker_in_group(serial, bot, reason="image-picker"):
                log.warning("发图：错屏且回群失败")
                return False
        if _verify_gallery_picker_open(serial):
            log.info("发图：已在相册，跳过 +/图片")
            return True
        if _verify_attach_menu_open(serial):
            if clicker_fire_attach_image(serial):
                log.info("发图：附件栏已开，fire 点图片进相册")
                return True
            ix, iy = resolve_clicker_attach_image_xy(serial)
            clicker_fire_tap(serial, ix, iy)
            clicker_w(0.08, 0.15)
            invalidate_step_verify_cache(serial)
            if _verify_gallery_picker_open(serial):
                log.info("发图：附件栏 fire 补点图片进相册 @(%d,%d)", ix, iy)
                return True
            log.warning("附件栏已开但未进相册")
            return False
        if not clicker_tap_plus_until_attach_menu(serial):
            log.warning("点+未展开附件菜单")
            return False
        if clicker_fire_attach_image(serial):
            log.info("发图钉死 +→图片 已进相册")
            clicker_w(0.08, 0.15)
            if _is_gallery_fullscreen_viewer(ui_hierarchy(serial, force=True)):
                device_safe_back(serial, reason="单张浏览→网格")
                clicker_w(0.3, 0.4)
                invalidate_step_verify_cache(serial)
            return _verify_gallery_picker_open(serial)
        log.warning("钉死坐标点「图片」未进相册")
        return False

    if is_clicker_serial(serial) and CLICKER_IMG_TAP_ONLY:
        log.warning("左机发图须走钉死坐标路径")
        return False

    snap = ui_snapshot(serial, chat=False)
    px, py = _resolve_plus_xy(serial, snap, settings, bot, input_xy)
    if is_clicker_serial(serial) and CLICK_VERIFY:
        if not clicker_tap_plus_until_attach_menu(serial):
            log.warning("点+未展开附件菜单")
            return False
    else:
        adb_tap_raw(serial, px, py)
        clicker_w(0.12, 0.12) if is_clicker_serial(serial) else w(0.45, 0.12)

    opened = False
    dev = _get_u2_device(serial) if not (IMG_PINNED and is_clicker_serial(serial)) else None
    if dev and not is_clicker_serial(serial):
        for label in ("＋", "+", "更多"):
            try:
                node = dev(text=label)
                if node.exists(timeout=0.8):
                    node.click()
                    opened = True
                    log.info("发图点+ [%s]", label)
                    break
            except Exception:
                continue
    if not opened:
        adb_tap_raw(serial, px, py)
        clicker_w(0.08, 0.1) if is_clicker_serial(serial) else w(0.35, 0.1)

    clicker_w(0.12, 0.12) if is_clicker_serial(serial) else w(0.5, 0.12)
    picked = False
    if dev and not is_clicker_serial(serial):
        for label in ("图片", "照片"):
            try:
                node = dev(text=label)
                if node.exists(timeout=2.0):
                    node.click()
                    picked = True
                    log.info("发图点菜单 [%s]", label)
                    break
            except Exception:
                continue
    if not picked and dev and not is_clicker_serial(serial):
        try:
            nodes = dev(textContains="图")
            for i in range(min(nodes.count, 6)):
                t = (nodes[i].info.get("text") or "").strip()
                if t in ("图片", "照片", "图库"):
                    nodes[i].click()
                    picked = True
                    log.info("发图点菜单 text=%s", t)
                    break
        except Exception:
            pass
    if not picked:
        img_fb = pinned_attach_image_xy() if is_clicker_serial(serial) else None
        if img_fb:
            if is_clicker_serial(serial) and CLICK_VERIFY:
                if not clicker_tap_until_verify(
                    serial, img_fb[0], img_fb[1],
                    verify=_verify_gallery_picker_open,
                    label="attach_image-fb",
                ):
                    return False
            else:
                adb_tap_raw(serial, img_fb[0], img_fb[1])
        else:
            adb_tap_raw(serial, min(px + 120, 680), py - 40)
    clicker_w(0.15, 0.25) if is_clicker_serial(serial) else w(0.8, 0.25)
    if is_clicker_serial(serial) and CLICK_VERIFY and not _verify_gallery_picker_open(serial):
        log.warning("发图菜单未进入相册")
        return False
    return True


def _verify_gallery_selected_at_least(serial: str, min_count: int) -> bool:
    def check(s: str) -> bool:
        root = ui_hierarchy(s, force=True)
        return _gallery_selected_count(root) >= min_count

    return cached_step_verify(serial, f"img_gallery_sel_{min_count}", check)


def _verify_gallery_send_tapped_serial(serial: str) -> bool:
    root = ui_hierarchy(serial, force=True)
    if root is None:
        return False
    if _is_gallery_fullscreen_viewer(root):
        return False
    if _gallery_selected_count(root) > 0:
        return False
    if _count_gallery_thumbnails(root) >= 3:
        return False
    blob = _ui_text_blob(root).replace(" ", "")
    if "/9" in blob:
        return False
    return _verify_chat_composer_ready_root(root, serial)


def _verify_gallery_send_tapped(serial: str) -> bool:
    return cached_step_verify(serial, "img_gallery_send", _verify_gallery_send_tapped_serial)


def _u2_bounds_dict(node) -> tuple[int, int, int, int] | None:
    try:
        b = node.info.get("bounds") or {}
        if isinstance(b, dict):
            x1, y1, x2, y2 = b.get("left"), b.get("top"), b.get("right"), b.get("bottom")
        else:
            return None
        if None in (x1, y1, x2, y2):
            return None
        w, h = x2 - x1, y2 - y1
        if w < 60 or h < 60:
            return None
        return int(x1), int(y1), int(x2), int(y2)
    except Exception:
        return None


def _close_image_preview_if_open(serial: str) -> None:
    """误点缩略图进入大图预览时按返回。"""
    dev = _get_u2_device(serial)
    if not dev:
        return
    try:
        sw, sh = dev.window_size()
        for node in dev(className="android.widget.ImageView"):
            b = _u2_bounds_dict(node)
            if not b:
                continue
            x1, y1, x2, y2 = b
            if (x2 - x1) > sw * 0.75 and (y2 - y1) > sh * 0.55 and y1 < sh * 0.2:
                log.info("检测到大图预览，按返回")
                device_safe_back(serial, reason="关闭大图预览")
                w(0.45, 0.12)
                return
    except Exception:
        pass


def _checkbox_tap_points(dev, serial: str, count: int) -> list[tuple[int, int]]:
    """优先找真实 CheckBox；否则缩略图格左上角极小区域（避免点开大图）。"""
    points: list[tuple[int, int]] = []
    try:
        sw, sh = dev.window_size()
        checks: list[tuple[int, int, int, int]] = []
        for cls in (
            "android.widget.CheckBox",
            "android.widget.CompoundButton",
            "androidx.appcompat.widget.AppCompatCheckBox",
        ):
            coll = dev(className=cls)
            for i in range(coll.count):
                b = _u2_bounds_dict(coll[i])
                if not b:
                    continue
                w, h = b[2] - b[0], b[3] - b[1]
                if 16 <= w <= 96 and 16 <= h <= 96 and b[1] > sh * 0.12:
                    checks.append(b)
        if len(checks) >= count:
            key = (lambda b: ((b[1] + b[3]) // 2, (b[0] + b[2]) // 2))
            if BOT_IMG_NEWEST_AT == "bottom":
                key = (lambda b: (-((b[1] + b[3]) // 2), (b[0] + b[2]) // 2))
            checks.sort(key=key)
            seen: list[tuple[int, int]] = []
            for b in checks:
                cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
                if any(abs(cx - sx) < 40 and abs(cy - sy) < 40 for sx, sy in seen):
                    continue
                seen.append((cx, cy))
                points.append((cx, cy))
                if len(points) >= count:
                    return points
    except Exception as ex:
        log.debug("CheckBox 枚举: %s", ex)

    cells: list[tuple[int, int, int, int, int]] = []
    try:
        sw, sh = dev.window_size()
        for cls in ("android.widget.FrameLayout", "android.widget.RelativeLayout"):
            coll = dev(className=cls)
            for i in range(coll.count):
                b = _u2_bounds_dict(coll[i])
                if not b:
                    continue
                x1, y1, x2, y2 = b
                cw, ch = x2 - x1, y2 - y1
                area = cw * ch
                if cw < 90 or ch < 90 or cw > 420 or ch > 420:
                    continue
                if area < 12000 or area > 160000:
                    continue
                if y1 < sh * 0.18 or y2 > sh * 0.92:
                    continue
                cy, cx = (y1 + y2) // 2, (x1 + x2) // 2
                cells.append((cy, cx, x1, y1, x2, y2))
    except Exception as ex:
        log.warning("枚举缩略图格失败: %s", ex)
        return points

    uniq: list[tuple[int, int, int, int, int]] = []
    cell_order = (lambda t: (t[0], t[1])) if BOT_IMG_NEWEST_AT == "top" else (lambda t: (-t[0], t[1]))
    for cy, cx, x1, y1, x2, y2 in sorted(cells, key=cell_order):
        if any(abs(cy - u[0]) < 35 and abs(cx - u[1]) < 35 for u in uniq):
            continue
        uniq.append((cy, cx, x1, y1, x2, y2))

    inset_pct = float(os.environ.get("BOT_IMG_CHECK_INSET_PCT", "0.07") or 0.07)
    inset_max = int(os.environ.get("BOT_IMG_CHECK_INSET_MAX", "14") or 14)
    for _cy, _cx, x1, y1, x2, y2 in uniq[: max(1, count)]:
        cw, ch = x2 - x1, y2 - y1
        tx = x1 + min(inset_max, max(8, int(cw * inset_pct)))
        ty = y1 + min(inset_max, max(8, int(ch * inset_pct)))
        points.append((tx, ty))
        if len(points) >= count:
            break
    return points


def _is_gallery_fullscreen_viewer(root: ET.Element | None) -> bool:
    """单张浏览（如 7/1621）不是批量勾选网格。"""
    if root is None:
        return False
    blob = _ui_text_blob(root).replace(" ", "")
    top_blob = "".join(
        collect_ui_texts_in_band(root, int(screen_height(root) * 0.04), int(screen_height(root) * 0.18))
    ).replace(" ", "")
    if re.search(r"^\d+/1\d{3,}$", top_blob):
        return True
    if _count_gallery_thumbnails(root) <= 1 and "/9" not in blob:
        top = collect_ui_texts_in_band(root, int(screen_height(root) * 0.05), int(screen_height(root) * 0.22))
        if any("全选" in t or "相册" in t for t in top) and _count_gallery_thumbnails(root) <= 1:
            return True
    return False


def _resolve_gallery_toprow_checkpoints(root: ET.Element | None, count: int) -> list[tuple[int, int]]:
    """读屏算顶行 N 张缩略图右上角勾选圈（Pixel XL / itel 通用）。"""
    if root is None or count <= 0:
        return []
    sh = screen_height(root)
    y_lo, y_hi = int(sh * 0.08), int(sh * 0.55)
    cells: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "Image" not in cls:
            continue
        b = parse_bounds(node.attrib.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        cw, ch = x2 - x1, y2 - y1
        if 70 <= cw <= 420 and 70 <= ch <= 420 and y_lo < y1 < y_hi:
            cells.append((y1, x1, x2, y2))
    cells.sort()
    if not cells:
        return []
    row_y = cells[0][0]
    row: list[tuple[int, int, int, int]] = []
    for cell in cells:
        if abs(cell[0] - row_y) <= 48:
            row.append(cell)
        elif len(row) >= count:
            break
        else:
            row_y = cell[0]
            row = [cell]
    points: list[tuple[int, int]] = []
    for y1, x1, x2, y2 in row[:count]:
        tx = x2 - max(14, min(26, (x2 - x1) // 7))
        ty = y1 + max(18, min(32, (y2 - y1) // 5))
        points.append((tx, ty))
    return points


def _gallery_selected_count(root: ET.Element | None) -> int:
    if root is None:
        return 0
    blob = _ui_text_blob(root).replace(" ", "")
    m = re.search(r"(\d+)/9", blob)
    if m:
        return int(m.group(1))
    texts = collect_ui_texts(root)
    for t in texts:
        m = re.search(r"(\d+)\s*/\s*9", t.replace(" ", ""))
        if m:
            return int(m.group(1))
    if "/9" in texts:
        idx = texts.index("/9")
        if idx > 0 and texts[idx - 1].strip().isdigit():
            return int(texts[idx - 1].strip())
    # 部分 ROM 无 /9：数 selected 标记
    sel = 0
    for node in root.iter("node"):
        if node.attrib.get("selected") == "true" and "Check" in (node.attrib.get("class") or ""):
            sel += 1
    if sel:
        return sel
    return 0


def _select_gallery_image_checkboxes(serial: str, count: int) -> int:
    """W49：+→图片→勾选顶行 N 张（读屏算圈心，钉死坐标兜底）→右下蓝钮发送。"""
    _close_image_preview_if_open(serial)
    root = ui_hierarchy(serial, force=True, channel="clicker-img")
    if _is_gallery_fullscreen_viewer(root):
        log.warning("发图在单张浏览页，按返回进网格")
        device_safe_back(serial, reason="退出单张浏览")
        clicker_w(0.55, 0.70)
        invalidate_step_verify_cache(serial)
        root = ui_hierarchy(serial, force=True, channel="clicker-img")
    if root is None or _is_gallery_fullscreen_viewer(root):
        log.warning("发图未确认相册网格，取消本次勾选")
        return 0
    if not _verify_gallery_picker_open(serial):
        root_chk = ui_hierarchy(serial, force=True, channel="clicker-img")
        if _count_gallery_thumbnails(root_chk) < 3:
            log.warning("发图未确认相册网格，取消本次勾选")
            return 0
        log.info("发图：见缩略图网格，继续勾选")

    dynamic_pts = _resolve_gallery_toprow_checkpoints(root, count)
    pinned_pts: list[tuple[int, int]] = []
    if IMG_PINNED and is_clicker_serial(serial):
        for i in range(count):
            pt = pinned_xy("clicker", "gallery_check_top3", index=i)
            if pt:
                pinned_pts.append(pt)
    if IMG_TRUST_CLICK and is_clicker_serial(serial) and len(pinned_pts) >= count:
        tap_pts = pinned_pts[:count]
    elif IMG_PINNED and is_clicker_serial(serial) and len(pinned_pts) >= count:
        tap_pts = pinned_pts[:count]
    elif len(dynamic_pts) >= count:
        tap_pts = dynamic_pts
    else:
        tap_pts = pinned_pts or dynamic_pts

    if tap_pts and BOT_IMG_NEWEST_AT == "top" and len(tap_pts) >= 2:
        tap_pts = list(reversed(tap_pts[:count]))

    if tap_pts and is_clicker_serial(serial) and IMG_TRUST_CLICK:
        for i, (tx, ty) in enumerate(tap_pts[:count]):
            clicker_tap_pinned(serial, tx, ty, f"gallery_check_{i + 1}")
            clicker_w(0.14, 0.22)
        log.info("发图勾选信任 %d 张 @ 钉死", count)
        return count

    if tap_pts and is_clicker_serial(serial):
        picked = 0
        prev_sel = _gallery_selected_count(root)
        for i, (tx, ty) in enumerate(tap_pts[:count]):
            need = i + 1
            ok = clicker_tap_until_verify(
                serial, tx, ty,
                verify=lambda s, n=need, base=prev_sel: (
                    _verify_gallery_selected_at_least(s, n)
                    or _gallery_selected_count(ui_hierarchy(s, force=True)) > base
                ),
                label=f"gallery_check_{need}",
                fast_wait=0.14,
                slow_wait=0.22,
                recover_on_fail=False,
            )
            if ok:
                log.info("发图勾选%d @ (%d,%d) pinned=%s", need, tx, ty, tap_pts is pinned_pts)
                picked += 1
                prev_sel = max(prev_sel, need)
            else:
                log.warning("勾选%d 未确认 @ (%d,%d)", need, tx, ty)
        if picked >= count:
            return picked
        log.warning("读屏/钉死勾选 %d/%d，尝试 u2 网格兜底", picked, count)
        if picked > 0:
            return picked

    if is_clicker_serial(serial) and CLICKER_IMG_TAP_ONLY and not dynamic_pts:
        return 0

    dev = _get_u2_device(serial)
    if not dev:
        return 0
    clicker_w(0.12, 0.15) if is_clicker_serial(serial) else w(0.45, 0.15)
    points = _checkbox_tap_points(dev, serial, count)
    if not points:
        log.info("勾选 UI 枚举失败，使用网格角点兜底 newest_at=%s", BOT_IMG_NEWEST_AT)
        try:
            out = adb_run(serial, "shell", "wm", "size").strip()
            m = re.search(r"(\d+)x(\d+)", out)
            sw = int(m.group(1)) if m else 720
        except Exception:
            sw = 720
        cell_w = max(200, sw // 3)
        for i in range(count):
            cx, cy = _gallery_coord_for_index(serial, i)
            tx = max(14, cx - cell_w // 2 + min(22, int(cell_w * 0.1)))
            ty = max(160, cy - 58)
            points.append((tx, ty))
    if not points:
        log.warning("未找到可勾选缩略图格 newest_at=%s", BOT_IMG_NEWEST_AT)
        return 0
    picked = 0
    for tx, ty in points[:count]:
        adb_tap_raw(serial, tx, ty)
        log.info("发图勾选角点 (%d,%d) newest_at=%s", tx, ty, BOT_IMG_NEWEST_AT)
        picked += 1
        w(0.4, 0.12)
        _close_image_preview_if_open(serial)
    return picked


def _select_bottom_images_checkboxes(serial: str, count: int) -> int:
    """兼容旧名。"""
    return _select_gallery_image_checkboxes(serial, count)


def _tap_image_batch_send(
    serial: str,
    send_xy: tuple[int, int] | None,
) -> bool:
    """多图勾选后点右下蓝钮 3/9→ 发送（W49 截图；钉死优先）。"""
    if IMG_PINNED and is_clicker_serial(serial):
        pt = pinned_xy("clicker", "gallery_batch_send")
        if pt:
            if IMG_TRUST_CLICK:
                clicker_tap_pinned(serial, pt[0], pt[1], "gallery_batch_send")
                log.info("发图钉死发送(信任) @ (%d,%d)", pt[0], pt[1])
                return True
            candidates: list[tuple[int, int]] = []
            for cand in (pt, (660, 1235), (635, 1235), (626, 1235)):
                if cand not in candidates:
                    candidates.append(cand)
            if CLICK_VERIFY:
                for idx, (sx, sy) in enumerate(candidates, start=1):
                    invalidate_step_verify_cache(serial)
                    ok = clicker_tap_until_verify(
                        serial, sx, sy,
                        verify=_verify_gallery_send_tapped,
                        label=f"gallery_batch_send_{idx}",
                        max_tries=1,
                        fast_wait=0.35,
                        slow_wait=0.55,
                        recover_on_fail=False,
                    )
                    if ok:
                        log.info("发图钉死发送(已验证) @ (%d,%d)", sx, sy)
                        return True
                    log.warning("发图钉死发送候选未确认 @ (%d,%d)", sx, sy)
                    clicker_w(0.25, 0.30)
                return False
            sx, sy = candidates[0]
            clicker_tap_pinned(serial, sx, sy, "gallery_batch_send")
            log.info("发图钉死发送 @ (%d,%d)", sx, sy)
            return True

    dev = _get_u2_device(serial)
    if dev:
        for label in ("发送", "完成", "确定", "Send"):
            try:
                node = dev(text=label)
                if node.exists(timeout=1.5):
                    node.click()
                    log.info("发图批量确认 [%s]", label)
                    return True
            except Exception:
                continue
        try:
            sh = dev.window_size()[1]
            sw = dev.window_size()[0]
            # 左下角箭头区域
            candidates: list[tuple[int, int, int]] = []
            for node in dev(clickable=True):
                b = _u2_bounds_dict(node)
                if not b:
                    continue
                x1, y1, x2, y2 = b
                if y1 > sh * 0.78 and x2 < sw * 0.45:
                    candidates.append((y2, (x1 + x2) // 2, (y1 + y2) // 2))
            if candidates:
                candidates.sort(reverse=True)
                _, tx, ty = candidates[0]
                adb_tap_raw(serial, tx, ty)
                log.info("发图点左下箭头 (%d,%d)", tx, ty)
                return True
        except Exception:
            pass
    if send_xy:
        adb_tap_raw(serial, send_xy[0], send_xy[1])
        return True
    try:
        out = adb_run(serial, "shell", "wm", "size").strip()
        m = re.search(r"(\d+)x(\d+)", out)
        if m:
            sw, sh = int(m.group(1)), int(m.group(2))
            adb_tap_raw(serial, int(sw * 0.12), int(sh * 0.93))
            return True
    except Exception:
        pass
    return False


def _verify_chat_send(fp_before: str, texts_before: list[str], serial: str) -> bool:
    snap1 = ui_snapshot(serial, chat=False)
    fp_after = _screencap_bottom_fingerprint(serial)
    if fp_before and fp_after and fp_before != fp_after:
        return True
    if texts_before != snap1.texts:
        return True
    return chat_bottom_roi_changed(serial)


def send_chat_images_batch(
    serial: str,
    bot: dict,
    image_paths: list[str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    settings: dict[str, str] | None = None,
    *,
    group_ok: bool = False,
    settle_rid: int = 0,
    gallery_preloaded: bool = False,
) -> bool:
    """结算发图：优先 55M 内复制粘贴，失败回退 +→图片→勾选。"""
    paths = [p for p in image_paths if p and os.path.isfile(p)]
    if not paths:
        return False
    if block_clicker_send(serial, bot, paths[0], where="send-image-batch"):
        return False
    if not group_ok and not ensure_group_for_send(serial, bot):
        log.warning("不在目标群，取消批量发图")
        return False

    mode = BOT_IMG_SEND_MODE
    if is_clicker_serial(serial) and IMG_PINNED and CLICKER_IMG_TAP_ONLY:
        mode = "ui"
    if is_listener_send_only_serial(serial) or is_send_only_listener(bot):
        mode = "ui"

    log.info(
        "发图 %d 张 mode=%s: %s",
        len(paths), mode, ", ".join(os.path.basename(p) for p in paths),
    )

    if mode in ("auto", "in_app_copy", "copy"):
        if not _push_images_to_gallery(serial, paths):
            return False
        w(1.0, 0.3)
        copy_ok = True
        for k, p in enumerate(paths):
            thumb_idx = k if BOT_IMG_NEWEST_AT == "top" else len(paths) - 1 - k
            if not send_chat_image_in_app_copy(
                serial, bot, p, input_xy, send_xy, settings,
                group_ok=True,
                thumb_index_from_bottom=thumb_idx,
                gallery_preloaded=True,
            ):
                copy_ok = False
                break
            w(0.25, 0.08)
        if copy_ok:
            return True
        if mode in ("in_app_copy", "copy"):
            post_log("[ADB] 应用内复制发图失败", "WARNING")
            return False
        log.info("应用内复制发图未全成功，回退 UI 批量发图")
        _dismiss_image_picker(serial)
        w(0.35, 0.12)
        return _send_chat_images_ui_batch(
            serial, bot, paths, input_xy, send_xy, settings,
            group_ok=True, gallery_preloaded=True, settle_rid=settle_rid,
        )

    if mode == "paste":
        paste_ok = True
        for p in paths:
            if not send_chat_image_paste(
                serial, bot, p, input_xy, send_xy, settings, group_ok=True,
            ):
                paste_ok = False
                break
            w(0.35, 0.12)
        if paste_ok:
            return True
        log.info("外部剪贴板粘贴失败（55M 不联通），回退 UI 批量发图")

    return _send_chat_images_ui_batch(
        serial, bot, paths, input_xy, send_xy, settings,
        group_ok=True, gallery_preloaded=gallery_preloaded, settle_rid=settle_rid,
    )


def send_chat_image(
    serial: str,
    bot: dict,
    image_path: str,
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    settings: dict[str, str] | None = None,
    *,
    group_ok: bool = False,
) -> bool:
    """单张发图（走与批量相同：+ → 图片 → 勾选 → 发送）。"""
    return send_chat_images_batch(
        serial, bot, [image_path], input_xy, send_xy, settings, group_ok=group_ok,
    )


def send_chat_reply(
    serial: str,
    bot: dict,
    text: str,
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    settings: dict[str, str] | None = None,
    *,
    group_ok: bool = False,
    skip_fast: bool = False,
    kind: str = "",
) -> bool:
    if block_clicker_send(serial, bot, text, where="send", kind=kind):
        return False
    announce_kind = kind in ("warn", "close", "open", "open_after_settle")
    if clicker_announce_enabled() and announce_kind and (is_clicker_bot(bot) or is_clicker_serial(serial, bot)):
        if not group_ok and not ensure_clicker_in_group(serial, bot, reason=f"send-{kind or 'announce'}"):
            log.warning("左机公告发送前未在群 kind=%s", kind or "?")
            return False
        snap_ann = ui_snapshot(serial, chat=True, channel="clicker-img")
        ix = input_xy or snap_ann.input_xy
        sy = send_xy or snap_ann.inbar_send or snap_ann.keyboard_send
        if not skip_fast and send_chat_reply_fast_u2(
            serial, text, snap_ann.texts, snap_ann.draft or "",
        ):
            log.info("左机公告发送成功 [fast-u2] kind=%s: %s", kind, message_snip(text)[:40])
            return True
        if fill_input_box(serial, ix[0], ix[1], for_adb_send(text))[2]:
            if sy:
                adb_tap(serial, sy[0], sy[1])
                log.info("左机公告发送成功 [tap] kind=%s: %s", kind, message_snip(text)[:40])
                return True
        log.warning("左机公告发送失败 kind=%s: %s", kind, message_snip(text)[:40])
        return False
    if not group_ok and not ensure_group_for_send(serial, bot):
        log.warning("不在目标群，取消发送: %s", message_snip(text)[:40])
        post_log(f"[ADB] 发送取消：未在目标群 {bot.get('associatedGroup')}", "WARNING")
        return False
    now = time.time()
    debounce = 0.0 if (LISTENER_TRUST_SEND and LISTENER_PURE_PIPE and not skip_fast) else SEND_DEBOUNCE_SEC
    if debounce and now - _SENDING.get(serial, 0) < debounce:
        log.warning("发送锁：跳过重复 send_chat_reply")
        return False
    _SENDING[serial] = now

    if not skip_fast and LISTENER_FAST_SEND and is_listener_send_only_serial(serial, bot):
        coords = SendCoords.from_settings(settings or {})
        fx, fy = input_xy or DEFAULT_CHAT_INPUT
        inbar_pt = send_xy or coords.inbar
        mode = "adb_b64" if LISTENER_SEND_TAP_ONLY else LISTENER_SEND_MODE
        if mode in ("auto", "adb_b64"):
            return send_chat_reply_fast_adb_listener(
                serial, bot, text, (fx, fy), inbar_pt, settings,
                texts_before=[], draft_before="",
            )
        outgoing_chk = for_adb_send(text).strip()
        snap0 = ui_snapshot(serial, chat=False) if not LISTENER_TRUST_SEND else None
        texts_before = (snap0.texts if snap0 else [])
        draft_before = (snap0.draft or "" if snap0 else "")
        if mode in ("auto", "u2"):
            if send_chat_reply_fast_u2(serial, text, texts_before, draft_before):
                return True
        if snap0 is None:
            snap0 = ui_snapshot(serial, chat=False)
            texts_before = snap0.texts
            draft_before = snap0.draft or ""
        snap_chk = ui_snapshot(serial, chat=False)
        if draft_cleared_after_fill(draft_before, snap_chk.draft or "", outgoing_chk):
            log.info("发送完成 [fast-draft-clear]: %s", message_snip(outgoing_chk)[:40])
            return True
        if mode == "adb_b64":
            if LISTENER_TRUST_SEND:
                log.info("发送完成 [adb_b64+trust-fallback]: %s", message_snip(outgoing_chk)[:40])
                return True
            if send_chat_reply_fast_u2(serial, text, texts_before, draft_before):
                return True
            log.error("发送失败 [adb_b64+u2]: %s", message_snip(text)[:40])
            return False

    snap0 = ui_snapshot(serial, chat=False)
    texts_before = snap0.texts
    draft_before = snap0.draft
    if (
        not skip_fast
        and LISTENER_SEND_MODE in ("auto", "u2")
        and FAST
        and send_chat_reply_fast_u2(serial, text, texts_before, draft_before)
    ):
        invalidate_roi_cache(serial)
        return True
    if FAST and not is_listener_send_only_serial(serial, bot) and send_chat_reply_fast_u2(
        serial, text, texts_before, draft_before,
    ):
        return True

    coords = SendCoords.from_settings(settings or {})
    x, y = resolve_chat_input_xy(snap0, settings, bot)

    variants: list[str] = []
    for v in (for_adb_send(text), text.strip(), adb_safe_text(text)):
        if v and v not in variants:
            variants.append(v)

    for variant in variants:
        _, outgoing, ok = fill_input_box(serial, x, y, variant)
        min_len = 2 if any(ord(c) > 127 for c in variant) else 4
        if not ok or len(outgoing) < min_len:
            continue

        snap = ui_snapshot(serial)
        fx, fy = resolve_chat_input_xy(snap, settings, bot)
        log.info("待发 @(%d,%d): %s", fx, fy, outgoing[:70].replace("\n", " | "))

        bounds = effective_input_bounds(snap, settings, bot)
        patched = UiSnapshot(
            snap.texts, (fx, fy), bounds, snap.draft, snap.inbar_send, snap.keyboard_send,
            snap.chat_nodes, snap.root,
        )
        strategies = collect_send_strategies(patched, coords)

        for attempt in range(1 if FAST else 2):
            if execute_send_round(
                serial, (fx, fy), strategies, outgoing,
                texts_before, snap.draft or draft_before,
            ):
                final = ui_snapshot(serial)
                if not draft_is_empty(final.draft) and _draft_has(final.draft, outgoing):
                    log.warning("假成功：消息仍在输入框，继续重试")
                else:
                    log.info("发送成功: %s", message_snip(outgoing)[:40])
                    return True
            log.warning("发送未成功(第%d轮)，重新填字", attempt + 1)
            fill_input_box(serial, fx, fy, outgoing)
            snap = ui_snapshot(serial)
            fx, fy = resolve_chat_input_xy(snap, settings, bot)

    log.error("发送失败: %s", message_snip(text)[:60])
    return False


def chat_partner(texts: list[str], users: list[dict], bot_id: str, bot: dict | None = None) -> str:
    """返回最近可见的已登记昵称（优先聊天区下方、左侧消息）。"""
    pool = nickname_pool(users, bot_id)
    for t in texts:
        ts = t.strip()
        if ts in pool and len(pool[ts]) == 1:
            return ts
    return ""


def handle_bind(code: str, bot: dict, nickname: str, serial: str | None = None) -> str:
    nick = (nickname or "").strip()
    if not nick:
        return user_reply(nick or "?", "绑定失败", "无法识别发送者")
    try:
        users = api("GET", "/api/users")
        if not isinstance(users, list):
            return user_reply(nick, "绑定失败", "系统错误")
    except Exception as ex:
        log.warning("绑定拉取用户失败: %s", ex)
        return user_reply(nick, "绑定失败", "系统错误")

    target = find_user_by_code(users, bot["id"], code)
    if not target:
        return user_reply(nick, "绑定失败", f"编号 {code} 不存在")

    mid = read_messenger_id_for_nick(serial, nick) if serial else None
    if not mid:
        return user_reply(nick, "绑定失败", "无法读取 55M ID", "请确保已是好友并在控制面板填写 ID")

    target["messengerId"] = mid
    old_name = str(target.get("username") or "").strip()
    aliases = parse_aliases(target)
    if old_name and old_name != nick and old_name not in aliases:
        aliases.append(old_name)
    aliases = [a for a in aliases if a and a != nick]
    target["username"] = nick
    target["nickAliases"] = json.dumps(aliases, ensure_ascii=False)
    target["lastActive"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not commit_user(target):
        return user_reply(nick, "绑定失败", "保存错误")

    cc = str(target.get("customerCode") or "").replace("UID-", "")
    return user_reply(
        nick, "绑定成功", f"编号：{cc}", f"ID：{mid}", f"余额：{float(target.get('balance', 0)):.3f}",
    )


def panel_user_fast(
    bot_id: str,
    display_nick: str,
    users: list[dict] | None,
) -> dict | None:
    """已废弃：仅保留兼容入口，内部走 resolve_panel_user（禁止纯昵称猜测）。"""
    return resolve_panel_user(bot_id, display_nick, users, serial=None, allow_profile_read=False)


def resolve_panel_user(
    bot_id: str,
    display_nick: str,
    users: list[dict] | None,
    serial: str | None = None,
    *,
    allow_profile_read: bool = True,
    bot: dict | None = None,
) -> dict | None:
    """以 55M messengerId 为唯一键认人；昵称仅用于显示与点头像定位。"""
    nick = (display_nick or "").strip()
    if not nick or not is_plausible_sender(nick):
        log.info("无效昵称，跳过认人: %r", nick)
        return None
    try:
        if users is None:
            users = api("GET", "/api/users")
        if not isinstance(users, list):
            return None
    except Exception as ex:
        log.warning("拉取面板用户失败: %s", ex)
        return None

    mid: str | None = None
    if serial:
        mid = mid_cache_get(serial, nick, users, bot_id)
    if not mid and bot_id:
        mid = _global_mid_cache_get(bot_id, nick)
        if mid and not _validate_cached_mid(mid, nick, users, bot_id):
            mid = None

    row = panel_user_by_nick(users, bot_id, nick)
    if not mid and row:
        pm = normalize_messenger_id(str(row.get("messengerId") or ""))
        if pm:
            mid = pm
            if serial:
                store_mid_cache(serial, nick, mid, bot_id)
            elif bot_id:
                store_mid_cache("global", nick, mid, bot_id)

    if not mid and allow_profile_read and serial:
        if bot and is_send_only_listener(bot):
            log.debug("右机不点头像，等待 Clicker 缓存 ID: %s", nick)
        else:
            mid = read_messenger_id_for_nick(serial, nick, users, bot_id, bot=bot)

    if not mid:
        log.info("认人失败 nick=%s（无 ID 缓存且未读资料页）", nick)
        return None

    u = find_user_by_messenger_id(users, bot_id, mid)
    if u:
        log.info("认人成功 nick=%s mid=%s code=%s", nick, mid, u.get("customerCode"))
        return update_display_name(dict(u), nick)
    log.info("ID %s 未在面板登记 (nick=%s)", mid, nick)
    return None


def panel_user(
    bot_id: str,
    display_nick: str,
    serial: str | None = None,
    users: list[dict] | None = None,
) -> dict | None:
    """强制以 messengerId 认人（Clicker / 单机可用 profile 读取）。"""
    return resolve_panel_user(
        bot_id, display_nick, users, serial, allow_profile_read=bool(serial), bot=None,
    )


def command_needs_identity(cmd: str) -> bool:
    c = (cmd or "").strip()
    if not c:
        return False
    if ADD_FINANCE_RE.match(c) or BIND_RE.match(c):
        return False
    return bool(
        BALANCE_RE.match(c)
        or CANCEL_RE.match(c)
        or QUERY_ROUND_BETS_RE.match(c)
        or QUERY_FLOW_RE.match(c)
        or QUERY_HISTORY_RE.match(c)
        or REBATE_RE.match(c)
        or WITHDRAW_RE.match(c)
        or TOPUP_RE.match(c)
        or parse_any_bet(c)
        or looks_like_bet_attempt(c)
    )


def commit_user(user: dict) -> dict | None:
    """写回用户到控制面板（不触发群内回复）。"""
    try:
        api("POST", "/api/users", user)
        return user
    except Exception as ex:
        log.warning("写回面板用户失败: %s", ex)
        return None


def handle_command(
    msg: str,
    bot: dict,
    users: list[dict],
    products: list[dict],
    combo_rules: list[dict],
    settings: dict[str, str],
    hint: str,
    serial: str | None = None,
    cache_serial: str | None = None,
) -> str | None:
    cmd = msg.strip()
    display = (hint or "").strip()

    bind = BIND_RE.match(cmd)
    if bind:
        return handle_bind(bind.group(1), bot, hint, serial)

    lookup_serial = cache_serial or serial
    if serial:
        user = resolve_panel_user(
            bot["id"], hint, users, lookup_serial,
            allow_profile_read=True, bot=bot,
        )
    else:
        user = resolve_panel_user(
            bot["id"], hint, users, lookup_serial,
            allow_profile_read=False,
        )
    if not user:
        if needs_registration_reply(cmd):
            return user_reply(display or "?", UNREGISTERED_REPLY)
        return None

    username = reply_display_name(display, user)
    cc = str(user.get("customerCode") or "")
    customer_code = cc.replace("UID-", "")
    rid = current_round_id(settings)

    if BALANCE_RE.match(cmd):
        bal = float(user["balance"])
        return user_reply(
            username,
            f"积分：{int(bal)}",
            "冻结：0",
            f"余额：{int(bal)}",
            f"编号：{customer_code}",
        )

    if CANCEL_RE.match(cmd):
        pk = pending_key(bot["id"], user)
        pending = _PENDING.pop(pk, None)
        if not pending:
            return round_user_reply(rid, username, "取消失败", "暂无待取消订单")
        refund = float(pending.get("amount", 0))
        rid = int(pending.get("round_id") or rid)
        user = resolve_panel_user(
            bot["id"], hint, users, lookup_serial,
            allow_profile_read=bool(serial), bot=bot if serial else None,
        ) or user
        user["balance"] = float(user["balance"]) + refund
        user["lastActive"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_user(user)
        record_bill(bot["id"], username, "取消返还", refund, float(user["balance"]), str(pending.get("cmd") or ""), cc)
        stake_pk = f"{bot['id']}:{user.get('customerCode') or user.get('username')}:{rid}"
        _ROUND_STAKES[stake_pk] = max(0.0, _ROUND_STAKES.get(stake_pk, 0.0) - refund)
        bets = _ROUND_BETS.get(pk, [])
        if bets and bets[-1].get("cmd") == pending.get("cmd"):
            bets.pop()
        return round_user_reply(rid, username, "取消成功", f"返回积分：{refund:.0f}")

    if QUERY_ROUND_BETS_RE.match(cmd):
        return format_round_bets_reply(user, bot["id"], settings, username)

    if QUERY_FLOW_RE.match(cmd):
        return format_flow_reply(bot["id"], username)

    if QUERY_HISTORY_RE.match(cmd):
        return format_history_reply(username)

    if REBATE_RE.match(cmd):
        return user_reply(username, "反水申请已提交", "请联系群主核实流水后发放")

    withdraw = WITHDRAW_RE.match(cmd)
    if withdraw:
        amount = float(withdraw.group(1))
        try:
            pending_list = api(
                "GET",
                f"/api/withdraw-requests?status=pending&botId={bot['id']}",
            )
            if isinstance(pending_list, list) and any(
                r.get("username") == username for r in pending_list
            ):
                return finance_pending_reply("withdraw", username, amount, settings)
            api(
                "POST",
                "/api/withdraw-requests",
                {"botId": bot["id"], "username": username, "amount": amount},
            )
        except Exception as ex:
            log.warning("下分请求 API 失败: %s", ex)
        return finance_pending_reply("withdraw", username, amount, settings)

    topup = TOPUP_RE.match(cmd)
    if topup:
        amount = float(topup.group(1))
        try:
            pending_list = api(
                "GET",
                f"/api/topup-requests?status=pending&botId={bot['id']}",
            )
            if isinstance(pending_list, list) and any(
                r.get("username") == username for r in pending_list
            ):
                return finance_pending_reply("topup", username, amount, settings)
            api(
                "POST",
                "/api/topup-requests",
                {"botId": bot["id"], "username": username, "amount": amount},
            )
        except Exception as ex:
            log.warning("上分请求 API 失败: %s", ex)
        return finance_pending_reply("topup", username, amount, settings)

    if not PURCHASE_RULES_ENABLED:
        return None

    if maintenance_blocks_bet() and parse_any_bet(cmd):
        return user_reply(username, MAINTENANCE_MSG)

    bet = parse_any_bet(cmd)
    if bet:
        user = resolve_panel_user(
            bot["id"], hint, users, lookup_serial,
            allow_profile_read=bool(serial), bot=bot if serial else None,
        ) or user
        return execute_bet_order(bet, user, bot, username, cc, settings)

    if looks_like_bet_attempt(cmd):
        return round_user_reply(rid, username, BET_FORMAT_MSG)

    return None


def _log_worker_loop() -> None:
    while True:
        try:
            msg, typ = _LOG_QUEUE.get()
            api("POST", "/api/logs", {
                "id": f"d-{int(time.time() * 1000)}",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "type": typ,
                "message": msg,
            })
        except Exception:
            pass


@dataclass
class OutboundSend:
    serial: str
    bot: dict
    text: str
    settings: dict[str, str]
    input_xy: tuple[int, int] | None = None
    send_xy: tuple[int, int] | None = None
    group_ok: bool = False
    prio: int = SEND_PRIO_CMD
    kind: str = ""
    round_id: int = 0
    image_path: str = ""
    image_paths: list[str] = field(default_factory=list)
    gallery_preloaded: bool = False


_OPEN_AFTER_CAPTURE_PENDING: dict[int, OutboundSend] = {}
_OPEN_AFTER_CAPTURE_LOCK = threading.Lock()
_CLICKER_SETTLE_OPEN_BY_RID: dict[int, dict] = {}
_CLICKER_SETTLE_OPEN_LOCK = threading.Lock()


def settle_announce_chain_busy(serial: str = "") -> bool:
    """结算三图链未完成或待发「三图后新一局」时，禁止封盘提醒/封盘公告抢跑。"""
    with _OPEN_AFTER_CAPTURE_LOCK:
        if _OPEN_AFTER_CAPTURE_PENDING:
            return True
    with _CLICKER_SETTLE_OPEN_LOCK:
        if _CLICKER_SETTLE_OPEN_BY_RID:
            return True
    try:
        from bot_ops.capture_ipc import clicker_capture_queue_busy, has_pending_captures

        if has_pending_captures() or clicker_capture_queue_busy():
            return True
    except Exception:
        pass
    if serial:
        return outbound_for(serial).has_post_settle_open()
    with _OUTBOUND_REGISTRY_LOCK:
        return any(q.has_post_settle_open() for q in _OUTBOUND_BY_SERIAL.values())


def stash_open_after_capture(settled_rid: int, job: OutboundSend) -> None:
    """左机三图出队后再发右机「新的一局」（固定顺序 §2 ③）。"""
    with _OPEN_AFTER_CAPTURE_LOCK:
        _OPEN_AFTER_CAPTURE_PENDING[settled_rid] = job
        _OPEN_AFTER_CAPTURE_TS[settled_rid] = time.time()


def process_stale_open_after_capture() -> None:
    """结算图超时降级（默认关闭，须 BOT_OPEN_FALLBACK_SEC>0）。"""
    if OPEN_AFTER_CAPTURE_FALLBACK_SEC <= 0:
        return
    now = time.time()
    with _OPEN_AFTER_CAPTURE_LOCK:
        pending = list(_OPEN_AFTER_CAPTURE_PENDING.items())
    for settled_rid, job in pending:
        age = now - _OPEN_AFTER_CAPTURE_TS.get(settled_rid, now)
        if age < OPEN_AFTER_CAPTURE_FALLBACK_SEC:
            continue
        if _any_clicker_img_flow_busy():
            continue
        with _OPEN_AFTER_CAPTURE_LOCK:
            if settled_rid not in _OPEN_AFTER_CAPTURE_PENDING:
                continue
            _OPEN_AFTER_CAPTURE_PENDING.pop(settled_rid, None)
            _OPEN_AFTER_CAPTURE_TS.pop(settled_rid, None)
        log.warning(
            "结算图超时 %.0fs rid=%s → 降级入队新的一局 rid=%s",
            age, settled_rid, job.round_id,
        )
        grp = (job.bot.get("associatedGroup") or "").strip()
        if _open_gate_satisfied(grp, job.round_id):
            log.info("结算超时降级跳过：open rid=%s 已上闸", job.round_id)
            continue
        outbound_enqueue(job)


def flush_open_after_capture(settled_rid: int, *, images_ok: bool) -> None:
    with _OPEN_AFTER_CAPTURE_LOCK:
        job = _OPEN_AFTER_CAPTURE_PENDING.pop(settled_rid, None)
        stale_age = time.time() - _OPEN_AFTER_CAPTURE_TS.pop(settled_rid, time.time())
    if not job:
        return
    if not images_ok:
        log.warning("结算图失败 rid=%s，不发新的一局（固定顺序 §2 ③）", settled_rid)
        if settled_rid in _CAPTURE_SUCCEEDED:
            log.info("rid=%s 已有成功截图，不再重入结算发图", settled_rid)
            return
        grp = (job.bot.get("associatedGroup") or "").strip()
        if _open_gate_satisfied(grp, job.round_id):
            log.info("结算降级跳过：open rid=%s 已上闸", job.round_id)
            return
        if OPEN_AFTER_CAPTURE_FALLBACK_SEC > 0 and stale_age >= OPEN_AFTER_CAPTURE_FALLBACK_SEC:
            if _any_clicker_img_flow_busy():
                with _OPEN_AFTER_CAPTURE_LOCK:
                    _OPEN_AFTER_CAPTURE_PENDING[settled_rid] = job
                    _OPEN_AFTER_CAPTURE_TS[settled_rid] = time.time() - stale_age
                log.info("左机发图中，延后降级新的一局 settled_rid=%s", settled_rid)
                return
            log.warning("结算图失败且超时 rid=%s → 降级入队新的一局", settled_rid)
            outbound_enqueue(job)
        return
    log.info(
        "结算图成功 rid=%s → 入队新的一局 rid=%s",
        settled_rid, job.round_id,
    )
    outbound_enqueue(job)


def _finish_capture_batch_settle(
    settled_rid: int,
    *,
    images_ok: bool,
    ipc_open_job: dict | None = None,
    announce_serial: str = "",
    announce_bot: dict | None = None,
) -> None:
    """结算三图结案：左机内模式 → capture-ipc done 通知右机 open；同进程 → stash。"""
    settle_open_raw: dict | None = None
    with _CLICKER_SETTLE_OPEN_LOCK:
        settle_open_raw = _CLICKER_SETTLE_OPEN_BY_RID.pop(settled_rid, None)
    open_payload = settle_open_raw or (ipc_open_job if ipc_open_job else None)
    if open_payload:
        from bot_ops.capture_ipc import mark_capture_done, dict_to_outbound

        mark_capture_done(settled_rid, images_ok=images_ok, open_job=open_payload)
        if images_ok and clicker_announce_enabled():
            cs = (announce_serial or "").strip()
            cb = announce_bot
            if not cs:
                cs, cb = resolve_open_announce_target()
            elif not cb:
                _, cb = resolve_open_announce_target()
            if cs:
                ojob = dict_to_outbound(open_payload, cb or {}, cs)
                outbound_enqueue(ojob)
                log.info(
                    "[clicker] 三图成功 → 直接入队新一局 rid=%s serial=%s",
                    ojob.round_id, cs,
                )
        return
    flush_open_after_capture(settled_rid, images_ok=images_ok)


class OutboundQueue:
    """右机优先级发送队列：用户指令优先，公告/结算靠后。"""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, OutboundSend]] = []
        self._seq = 0
        self._cv = threading.Condition()

    def put(self, job: OutboundSend) -> None:
        with self._cv:
            if job.kind in ("open", "open_after_settle") and job.round_id > 0:
                dropped = self._drop_stale_open_jobs(job.round_id)
                if dropped:
                    log.info(
                        "出站队列丢弃过期 open %d 条，保留 rid>=%s",
                        dropped, job.round_id,
                    )
            self._seq += 1
            heapq.heappush(self._heap, (job.prio, self._seq, job))
            self._cv.notify()

    def _drop_stale_open_jobs(self, keep_rid: int) -> int:
        if not self._heap:
            return 0
        kept: list[tuple[int, int, OutboundSend]] = []
        dropped = 0
        for item in self._heap:
            _prio, _seq, j = item
            if j.kind in ("open", "open_after_settle") and j.round_id > 0:
                grp = (j.bot.get("associatedGroup") or "").strip()
                announced = int(_ROUND_OPEN_ANNOUNCED.get(grp) or 0)
                if j.round_id <= announced or j.round_id < keep_rid - 1:
                    dropped += 1
                    if j.text.strip():
                        _release_outbound_dedup(j.serial, j.text)
                    continue
            kept.append(item)
        heapq.heapify(kept)
        self._heap = kept
        return dropped

    def get(self, timeout: float = 0.3) -> OutboundSend | None:
        with self._cv:
            if not self._heap:
                self._cv.wait(timeout)
            if self._heap:
                _prio, _seq, job = heapq.heappop(self._heap)
                return job
        return None

    def pending_user_jobs(self) -> int:
        with self._cv:
            return sum(1 for p, _, _ in self._heap if p <= SEND_PRIO_BRAIN)

    def pending_cmd_jobs(self) -> int:
        with self._cv:
            return sum(1 for p, _, _ in self._heap if p == SEND_PRIO_CMD)

    def pending_for_serial(self, serial: str) -> int:
        with self._cv:
            return sum(1 for _, _, j in self._heap if j.serial == serial)

    def pending_announce_text(self, serial: str) -> bool:
        """右机队列里是否还有未发的封盘/开局类文字公告。"""
        with self._cv:
            return any(
                j.serial == serial
                and not j.image_paths
                and not j.image_path
                and (
                    j.kind in ("warn", "close", "open", "open_after_settle")
                    or SEND_PRIO_WARN <= j.prio <= SEND_PRIO_OPEN_AFTER_SETTLE
                )
                for _, _, j in self._heap
            )

    def has_post_settle_open(self, *, serial: str = "") -> bool:
        with self._cv:
            return any(
                j.kind in ("open_after_settle", "open")
                and j.prio == SEND_PRIO_OPEN_AFTER_SETTLE
                and (not serial or j.serial == serial)
                for _, _, j in self._heap
            )

    def has_open_job(self, rid: int, *, serial: str = "") -> bool:
        with self._cv:
            return any(
                j.kind in ("open", "open_after_settle")
                and j.round_id == rid
                and (not serial or j.serial == serial)
                for _, _, j in self._heap
            )

    def has_kind_job(self, kind: str, rid: int, *, serial: str = "") -> bool:
        with self._cv:
            return any(
                j.kind == kind
                and j.round_id == rid
                and (not serial or j.serial == serial)
                for _, _, j in self._heap
            )


_OUTBOUND_BY_SERIAL: dict[str, OutboundQueue] = {}
_OUTBOUND_REGISTRY_LOCK = threading.Lock()


def _canonical_outbound_serial(serial: str) -> str:
    """同机 ADB 统一队列键（localhost:PORT 与 127.0.0.1:PORT 不再分裂）。"""
    port = _adb_port_from_serial(serial)
    if port and str(port).isdigit():
        return f"localhost:{port}"
    return (serial or "").strip()


def outbound_for(serial: str) -> OutboundQueue:
    """出站资源 2：按 serial 独立队列，sender/clicker-img 不再踢皮球。"""
    serial = _canonical_outbound_serial(serial)
    with _OUTBOUND_REGISTRY_LOCK:
        q = _OUTBOUND_BY_SERIAL.get(serial)
        if q is None:
            q = OutboundQueue()
            _OUTBOUND_BY_SERIAL[serial] = q
        return q


def outbound_enqueue(job: OutboundSend) -> None:
    outbound_for(job.serial).put(job)


def outbound_pending_cmd_jobs() -> int:
    with _OUTBOUND_REGISTRY_LOCK:
        return sum(q.pending_cmd_jobs() for q in _OUTBOUND_BY_SERIAL.values())


def outbound_pending_user_jobs(serial: str | None = None) -> int:
    with _OUTBOUND_REGISTRY_LOCK:
        if serial:
            q = _OUTBOUND_BY_SERIAL.get(serial)
            return q.pending_user_jobs() if q else 0
        return sum(q.pending_user_jobs() for q in _OUTBOUND_BY_SERIAL.values())


def outbound_pending_announce_text(serial: str) -> bool:
    return outbound_for(serial).pending_announce_text(serial)


def _outbound_dedup_key(serial: str, text: str) -> str:
    snip = re.sub(r"\s+", "", message_snip(text))[:48]
    return f"{serial}|{snip}"


def _release_outbound_dedup(serial: str, text: str) -> None:
    _OUTBOUND_TEXT_DEDUP.pop(_outbound_dedup_key(serial, text), None)


def _open_dispatch_blocked(group: str, rid: int, serial: str) -> bool:
    """防公告线程风暴；若已派发但队列无 job 且未上闸，允许重入队。"""
    key = (group, rid)
    if key not in _OPEN_DISPATCH_SENT:
        return False
    if outbound_for(serial).has_open_job(rid, serial=serial):
        return True
    if _LISTENER_SEND_LOCK.get(serial):
        return True
    _OPEN_DISPATCH_SENT.discard(key)
    return False


def _kind_dispatch_blocked(
    kind: str,
    group: str,
    rid: int,
    serial: str,
    sent: set[tuple[str, int]],
) -> bool:
    key = (group, rid)
    if key not in sent:
        return False
    if outbound_for(serial).has_kind_job(kind, rid, serial=serial):
        return True
    if _LISTENER_SEND_LOCK.get(serial):
        return True
    sent.discard(key)
    return False


def _announce_in_fail_cooldown(kind: str, group: str, rid: int) -> bool:
    return time.time() < _ANNOUNCE_FAIL_UNTIL.get((kind, group, rid), 0.0)


def _mark_announce_fail_cooldown(kind: str, group: str, rid: int) -> None:
    _ANNOUNCE_FAIL_UNTIL[(kind, group, rid)] = time.time() + ANNOUNCE_FAIL_COOLDOWN_SEC


def open_send_prio(group: str, rid: int) -> int:
    """积压 open 优先于 warn，避免封盘提醒饿死新的一局。"""
    announced = int(_ROUND_OPEN_ANNOUNCED.get(group) or 0)
    if rid > announced:
        return SEND_PRIO_OPEN_CATCHUP
    return SEND_PRIO_OPEN


def _announce_job_redundant(job: OutboundSend) -> bool:
    """队列里重复的 warn/close/open（已成功发过同一 rid）。"""
    group = (job.bot.get("associatedGroup") or "").strip()
    rid = job.round_id
    if not group or not rid or not job.kind:
        return False
    if job.kind == "warn" and _WARN_ANNOUNCED_ROUND.get(group) == rid:
        return True
    if job.kind == "close" and _CLOSE_ANNOUNCED_ROUND.get(group) == rid:
        return True
    if job.kind == "open" and _ROUND_OPEN_ANNOUNCED.get(group) == rid:
        return True
    if job.kind == "open_after_settle" and _ROUND_OPEN_ANNOUNCED.get(group) == rid:
        return True
    return False


def poll_edge_brain_open_dispatch(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
) -> None:
    """124 架构：左机 JS settle-done → edge_brain 门闸 → 右机 LISTENER 发 open。"""
    if not EDGE_LEFT_JS or not is_send_only_listener(bot):
        return
    try:
        req = urllib.request.Request(
            f"{EDGE_BRAIN_URL}/edge/open-job",
            headers=edge_brain_auth_headers(),
        )
        with urllib.request.urlopen(req, timeout=0.35) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        log.debug("edge_brain open-job: %s", ex)
        return
    gates = body.get("gates") or {}
    if not gates.get("open"):
        return
    open_rid = int(gates.get("open_rid") or 0)
    open_text = str(body.get("open_text") or "").strip()
    if open_rid <= 0 or not open_text:
        return
    group = (bot.get("associatedGroup") or "").strip()
    if _ROUND_OPEN_ANNOUNCED.get(group) == open_rid:
        return
    if _open_dispatch_blocked(group, open_rid, serial):
        return
    if dispatch_send(
        serial, bot, open_text, settings,
        input_xy=input_xy, send_xy=send_xy,
        prio=SEND_PRIO_OPEN_AFTER_SETTLE, kind="open_after_settle",
        round_id=open_rid, group_ok=True,
    ):
        _OPEN_DISPATCH_SENT.add((group, open_rid))
        log.info("[edge_brain] 三图后门闸 open rid=%s", open_rid)


def drain_capture_ipc_open_jobs(serial: str, bot: dict) -> None:
    """消费左机 capture-ipc done → 入队「三图后新一局」。须在群检测前调用。"""
    if EDGE_LEFT_JS:
        return
    try:
        from bot_ops.capture_ipc import dict_to_outbound, poll_capture_done

        items = poll_capture_done()
        if items:
            log.info("[capture-ipc] drain serial=%s n=%d", serial, len(items))
        for done in items:
            settled_rid = int(done.get("settled_rid") or 0)
            open_raw = done.get("open_job") or {}
            if done.get("images_ok") and open_raw:
                ojob = dict_to_outbound(open_raw, bot, serial)
                outbound_enqueue(ojob)
                log.info(
                    "[capture-ipc] 左机图成功 → 入队三图后新一局 rid=%s (settled=%s)",
                    ojob.round_id, settled_rid,
                )
            elif settled_rid:
                log.warning(
                    "[capture-ipc] 左机图未成功 settled_rid=%s，不发新一局（§2 ③）",
                    settled_rid,
                )
    except Exception:
        log.exception("[capture-ipc] 处理 done 失败")


def dispatch_send(
    serial: str,
    bot: dict,
    text: str,
    settings: dict[str, str],
    *,
    input_xy: tuple[int, int] | None = None,
    send_xy: tuple[int, int] | None = None,
    group_ok: bool = False,
    prio: int = SEND_PRIO_CMD,
    kind: str = "",
    round_id: int = 0,
) -> bool:
    """统一发送入口：Listener 入优先级队列，其它同步发送。"""
    if not text.strip():
        return False
    if block_clicker_send(serial, bot, text, where="dispatch", kind=kind):
        return False
    snip = re.sub(r"\s+", "", message_snip(text))[:48]
    out_key = _outbound_dedup_key(serial, text)
    now = time.time()
    announce_dedup = kind in ("warn", "close", "open", "open_after_settle") and round_id > 0
    dedup_sec = 2.0 if announce_dedup else OUTBOUND_DEDUP_SEC
    if snip and now - _OUTBOUND_TEXT_DEDUP.get(out_key, 0) < dedup_sec:
        log.info("跳过重复出站 [%s]: %s", serial, snip[:32])
        return False
    if snip:
        _OUTBOUND_TEXT_DEDUP[out_key] = now
    if outbound_uses_queue(bot):
        outbound_enqueue(
            OutboundSend(
                serial, bot, text, settings,
                input_xy, send_xy, group_ok,
                prio=prio, kind=kind, round_id=round_id,
            )
        )
        return True
    return send_chat_reply(
        serial, bot, text, input_xy, send_xy, settings,
        group_ok=group_ok, skip_fast=True, kind=kind,
    )


def enqueue_send(
    serial: str,
    bot: dict,
    text: str,
    settings: dict[str, str],
    *,
    input_xy: tuple[int, int] | None = None,
    send_xy: tuple[int, int] | None = None,
    group_ok: bool = False,
    prio: int = SEND_PRIO_CMD,
) -> None:
    dispatch_send(
        serial, bot, text, settings,
        input_xy=input_xy, send_xy=send_xy, group_ok=group_ok, prio=prio,
    )


def current_round_open_gate(group: str, rid: int) -> bool:
    """§2：当期「新的一局」已发出后，才允许封盘提醒/封盘公告。"""
    return bool(group) and rid > 0 and _ROUND_OPEN_ANNOUNCED.get(group) == rid


def process_round_warn_announce(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
) -> None:
    """结束前 WARN_ANNOUNCE_BEFORE_SEC 秒发「距离封盘还有60秒」（每群每期一次）。"""
    if not WARN_ANNOUNCE_ENABLED:
        return
    if not runs_announce_loop(bot):
        return
    if in_maintenance_window():
        return
    if settle_announce_chain_busy(serial):
        return
    group = (bot.get("associatedGroup") or "").strip()
    if not group:
        return
    rid, _interval, remaining = active_round_timing(settings)
    # 剩余 (CLOSE, WARN] 秒内发封盘提醒（默认封盘前70秒～15秒之间）
    if remaining > WARN_ANNOUNCE_BEFORE_SEC or remaining <= CLOSE_ANNOUNCE_BEFORE_SEC:
        return
    if _WARN_ANNOUNCED_ROUND.get(group) == rid:
        return
    if _announce_in_fail_cooldown("warn", group, rid):
        return
    if not current_round_open_gate(group, rid):
        return
    tpl = sanitize_announce_text((settings.get("warnAnnounceTemplate") or DEFAULT_WARN_ANNOUNCE).strip())
    if not tpl:
        return
    text = apply_template(tpl, round_id=rid, seconds_left=int(remaining))
    if _announce_already_visible(serial, bot, text):
        _WARN_ANNOUNCED_ROUND[group] = rid
        log.info("封盘提醒已在群 rid=%s，跳过重复发送", rid)
        return
    log.info(
        "封盘提醒 rid=%s 剩余%.0fs 群=%s",
        rid, remaining, group,
    )
    if _kind_dispatch_blocked("warn", group, rid, serial, _WARN_DISPATCH_SENT):
        return
    if not dispatch_send(
        serial, bot, text, settings,
        input_xy=input_xy, send_xy=send_xy,
        prio=SEND_PRIO_WARN, kind="warn", round_id=rid, group_ok=True,
    ):
        log.warning("封盘提醒入队失败 rid=%s", rid)
        return
    _WARN_DISPATCH_SENT.add((group, rid))
    post_log(f"[ADB] 封盘提醒 rid={rid} 剩余{int(remaining)}s", "INFO")


def process_round_close_announce(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
) -> None:
    """结束前 CLOSE_ANNOUNCE_BEFORE_SEC 秒发「已封盘停止下注」（每群每期一次）。"""
    if not CLOSE_ANNOUNCE_ENABLED:
        return
    if not runs_announce_loop(bot):
        return
    if in_maintenance_window():
        return
    if settle_announce_chain_busy(serial):
        return
    group = (bot.get("associatedGroup") or "").strip()
    if not group:
        return
    rid, _interval, remaining = active_round_timing(settings)
    if remaining > CLOSE_ANNOUNCE_BEFORE_SEC or remaining <= 0:
        return
    dedupe_key = group
    if _CLOSE_ANNOUNCED_ROUND.get(dedupe_key) == rid:
        return
    if _announce_in_fail_cooldown("close", group, rid):
        return
    if not current_round_open_gate(group, rid):
        return
    if _WARN_ANNOUNCED_ROUND.get(group) != rid:
        return
    tpl = (settings.get("closeAnnounceTemplate") or DEFAULT_CLOSE_ANNOUNCE).strip()
    if not tpl:
        return
    text = apply_template(tpl, round_id=rid)
    if _announce_already_visible(serial, bot, text):
        _CLOSE_ANNOUNCED_ROUND[group] = rid
        log.info("封盘公告已在群 rid=%s，跳过重复发送", rid)
        return
    log.info(
        "封盘公告 rid=%s 剩余%.0fs 群=%s",
        rid, remaining, group,
    )
    if _kind_dispatch_blocked("close", group, rid, serial, _CLOSE_DISPATCH_SENT):
        return
    if not dispatch_send(
        serial, bot, text, settings,
        input_xy=input_xy, send_xy=send_xy,
        prio=SEND_PRIO_CLOSE, kind="close", round_id=rid, group_ok=True,
    ):
        log.warning("封盘公告入队失败 rid=%s", rid)
        return
    _CLOSE_DISPATCH_SENT.add((group, rid))
    post_log(f"[ADB] 封盘公告 rid={rid} 剩余{int(remaining)}s", "INFO")


def latest_drawn_round_id(data: dict | None = None) -> int | None:
    """28.run 最近一条已开奖期号。"""
    payload = data if data is not None else fetch_28run_recent()
    if not payload:
        return None
    rows = payload.get("recent_results") or []
    if not rows:
        return None
    try:
        rid = int(rows[-1].get("expect", 0))
        return rid if rid > 0 else None
    except (TypeError, ValueError):
        return None


def process_round_open_announce(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
    *,
    data: dict | None = None,
) -> None:
    """新一期开始 OPEN_ANNOUNCE_AFTER_SEC 秒后发「新的一局」（须等上期开奖已播报）。"""
    if not OPEN_ANNOUNCE_ENABLED:
        return
    if not runs_announce_loop(bot):
        return
    # 左机结算链：新的一局仅由 open_after_settle 在三图后发出，禁止定时 open 抢序
    if CLICKER_SETTLE_ENABLED and SETTLE_CAPTURE_ENABLED:
        return
    if in_maintenance_window():
        return
    group = (bot.get("associatedGroup") or "").strip()
    if not group:
        return
    rid, interval, remaining = active_round_timing(settings)
    elapsed = interval - remaining
    if elapsed < OPEN_ANNOUNCE_AFTER_SEC:
        return
    if _ROUND_OPEN_ANNOUNCED.get(group) == rid:
        return
    pending = pending_settle_round_id(rid, data)
    if pending:
        defer_key = (group, rid)
        now = time.time()
        if now - _OPEN_DEFER_LOG.get(defer_key, 0) >= 30:
            _OPEN_DEFER_LOG[defer_key] = now
            log.info("开局公告延后 rid=%s：期 %s 待三图后新一局", rid, pending)
        return
    tpl = (settings.get("openAnnounceTemplate") or DEFAULT_ROUND_OPEN_ANNOUNCE).strip()
    if not tpl:
        return
    period_start = beijing_now() - timedelta(seconds=elapsed)
    open_at = period_start + timedelta(seconds=OPEN_ANNOUNCE_AFTER_SEC)
    round_time = format_group_display_time(open_at)
    text = apply_template(tpl, round_id=rid, round_time=round_time)
    if _announce_already_visible(serial, bot, text):
        _ROUND_OPEN_ANNOUNCED[group] = rid
        save_round_open_announced_persisted()
        _OPEN_DISPATCH_SENT.discard((group, rid))
        log.info("开局公告已在群 rid=%s，推进门闸", rid)
        return
    log.info(
        "开局公告 rid=%s 开盘后%.0fs 时间=%s 群=%s",
        rid, OPEN_ANNOUNCE_AFTER_SEC, round_time, group,
    )
    dispatch_key = (group, rid)
    if _open_dispatch_blocked(group, rid, serial):
        return
    if not dispatch_send(
        serial, bot, text, settings,
        input_xy=input_xy, send_xy=send_xy,
        prio=open_send_prio(group, rid), kind="open", round_id=rid, group_ok=True,
    ):
        log.warning("开局公告入队失败 rid=%s", rid)
        return
    _OPEN_DISPATCH_SENT.add(dispatch_key)
    post_log(f"[ADB] 开局公告 rid={rid} 开盘后{int(OPEN_ANNOUNCE_AFTER_SEC)}s {round_time}", "INFO")


def process_topup_outbox(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
) -> None:
    try:
        approved = api(
            "GET",
            f"/api/topup-requests?status=approved&botId={bot['id']}",
        )
    except Exception:
        return
    if not isinstance(approved, list) or not approved:
        return
    if not ensure_group_for_send(serial, bot):
        log.warning("上分回复：未在目标群 %s，暂缓发送", bot.get("associatedGroup"))
        return
    for tr in approved:
        reply = (tr.get("replyText") or "").strip()
        if not reply:
            continue
        reply = with_user_header(reply, str(tr.get("username") or ""))
        log.info("发送已审核上分 [%s] %s", tr.get("username"), tr.get("id"))
        dispatch_send(
            serial, bot, reply, settings,
            input_xy=input_xy, send_xy=send_xy,
            prio=SEND_PRIO_TOPUP,
        )
        try:
            api("POST", f"/api/topup-requests/{tr['id']}/sent", {})
        except Exception as ex:
            log.warning("标记 sent 失败: %s", ex)
        post_log(f"[ADB] 已同意上分: {tr.get('username')} +{tr.get('amount')}", "SUCCESS")
        w(1.5, 0.3)


def process_withdraw_outbox(
    serial: str,
    bot: dict,
    settings: dict[str, str],
    input_xy: tuple[int, int] | None,
    send_xy: tuple[int, int] | None,
) -> None:
    try:
        approved = api(
            "GET",
            f"/api/withdraw-requests?status=approved&botId={bot['id']}",
        )
    except Exception:
        return
    if not isinstance(approved, list) or not approved:
        return
    if not ensure_group_for_send(serial, bot):
        log.warning("下分回复：未在目标群 %s，暂缓发送", bot.get("associatedGroup"))
        return
    for tr in approved:
        reply = (tr.get("replyText") or "").strip()
        if not reply:
            continue
        reply = with_user_header(reply, str(tr.get("username") or ""))
        log.info("发送已审核下分 [%s] %s", tr.get("username"), tr.get("id"))
        dispatch_send(
            serial, bot, reply, settings,
            input_xy=input_xy, send_xy=send_xy,
            prio=SEND_PRIO_TOPUP,
        )
        try:
            api("POST", f"/api/withdraw-requests/{tr['id']}/sent", {})
        except Exception as ex:
            log.warning("下分标记 sent 失败: %s", ex)
        post_log(f"[ADB] 已同意下分: {tr.get('username')} -{tr.get('amount')}", "SUCCESS")
        w(1.5, 0.3)


def bot_device_role(bot: dict, clicker_ids: set[str] | None = None) -> str:
    """LISTENER=右机发消息 | CLICKER=左机只点击 | HYBRID=单机全能"""
    bid = str(bot.get("id") or "")
    clickers = clicker_ids if clicker_ids is not None else _clicker_bot_ids()

    per = (
        os.environ.get(f"BOT_ROLE_{bid}")
        or bot.get("deviceRole")
        or bot.get("role")
        or ""
    ).strip().upper()
    if per in ("LISTENER", "CLICKER", "HYBRID"):
        return per

    if BOT_ROLE in ("LISTENER", "CLICKER", "HYBRID"):
        if BOT_ROLE == "LISTENER" and bid == BOT_LISTENER_ID:
            return "LISTENER"
        if BOT_ROLE == "CLICKER" and bid in clickers:
            return "CLICKER"
        if BOT_ROLE == "HYBRID":
            return "HYBRID"

    if ORCHESTRATOR and (BOT_LISTENER_ID or clickers):
        if bid == BOT_LISTENER_ID:
            return "LISTENER"
        if bid in clickers:
            return "CLICKER"
        log.warning("bot %s 不在编排名单，按 CLICKER 处理", bid)
        return "CLICKER"

    if bid == BOT_LISTENER_ID:
        return "LISTENER"
    if bid in clickers:
        return "CLICKER"
    if bid != BOT_LISTENER_ID:
        return "CLICKER"
    return "HYBRID"


def bot_matches_deployment_role(bot: dict) -> bool:
    """BOT_ROLE 单机部署：过滤与本进程身份不符的云机。"""
    if BOT_ROLE not in ("LISTENER", "CLICKER"):
        return True
    return bot_device_role(bot) == BOT_ROLE


def is_clicker_bot(bot: dict | None) -> bool:
    """Clicker（左机）：点击/发图；公告在 BOT_CLICKER_SEND_ANNOUNCE=1 时由本机发送。"""
    if not bot:
        return False
    return bot_device_role(bot) == "CLICKER"


def clicker_return_to_group(serial: str, bot: dict, *, label: str = "") -> bool:
    """Clicker 完成点击任务后必须立即回到目标群聊界面。"""
    ok = clicker_back_to_group(serial, bot)
    if ok:
        log.info("Clicker 已回群 %s %s", bot.get("associatedGroup"), label)
    else:
        log.warning("Clicker 未能回到目标群 %s %s", bot.get("associatedGroup"), label)
    return ok


def is_send_bot(bot: dict | None) -> bool:
    """Listener（右机）负责群内用户回复；公告在 BOT_CLICKER_SEND_ANNOUNCE=0 时由本机发送。"""
    if not bot:
        return False
    return bot_device_role(bot) == "LISTENER" and not is_clicker_bot(bot)


def _clicker_bot_ids() -> set[str]:
    return set(CLICKER_BOT_IDS)


def _align_deploy_adb_hosts(active: list[dict]) -> None:
    """面板 adbHost 滞后时，以 bot-start.env 端口为准对齐（避免 DEPLOY LOCK 卡死）。"""
    desired: dict[str, str] = {
        BOT_LISTENER_ID: f"localhost:{_LISTENER_ADB_PORT}",
    }
    for bid in CLICKER_BOT_IDS:
        desired[bid] = f"localhost:{_CLICKER_ADB_PORT}"
    for bot in active:
        bid = str(bot.get("id") or "")
        want = desired.get(bid)
        if not want:
            continue
        cur = str(bot.get("adbHost") or "")
        if want not in cur:
            log.warning("DEPLOY LOCK align %s adbHost %s -> %s", bid, cur or "?", want)
            bot["adbHost"] = want


def validate_deploy_roles(active: list[dict]) -> None:
    """启动时校验 DEPLOY LOCK，防止左右机角色/端口被调换。"""
    if not ORCHESTRATOR:
        return
    _align_deploy_adb_hosts(active)
    by_id = {str(b.get("id") or ""): b for b in active}
    dual = os.environ.get("BOT_DUAL_PROCESS", "0").lower() in ("1", "true", "yes")
    if dual and len(by_id) == 1:
        bid = next(iter(by_id))
        bot = by_id[bid]
        slot = DEPLOY_ADB_ROLES.get(bid)
        if slot:
            port, role = slot
            host = str(bot.get("adbHost") or "")
            if port not in host:
                raise RuntimeError(f"DEPLOY LOCK: {bid} adbHost 应为 *:{port}，当前 {host}")
            actual = bot_device_role(bot, CLICKER_BOT_IDS)
            if actual != role:
                raise RuntimeError(f"DEPLOY LOCK: {bid} 应为 {role}，当前 {actual}")
        log.info("DEPLOY LOCK OK 模式=DUAL-%s 编排器=%s", slot[1] if slot else "?", bid)
        return
    if BOT_LISTENER_ID not in by_id:
        raise RuntimeError(f"监听器 {BOT_LISTENER_ID} 未 ACTIVE")
    missing = [c for c in CLICKER_BOT_IDS if c not in by_id]
    if missing and not CLICKER_OPTIONAL:
        raise RuntimeError(f"点击器未 ACTIVE: {','.join(missing)}")
    if missing and CLICKER_OPTIONAL:
        log.warning("CLICKER 未 ACTIVE（BOT_CLICKER_OPTIONAL=1）: %s", ",".join(missing))
    for bid, (port, role) in DEPLOY_ADB_ROLES.items():
        bot = by_id.get(bid)
        if not bot:
            if bid in CLICKER_BOT_IDS and CLICKER_OPTIONAL:
                continue
            continue
        host = str(bot.get("adbHost") or "")
        if port not in host:
            raise RuntimeError(f"DEPLOY LOCK: {bid} adbHost 应为 *:{port}，当前 {host}")
        actual = bot_device_role(bot, CLICKER_BOT_IDS)
        if actual != role:
            raise RuntimeError(
                f"DEPLOY LOCK: {bid} 应为 {role}，当前 {actual} "
                f"(BOT_LISTENER_ID={BOT_LISTENER_ID} BOT_CLICKER_IDS={','.join(CLICKER_BOT_IDS)})"
            )
    log.info(
        "DEPLOY LOCK OK 右机=%s@%s LISTENER 左机=%s@%s CLICKER",
        BOT_LISTENER_ID,
        by_id[BOT_LISTENER_ID].get("adbHost"),
        ",".join(sorted(CLICKER_BOT_IDS)),
        ",".join(str(by_id[c].get("adbHost") or "") for c in CLICKER_BOT_IDS if c in by_id),
    )


def _adb_port_from_serial(serial: str) -> str:
    s = (serial or "").strip()
    return s.rsplit(":", 1)[-1] if ":" in s else s


def register_deploy_serial_roles(active: list[dict]) -> None:
    """运行时 serial→角色 映射，防止 env 配错导致左右机串岗。"""
    _DEPLOY_SERIAL_ROLE.clear()
    for bot in active:
        host = bot.get("adbHost") or DEFAULT_ADB
        role = bot_device_role(bot)
        serial = resolve_serial_optional(host, label=f"{bot.get('id')}({role})")
        if not serial:
            if role == "LISTENER":
                raise RuntimeError(f"右机 LISTENER 不可用: {host}")
            log.warning("左机 CLICKER 暂不可用，认人/添加将跳过: %s", host)
            continue
        _DEPLOY_SERIAL_ROLE[serial] = role
        if role == "CLICKER":
            _CLICKER_DEPLOY["serial"] = serial
            _CLICKER_DEPLOY["bot"] = bot
    log.info(
        "serial 角色锁定: %s",
        " | ".join(f"{s}={r}" for s, r in sorted(_DEPLOY_SERIAL_ROLE.items())),
    )


def serial_role(serial: str) -> str:
    return _DEPLOY_SERIAL_ROLE.get(serial, "")


def clicker_device_model(serial: str) -> str:
    try:
        return (adb_run(serial, "shell", "getprop", "ro.product.model") or "").strip()
    except Exception:
        return ""


def clicker_model_mismatch(serial: str) -> bool:
    """左机须 V03/Pixel XL（§固定文档）；itel 等机型相册坐标无效。"""
    if not _CLICKER_EXPECT_MODEL or not is_clicker_serial(serial):
        return False
    model = clicker_device_model(serial)
    if not model:
        return False
    expect = _CLICKER_EXPECT_MODEL.lower()
    ok = expect in model.lower() or model.lower() in ("pixel xl", "v03")
    return not ok


def is_clicker_serial(serial: str, bot: dict | None = None) -> bool:
    if serial in _DEPLOY_SERIAL_ROLE:
        return _DEPLOY_SERIAL_ROLE[serial] == "CLICKER"
    if bot and is_clicker_bot(bot):
        return True
    port = _adb_port_from_serial(serial)
    return port == DEPLOY_ADB_ROLES.get("bot-3", ("52840", ""))[0]


def is_listener_send_only_serial(serial: str, bot: dict | None = None) -> bool:
    """右机 LISTENER serial（与是否允许导航无关；发送永远走 b64+钉死蓝键）。"""
    if bot and is_send_bot(bot):
        return True
    if serial in _DEPLOY_SERIAL_ROLE:
        return _DEPLOY_SERIAL_ROLE[serial] == "LISTENER"
    if bot and is_send_only_listener(bot):
        return True
    port = _adb_port_from_serial(serial)
    return port == DEPLOY_ADB_ROLES.get("bot-4", ("52715", ""))[0]


def listener_nav_frozen(serial: str) -> bool:
    """零导航模式下禁止点 Tab/群名等（回群 recovery 时临时 BOT_ALLOW_LISTENER_NAV=1 除外）。"""
    if os.environ.get("BOT_ALLOW_LISTENER_NAV") == "1":
        return False
    return is_listener_send_only_serial(serial)


def block_listener_navigation(serial: str, action: str) -> bool:
    """右机禁止一切导航/资料页/返回/搜索点击。返回 True=已拦截。"""
    if listener_nav_frozen(serial):
        log.info("右机禁止点击：%s serial=%s", action, serial)
        return True
    return False


def try_recover_listener_to_group(
    serial: str,
    bot: dict,
    *,
    reason: str = "",
    force: bool = False,
) -> bool:
    """右机离群或 55M 退后台时，限流自动拉回目标群。"""
    if not is_send_only_listener(bot):
        return ensure_group_chat(serial, bot)
    if listener_in_group_for_send(ui_hierarchy(serial), bot, serial):
        return True
    if MANUAL_IN_GROUP:
        root = ui_hierarchy(serial)
        if in_target_group_chat(root, bot, serial):
            return True
        if not force:
            return False
        log.info("BOT_MANUAL_IN_GROUP=1 禁止自动导航回群 reason=%s", reason)
        return False
    if not LISTENER_STAY_IN_GROUP:
        return False
    now = time.time()
    last = _LISTENER_LAST_RECOVER.get(serial, 0.0)
    if not force and now - last < LISTENER_STAY_RECOVER_SEC:
        return False
    _LISTENER_LAST_RECOVER[serial] = now
    tag = f" ({reason})" if reason else ""
    log.info(
        "右机尝试自动回群%s serial=%s group=%s",
        tag, serial, bot.get("associatedGroup"),
    )
    prev = os.environ.get("BOT_ALLOW_LISTENER_NAV")
    os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
    try:
        if not is_55m_foreground(serial):
            launch_messenger_app(serial)
        ok = recover_listener_to_group_minimal(serial, bot)
        if ok:
            log.info("右机自动回群成功 %s", bot.get("associatedGroup"))
        else:
            ctx = describe_screen_context(ui_hierarchy(serial), bot, serial)
            log.warning(
                "右机自动回群失败 page=%s title=%r（请手动点回目标群，勿再自动乱点）",
                ctx.page, ctx.title,
            )
        return ok
    finally:
        if prev is None:
            os.environ.pop("BOT_ALLOW_LISTENER_NAV", None)
        else:
            os.environ["BOT_ALLOW_LISTENER_NAV"] = prev


def block_clicker_send(
    serial: str,
    bot: dict | None,
    text: str,
    *,
    where: str,
    kind: str = "",
) -> bool:
    """左机禁止群内发用户文字。发图/公告（BOT_CLICKER_SEND_ANNOUNCE）放行。"""
    if CLICKER_SEND_IMAGES and where.startswith("send-image"):
        return False
    if clicker_announce_enabled() and kind in ("warn", "close", "open", "open_after_settle"):
        return False
    if is_clicker_bot(bot) or is_clicker_serial(serial, bot):
        log.warning("左机禁止群发送(%s): %s", where, message_snip(text)[:40])
        return True
    return False


def is_send_only_listener(bot: dict | None) -> bool:
    """双机：右机 Listener 只发公告/回复，禁止导航/点头像等一切非发送点击。"""
    if not bot:
        return False
    if is_send_bot(bot):
        return True
    if not ORCHESTRATOR or not _clicker_bot_ids():
        return False
    return False


def guard_listener_no_nav(serial: str, bot: dict, action: str) -> bool:
    """右机（纯发送）禁止为认人/导航离开群聊。"""
    if block_listener_navigation(serial, action) or is_send_only_listener(bot):
        if is_send_only_listener(bot):
            log.info("右机禁止导航/点击：%s serial=%s", action, serial)
        return False
    return True


def ensure_group_for_send(serial: str, bot: dict) -> bool:
    """发送前入群：Listener 双机模式检测并在离群时限流自动回群；左机发图可导航回群。"""
    if is_send_only_listener(bot):
        root = ui_hierarchy(serial)
        if listener_in_group_for_send(root, bot, serial):
            return True
        if try_recover_listener_to_group(serial, bot, reason="before-send", force=True):
            return listener_in_group_for_send(ui_hierarchy(serial), bot, serial)
        log.warning(
            "纯发送机未在目标群 %s（请手动停留在群聊界面）",
            bot.get("associatedGroup"),
        )
        return False
    return ensure_group_chat(serial, bot)


@dataclass
class ReplyJob:
    nick: str
    text: str


@dataclass
class SlowTask:
    kind: str
    listener_id: str
    nick: str
    cmd_y: int
    mid: str
    cmd: str = ""


class SharedContext:
    """大脑共享的面板数据（后台刷新，执行体只读快照）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.users: list = []
        self.products: list = []
        self.combo_rules: list = []
        self.settings: dict[str, str] = dict(DEFAULT_SETTINGS)

    def refresh(self) -> None:
        try:
            users = api("GET", "/api/users")
            products = api("GET", "/api/products")
            combo_rules = api("GET", "/api/combo-rules")
            settings = merge_settings(api("GET", "/api/settings"))
        except Exception as ex:
            log.warning("刷新面板数据失败: %s", ex)
            return
        with self._lock:
            if isinstance(users, list):
                self.users = users
            if isinstance(products, list):
                self.products = products
            if isinstance(combo_rules, list):
                self.combo_rules = combo_rules
            self.settings = settings

    def snapshot(self) -> tuple[list, list, list, dict[str, str]]:
        with self._lock:
            return self.users, self.products, self.combo_rules, dict(self.settings)


class Brain:
    """任务大脑：慢任务入队给 Clicker，完成后再派快回复给 Listener。"""

    def __init__(self) -> None:
        self._slow: queue.PriorityQueue = queue.PriorityQueue()
        self._replies: dict[str, deque[ReplyJob]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._seq = 0
        self._clicker_ids: list[str] = []
        self._clicker_load: dict[str, int] = defaultdict(int)
        self._active_add: set[str] = set()
        self._active_resolve: set[str] = set()
        self._recent_reply: dict[tuple[str, str, str], float] = {}

    def register_clickers(self, clicker_ids: list[str]) -> None:
        with self._lock:
            self._clicker_ids = list(clicker_ids)

    def has_clickers(self) -> bool:
        with self._lock:
            return bool(self._clicker_ids)

    def _pick_clicker(self) -> str:
        with self._lock:
            if not self._clicker_ids:
                return ""
            pick = min(self._clicker_ids, key=lambda cid: self._clicker_load[cid])
            self._clicker_load[pick] += 1
            return pick

    def _done_clicker(self, clicker_id: str) -> None:
        with self._lock:
            if clicker_id in self._clicker_load and self._clicker_load[clicker_id] > 0:
                self._clicker_load[clicker_id] -= 1

    def submit_add_finance(
        self,
        listener_id: str,
        nick: str,
        cmd_y: int,
        mid: str,
    ) -> bool:
        return self._submit_slow(
            "ADD_FINANCE", listener_id, nick, cmd_y, mid, ADD_FINANCE_CMD, prio=5,
        )

    def submit_bind(
        self,
        listener_id: str,
        nick: str,
        cmd: str,
        cmd_y: int,
        mid: str,
    ) -> bool:
        return self._submit_slow("BIND", listener_id, nick, cmd_y, mid, cmd, prio=4)

    def submit_resolve_cmd(
        self,
        listener_id: str,
        nick: str,
        cmd_y: int,
        mid: str,
        cmd: str,
    ) -> bool:
        """Listener 无 ID 缓存时，委派 Clicker 点头像读 ID 再执行业务指令。"""
        nick_key = (nick or "").strip().lower()
        dedup = f"{listener_id}|{(nick or '').strip().lower()}|{normalize_cmd_key(cmd)}|{cmd_y // CMD_Y_BUCKET}"
        with self._lock:
            if dedup in self._active_resolve:
                log.info("RESOLVE_CMD 已在队列 nick=%s cmd=%s", nick, cmd)
                return True
            self._active_resolve.add(dedup)
        ok = self._submit_slow("RESOLVE_CMD", listener_id, nick, cmd_y, mid, cmd, prio=2)
        if not ok:
            with self._lock:
                self._active_resolve.discard(dedup)
        return ok

    def release_resolve_cmd(self, listener_id: str, nick: str, cmd: str, cmd_y: int) -> None:
        dedup = f"{listener_id}|{(nick or '').strip().lower()}|{normalize_cmd_key(cmd)}|{cmd_y // CMD_Y_BUCKET}"
        with self._lock:
            self._active_resolve.discard(dedup)

    def is_resolve_active(self, listener_id: str, nick: str, cmd: str, cmd_y: int = 0) -> bool:
        dedup = f"{listener_id}|{(nick or '').strip().lower()}|{normalize_cmd_key(cmd)}|{cmd_y // CMD_Y_BUCKET}"
        with self._lock:
            return dedup in self._active_resolve

    def _submit_slow(
        self,
        kind: str,
        listener_id: str,
        nick: str,
        cmd_y: int,
        mid: str,
        cmd: str,
        *,
        prio: int = 5,
    ) -> bool:
        nick_key = (nick or "").strip().lower()
        if kind == "ADD_FINANCE" and nick_key:
            with self._lock:
                if nick_key in self._active_add:
                    log.info("ADD 已在执行/排队，跳过重复 nick=%s", nick)
                    return True
                self._active_add.add(nick_key)
        clicker_id = self._pick_clicker()
        if not clicker_id:
            if kind == "ADD_FINANCE" and nick_key:
                with self._lock:
                    self._active_add.discard(nick_key)
            return False
        self._seq += 1
        task = SlowTask(kind, listener_id, nick, cmd_y, mid, cmd)
        self._slow.put((prio, self._seq, clicker_id, task))
        log.info("大脑委派 %s nick=%s → %s", kind, nick, clicker_id)
        return True

    def release_add_finance(self, nick: str) -> None:
        with self._lock:
            self._active_add.discard((nick or "").strip().lower())

    def requeue_slow(self, clicker_id: str, task: SlowTask, *, prio: int = 3) -> None:
        self._seq += 1
        self._slow.put((prio, self._seq, clicker_id, task))

    def pop_slow(self, clicker_id: str, timeout: float = 0.25) -> SlowTask | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                _prio, _seq, assignee, task = self._slow.get(timeout=max(0.01, deadline - time.time()))
            except queue.Empty:
                return None
            if assignee != clicker_id:
                self._slow.put((_prio, _seq, assignee, task))
                time.sleep(0.01)
                continue
            return task
        return None

    def enqueue_reply(self, listener_id: str, nick: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        key = (listener_id, (nick or "").strip().lower(), text)
        now = time.time()
        with self._lock:
            if now - self._recent_reply.get(key, 0) < 45:
                log.info("跳过重复群回复 nick=%s text=%s", nick, text[:20])
                return
            self._recent_reply[key] = now
            self._replies[listener_id].append(ReplyJob(nick, text))

    def drain_replies(self, listener_id: str) -> list[ReplyJob]:
        with self._lock:
            jobs = list(self._replies[listener_id])
            self._replies[listener_id].clear()
            return jobs

    def has_pending_replies(self, listener_id: str) -> bool:
        with self._lock:
            return bool(self._replies.get(listener_id))

    def clicker_finished(self, clicker_id: str) -> None:
        self._done_clicker(clicker_id)


class Orchestrator:
    """一脑多手：每台云手机一个执行线程，Listener 快路径不被 Clicker 阻塞。"""

    def __init__(self) -> None:
        self.brain = Brain()
        self.ctx = SharedContext()
        self.outbound_pool = get_outbound_task_pool()
        self._running = threading.Event()
        self._running.set()
        self._threads: list[threading.Thread] = []
        self._workers: dict[str, Worker] = {}
        self._serials: dict[str, str] = {}

    def _dispatch_finance_outbox_hook(self, serial: str, bot: dict) -> None:
        """Panel API 200 触发的上下分出站：有界池异步执行，brain-refresh 毫秒级返回。"""
        bot_id = str(bot.get("id") or "")
        try:
            approved = api(
                "GET",
                f"/api/topup-requests?status=approved&botId={bot_id}",
            )
            if not isinstance(approved, list) or not approved:
                return
            _, _, _, settings = self.ctx.snapshot()
            snap = ui_snapshot(serial, chat=False, channel="refresh")
            send_xy = snap.inbar_send or snap.keyboard_send
            if not in_target_group_chat(snap.root, bot, serial):
                return
            process_topup_outbox(
                serial, bot, settings, snap.input_xy, send_xy,
            )
            process_withdraw_outbox(
                serial, bot, settings, snap.input_xy, send_xy,
            )
        except Exception:
            log.exception("上分出站异常 bot=%s", bot_id)

    def _refresh_loop(self) -> None:
        topup_counter = 0
        while self._running.is_set():
            self.ctx.refresh()
            topup_counter += 1
            if topup_counter >= 2:
                topup_counter = 0
                for bot in self._listener_bots():
                    serial = self._serials.get(bot["id"])
                    if not serial:
                        continue
                    submit_outbound_hook(
                        self._dispatch_finance_outbox_hook,
                        serial,
                        bot,
                        label=f"finance-outbox-{bot.get('id')}",
                    )
            time.sleep(CONTEXT_REFRESH_SEC)

    def _listener_bots(self) -> list[dict]:
        return [
            self._workers[bid].bot
            for bid, w in self._workers.items()
            if w.role != "CLICKER" and not is_clicker_bot(w.bot)
        ]

    def _announce_loop(self, bot: dict, serial: str) -> None:
        name = f"announce-{bot.get('id')}"
        log.info("[%s] 公告线程启动 serial=%s clicker_announce=%s", name, serial, clicker_announce_enabled())
        while self._running.is_set():
            try:
                drain_capture_ipc_open_jobs(serial, bot)
                if announce_serial_skipped(bot, serial) or in_maintenance_window():
                    time.sleep(ANNOUNCE_LOOP_SEC)
                    continue
                reload_round_state_from_disk()
                _, _, _, settings = self.ctx.snapshot()
                if is_clicker_bot(bot):
                    snap = ui_snapshot(serial, chat=False, channel="clicker-img")
                    # 左机发图/选图时 UI 不在群聊页，公告只入队；实际发送由 sender 在发图结束后完成
                    input_xy = snap.input_xy
                    send_xy = snap.inbar_send or snap.keyboard_send
                else:
                    snap = ui_snapshot(serial, chat=False, channel="announce")
                    root = snap.root
                    if not listener_in_group_for_send(root, bot, serial):
                        if MANUAL_IN_GROUP:
                            log.info(
                                "[%s] MANUAL_IN_GROUP 右机未在群，跳过公告（请手动进「%s」）",
                                name,
                                bot.get("associatedGroup") or "",
                            )
                            time.sleep(ANNOUNCE_LOOP_SEC)
                            continue
                        if is_send_only_listener(bot):
                            if listener_send_blocked(root) or is_in_app_webview(root):
                                if dismiss_listener_blockers(serial, root):
                                    snap = ui_snapshot(serial, chat=False, channel="announce")
                                    root = snap.root
                            if not listener_in_group_for_send(root, bot, serial):
                                if LISTENER_ZERO_NAV and is_group_chat_activity(serial):
                                    dismiss_listener_blockers(serial, root)
                                    snap = ui_snapshot(serial, chat=False, channel="announce")
                                    root = snap.root
                                elif not LISTENER_ZERO_NAV:
                                    recover_listener_to_group_minimal(serial, bot)
                                    snap = ui_snapshot(serial, chat=False, channel="announce")
                                    root = snap.root
                        if not listener_in_group_for_send(root, bot, serial):
                            if is_send_only_listener(bot) and is_in_app_webview(root):
                                log.warning("[%s] 右机在开奖外链页，系统返回", name)
                                dismiss_in_app_webview(serial, max_steps=1)
                            else:
                                log.info("[%s] 右机不在群聊，跳过公告", name)
                                time.sleep(ANNOUNCE_LOOP_SEC)
                                continue
                    input_xy = snap.input_xy
                    send_xy = listener_pinned_send_xy(settings, snap) if is_send_only_listener(bot) else (
                        snap.inbar_send or snap.keyboard_send
                    )
                try:
                    if EDGE_LEFT_JS:
                        poll_edge_brain_open_dispatch(
                            serial, bot, settings, input_xy, send_xy,
                        )
                    else:
                        drain_capture_ipc_open_jobs(serial, bot)
                except Exception:
                    log.exception("[capture-ipc] 处理 done 失败")
                process_stale_open_after_capture()
                draw_data = fetch_28run_recent(force=False)
                process_round_open_announce(
                    serial, bot, settings, input_xy, send_xy, data=draw_data,
                )
                process_round_warn_announce(
                    serial, bot, settings, input_xy, send_xy,
                )
                process_round_close_announce(
                    serial, bot, settings, input_xy, send_xy,
                )
                # 开局公告由结算线程在播报完成后触发，避免与开奖结果抢顺序
            except Exception:
                log.exception("[%s] 公告异常", name)
            time.sleep(ANNOUNCE_LOOP_SEC)

    def _sender_loop(self, bot: dict, serial: str) -> None:
        name = f"sender-{bot.get('id')}"
        log.info("[%s] 发送线程启动 serial=%s (优先级队列)", name, serial)
        while self._running.is_set():
            if runs_announce_loop(bot):
                drain_capture_ipc_open_jobs(serial, bot)
            job = outbound_for(serial).get(timeout=0.25)
            if not job:
                continue
            if (job.image_paths or job.image_path) and (
                is_clicker_bot(bot) or is_clicker_serial(serial, bot)
            ):
                outbound_enqueue(job)
                time.sleep(0.02)
                continue
            if not job.image_paths and not job.image_path and _announce_job_redundant(job):
                log.info(
                    "[%s] 跳过重复公告 kind=%s rid=%s",
                    name, job.kind, job.round_id,
                )
                continue
            if job.kind in ("open", "open_after_settle") and job.round_id > 0:
                group = (job.bot.get("associatedGroup") or "").strip()
                announced = _ROUND_OPEN_ANNOUNCED.get(group, 0)
                if announced and job.round_id <= announced:
                    log.info(
                        "[%s] 跳过过期 open rid=%s（已公告 rid=%s）",
                        name, job.round_id, announced,
                    )
                    continue
                try:
                    cur_rid, _, _ = active_round_timing(job.settings)
                    if job.round_id < cur_rid - 1:
                        log.info(
                            "[%s] 跳过积压 open rid=%s（当前期 %s）",
                            name, job.round_id, cur_rid,
                        )
                        continue
                except Exception:
                    pass
            elif job.kind in ("warn", "close") and job.round_id > 0:
                group = (job.bot.get("associatedGroup") or "").strip()
                try:
                    cur_rid, _, _ = active_round_timing(job.settings)
                    if job.round_id < cur_rid:
                        log.info(
                            "[%s] 跳过过期 %s rid=%s（当前期 %s）",
                            name, job.kind, job.round_id, cur_rid,
                        )
                        continue
                    if job.kind == "warn" and _WARN_ANNOUNCED_ROUND.get(group) == job.round_id:
                        continue
                    if job.kind == "close":
                        if _CLOSE_ANNOUNCED_ROUND.get(group) == job.round_id:
                            continue
                        if _WARN_ANNOUNCED_ROUND.get(group) != job.round_id:
                            outbound_enqueue(job)
                            time.sleep(0.05)
                            continue
                except Exception:
                    pass
            if (
                (job.image_paths or job.image_path)
                and is_listener_send_only_serial(serial, job.bot)
                and CLICKER_SEND_IMAGES
            ):
                log.warning("[%s] 发图任务不应走右机，丢弃 rid=%s", name, job.round_id)
                continue
            if (
                (job.image_paths or job.image_path)
                and outbound_pending_announce_text(serial)
            ):
                outbound_enqueue(job)
                time.sleep(0.03)
                continue
            if (
                job.kind in ("warn", "close", "open", "open_after_settle")
                and (_any_clicker_img_flow_busy() or settle_announce_chain_busy(serial))
            ):
                outbound_enqueue(job)
                time.sleep(0.12 if _any_clicker_img_flow_busy() else 0.08)
                continue
            if not job.image_paths and not job.image_path and job.kind in (
                "warn", "close", "open", "open_after_settle",
            ):
                log.info(
                    "[%s] 队列出队 kind=%s rid=%s prio=%s",
                    name, job.kind, job.round_id, job.prio,
                )
            ok = False
            try:
                _LISTENER_SEND_LOCK[serial] = True
                if job.image_paths:
                    ok = send_chat_images_batch(
                        job.serial,
                        job.bot,
                        job.image_paths,
                        job.input_xy,
                        job.send_xy,
                        job.settings,
                        group_ok=job.group_ok,
                    )
                elif job.image_path:
                    ok = send_chat_image(
                        job.serial,
                        job.bot,
                        job.image_path,
                        job.input_xy,
                        job.send_xy,
                        job.settings,
                        group_ok=job.group_ok,
                    )
                else:
                    is_announce_text = (
                        not job.image_paths
                        and not job.image_path
                        and (
                            job.kind in ("warn", "close", "open", "open_after_settle")
                            or job.prio >= SEND_PRIO_WARN
                        )
                    )
                    use_fast = (
                        LISTENER_FAST_SEND
                        and is_listener_send_only_serial(serial, job.bot)
                        and (
                            job.prio <= SEND_PRIO_BRAIN
                            or LISTENER_PURE_PIPE
                            or is_announce_text
                        )
                    )
                    if (
                        not use_fast
                        and not is_announce_text
                        and outbound_for(serial).pending_cmd_jobs()
                    ):
                        outbound_enqueue(job)
                        time.sleep(0.005)
                        continue
                    ok = send_chat_reply(
                        job.serial,
                        job.bot,
                        job.text,
                        job.input_xy,
                        job.send_xy,
                        job.settings,
                        group_ok=job.group_ok,
                        skip_fast=not use_fast,
                        kind=job.kind,
                    )
                if ok:
                    if job.kind in ("open", "open_after_settle") and job.round_id:
                        group = (job.bot.get("associatedGroup") or "").strip()
                        if group:
                            _ROUND_OPEN_ANNOUNCED[group] = job.round_id
                            save_round_open_announced_persisted()
                    elif job.kind == "warn" and job.round_id:
                        group = (job.bot.get("associatedGroup") or "").strip()
                        if group:
                            _WARN_ANNOUNCED_ROUND[group] = job.round_id
                    elif job.kind == "close" and job.round_id:
                        group = (job.bot.get("associatedGroup") or "").strip()
                        if group:
                            _CLOSE_ANNOUNCED_ROUND[group] = job.round_id
                    elif job.kind == "trend" and job.round_id:
                        post_log(f"[ADB] 六合走势图 rid={job.round_id}", "INFO")
                    label = (
                        f"批量{len(job.image_paths)}张"
                        if job.image_paths
                        else (os.path.basename(job.image_path) if job.image_path else message_snip(job.text)[:80])
                    )
                    post_log(
                        f"[ADB] 队列发送(p{job.prio}): {label}",
                        "SUCCESS",
                    )
                    if job.text and job.text.strip() and is_listener_send_only_serial(job.serial, job.bot):
                        defer_listener_composer_clean(job.serial, reason=f"send-{job.kind or 'text'}")
                elif job.prio <= SEND_PRIO_BRAIN:
                    log.warning("[%s] 用户回复发送失败: %s", name, message_snip(job.text)[:60])
                elif job.image_paths or job.image_path:
                    if job.image_paths:
                        log.warning("[%s] 批量发图失败 rid=%s", name, job.round_id)
                    else:
                        log.warning("[%s] 发图失败 %s", name, os.path.basename(job.image_path))
                elif job.kind == "settle" and job.round_id:
                    log.warning("[%s] 结算发送失败 rid=%s", name, job.round_id)
                elif job.kind in ("warn", "close", "open", "open_after_settle"):
                    log.warning(
                        "[%s] 公告发送失败 kind=%s rid=%s: %s",
                        name, job.kind, job.round_id, message_snip(job.text)[:48],
                    )
                    grp = (job.bot.get("associatedGroup") or "").strip()
                    if grp and job.round_id:
                        _mark_announce_fail_cooldown(job.kind, grp, job.round_id)
                    if job.kind == "open" and job.round_id:
                        if grp:
                            _OPEN_DISPATCH_SENT.discard((grp, job.round_id))
                    elif job.kind == "warn" and job.round_id:
                        if grp:
                            _WARN_DISPATCH_SENT.discard((grp, job.round_id))
                    elif job.kind == "close" and job.round_id:
                        if grp:
                            _CLOSE_DISPATCH_SENT.discard((grp, job.round_id))
                if not ok and job.text.strip():
                    _release_outbound_dedup(job.serial, job.text)
            except Exception:
                log.exception("[%s] 发送失败", name)
                if job.text.strip():
                    _release_outbound_dedup(job.serial, job.text)
            finally:
                _LISTENER_SEND_LOCK[serial] = False
                invalidate_roi_cache(serial)

    def _listener_stay_loop(self, bot: dict, serial: str) -> None:
        """右机看门狗：仅系统 Back 关外链，禁止 Tab/群名乱点。"""
        name = f"listener-stay-{bot.get('id')}"
        interval = max(LISTENER_STAY_RECOVER_SEC, 15.0 if LISTENER_ZERO_NAV else LISTENER_STAY_RECOVER_SEC)
        log.info("[%s] 右机驻群看门狗 serial=%s interval=%.0fs zero_nav=%s", name, serial, interval, LISTENER_ZERO_NAV)
        while self._running.is_set():
            try:
                if MANUAL_IN_GROUP:
                    root = ui_hierarchy(serial, channel="stay")
                    dismiss_upgrade_popup(serial)
                    if listener_send_blocked(root, serial):
                        dismiss_listener_blockers(serial, root)
                    time.sleep(interval)
                    continue
                if not is_send_only_listener(bot):
                    time.sleep(interval)
                    continue
                root = ui_hierarchy(serial, channel="stay")
                if not is_55m_foreground(serial):
                    log.warning("[%s] 右机不在 55M 前台，拉起", name)
                    launch_messenger_app(serial)
                    recover_listener_to_group_minimal(serial, bot)
                    root = ui_hierarchy(serial, channel="stay")
                if listener_send_blocked(root, serial):
                    dismiss_listener_blockers(serial, root)
                elif is_in_app_webview(root) and not is_group_chat_activity(serial):
                    log.warning("[%s] 右机卡在开奖外链，系统返回", name)
                    dismiss_in_app_webview(serial, max_steps=1)
                elif not listener_in_group_for_send(root, bot, serial):
                    log.warning(
                        "[%s] 右机不在群 page=%s",
                        name,
                        describe_screen_context(root, bot, serial).page,
                    )
                    if is_group_chat_activity(serial) or not LISTENER_ZERO_NAV:
                        recover_listener_to_group_minimal(serial, bot)
            except Exception:
                log.exception("[%s] 驻群看门狗异常", name)
            time.sleep(interval)

    def _clicker_stay_loop(self, bot: dict, serial: str) -> None:
        """左机驻群看门狗：桌面/离群时拉回，任务在群内完成。"""
        name = f"clicker-stay-{bot.get('id')}"
        log.info("[%s] 左机驻群看门狗 serial=%s interval=%.0fs", name, serial, CLICKER_STAY_SEC)
        while self._running.is_set():
            try:
                if MANUAL_IN_GROUP:
                    dismiss_clicker_dialogs(serial)
                    dismiss_upgrade_popup(serial)
                    root = ui_hierarchy(serial)
                    if is_clicker_serial(serial) and root is not None:
                        if is_on_launcher(serial) or not is_55m_foreground(serial):
                            log.warning("[%s] 左机离桌面/退后台，拉回 55M（MANUAL_IN_GROUP）", name)
                            ensure_clicker_in_group(serial, bot, reason="manual-watchdog")
                        elif not in_target_group_chat(root, bot, serial):
                            ctx = describe_screen_context(root, bot, serial)
                            if ctx.page == "message_list":
                                log.info("[%s] 左机在消息列表，点群名回群（MANUAL_IN_GROUP）", name)
                                tap_target_group_in_list(serial, bot, scrolls=2)
                            elif not clicker_img_task_surface_ready(serial, root):
                                log.warning("[%s] 左机不在目标群 page=%s，尝试回群", name, ctx.page)
                                recover_clicker_to_group_minimal(serial, bot)
                    time.sleep(CLICKER_STAY_SEC)
                    continue
                if CLICKER_STAY_IN_CHAT:
                    if _any_clicker_img_flow_busy():
                        time.sleep(CLICKER_STAY_SEC)
                        continue
                    try:
                        from bot_ops.capture_ipc import has_pending_captures

                        if has_pending_captures():
                            time.sleep(CLICKER_STAY_SEC)
                            continue
                    except Exception:
                        pass
                    dismiss_clicker_dialogs(serial)
                    if is_on_launcher(serial) or not is_55m_foreground(serial):
                        log.warning("[%s] 左机离桌面/退后台，拉回 55M", name)
                        ensure_clicker_in_group(serial, bot, reason="watchdog")
                    elif not in_target_group_chat(ui_hierarchy(serial), bot, serial):
                        root = ui_hierarchy(serial)
                        if clicker_img_task_surface_ready(serial, root):
                            time.sleep(CLICKER_STAY_SEC)
                            continue
                        if is_in_app_webview(root):
                            log.warning("[%s] 左机在开奖外链页，拉回群聊", name)
                        else:
                            log.warning("[%s] 左机不在目标群，尝试回群", name)
                        recover_clicker_to_group_minimal(serial, bot)
            except Exception:
                log.exception("[%s] 驻群看门狗异常", name)
            time.sleep(CLICKER_STAY_SEC)

    def _clicker_image_sender_loop(self, bot: dict, serial: str) -> None:
        """左机专用：capture-ipc 认领 + UI 发图（+→图片→勾选→发送）。"""
        name = f"clicker-img-{bot.get('id')}"
        log.info("[%s] 左机 UI 发图线程 serial=%s mode=%s", name, serial, BOT_IMG_SEND_MODE)
        if clicker_model_mismatch(serial):
            log.error(
                "[%s] 左机型号=%s 非 %s（固定文档 V03/Pixel XL）；发图坐标无效，请 VMOS 换回 APP5AU4BB269OR35",
                name, clicker_device_model(serial), _CLICKER_EXPECT_MODEL,
            )
        while self._running.is_set():
            global _CAPTURE_SUCCEEDED, _SETTLE_DISPATCHED, _SETTLED_ROUNDS
            job: OutboundSend | None = None
            ipc_open_job: dict | None = None
            try:
                from bot_ops.capture_ipc import claim_pending_captures

                for ipc in claim_pending_captures():
                    ipc_serial = str(ipc.get("clicker_serial") or serial).strip()
                    if _adb_port_from_serial(ipc_serial) != _adb_port_from_serial(serial):
                        continue
                    paths = [p for p in (ipc.get("image_paths") or []) if p]
                    rid = int(ipc.get("round_id") or 0)
                    if not paths or rid <= 0:
                        continue
                    _, _, _, settings = self.ctx.snapshot()
                    snap = ui_snapshot(serial, chat=True, channel="clicker-img")
                    job = OutboundSend(
                        serial, bot, "", settings,
                        input_xy=snap.input_xy,
                        send_xy=snap.inbar_send or snap.keyboard_send,
                        prio=SEND_PRIO_CAPTURE,
                        kind="capture_batch",
                        round_id=rid,
                        image_paths=paths,
                        group_ok=True,
                        gallery_preloaded=bool(ipc.get("gallery_preloaded")),
                    )
                    ipc_open_job = ipc.get("open_job") or {}
                    log.info("[%s] capture-ipc 认领 rid=%s paths=%d pre=%s", name, rid, len(paths), job.gallery_preloaded)
                    break
            except Exception:
                log.exception("[%s] capture-ipc 认领异常", name)
            if not job:
                job = outbound_for(serial).get(timeout=0.25)
            if not job:
                continue
            if not (job.image_paths or job.image_path):
                outbound_enqueue(job)
                time.sleep(0.02)
                continue
            if job.kind == "capture_batch" and job.round_id:
                if job.round_id in _CAPTURE_SUCCEEDED:
                    _finish_capture_batch_settle(
                        job.round_id,
                        images_ok=True,
                        ipc_open_job=ipc_open_job,
                        announce_serial=serial,
                        announce_bot=bot,
                    )
                    continue
            ok = False
            clicker_img_flow_begin(serial)
            try:
                in_group = False
                if job.gallery_preloaded and clicker_composer_or_gallery_ready(serial):
                    in_group = True
                else:
                    dismiss_clicker_stuck_surface(serial)
                    for attempt in range(2 if job.gallery_preloaded else 3):
                        if recover_clicker_to_group_minimal(serial, bot):
                            in_group = True
                            break
                        if clicker_composer_or_gallery_ready(serial):
                            in_group = True
                            break
                        _dismiss_image_picker(serial)
                        clicker_w(0.35, 0.6) if job.gallery_preloaded else clicker_w(0.7, 1.0)
                if not in_group:
                    log.warning("[%s] 左机不在目标群，跳过发图", name)
                    if job.kind == "capture_batch" and job.round_id:
                        _finish_capture_batch_settle(
                            job.round_id,
                            images_ok=False,
                            ipc_open_job=ipc_open_job,
                            announce_serial=serial,
                            announce_bot=bot,
                        )
                    continue
                if job.kind != "capture_batch" and not (
                    _verify_chat_composer_ready_serial(serial)
                    or clicker_img_task_surface_ready(serial)
                    or _verify_gallery_picker_open(serial)
                ):
                    log.warning("[%s] 左机输入栏未就绪，跳过发图", name)
                    if job.kind == "capture_batch" and job.round_id:
                        _finish_capture_batch_settle(
                            job.round_id,
                            images_ok=False,
                            ipc_open_job=ipc_open_job,
                            announce_serial=serial,
                            announce_bot=bot,
                        )
                    continue
                dismiss_clicker_popup_overlay(serial)
                snap = ui_snapshot(serial, chat=True, channel="clicker-img")
                ix = job.input_xy or snap.input_xy
                sy = job.send_xy or snap.inbar_send or snap.keyboard_send
                if job.image_paths:
                    bubble_before = 0
                    snap_b = ui_snapshot(serial, chat=False, channel="clicker-img")
                    ib_b = snap_b.input_bounds
                    if ib_b and snap_b.root:
                        bubble_before = _count_chat_media_bubbles(snap_b.root, ib_b[1] - 16)
                    for send_try in range(CLICKER_IMG_SEND_RETRIES):
                        if send_try > 0:
                            snap_c = ui_snapshot(serial, chat=False, channel="clicker-img")
                            ib_c = snap_c.input_bounds
                            if ib_c and snap_c.root:
                                delta = (
                                    _count_chat_media_bubbles(snap_c.root, ib_c[1] - 16)
                                    - bubble_before
                                )
                                if delta >= len(job.image_paths):
                                    log.info(
                                        "[%s] 群聊已新增%d张图，停止重试 rid=%s",
                                        name, delta, job.round_id,
                                    )
                                    ok = True
                                    break
                        ok = send_chat_images_batch(
                            serial, bot, job.image_paths, ix, sy, job.settings, group_ok=True,
                            settle_rid=job.round_id or 0,
                            gallery_preloaded=job.gallery_preloaded,
                        )
                        if ok:
                            break
                        if send_try + 1 < CLICKER_IMG_SEND_RETRIES:
                            log.warning(
                                "[%s] 左机发图重试 rid=%s try=%d",
                                name, job.round_id, send_try + 2,
                            )
                            _dismiss_image_picker(serial)
                            clicker_w(0.3, 0.5)
                else:
                    ok = send_chat_image(
                        serial, bot, job.image_path, ix, sy, job.settings, group_ok=True,
                    )
                if ok:
                    if job.kind == "capture_batch" and job.round_id:
                        _CAPTURE_SUCCEEDED.add(job.round_id)
                    label = (
                        f"批量{len(job.image_paths)}张"
                        if job.image_paths
                        else os.path.basename(job.image_path)
                    )
                    post_log(f"[ADB] 左机 UI 发图成功: {label}", "SUCCESS")
                    clicker_return_to_group(serial, bot, label="after-ui-image")
                    if job.kind == "capture_batch" and job.round_id:
                        _SETTLE_DISPATCHED.add(job.round_id)
                else:
                    log.warning("[%s] 左机 UI 发图失败 rid=%s", name, job.round_id)
                if job.kind == "capture_batch" and job.round_id:
                    _finish_capture_batch_settle(
                        job.round_id,
                        images_ok=ok,
                        ipc_open_job=ipc_open_job,
                        announce_serial=serial,
                        announce_bot=bot,
                    )
                    if ok:
                        _SETTLED_ROUNDS.add(job.round_id)
                        save_settled_rounds_persisted()
            except Exception:
                log.exception("[%s] 左机发图异常", name)
                if job.kind == "capture_batch" and job.round_id:
                    _finish_capture_batch_settle(
                        job.round_id,
                        images_ok=False,
                        ipc_open_job=ipc_open_job,
                        announce_serial=serial,
                        announce_bot=bot,
                    )
            finally:
                clicker_img_flow_end(serial)
                invalidate_roi_cache(serial)

    def _settlement_loop(self, bot: dict, serial: str) -> None:
        name = f"settle-{bot.get('id')}"
        log.info("[%s] 结算线程启动 serial=%s", name, serial)
        while self._running.is_set():
            try:
                if maintenance_just_ended():
                    users, _, _, settings = self.ctx.snapshot()
                    snap = ui_snapshot(serial, chat=False, channel="settle")
                    send_xy = snap.inbar_send or snap.keyboard_send
                    if describe_screen_context(snap.root, bot, serial).page == "target_group":
                        process_maintenance_resume(
                            serial, bot, settings, users, snap.input_xy, send_xy,
                        )
                if SETTLE_ENABLED and should_run_settlement(bot, serial) and not in_maintenance_window():
                    users, _, _, settings = self.ctx.snapshot()
                    process_round_settlement(
                        serial, bot, settings, users, None, None, force_draw=True,
                    )
            except Exception:
                log.exception("[%s] 结算异常", name)
            time.sleep(SETTLE_LOOP_SEC)

    def _listener_loop(self, bot: dict, serial: str) -> None:
        name = f"listener-{bot.get('id')}"
        worker = self._workers[bot["id"]]
        log.info("[%s] 监听线程启动 serial=%s", name, serial)
        while self._running.is_set():
            try:
                if not clicker_announce_enabled():
                    drain_capture_ipc_open_jobs(serial, bot)
                users, products, combo_rules, settings = self.ctx.snapshot()
                had_work = worker.tick(serial, users, products, combo_rules, settings)
            except RuntimeError as ex:
                log.error("[%s] ADB: %s", name, str(ex).replace("\n", " | "))
                time.sleep(6)
                continue
            except Exception:
                log.exception("[%s] 异常", name)
                time.sleep(2)
                continue
            delay = LISTENER_TICK_SEC if had_work or not worker._tick_idle else LISTENER_IDLE_TICK_SEC
            time.sleep(delay)

    def _clicker_loop(self, bot: dict, serial: str) -> None:
        bid = bot["id"]
        name = f"clicker-{bid}"
        log.info("[%s] 点击线程启动 serial=%s", name, serial)
        while self._running.is_set():
            task = self.brain.pop_slow(bid, timeout=CLICKER_IDLE_SEC)
            if not task:
                continue
            try:
                users, products, combo_rules, settings = self.ctx.snapshot()
                if not ensure_clicker_in_group(serial, bot, reason=task.kind):
                    log.warning("[%s] Clicker 未能进入目标群，任务推迟", name)
                    self.brain.requeue_slow(bid, task)
                    time.sleep(1)
                    continue
                if task.kind == "ADD_FINANCE":
                    log.info("[%s] 执行 ADD_FINANCE ← %s", name, task.nick)
                    try:
                        local_y = resolve_add_near_y(
                            serial, bot, task.nick, task.cmd_y or None,
                            users, products, settings,
                        )
                        result = send_friend_add_request(
                            serial, bot, task.nick, local_y, settings,
                            skip_group_reply=True,
                        )
                        if result == "ok":
                            self.brain.enqueue_reply(
                                task.listener_id, task.nick,
                                user_reply(task.nick, ADD_FINANCE_REPLY),
                            )
                        elif result == "already":
                            self.brain.enqueue_reply(
                                task.listener_id, task.nick,
                                user_reply(task.nick, ADD_FINANCE_ALREADY_REPLY),
                            )
                        else:
                            self.brain.enqueue_reply(
                                task.listener_id, task.nick,
                                user_reply(task.nick, ADD_FINANCE_FAIL_REPLY),
                            )
                    finally:
                        self.brain.release_add_finance(task.nick)
                elif task.kind == "BIND":
                    log.info("[%s] 执行 BIND ← %s cmd=%s", name, task.nick, task.cmd)
                    m = BIND_RE.match((task.cmd or "").strip())
                    if not m:
                        self.brain.enqueue_reply(
                            task.listener_id, task.nick,
                            user_reply(task.nick, "绑定失败", "命令无效"),
                        )
                    else:
                        reply = handle_bind(m.group(1), bot, task.nick, serial)
                        self.brain.enqueue_reply(task.listener_id, task.nick, reply or "绑定失败")
                elif task.kind == "RESOLVE_CMD":
                    listener_bot = self._workers.get(task.listener_id)
                    lbot = listener_bot.bot if listener_bot else bot
                    log.info("[%s] RESOLVE_CMD ← %s cmd=%s y=%s", name, task.nick, task.cmd, task.cmd_y)
                    if task.cmd_y:
                        _TAP_NEAR_Y[serial] = task.cmd_y
                    users, products, combo_rules, settings = self.ctx.snapshot()
                    if not is_plausible_sender(task.nick, settings, products, lbot["id"]):
                        log.warning("[%s] RESOLVE_CMD 无效昵称，跳过: %s", name, task.nick)
                    else:
                        mid = read_messenger_id_for_nick(
                            serial, task.nick, users, lbot["id"], bot=bot,
                        )
                        if mid and GATEWAY_ENABLED:
                            gateway_update_id(task.nick, mid)
                        if mid:
                            log.info("[%s] RESOLVE_CMD 已读 ID %s ← %s", name, mid, task.nick)
                        reply = handle_command(
                            task.cmd, lbot, users, products, combo_rules, settings,
                            task.nick, serial,
                            cache_serial=serial,
                        )
                        if reply:
                            self.brain.enqueue_reply(task.listener_id, task.nick, reply)
                        elif needs_registration_reply(task.cmd):
                            self.brain.enqueue_reply(
                                task.listener_id, task.nick,
                                user_reply(task.nick, UNREGISTERED_REPLY),
                            )
                        else:
                            log.info("RESOLVE_CMD 无回复 nick=%s cmd=%s", task.nick, task.cmd)
                else:
                    log.warning("[%s] 未知慢任务 %s", name, task.kind)
            except Exception:
                log.exception("[%s] 慢任务失败", name)
                if task.kind == "ADD_FINANCE":
                    self.brain.release_add_finance(task.nick)
                    self.brain.enqueue_reply(
                        task.listener_id, task.nick,
                        user_reply(task.nick, ADD_FINANCE_FAIL_REPLY),
                    )
            finally:
                clicker_return_to_group(serial, bot, label=f"after {task.kind}")
                self.brain.clicker_finished(bid)
                if task.kind == "RESOLVE_CMD":
                    self.brain.release_resolve_cmd(task.listener_id, task.nick, task.cmd, task.cmd_y)

    def start(self, active: list[dict]) -> None:
        active = [b for b in active if str(b.get("id") or "") not in SKIP_BOT_IDS]
        active = [b for b in active if bot_matches_deployment_role(b)]
        if BOT_ROLE:
            log.info("BOT_ROLE=%s GATEWAY=%s 本进程 active=%s", BOT_ROLE, GATEWAY_ENABLED, [b.get("id") for b in active])
        if SKIP_BOT_IDS:
            log.info("跳过 bot: %s", ",".join(sorted(SKIP_BOT_IDS)))
        validate_deploy_roles(active)
        register_deploy_serial_roles(active)
        for bot in active:
            if is_clicker_bot(bot):
                host = bot.get("adbHost") or DEFAULT_ADB
                cs = resolve_serial_optional(host, label=f"{bot.get('id')}(model-check)")
                if cs and clicker_model_mismatch(cs):
                    log.error(
                        "左机 CLICKER %s 型号=%s ≠ %s — 发图将 0/3；控制台须换回 V03 pad APP5AU4BB269OR35",
                        bot.get("id"), clicker_device_model(cs), _CLICKER_EXPECT_MODEL,
                    )
        clicker_ids = [
            b["id"] for b in active if bot_device_role(b) == "CLICKER"
        ]
        self.brain.register_clickers(clicker_ids)
        self.ctx.refresh()

        by_serial: dict[str, list[tuple[dict, str]]] = defaultdict(list)
        for bot in active:
            host = bot.get("adbHost") or DEFAULT_ADB
            role = bot_device_role(bot, set(clicker_ids))
            serial = resolve_serial_optional(host, label=f"{bot.get('id')}({role})")
            if not serial:
                if role == "LISTENER":
                    raise RuntimeError(f"右机 LISTENER 不可用: {host}")
                log.warning("跳过不可用 CLICKER bot=%s host=%s", bot.get("id"), host)
                continue
            self._workers[bot["id"]] = Worker(bot, role=role, brain=self.brain)
            self._serials[bot["id"]] = serial
            by_serial[serial].append((bot, role))
            log.info(
                "编排 %s role=%s serial=%s group=%s",
                bot.get("botName"), role, serial, bot.get("associatedGroup"),
            )

        for serial, items in by_serial.items():
            if len(items) > 1:
                log.warning("同一 serial %s 绑了 %d 个 bot，仅建议一机一号", serial, len(items))

        log.info(
            "出站并发池 outbound-pool max_workers=%d (公告/回复队列预留)",
            self.outbound_pool.max_workers,
        )

        if UI_COLLECTOR_ENABLED:
            for serial in by_serial:
                ensure_ui_collector(serial)
                ui_collector_prewarm(serial)
                log.info("读屏收集器 ui-collect 启动+预热 serial=%s", serial)

        t = threading.Thread(target=self._refresh_loop, name="brain-refresh", daemon=True)
        t.start()
        self._threads.append(t)

        if PROBE_ENABLED:
            start_probe_server()
        for bot in active:
            serial = self._serials.get(bot["id"])
            if not serial:
                continue
            if is_send_bot(bot):
                ensure_adb_keyboard_installed(serial)
                if PROBE_ENABLED:
                    setup_probe_adb_reverse(serial)
                    ensure_trime_installed(serial)
                    enable_probe_accessibility(serial)

        th_log = threading.Thread(target=_log_worker_loop, name="log-worker", daemon=True)
        th_log.start()
        self._threads.append(th_log)
        for i in range(1, LOG_WORKER_THREADS):
            th_extra = threading.Thread(
                target=_log_worker_loop, name=f"log-worker-{i + 1}", daemon=True,
            )
            th_extra.start()
            self._threads.append(th_extra)

        for bot in active:
            bid = str(bot.get("id") or "")
            if bid not in self._serials or bid not in self._workers:
                continue
            serial = self._serials[bid]
            role = self._workers[bid].role
            if role == "CLICKER":
                fn = self._clicker_loop
            else:
                fn = self._listener_loop
            th = threading.Thread(
                target=fn, args=(bot, serial),
                name=f"{role.lower()}-{bot['id']}", daemon=True,
            )
            th.start()
            self._threads.append(th)
            if role == "CLICKER":
                log.info(
                    "左机 CLICKER %s @ %s — 添加/认ID%s%s",
                    bot.get("id"),
                    serial,
                    " + UI发图" if CLICKER_SEND_IMAGES else "",
                    " + 28.run结算" if clicker_settle_enabled() else "",
                )
                if CLICKER_SEND_IMAGES:
                    clicker_ensure_fire_worker(serial)
                    st_img = threading.Thread(
                        target=self._clicker_image_sender_loop,
                        args=(bot, serial),
                        name=f"clicker-img-{bot['id']}",
                        daemon=True,
                    )
                    st_img.start()
                    self._threads.append(st_img)
                if SETTLE_ENABLED and clicker_settle_enabled():
                    st_settle = threading.Thread(
                        target=self._settlement_loop, args=(bot, serial),
                        name=f"settle-{bot['id']}", daemon=True,
                    )
                    st_settle.start()
                    self._threads.append(st_settle)
                if CLICKER_STAY_IN_CHAT:
                    st_stay = threading.Thread(
                        target=self._clicker_stay_loop,
                        args=(bot, serial),
                        name=f"clicker-stay-{bot['id']}",
                        daemon=True,
                    )
                    st_stay.start()
                    self._threads.append(st_stay)
                if clicker_announce_enabled():
                    clicker_ensure_fire_worker(serial)
                    at = threading.Thread(
                        target=self._announce_loop, args=(bot, serial),
                        name=f"announce-{bot['id']}", daemon=True,
                    )
                    at.start()
                    self._threads.append(at)
                    if SEND_QUEUE_ENABLED:
                        st_ann = threading.Thread(
                            target=self._sender_loop, args=(bot, serial),
                            name=f"sender-{bot['id']}", daemon=True,
                        )
                        st_ann.start()
                        self._threads.append(st_ann)
                    log.info(
                        "左机 CLICKER %s @ %s — 公告 warn/close/open 本机发送",
                        bot.get("id"), serial,
                    )
                continue
            if is_clicker_serial(serial, bot):
                log.error("左机 serial 被标为 LISTENER，拒绝启动发送线程 %s", serial)
                continue
            if SETTLE_ENABLED and not clicker_settle_enabled():
                st = threading.Thread(
                    target=self._settlement_loop, args=(bot, serial),
                    name=f"settle-{bot['id']}", daemon=True,
                )
                st.start()
                self._threads.append(st)
            if is_send_bot(bot):
                if not clicker_announce_enabled():
                    at = threading.Thread(
                        target=self._announce_loop, args=(bot, serial),
                        name=f"announce-{bot['id']}", daemon=True,
                    )
                    at.start()
                    self._threads.append(at)
                if SEND_QUEUE_ENABLED:
                    listener_ensure_fire_worker(serial)
                    st_send = threading.Thread(
                        target=self._sender_loop, args=(bot, serial),
                        name=f"sender-{bot['id']}", daemon=True,
                    )
                    st_send.start()
                    self._threads.append(st_send)
                if LISTENER_STAY_IN_GROUP:
                    st_lstay = threading.Thread(
                        target=self._listener_stay_loop, args=(bot, serial),
                        name=f"listener-stay-{bot['id']}", daemon=True,
                    )
                    st_lstay.start()
                    self._threads.append(st_lstay)
                log.info(
                    "右机 LISTENER %s @ %s — %s",
                    bot.get("id"),
                    serial,
                    "仅用户回复" if clicker_announce_enabled() else "群内发送/监听",
                )

        log.info(
            "大脑编排已启动 右机发送=%s 左机点击=%s tick=%.0fms debounce=%.1fs",
            BOT_LISTENER_ID,
            ",".join(sorted(clicker_ids)) or "-",
            LISTENER_TICK_SEC * 1000,
            SEND_DEBOUNCE_SEC,
        )

        def boot_stabilize() -> None:
            time.sleep(2.5)
            heal_adb_hosts(active)
            if MANUAL_IN_GROUP:
                log.info("BOT_MANUAL_IN_GROUP=1 跳过 boot 自动回群（W49 已手动进群）")
                for bot in active:
                    bid = str(bot.get("id") or "")
                    serial = self._serials.get(bid)
                    if serial and is_send_bot(bot):
                        listener_hide_keyboard(serial, reason="boot")
                return
            prev = os.environ.get("BOT_ALLOW_LISTENER_NAV")
            os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
            try:
                for bot in active:
                    bid = str(bot.get("id") or "")
                    serial = self._serials.get(bid)
                    if not serial:
                        continue
                    if is_send_bot(bot):
                        try_recover_listener_to_group(
                            serial, bot, reason="boot", force=True,
                        )
                        listener_hide_keyboard(serial, reason="boot")
                    elif bot_device_role(bot) == "CLICKER":
                        ensure_clicker_in_group(serial, bot, reason="boot")
            finally:
                if prev is None:
                    os.environ.pop("BOT_ALLOW_LISTENER_NAV", None)
                else:
                    os.environ["BOT_ALLOW_LISTENER_NAV"] = prev

        threading.Thread(target=boot_stabilize, name="boot-stabilize", daemon=True).start()

        def adb_heal_loop() -> None:
            while self._running.is_set():
                time.sleep(45)
                try:
                    if not ADB_HEAL_DURING_SEND:
                        listener_serial = None
                        for bot in active:
                            if is_send_bot(bot):
                                listener_serial = str(bot.get("adbHost") or "").strip()
                                break
                        if listener_serial and listener_send_protected(listener_serial):
                            continue
                    heal_adb_hosts(active)
                except Exception:
                    log.exception("ADB 自愈循环异常")

        threading.Thread(target=adb_heal_loop, name="adb-heal", daemon=True).start()

    def join_forever(self) -> None:
        try:
            while self._running.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self._running.clear()
            shutdown_outbound_task_pool()


class Worker:
    def __init__(
        self,
        bot: dict,
        *,
        role: str = "HYBRID",
        brain: Brain | None = None,
    ):
        self.bot = bot
        self.role = role
        self.brain = brain
        self.seen_ids: set[str] = set()
        self._baseline_cmds: set[tuple[str, str, int]] = set()
        self._handled_cmd_y: dict[tuple[str, str], int] = {}
        self._tick_idle = True
        self._last_full_tick_at = 0.0
        self.ready = False
        self.last_draft = ""
        self.in_group = False

    def _listener_no_click(self) -> bool:
        return (
            self.role == "LISTENER"
            and self.brain is not None
            and self.brain.has_clickers()
        )

    def _cmd_serial(self, serial: str) -> str | None:
        """Listener+Clicker 协同时：右机不执行任何点头像/导航类 ADB 操作。"""
        return None if self._listener_no_click() else serial

    def _enter_group_for_worker(
        self, serial: str, *, force: bool = False, reason: str = "worker-tick",
    ) -> bool:
        """Listener 双机：检测是否在群；离群时限流自动回群。"""
        if is_send_only_listener(self.bot):
            if in_target_group_chat(ui_hierarchy(serial), self.bot, serial):
                return True
            if not is_55m_foreground(serial):
                launch_messenger_app(serial)
            return try_recover_listener_to_group(
                serial, self.bot, reason=reason, force=force,
            )
        return ensure_group_chat(serial, self.bot)

    def _flush_brain_replies(
        self,
        serial: str,
        settings: dict[str, str],
        snap: UiSnapshot | None = None,
    ) -> bool:
        if not self.brain or self.role == "CLICKER":
            return False
        jobs = self.brain.drain_replies(self.bot["id"])
        if not jobs:
            return False
        if snap is None:
            snap = ui_snapshot(serial, chat=False)
        send_xy = resolve_listener_send_xy(self.bot, settings, snap)
        in_group = in_target_group_chat(snap.root, self.bot, serial)
        for job in jobs:
            reply = job.text if re.search(r"用户[：:]\[", job.text or "") else with_user_header(job.text, job.nick)
            enqueue_send(
                serial, self.bot, reply, settings,
                input_xy=snap.input_xy,
                send_xy=send_xy,
                group_ok=in_group,
                prio=SEND_PRIO_CMD,
            )
        return True

    def _process_probe_events(
        self,
        serial: str,
        users: list,
        products: list,
        combo_rules: list,
        settings: dict[str, str],
    ) -> bool:
        """无障碍探针事件：跳过 ROI 轮询，直接处理指令。"""
        if not PROBE_ENABLED or self.role != "LISTENER":
            return False
        events = drain_probe_events()
        if not events:
            return False
        snap = ui_snapshot(serial, chat=False)
        input_xy = snap.input_xy
        send_xy = resolve_listener_send_xy(self.bot, settings, snap)
        in_group = in_target_group_chat(snap.root, self.bot, serial)
        if not in_group:
            log.warning("探针事件到达但右机不在群聊，忽略")
            return False
        worked = False
        for ev in events:
            cmd = str(ev.get("command") or "").strip()
            sender = str(ev.get("sender") or "").strip()
            if not cmd:
                continue
            if sender and not is_plausible_sender(sender, settings, products, self.bot["id"]):
                continue
            if not try_claim_command(self.bot["id"], sender, cmd, 0):
                continue
            log.info("探针拦截 [%s] %s", sender or "?", cmd)
            if (
                self._listener_no_click()
                and command_needs_identity(cmd)
                and not resolve_panel_user(
                    self.bot["id"], sender, users, serial,
                    allow_profile_read=False, bot=self.bot,
                )
            ):
                mid = f"probe:{sender}:{cmd}"
                if self.brain.submit_resolve_cmd(self.bot["id"], sender, 0, mid, cmd):
                    worked = True
                continue
            reply = handle_command(
                cmd, self.bot, users, products, combo_rules, settings, sender,
                self._cmd_serial(serial), cache_serial=serial,
            )
            if not reply:
                continue
            reply = with_user_header(reply, sender)
            enqueue_send(
                serial, self.bot, reply, settings,
                input_xy=input_xy, send_xy=send_xy, group_ok=in_group,
                prio=SEND_PRIO_CMD,
            )
            post_log(f"[PROBE] 已回复: {reply[:100]}", "SUCCESS")
            worked = True
        return worked

    def tick(
        self,
        serial: str,
        users: list,
        products: list,
        combo_rules: list,
        settings: dict[str, str],
    ) -> bool:
        if is_send_bot(self.bot) and not clicker_announce_enabled():
            drain_capture_ipc_open_jobs(serial, self.bot)
        if self._process_probe_events(serial, users, products, combo_rules, settings):
            self._last_full_tick_at = time.time()
            return True
        force_scan = (
            self._last_full_tick_at <= 0
            or time.time() - self._last_full_tick_at >= LISTENER_FORCE_SCAN_SEC
        )
        if (
            is_send_only_listener(self.bot)
            and FAST_DETECT_ENABLED
            and self.brain
            and self.ready
            and self._tick_idle
            and not force_scan
            and not self.brain.has_pending_replies(self.bot["id"])
            and not probe_events_pending()
            and not outbound_pending_user_jobs(serial)
            and not chat_bottom_roi_changed(serial)
        ):
            return False

        if is_send_only_listener(self.bot):
            if LISTENER_TICK_HIDE_KB and not listener_send_protected(serial):
                listener_hide_keyboard(serial, reason="before-tick")

        snap = ui_snapshot(serial, channel="listener")
        self._last_full_tick_at = time.time()
        had_work = self._flush_brain_replies(serial, settings, snap)
        texts, input_xy, send_xy, draft = snap.texts, snap.input_xy, (
            snap.inbar_send or snap.keyboard_send
        ), snap.draft
        if not texts and not draft:
            ctx0 = describe_screen_context(snap.root, self.bot, serial)
            if ctx0.page == "target_group":
                self.in_group = True
            elif is_send_only_listener(self.bot):
                self.in_group = self._enter_group_for_worker(serial)
            elif self._enter_group_for_worker(serial):
                if describe_screen_context(snap.root, self.bot, serial).page == "target_group":
                    self.in_group = True
            return had_work
        ctx = describe_screen_context(snap.root, self.bot, serial)
        if is_send_only_listener(self.bot):
            if ctx.page != "target_group":
                pending = bool(texts or draft)
                recovered = False
                if ctx.page == "webview":
                    dismiss_in_app_webview(serial)
                    invalidate_ui_cache(serial)
                    snap = ui_snapshot(serial)
                    ctx = describe_screen_context(snap.root, self.bot, serial)
                    recovered = ctx.page == "target_group"
                elif not LISTENER_ZERO_NAV:
                    recovered = self._enter_group_for_worker(
                        serial, force=pending, reason="worker-tick-pending" if pending else "worker-tick",
                    )
                    if not recovered and pending:
                        recovered = self._enter_group_for_worker(
                            serial, force=True, reason="worker-tick-force",
                        )
                if recovered:
                    invalidate_ui_cache(serial)
                    snap = ui_snapshot(serial)
                    texts, input_xy, send_xy, draft = snap.texts, snap.input_xy, (
                        resolve_listener_send_xy(self.bot, settings, snap)
                    ), snap.draft
                    ctx = describe_screen_context(snap.root, self.bot, serial)
                if ctx.page != "target_group":
                    if pending:
                        log.warning(
                            "右机不在群但有待处理内容 page=%s group=%s",
                            ctx.summary(), self.bot.get("associatedGroup"),
                        )
                    else:
                        log.info("右机仅发送：当前 %s，请手动停留在目标群", ctx.summary())
                    self.in_group = False
                    return had_work
        elif ctx.page == "search":
            dismiss_search_page(serial)
            invalidate_ui_cache(serial)
            snap = ui_snapshot(serial)
            ctx = describe_screen_context(snap.root, self.bot, serial)
        elif ctx.page == "secret_key":
            dismiss_secret_key_page(serial)
            invalidate_ui_cache(serial)
            snap = ui_snapshot(serial)
            ctx = describe_screen_context(snap.root, self.bot, serial)
        elif ctx.page == "webview":
            log.warning("右机在内嵌开奖页，系统返回")
            dismiss_in_app_webview(serial)
            invalidate_ui_cache(serial)
            snap = ui_snapshot(serial)
            texts, input_xy, send_xy, draft = snap.texts, snap.input_xy, (
                snap.inbar_send or snap.keyboard_send
            ), snap.draft
            ctx = describe_screen_context(snap.root, self.bot, serial)
        if not is_send_only_listener(self.bot) and ctx.page != "target_group":
            log.info("屏幕定位 %s", ctx.summary())
        in_group = ctx.page == "target_group"
        if not in_group:
            pending = bool(texts or draft)
            force = pending and is_send_only_listener(self.bot) and not LISTENER_ZERO_NAV
            if force and self._enter_group_for_worker(
                serial, force=force, reason="worker-enter-pending" if force else "worker-enter",
            ):
                invalidate_ui_cache(serial)
                snap = ui_snapshot(serial)
                texts = snap.texts
                input_xy = snap.input_xy
                send_xy = snap.inbar_send or snap.keyboard_send
                draft = snap.draft
                ctx = describe_screen_context(snap.root, self.bot, serial)
                in_group = ctx.page == "target_group"
            elif force and self._enter_group_for_worker(serial, force=True, reason="worker-enter-force"):
                invalidate_ui_cache(serial)
                snap = ui_snapshot(serial)
                texts = snap.texts
                input_xy = snap.input_xy
                send_xy = snap.inbar_send or snap.keyboard_send
                draft = snap.draft
                ctx = describe_screen_context(snap.root, self.bot, serial)
                in_group = ctx.page == "target_group"
            else:
                self.in_group = False
                return had_work
        self.in_group = in_group
        self._tick_idle = False
        hint = chat_partner(texts, users, self.bot["id"], self.bot)

        if draft and draft != self.last_draft and is_command(draft, settings, products, self.bot["id"]):
            can_bind = bool(BIND_RE.match(draft.strip()))
            log.info("拦截[输入框] [%s]: %s", self.bot.get("botName"), draft)
            post_log(f"[ADB] 输入框拦截: {draft}", "INFO")
            reply = handle_command(
                draft, self.bot, users, products, combo_rules, settings, hint,
                self._cmd_serial(serial), cache_serial=serial,
            )
            if reply:
                reply = with_user_header(reply, hint)
                enqueue_send(
                    serial, self.bot, reply, settings,
                    input_xy=input_xy, send_xy=send_xy, group_ok=in_group,
                )
                post_log(f"[ADB] 已回复: {reply[:100]}", "SUCCESS")
                had_work = True
            elif not can_bind and not needs_registration_reply(draft.strip()):
                log.info("忽略非指令输入 partner=%s: %s", hint or "?", draft)
            self.last_draft = draft
        elif not draft:
            self.last_draft = ""

        if is_send_only_listener(self.bot) and in_group:
            if not self.ready or chat_scan_needs_scroll(snap):
                listener_refresh_chat_view(
                    serial, reason="baseline" if not self.ready else "sparse",
                )
                snap = ui_snapshot(serial, force=True)
                texts, input_xy, send_xy, draft = snap.texts, snap.input_xy, (
                    snap.inbar_send or snap.keyboard_send
                ), snap.draft
            if expand_unread_chat_messages(serial, snap.root):
                snap = ui_snapshot(serial, force=True)
                texts, input_xy, send_xy, draft = snap.texts, snap.input_xy, (
                    snap.inbar_send or snap.keyboard_send
                ), snap.draft
                log.info(
                    "未读展开后 nodes=%d texts=%d",
                    len(snap.chat_nodes), len(snap.texts),
                )

        msgs = chat_message_ids(
            snap.chat_nodes, snap.texts, settings, products, self.bot["id"], users,
        )
        if not self.ready:
            for mid, cmd, sender, _, cmd_y in msgs:
                c = cmd.strip()
                snd = (sender or "").strip()
                if ADD_FINANCE_RE.match(c):
                    continue
                if snd and cmd_y > 0 and c:
                    self._baseline_cmds.add(cmd_baseline_key(c, snd, cmd_y))
                    record_handled_cmd_y(self._handled_cmd_y, c, snd, cmd_y)
                self.seen_ids.add(mid)
            self.ready = True
            if not self._listener_no_click():
                schedule_batch_prewarm(serial, self.bot["id"], users, texts)
            log.info("基线 %s 已忽略 %d 条 | %s", hint or "?", len(self.seen_ids), ctx.summary())
            return had_work

        pending = [
            (mid, cmd, sender, idx, cmd_y)
            for mid, cmd, sender, idx, cmd_y in msgs
            if mid not in self.seen_ids
        ]
        queue = fair_queue_pending(pending, hint)
        if not queue and not pending:
            self._tick_idle = True
        if not self._listener_no_click() and self.role != "LISTENER":
            if not queue and not pending:
                batch_prewarm_step(serial, self.bot["id"], users, self.bot)

        cmd_serial = self._cmd_serial(serial)
        processed_cmds = 0

        for mid, cmd, sender, _idx, cmd_y in queue:
            snd = (sender or "").strip()
            self.seen_ids.add(mid)
            if cmd_y:
                _TAP_NEAR_Y[serial] = cmd_y
            is_bind = bool(BIND_RE.match(cmd.strip()))
            is_add = bool(ADD_FINANCE_RE.match(cmd.strip()))
            if not is_bind and not is_add:
                if cmd_y <= 0 and not is_query_command(cmd):
                    log.info("无坐标指令，跳过: %s partner=%s", cmd, hint or "?")
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                    continue
                if not snd:
                    log.info("无发送者，跳过: %s y=%s", cmd, cmd_y)
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                    continue
                if is_rescan_command(cmd, snd, cmd_y, self._handled_cmd_y, self._baseline_cmds):
                    log.info("历史指令，跳过 [%s] %s y=%s", snd, cmd, cmd_y)
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                    continue
            elif is_add and not snd:
                log.info("添加：无法识别发送者")
                break
            if is_bind and not snd:
                log.info("绑定命令无法识别发送者: %s", cmd)
                break
            if snd and not is_plausible_sender(snd, settings, products, self.bot["id"]):
                log.info("无效发送者，跳过: %s cmd=%s | %s", snd, cmd, ctx.summary())
                mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                continue
            if self.brain and self.brain.is_resolve_active(self.bot["id"], snd, cmd, cmd_y):
                log.info("认人进行中，跳过 [%s] %s @ %s", snd, cmd, mid)
                mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                continue
            if not try_claim_command(self.bot["id"], snd, cmd, cmd_y or 0):
                log.info("重复指令跳过 [%s] %s @ %s", snd, cmd, mid)
                mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                continue
            had_work = True
            log.info(
                "公平队列 [%s]: %s @ %s sender=%s y=%s | %s",
                self.bot.get("botName"), cmd, mid, snd, cmd_y, ctx.summary(),
            )
            post_log(f"[ADB] 拦截: {cmd} ({ctx.page})", "INFO")

            if is_add:
                if not snd:
                    break
                if self._listener_no_click():
                    if self.brain.submit_add_finance(self.bot["id"], snd, cmd_y or 0, mid):
                        log.info("添加已委派 Clicker ← %s y=%s", snd, cmd_y)
                        mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                        set_reply_cooldown(self.bot["id"], snd, cmd)
                    else:
                        reply = user_reply(snd, ADD_FINANCE_FAIL_REPLY)
                        enqueue_send(
                            serial, self.bot, reply, settings,
                            input_xy=input_xy, send_xy=send_xy, group_ok=in_group,
                        )
                        mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                        set_reply_cooldown(self.bot["id"], snd, cmd)
                    break
                log.info("添加流程触发 ← %s y=%s", snd, cmd_y)
                result = send_friend_add_request(serial, self.bot, snd, cmd_y or None, settings)
                if result in ("ok", "already"):
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                    set_reply_cooldown(self.bot["id"], snd, cmd)
                else:
                    reply = user_reply(snd, ADD_FINANCE_FAIL_REPLY)
                    enqueue_send(
                        serial, self.bot, reply, settings,
                        input_xy=input_xy, send_xy=send_xy, group_ok=in_group,
                    )
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                    set_reply_cooldown(self.bot["id"], snd, cmd)
                break

            if is_bind and self._listener_no_click():
                if self.brain.submit_bind(self.bot["id"], snd, cmd, cmd_y or 0, mid):
                    log.info("绑定已委派 Clicker ← %s %s", snd, cmd)
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                else:
                    self.seen_ids.discard(mid)
                break

            if (
                self._listener_no_click()
                and command_needs_identity(cmd)
                and not resolve_panel_user(
                    self.bot["id"], snd, users, serial,
                    allow_profile_read=False,
                    bot=self.bot,
                )
            ):
                gw = listener_gateway_resolve(serial, self.bot["id"], snd, cmd)
                if gw == "hit":
                    reply = handle_command(
                        cmd, self.bot, users, products, combo_rules, settings, snd,
                        cmd_serial, cache_serial=serial,
                    )
                    if reply:
                        mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                        if cmd_y > 0 and snd:
                            record_handled_cmd_y(self._handled_cmd_y, cmd, snd, cmd_y)
                        reply = with_user_header(reply, snd)
                        enqueue_send(
                            serial, self.bot, reply, settings,
                            input_xy=input_xy, send_xy=send_xy, group_ok=self.in_group,
                        )
                        post_log(f"[ADB] 已回复(网关缓存): {reply[:100]}", "SUCCESS")
                    else:
                        mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                    break
                if self.brain.submit_resolve_cmd(self.bot["id"], snd, cmd_y or 0, mid, cmd):
                    log.info("认人+指令已委派 Clicker ← [%s] %s y=%s gw=%s", snd, cmd, cmd_y, gw)
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                else:
                    log.warning("Clicker 不可用，无法认人: [%s] %s", snd, cmd)
                    mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                break

            reply = handle_command(
                cmd, self.bot, users, products, combo_rules, settings, snd,
                cmd_serial, cache_serial=serial,
            )
            if not reply:
                if not is_bind and not ADD_FINANCE_RE.match(cmd.strip()):
                    if needs_registration_reply(cmd):
                        log.info("未登记用户指令 %s: %s @ %s", snd or "?", cmd, mid)
                    else:
                        log.info("忽略非指令 %s: %s @ %s", snd or "?", cmd, mid)
                mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
                if not self._listener_no_click():
                    ensure_group_chat(serial, self.bot)
                continue
            mark_cmds_seen(self.seen_ids, msgs, cmd, snd, hint)
            if cmd_y > 0 and snd:
                record_handled_cmd_y(self._handled_cmd_y, cmd, snd, cmd_y)
            if not self.in_group and not self._listener_no_click():
                ensure_group_chat(serial, self.bot)
            reply = with_user_header(reply, snd)
            enqueue_send(
                serial, self.bot, reply, settings,
                input_xy=input_xy, send_xy=send_xy, group_ok=self.in_group,
            )
            post_log(f"[ADB] 已回复: {reply[:100]}", "SUCCESS")
            if not FAST:
                w(0.6, 0.1)
            had_work = True
            processed_cmds += 1
            if processed_cmds >= LISTENER_CMDS_PER_TICK:
                break
            continue

        return had_work

        # topup 已移至 brain-refresh 线程


def benchmark_ui(serial: str, rounds: int = 5) -> dict[str, Any]:
    """压测 UI 读取速度（ms）"""
    results: dict[str, list[int]] = {"cached": [], "cold_u2": [], "cold_adb": [], "roi": [], "screencap": []}
    invalidate_ui_cache(serial)
    invalidate_roi_cache(serial)
    for _ in range(rounds):
        t0 = time.perf_counter()
        ui_hierarchy(serial, force=True)
        results["cold_adb" if not _HAS_U2 else "cold_u2"].append(int((time.perf_counter() - t0) * 1000))
    for _ in range(rounds):
        t0 = time.perf_counter()
        ui_hierarchy(serial)
        results["cached"].append(int((time.perf_counter() - t0) * 1000))
    if FAST_DETECT_ENABLED:
        for _ in range(max(3, rounds)):
            t0 = time.perf_counter()
            chat_bottom_roi_changed(serial)
            results["roi"].append(int((time.perf_counter() - t0) * 1000))
        for _ in range(3):
            t0 = time.perf_counter()
            adb_screencap_png(serial)
            results["screencap"].append(int((time.perf_counter() - t0) * 1000))
    def stat(xs: list[int]) -> dict[str, int]:
        if not xs:
            return {"min": 0, "avg": 0, "max": 0}
        return {"min": min(xs), "avg": int(sum(xs) / len(xs)), "max": max(xs)}
    return {
        "serial": serial,
        "engine": "u2" if _HAS_U2 and _U2_DEVICES.get(serial) else "adb",
        "fast": FAST,
        "fast_detect": FAST_DETECT_ENABLED,
        "cv2": _HAS_CV2,
        "roi_engine": "cv2" if _HAS_CV2 else "raw",
        "listener_send_mode": LISTENER_SEND_MODE,
        "cache_ttl_ms": int(UI_CACHE_TTL * 1000),
        "tick_min_ms": int(TICK_MIN_SEC * 1000),
        "stats": {k: stat(v) for k, v in results.items() if v},
    }


def active_messenger_bots(bots: list[dict]) -> list[dict]:
    return [
        b for b in bots
        if b.get("status") == "ACTIVE"
        and b.get("platform") == "55Messenger"
        and str(b.get("id") or "") not in SKIP_BOT_IDS
    ]


def acquire_singleton_lock() -> None:
    """禁止多实例同时跑，避免同一条消息被回复多次。"""
    global _LOCK_FP
    os.makedirs(os.path.dirname(BOT_LOCK_FILE) or ".", exist_ok=True)
    fp = open(BOT_LOCK_FILE, "w", encoding="utf-8")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("已有 bot 守护进程在运行（%s），本进程退出", BOT_LOCK_FILE)
        sys.exit(0)
    fp.write(str(os.getpid()))
    fp.flush()
    _LOCK_FP = fp


def main_legacy() -> None:
    load_mid_cache()
    log.info("启动(legacy) API=%s ADB=%s FAST=%s", API_BASE, DEFAULT_ADB, FAST)
    workers: dict[str, Worker] = {}
    last_adb_err = ""
    last_adb_log = 0.0

    while True:
        try:
            bots = api("GET", "/api/bots")
            users = api("GET", "/api/users")
            products = api("GET", "/api/products")
            combo_rules = api("GET", "/api/combo-rules")
            settings = merge_settings(api("GET", "/api/settings"))
            active = active_messenger_bots(bots)
            if not active:
                log.warning("等待 55Messenger bot ACTIVE...")
                time.sleep(5)
                continue

            for bot in active:
                host = bot.get("adbHost") or DEFAULT_ADB
                serial = resolve_serial(host)
                last_adb_err = ""
                if bot["id"] not in workers:
                    workers[bot["id"]] = Worker(bot)
                    log.info("监听 %s @ %s", bot.get("botName"), serial)
                workers[bot["id"]].tick(serial, users, products, combo_rules, settings)
                default_ms = 80 if FAST else 200
                interval = max(TICK_MIN_SEC, int(bot.get("ocrIntervalMs") or default_ms) / 1000)
                w(interval, interval)

        except urllib.error.URLError as e:
            log.error("API: %s", e)
            time.sleep(4)
        except RuntimeError as e:
            msg = str(e)
            now = time.time()
            if msg != last_adb_err or now - last_adb_log > 45:
                log.error("%s", msg.replace("\n", " | "))
                last_adb_err = msg
                last_adb_log = now
            time.sleep(8)
        except KeyboardInterrupt:
            break
        except Exception:
            log.exception("异常")
            time.sleep(3)


def main() -> None:
    acquire_singleton_lock()
    load_mid_cache()
    load_round_bets_persisted()
    global _MAINT_WAS_ACTIVE
    _MAINT_WAS_ACTIVE = in_maintenance_window()
    if not ORCHESTRATOR:
        main_legacy()
        return
    log.info(
        "启动(大脑编排) API=%s FAST=%s LISTENER=%s CLICKER=%s BOT_ROLE=%s GATEWAY=%s tick=%.0fms "
        "ROI=%s CV2=%s SEND=%s PRIO=1",
        API_BASE, FAST, BOT_LISTENER_ID, ",".join(sorted(CLICKER_BOT_IDS)),
        BOT_ROLE or "-", GATEWAY_ENABLED,
        LISTENER_TICK_SEC * 1000,
        FAST_DETECT_ENABLED, _HAS_CV2,
        LISTENER_SEND_MODE if LISTENER_FAST_SEND else "off",
    )
    orch = Orchestrator()
    while True:
        try:
            bots = api("GET", "/api/bots")
            active = active_messenger_bots(bots)
            if not active:
                log.warning("等待 55Messenger bot ACTIVE...")
                time.sleep(5)
                continue
            if not orch._threads:
                orch.start(active)
            orch.join_forever()
        except urllib.error.URLError as e:
            log.error("API: %s", e)
            time.sleep(4)
        except KeyboardInterrupt:
            break
        except Exception:
            log.exception("编排异常")
            time.sleep(3)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--bench":
        host = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ADB
        serial = resolve_serial(host)
        print(json.dumps(benchmark_ui(serial), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--ime-bench":
        host = sys.argv[2] if len(sys.argv) > 2 else f"127.0.0.1:{_LISTENER_ADB_PORT}"
        serial = resolve_serial(host)
        print(json.dumps(benchmark_ime_send(serial), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--recover-group":
        host = sys.argv[2] if len(sys.argv) > 2 else f"127.0.0.1:{_LISTENER_ADB_PORT}"
        serial = resolve_serial(host)
        os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
        ok = recover_listener_to_group(serial)
        print("recover", "ok" if ok else "fail")
        sys.exit(0 if ok else 1)
    elif len(sys.argv) > 1 and sys.argv[1] == "--probe-test":
        host = sys.argv[2] if len(sys.argv) > 2 else f"127.0.0.1:{_LISTENER_ADB_PORT}"
        serial = resolve_serial(host)
        start_probe_server()
        setup_probe_adb_reverse(serial)
        payload = json.dumps({"sender": "probe_test", "command": "1", "ts": int(time.time() * 1000)})
        req = urllib.request.Request(
            f"http://127.0.0.1:{PROBE_PORT}/event",
            data=payload.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            print("probe_http", resp.read().decode())
        time.sleep(0.3)
        print("queue", drain_probe_events())
    elif len(sys.argv) > 1 and sys.argv[1] == "--test-ui-image":
        host = sys.argv[2] if len(sys.argv) > 2 else f"127.0.0.1:{_CLICKER_ADB_PORT}"
        serial = resolve_serial(host)
        os.environ["BOT_CLICKER_SEND_IMAGES"] = "1"
        os.environ.setdefault("BOT_IMG_SEND_MODE", "ui")
        os.environ["BOT_ALLOW_LISTENER_NAV"] = "1"
        bots = api("GET", "/api/bots")
        bot = next((b for b in bots if str(b.get("id")) in CLICKER_BOT_IDS), None)
        if not bot:
            print("no clicker bot")
            sys.exit(2)
        try:
            settings = api("GET", "/api/settings") or dict(DEFAULT_SETTINGS)
        except Exception:
            settings = dict(DEFAULT_SETTINGS)
        snap = ui_snapshot(serial, chat=True)
        ix, sy = snap.input_xy, snap.inbar_send or snap.keyboard_send
        test_png = "/tmp/bot_ui_image_test.png"
        try:
            from PIL import Image
            Image.new("RGB", (64, 64), (220, 40, 40)).save(test_png)
        except Exception:
            import base64
            raw = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M9Qz0AEYBxVSF+F"
                "AAh8Aaj+l2NYAAAAAElFTkSuQmCC"
            )
            with open(test_png, "wb") as f:
                f.write(raw)
        if in_target_group_chat(ui_hierarchy(serial), bot, serial):
            print("already in group")
        elif "GroupChatActivity" in adb_run(serial, "shell", "dumpsys", "window", "displays"):
            print("already in group (activity)")
        elif not recover_listener_to_group_minimal(serial, bot):
            print("not in group")
            sys.exit(3)
        ok = send_chat_images_batch(serial, bot, [test_png], ix, sy, settings, group_ok=True)
        print("test_ui_image", "ok" if ok else "fail")
        sys.exit(0 if ok else 1)
    else:
        main()
