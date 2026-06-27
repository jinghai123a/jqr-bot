"""VPS local dual-cloud watch — ADB/group/daemon heal loop."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .checks import adb_online, daemon_running, in_group_chat

RunFn = Callable[[str, int], str]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _default_root() -> Path:
    return Path("/home/bot/55chat-bot")


def run_watch_cycle(
    root: Path | None = None,
    *,
    right_serial: str = "127.0.0.1:60478",
    left_serial: str = "localhost:56121",
    run_fn: RunFn | None = None,
    log_fn: Callable[[str], None] | None = None,
    acquire_lock: Callable[[], bool] | None = None,
) -> int:
    root = root or _default_root()
    log_path = root / "logs" / "cloud-watch.log"
    bot_log = root / "logs" / "bot.log"
    restart = root / "scripts" / "restart-55chat-bot.sh"
    tun_l = root / "scripts" / "tunnel-left.sh"
    tun_r = root / "scripts" / "tunnel-right.sh"

    def sh(cmd: str, t: int = 90) -> str:
        if run_fn:
            return run_fn(cmd, t)
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
            return (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            return "TIMEOUT"

    def log(msg: str) -> None:
        if log_fn:
            log_fn(msg)
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{_ts()}] {msg}\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
        print(line, end="")

    def recent_bot_errors() -> list[str]:
        if not bot_log.is_file():
            return []
        try:
            raw = bot_log.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
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
        if not adb_online(left_serial, sh) and tun_l.is_file():
            log("HEAL: 左机 ADB 离线 → tunnel-left")
            sh(f"bash {tun_l}", 120)
            actions.append("tunnel-left")
        if not adb_online(right_serial, sh) and tun_r.is_file():
            log("HEAL: 右机 ADB 离线 → tunnel-right")
            sh(f"bash {tun_r}", 120)
            actions.append("tunnel-right")
        if not daemon_running(sh) and restart.is_file():
            log("HEAL: daemon 不在 → restart-55chat-bot")
            sh(f"bash {restart}", 150)
            actions.append("restart-daemon")
        if (not group_l or not group_r) and (root / "scripts" / "_watch_heal_left_group.py").is_file():
            log("HEAL: 不在群 → ensure_clicker_in_group")
            sh(f"python3 {root}/scripts/_watch_heal_left_group.py", 120)
            actions.append("ensure-group")
        return actions

    if acquire_lock is not None:
        if not acquire_lock():
            print("skip: another watch running")
            return 0
    else:
        lock_path = Path("/tmp/cloud_dual_watch.lock")
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            print("skip: another watch running")
            return 0

    ok_adb_l = adb_online(left_serial, sh)
    ok_adb_r = adb_online(right_serial, sh)
    ok_d = daemon_running(sh)
    ok_grp_l = in_group_chat(left_serial, sh, left=True) if ok_adb_l else False
    ok_grp_r = in_group_chat(right_serial, sh, left=False) if ok_adb_r else False
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
        ok_adb_l = adb_online(left_serial, sh)
        ok_adb_r = adb_online(right_serial, sh)
        ok_d = daemon_running(sh)
        ok_grp_l = in_group_chat(left_serial, sh, left=True) if ok_adb_l else False
        ok_grp_r = in_group_chat(right_serial, sh, left=False) if ok_adb_r else False
        if ok_adb_l and ok_adb_r and ok_d and ok_grp_l and ok_grp_r:
            log("RECOVERED after heal")
            return 0

    log("FAIL still unhealthy after heal")
    return 1
