#!/usr/bin/env python3
"""
发现问题 → 修复 → 再验，直到通过才 exit 0。
禁止把未修复状态报给用户。
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]
MAX_ROUNDS = 8
PASS_STREAK = 2


def connect():
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    return s


def run(ssh, cmd: str, t: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def upload_core(ssh) -> None:
    sftp = ssh.open_sftp()
    base = ROOT / "scripts"
    for name in (
        "recover_listener_now.py",
        "confirm_e2e.py",
        "verify_dual_brain.py",
        "vmos_visual_monitor.py",
    ):
        p = base / name
        if p.is_file():
            sftp.put(str(p), f"{R}/scripts/{name}")
    sftp.put(str(ROOT / "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
    sftp.close()


def listener_in_group(ssh) -> bool:
    out = run(
        ssh,
        f"""python3 - <<'PY'
import os, sys
sys.path.insert(0, "{R}")
os.chdir("{R}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="127.0.0.1:60478"
bot={{"id":"bot-4","associatedGroup":"苍井空测试"}}
root=d.ui_hierarchy(serial)
ok=d.listener_in_group_for_send(root, bot, serial)
act=d.is_group_chat_activity(serial)
print("OK" if ok else "NO", "activity="+str(act))
PY""",
    )
    return "OK" in out.splitlines()[-1] if out.strip() else False


def fix_listener(ssh) -> str:
    return run(ssh, f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 120)


def restart_daemon_once(ssh) -> None:
    run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -3", 120)
    time.sleep(18)


def local_confirm() -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "confirm_e2e.py")],
        cwd=ROOT,
    ).returncode


def recent_pipe(ssh) -> bool:
    out = run(ssh, f"grep 'pipe+b64+send' {R}/logs/bot.log | tail -1")
    if not out.strip():
        return False
    m = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", out)
    if not m:
        return True
    from datetime import datetime, timezone

    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age < 600


def main() -> int:
    ssh = connect()
    upload_core(ssh)
    print("[fix-loop] 已上传代码（不重启 daemon，避免把右机打出群）")

    streak = 0
    for rnd in range(1, MAX_ROUNDS + 1):
        print(f"\n========== 轮次 {rnd}/{MAX_ROUNDS} ==========")
        if not listener_in_group(ssh):
            print("[fix] 右机不在群 → recover")
            print(fix_listener(ssh))
            time.sleep(8)
            if not listener_in_group(ssh):
                print("[fix] 仍不在群 → 再 recover")
                print(fix_listener(ssh))
                time.sleep(8)
        else:
            print("[check] 右机已在群")

        ssh.close()
        rc = local_confirm()
        ssh = connect()

        if rc == 0:
            streak += 1
            print(f"[pass] confirm_e2e 通过 ({streak}/{PASS_STREAK})")
            if streak >= PASS_STREAK:
                print("\n=== 闭环完成：连续两次 e2e 全过 ===")
                ssh.close()
                return 0
        else:
            streak = 0
            print("[fail] confirm_e2e 未过，继续修复…")
            if not recent_pipe(ssh):
                print("[fix] 近10min 无公告 pipe，尝试 recover 后等公告线程…")
                print(fix_listener(ssh))
                time.sleep(20)
        time.sleep(10)

    ssh.close()
    print("\n=== 闭环失败：已达最大轮次，仍有问题 ===")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "confirm_e2e.py")], cwd=ROOT)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
