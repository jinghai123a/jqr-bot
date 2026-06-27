#!/usr/bin/env python3
"""VPS 双机轻量巡检：ADB/在群/daemon；异常自动拉隧道或重启。勿与发图探针并发。"""
from __future__ import annotations

import fcntl
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/bot/55chat-bot")
LOG = ROOT / "logs" / "cloud-watch.log"
BOT_LOG = ROOT / "logs" / "bot.log"
LOCK = Path("/tmp/cloud_dual_watch.lock")
RIGHT = "127.0.0.1:60478"
LEFT = "localhost:56121"
RESTART = ROOT / "scripts" / "restart-55chat-bot.sh"
TUN_L = ROOT / "scripts" / "tunnel-left.sh"
TUN_R = ROOT / "scripts" / "tunnel-right.sh"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{ts()}] {msg}\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")


def sh(cmd: str, t: int = 90) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def adb_ok(serial: str) -> bool:
    out = sh(f"adb -s {serial} get-state 2>/dev/null", 15)
    return "device" in out or out.strip() == "device"


def in_group(serial: str) -> bool:
    out = sh(
        f'adb -s {serial} shell "dumpsys window 2>/dev/null | grep mCurrentFocus | head -1"',
        25,
    )
    if "GroupChatActivity" in out:
        return True
    # 发图中途：相册/媒体选择/预览
    if serial == LEFT and any(
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


def daemon_running() -> bool:
    out = sh("pgrep -af bot_55chat_daemon.py 2>/dev/null", 10)
    return "bot_55chat_daemon.py" in out


def recent_bot_errors() -> list[str]:
    if not BOT_LOG.is_file():
        return []
    try:
        raw = BOT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return []
    bad: list[str] = []
    for ln in raw[-80:]:
        if "ERROR" in ln or (
            "WARNING" in ln
            and any(
                k in ln
                for k in (
                    "不在目标群",
                    "批量发图失败",
                    "UI 发图失败",
                    "ADB offline",
                    "tunnel",
                )
            )
        ):
            bad.append(ln[-160:])
    return bad[-5:]


def heal(group_l: bool, group_r: bool) -> list[str]:
    actions: list[str] = []
    if not adb_ok(LEFT) and TUN_L.is_file():
        log("HEAL: 左机 ADB 离线 → tunnel-left")
        sh(f"bash {TUN_L}", 120)
        actions.append("tunnel-left")
    if not adb_ok(RIGHT) and TUN_R.is_file():
        log("HEAL: 右机 ADB 离线 → tunnel-right")
        sh(f"bash {TUN_R}", 120)
        actions.append("tunnel-right")
    if not daemon_running() and RESTART.is_file():
        log("HEAL: daemon 不在 → restart-55chat-bot")
        sh(f"bash {RESTART}", 150)
        actions.append("restart-daemon")
    if (not group_l or not group_r) and (ROOT / "scripts" / "_watch_heal_left_group.py").is_file():
        log("HEAL: 不在群 → ensure_clicker_in_group")
        sh(f"python3 {ROOT}/scripts/_watch_heal_left_group.py", 120)
        actions.append("ensure-group")
    return actions


def main() -> int:
    lock_fd = os.open(str(LOCK), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("skip: another watch running")
        return 0

    ok_adb_l = adb_ok(LEFT)
    ok_adb_r = adb_ok(RIGHT)
    ok_d = daemon_running()
    ok_grp_l = in_group(LEFT) if ok_adb_l else False
    ok_grp_r = in_group(RIGHT) if ok_adb_r else False
    errs = recent_bot_errors()

    healthy = ok_adb_l and ok_adb_r and ok_d and ok_grp_l and ok_grp_r
    status = (
        f"adb_L={ok_adb_l} adb_R={ok_adb_r} daemon={ok_d} "
        f"group_L={ok_grp_l} group_R={ok_grp_r} errs={len(errs)}"
    )
    if healthy:
        if errs:
            log(f"OK(warn) {status}")
            for e in errs:
                log(f"  log: {e}")
        else:
            log(f"OK {status}")
        return 0

    log(f"WARN {status}")
    for e in errs:
        log(f"  log: {e}")

    actions = heal(ok_grp_l, ok_grp_r)
    if actions:
        log(f"HEAL done: {','.join(actions)}")
        ok_adb_l = adb_ok(LEFT)
        ok_adb_r = adb_ok(RIGHT)
        ok_d = daemon_running()
        ok_grp_l = in_group(LEFT) if ok_adb_l else False
        ok_grp_r = in_group(RIGHT) if ok_adb_r else False
        if ok_adb_l and ok_adb_r and ok_d and ok_grp_l and ok_grp_r:
            log("RECOVERED after heal")
            return 0

    log("FAIL still unhealthy after heal")
    return 1


if __name__ == "__main__":
    sys.exit(main())
