#!/usr/bin/env python3
import os
import time
import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"
base = os.path.dirname(os.path.abspath(__file__))


def run(ssh, cmd, t=120):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=30)
sftp = ssh.open_sftp()
sftp.put(os.path.join(base, "_patch_finance_bots.py"), f"{R}/scripts/_patch_finance_bots.py")
sftp.close()

print(run(ssh, f"python3 {R}/scripts/_patch_finance_bots.py"))
print(run(ssh, "adb devices -l | grep -E '52718|60478'"))
print("=== restart bot ===")
print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -12"))
time.sleep(20)
print(run(ssh, f"tail -60 {R}/logs/bot.log | grep -E 'DEPLOY|LISTENER|CLICKER|编排|sender|listener|target_group|ERROR|recover|苍井' | tail -30"))
ssh.close()
