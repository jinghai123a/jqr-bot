#!/usr/bin/env python3
"""上传右机所需文件并执行 deploy-right-listener-now.sh（不含左机）。"""
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
    "scripts/deploy-listener-oss-stack.sh",
    "scripts/deploy-right-listener-now.sh",
    "scripts/probe-55m-commit-content.py",
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
        data = local.read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(remote, "wb") as f:
            f.write(data)
        if rel.endswith(".sh"):
            ssh.exec_command(f"chmod +x {remote}")
    sftp.close()
    print("uploaded", len(UPLOAD), "files")

    print("=== deploy right listener only ===")
    print(run(ssh, f"bash {REMOTE}/scripts/deploy-right-listener-now.sh", timeout=300))
    time.sleep(2)
    print("=== commit-content probe ===")
    print(run(ssh, f"cd {REMOTE} && python3 scripts/probe-55m-commit-content.py --serial 127.0.0.1:54936", timeout=90))
    print("=== ime-bench (text send path) ===")
    print(run(
        ssh,
        f"cd {REMOTE} && python3 bot_55chat_daemon.py --ime-bench 127.0.0.1:54936 2>&1 | tail -30",
        timeout=120,
    ))
    ssh.close()


if __name__ == "__main__":
    main()
