#!/usr/bin/env python3
import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
R = "/home/bot/55chat-bot"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=25)


def run(cmd, t=40):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


sections = [
    ("process", "pgrep -af 'dual-monitor-1h|bot_55chat_daemon'"),
    ("adb", "adb devices -l | grep -E '52718|60478'"),
    ("deploy", f"grep 'DEPLOY LOCK' {R}/logs/bot.log | tail -1"),
    ("monitor", f"tail -10 {R}/logs/dual-monitor-1h.log 2>/dev/null"),
    ("listener", f"grep -E 'listener-bot|sender-bot|target_group' {R}/logs/bot.log | tail -12"),
    ("clicker", f"grep -E 'clicker-bot|clicker-img' {R}/logs/bot.log | tail -8"),
    ("errors_1h", f"grep ERROR {R}/logs/bot.log | tail -5"),
    ("probe_right", f"adb -s 127.0.0.1:60478 shell dumpsys window | grep -E 'mCurrentFocus|wuwu' | head -3"),
    ("probe_left", f"adb -s 127.0.0.1:52718 shell dumpsys window | grep -E 'mCurrentFocus|wuwu' | head -3"),
]
for name, cmd in sections:
    print(f"=== {name} ===")
    print(run(cmd)[:2500])
    print()

ssh.close()
