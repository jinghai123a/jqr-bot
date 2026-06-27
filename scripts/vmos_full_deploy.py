#!/usr/bin/env python3
"""上传 bot + VMOS 脚本到 VPS 并执行 vmos-cloud-bootstrap。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

HOST = "46.183.27.174"
USER = "root"
PASSWORD = "Aa112211@@785*"
REMOTE = "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]

UPLOAD = [
    "bot_55chat_daemon.py",
    "scripts/vmos_api_client.py",
    "scripts/vmos-refresh-tunnels.py",
    "scripts/setup-cloud-clipboard.sh",
    "scripts/vmos-dual-watchdog.sh",
    "scripts/vmos-cloud-bootstrap.py",
]


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 600) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (f"\n[stderr]\n{err}" if err.strip() else "")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)

    sftp = ssh.open_sftp()
    for rel in UPLOAD:
        local = ROOT / rel
        remote = f"{REMOTE}/{rel.replace(chr(92), '/')}"
        with sftp.file(remote, "wb") as f:
            f.write(local.read_bytes())
        if rel.endswith(".sh") or rel.endswith(".py"):
            ssh.exec_command(f"chmod +x {remote}")
    sftp.close()
    print("uploaded", len(UPLOAD), "files")

    print(run(ssh, f"python3 -m py_compile {REMOTE}/bot_55chat_daemon.py {REMOTE}/scripts/vmos_api_client.py"))
    print(run(ssh, f"python3 {REMOTE}/scripts/vmos-cloud-bootstrap.py", timeout=900))
    time.sleep(5)
    print(run(ssh, f"tail -n 35 {REMOTE}/logs/bot.log"))
    ssh.close()


if __name__ == "__main__":
    main()
