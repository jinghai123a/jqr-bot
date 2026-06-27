"""Shared health-check primitives for VPS / local watch."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable

RunFn = Callable[[str, int], str]


def env_map(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def adb_online(serial: str, run_fn: RunFn) -> bool:
    out = run_fn(f"adb -s {serial} get-state 2>/dev/null", 15)
    return "device" in out or out.strip() == "device"


def adb_port_online(adb_devices_output: str, port: str) -> bool:
    return any(
        port in line and re.search(r"\sdevice(?:\s|$)", line)
        for line in adb_devices_output.splitlines()
    )


def in_group_chat(serial: str, run_fn: RunFn, *, left: bool = False) -> bool:
    out = run_fn(
        f'adb -s {serial} shell "dumpsys window 2>/dev/null | grep mCurrentFocus | head -1"',
        25,
    )
    if "GroupChatActivity" in out:
        return True
    if left and any(
        k in out
        for k in (
            "GroupChatActivity",
            "ChannelMediaSelectActivity",
            "Gallery",
            "gallery",
            "Preview",
            "Crop",
            "PhotoPicker",
        )
    ):
        return True
    return False


def daemon_running(run_fn: RunFn) -> bool:
    out = run_fn("pgrep -af bot_55chat_daemon.py 2>/dev/null", 10)
    return "bot_55chat_daemon.py" in out


def log_ts(line: str) -> datetime | None:
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def recent_log_matches(
    log_text: str,
    pattern: str,
    *,
    minutes: int = 15,
    tail_only: int | None = None,
) -> list[tuple[datetime | None, str]]:
    lines = log_text.splitlines()
    if tail_only:
        lines = lines[-tail_only:]
    rx = re.compile(pattern)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    out: list[tuple[datetime | None, str]] = []
    for ln in lines:
        if not rx.search(ln):
            continue
        ts = log_ts(ln)
        if ts and ts < cutoff:
            continue
        out.append((ts, ln))
    return out
