#!/usr/bin/env python3
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
cmd = r"""python3 - <<'PY'
import re
from collections import defaultdict
path = "/home/bot/55chat-bot/logs/bot.log"
lines = open(path, encoding="utf-8", errors="replace").readlines()
print("log tail time:", lines[-1][:30] if lines else "?")
print("log lines:", len(lines))
# 06-24 全部
d24 = [ln for ln in lines if "2026-06-24" in ln]
print("06-24 lines:", len(d24))
for ln in d24[-50:]:
    if any(k in ln for k in ("探针", "公平", "已回复", "发送完成", "拦截", "bal", "扣", "RESOLVE")):
        print(ln.rstrip())
# 找同一分钟内 >=3 条 user/bal 回复
ts_re = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
buckets = defaultdict(list)
for ln in lines[-15000:]:
    if "发送完成" not in ln and "已回复" not in ln and "[PROBE]" not in ln:
        continue
    if "bal" not in ln and "余额" not in ln and "用户" not in ln and "user " not in ln.lower():
        continue
    m = ts_re.search(ln)
    if m:
        buckets[m.group(1)].append(ln.rstrip())
print("=== minutes with >=3 balance-like sends ===")
for k in sorted(buckets):
    if len(buckets[k]) >= 3:
        print(k, len(buckets[k]))
        for ln in buckets[k][:5]:
            print(" ", ln[:120])
PY"""
_, o, _ = ssh.exec_command(cmd, timeout=90)
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
