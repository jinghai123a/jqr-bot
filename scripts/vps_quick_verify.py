#!/usr/bin/env python3
"""快速验证 VPS：heapq 修复、回群、探针 e2e。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent

VPS = ("46.183.27.174", "root", "Aa112211@@785*")
REMOTE = "/home/bot/55chat-bot"


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (f"\nSTDERR:\n{err}" if err.strip() else "")


def main() -> None:
    host, user, password = VPS
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)

    sftp = ssh.open_sftp()
    with sftp.file(f"{REMOTE}/bot_55chat_daemon.py", "wb") as f:
        f.write((ROOT / "bot_55chat_daemon.py").read_bytes())
    sftp.close()
    print("Uploaded daemon")

    print("=== heapq import check ===")
    print(run(ssh, f"grep -n '^import heapq' {REMOTE}/bot_55chat_daemon.py || echo MISSING"))

    print("=== restart daemon ===")
    print(run(ssh, f"bash {REMOTE}/scripts/restart-55chat-bot.sh", timeout=60))
    time.sleep(4)

    print("=== recover group ===")
    print(
        run(
            ssh,
            f"cd {REMOTE} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group 127.0.0.1:54936",
        )
    )

    print("=== probe e2e curl ===")
    ts = int(time.time() * 1000)
    payload = json.dumps({"sender": "探针测试", "command": "扣1", "package": "wuwu.client", "ts": ts})
    print(
        run(
            ssh,
            f"""cd {REMOTE} && curl -fsS -X POST http://127.0.0.1:3910/event \\
  -H 'Content-Type: application/json' \\
  -d '{payload}'""",
        )
    )
    time.sleep(4)

    print("=== recent log (probe + send + heapq) ===")
    print(
        run(
            ssh,
            f"tail -n 80 {REMOTE}/logs/bot.log | grep -E '探针拦截|PROBE|heapq|发送完成|发送失败' | tail -20",
        )
    )
    ssh.close()


if __name__ == "__main__":
    main()
