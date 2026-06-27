#!/usr/bin/env python3
"""全链路实机验收：扣1 入队发送 + 左机发图探针 + verify。"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
RIGHT = "127.0.0.1:60478"
LEFT = "localhost:56121"
LOG = f"{R}/logs/bot.log"
BASE = os.path.dirname(os.path.abspath(__file__))


def run(ssh: paramiko.SSHClient, cmd: str, t: int = 90) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def tail_grep(ssh: paramiko.SSHClient, pattern: str, n: int = 20) -> list[str]:
    raw = run(ssh, f"tail -n 1200 {LOG}")
    rx = re.compile(pattern)
    return [ln for ln in raw.splitlines() if rx.search(ln)][-n:]


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username="root", password=PW, timeout=30)
    print(f"=== E2E UTC {datetime.now(timezone.utc).isoformat()} ===\n")
    fails = 0

    adb = run(ssh, "adb devices -l")
    ok_adb = "60478" in adb and "56121" in adb
    print(f"[{'PASS' if ok_adb else 'FAIL'}] 双机 ADB online")
    fails += 0 if ok_adb else 1

    for ser, label in ((RIGHT, "right"), (LEFT, "left")):
        act = run(ssh, f'adb -s {ser} shell "dumpsys window 2>/dev/null | grep mCurrentFocus | head -1"', 25)
        in_group = "GroupChatActivity" in act
        print(f"[{'PASS' if in_group else 'FAIL'}] {label} 在群聊")
        fails += 0 if in_group else 1

    # 扣1：handle_command + dispatch（探针关闭时的真实发送链）
    sftp = ssh.open_sftp()
    remote_py = f"{R}/scripts/_e2e_balance_once.py"
    sftp.put(os.path.join(BASE, "_e2e_balance_once.py"), remote_py)
    sftp.close()
    bal_out = run(ssh, f"cd {R} && python3 scripts/_e2e_balance_once.py", 90)
    got_bal = "ENQUEUE True" in bal_out and "NO_REPLY" not in bal_out
    time.sleep(2.5)
    send_ln = tail_grep(ssh, r"已回复|发送完成|积分：|用户：\[qwer\]")
    print(f"[{'PASS' if got_bal else 'FAIL'}] 扣1 入队+发送")
    print("  ", bal_out.strip().splitlines()[-1] if bal_out.strip() else "(empty)")
    fails += 0 if got_bal else 1

    # 左机 + 菜单（走 daemon 真实逻辑，禁止裸 tap 误判）
    sftp = ssh.open_sftp()
    sftp.put(os.path.join(BASE, "_e2e_plus_daemon.py"), f"{R}/scripts/_e2e_plus_daemon.py")
    sftp.close()
    plus_out = run(ssh, f"cd {R} && python3 scripts/_e2e_plus_daemon.py", 120)
    attach_ok = "attach_menu True" in plus_out
    print(f"[{'PASS' if attach_ok else 'FAIL'}] 左机 daemon 点+ 出附件栏")
    if not attach_ok:
        print("  ", plus_out.strip().splitlines()[-3:] if plus_out.strip() else "(empty)")
    fails += 0 if attach_ok else 1

    ssh.close()
    print(f"\n=== {'PASS' if fails == 0 else f'FAIL ({fails})'} ===")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
