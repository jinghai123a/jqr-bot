#!/usr/bin/env python3
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
cmd = r"""python3 - <<'PY'
import re
from collections import defaultdict
path = "/home/bot/55chat-bot/logs/bot.log"
# 精确匹配日志时间 03:20（非 20:03:20）
ts_re = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
want = ("03:19", "03:20", "03:21", "03:22")
keys = (
    "探针拦截", "公平队列", "PROBE", "拦截", "已回复", "发送成功", "发送完成",
    "重复指令", "RESOLVE", "认人", "enqueue", "bal ", "扣", " user ",
)
lines_all = open(path, encoding="utf-8", errors="replace").readlines()
matched = []
for ln in lines_all:
    m = ts_re.search(ln)
    if not m:
        continue
    t = m.group(1)
    if not any(f" {h}" in t for h in want):
        continue
    if any(k in ln for k in keys) or " 1 " in ln or "] 1" in ln:
        matched.append(ln.rstrip())
# 若没命中，看最近 06-24 凌晨
if not matched:
    for ln in lines_all[-3000:]:
        if "2026-06-24 03:" in ln and any(k in ln for k in keys):
            matched.append(ln.rstrip())
if not matched:
    # 最近 06-23 03:
    for ln in lines_all:
        if "2026-06-23 03:" in ln and any(k in ln for k in keys):
            matched.append(ln.rstrip())
print("=== matched", len(matched), "lines ===")
for ln in matched[-80:]:
    print(ln)
# 统计 03:20 分钟内发送完成
sends = defaultdict(int)
for ln in matched:
    if "发送完成" in ln or "已回复" in ln or "[PROBE]" in ln:
        t = ts_re.search(ln)
        if t:
            minute = t.group(1)[:16]
            sends[minute] += 1
print("=== send/reply per minute ===")
for k in sorted(sends):
    print(k, sends[k])
PY"""
_, o, e = ssh.exec_command(cmd, timeout=90)
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
