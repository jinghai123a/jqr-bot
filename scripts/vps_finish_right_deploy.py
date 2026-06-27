#!/usr/bin/env python3
"""完成右机部署：启面板 API + OSS 栈 + bot + 测试。"""
from __future__ import annotations

import time

import paramiko

HOST = "46.183.27.174"
USER = "root"
PASSWORD = "Aa112211@@785*"
ROOT = "/home/bot/55chat-bot"


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 180) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (f"\n{err}" if err.strip() else "")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)

    steps = [
        ("panel check", f"ls -la {ROOT}/dist/server.cjs 2>/dev/null; pgrep -af node || true"),
        (
            "start panel",
            f"cd {ROOT} && "
            f"(curl -sf http://127.0.0.1:3000/api/bots >/dev/null || "
            f"(nohup npm run start >> logs/panel.log 2>&1 & sleep 5)) && "
            f"curl -s -o /dev/null -w 'panel_http:%{{http_code}}' http://127.0.0.1:3000/api/bots",
        ),
        (
            "patch env",
            f"""ENV={ROOT}/config/bot-start.env
for kv in BOT_CLICKER_OPTIONAL=1 BOT_LISTENER_STAY_IN_GROUP=1 BOT_PROBE_ENABLED=0; do
  k=${{kv%%=*}}; v=${{kv#*=}}
  grep -q "^$k=" "$ENV" && sed -i "s/^$k=.*/$k=$v/" "$ENV" || echo "$k=$v" >>"$ENV"
done
grep -E 'BOT_CLICKER_OPTIONAL|BOT_LISTENER_STAY' "$ENV"
""",
        ),
        ("tunnel right", f"bash {ROOT}/scripts/tunnel-right.sh 2>&1 | tail -8"),
        ("oss stack", f"bash {ROOT}/scripts/deploy-listener-oss-stack.sh 2>&1 | tail -25"),
        ("restart bot", f"bash {ROOT}/scripts/restart-55chat-bot.sh 2>&1"),
    ]
    for name, cmd in steps:
        print(f"\n=== {name} ===")
        print(run(ssh, cmd))

    time.sleep(6)
    print("\n=== bot log ===")
    print(run(ssh, f"tail -40 {ROOT}/logs/bot.log"))

    print("\n=== recover-group ===")
    print(
        run(
            ssh,
            f"cd {ROOT} && BOT_ALLOW_LISTENER_NAV=1 "
            f"python3 bot_55chat_daemon.py --recover-group 127.0.0.1:54936",
        )
    )

    print("\n=== ime-bench ===")
    print(
        run(
            ssh,
            f"cd {ROOT} && python3 bot_55chat_daemon.py --ime-bench 127.0.0.1:54936 2>&1 | tail -30",
            timeout=120,
        )
    )

    print("\n=== commit probe ===")
    print(
        run(
            ssh,
            f"cd {ROOT} && python3 scripts/probe-55m-commit-content.py --serial 127.0.0.1:54936",
            timeout=90,
        )
    )
    ssh.close()


if __name__ == "__main__":
    main()
