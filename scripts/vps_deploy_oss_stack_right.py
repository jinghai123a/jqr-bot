#!/usr/bin/env python3
"""上传并执行右机 OSS 栈部署（不启动 bot）。"""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "46.183.27.174"
USER = "root"
PASSWORD = "Aa112211@@785*"
REMOTE = "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 300) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (f"\n[stderr]\n{err}" if err.strip() else "")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)

    # 确保 bot 仍暂停
    print(run(ssh, "systemctl is-active 55chat-bot.service 2>/dev/null || echo stopped"))
    print(run(ssh, "pkill -9 -f bot_55chat_daemon.py 2>/dev/null; pgrep -af bot_55chat_daemon || echo BOT_STOPPED"))

    sftp = ssh.open_sftp()
    local = ROOT / "scripts" / "deploy-listener-oss-stack.sh"
    remote = f"{REMOTE}/scripts/deploy-listener-oss-stack.sh"
    data = local.read_bytes().replace(b"\r\n", b"\n")
    with sftp.file(remote, "wb") as f:
        f.write(data)
    sftp.close()
    ssh.exec_command(f"chmod +x {remote}")

    print("=== deploy oss stack on right ===")
    print(run(ssh, f"bash {remote}", timeout=300))
    ssh.close()


if __name__ == "__main__":
    main()
