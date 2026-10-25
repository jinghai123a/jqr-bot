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
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import queue
from concurrent.futures import Future, ThreadPoolExecutor
from collections import Counter, deque, defaultdict
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from bot_backend import BackendApiTransport, fetch_user_bills as _fetch_user_bills_impl, record_bill as _record_bill_impl
import bot_probe

try:
    from board_capture import (
        patch_trade_flow_draw,
        render_mark6_board_png,
        render_pc28_board_png,
        render_trade_flow_png,
        upsert_board_rows,
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
_ACTIVE_ORCH: Any = None  # Orchestrator 实例（ingress IPC 用）
BOT_LISTENER_ID = os.environ.get("BOT_LISTENER_ID", "bot-4").strip()
CLICKER_BOT_IDS = {
    x.strip()
    for x in os.environ.get("BOT_CLICKER_IDS", "bot-3").split(",")
    if x.strip()
}
CLICKER_OPTIONAL = os.environ.get("BOT_CLICKER_OPTIONAL", "0").lower() in ("1", "true", "yes")
# 左机仅负责 UI 发图（+→图片→勾选→发送）；右机 LISTENER 仍发文字
CLICKER_SEND_IMAGES = os.environ.get("BOT_CLICKER_SEND_IMAGES", "0").lower() in ("1", "true", "yes")
# 左机驻留群聊：慢任务/发图全程在 55M 内完成，禁止系统 Back 退出 App
CLICKER_STAY_IN_CHAT = os.environ.get("BOT_CLICKER_STAY_IN_CHAT", "1").lower() in ("1", "true", "yes")
CLICKER_STAY_SEC = max(15.0, float(os.environ.get("BOT_CLICKER_STAY_SEC", "30") or 30))
CLICKER_FAST = os.environ.get("BOT_CLICKER_FAST", "1").lower() in ("1", "true", "yes")
# DEPLOY LOCK: 左机 CLICKER | 右机 LISTENER（端口见 env，云机重启后可能变）
_LISTENER_ADB_PORT = os.environ.get("BOT_LISTENER_ADB_PORT", "58433").strip()
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
GATEWAY_TIMEOUT_SEC = max(0.15, float(os.environ.get("BOT_GATEWAY_TIMEOUT_SEC", "0.2") or 0.2))
GATEWAY_WARM_SEC = max(3.0, float(os.environ.get("BOT_GATEWAY_WARM_SEC", "5") or 5))
PANEL_SEND_GATE = os.environ.get("BOT_PANEL_SEND_GATE", "1").lower() in ("1", "true", "yes")
PANEL_CHECK_TTL_SEC = max(0.5, float(os.environ.get("BOT_PANEL_CHECK_TTL_SEC", "1") or 1))
_PANEL_OK_UNTIL: float = 0.0
LOG_WORKER_THREADS = max(1, int(os.environ.get("BOT_LOG_WORKERS", "4") or 4))
_role_log = os.environ.get(f"BOT_{os.environ.get('BOT_ROLE', '').upper()}_LOG_WORKERS", "").strip()
if _role_log:
    LOG_WORKER_THREADS = max(1, int(_role_log))
# 公告/回复并发：有界线程池上限（后续 Hook / 剪贴板快发任务统一入口）
OUTBOUND_POOL_MAX = max(1, min(10, int(os.environ.get("BOT_OUTBOUND_POOL_MAX", "10") or 10)))
_role_pool = os.environ.get(f"BOT_{os.environ.get('BOT_ROLE', '').upper()}_OUTBOUND_POOL_MAX", "").strip()
if _role_pool:
    OUTBOUND_POOL_MAX = max(1, min(10, int(_role_pool or OUTBOUND_POOL_MAX)))
CONTEXT_REFRESH_SEC = max(1.0, float(os.environ.get("BOT_CONTEXT_REFRESH_SEC", "1") or 1))
CLICKER_CONTEXT_REFRESH_SEC = max(
    CONTEXT_REFRESH_SEC,
    float(os.environ.get("BOT_CLICKER_CONTEXT_REFRESH_SEC", "10") or 10),
)
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
CLICKER_ZERO_NAV = os.environ.get("BOT_CLICKER_ZERO_NAV", "1").lower() in ("1", "true", "yes")
# 右机读屏/空闲时强制收起键盘，避免 Gboard 遮挡气泡导致认不到指令
LISTENER_HIDE_KEYBOARD = os.environ.get("BOT_LISTENER_HIDE_KEYBOARD", "0").lower() in (
    "1", "true", "yes",
)
# 右机 b64 后：灌字完成即点钉死发送键，不做多轮 dump 等箭头
LISTENER_BLUE_SEND_POLLS = max(
    1, min(40, int(os.environ.get("BOT_LISTENER_BLUE_SEND_POLLS", "20") or 20)),
)
# 封盘/公告 UI 验发硬截止（毫秒）；超时走 trust-fallback，禁止阻塞 sender 队列
LISTENER_ANNOUNCE_VERIFY_MAX_MS = max(
    500, min(5000, int(os.environ.get("BOT_LISTENER_ANNOUNCE_VERIFY_MAX_MS", "2000") or 2000)),
)
LISTENER_ANNOUNCE_TRUST_FALLBACK = os.environ.get("BOT_LISTENER_ANNOUNCE_TRUST_FALLBACK", "1").lower() in (
    "1", "true", "yes",
)
LISTENER_SEND_FIRE = os.environ.get("BOT_LISTENER_SEND_FIRE", "1").lower() in (
    "1", "true", "yes",
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
CLICK_VERIFY = os.environ.get("BOT_CLICK_VERIFY", "1").lower() in ("1", "true", "yes")
# W49：55M 自定义 UI 导致 uiautomator 验证不可靠，信任钉死坐标点击，跳过验证
IMG_TRUST_CLICK = os.environ.get("BOT_IMG_TRUST_CLICK", "1").lower() in ("1", "true", "yes")
# 左机发图：钉死 04:16 成功坐标序，跳过读屏/grid 漂移
IMG_LOCKED = os.environ.get("BOT_IMG_LOCKED", "1").lower() in ("1", "true", "yes")
# 左机发图快路径：缩短 push/勾选/发送等待（亚秒级链）
IMG_FAST = os.environ.get("BOT_IMG_FAST", "1").lower() in ("1", "true", "yes")
IMG_CHECK_W_SEC = max(0.06, float(os.environ.get("BOT_IMG_CHECK_W_SEC", "0.10") or 0.10))
IMG_SEND_W_SEC = max(0.12, float(os.environ.get("BOT_IMG_SEND_W_SEC", "0.22") or 0.22))
IMG_ATTACH_W_SEC = max(0.20, float(os.environ.get("BOT_IMG_ATTACH_W_SEC", "0.32") or 0.32))
CLICK_VERIFY_TRIES = max(1, int(os.environ.get("BOT_CLICK_VERIFY_TRIES", "3") or 3))
# §3.2 顶行三圈钉死兜底（与 config/pinned-coords.json 一致，04:16 实弹序）
_GALLERY_CHECK_TOP3_FALLBACK: tuple[tuple[int, int], ...] = (
    (654, 374),
    (429, 374),
    (205, 374),
)
GALLERY_PUSH_SETTLE_SEC = max(0.15, float(os.environ.get("BOT_GALLERY_PUSH_SETTLE_SEC", "0.28") or 0.28))
GALLERY_OPEN_RETRIES = max(1, int(os.environ.get("BOT_GALLERY_OPEN_RETRIES", "3") or 3))
# W49 截图：点 + 后附件栏应出现的锚点（至少命中「图片」）
ATTACH_MENU_MARKERS = ("图片", "拍摄", "名片", "文件", "红包", "群聊转账")
CLICKER_TAP_MS = max(40, int(os.environ.get("BOT_CLICKER_TAP_MS", "80") or 80))
# 左机发图流程内仅允许 purpose=clicker-pinned-* 的钉死坐标 tap（禁止聊天区/u2 乱点）
CLICKER_IMG_TAP_ONLY = os.environ.get("BOT_CLICKER_IMG_TAP_ONLY", "1").lower() in ("1", "true", "yes")
CLICKER_IMG_TAP_TOL = max(24, int(os.environ.get("BOT_CLICKER_IMG_TAP_TOL", "52") or 52))
_CLICKER_IMG_FLOW_SERIALS: set[str] = set()
_CLICKER_IMG_FLOW_SINCE: dict[str, float] = {}
_CLICKER_ATTACH_IME_RESTORE: dict[str, str] = {}
_CLICKER_ATTACH_IME_DISABLED: dict[str, list[str]] = {}
GALLERY_PURGE_INTERVAL_SEC = max(60, int(os.environ.get("BOT_GALLERY_PURGE_SEC", "3600") or 3600))
CLICKER_IMG_FLOW_MAX_SEC = max(45, int(os.environ.get("BOT_CLICKER_IMG_FLOW_MAX_SEC", "120") or 120))
_GALLERY_LAST_PURGE: dict[str, float] = {}


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


def _clicker_settle_pinned_pair() -> tuple[tuple[int, int], tuple[int, int]]:
    """结算发图：零读屏钉死 + / 批量发送坐标。"""
    ix = pinned_xy("clicker", "chat_plus") or (45, 1235)
    sy = pinned_xy("clicker", "gallery_batch_send") or (668, 1210)
    return ix, sy


def _settle_capture_fast(gallery_preloaded: bool, settle_rid: int, serial: str) -> bool:
    return (
        gallery_preloaded
        and settle_rid > 0
        and IMG_LOCKED
        and is_clicker_serial(serial)
    )


def _settle_cloud_no_audit(serial: str) -> bool:
    """铁律4：结算发图云机只 tap，不做 uiautomator/OCR 审核。"""
    return IMG_LOCKED and IMG_TRUST_CLICK and is_clicker_serial(serial)


def clicker_w(fast_sec: float = 0.12, slow_sec: float = 0.35) -> None:
    """左机点击间隔（亚秒）。"""
    w(CLICKER_TAP_MS / 1000.0 if CLICKER_FAST else fast_sec, slow_sec)


def clicker_img_w(fast_sec: float | None = None, slow_sec: float | None = None) -> None:
    """左机发图链专用等待（IMG_FAST 时更短）。"""
    if IMG_FAST:
        fs = IMG_CHECK_W_SEC if fast_sec is None else fast_sec
        ss = (IMG_CHECK_W_SEC + 0.08) if slow_sec is None else slow_sec
        w(fs, ss)
    else:
        clicker_w(0.28 if fast_sec is None else fast_sec, 0.18 if slow_sec is None else slow_sec)


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
LISTENER_STAY_IN_GROUP = os.environ.get("BOT_LISTENER_STAY_IN_GROUP", "0").lower() in ("1", "true", "yes")
LISTENER_AUTO_RECOVER = os.environ.get("BOT_LISTENER_AUTO_RECOVER", "0").lower() in ("1", "true", "yes")
LISTENER_STAY_LOOP = os.environ.get("BOT_LISTENER_STAY_LOOP", "0").lower() in ("1", "true", "yes")
LISTENER_WEBVIEW_AUTO_BACK = os.environ.get("BOT_LISTENER_WEBVIEW_AUTO_BACK", "0").lower() in (
    "1", "true", "yes",
)
LISTENER_STAY_RECOVER_SEC = max(3, int(os.environ.get("BOT_LISTENER_STAY_RECOVER_SEC", "5") or 5))
LISTENER_CHAT_SCROLL_SEC = max(0.8, float(os.environ.get("BOT_LISTENER_CHAT_SCROLL_SEC", "2") or 2))
_LISTENER_LAST_CHAT_SCROLL: dict[str, float] = {}
_LISTENER_LAST_GROUP_TAP: dict[str, float] = {}
LISTENER_GROUP_TAP_SEC = max(8.0, float(os.environ.get("BOT_LISTENER_GROUP_TAP_SEC", "12") or 12))
_LISTENER_LAST_RECOVER: dict[str, float] = {}
_LISTENER_RECOVER_LOCK = threading.Lock()
_LISTENER_RECOVER_OK_TS: dict[str, float] = {}
LISTENER_RECOVER_HOLD_SEC = max(15.0, float(os.environ.get("BOT_LISTENER_RECOVER_HOLD_SEC", "25") or 25))
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
        )
        th.daemon = True
        _LISTENER_FIRE_THREADS[serial] = th
        th.start()

