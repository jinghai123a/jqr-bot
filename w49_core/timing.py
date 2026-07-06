"""期号与时间窗（210s 对齐，优先 28.run）。"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from w49_core.draw import fetch_28run_recent

BEIJING_TZ = timezone(timedelta(hours=8))
DEFAULT_ROUND_ANCHOR_PERIOD = int(os.environ.get("BOT_ROUND_ANCHOR_PERIOD", "3445908") or 3445908)
DEFAULT_ROUND_INTERVAL_SEC = int(os.environ.get("BOT_ROUND_INTERVAL_SEC", "210") or 210)
DEFAULT_ROUND_ANCHOR_BEIJING = os.environ.get(
    "BOT_ROUND_ANCHOR_BEIJING", "2026-06-17 05:17:30",
)
WARN_BEFORE_SEC = max(1, int(os.environ.get("BOT_WARN_ANNOUNCE_SEC", "70") or 70))
CLOSE_BEFORE_SEC = max(1, int(os.environ.get("BOT_CLOSE_ANNOUNCE_SEC", "15") or 15))


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def parse_beijing_dt(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING_TZ)


def round_timing(settings: dict[str, str] | None = None) -> tuple[int, int, float]:
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
    rem = interval - (elapsed % interval)
    return rid, interval, rem


def active_round_timing(settings: dict[str, str] | None = None) -> tuple[int, int, float]:
    """与 bot_55chat_daemon.active_round_timing 一致：优先 28.run。"""
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
                    rem = float(interval)
                return rid, interval, rem
            except (ValueError, TypeError):
                pass
        if rid > 0:
            _, _, rem = round_timing(cfg)
            return rid, interval, rem
    return round_timing(cfg)


def sync_anchor_from_28run() -> dict[str, str]:
    """从 28.run 最新开奖反推 panel 锚点（供 mock panel 展示）。"""
    data = fetch_28run_recent(force=True) or {}
    rows = data.get("recent_results") or []
    if not rows:
        return {}
    last = rows[-1]
    expect = int(last.get("expect", 0))
    opentime = str(last.get("opentime") or "")
    if expect <= 0 or not opentime:
        return {}
    return {
        "roundAnchorPeriod": str(expect),
        "roundAnchorBeijing": opentime,
        "roundIntervalSec": str(DEFAULT_ROUND_INTERVAL_SEC),
        "draw28_latest_rid": str(expect),
        "draw28_next_rid": str(int(data.get("next_prediction", {}).get("expect") or expect + 1)),
    }


def current_round_close_ts_ms(settings: dict[str, str] | None = None) -> int:
    rid, interval, rem = active_round_timing(settings)
    close_in = max(0.0, rem - CLOSE_BEFORE_SEC)
    return int(time.time() * 1000) + int(close_in * 1000)


def build_timeline(settings: dict[str, str] | None = None) -> dict[str, Any]:
    rid, interval, rem = active_round_timing(settings)
    now_ms = int(time.time() * 1000)
    close_ms = now_ms + int(max(0.0, rem - CLOSE_BEFORE_SEC) * 1000)
    warn_ms = now_ms + int(max(0.0, rem - WARN_BEFORE_SEC) * 1000)
    data = fetch_28run_recent()
    draw_latest = 0
    if data:
        rows = data.get("recent_results") or []
        if rows:
            try:
                draw_latest = int(rows[-1].get("expect", 0))
            except (TypeError, ValueError):
                draw_latest = 0
    return {
        "rid": rid,
        "interval_sec": interval,
        "remaining_sec": round(rem, 2),
        "draw_latest_rid": draw_latest,
        "server_ts": now_ms,
        "windows": {
            "warn": [warn_ms, warn_ms + 5000],
            "close": [close_ms, close_ms + 5000],
            "draw_earliest": close_ms,
            "open_earliest": close_ms + 2000,
        },
        "open_rid": rid + 1,
    }
