#!/usr/bin/env python3
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
cmd = r"""python3 - <<'PY'
path = "/home/bot/55chat-bot/logs/bot.log"
keys = ("探针拦截", "公平队列", "已回复", "发送完成", "PROBE", "重复", "qwer", " probe ", "UID-TEST", "拦截")
lines = open(path, encoding="utf-8", errors="replace").readlines()[-500:]
for ln in lines:
    if any(k in ln for k in keys):
        print(ln.rstrip())
PY"""
_, o, _ = ssh.exec_command(cmd, timeout=60)
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
