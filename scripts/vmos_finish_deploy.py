#!/usr/bin/env python3
"""快速完成 bootstrap 剩余步骤（API busy 时跳过 refresh）。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import paramiko

HOST, USER, PASSWORD = "46.183.27.174", "root", "Aa112211@@785*"
REMOTE = "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]

FILES = [
    "bot_55chat_daemon.py",
    "scripts/vmos_api_client.py",
    "scripts/vmos-refresh-tunnels.py",
    "scripts/setup-cloud-clipboard.sh",
    "scripts/vmos-dual-watchdog.sh",
    "scripts/vmos-cloud-bootstrap.py",
]


def run(ssh, cmd, timeout=600):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    return out + (f"\n[stderr]\n{err}" if err.strip() else "")


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
    sftp = ssh.open_sftp()
    for rel in FILES:
        remote = f"{REMOTE}/{rel}"
        with sftp.file(remote, "wb") as f:
            f.write((ROOT / rel).read_bytes())
        if rel.endswith((".sh", ".py")):
            ssh.exec_command(f"chmod +x {remote}")
    sftp.close()

    steps = [
        f"grep BOT_CLICKER_ADB_PORT {REMOTE}/config/bot-start.env",
        f"bash {REMOTE}/scripts/reconnect-dual-adb.sh",
        f"bash {REMOTE}/scripts/setup-cloud-clipboard.sh",
        f"python3 {REMOTE}/scripts/vmos-cloud-bootstrap.py",
    ]
    for cmd in steps:
        print(f"\n>>> {cmd}\n")
        print(run(ssh, cmd, timeout=900))
        time.sleep(2)

    print(run(ssh, "adb devices -l; crontab -l; systemctl is-active vmos-dual-watchdog.timer"))
    print(run(ssh, f"tail -n 25 {REMOTE}/logs/bot.log"))
    ssh.close()


if __name__ == "__main__":
    main()
