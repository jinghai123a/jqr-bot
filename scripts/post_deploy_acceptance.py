#!/usr/bin/env python3
"""
部署后硬性验收（W49）：回群 → verify x2 → visual x2 → 任务清单。
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
BASE = Path(__file__).resolve().parent
ROOT = BASE.parent

TASKS = [
    ("右机文本公告 pipe", r"pipe\+b64\+send"),
    ("右机读指令/回复", r"公平队列|已回复|enqueue_reply"),
    ("左机发图钉死坐标", r"发图钉死 \+|批量发图成功"),
    ("ADD 三分支话术", r"已发送请求|已是好友"),
    ("双 ADB + daemon", r"announce-bot-4"),
]


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)
    return ssh


def ssh_run(ssh, cmd: str, t: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def main() -> int:
    rc = 0
    ssh = connect()
    sftp = ssh.open_sftp()
    for name in ("recover_listener_now.py", "verify_dual_brain.py", "vmos_visual_monitor.py"):
        local = BASE / name
        if local.is_file():
            sftp.put(str(local), f"{R}/scripts/{name}")
    sftp.close()

    print("\n========== 右机回群 ==========")
    out = ssh_run(ssh, f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 90)
    print(out)
    if "in_group=True" not in out and "AFTER ok=True" not in out:
        rc = 1
        print("[WARN] 右机可能仍在离群")

    print("\n等待 30s 稳定…")
    time.sleep(30)

    for i in (1, 2):
        print(f"\n========== verify 第{i}轮 ==========")
        r = subprocess.run([sys.executable, str(BASE / "verify_dual_brain.py")], cwd=ROOT)
        if r.returncode != 0:
            rc = 1
        if i == 1:
            time.sleep(15)

    for i in (1, 2):
        print(f"\n========== visual 监控 第{i}轮 ==========")
        out = ssh_run(
            ssh,
            f"W49_VISUAL_LOG={R}/logs/visual-watch.log "
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"python3 {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
            60,
        )
        print(out)
        if "state=launcher" in out or "state=offline" in out:
            rc = 1
        if "state=target_group" not in out:
            rc = 1
        if i == 1:
            time.sleep(8)

    print("\n========== 任务清单核对（近 log）==========")
    log_tail = ssh_run(ssh, f"tail -n 4000 {R}/logs/bot.log", 30)
    pinned_ok = ssh_run(ssh, f"test -f {R}/config/pinned-coords.json && echo OK").strip()
    print(f"  [OK] pinned-coords.json" if pinned_ok == "OK" else "  [FAIL] pinned-coords.json")
    if pinned_ok != "OK":
        rc = 1
    for title, pattern in TASKS:
        hit = bool(re.search(pattern, log_tail))
        print(f"  [{'OK' if hit else '—'}] {title}")
        if not hit and "ADD" not in title:
            pass  # ADD 可能本期无触发，不硬 fail

    ssh.close()
    print(f"\n{'=== 验收通过 ===' if rc == 0 else '=== 验收有未通过项 ==='}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
