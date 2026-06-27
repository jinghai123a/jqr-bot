#!/usr/bin/env python3
import json
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)

patch = r"""
from pathlib import Path
import json, re

# finance.db is JSON blob
p = Path('/home/bot/55chat-bot/finance.db')
raw = p.read_text(encoding='utf-8', errors='replace')
if '58851' in raw:
    new = raw.replace('127.0.0.1:58851', '127.0.0.1:52840')
    p.write_text(new, encoding='utf-8')
    print('finance.db patched')

env = Path('/home/bot/55chat-bot/.env')
if env.exists():
    t = env.read_text(encoding='utf-8')
    t2 = re.sub(r'BOT_CLICKER_ADB_PORT=58851', 'BOT_CLICKER_ADB_PORT=52840', t)
    if t2 != t:
        env.write_text(t2, encoding='utf-8')
        print('.env patched')
"""
_, o, e = ssh.exec_command(f"python3 - <<'PY'\n{patch}\nPY", timeout=30)
print(o.read().decode())
print(e.read().decode())

_, o, _ = ssh.exec_command(
    "curl -s http://127.0.0.1:3000/api/bots | python3 -c \"import sys,json;print([b.get('adbHost') for b in json.load(sys.stdin) if b.get('id')=='bot-3'])\"",
    timeout=20,
)
print("api bot-3 adbHost:", o.read().decode())

# restart node server to reload bots?
ssh.exec_command("pkill -f 'node dist/server'")
time.sleep(2)
ssh.exec_command("cd /home/bot/55chat-bot && nohup node dist/server.cjs >> logs/server.log 2>&1 &")
time.sleep(4)

_, o, _ = ssh.exec_command(
    "curl -s http://127.0.0.1:3000/api/bots | python3 -c \"import sys,json;print([b for b in json.load(sys.stdin) if b.get('id')=='bot-3'])\"",
    timeout=20,
)
print("after restart:", o.read().decode())

ssh.exec_command("pkill -f bot_55chat_daemon.py")
time.sleep(2)
_, o, _ = ssh.exec_command("bash /home/bot/55chat-bot/scripts/restart-55chat-bot.sh", timeout=90)
time.sleep(10)
_, o, _ = ssh.exec_command("grep -E 'DEPLOY LOCK|listener-bot|clicker-bot|大脑编排' /home/bot/55chat-bot/logs/bot.log | tail -8", timeout=20)
print(o.read().decode("utf-8", "replace"))
_, o, _ = ssh.exec_command("adb devices -l", timeout=15)
print(o.read().decode())
ssh.close()
