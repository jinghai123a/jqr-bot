#!/usr/bin/env python3
import os
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
sftp.put(os.path.join(base, "_fix_bot_ports.py"), f"{R}/scripts/_fix_bot_ports.py")
sftp.close()

print(run(ssh, f"python3 {R}/scripts/_fix_bot_ports.py"))
print(run(ssh, f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -5"))
print(run(ssh, f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -5"))
print(run(ssh, "adb devices -l | grep -E '60478|52718'"))
print("=== restart ===")
print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -18"))
run(ssh, "sleep 15")
print(run(ssh, f"tail -40 {R}/logs/bot.log | grep -E 'DEPLOY|LISTENER|CLICKER|编排|sender|listener|target_group|ERROR|UI发图' | tail -25"))
ssh.close()
