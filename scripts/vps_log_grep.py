#!/usr/bin/env python3
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
cmd = r"""python3 - <<'PY'
import re
path = "/home/bot/55chat-bot/logs/bot.log"
keys = ("探针拦截", "公平队列", "PROBE", "拦截", "已回复", "发送成功", "扣1")
with open(path, encoding="utf-8", errors="replace") as f:
    lines = f.readlines()
for line in lines[-400:]:
    if any(k in line for k in keys):
        print(line.rstrip())
PY"""
_, o, e = ssh.exec_command(cmd, timeout=60)
print(o.read().decode("utf-8", errors="replace"))
err = e.read().decode("utf-8", errors="replace")
if err.strip():
    print("ERR:", err)
ssh.close()
