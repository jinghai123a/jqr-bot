#!/usr/bin/env python3
import os
import time
import paramiko

H, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(ssh, cmd, t=60):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(H, username="root", password=PW, timeout=30)
sftp = ssh.open_sftp()
sftp.put(os.path.join(BASE, "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
sftp.put(os.path.join(BASE, "config", "pinned-coords.json"), f"{R}/config/pinned-coords.json")
sftp.put(os.path.join(BASE, "scripts", "_e2e_balance_once.py"), f"{R}/scripts/_e2e_balance_once.py")
sftp.put(os.path.join(BASE, "scripts", "_e2e_plus_daemon.py"), f"{R}/scripts/_e2e_plus_daemon.py")
for doc in ("固定-公告顺序与内容文本.md", "固定-全局线程与资源分发.md"):
    sftp.put(os.path.join(BASE, "docs", doc), f"{R}/docs/{doc}")
sftp.put(os.path.join(BASE, "scripts", "_verify_round_sequence.py"), f"{R}/scripts/_verify_round_sequence.py")
sftp.close()
print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -6"))
time.sleep(12)
ssh.close()
print("done")
