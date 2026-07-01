"""VMOS ADB credential expiry — parse EXPIRE_TIME and schedule proactive refresh."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .env_io import load_env_file

BJ = ZoneInfo("Asia/Shanghai")

_EXPIRE_PATTERNS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
)


def adb_expire_minutes() -> int:
    raw = os.environ.get("BOT_VMOS_ADB_EXPIRE_MINUTES", "10080")
    try:
        return max(1440, min(10080, int(raw)))
    except (TypeError, ValueError):
        return 10080


def refresh_buffer_minutes() -> int:
    """Refresh this many minutes before EXPIRE_TIME (default 2h)."""
    raw = os.environ.get("BOT_VMOS_REFRESH_BUFFER_MINUTES", "120")
    try:
        return max(15, min(1440, int(raw)))
    except (TypeError, ValueError):
        return 120


def _parse_hhmm(raw: str, default: tuple[int, int]) -> tuple[int, int]:
    s = (raw or "").strip()
    if not s or ":" not in s:
        return default
    parts = s.split(":", 1)
    try:
        return max(0, min(23, int(parts[0]))), max(0, min(59, int(parts[1])))
    except (TypeError, ValueError):
        return default


def maintenance_window_start_hhmm() -> tuple[int, int]:
    return _parse_hhmm(os.environ.get("BOT_VMOS_MAINTENANCE_START", "19:00"), (19, 0))


def maintenance_window_end_hhmm() -> tuple[int, int]:
    return _parse_hhmm(os.environ.get("BOT_VMOS_MAINTENANCE_END", "19:30"), (19, 30))


def maintenance_window_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Next maintenance window [start, end] in Beijing time."""
    now = (now or datetime.now(BJ)).astimezone(BJ)
    sh, sm = maintenance_window_start_hhmm()
    eh, em = maintenance_window_end_hhmm()
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    if now > end:
        start += timedelta(days=1)
        end += timedelta(days=1)
    return start, end


def in_maintenance_window(now: datetime | None = None) -> bool:
    now = (now or datetime.now(BJ)).astimezone(BJ)
    start, end = maintenance_window_bounds(now)
    return start <= now <= end


def next_maintenance_start(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(BJ)).astimezone(BJ)
    start, end = maintenance_window_bounds(now)
    if now < start:
        return start
    if now <= end:
        return now
    return start


def should_refresh_urgent(
    env: dict[str, str],
    *,
    now: datetime | None = None,
) -> bool:
    """True when creds cannot safely wait until the next 19:00 maintenance window."""
    buf = refresh_buffer_minutes()
    left = minutes_until_expire(env, now=now)
    if left is None:
        return True
    if left <= buf:
        return True
    exp = expire_at_from_env(env)
    if exp is None:
        return True
    nms = next_maintenance_start(now)
    return exp <= nms + timedelta(minutes=buf)


def _parse_ts(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{10,13}", s):
        ts = int(s[:10]) if len(s) >= 13 else int(s)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    for fmt in _EXPIRE_PATTERNS:
        try:
            dt = datetime.strptime(s[:19], fmt)
            return dt.replace(tzinfo=BJ)
        except ValueError:
            continue
    return None


def expire_at_from_env(env: dict[str, str]) -> datetime | None:
    exp = _parse_ts(env.get("EXPIRE_TIME") or "")
    if exp is not None:
        return exp
    issued = _parse_ts(env.get("ISSUED_AT") or "")
    if issued is None:
        return None
    mins = int(env.get("EXPIRE_MINUTES") or adb_expire_minutes())
    return issued + timedelta(minutes=mins)


def minutes_until_expire(env: dict[str, str], *, now: datetime | None = None) -> float | None:
    exp = expire_at_from_env(env)
    if exp is None:
        return None
    now = now or datetime.now(tz=exp.tzinfo or BJ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BJ)
    return (exp - now).total_seconds() / 60.0


def should_refresh_tunnel(
    env: dict[str, str],
    *,
    buffer_minutes: int | None = None,
    now: datetime | None = None,
) -> bool:
    """True when within buffer of expiry or EXPIRE_TIME missing/stale."""
    buf = refresh_buffer_minutes() if buffer_minutes is None else buffer_minutes
    left = minutes_until_expire(env, now=now)
    if left is None:
        return True
    return left <= buf


def refresh_recommended_at(env: dict[str, str], *, buffer_minutes: int | None = None) -> datetime | None:
    exp = expire_at_from_env(env)
    if exp is None:
        return None
    buf = refresh_buffer_minutes() if buffer_minutes is None else buffer_minutes
    return exp - timedelta(minutes=buf)


def format_expire_status(side: str, tunnel_file: Path, *, pad_code: str = "") -> dict[str, Any]:
    env = load_env_file(tunnel_file)
    exp = expire_at_from_env(env)
    left = minutes_until_expire(env)
    rec = refresh_recommended_at(env)
    return {
        "side": side,
        "pad_code": pad_code or env.get("PAD_CODE", ""),
        "tunnel_file": str(tunnel_file),
        "local_port": env.get("LOCAL_PORT", ""),
        "expire_time": env.get("EXPIRE_TIME", ""),
        "expire_at": exp.isoformat() if exp else None,
        "expire_at_beijing": exp.strftime("%Y-%m-%d %H:%M:%S %Z") if exp else None,
        "minutes_left": round(left, 1) if left is not None else None,
        "refresh_recommended_at_beijing": rec.strftime("%Y-%m-%d %H:%M:%S %Z") if rec else None,
        "should_refresh": should_refresh_tunnel(env),
        "expire_minutes_config": adb_expire_minutes(),
        "refresh_buffer_minutes": refresh_buffer_minutes(),
        "maintenance_window_beijing": (
            f"{maintenance_window_start_hhmm()[0]:02d}:{maintenance_window_start_hhmm()[1]:02d}"
            f"-{maintenance_window_end_hhmm()[0]:02d}:{maintenance_window_end_hhmm()[1]:02d}"
        ),
        "next_maintenance_beijing": next_maintenance_start().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "refresh_urgent": should_refresh_urgent(env),
    }


def print_expire_status_table(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(
            f"[{row['side']}] port={row['local_port']} "
            f"expire={row['expire_at_beijing'] or row['expire_time'] or 'unknown'} "
            f"left_min={row['minutes_left']} "
            f"refresh_at={row['refresh_recommended_at_beijing'] or '-'} "
            f"maintenance={row.get('maintenance_window_beijing', '-')} "
            f"next_maint={row.get('next_maintenance_beijing', '-')} "
            f"urgent={row.get('refresh_urgent', row['should_refresh'])} "
            f"should_refresh={row['should_refresh']}"
        )
