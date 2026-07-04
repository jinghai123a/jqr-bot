"""期号与时间窗（210s 对齐）。"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

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


def current_round_close_ts_ms(settings: dict[str, str] | None = None) -> int:
    rid, interval, rem = round_timing(settings)
    close_in = max(0.0, rem - CLOSE_BEFORE_SEC)
    return int(time.time() * 1000) + int(close_in * 1000)


def build_timeline(settings: dict[str, str] | None = None) -> dict[str, Any]:
    rid, interval, rem = round_timing(settings)
    now_ms = int(time.time() * 1000)
    close_ms = now_ms + int(max(0.0, rem - CLOSE_BEFORE_SEC) * 1000)
    warn_ms = now_ms + int(max(0.0, rem - WARN_BEFORE_SEC) * 1000)
    next_close_ms = close_ms + int(interval * 1000)
    return {
        "rid": rid,
        "interval_sec": interval,
        "server_ts": now_ms,
        "windows": {
            "warn": [warn_ms, warn_ms + 5000],
            "close": [close_ms, close_ms + 5000],
            "draw_earliest": close_ms,
            "open_earliest": close_ms + 2000,
        },
        "open_rid": rid + 1,
    }
