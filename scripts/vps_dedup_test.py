#!/usr/bin/env python3
"""模拟连发扣1，验证只回复一次。"""
import json
import time

import paramiko

VPS = ("46.183.27.174", "root", "Aa112211@@785*")
REMOTE = "/home/bot/55chat-bot"


def run(ssh, cmd, t=120):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", errors="replace") + e.read().decode("utf-8", errors="replace")


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    host, user, password = VPS
    ssh.connect(host, username=user, password=password, timeout=30)

    print(run(ssh, f"grep -n '^import heapq' {REMOTE}/bot_55chat_daemon.py"))

    print("=== recover ===")
    print(run(ssh, f"cd {REMOTE} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group 127.0.0.1:54936"))

    print("=== burst 5x probe 扣1 ===")
    for i in range(5):
        payload = json.dumps(
            {"sender": "dedup_test", "command": "1", "package": "wuwu.client", "ts": int(time.time() * 1000) + i},
            ensure_ascii=False,
        )
        run(
            ssh,
            f"""cd {REMOTE} && curl -fsS -X POST http://127.0.0.1:3910/event -H 'Content-Type: application/json' -d '{payload}'""",
        )
        time.sleep(0.15)

    time.sleep(5)
    print("=== log since burst ===")
    print(
        run(
            ssh,
            f"""python3 - <<'PY'
import re
from datetime import datetime
path = "{REMOTE}/logs/bot.log"
keys = ("探针拦截", "重复指令", "PROBE", "已回复", "发送成功", "enqueue", "dedup_test", "heapq")
with open(path, encoding="utf-8", errors="replace") as f:
    lines = f.readlines()[-120:]
for line in lines:
    if any(k in line for k in keys):
        print(line.rstrip())
PY""",
        )
    )
    ssh.close()


if __name__ == "__main__":
    main()
