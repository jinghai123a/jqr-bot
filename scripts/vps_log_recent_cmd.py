#!/usr/bin/env python3
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
cmd = r"""python3 - <<'PY'
import re
from datetime import datetime
path = "/home/bot/55chat-bot/logs/bot.log"
lines = open(path, encoding="utf-8", errors="replace").readlines()
# 最近 5000 行里找 扣1/1 相关
recent = lines[-8000:]
keys_cmd = ("探针拦截", "公平队列", "PROBE", "拦截[", "已回复", "发送完成", "发送成功", "重复指令", "RESOLVE_CMD", "认人失败", "认人+")
for ln in recent:
    if not any(k in ln for k in keys_cmd):
        continue
    # 扣1 /  1 / bal
    if any(x in ln for x in ("扣1", " cmd=1", "] 1", " command=1", " bal ", "余额", "PROBE")):
        print(ln.rstrip())
print("--- tail 30 any intercept ---")
for ln in recent[-2000:]:
    if "探针拦截" in ln or "公平队列" in ln or "[PROBE]" in ln or "[ADB] 已回复" in ln:
        print(ln.rstrip())
PY"""
_, o, _ = ssh.exec_command(cmd, timeout=90)
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
