#!/usr/bin/env python3
"""修复：回调走 195.114.193.237；ADB 隧道仍用 VMOS API 返回的 SSH 主机。"""
from __future__ import annotations

import os
import time
import paramiko

HOST, USER, PW = "46.183.27.174", "root", "Aa112211@@785*"
DEDICATED = "195.114.193.237"
CALLBACK = f"http://{DEDICATED}:3000/api/vmos/callback"
R = "/home/bot/55chat-bot"

FIX = r'''
import json, re, subprocess
from pathlib import Path
R = Path("/home/bot/55chat-bot")

# fix vmos-pads.json if corrupted
pp = R / "config/vmos-pads.json"
raw = pp.read_text(encoding="utf-8").strip()
if raw.count("{") > 1 or "}\n{" in raw:
    # take first valid object block
    try:
        data = json.loads(raw.split("}\n")[0] + "}")
    except Exception:
        data = {
            "right": {"pad_code": "ATP6416I3I1E6KPM", "local_port": 60478, "match_android": 13},
            "left": {"pad_code": "APP5AU4BB269OR35", "local_port": 52718, "match_android": 15},
        }
else:
    data = json.loads(raw)
data.setdefault("right", {})["local_port"] = 60478
data.setdefault("left", {})["local_port"] = 52718
pp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("vmos-pads fixed")

# refresh tunnels from API (restores real SSH_HOST)
r = subprocess.run(
    ["python3", str(R / "scripts/vmos-refresh-tunnels.py"), "--reconnect"],
    cwd=str(R), capture_output=True, text=True, timeout=300,
)
print(r.stdout[-1500:] if r.stdout else "")
print(r.stderr[-500:] if r.stderr else "")
print("refresh exit", r.returncode)
'''


def run(ssh, cmd, t=120):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=30)
sftp = ssh.open_sftp()
with sftp.file(f"{R}/scripts/_fix_tunnels.py", "w") as f:
    f.write(FIX)
sftp.close()

print("=== fix pads + refresh tunnels ===")
print(run(ssh, f"python3 {R}/scripts/_fix_tunnels.py", t=300))

print("=== tunnel hosts ===")
print(run(ssh, f"grep -v PASS {R}/config/tunnel-left.env {R}/config/tunnel-right.env"))

print("=== adb ===")
print(run(ssh, "adb devices -l | grep -E '52718|60478'"))

print("=== restart panel (non-blocking) ===")
run(ssh, "pkill -f 'node dist/server' 2>/dev/null; sleep 1; true", t=15)
ssh.exec_command(f"cd {R} && nohup node dist/server.cjs >> logs/server.log 2>&1 &")
time.sleep(5)
print(run(ssh, f"pgrep -af 'node dist/server' | head -2", t=15))
print(run(ssh, f"curl -s -o /dev/null -w '%{{http_code}}' -X POST {CALLBACK} -H 'Content-Type: application/json' -d '{{\"taskBusinessType\":999}}'", t=15))
print(run(ssh, f"tail -1 {R}/logs/vmos-callback.log 2>/dev/null", t=15))

print("=== restart bot ===")
print(run(ssh, f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -12", t=90))
time.sleep(12)
print(run(ssh, f"tail -25 {R}/logs/bot.log | grep -E 'DEPLOY|LISTENER|CLICKER|ERROR|target_group' | tail -15", t=20))
ssh.close()
