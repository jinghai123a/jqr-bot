#!/usr/bin/env python3
"""上传 cloud_dual_watch 并安装 VPS crontab（每 5 分钟）。"""
from __future__ import annotations

import os
import time

import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
BASE = os.path.dirname(os.path.abspath(__file__))
CRON_LINE = (
    f"*/5 * * * * flock -n /tmp/cloud_dual_watch.lock "
    f"python3 {R}/scripts/cloud_dual_watch.py "
    f">> {R}/logs/cloud-watch-cron.log 2>&1"
)


def run(ssh: paramiko.SSHClient, cmd: str, t: int = 90) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=30)
    sftp = ssh.open_sftp()
    sftp.put(os.path.join(BASE, "cloud_dual_watch.py"), f"{R}/scripts/cloud_dual_watch.py")
    sftp.put(os.path.join(BASE, "_watch_heal_left_group.py"), f"{R}/scripts/_watch_heal_left_group.py")
    sftp.close()

    run(ssh, f"mkdir -p {R}/logs && chmod +x {R}/scripts/cloud_dual_watch.py", 15)

    cur = run(ssh, "crontab -l 2>/dev/null || true", 15)
    lines = [ln for ln in cur.splitlines() if "cloud_dual_watch" not in ln and ln.strip()]
    lines.append(CRON_LINE)
    payload = "\n".join(lines) + "\n"
    run(ssh, f"crontab - <<'EOF'\n{payload}EOF", 15)

    print("=== crontab ===")
    print(run(ssh, "crontab -l | grep cloud_dual_watch", 15))
    print("=== first run ===")
    print(run(ssh, f"python3 {R}/scripts/cloud_dual_watch.py; echo EXIT:$?", 120))
    print("=== tail watch log ===")
    print(run(ssh, f"tail -n 8 {R}/logs/cloud-watch.log 2>/dev/null || true", 15))
    ssh.close()
    print("done")


if __name__ == "__main__":
    main()
